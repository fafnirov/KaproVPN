"""Windows route + DNS manipulation for TUN-mode setup.

Wraps the legacy `route` / `netsh` commands and the modern `Get-NetAdapter`
PowerShell cmdlet. All operations need admin privileges.

Session pattern: callers build up a list of routes/DNS changes through
RouteSession, then `restore()` undoes them all at disconnect (or atexit if
the app crashes).
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --- low-level shell wrappers ---------------------------------------------

def _run(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    proc = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _ps(script: str, timeout: float = 10.0) -> tuple[int, str, str]:
    """Run a single PowerShell command and return (rc, stdout, stderr)."""
    return _run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
    )


# --- discovery ------------------------------------------------------------

@dataclass
class InterfaceInfo:
    name: str       # User-facing alias, e.g. "Беспроводная сеть" or "tun0"
    index: int      # ifIndex
    gateway: str = ""  # IPv4 gateway, empty for TUN


def get_default_route_v4() -> Optional[InterfaceInfo]:
    """Find the IPv4 default-route interface BEFORE we add our TUN routes."""
    rc, out, err = _ps(
        "Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue "
        "| Sort-Object RouteMetric "
        "| Select-Object -First 1 -Property InterfaceAlias,InterfaceIndex,NextHop "
        "| ConvertTo-Json -Compress"
    )
    if rc != 0 or not out.strip():
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    return InterfaceInfo(
        name=str(data.get("InterfaceAlias", "")),
        index=int(data.get("InterfaceIndex", 0)),
        gateway=str(data.get("NextHop", "")),
    )


def find_interface_by_name(name: str, timeout: float = 8.0) -> Optional[InterfaceInfo]:
    """Poll Get-NetAdapter until an interface with the given alias appears.

    tun2socks creates the TUN asynchronously after launch, so we wait.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rc, out, err = _ps(
            f"Get-NetAdapter -Name '{name}' -ErrorAction SilentlyContinue "
            f"| Select-Object -Property Name,ifIndex,Status "
            f"| ConvertTo-Json -Compress"
        )
        if rc == 0 and out.strip():
            try:
                data = json.loads(out)
                return InterfaceInfo(name=data["Name"], index=int(data["ifIndex"]))
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.4)
    return None


def configure_tun_interface(iface: InterfaceInfo, address: str = "10.255.0.2",
                            mask: str = "255.255.255.0") -> None:
    """Give the TUN interface an IPv4 address and bring it up."""
    _run([
        "netsh", "interface", "ipv4", "set", "address",
        f"name={iface.name}", "source=static",
        f"addr={address}", f"mask={mask}",
    ])


def set_dns(iface_name: str, servers: list[str]) -> None:
    """Pin DNS servers on an interface (replaces DHCP-assigned ones)."""
    if not servers:
        return
    _run([
        "netsh", "interface", "ipv4", "set", "dns",
        f"name={iface_name}", "source=static", f"addr={servers[0]}",
        "register=primary", "validate=no",
    ])
    for s in servers[1:]:
        _run([
            "netsh", "interface", "ipv4", "add", "dns",
            f"name={iface_name}", f"addr={s}", "validate=no",
        ])


def reset_dns(iface_name: str) -> None:
    _run([
        "netsh", "interface", "ipv4", "set", "dns",
        f"name={iface_name}", "source=dhcp",
    ])


# --- route add/remove -----------------------------------------------------

def add_route(dest: str, mask: str, gateway: str, if_index: int,
              metric: int = 1) -> bool:
    rc, out, err = _run([
        "route", "add", dest, "mask", mask, gateway,
        "if", str(if_index), "metric", str(metric),
    ])
    return rc == 0


def delete_route(dest: str, mask: str, gateway: str = "") -> bool:
    args = ["route", "delete", dest, "mask", mask]
    if gateway:
        args.append(gateway)
    rc, out, err = _run(args)
    return rc == 0


# --- session --------------------------------------------------------------

@dataclass
class _DnsEntry:
    iface_name: str


@dataclass
class _RouteEntry:
    dest: str
    mask: str
    gateway: str


@dataclass
class RouteSession:
    """Tracks routes/DNS changes so they can all be undone on disconnect."""
    routes: list[_RouteEntry] = field(default_factory=list)
    dns_changed: list[_DnsEntry] = field(default_factory=list)

    def add_route(self, dest: str, mask: str, gateway: str, if_index: int,
                  metric: int = 1) -> bool:
        ok = add_route(dest, mask, gateway, if_index, metric)
        if ok:
            self.routes.append(_RouteEntry(dest, mask, gateway))
        return ok

    def set_dns(self, iface_name: str, servers: list[str]) -> None:
        set_dns(iface_name, servers)
        self.dns_changed.append(_DnsEntry(iface_name))

    def restore(self) -> None:
        for r in reversed(self.routes):
            try:
                delete_route(r.dest, r.mask, r.gateway)
            except Exception:
                pass
        self.routes.clear()
        for d in self.dns_changed:
            try:
                reset_dns(d.iface_name)
            except Exception:
                pass
        self.dns_changed.clear()
