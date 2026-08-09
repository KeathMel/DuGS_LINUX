"""
memory_viewer.py — a look inside one Memory Bank.

Shares the same customizable "skin" as home_screen.py and tabel_editor.py:
grey background by default, white buttons, a blue logo — all changeable from
the gear icon in the bottom-left corner, which opens the same settings popup
used everywhere else (settings live in home_ui_settings.json, so changing
them in one place changes them everywhere).

The list on the left shows every entry, numbered, with its date. The arrow
button flips it between oldest-first and newest-first. Click an entry and
its full value opens on the right, where you can edit and save it.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QTextEdit,
)
from PyQt6.QtCore import Qt

from theme import DIM
from storage import load_memory_bank, save_memory_bank
from home_screen import (
    load_home_ui_settings, HomeSettingsDialog,
    DEFAULT_BUTTON_COLOR, DEFAULT_LOGO_COLOR,
    button_style, paint_flat_or_image_bg, register_themed_screen,
)


class MemoryBankViewer(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app; self.bank_name = None
        self.settings = load_home_ui_settings()
        self._newest_first = False
        self._selected_key = None
        root = QVBoxLayout(self); root.setContentsMargins(16, 12, 16, 16); root.setSpacing(8)

        # ---- top bar: DuGS (= back), title, sort order, count ----
        bar = QHBoxLayout()
        self.dugs = QLabel("DuGS")
        self.dugs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dugs.mousePressEvent = lambda _e: self.app.go_home()
        bar.addWidget(self.dugs)
        self.title = QLabel("-")
        bar.addSpacing(16); bar.addWidget(self.title); bar.addStretch()
        self.sort_btn = QPushButton("\u2191 Oldest first")
        self.sort_btn.setToolTip("Click to flip the sort order")
        self.sort_btn.clicked.connect(self._toggle_sort)
        bar.addWidget(self.sort_btn)
        bar.addSpacing(12)
        self.count_label = QLabel("")
        bar.addWidget(self.count_label)
        root.addLayout(bar)

        # ---- body: list on the left, detail/edit on the right ----
        body = QHBoxLayout(); body.setSpacing(10)

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show_detail)
        body.addWidget(self.list, 1)

        detail_box = QVBoxLayout(); detail_box.setSpacing(6)
        self.detail_key = QLabel("select an entry")
        detail_box.addWidget(self.detail_key)
        self.detail_time = QLabel("")
        detail_box.addWidget(self.detail_time)
        self.detail_text = QTextEdit()
        self.detail_text.setPlaceholderText("(nothing selected)")
        detail_box.addWidget(self.detail_text, 1)
        save_row = QHBoxLayout()
        save_row.addStretch()
        self.save_btn = QPushButton("Save changes")
        self.save_btn.clicked.connect(self._save_edit)
        self.save_btn.setEnabled(False)
        save_row.addWidget(self.save_btn)
        detail_box.addLayout(save_row)
        body.addLayout(detail_box, 1)

        root.addLayout(body, 1)

        self.hint = QLabel("click an entry to view and edit it \u00b7 the arrow button flips the sort order")
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
            f"QListWidget::item:selected{{background:rgba(255,255,255,0.14);color:{color};}}"
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
        self.sort_btn.setStyleSheet(button_style(btn_color))
        self.save_btn.setStyleSheet(button_style(btn_color))
        self.list.setStyleSheet(self._list_style(btn_color))
        self.detail_key.setStyleSheet(
            f"color:{btn_color};font-family:monospace;font-size:13px;font-weight:bold;")
        self.detail_time.setStyleSheet(f"color:{DIM};font-family:monospace;font-size:9px;")
        self.detail_text.setStyleSheet(
            "QTextEdit{background:rgba(58,58,58,0.55);color:#eee;"
            "font-family:monospace;font-size:11px;border:1px solid #555;border-radius:4px;padding:6px;}")
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
        self._selected_key = None
        self._reload()

    def _toggle_sort(self):
        self._newest_first = not self._newest_first
        self.sort_btn.setText("\u2193 Newest first" if self._newest_first else "\u2191 Oldest first")
        self._reload()

    def _reload(self):
        if not self.bank_name:
            return
        try:
            data = load_memory_bank(self.bank_name)
        except Exception:
            data = {"entries": {}}

        self._entries = data.get("entries") or {}
        # each entry carries updated_at (a unix timestamp) from storage.py's
        # memory_set — that's what oldest/newest actually sorts on
        self._rows = sorted(
            self._entries.items(),
            key=lambda kv: kv[1].get("updated_at", 0),
            reverse=self._newest_first,
        )
        self.count_label.setText(f"{len(self._rows)} entr{'y' if len(self._rows) == 1 else 'ies'}")

        self.list.blockSignals(True)
        self.list.clear()
        restore_row = -1
        for i, (key, entry) in enumerate(self._rows):
            when = self._fmt_time(entry.get("updated_at"))
            item = QListWidgetItem(f"{i + 1:>3}.  {key}   \u00b7   {when}")
            self.list.addItem(item)
            if key == self._selected_key:
                restore_row = i
        self.list.blockSignals(False)

        if restore_row >= 0:
            self.list.setCurrentRow(restore_row)
        else:
            self._selected_key = None
            self.detail_key.setText("select an entry")
            self.detail_time.setText("")
            self.detail_text.clear()
            self.save_btn.setEnabled(False)

    def _show_detail(self, row):
        if row < 0 or row >= len(self._rows):
            return
        key, entry = self._rows[row]
        self._selected_key = key
        self.detail_key.setText(key)
        self.detail_time.setText(self._fmt_time(entry.get("updated_at")))
        self.detail_text.setPlainText(str(entry.get("value", "")))
        self.save_btn.setEnabled(True)

    def _save_edit(self):
        if not self._selected_key or not self.bank_name:
            return
        try:
            data = load_memory_bank(self.bank_name)
        except Exception:
            return
        entries = data.setdefault("entries", {})
        entry = entries.get(self._selected_key, {})
        # only the value and updated_at change on an edit -- expires_at stays
        # exactly as it was, so editing a entry never accidentally resets or
        # clears whatever expiry it already had
        entry["value"] = self.detail_text.toPlainText()
        import time
        entry["updated_at"] = time.time()
        entries[self._selected_key] = entry
        save_memory_bank(self.bank_name, data)
        self._reload()

    @staticmethod
    def _fmt_time(ts):
        if not ts:
            return "no timestamp"
        try:
            from datetime import datetime
            return datetime.fromtimestamp(ts).strftime("%d %b %H:%M:%S")
        except Exception:
            return str(ts)
