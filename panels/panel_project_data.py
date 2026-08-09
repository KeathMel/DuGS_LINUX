"""
Tabels & Memory panel — the Tabels and Memory Banks the CURRENT workflow
uses. Scans the canvas live (not just the last save), so it's always
right, even before you've hit Save. Click one to open it.

Sits on the left, same family as Other Projects.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget, QListWidgetItem
from panel_base import Panel


class ProjectDataPanel(Panel):
    ID = "project_data"
    TITLE = "TABELS & MEMORY"
    SIDE = "left"
    ORDER = 25
    STRETCH = 1

    def build(self):
        lst = QListWidget()
        lst.itemDoubleClicked.connect(self._open_item)
        self.widget = lst
        return lst

    def on_project_opened(self, name):
        self.refresh()

    def on_workflow_changed(self):
        self.refresh()

    def refresh(self):
        try:
            self._reload()
        except Exception:
            pass

    def _reload(self):
        ed = self.editor
        if self.widget is None:
            return
        self.widget.clear()

        if not ed.current_project:
            item = QListWidgetItem("(no project open)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.widget.addItem(item)
            return

        from storage import workflow_dependencies
        # the LIVE canvas, not the last save -- so a Tabel/Memory node you
        # just dragged in shows up immediately, not after the next autosave
        wf = ed.canvas.to_workflow(ed.current_project)
        tabels, banks = workflow_dependencies(wf.get("nodes", []))

        if not tabels and not banks:
            item = QListWidgetItem("(this project doesn't use any)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.widget.addItem(item)
            return

        if tabels:
            self._add_header("TABELS")
            for t in sorted(tabels):
                self._add_entry(t, "tabel")

        if banks:
            self._add_header("MEMORY BANKS")
            for b in sorted(banks):
                self._add_entry(b, "memory")

    def _add_header(self, text):
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)   # a label, not clickable
        self.widget.addItem(item)

    def _add_entry(self, name, kind):
        item = QListWidgetItem(f"  {name}")
        item.setData(Qt.ItemDataRole.UserRole, (kind, name))
        item.setToolTip("double-click to open")
        self.widget.addItem(item)

    def _open_item(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, name = data
        ed = self.editor
        app = getattr(ed, "app", None)
        if app is None:
            return
        # save first, same instinct as switching projects -- so navigating
        # away to look at a Tabel never quietly drops unsaved node edits
        try:
            ed.save()
        except Exception:
            pass
        if kind == "tabel" and hasattr(app, "open_tabel"):
            app.open_tabel(name)
        elif kind == "memory" and hasattr(app, "open_memory"):
            app.open_memory(name)

    def apply_theme(self, css, colors):
        # colors[0] is already transparent when 'no background' is on, so the
        # same code path gives a solid panel or a see-through one
        if self.widget is not None and colors:
            panel, text, border = colors
            self.widget.setStyleSheet(
                f"QListWidget{{background:{panel};color:{text};"
                f"border:1px solid {border};}}"
                f"QListWidget::item{{color:{text};}}")
