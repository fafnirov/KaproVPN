"""Statistics page — 24h bandwidth chart + total downloaded/uploaded.

Lives at index 4 in MainWindow's QStackedWidget, reachable via the
new chart-glyph button in the bottom nav. The page is read-only:
it queries core/bandwidth_history every time it becomes visible and
on a 60-second timer while visible (so a long-open Stats tab stays
fresh as new minute-samples land).

Out of scope for v1.15.0:
  - Time-range selectors (last hour / last week). 24h fits the rolling
    db window — for longer history we'd need to keep the db unbounded
    or aggregate into daily buckets. Future work.
  - CSV/JSON export. If users ask, easy add-on.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import bandwidth_history
from .bandwidth_chart import BandwidthChartWidget, format_bytes


class StatsPage(QWidget):
    """The "Статистика" tab. Header → totals → chart → clear-button."""

    cleared = Signal()  # emitted after the user clears history (just for testability)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(14)

        title = QLabel("Статистика за 24 часа")
        title.setObjectName("h1")
        outer.addWidget(title)

        # Totals row — two big numbers side-by-side. The chart underneath
        # explains "when", these explain "how much".
        totals_row = QHBoxLayout()
        totals_row.setSpacing(24)
        self.down_label = QLabel("Скачано: —")
        self.down_label.setTextFormat(Qt.RichText)
        self.up_label = QLabel("Отправлено: —")
        self.up_label.setTextFormat(Qt.RichText)
        totals_row.addWidget(self.down_label)
        totals_row.addWidget(self.up_label)
        totals_row.addStretch(1)
        outer.addLayout(totals_row)

        # Chart centered horizontally
        chart_row = QHBoxLayout()
        chart_row.addStretch(1)
        self.chart = BandwidthChartWidget()
        chart_row.addWidget(self.chart)
        chart_row.addStretch(1)
        outer.addLayout(chart_row)

        # Note about gaps in the chart — preempts "why is there empty
        # space in the middle?" support questions.
        note = QLabel(
            "Пустые промежутки на графике — это время, когда VPN был "
            "отключён или приложение закрыто. Мы измеряем трафик только "
            "пока туннель активен."
        )
        note.setObjectName("dim")
        note.setWordWrap(True)
        outer.addWidget(note)

        outer.addStretch(1)

        # Clear-history button — destructive, danger-styled, with a
        # confirm dialog. Useful for shared/loaned laptops or privacy-
        # paranoid users who don't want to dig for the sqlite file.
        clear_row = QHBoxLayout()
        clear_row.addStretch(1)
        self.clear_btn = QPushButton("Очистить историю")
        self.clear_btn.setObjectName("danger")
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        clear_row.addWidget(self.clear_btn)
        outer.addLayout(clear_row)

        # Auto-refresh while page is visible. 60-second tick matches our
        # recording cadence — no point polling faster than new data lands.
        # The timer starts in showEvent and stops in hideEvent to avoid
        # waking the db on every Home/Settings interaction.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(60_000)
        self._refresh_timer.timeout.connect(self.refresh)

    def set_theme_getter(self, getter) -> None:
        self.chart.set_theme_getter(getter)

    def refresh(self) -> None:
        """Re-read totals and tell the chart to repaint."""
        down_bytes, up_bytes = (
            bandwidth_history.totals_24h()[1],
            bandwidth_history.totals_24h()[0],
        )
        # Above call returns (up_bytes, down_bytes) — unpacking and
        # reordering for the labels' "Скачано first, Отправлено
        # second" convention.
        self.down_label.setText(
            f"<span style='color:#a1a1aa'>Скачано: </span>"
            f"<span style='font-size:14pt; font-weight:600'>"
            f"{format_bytes(down_bytes)}</span>"
        )
        self.up_label.setText(
            f"<span style='color:#a1a1aa'>Отправлено: </span>"
            f"<span style='font-size:14pt; font-weight:600'>"
            f"{format_bytes(up_bytes)}</span>"
        )
        self.chart.refresh()

    # ----- visibility-aware timer ------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()
        self._refresh_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._refresh_timer.stop()

    # ----- actions ---------------------------------------------------------

    def _on_clear_clicked(self) -> None:
        reply = QMessageBox.question(
            self,
            "Очистить статистику",
            "Удалить всю историю трафика за последние 24 часа? "
            "Это действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        bandwidth_history.clear()
        self.refresh()
        self.cleared.emit()
