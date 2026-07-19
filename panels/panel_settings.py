"""
Settings panel — the parameters of whichever node is selected.

Sits top-left. The actual form rendering lives in editor_settings.py
(SettingsPanelMixin.show_node_settings); this panel just provides the scroll
area it fills.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QScrollArea, QWidget, QVBoxLayout
from panel_base import Panel


class SettingsPanel(Panel):
    ID = "settings"
    TITLE = "SETTINGS"
    SIDE = "left"
    ORDER = 10          # topmost on the left
    STRETCH = 3         # biggest of the left panels

    def build(self):
        area = QScrollArea()
        area.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.addStretch()
        area.setWidget(host)
        # editor_settings.py fills these in when a node is selected
        self.editor.settings_area = area
        self.editor.settings_host = host
        self.editor.settings_layout = layout
        return area

    def on_selection_changed(self, node):
        try:
            self.editor.show_node_settings(node)
        except Exception:
            pass

    def apply_theme(self, css, colors):
        # colors[0] is already transparent when 'no background' is on, so the
        # same code path gives a solid panel or a see-through one
        if self.widget is None or not colors:
            return
        panel, text, border = colors
        # style the scroll area and its inner host, and make the child form
        # widgets inherit the text colour instead of staying hard-coded
        self.widget.setStyleSheet(
            f"QScrollArea{{background:{panel};border:1px solid {border};}}"
            f"QScrollArea > QWidget > QWidget{{background:transparent;}}"
            f"QLabel{{color:{text};background:transparent;}}")
