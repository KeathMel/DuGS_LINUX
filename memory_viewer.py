"""
memory_viewer.py — a look inside one Memory Bank.

Shares the same customizable "skin" as home_screen.py and tabel_editor.py:
grey background by default, white buttons, a blue logo — all changeable from
the gear icon in the bottom-left corner, which opens the same settings popup
used everywhere else (settings live in home_ui_settings.json, so changing
them in one place changes them everywhere).

The most recent entry shows up top so you can see at a glance what's
freshest. Everything else is listed underneath, numbered, oldest-first by
default — flip the switch for newest-first.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem,
)
from PyQt6.QtCore import Qt

from theme import DIM
from storage import load_memory_bank
from home_screen import (
    load_home_ui_settings, HomeSettingsDialog, ToggleSwitch,
    DEFAULT_BUTTON_COLOR, DEFAULT_LOGO_COLOR,
    button_style, paint_flat_or_image_bg, register_themed_screen,
)


class MemoryBankViewer(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app; self.bank_name = None
        self.settings = load_home_ui_settings()
        root = QVBoxLayout(self); root.setContentsMargins(16, 12, 16, 16); root.setSpacing(8)

        bar = QHBoxLayout()
        self.dugs = QLabel("DuGS")
        self.dugs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dugs.mousePressEvent = lambda _e: self.app.go_home()
        bar.addWidget(self.dugs)
        self.title = QLabel("-")
        bar.addSpacing(16); bar.addWidget(self.title); bar.addStretch()
        self.sort_label_old = QLabel("Oldest")
        bar.addWidget(self.sort_label_old)
        self.sort_switch = ToggleSwitch(checked=False)
        self.sort_switch.toggled.connect(self._reload)
        bar.addWidget(self.sort_switch)
        self.sort_label_new = QLabel("Newest")
        bar.addWidget(self.sort_label_new)
        bar.addSpacing(12)
        self.count_label = QLabel("")
        bar.addWidget(self.count_label)
        root.addLayout(bar)

        # ---- the most recent entry, front and centre ----
        self.latest_box = QWidget()
        lb = QVBoxLayout(self.latest_box)
        lb.setContentsMargins(10, 10, 10, 10); lb.setSpacing(4)
        self.latest_label = QLabel("MOST RECENT")
        lb.addWidget(self.latest_label)
        self.latest_key = QLabel("—")
        lb.addWidget(self.latest_key)
        self.latest_value = QLabel(""); self.latest_value.setWordWrap(True)
        lb.addWidget(self.latest_value)
        self.latest_time = QLabel("")
        lb.addWidget(self.latest_time)
        root.addWidget(self.latest_box)

        # ---- the full list, numbered ----
        self.list = QListWidget()
        root.addWidget(self.list, 1)

        self.hint = QLabel("the switch flips the list between oldest-first and newest-first")
        self.hint.setStyleSheet(f"color:{DIM};font-family:monospace;font-size:9px;")
        root.addWidget(self.hint)

        # settings gear, pinned bottom-left — same popup as everywhere else
        bottom_bar = QHBoxLayout()
        self.settings_btn = QPushButton("\u2699")
        self.settings_btn.setFixedSize(38, 38)
        self.settings_btn.setToolTip("Home screen settings")
        self.settings_btn.clicked.connect(self.open_settings)
        bottom_bar.addWidget(self.settings_btn)
        bottom_bar.addStretch()
        root.addLayout(bottom_bar)

        self.apply_theme()
        register_themed_screen(self)

    # -- theme ---------------------------------------------------------------
    def _list_style(self, color):
        return (
            "QListWidget{background:rgba(58,58,58,0.55);color:#eee;"
            "font-family:monospace;border:1px solid #555;}"
            "QListWidget::item:selected{background:rgba(255,255,255,0.14);}"
        )

    def apply_theme(self):
        """(Re)apply button/logo colors, list styling, and background from
        self.settings. Called at startup and again after the shared settings
        dialog is saved — same as TabelEditor's apply_theme."""
        btn_color = self.settings.get("button_color", DEFAULT_BUTTON_COLOR)
        logo_color = self.settings.get("logo_color", DEFAULT_LOGO_COLOR)

        self.dugs.setStyleSheet(f"color:{logo_color};font-family:monospace;font-size:20px;font-weight:bold;")
        self.title.setStyleSheet(f"color:{btn_color};font-family:monospace;font-size:14px;")
        self.settings_btn.setStyleSheet(button_style(btn_color, circular=True))
        self.list.setStyleSheet(self._list_style(btn_color))
        self.latest_box.setStyleSheet(
            "QWidget{background:rgba(255,255,255,0.05);border:1px solid "
            f"{btn_color};border-radius:6px;}}")
        self.latest_label.setStyleSheet(f"color:{DIM};font-family:monospace;font-size:9px;")
        self.latest_key.setStyleSheet(
            f"color:{btn_color};font-family:monospace;font-size:13px;font-weight:bold;")
        self.latest_value.setStyleSheet("color:#ccc;font-family:monospace;font-size:11px;")
        self.latest_time.setStyleSheet(f"color:{DIM};font-family:monospace;font-size:9px;")
        self.count_label.setStyleSheet(f"color:{DIM};font-family:monospace;font-size:10px;")

        self.update()  # repaint background (grey / image / see-through)

    def open_settings(self):
        dlg = HomeSettingsDialog(self, self)
        dlg.exec()

    def paintEvent(self, event):
        """Same background behavior as the home screen and Tabel editor:
        chosen image, flat grey, or fully see-through."""
        if not paint_flat_or_image_bg(self, event, self.settings):
            super().paintEvent(event)
            return
        super().paintEvent(event)

    # -- data logic -----------------------------------------------------------
    def open(self, name):
        self.bank_name = name; self.title.setText(name)
        self._reload()

    def _reload(self):
        if not self.bank_name:
            return
        try:
            data = load_memory_bank(self.bank_name)
        except Exception:
            data = {"entries": {}}

        entries = data.get("entries") or {}
        # each entry carries updated_at (a unix timestamp) from storage.py's
        # memory_set — that's what oldest/newest actually sorts on
        rows = sorted(
            entries.items(),
            key=lambda kv: kv[1].get("updated_at", 0),
            reverse=self.sort_switch.isChecked(),   # True = newest first
        )
        self.count_label.setText(f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}")

        if rows:
            # "most recent" is always the actual newest, regardless of which
            # way the list below is currently sorted
            newest_key, newest_entry = max(
                entries.items(), key=lambda kv: kv[1].get("updated_at", 0))
            self.latest_key.setText(newest_key)
            self.latest_value.setText(str(newest_entry.get("value", ""))[:300])
            self.latest_time.setText(self._fmt_time(newest_entry.get("updated_at")))
        else:
            self.latest_key.setText("—")
            self.latest_value.setText("this bank is empty")
            self.latest_time.setText("")

        self.list.clear()
        for i, (key, entry) in enumerate(rows, start=1):
            when = self._fmt_time(entry.get("updated_at"))
            value_preview = str(entry.get("value", ""))
            if len(value_preview) > 60:
                value_preview = value_preview[:60] + "…"
            item = QListWidgetItem(f"{i:>3}.  {key}   \u00b7   {when}")
            item.setToolTip(value_preview)
            self.list.addItem(item)

    @staticmethod
    def _fmt_time(ts):
        if not ts:
            return "no timestamp"
        try:
            from datetime import datetime
            return datetime.fromtimestamp(ts).strftime("%d %b %H:%M:%S")
        except Exception:
            return str(ts)
