"""Modal dialog for picking, adding, and removing proxy configs."""
from __future__ import annotations

import concurrent.futures
import socket
import time
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..core import storage
from ..core.parser import ProxyConfig
from . import flags
from .config_dialog import AddConfigDialog
from .subscription_dialog import SubscriptionDialog


class _PingerThread(QThread):
    """TCP-pings every config server in parallel and emits one result per config.

    A "ping" here is a single TCP connect to (server, port) with a 3-second
    timeout — close enough to RTT to be useful for picking a fast server,
    without needing ICMP privileges or a real proxy handshake.
    """
    pinged = Signal(str, object)  # config name, latency_ms (int) or None

    def __init__(self, configs: list[ProxyConfig], parent=None):
        super().__init__(parent)
        self._configs = configs

    def run(self) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(self._ping_one, c): c for c in self._configs}
            for fut in concurrent.futures.as_completed(futures):
                cfg = futures[fut]
                try:
                    ms = fut.result()
                except Exception:
                    ms = None
                self.pinged.emit(cfg.name, ms)

    @staticmethod
    def _ping_one(cfg: ProxyConfig) -> Optional[int]:
        server = cfg.outbound.get("server")
        port = cfg.outbound.get("server_port")
        if not server or not port:
            return None
        # UDP-only protocols (Hysteria2): a TCP-connect probe to their
        # endpoint port ALWAYS fails (port is closed for TCP), which
        # would falsely label the config "недоступен" even when the
        # server is fine. Sentinel -1 tells the UI "skip the ping
        # label, just show the protocol".
        if cfg.protocol in ("hysteria2", "hy2"):
            return -1
        try:
            t0 = time.monotonic()
            with socket.create_connection((server, int(port)), timeout=3.0):
                return int((time.monotonic() - t0) * 1000)
        except (socket.gaierror, OSError):
            return None


class ConfigsPickerDialog(QDialog):
    """Pick a saved config, or add/remove from the saved list.

    On Accept, `selected_config()` returns the chosen ProxyConfig (or None).
    Mutations to the saved list happen in-place — caller should reload from
    `storage.load_configs()` after the dialog closes either way.
    """

    def __init__(
        self,
        configs: list[ProxyConfig],
        current_name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Выбор конфига")
        self.resize(440, 540)
        self._configs = list(configs)
        self._current_name = current_name
        self._chosen: Optional[ProxyConfig] = None
        self._pings: dict[str, Optional[int]] = {}  # name -> ms (None = unreachable)
        self._pinger: Optional[_PingerThread] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("Конфиги")
        title.setObjectName("h2")
        header_row.addWidget(title)
        # Count label updates as the search filters in — "12 из 47"
        # is way clearer feedback than the list silently shrinking.
        self.count_label = QLabel("")
        self.count_label.setObjectName("dim")
        header_row.addWidget(self.count_label)
        header_row.addStretch(1)
        self.refresh_ping_btn = QPushButton("↻ Пинг")
        self.refresh_ping_btn.setToolTip("Перепроверить задержку до каждого сервера")
        self.refresh_ping_btn.clicked.connect(self._start_pings)
        header_row.addWidget(self.refresh_ping_btn)
        layout.addLayout(header_row)

        # Search box — substring match across name + server + port +
        # protocol. Live-filtered as you type, clearable via the built-in
        # X button on the right. v1.12.0. Critical when a subscription
        # gives you 20-50 servers and finding "the German one" by scroll
        # is annoying.
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Поиск (имя, IP, протокол, порт)…"
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.list_widget, stretch=1)

        # Empty-state label — shown only when the search query yields
        # zero matches. Without this the list silently goes blank and
        # the user doesn't know if the picker is broken or just filtered.
        self.empty_label = QLabel("Ничего не найдено")
        self.empty_label.setObjectName("dim")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        add_btn = QPushButton("＋ Добавить")
        add_btn.clicked.connect(self._on_add)
        sub_btn = QPushButton("📥 Подписка")
        sub_btn.setToolTip("Импортировать сразу много конфигов из URL подписки")
        sub_btn.clicked.connect(self._on_import_subscription)
        remove_btn = QPushButton("Удалить")
        remove_btn.setObjectName("danger")
        remove_btn.clicked.connect(self._on_remove)

        button_row.addWidget(add_btn)
        button_row.addWidget(sub_btn)
        button_row.addWidget(remove_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        cancel_btn = QPushButton("Закрыть")
        cancel_btn.clicked.connect(self.reject)
        use_btn = QPushButton("Использовать")
        use_btn.setObjectName("primary")
        use_btn.clicked.connect(self._on_use)
        bottom_row.addWidget(cancel_btn)
        bottom_row.addWidget(use_btn)
        layout.addLayout(bottom_row)

        self._refresh()
        self._start_pings()

    # --- helpers ----------------------------------------------------------

    def _refresh(self) -> None:
        self.list_widget.clear()
        for cfg in self._configs:
            item = QListWidgetItem(self._format_item(cfg))
            item.setData(Qt.UserRole, cfg)
            self.list_widget.addItem(item)
            if cfg.name == self._current_name:
                self.list_widget.setCurrentItem(item)
        if self.list_widget.currentRow() < 0 and self._configs:
            self.list_widget.setCurrentRow(0)
        # Re-apply the active search filter to the rebuilt list — if
        # the user added/removed/imported configs while a query was in
        # the search box, fresh items would otherwise all show.
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Hide list items whose config doesn't match the search query.

        Match is case-insensitive substring across name, server hostname,
        port number, and protocol — so the user can type "fi" (country
        flag prefix), "144.31" (server IP block), "vless" (protocol),
        or "443" (port) and get the expected hits.
        """
        q = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        visible = 0
        total = self.list_widget.count()
        for i in range(total):
            item = self.list_widget.item(i)
            cfg = item.data(Qt.UserRole)
            if not q or self._matches(cfg, q):
                item.setHidden(False)
                visible += 1
            else:
                item.setHidden(True)
        # Empty-state visibility — only "no match" when the user IS
        # filtering (a literally empty config list isn't a search failure).
        self.empty_label.setVisible(bool(q) and total > 0 and visible == 0)
        # Count label — silent when no filter is active to avoid
        # redundant "47 из 47", informative once the user starts typing.
        if q:
            self.count_label.setText(f"{visible} из {total}")
        else:
            self.count_label.setText("")
        # If the currently-selected row got hidden by the filter, move
        # selection to the first visible item so Enter / "Использовать"
        # still does something sensible.
        cur = self.list_widget.currentItem()
        if cur is not None and cur.isHidden():
            for i in range(total):
                if not self.list_widget.item(i).isHidden():
                    self.list_widget.setCurrentRow(i)
                    break

    def _on_search_changed(self, _text: str) -> None:
        self._apply_filter()

    @staticmethod
    def _matches(cfg: ProxyConfig, q: str) -> bool:
        haystack = " ".join([
            cfg.name.lower(),
            str(cfg.outbound.get("server") or "").lower(),
            str(cfg.outbound.get("server_port") or ""),
            cfg.protocol.lower(),
        ])
        return q in haystack

    def _format_item(self, cfg: ProxyConfig) -> str:
        srv = cfg.outbound.get("server", "?")
        port = cfg.outbound.get("server_port", "?")
        # Ping suffix is in the protocol line: known ms / "недоступен" / "…"
        # Sentinel -1 from _ping_one means "UDP-only protocol, skip the
        # ping label entirely" — TCP-probing a WG/HY2 endpoint always
        # fails and would falsely show "недоступен".
        ping_value = self._pings.get(cfg.name, "pending")
        if ping_value == "pending":
            ping_str = "…"
        elif ping_value == -1:
            ping_str = "UDP"  # protocol uses UDP-only, can't TCP-probe
        elif ping_value is None:
            ping_str = "недоступен"
        else:
            ping_str = f"{ping_value} мс"
        return (
            f"{flags.prefix_with_flag(cfg)}\n"
            f"{cfg.protocol.upper()}  ·  {srv}:{port}  ·  {ping_str}"
        )

    # --- pinger lifecycle -------------------------------------------------

    def _start_pings(self) -> None:
        if self._pinger is not None and self._pinger.isRunning():
            return  # already running
        # Reset all to "pending" so the UI shows progress
        for cfg in self._configs:
            self._pings[cfg.name] = "pending"
        self._refresh_list_text()
        self.refresh_ping_btn.setEnabled(False)
        self._pinger = _PingerThread(self._configs, parent=self)
        self._pinger.pinged.connect(self._on_pinged)
        self._pinger.finished.connect(lambda: self.refresh_ping_btn.setEnabled(True))
        self._pinger.start()

    def _on_pinged(self, name: str, ms) -> None:
        self._pings[name] = ms
        self._refresh_list_text()

    def _refresh_list_text(self) -> None:
        """Update each list item's label in place (no row rebuild)."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            cfg = item.data(Qt.UserRole)
            item.setText(self._format_item(cfg))

    def _selected_index(self) -> int:
        return self.list_widget.currentRow()

    # --- actions ----------------------------------------------------------

    def _on_add(self) -> None:
        dlg = AddConfigDialog(self)
        rc = dlg.exec()
        # Auto-redirect: if the user pasted a subscription URL into the
        # "add single config" form, AddConfigDialog asks them whether to
        # switch and bails with this sentinel. We open the subscription
        # dialog pre-filled so they don't have to paste again.
        if rc == AddConfigDialog.SWITCH_TO_SUBSCRIPTION:
            self._on_import_subscription(prefill_url=dlg.pending_subscription_url())
            return
        if rc != AddConfigDialog.Accepted:
            return
        new_cfg = dlg.result_config()
        if new_cfg is None:
            return
        # Replace existing by name, else append
        for i, c in enumerate(self._configs):
            if c.name == new_cfg.name:
                self._configs[i] = new_cfg
                break
        else:
            self._configs.append(new_cfg)
        storage.save_configs(self._configs)
        self._current_name = new_cfg.name
        self._refresh()

    def _on_import_subscription(self, prefill_url: Optional[str] = None) -> None:
        dlg = SubscriptionDialog(self, prefill_url=prefill_url)
        if dlg.exec() != SubscriptionDialog.Accepted:
            return
        imported = dlg.imported_configs()
        if not imported:
            return
        # Merge — name conflicts overwrite existing entries
        existing_by_name = {c.name: i for i, c in enumerate(self._configs)}
        added = replaced = 0
        for cfg in imported:
            if cfg.name in existing_by_name:
                self._configs[existing_by_name[cfg.name]] = cfg
                replaced += 1
            else:
                self._configs.append(cfg)
                existing_by_name[cfg.name] = len(self._configs) - 1
                added += 1
        storage.save_configs(self._configs)
        self._refresh()
        self._start_pings()
        QMessageBox.information(
            self,
            "Импорт завершён",
            f"Добавлено новых: {added}\nЗаменено существующих: {replaced}",
        )

    def _on_remove(self) -> None:
        idx = self._selected_index()
        if idx < 0:
            return
        cfg = self._configs[idx]
        confirm = QMessageBox.question(
            self, "Удалить", f"Удалить конфиг «{cfg.name}»?"
        )
        if confirm != QMessageBox.Yes:
            return
        del self._configs[idx]
        storage.save_configs(self._configs)
        self._refresh()

    def _on_use(self) -> None:
        idx = self._selected_index()
        if idx < 0:
            QMessageBox.information(self, "Конфиг", "Выбери конфиг из списка.")
            return
        self._chosen = self._configs[idx]
        self.accept()

    def _on_double_click(self, _item) -> None:
        self._on_use()

    # --- result -----------------------------------------------------------

    def selected_config(self) -> Optional[ProxyConfig]:
        return self._chosen
