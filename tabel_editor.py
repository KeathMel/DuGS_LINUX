"""
tabel_editor.py — Google-Sheets-style grid editor for Tabels.

Shares the same customizable "skin" as home_screen.py: grey background by
default, white buttons, a blue logo — all changeable from the gear icon in
the bottom-left corner, which opens the same settings popup used on the home
screen (settings live in home_ui_settings.json, so changing them in one
place changes them everywhere).
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QInputDialog, QMenu
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from theme import DIM
from storage import load_tabel, save_tabel
from home_screen import (
    load_home_ui_settings, HomeSettingsDialog,
    DEFAULT_BUTTON_COLOR, DEFAULT_LOGO_COLOR,
    button_style, paint_flat_or_image_bg, register_themed_screen,
)


class TabelEditor(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app; self.current = None
        self.settings = load_home_ui_settings()
        root = QVBoxLayout(self); root.setContentsMargins(16, 12, 16, 16); root.setSpacing(8)

        bar = QHBoxLayout()
        self.dugs = QLabel("DuGS")
        self.dugs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dugs.mousePressEvent = lambda _e: self.app.go_home()
        bar.addWidget(self.dugs)
        self.title = QLabel("-")
        bar.addSpacing(16); bar.addWidget(self.title); bar.addStretch()
        self.add_col_btn = QPushButton("+ Column"); self.add_col_btn.clicked.connect(self.add_column)
        self.add_row_btn = QPushButton("+ Row"); self.add_row_btn.clicked.connect(self.add_row)
        self.save_btn = QPushButton("Save"); self.save_btn.clicked.connect(self.save)
        for b in (self.add_col_btn, self.add_row_btn, self.save_btn): bar.addWidget(b)
        root.addLayout(bar)

        self.table = QTableWidget()
        self.table.itemChanged.connect(self._cell_changed)
        root.addWidget(self.table, 1)

        self.hint = QLabel("double-click a header to rename a column · right-click a row number to delete")
        self.hint.setStyleSheet(f"color:{DIM};font-family:monospace;font-size:9px;")
        root.addWidget(self.hint)

        self.table.horizontalHeader().sectionDoubleClicked.connect(self.rename_column)
        self.table.verticalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.verticalHeader().customContextMenuRequested.connect(self.row_menu)
        self._loading = False

        # settings gear, pinned bottom-left — same popup as the home screen
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
    def _table_style(self, color):
        return (
            "QTableWidget{background:rgba(58,58,58,0.55);color:#eee;gridline-color:#555;"
            "font-family:monospace;border:1px solid #555;}"
            f"QHeaderView::section{{background:rgba(30,30,30,0.8);color:{color};"
            "border:1px solid #555;padding:4px;font-family:monospace;}"
            "QTableWidget::item:selected{background:rgba(255,255,255,0.14);}"
        )

    def apply_theme(self):
        """(Re)apply button/logo colors, table styling, and background from
        self.settings. Called at startup and again after the shared settings
        dialog is saved."""
        btn_color = self.settings.get("button_color", DEFAULT_BUTTON_COLOR)
        logo_color = self.settings.get("logo_color", DEFAULT_LOGO_COLOR)

        self.dugs.setStyleSheet(f"color:{logo_color};font-family:monospace;font-size:20px;font-weight:bold;")
        self.title.setStyleSheet(f"color:{btn_color};font-family:monospace;font-size:14px;")
        for b in (self.add_col_btn, self.add_row_btn, self.save_btn):
            b.setStyleSheet(button_style(btn_color))
        self.settings_btn.setStyleSheet(button_style(btn_color, circular=True))
        self.table.setStyleSheet(self._table_style(btn_color))

        self.update()  # repaint background (grey / image / see-through)

    def open_settings(self):
        dlg = HomeSettingsDialog(self, self)
        dlg.exec()

    def paintEvent(self, event):
        """Same background behavior as the home screen: chosen image, flat
        grey, or fully see-through."""
        if not paint_flat_or_image_bg(self, event, self.settings):
            super().paintEvent(event)
            return
        super().paintEvent(event)

    # -- table logic -----------------------------------------------------------
    def open(self, name):
        self.current = name; self.title.setText(name)
        self.data = load_tabel(name)
        self.rebuild()

    def rebuild(self):
        self._loading = True
        cols = self.data.get("columns", [])
        rows = self.data.get("rows", [])
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(rows))
        self.table.setVerticalHeaderLabels([str(r.get("id", i + 1)) for i, r in enumerate(rows)])
        for ri, row in enumerate(rows):
            for ci, c in enumerate(cols):
                val = row.get(c)
                self.table.setItem(ri, ci, QTableWidgetItem("" if val is None else str(val)))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._loading = False

    def _cell_changed(self, item):
        if self._loading: return
        cols = self.data["columns"]
        ri, ci = item.row(), item.column()
        if ri < len(self.data["rows"]) and ci < len(cols):
            self.data["rows"][ri][cols[ci]] = item.text()

    def add_column(self):
        name, ok = QInputDialog.getText(self, "New Column", "Column name:")
        if ok and name.strip():
            name = name.strip()
            if name in self.data["columns"] or name == "id": return
            self.data["columns"].append(name)
            for r in self.data["rows"]: r[name] = ""
            self.rebuild()

    def add_row(self):
        row = {"id": len(self.data["rows"]) + 1}
        for c in self.data["columns"]: row[c] = ""
        self.data["rows"].append(row); self.rebuild()

    def rename_column(self, idx):
        cols = self.data["columns"]
        if idx >= len(cols): return
        old = cols[idx]
        new, ok = QInputDialog.getText(self, "Rename Column", "Name:", text=old)
        if ok and new.strip() and new.strip() != old:
            new = new.strip()
            cols[idx] = new
            for r in self.data["rows"]:
                r[new] = r.pop(old, "")
            self.rebuild()

    def row_menu(self, pos):
        ri = self.table.verticalHeader().logicalIndexAt(pos)
        if ri < 0: return
        m = QMenu(self)
        act = QAction("Delete row", self)
        act.triggered.connect(lambda: self._del_row(ri))
        m.addAction(act)
        m.exec(self.table.verticalHeader().mapToGlobal(pos))

    def _del_row(self, ri):
        if 0 <= ri < len(self.data["rows"]):
            del self.data["rows"][ri]; self.rebuild()

    def save(self):
        if not self.current: return
        save_tabel(self.current, self.data)
        self.open(self.current)
        self.app.toast(f"saved Tabel {self.current}")
