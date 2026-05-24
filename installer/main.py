"""KaproVPN-Setup.exe entry point.

Modes:
  default             → full install UI (Welcome → Progress → Done)
  --uninstall         → confirm + uninstall flow
  --silent            → headless update install: tiny progress indicator,
                        run install_everything(), launch installed app,
                        exit. Used by the in-app auto-updater.
"""
from __future__ import annotations

import sys

from .gui import run, run_silent


def main() -> int:
    if "--silent" in sys.argv:
        return run_silent()
    uninstall = "--uninstall" in sys.argv
    return run(uninstall=uninstall)


if __name__ == "__main__":
    sys.exit(main())
