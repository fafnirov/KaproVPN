"""Modal dialog: 'Проверка утечек' — runs leak_test.run_full_leak_test
in a worker thread, displays a 4-row pass/fail table.

Triggered from SettingsPage 'Проверить утечки' button. Probes can
take 10-15 s total (network calls + 1 s settle for bash.ws DNS test),
so we MUST run them off the GUI thread — otherwise the window freezes
and Windows shows "Не отвечает" in the titlebar.

UI shape:
    +-------------------------------------------+
    | Проверка утечек                       [x] |
    +-------------------------------------------+
    |                                           |
    |  Проверяем IPv4, IPv6, DNS, WebRTC…       |  ← while running
    |  [spinner]                                |
    |                                           |
    +-------------------------------------------+
                       ↓ done ↓
    +-------------------------------------------+
    | Проверка утечек                       [x] |
    +-------------------------------------------+
    |  ● IPv4   46.17.101.82 (Финляндия)        |
    |  ● IPv6   заблокирован                    |
    |  ⚠ DNS    обнаружен ISP-резолвер!         |
    |       (показать список ↓)                 |
    |  ● WebRTC STUN заблокирован                |
    |                                           |
    |              [Закрыть]                    |
    +-------------------------------------------+

Colour convention:
  ●  green   — pass / clean
  ⚠  amber   — warning / suspected leak
  ✗  red     — fail / definite leak / probe error
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core import leak_test
from . import styles


class _LeakTestWorker(QObject):
    """Runs the probes off the GUI thread. Emits report when done."""
    finished = Signal(object)  # leak_test.LeakTestReport

    def __init__(self, socks_proxy: Optional[str]):
        super().__init__()
        self._socks_proxy = socks_proxy

    def run(self) -> None:
        try:
            report = leak_test.run_full_leak_test(self._socks_proxy)
        except Exception as e:  # safety net — never let worker crash silently
            # Build an empty report; the dialog will show "—" everywhere.
            # The unexpected exception goes into the IPv4 error field
            # because that's the first probe a user looks at.
            report = leak_test.LeakTestReport()
            report.ipv4 = leak_test.IPv4Result(
                error=f"{type(e).__name__}: {e}"
            )
        self.finished.emit(report)


class LeakTestDialog(QDialog):
    """The Settings → 'Проверить утечки' dialog."""

    def __init__(self, socks_proxy: Optional[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Проверка утечек")
        self.setModal(True)
        self.setMinimumWidth(440)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setSpacing(12)

        # ----- Running state: caption + indeterminate progress -----
        self._running_caption = QLabel(
            "Проверяем IPv4, IPv6, DNS, WebRTC через активный VPN…\n"
            "Это займёт ~10-15 секунд."
        )
        self._running_caption.setWordWrap(True)
        self._layout.addWidget(self._running_caption)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate "barber pole"
        self._layout.addWidget(self._progress)

        # ----- Result rows (created hidden, revealed when worker done) -----
        self._row_ipv4 = _ResultRow("IPv4")
        self._row_ipv6 = _ResultRow("IPv6")
        self._row_dns = _ResultRow("DNS")
        self._row_webrtc = _ResultRow("WebRTC STUN")
        for row in (self._row_ipv4, self._row_ipv6,
                    self._row_dns, self._row_webrtc):
            row.setVisible(False)
            self._layout.addWidget(row)

        # DNS detail panel — folds out under the DNS row when leak found.
        self._dns_detail = QTextEdit()
        self._dns_detail.setReadOnly(True)
        self._dns_detail.setFixedHeight(110)
        self._dns_detail.setVisible(False)
        self._layout.addWidget(self._dns_detail)

        # ----- Close button at the bottom -----
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._close_btn = QPushButton("Закрыть")
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._close_btn)
        self._layout.addLayout(btn_row)

        # ----- Kick off the worker -----
        self._thread = QThread(self)
        self._worker = _LeakTestWorker(socks_proxy)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_report)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    # ----- result handling -------------------------------------------------

    def _on_report(self, report: leak_test.LeakTestReport) -> None:
        # Swap the "Проверяем…" caption + progress for the results.
        self._running_caption.setVisible(False)
        self._progress.setVisible(False)

        # --- IPv4 ---
        v4 = report.ipv4
        if v4.ok:
            country_text = f" ({v4.country})" if v4.country else ""
            self._row_ipv4.set_pass(f"{v4.ip}{country_text}")
        else:
            self._row_ipv4.set_fail(v4.error or "не удалось получить IP")

        # --- IPv6 ---
        v6 = report.ipv6
        if v6.ipv6_blocked:
            self._row_ipv6.set_pass("заблокирован (нет утечки)")
        else:
            # We got an IPv6 — that means traffic went out the real ISP.
            self._row_ipv6.set_fail(
                f"утечка: {v6.ip} прошёл мимо туннеля"
            )

        # --- DNS ---
        dns = report.dns
        if dns.error:
            self._row_dns.set_fail(f"ошибка теста: {dns.error}")
        elif not dns.resolvers:
            self._row_dns.set_warn(
                "bash.ws не зарегистрировал ни одного резолвера "
                "(возможно, заблокирован VPN-провайдером)"
            )
        elif dns.suspected_leak:
            self._row_dns.set_fail(
                f"подозрение на утечку — {len(dns.resolvers)} резолверов, "
                f"один из них похож на ISP"
            )
            self._dns_detail.setText(self._format_dns_resolvers(dns))
            self._dns_detail.setVisible(True)
        else:
            self._row_dns.set_pass(
                f"{len(dns.resolvers)} резолверов, все похожи на VPN/CDN"
            )

        # --- WebRTC ---
        wr = report.webrtc
        if wr.stun_blocked:
            note = "stun.l.google.com:19302 заблокирован firewall'ом"
            self._row_webrtc.set_pass(note)
        else:
            self._row_webrtc.set_fail(
                "STUN ответил — браузер может узнать реальный IP "
                "(включи 'Защита от WebRTC leak' в настройках)"
            )

        # Reveal the rows.
        for row in (self._row_ipv4, self._row_ipv6,
                    self._row_dns, self._row_webrtc):
            row.setVisible(True)
        # Resize the dialog to fit the new content.
        self.adjustSize()

    def _format_dns_resolvers(self, dns: leak_test.DnsResult) -> str:
        """Pretty list of DNS resolvers + their geo for the detail panel."""
        lines = []
        for entry in dns.resolvers_meta:
            ip = entry.get("ip", "?")
            country = entry.get("country_name") or entry.get("country", "")
            asn = entry.get("asn") or ""
            hostname = entry.get("hostname") or ""
            tail = " · ".join(p for p in (country, asn, hostname) if p)
            lines.append(f"• {ip}    {tail}" if tail else f"• {ip}")
        return "\n".join(lines) if lines else "(нет данных)"

    def closeEvent(self, event) -> None:  # noqa: N802
        # Make sure the worker thread tears down cleanly before the dialog
        # is destroyed — otherwise Qt warns "QThread destroyed while still
        # running" on exit.
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)


# ===== Helper widget: one result row ====================================

class _ResultRow(QWidget):
    """A single ●/⚠/✗ label + caption + detail row."""

    def __init__(self, name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._badge = QLabel("●")
        self._badge.setFixedWidth(20)
        self._badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._badge)

        self._name = QLabel(name)
        self._name.setFixedWidth(96)
        self._name.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._name)

        self._detail = QLabel("…")
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail, stretch=1)

    def set_pass(self, detail: str) -> None:
        self._badge.setText("●")
        self._badge.setStyleSheet(f"color: {styles.ACCENT}; font-size: 14pt;")
        self._detail.setText(detail)
        self._detail.setStyleSheet("")

    def set_warn(self, detail: str) -> None:
        self._badge.setText("⚠")
        # Use ACCENT (amber) — matches the brand and reads as "caution"
        self._badge.setStyleSheet(f"color: {styles.ACCENT}; font-size: 12pt;")
        self._detail.setText(detail)
        self._detail.setStyleSheet("")

    def set_fail(self, detail: str) -> None:
        self._badge.setText("✗")
        self._badge.setStyleSheet(f"color: {styles.DANGER}; font-size: 12pt; font-weight: bold;")
        self._detail.setText(detail)
        self._detail.setStyleSheet(f"color: {styles.DANGER};")
