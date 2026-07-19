"""
Nodes panel — the palette you drag nodes from, with a search box.

Sits top right. The grouping logic (TRIGGERS / LOGIC / DATA / ... for normal
projects, FLOW / SERVO / SCREEN / ... for servo projects) lives in
editor.load_palette(); this panel provides the search box and list it fills.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget
from panel_base import Panel


class NodesPanel(Panel):
    ID = "nodes"
    TITLE = "NODES"
    SIDE = "right"
    ORDER = 10
    STRETCH = 3

    def build(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        search = QLineEdit()
        search.setPlaceholderText("search nodes...")
        search.textChanged.connect(self.editor.filter_palette)
        lay.addWidget(search)

        lst = QListWidget()
        lst.setStyleSheet("QListWidget::item { padding: 0px; }")
        lst.itemClicked.connect(self.editor.drop_node)
        lay.addWidget(lst, 1)

        # editor.load_palette() fills these by name
        self.editor.palette_search = search
        self.editor.palette = lst
        return box

    def on_project_opened(self, name):
        # the palette changes between normal and servo projects
        try:
            self.editor.load_palette()
        except Exception:
            pass

    def apply_theme(self, css, colors):
        # colors[0] is already transparent when 'no background' is on, so the
        # same code path gives a solid panel or a see-through one
        if colors and getattr(self.editor, "palette", None) is not None:
            panel, text, border = colors
            self.editor.palette.setStyleSheet(
                f"QListWidget{{background:{panel};color:{text};"
                f"border:1px solid {border};}}"
                "QListWidget::item{padding:0px;}")
            if getattr(self.editor, "palette_search", None) is not None:
                self.editor.palette_search.setStyleSheet(
                    f"QLineEdit{{background:{panel};color:{text};"
                    f"border:1px solid {border};padding:3px;}}")
