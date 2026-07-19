"""
panel_base.py — the framework for editor panels.

The tools around the canvas (Nodes, Settings, Other Projects, Run Log,
JSON/CODE) are all panels. Each one lives in its own file in panels/ and is
discovered at startup, exactly like nodes are.

WRITING A PANEL
===============
Drop a file in panels/ with a class subclassing Panel:

    from panel_base import Panel
    from PyQt6.QtWidgets import QLabel

    class NotesPanel(Panel):
        ID    = "notes"          # unique, used in the saved layout
        TITLE = "NOTES"          # the little header label
        SIDE  = "left"           # left | right | bottom_right
        ORDER = 50               # position within its side (low = higher up)
        STRETCH = 1              # how much space it takes vs its neighbours

        def build(self):
            "Return the widget that goes inside the panel."
            return QLabel("hello")

That's it — restart and it appears. `self.editor` is the Editor, so a panel can
reach the canvas, the current project, the API, whatever it needs.

OPTIONAL HOOKS
==============
    on_project_opened(name)   project was opened/switched
    on_selection_changed(node) a node was selected (None when deselected)
    on_workflow_changed()     the graph changed (node added/moved/edited)
    on_run_event(evt)         a live run event arrived
    refresh()                 asked to redraw itself
    apply_theme(css, colors)  the appearance settings changed

Every hook is optional; leave out what you don't need. Panels that raise are
logged and skipped rather than taking the editor down.
"""
import os
import sys
import inspect
import importlib.util

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout


class Panel:
    """Base class for a tool panel around the canvas."""

    ID = "panel"
    TITLE = "PANEL"
    SIDE = "left"          # left | right | bottom_right
    ORDER = 100
    STRETCH = 1
    CLOSABLE = True        # can the user hide it
    SHOW_HEADER = True     # draw the little TITLE label above the content

    def __init__(self, editor):
        self.editor = editor
        self.widget = None      # the built content widget
        self.container = None   # header + content wrapper

    # ---- the one thing every panel must implement ----
    def build(self) -> QWidget:
        raise NotImplementedError(f"{type(self).__name__} must implement build()")

    # ---- optional hooks, all no-ops by default ----
    def on_project_opened(self, name): pass
    def on_selection_changed(self, node): pass
    def on_workflow_changed(self): pass
    def on_run_event(self, evt): pass
    def refresh(self): pass
    def apply_theme(self, css, colors): pass

    # ---- header widgets a panel can add next to its title (e.g. a copy button)
    def header_widgets(self) -> list:
        return []


def discover_panels(panels_dir: str) -> list:
    """Load every Panel subclass out of panels/, sorted by SIDE then ORDER."""
    found = []
    if not os.path.isdir(panels_dir):
        return found
    parent = os.path.dirname(panels_dir)
    for fname in sorted(os.listdir(panels_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(panels_dir, fname)
        try:
            if panels_dir not in sys.path:
                sys.path.insert(0, panels_dir)
            if parent not in sys.path:
                sys.path.insert(0, parent)
            spec = importlib.util.spec_from_file_location(f"panel_{fname[:-3]}", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Panel) and obj is not Panel and hasattr(obj, "ID"):
                    found.append(obj)
        except Exception as e:
            print(f"  [panel warn] could not load {fname}: {e}")
    found.sort(key=lambda c: (c.SIDE, c.ORDER))
    return found


def wrap_panel(panel: Panel, tag_fn=None) -> QWidget:
    """Build a panel and put its TITLE header above it, matching the existing
    editor styling. `tag_fn` is the editor's _tag() so headers look identical.

    The container is given an opaque background: the app window is translucent,
    so a widget that paints nothing lets the previous frame show through and the
    UI smears on top of itself.
    """
    content = panel.build()
    panel.widget = content

    box = QWidget()
    box.setObjectName(f"panelbox_{panel.ID}")   # so CSS can target only this
    # opaque background: the app window is translucent, so a panel that paints
    # nothing lets the previous frame show through and the UI smears
    box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    box.setAutoFillBackground(True)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(4, 4, 4, 4)
    lay.setSpacing(4)

    if panel.SHOW_HEADER:
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        if tag_fn is not None:
            head.addWidget(tag_fn(panel.TITLE))
        else:
            lbl = QLabel(panel.TITLE)
            lbl.setStyleSheet("color:#888;font-family:monospace;font-size:9px;")
            head.addWidget(lbl)
        head.addStretch()
        for w in panel.header_widgets():
            head.addWidget(w)
        lay.addLayout(head)

    lay.addWidget(content, 1)
    panel.container = box
    return box
