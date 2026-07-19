"""
panel_base.py — the module/panel system for the editor.

TWO CONCEPTS
============
A MODULE is a tool: the node palette, the settings form, the run log, the
JSON/code view. Each lives in its own file in panels/ and is discovered at
startup, exactly like nodes are.

A PANEL is a container down one edge of the editor (left, right or bottom).
Panels start EMPTY. You pull one open with the arrow on its edge, press its
[+] button, and tick which modules go in it. A panel can hold several modules
stacked, resizable against each other by the three-dot grip lines between them.

WRITING A MODULE
================
Drop a file in panels/ with a class subclassing Panel:

    from panel_base import Panel
    from PyQt6.QtWidgets import QLabel

    class NotesModule(Panel):
        ID    = "notes"        # unique, used when saving the layout
        TITLE = "NOTES"        # shown in the header and in the [+] list
        SIDE  = "left"         # default side if nothing is saved yet
        ORDER = 50             # order within that side
        STRETCH = 1            # share of space vs its neighbours

        def build(self):
            return QLabel("hello")

`self.editor` is the Editor, so a module can reach the canvas, the current
project, the API, whatever it needs.

OPTIONAL HOOKS
==============
    on_project_opened(name)    project opened/switched
    on_selection_changed(node) a node was selected (None = deselected)
    on_workflow_changed()      the graph changed
    on_run_event(evt)          a live run event arrived
    refresh()                  redraw yourself
    apply_theme(css, colors)   appearance settings changed
    header_widgets()           extra buttons to sit beside the title

All optional. A module that raises is logged and skipped rather than taking the
editor down.
"""
import os
import sys
import inspect
import importlib.util

from PyQt6.QtCore import Qt, QPoint, QEvent
from PyQt6.QtGui import QPainter, QColor, QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QSplitterHandle, QMenu,
)


# --------------------------------------------------------------- MODULE BASE
class Panel:
    """Base class for a module that can sit inside a panel."""

    ID = "panel"
    TITLE = "PANEL"
    SIDE = "left"          # left | right | bottom
    ORDER = 100
    STRETCH = 1
    SHOW_HEADER = True

    def __init__(self, editor):
        self.editor = editor
        self.widget = None      # the built content widget
        self.container = None   # the ModuleFrame wrapping it
        self.host = None        # the panel currently holding it

    def build(self) -> QWidget:
        raise NotImplementedError(f"{type(self).__name__} must implement build()")

    # optional hooks
    def on_project_opened(self, name): pass
    def on_selection_changed(self, node): pass
    def on_workflow_changed(self): pass
    def on_run_event(self, evt): pass
    def refresh(self): pass
    def apply_theme(self, css, colors): pass
    def header_widgets(self) -> list: return []


def discover_modules(panels_dir: str) -> list:
    """Load every Panel subclass out of panels/."""
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
            print(f"  [module warn] could not load {fname}: {e}")
    found.sort(key=lambda c: (c.SIDE, c.ORDER))
    return found


# ---------------------------------------------------------------- DOT GRIPS
def _draw_dots(widget, painter, horizontal, count=3, gap=5, alpha=120):
    """Three little dots, used everywhere something is draggable."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, alpha))
    cx, cy = widget.width() / 2, widget.height() / 2
    span = range(-(count // 2), count // 2 + 1)
    for i in span:
        if horizontal:
            painter.drawEllipse(QPoint(int(cx + i * gap), int(cy)), 1, 1)
        else:
            painter.drawEllipse(QPoint(int(cx), int(cy + i * gap)), 1, 1)


class _DotHandle(QSplitterHandle):
    """Splitter handle with three dots, so it is obvious you can drag it."""

    def paintEvent(self, _):
        p = QPainter(self)
        horizontal = (self.orientation() == Qt.Orientation.Vertical)
        _draw_dots(self, p, horizontal)


class DotSplitter(QSplitter):
    """Splitter whose handles show the three-dot grip."""

    def createHandle(self):
        return _DotHandle(self.orientation(), self)


class GripDots(QWidget):
    """The three-dot grab indicator in a module header."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(12, 16)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.setToolTip("hold middle mouse button here to move this module")

    def paintEvent(self, _):
        p = QPainter(self)
        _draw_dots(self, p, horizontal=False, gap=4)


# ------------------------------------------------------------ MODULE FRAME
class ModuleFrame(QWidget):
    """One module inside a panel: a header (grip dots + title + buttons) with
    the module's own widget below it.

    Middle-mouse-drag anywhere on the frame to move the module to another
    panel — the drop target is whichever panel is under the cursor on release.
    """

    def __init__(self, module, panel, editor):
        super().__init__()
        self.module = module
        self.panel = panel
        self.editor = editor
        self._drag_from = None
        self.setObjectName(f"modframe_{module.ID}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(3)

        if module.SHOW_HEADER:
            head = QWidget()
            head.setFixedHeight(18)
            hl = QHBoxLayout(head)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            hl.addWidget(GripDots())
            title = QLabel(module.TITLE)
            title.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:9px;")
            hl.addWidget(title)
            hl.addStretch()
            for w in module.header_widgets():
                hl.addWidget(w)
            lay.addWidget(head)

        content = module.build()
        module.widget = content
        module.container = self
        module.host = panel
        lay.addWidget(content, 1)

        # Mouse events land on whichever child is under the cursor (a list, a
        # text box), so they never reach this frame. Watching the frame and
        # every descendant means the middle-button drag works anywhere on the
        # module, not just the few pixels of bare header.
        self._watch(self)

    def _watch(self, w):
        w.installEventFilter(self)
        for child in w.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj, e):
        et = e.type()
        if et == QEvent.Type.MouseButtonPress:
            if e.button() == Qt.MouseButton.MiddleButton:
                self._drag_from = e.globalPosition().toPoint()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                return True          # swallow it so the child ignores it
        elif et == QEvent.Type.MouseButtonRelease:
            if e.button() == Qt.MouseButton.MiddleButton and self._drag_from is not None:
                self.unsetCursor()
                self._drag_from = None
                target = self.editor.panel_at_global(e.globalPosition().toPoint())
                if target is not None and target is not self.panel:
                    self.editor.move_module(self.module, target)
                return True
        return super().eventFilter(obj, e)


# ----------------------------------------------------------------- PANEL BOX
class PanelBox(QWidget):
    """A container down one edge of the editor.

    Starts empty and collapsed. The [+] at the bottom lists every discovered
    module with a tick — ticking adds it to this panel, unticking removes it
    again, so you build the layout you want instead of getting a fixed one.
    """

    def __init__(self, side, editor):
        super().__init__()
        self.side = side               # left | right | bottom
        self.editor = editor
        self.modules = []              # Panel instances currently held
        self.setObjectName(f"panelbox_{side}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        # modules stack vertically on the sides, horizontally along the bottom
        orient = (Qt.Orientation.Horizontal if side == "bottom"
                  else Qt.Orientation.Vertical)
        self.stack = DotSplitter(orient)
        self.stack.setChildrenCollapsible(True)
        self.stack.setHandleWidth(8)
        outer.addWidget(self.stack, 1)

        # the [+] strip: what this panel is showing, and how to change it
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 0, 4, 3)
        bar.setSpacing(4)
        self.plus = QPushButton("+")
        self.plus.setFixedSize(18, 16)
        self.plus.setToolTip("choose which modules this panel shows")
        self.plus.setStyleSheet(
            "QPushButton{font-size:11px;padding:0px;border:1px solid #666;"
            "color:#aaa;border-radius:3px;background:rgba(0,0,0,0.25);}"
            "QPushButton:hover{color:#fff;border-color:#999;}")
        self.plus.clicked.connect(self.show_module_menu)
        bar.addWidget(self.plus)
        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#777;font-family:monospace;font-size:8px;")
        bar.addWidget(self.summary)
        bar.addStretch()
        outer.addLayout(bar)

        self._refresh_summary()

    # ---- module management -------------------------------------------------
    def add_module(self, module):
        if module in self.modules:
            return
        frame = ModuleFrame(module, self, self.editor)
        self.stack.addWidget(frame)
        self.modules.append(module)
        self._apply_stretch()
        self._refresh_summary()

    def remove_module(self, module):
        if module not in self.modules:
            return
        if module.container is not None:
            module.container.setParent(None)
            module.container.deleteLater()
        module.container = None
        module.host = None
        self.modules.remove(module)
        self._refresh_summary()

    def _apply_stretch(self):
        sizes = []
        total = sum(max(1, m.STRETCH) for m in self.modules) or 1
        span = (self.width() if self.side == "bottom" else self.height()) or 400
        for m in self.modules:
            sizes.append(int(span * max(1, m.STRETCH) / total))
        if sizes:
            self.stack.setSizes(sizes)

    def _refresh_summary(self):
        if self.modules:
            self.summary.setText(" · ".join(m.TITLE.lower() for m in self.modules))
        else:
            self.summary.setText("empty — press + to add a module")

    # ---- the [+] menu ------------------------------------------------------
    def show_module_menu(self):
        """List every module with a tick showing whether this panel has it."""
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#1e1e1e;color:#ddd;font-family:monospace;"
            "font-size:11px;border:1px solid #555;}"
            "QMenu::item:selected{background:#333;}")
        mine = {m.ID for m in self.modules}
        for mod in self.editor.all_modules:
            act = menu.addAction(mod.TITLE)
            act.setCheckable(True)
            act.setChecked(mod.ID in mine)
            # elsewhere = held by a different panel, so say so
            if mod.ID not in mine and mod.host is not None:
                act.setText(f"{mod.TITLE}   (in {mod.host.side})")
            act.triggered.connect(
                lambda checked, m=mod: self.editor.toggle_module(m, self, checked))
        if not self.editor.all_modules:
            a = menu.addAction("no modules found in panels/")
            a.setEnabled(False)
        menu.exec(self.plus.mapToGlobal(QPoint(0, -menu.sizeHint().height())))


# ------------------------------------------------------------- EDGE ARROW
class EdgeArrow(QPushButton):
    """The little arrow on an edge that pulls its panel open or shut."""

    def __init__(self, side, on_toggle):
        super().__init__()
        self.side = side
        self.open = False
        self.on_toggle = on_toggle
        if side == "bottom":
            self.setFixedSize(34, 12)
        else:
            self.setFixedSize(12, 34)
        self.setStyleSheet(
            "QPushButton{border:none;background:rgba(255,255,255,0.06);"
            "color:#999;font-size:9px;padding:0px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.14);color:#fff;}")
        self.clicked.connect(self._clicked)
        self._sync()

    def _clicked(self):
        self.open = not self.open
        self._sync()
        self.on_toggle(self.side, self.open)

    def set_open(self, is_open):
        self.open = is_open
        self._sync()

    def _sync(self):
        arrows = {
            ("left", False): "\u203a",   # ›
            ("left", True): "\u2039",    # ‹
            ("right", False): "\u2039",
            ("right", True): "\u203a",
            ("bottom", False): "\u2039",
            ("bottom", True): "\u203a",
        }
        self.setText(arrows.get((self.side, self.open), "\u203a"))
        self.setToolTip(f"{'hide' if self.open else 'show'} the {self.side} panel")
