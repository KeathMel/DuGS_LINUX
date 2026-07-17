"""
tabel_editor.py — Google-Sheets-style grid editor for Tabels.
"""
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QInputDialog, QMenu
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from theme import ACCENT, DIM
from storage import load_tabel, save_tabel


class TabelEditor(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app; self.current = None
        root = QVBoxLayout(self); root.setContentsMargins(16, 12, 16, 16); root.setSpacing(8)

        bar = QHBoxLayout()
        dugs = QLabel("dugs"); dugs.setStyleSheet(f"color:{ACCENT};font-family:monospace;font-size:20px;")
        dugs.setCursor(Qt.CursorShape.PointingHandCursor)
        dugs.mousePressEvent = lambda _e: self.app.go_home()
        bar.addWidget(dugs)
        self.title = QLabel("-"); self.title.setStyleSheet(f"color:{ACCENT};font-family:monospace;font-size:14px;")
        bar.addSpacing(16); bar.addWidget(self.title); bar.addStretch()
        add_col = QPushButton("+ Column"); add_col.clicked.connect(self.add_column)
        add_row = QPushButton("+ Row"); add_row.clicked.connect(self.add_row)
        save = QPushButton("Save"); save.clicked.connect(self.save)
        for b in (add_col, add_row, save): bar.addWidget(b)
        root.addLayout(bar)

        self.table = QTableWidget()
        self.table.setStyleSheet(
            "QTableWidget{background:rgba(12,12,12,0.55);color:#eee;gridline-color:#444;"
            "font-family:monospace;border:1px solid #444;}"
            f"QHeaderView::section{{background:rgba(20,20,20,0.8);color:{ACCENT};"
            "border:1px solid #444;padding:4px;font-family:monospace;}}"
            "QTableWidget::item:selected{background:rgba(126,207,255,0.18);}")
        self.table.itemChanged.connect(self._cell_changed)
        root.addWidget(self.table, 1)

        self.hint = QLabel("double-click a header to rename a column · right-click a row number to delete")
        self.hint.setStyleSheet(f"color:{DIM};font-family:monospace;font-size:9px;")
        root.addWidget(self.hint)

        self.table.horizontalHeader().sectionDoubleClicked.connect(self.rename_column)
        self.table.verticalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.verticalHeader().customContextMenuRequested.connect(self.row_menu)
        self._loading = False

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
