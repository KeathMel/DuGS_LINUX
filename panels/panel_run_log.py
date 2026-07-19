"""
Run Log panel — the scrolling output from a run, an export, or a simulation.

Sits bottom-left under Other Projects. This is the panel everything writes
status into, so the editor keeps a direct reference to the text box as
`editor.results` (the rest of the editor writes to it by that name).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QTextEdit
from panel_base import Panel


class RunLogPanel(Panel):
    ID = "run_log"
    TITLE = "RUN LOG"
    SIDE = "left"
    ORDER = 30          # settings(10) -> projects(20) -> log(30)
    STRETCH = 2

    def build(self):
        box = QTextEdit()
        box.setReadOnly(True)
        box.setStyleSheet(
            "background: rgba(10,10,10,0.5); color:#ddd; "
            "font-family:monospace; font-size:9px; border:1px solid #444;")
        # the editor writes status here from many places, so expose it under
        # the name the rest of the code already uses
        self.editor.results = box
        return box

    def apply_theme(self, css, colors):
        # colors[0] is already transparent when 'no background' is on, so the
        # same code path gives a solid panel or a see-through one
        if self.widget is not None and css:
            self.widget.setStyleSheet(css)
