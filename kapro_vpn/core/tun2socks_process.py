"""Run tun2socks.exe as a managed subprocess.

tun2socks creates a WinTUN interface and forwards all IP traffic from it
to our xray's SOCKS5 inbound. We then point Windows' default route at
the TUN, achieving system-wide tunneling.
"""
from __future__ import annotations

import subprocess
import threading
from collections import deque
from typing import Callable, Optional

from . import paths

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LogSink = Callable[[str], None]

# Friendly name for our TUN interface — same one we look up in Get-NetAdapter
TUN_DEVICE_NAME = "KaproTun"


class Tun2socksProcess:
    """Wraps tun2socks.exe as a subprocess."""

    def __init__(self, on_log: Optional[LogSink] = None, log_buffer: int = 500):
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._on_log = on_log
        self._recent: deque[str] = deque(maxlen=log_buffer)
        self._lock = threading.Lock()

    def start(self, socks_addr: str = "127.0.0.1:2081",
              mtu: int = 1500, loglevel: str = "info") -> None:
        if self.is_running():
            raise RuntimeError("tun2socks is already running")
        exe = paths.tun2socks_exe()
        if not exe.is_file():
            raise FileNotFoundError(f"tun2socks.exe not found at {exe}")
        if not paths.wintun_dll().is_file():
            raise FileNotFoundError(f"wintun.dll not found at {paths.wintun_dll()}")

        # tun2socks loads wintun.dll from its working directory.
        self._proc = subprocess.Popen(
            [
                str(exe),
                "-device", f"tun://{TUN_DEVICE_NAME}",
                "-proxy", f"socks5://{socks_addr}",
                "-loglevel", loglevel,
                "-mtu", str(mtu),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            cwd=str(paths.tun_dir()),
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def stop(self, timeout: float = 3.0) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        self._proc = None

    def is_running(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None

    def returncode(self) -> Optional[int]:
        return self._proc.returncode if self._proc else None

    def recent_logs(self) -> list[str]:
        with self._lock:
            return list(self._recent)

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            with self._lock:
                self._recent.append(line)
            if self._on_log:
                try:
                    self._on_log(line)
                except Exception:
                    pass
