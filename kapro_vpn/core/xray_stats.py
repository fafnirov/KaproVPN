"""Query Xray-core's runtime traffic stats via its built-in gRPC StatsService.

Xray exposes per-inbound / per-outbound byte counters when the config has
a `stats` block and an `api` inbound. We can read them out via the CLI
helper `xray api stats`, which prints JSON, so we don't have to bring in
a grpc Python dependency.

Subprocess overhead is ~50 ms on Windows — fine for once-per-second
polling, which is what the UI does.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from . import paths

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

API_LISTEN_HOST = "127.0.0.1"
API_LISTEN_PORT = 10085


@dataclass
class TrafficStats:
    """Cumulative byte counters for the proxy outbound at one point in time."""
    uplink_bytes: int = 0
    downlink_bytes: int = 0
    timestamp: float = 0.0

    def delta_rate(self, prev: "TrafficStats") -> tuple[float, float]:
        """(upload_bytes_per_sec, download_bytes_per_sec) since `prev`."""
        dt = self.timestamp - prev.timestamp
        if dt <= 0:
            return 0.0, 0.0
        up = max(0, self.uplink_bytes - prev.uplink_bytes) / dt
        down = max(0, self.downlink_bytes - prev.downlink_bytes) / dt
        return up, down


def query_stats() -> Optional[TrafficStats]:
    """Query Xray's StatsService for `outbound>>>proxy>>>traffic`.

    Returns None if xray isn't running, the API inbound isn't up, or the
    subprocess errors out — caller treats that as "no data yet".
    """
    exe = paths.xray_exe()
    if not exe.is_file():
        return None
    api_addr = f"{API_LISTEN_HOST}:{API_LISTEN_PORT}"
    try:
        result = subprocess.run(
            [str(exe), "api", "stats", f"-server={api_addr}", "-reset=false"],
            capture_output=True, text=True, timeout=2,
            creationflags=CREATE_NO_WINDOW,
            cwd=str(paths.xray_dir()),
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None

    stats = TrafficStats(timestamp=time.time())
    for entry in data.get("stat", []):
        name = entry.get("name", "")
        try:
            value = int(entry.get("value", 0))
        except (TypeError, ValueError):
            continue
        if name == "outbound>>>proxy>>>traffic>>>uplink":
            stats.uplink_bytes = value
        elif name == "outbound>>>proxy>>>traffic>>>downlink":
            stats.downlink_bytes = value
    return stats


def format_rate(bps: float) -> str:
    """Bytes/second → human-readable string."""
    if bps < 1024:
        return f"{bps:.0f} Б/с"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} КБ/с"
    return f"{bps / (1024 * 1024):.1f} МБ/с"


def format_bytes(total: int) -> str:
    """Cumulative bytes → human-readable string."""
    if total < 1024:
        return f"{total} Б"
    if total < 1024 * 1024:
        return f"{total / 1024:.1f} КБ"
    if total < 1024 * 1024 * 1024:
        return f"{total / (1024 * 1024):.1f} МБ"
    return f"{total / (1024 * 1024 * 1024):.2f} ГБ"
