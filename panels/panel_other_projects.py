"""
Other Projects panel — the list of your other workflows, click one to switch.

Sits on the left between Settings and the Run Log. Saves the current project
before switching, so you never lose work by clicking away.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QListWidget, QListWidgetItem
from panel_base import Panel


class OtherProjectsPanel(Panel):
    ID = "other_projects"
    TITLE = "OTHER PROJECTS"
    SIDE = "left"
    ORDER = 20
    STRETCH = 1

    def build(self):
        lst = QListWidget()
        lst.itemClicked.connect(self.editor.switch_project)
        # the editor refreshes this list by name after saves/renames
        self.editor.other_projects = lst
        return lst

    def on_project_opened(self, name):
        self.refresh()

    def refresh(self):
        try:
            self.editor.refresh_other_projects()
        except Exception:
            pass

    def apply_theme(self, css, colors):
        # colors[0] is already transparent when 'no background' is on, so the
        # same code path gives a solid panel or a see-through one
        if self.widget is not None and colors:
            panel, text, border = colors
            self.widget.setStyleSheet(
                f"QListWidget{{background:{panel};color:{text};"
                f"border:1px solid {border};}}"
                f"QListWidget::item{{color:{text};}}")
