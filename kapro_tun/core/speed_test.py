"""Quick direct link-speed probe (download + upload).

Used to auto-configure Hysteria2's `bandwidth` (brutal congestion control)
so the user doesn't have to run an external speedtest and type numbers in.

CRITICAL: this must measure the user's RAW link, not the VPN tunnel — so
the caller runs it BEFORE the tunnel routes go up (controller calls it at
the very start of _maybe_start_hysteria, before tun2socks creates the TUN).
We also bypass any system proxy explicitly.

Everything is best-effort: a failure returns 0 for that direction, and the
caller falls back to BBR (hysteria's adaptive default). We never raise.
"""
from __future__ import annotations

import time
from typing import Tuple

import requests

# Cloudflare's open speed-test endpoints. __down?bytes=N streams N bytes;
# __up accepts a POST body and times the upload. No auth, no user id.
_DOWN_URL = "https://speed.cloudflare.com/__down?bytes={n}"
_UP_URL = "https://speed.cloudflare.com/__up"

# Bypass the system proxy — same reasoning as ip_probe/xray_installer: a
# stale 127.0.0.1:2080 entry would make this fail, and we want the raw link.
_NO_PROXY = {"http": "", "https": ""}

# Sane clamps so a measurement glitch can't feed hysteria an absurd rate
# (overshooting bandwidth causes packet-loss storms — worse than BBR).
_MIN_MBPS = 1
_MAX_MBPS = 2000


def _mbps(num_bytes: int, seconds: float) -> int:
    if seconds <= 0 or num_bytes <= 0:
        return 0
    val = num_bytes * 8 / seconds / 1_000_000
    return int(max(0, min(_MAX_MBPS, round(val))))


def _measure_download(num_bytes: int, timeout: float) -> int:
    t0 = time.monotonic()
    got = 0
    with requests.get(_DOWN_URL.format(n=num_bytes), stream=True,
                      timeout=timeout, proxies=_NO_PROXY) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=64 * 1024):
            got += len(chunk)
    return _mbps(got, time.monotonic() - t0)


def _measure_upload(num_bytes: int, timeout: float) -> int:
    payload = b"\x00" * num_bytes
    t0 = time.monotonic()
    r = requests.post(_UP_URL, data=payload, timeout=timeout, proxies=_NO_PROXY)
    r.raise_for_status()
    return _mbps(num_bytes, time.monotonic() - t0)


def measure_link_speed(down_bytes: int = 25_000_000,
                       up_bytes: int = 10_000_000,
                       timeout: float = 20.0) -> Tuple[int, int]:
    """Return (down_mbps, up_mbps) as ints. 0 for a direction that failed.

    Both must be > 0 for the caller to enable hysteria brutal CC; if either
    is 0 the caller keeps BBR (safe). Never raises.
    """
    try:
        down = _measure_download(down_bytes, timeout)
    except Exception:
        down = 0
    try:
        up = _measure_upload(up_bytes, timeout)
    except Exception:
        up = 0
    # Below the floor we treat as "couldn't measure" rather than feed
    # hysteria a near-zero rate.
    if down and down < _MIN_MBPS:
        down = 0
    if up and up < _MIN_MBPS:
        up = 0
    return (down, up)
