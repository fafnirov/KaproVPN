r"""WireGuard via the official WireGuard for Windows service.

Why this exists separately from xray:

  Xray-core ships its own user-space WireGuard outbound (gVisor netstack).
  It works on paper, but in practice we hit a wall trying to make it pass
  real traffic from RU networks — the kind of intermittent silent failure
  that's untestable on a developer machine outside the affected region.

  The official WireGuard for Windows client uses tunnel.dll (a Go
  implementation) running as a Windows service, with WinTUN as the
  network driver. It's the upstream reference implementation, used by
  every popular Windows VPN GUI (Hiddify, Nekoray, NekoBox, etc).
  Reliability is on a different level.

So: instead of replicating WG inside our process, we drive the official
client via its CLI:

  wireguard.exe /installtunnelservice  <path-to-conf>
    → registers a Windows service named "WireGuardTunnel$<basename>"
    → service starts, creates the TUN interface, runs handshake,
      sets up routes per AllowedIPs

  wireguard.exe /uninstalltunnelservice <basename>
    → stops + removes the service, tears down interface and routes

Our config file lives at:
  %LOCALAPPDATA%\KaproVPN\wg\<name>.conf

Service basename = stem of that file = our chosen tunnel name.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import requests

from . import paths

# Default install path of WireGuard for Windows. Users who chose a custom
# install location can set $WIREGUARD_EXE in their environment.
DEFAULT_EXE = r"C:\Program Files\WireGuard\wireguard.exe"

# Pinned MSI version we know works with our orchestration. WireGuard for
# Windows is API-stable across versions but we pin to avoid an upstream
# breaking change silently breaking our users. Bump after manual smoke-test.
WIREGUARD_MSI_VERSION = "0.5.3"
WIREGUARD_MSI_FILENAME = f"wireguard-amd64-{WIREGUARD_MSI_VERSION}.msi"

# Upstream MSI URL — used as fallback if our mirror is unreachable.
WIREGUARD_MSI_UPSTREAM = (
    f"https://download.wireguard.com/windows-client/{WIREGUARD_MSI_FILENAME}"
)
# Our mirror (server-setup/sync-binaries.sh re-hosts the MSI). Primary
# because it's geographically closer + we control its uptime.
WIREGUARD_MSI_MIRROR = f"https://files.kaprovpn.pro/{WIREGUARD_MSI_FILENAME}"

DOWNLOAD_URL = WIREGUARD_MSI_UPSTREAM  # legacy alias, kept for callers

# Bypass system proxy on internal downloads — see xray_installer for
# full rationale (stale registry proxy from crashed HTTP-mode sessions).
_NO_PROXY = {"http": "", "https": ""}

# Hidden-subprocess flag — without it Windows pops a fleeting console
# window for every wireguard.exe call.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ProgressCb = Optional[Callable[[int, int], None]]


def wg_dir() -> Path:
    """Where our generated WG .conf files live."""
    p = paths.app_data_dir() / "wg"
    p.mkdir(parents=True, exist_ok=True)
    return p


def find_wireguard_exe() -> Optional[Path]:
    """Locate wireguard.exe. Returns None if WireGuard for Windows
    isn't installed.
    """
    if sys.platform != "win32":
        return None
    env_override = os.environ.get("WIREGUARD_EXE")
    if env_override and Path(env_override).is_file():
        return Path(env_override)
    if Path(DEFAULT_EXE).is_file():
        return Path(DEFAULT_EXE)
    found = shutil.which("wireguard.exe")
    if found:
        return Path(found)
    return None


def is_installed() -> bool:
    return find_wireguard_exe() is not None


# ---------------------------------------------------------------- silent install

def _download_msi(progress: ProgressCb = None) -> bytes:
    """Fetch the WireGuard MSI: mirror first, upstream fallback.

    Mirror is faster + more reliable from RU. Upstream is the safety
    net if our VPS is down. 2 attempts per source, 4 chances total.
    """
    last_err: Optional[Exception] = None
    for url in (WIREGUARD_MSI_MIRROR, WIREGUARD_MSI_UPSTREAM):
        for attempt in range(2):
            try:
                sink = io.BytesIO()
                downloaded = 0
                with requests.get(url, stream=True, timeout=(10, 30),
                                  proxies=_NO_PROXY) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length", 0))
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        sink.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, total)
                data = sink.getvalue()
                # Sanity: MSI is ~5-8 MB; anything tiny is a captive-
                # portal HTML or a broken truncated download.
                if len(data) < 500_000:
                    raise RuntimeError(
                        f"Suspiciously small download ({len(data)} B) — "
                        f"probably a 404 page or captive portal"
                    )
                return data
            except (requests.exceptions.RequestException, OSError, RuntimeError) as e:
                last_err = e
    raise RuntimeError(
        f"Не удалось скачать WireGuard MSI ни с зеркала, ни с upstream: {last_err}"
    )


def silent_install(progress: ProgressCb = None) -> None:
    """Download WireGuard for Windows MSI and install it silently.

    Requires admin (msiexec /i with /quiet on a system component needs
    elevation). Controller has already gated on admin.is_admin() before
    calling us, so this is safe.

    Side effect: registers WireGuard as a normal Windows program (shows
    up in Add/Remove Programs, Start Menu). KaproVPN doesn't uninstall
    it on its own removal — the user may use it for other tunnels.
    """
    if sys.platform != "win32":
        raise RuntimeError("WireGuard MSI install is Windows-only")

    raw = _download_msi(progress=progress)

    # Write the MSI to a temp file — msiexec needs a real path.
    fd, tmp_path = tempfile.mkstemp(
        suffix=".msi", prefix="kaprovpn-wg-",
    )
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)

    try:
        # /i  = install
        # /quiet  = no UI (also blocks reboot prompt — we use /norestart anyway)
        # /norestart = never reboot, even if MSI requests it
        # ACCEPTEULA=1 = pre-accept the EULA (so install doesn't block on it)
        proc = subprocess.run(
            ["msiexec", "/i", tmp_path, "/quiet", "/norestart", "ACCEPTEULA=1"],
            capture_output=True, timeout=180,
            creationflags=_NO_WINDOW,
        )
        if proc.returncode not in (0, 3010):
            # 3010 = "success, but a reboot is required". For WG, no
            # reboot is actually needed for the CLI to work; the service
            # subsystem is reachable without one.
            raise RuntimeError(
                f"msiexec вернул {proc.returncode}. "
                f"stderr: {(proc.stderr or b'').decode('utf-8', errors='replace')[:200]}"
            )
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # Sanity-check that the install actually landed.
    if not is_installed():
        raise RuntimeError(
            "MSI отработал без ошибки, но wireguard.exe всё равно не "
            "найден на диске. Возможно, антивирус помешал — попробуй "
            "временно выключить защиту реального времени и переподключиться."
        )


def ensure_installed(progress: ProgressCb = None) -> None:
    """Idempotent: install only if missing."""
    if is_installed():
        return
    silent_install(progress=progress)


def get_installed_version() -> Optional[str]:
    exe = find_wireguard_exe()
    if exe is None:
        return None
    # WireGuard for Windows doesn't expose --version cleanly, but the
    # binary's file-info has it. PowerShell one-liner gives a clean
    # string; cheap enough.
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"(Get-Item '{exe}').VersionInfo.ProductVersion"],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        return (proc.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------- naming

_TUNNEL_NAME_INVALID = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize_tunnel_name(name: str) -> str:
    """Make a name safe for use as a Windows-service component.

    Service names like "WireGuardTunnel$<name>" reject spaces and most
    punctuation. We strip down to [A-Za-z0-9_-] and prepend "KaproVPN-"
    so we can recognise our own tunnels in `services.msc` and clean
    them up safely without touching tunnels the user created via the
    WireGuard GUI directly.
    """
    cleaned = _TUNNEL_NAME_INVALID.sub("-", name).strip("-_")
    if not cleaned:
        cleaned = "tunnel"
    # Service-name + tunnel-name length cap is ~63 chars.
    return f"KaproVPN-{cleaned}"[:63]


def conf_path_for(tunnel_name: str) -> Path:
    return wg_dir() / f"{tunnel_name}.conf"


# ---------------------------------------------------------------- service ops

class WireGuardError(Exception):
    """Raised when wireguard.exe refuses an install/uninstall call."""


def install_tunnel(conf_text: str, tunnel_name: str) -> Path:
    """Write the .conf to disk and register it as a Windows service.

    Returns the path of the on-disk .conf (kept for the service to
    re-read on reboot). Caller is responsible for routes — WireGuard
    only handles the AllowedIPs-based defaults; KaproVPN's
    network_routes adds bypass entries on top.

    Raises WireGuardError on failure (missing WireGuard.exe, refused
    install, malformed config).
    """
    exe = find_wireguard_exe()
    if exe is None:
        raise WireGuardError(
            "WireGuard для Windows не установлен.\n"
            f"Скачай: {DOWNLOAD_URL}\n"
            "Поставь (10 МБ, ~30 секунд), потом снова жми «Подключить»."
        )

    conf_file = conf_path_for(tunnel_name)
    # Hardening: make sure no stale conf from a previous run with the
    # same tunnel name is hanging around — would silently get used.
    conf_file.write_text(conf_text, encoding="utf-8")

    # /installtunnelservice is the official, documented CLI verb.
    # It requires admin privileges; controller has already gated on
    # admin.is_admin() before calling us.
    proc = subprocess.run(
        [str(exe), "/installtunnelservice", str(conf_file)],
        capture_output=True, text=True, timeout=15,
        creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise WireGuardError(
            f"wireguard.exe вернул ошибку (rc={proc.returncode}):\n"
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    return conf_file


def uninstall_tunnel(tunnel_name: str) -> None:
    """Stop and remove the service. Best-effort — if it's already gone,
    we don't care.
    """
    exe = find_wireguard_exe()
    if exe is None:
        # Nothing to do — the service can't exist without the exe.
        return
    try:
        subprocess.run(
            [str(exe), "/uninstalltunnelservice", tunnel_name],
            capture_output=True, text=True, timeout=15,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    # Don't delete the .conf — keeps "what was the last config" intact
    # for the user to inspect if something went wrong.


def is_tunnel_active(tunnel_name: str) -> bool:
    """True if the Windows service for this tunnel is in Running state.

    Uses `sc query` rather than Get-Service to avoid the PowerShell
    startup cost on the hot path.
    """
    service_name = f"WireGuardTunnel${tunnel_name}"
    try:
        proc = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "RUNNING" in (proc.stdout or "")


def wait_for_tunnel_up(tunnel_name: str, timeout: float = 10.0) -> bool:
    """Block until the service reports RUNNING (or timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_tunnel_active(tunnel_name):
            return True
        time.sleep(0.3)
    return False


def list_kaprovpn_tunnels() -> list[str]:
    """Names of currently-installed KaproVPN tunnel services.

    Useful for startup cleanup — if a previous run crashed without
    uninstalling its tunnel, this lets us find and remove it before
    starting a new one.
    """
    try:
        proc = subprocess.run(
            ["sc", "query", "type=", "service", "state=", "all"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out = proc.stdout or ""
    # Lines look like "SERVICE_NAME: WireGuardTunnel$KaproVPN-foo"
    found = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("SERVICE_NAME:") and "WireGuardTunnel$KaproVPN-" in line:
            name = line.split("WireGuardTunnel$", 1)[1].strip()
            found.append(name)
    return found


def cleanup_orphan_tunnels() -> int:
    """Remove any leftover KaproVPN-* tunnels from prior crashed runs.

    Like the orphan-killer in main.py but for WireGuard services.
    Returns the count cleaned up.
    """
    orphans = list_kaprovpn_tunnels()
    for name in orphans:
        uninstall_tunnel(name)
    return len(orphans)
