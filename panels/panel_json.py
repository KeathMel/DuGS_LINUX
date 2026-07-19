"""
JSON / CODE panel — bottom right.

Shows the workflow as JSON for normal projects, or the live-generated Arduino
code for servo projects (the header flips between JSON and CODE). The copy
button next to the title copies whatever is showing.

This panel demonstrates header_widgets(): anything returned there is placed
next to the title, which is how the copy button gets up there.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QTextEdit, QPushButton
from PyQt6.QtCore import Qt
from panel_base import Panel


class JsonCodePanel(Panel):
    ID = "json"
    TITLE = "JSON"
    SIDE = "bottom"
    ORDER = 20
    STRETCH = 2

    def build(self):
        view = QTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet(
            "background: rgba(10,10,10,0.5); color:#9fb; "
            "font-family:monospace; font-size:9px; border:1px solid #444;")
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.editor.json_view = view
        return view

    def header_widgets(self):
        btn = QPushButton("⎘ copy")
        btn.setFixedSize(54, 18)
        btn.setStyleSheet("font-size:9px; padding:0px 4px; border:1px solid #444;"
                          "color:#888; border-radius:3px;")
        btn.clicked.connect(self._copy)
        return [btn]

    def _copy(self):
        try:
            self.editor._copy_json()
        except Exception:
            pass

    def on_workflow_changed(self):
        try:
            self.editor.refresh_json()
        except Exception:
            pass

    def apply_theme(self, css, colors):
        # colors[0] is already transparent when 'no background' is on, so the
        # same code path gives a solid panel or a see-through one
        if self.widget is not None and css:
            # keep the greenish code colour, only swap background/border
            if colors:
                panel, _text, border = colors
                self.widget.setStyleSheet(
                    f"background:{panel}; color:#9fb; font-family:monospace; "
                    f"font-size:9px; border:1px solid {border};")
