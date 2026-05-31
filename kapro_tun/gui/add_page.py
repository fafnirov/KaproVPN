"""Inline "Add config" page for the main stacked widget.

Replaces the AddConfigDialog modal so adding a config doesn't pop a
separate window — it slides into the same window via the QStackedWidget.

Emits:
  config_ready(ProxyConfig)    user pasted, parsed, named, hit Save
  back_clicked                  user hit ← Назад (also raised on save)
  subscription_clicked          user wants the URL-subscription path
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.parser import ParseError, ProxyConfig, parse
from .toast import show_toast


class AddConfigPage(QWidget):
    config_ready = Signal(object)  # ProxyConfig
    back_clicked = Signal()
    subscription_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("page")
        self._parsed: Optional[ProxyConfig] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        # --- Header ---
        header = QHBoxLayout()
        back_btn = QPushButton("← Назад")
        back_btn.clicked.connect(self.back_clicked)
        header.addWidget(back_btn)
        header.addStretch(1)
        outer.addLayout(header)

        title = QLabel("Добавить конфиг")
        title.setObjectName("h1")
        outer.addWidget(title)

        # --- URL field ---
        outer.addWidget(QLabel("Вставь share-URL:"))
        self.url_edit = QPlainTextEdit()
        self.url_edit.setPlaceholderText(
            "vless://uuid@host:443?type=xhttp&security=reality...#Server name\n"
            "(Также trojan://, vmess://, ss://, hysteria2://)"
        )
        self.url_edit.setMinimumHeight(120)
        self.url_edit.setMaximumHeight(160)
        # As soon as user types, re-validate
        self.url_edit.textChanged.connect(self._on_url_changed)
        outer.addWidget(self.url_edit)

        # --- Parse status row ---
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.RichText)
        outer.addWidget(self.status_label)

        # --- Name field ---
        outer.addWidget(QLabel("Имя (как будет отображаться в списке):"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("например, NL Server #2")
        outer.addWidget(self.name_edit)

        # --- Primary action ---
        self.save_btn = QPushButton("Сохранить и подключить")
        self.save_btn.setObjectName("primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        outer.addWidget(self.save_btn)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        outer.addSpacing(4)
        outer.addWidget(sep)

        # --- Alternative: subscription ---
        sub_label = QLabel(
            "<span style='color:#a1a1aa'>Если провайдер выдал ссылку на "
            "подписку — все сервера одним кликом</span>"
        )
        sub_label.setTextFormat(Qt.RichText)
        sub_label.setWordWrap(True)
        outer.addWidget(sub_label)

        sub_btn = QPushButton("📥 Импорт по подписке")
        sub_btn.clicked.connect(self.subscription_clicked)
        outer.addWidget(sub_btn)

        outer.addStretch(1)

    # --- helpers ----------------------------------------------------------

    def reset(self) -> None:
        """Clear the form — called when the page is shown fresh."""
        self.url_edit.blockSignals(True)
        self.url_edit.clear()
        self.url_edit.blockSignals(False)
        self.name_edit.clear()
        self.status_label.clear()
        self._parsed = None
        self.save_btn.setEnabled(False)

    def _on_url_changed(self) -> None:
        text = self.url_edit.toPlainText().strip()
        if not text:
            self.status_label.clear()
            self._parsed = None
            self.save_btn.setEnabled(False)
            return
        # Friendly nudge: an http(s) URL pasted here is almost always a
        # subscription URL that belongs in the other dialog. Don't auto-
        # redirect (textChanged fires per-keystroke) — just hint.
        if text.lower().startswith(("http://", "https://")):
            self._parsed = None
            self.status_label.setText(
                "<span style='color:#fbbf24'>⚠ Похоже на URL подписки.</span> "
                "<span style='color:#a1a1aa'>Жми «📥 Импорт по подписке» "
                "ниже — это другая кнопка.</span>"
            )
            self.save_btn.setEnabled(False)
            return
        try:
            cfg = parse(text)
        except ParseError as e:
            self._parsed = None
            self.status_label.setText(
                f"<span style='color:#ef4444'>✕ Не удалось разобрать:</span> "
                f"<span style='color:#a1a1aa'>{e}</span>"
            )
            self.save_btn.setEnabled(False)
            return
        self._parsed = cfg
        # Auto-fill the name field on first successful parse
        if not self.name_edit.text().strip():
            self.name_edit.setText(cfg.name)
        srv = cfg.outbound.get("server", "?")
        port = cfg.outbound.get("server_port", "?")
        self.status_label.setText(
            f"<span style='color:#16a34a'>✓ {cfg.protocol.upper()}</span>"
            f" <span style='color:#71717a'>·</span>"
            f" <span style='color:#fafafa'>{srv}:{port}</span>"
        )
        self.save_btn.setEnabled(True)

    def _on_save(self) -> None:
        if self._parsed is None:
            return
        name = self.name_edit.text().strip()
        if not name:
            show_toast(self.window(), "Укажи имя для конфига", kind="error")
            self.name_edit.setFocus()
            return
        self._parsed.name = name
        self.config_ready.emit(self._parsed)
