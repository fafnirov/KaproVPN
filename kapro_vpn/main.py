"""Application entry point."""
from __future__ import annotations

import signal
import socket
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QSplashScreen

from .core import autostart, storage, system_proxy
from .gui import icons
from .gui.main_window import MainWindow
from .gui.singleton import SingleInstanceGuard
from .gui.styles import DARK_QSS


def _clear_stale_system_proxy() -> None:
    """If the registry still says system-proxy points at 127.0.0.1:<our port>
    but nothing's listening there, clear it.

    Happens when a previous HTTP-mode session was killed hard (Task Manager,
    Windows reboot mid-session) before disconnect() could restore the
    registry. Result: every browser/app on the machine tries to send
    traffic through a dead port and gets "connection refused" until the
    user manually clears it via Windows Settings.

    The single-instance guard runs BEFORE this, so if we reach this point
    no other KaproVPN is running — meaning a 127.0.0.1:<port> proxy entry
    is guaranteed stale.
    """
    try:
        state = system_proxy.get_state()
    except Exception:
        return
    if not state or not state.get("enable"):
        return
    server = str(state.get("server", ""))
    if ":" not in server:
        return
    host, _, port_s = server.rpartition(":")
    # Only touch proxies that point at our local listener — leave a real
    # corporate/personal proxy entry alone.
    if host not in ("127.0.0.1", "localhost", "::1"):
        return
    try:
        listen_port = int(storage.load_settings().get("listen_port", 2080))
    except Exception:
        listen_port = 2080
    try:
        if int(port_s) != listen_port:
            return
    except ValueError:
        return
    # Probe — fast TCP connect with tight timeout. If anything responds,
    # leave the registry alone (we'll attach to it).
    try:
        with socket.create_connection((host, listen_port), timeout=0.3):
            return
    except OSError:
        pass  # dead port → fall through to clear
    try:
        system_proxy.disable_proxy()
    except Exception:
        pass


def main() -> int:
    # Let Ctrl+C in the terminal kill the app cleanly
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # --minimized: boot straight to the tray, don't pop the main window
    # (used by the Windows Run-key registration for auto-start on login).
    start_minimized = autostart.MINIMIZED_FLAG in sys.argv

    app = QApplication(sys.argv)
    app.setApplicationName("KaproVPN")
    app.setOrganizationName("KaproVPN")
    app.setStyleSheet(DARK_QSS)
    app.setWindowIcon(icons.app_icon())
    # Don't exit when the user clicks X — we hide to tray instead.
    # Real exit goes through the tray-menu "Выход" item, which calls
    # QApplication.quit() explicitly.
    app.setQuitOnLastWindowClosed(False)

    # Single-instance check — bail early if another KaproVPN is already
    # running (and tell it to show its window). Without this, double-
    # clicking the shortcut while the app is in the tray would spawn a
    # second xray fighting for port 2080.
    guard = SingleInstanceGuard()
    if not guard.acquire():
        # Already running — we've asked the primary to show itself.
        return 0

    # Defensive: a crashed previous run may have left the system proxy
    # pointing at our dead local port. Clear it before any downloads
    # (xray installer, geoip, updater) try to route through nothing.
    _clear_stale_system_proxy()

    splash = None
    if not start_minimized:
        splash = QSplashScreen(icons.splash_pixmap(320), Qt.WindowStaysOnTopHint)
        splash.show()
        splash.showMessage("Запуск…", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
        app.processEvents()

    window = MainWindow()
    # Re-route "show" pings from any future second-launch attempts to
    # the same code path the tray icon uses.
    guard.setParent(window)  # keep the guard alive for the window's lifetime
    guard.show_requested.connect(window._on_show_window)

    def reveal() -> None:
        if not start_minimized:
            window.show()
            if splash is not None:
                splash.finish(window)
        # Optional auto-connect on launch — wait a beat after window
        # construction so any first-run installer dialogs finish first.
        if window.manager.settings.get("autoconnect_on_launch", False):
            QTimer.singleShot(800, window.trigger_autoconnect)

    # Tiny delay before swapping splash → window, so the splash is
    # actually visible. Without this, fast machines flash it for 1 frame.
    QTimer.singleShot(600 if not start_minimized else 0, reveal)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
