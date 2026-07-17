"""
ui.py — the dugs face. This file is now just the entry point: it wires
together the three screens (Home, Editor, TabelEditor) into one stacked
window. All the actual logic lives in separate modules:

  theme.py           — colors, stylesheet
  api_client.py       — HTTP calls to api.py
  storage.py          — local project/tabel file I/O
  home_screen.py      — Projects | Tabels landing screen
  tabel_editor.py     — spreadsheet grid editor
  canvas.py           — node graph drawing/dragging/wiring
  editor_settings.py  — the right-hand settings panel (mixin)
  editor.py           — the workflow editor screen shell

Run:  Terminal 1: python3 api.py    Terminal 2: python3 ui.py
(Hyprland fallback: GDK_BACKEND=x11 python3 ui.py)
"""
from __future__ import annotations
import sys

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QStackedWidget
from PyQt6.QtCore import Qt

from theme import STYLESHEET
from storage import PROJECTS_DIR, TABELS_DIR, _ensure
from home_screen import Home
from tabel_editor import TabelEditor
from editor import Editor


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("dugs"); self.resize(1200, 760)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.stack = QStackedWidget()
        self.home = Home(self); self.editor = Editor(self); self.tabel = TabelEditor(self)
        for w in (self.home, self.editor, self.tabel): self.stack.addWidget(w)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.stack)
        self.setStyleSheet(STYLESHEET)
        self.go_home()

    def toast(self, msg):
        try: self.editor.results.setText(msg)
        except Exception: pass
        print("  dugs:", msg)

    def go_home(self):
        self.home.refresh(); self.stack.setCurrentWidget(self.home)

    def open_project(self, name):
        self.editor.open_project(name); self.stack.setCurrentWidget(self.editor)

    def open_tabel(self, name):
        self.tabel.open(name); self.stack.setCurrentWidget(self.tabel)


if __name__ == "__main__":
    _ensure(PROJECTS_DIR); _ensure(TABELS_DIR)
    app = QApplication(sys.argv)
    w = App(); w.show()
    sys.exit(app.exec())
