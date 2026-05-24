"""Windows UAC / elevated-process helpers.

TUN mode requires admin privileges (TUN interface creation + route changes).
We don't ship a Windows service, so the user gets a UAC prompt when they
enable TUN mode.
"""
from __future__ import annotations

import ctypes
import os
import sys
from typing import Sequence


def is_admin() -> bool:
    """True if the current process has admin (UAC-elevated) privileges."""
    if sys.platform != "win32":
        return os.geteuid() == 0  # type: ignore[attr-defined]
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(argv: Sequence[str] = None) -> int:
    """Spawn a new elevated copy of this app and return ShellExecute's result.

    Anything > 32 = success, the elevated process is starting. The caller
    should exit immediately after. <= 32 = failure (user declined UAC, etc.).
    """
    if sys.platform != "win32":
        raise NotImplementedError("Elevation only supported on Windows")

    if argv is None:
        argv = sys.argv

    # Run via python.exe so the venv / interpreter context is preserved.
    # `script` is sys.argv[0]; pass remaining args separately so spaces in
    # paths don't get re-split.
    params = " ".join(f'"{a}"' for a in argv)
    rc = ctypes.windll.shell32.ShellExecuteW(
        None,           # parent hwnd
        "runas",        # verb: trigger UAC
        sys.executable, # exe to run (python.exe)
        params,         # args (the script + its args, quoted)
        None,           # working dir
        1,              # SW_SHOWNORMAL
    )
    return int(rc)
