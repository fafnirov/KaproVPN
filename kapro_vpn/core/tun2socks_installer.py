"""Downloads tun2socks (xjasonlyu/tun2socks) and the WinTUN driver DLL.

These two artefacts together let us tunnel all OS-level TCP/UDP traffic into
xray's SOCKS5 inbound, achieving feature parity with AmneziaVPN's TUN mode.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from . import paths

TUN2SOCKS_LATEST = "https://api.github.com/repos/xjasonlyu/tun2socks/releases/latest"
TUN2SOCKS_FALLBACK = (
    "https://github.com/xjasonlyu/tun2socks/releases/download/"
    "v2.6.0/tun2socks-windows-amd64.zip"
)
TUN2SOCKS_ASSET_MARKER = "windows-amd64"

WINTUN_URL = "https://www.wintun.net/builds/wintun-0.14.1.zip"
WINTUN_DLL_IN_ZIP = "wintun/bin/amd64/wintun.dll"

ProgressCb = Optional[Callable[[int, int], None]]


@dataclass
class ReleaseInfo:
    version: str
    url: str
    filename: str


def is_installed() -> bool:
    return paths.tun2socks_exe().is_file() and paths.wintun_dll().is_file()


def get_installed_version() -> Optional[str]:
    if not paths.tun2socks_exe().is_file():
        return None
    import subprocess
    try:
        proc = subprocess.run(
            [str(paths.tun2socks_exe()), "-version"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first = (proc.stdout or proc.stderr or "").splitlines()[0].strip() if (proc.stdout or proc.stderr) else ""
        return first or None
    except Exception:
        return None


def _fetch_tun2socks_release() -> ReleaseInfo:
    try:
        r = requests.get(TUN2SOCKS_LATEST, timeout=10)
        r.raise_for_status()
        data = r.json()
        version = data.get("tag_name", "unknown")
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if TUN2SOCKS_ASSET_MARKER in name and name.endswith(".zip"):
                return ReleaseInfo(
                    version=version,
                    url=asset["browser_download_url"],
                    filename=name,
                )
    except Exception:
        pass
    return ReleaseInfo(
        version="v2.6.0",
        url=TUN2SOCKS_FALLBACK,
        filename="tun2socks-windows-amd64.zip",
    )


def _download(url: str, progress: ProgressCb, total_offset: int = 0,
              attempts: int = 3) -> bytes:
    """Download to memory with per-chunk read timeout and retries.

    The tuple `timeout=(connect_s, read_s)` makes `requests` raise if any
    single chunk read stalls for more than `read_s` seconds, which is the
    failure mode we hit when GitHub's CDN goes silent under throttling.
    """
    last_err: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            buf = io.BytesIO()
            downloaded = 0
            with requests.get(url, stream=True, timeout=(10, 20)) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0))
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    buf.write(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(total_offset + downloaded, total_offset + total)
            return buf.getvalue()
        except (requests.exceptions.RequestException, OSError) as e:
            last_err = e
            if attempt < attempts - 1:
                continue
    raise RuntimeError(f"Не удалось скачать после {attempts} попыток: {last_err}")


def _install_tun2socks(progress: ProgressCb) -> None:
    release = _fetch_tun2socks_release()
    data = _download(release.url, progress)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        exe_member = next(
            (n for n in zf.namelist() if n.endswith("tun2socks-windows-amd64.exe")
             or n.endswith("tun2socks.exe")),
            None,
        )
        if not exe_member:
            # Some releases ship the bare binary without .exe extension
            exe_member = next(
                (n for n in zf.namelist() if "tun2socks" in n.lower() and not n.endswith("/")),
                None,
            )
        if not exe_member:
            raise RuntimeError("tun2socks binary not found in the archive")
        with zf.open(exe_member) as src:
            paths.tun2socks_exe().write_bytes(src.read())


def _install_wintun(progress: ProgressCb) -> None:
    data = _download(WINTUN_URL, progress)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Find amd64 DLL — exact path is wintun/bin/amd64/wintun.dll
        dll_member = next(
            (n for n in zf.namelist()
             if n.endswith("wintun.dll") and "amd64" in n),
            None,
        )
        if not dll_member:
            raise RuntimeError("wintun.dll (amd64) not found in the archive")
        with zf.open(dll_member) as src:
            paths.wintun_dll().write_bytes(src.read())


def download_and_install(progress: ProgressCb = None) -> None:
    """Install both tun2socks and wintun.dll."""
    if not paths.tun2socks_exe().is_file():
        _install_tun2socks(progress)
    if not paths.wintun_dll().is_file():
        _install_wintun(progress)


def ensure_installed(progress: ProgressCb = None) -> None:
    if not is_installed():
        download_and_install(progress)
