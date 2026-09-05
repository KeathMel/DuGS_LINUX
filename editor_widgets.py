"""
editor_widgets.py — small custom widgets the editor is built from.

  GripSplitter / _GripHandle : splitters with a visible 3-dot grab handle, so
                               the panel dividers are obvious and draggable.
  DragJsonTree               : the input JSON tree you can drag fields out of.
  DropLineEdit / DropTextEdit: parameter boxes that accept those drops and turn
                               them into {{ }} expressions.

Pulled out of editor.py because none of it depends on the Editor — it is just
reusable widget behaviour.
"""
from PyQt6.QtCore import Qt, QMimeData, QPoint
from PyQt6.QtGui import QPainter, QColor, QDrag
from PyQt6.QtWidgets import (
    QSplitter, QSplitterHandle, QTreeWidget, QLineEdit, QPlainTextEdit,
)


class _GripHandle(QSplitterHandle):
    """A splitter handle that paints 3 grip dots so it's obvious you can drag."""
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), _QColor("#242424"))
        p.setBrush(_QColor("#888")); p.setPen(Qt.PenStyle.NoPen)
        cx = self.width() / 2; cy = self.height() / 2
        if self.orientation() == Qt.Orientation.Horizontal:
            for dy in (-7, 0, 7):
                p.drawEllipse(int(cx - 1.5), int(cy + dy - 1.5), 3, 3)
        else:
            for dx in (-7, 0, 7):
                p.drawEllipse(int(cx + dx - 1.5), int(cy - 1.5), 3, 3)


class GripSplitter(QSplitter):
    def createHandle(self):
        return _GripHandle(self.orientation(), self)


# --- n8n-style drag-to-map: drag a field from the input tree, drop it into a
#     parameter box to insert its {{ }} reference at the cursor. -------------
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QLineEdit, QPlainTextEdit
from PyQt6.QtCore import QMimeData
from PyQt6.QtGui import QDrag



def _nfs(base):
    """Node-popup font size. Every widget in this file is built by the node
    popup, so they all follow the node text multiplier from the settings
    popup. Falls back to the raw size if home_screen is not importable."""
    try:
        from home_screen import fs
        return fs(base)
    except Exception:
        return base


class DragJsonTree(QTreeWidget):
    """A JSON tree whose rows can be dragged; the drag carries the field's
    {{ }} reference as text so it can be dropped into any param box."""
    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["field", "value"])
        self.setColumnWidth(0, 130)
        self.setDragEnabled(True)
        self.setStyleSheet(
            "QTreeWidget{background:rgba(10,10,10,0.5);color:#9fb;"
            f"font-family:monospace;font-size:{_nfs(10)}px;border:1px solid #444;}}"
            "QTreeWidget::item{padding:1px;}"
            # the header carries its own font, so it needs saying twice or the
            # "field"/"value" row stays small while the rows below it grow
            "QHeaderView::section{background:rgba(0,0,0,0.35);color:#aaa;"
            f"font-family:monospace;font-size:{_nfs(10)}px;border:none;padding:2px 4px;}}"
        )

    def startDrag(self, _actions):
        item = self.currentItem()
        if item is None:
            return
        ref = item.data(0, Qt.ItemDataRole.UserRole)
        if not ref:
            return
        if not str(ref).strip().startswith("{{"):
            ref = "{{ " + ref + " }}"
        md = QMimeData(); md.setText(ref)
        drag = QDrag(self); drag.setMimeData(md)
        drag.exec(Qt.DropAction.CopyAction)


class DropLineEdit(QLineEdit):
    """A line edit that accepts dropped {{ }} references at the cursor."""
    def __init__(self, *a, on_change=None, **k):
        super().__init__(*a, **k)
        self.setAcceptDrops(True); self._on_change = on_change
    def dragEnterEvent(self, e):
        if e.mimeData().hasText(): e.acceptProposedAction()
    def dropEvent(self, e):
        txt = e.mimeData().text()
        pos = self.cursorPositionAt(e.position().toPoint())
        cur = self.text()
        self.setText(cur[:pos] + txt + cur[pos:])
        e.acceptProposedAction()
        if self._on_change: self._on_change()


class DropTextEdit(QPlainTextEdit):
    """A multiline edit that accepts dropped {{ }} references at the cursor."""
    def __init__(self, *a, on_change=None, **k):
        super().__init__(*a, **k)
        self.setAcceptDrops(True); self._on_change = on_change
    def dragEnterEvent(self, e):
        if e.mimeData().hasText(): e.acceptProposedAction()
    def dragMoveEvent(self, e):
        if e.mimeData().hasText(): e.acceptProposedAction()
    def dropEvent(self, e):
        txt = e.mimeData().text()
        cursor = self.cursorForPosition(e.position().toPoint())
        cursor.insertText(txt)
        e.acceptProposedAction()
        if self._on_change: self._on_change()



# ---------------------------------------------------------------------------
# Expandable text box + hover-help label — used by the node popup so big text
# fields (Note, system prompt, Code, Text Template) can be edited comfortably
# and so parameter rows stay short with the explanation tucked into a tooltip.
# ---------------------------------------------------------------------------
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog,
)
from PyQt6.QtCore import Qt


class ExpandableText(QWidget):
    """A multiline box with an expand button at the top-right.

    Pressing expand opens the same text in a large movable panel so long
    content (a system prompt, a block of code, a note) can be edited without
    squinting at a tiny box. Editing either view keeps the other in sync.
    """

    def __init__(self, text="", on_change=None, title="TEXT"):
        super().__init__()
        self._on_change = on_change
        self._title = title

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addStretch()
        self.expand_btn = QPushButton("\u2921")   # diagonal expand arrows
        self.expand_btn.setFixedSize(20, 16)
        self.expand_btn.setToolTip("expand this box to a big editor")
        self.expand_btn.setStyleSheet(
            f"QPushButton{{font-size:{_nfs(11)}px;padding:0px;border:1px solid #555;"
            "color:#aaa;border-radius:3px;background:rgba(0,0,0,0.25);}"
            "QPushButton:hover{color:#fff;border-color:#999;}")
        self.expand_btn.clicked.connect(self._expand)
        bar.addWidget(self.expand_btn)
        lay.addLayout(bar)

        self.edit = DropTextEdit(text)
        self.edit.setFixedHeight(70)
        if on_change is not None:
            self.edit.textChanged.connect(on_change)
        lay.addWidget(self.edit)

    # behave enough like a text edit that existing code keeps working
    def toPlainText(self):
        return self.edit.toPlainText()

    def setPlainText(self, t):
        self.edit.setPlainText(t)

    @property
    def textChanged(self):
        return self.edit.textChanged

    def _expand(self):
        dlg = _ExpandDialog(self.edit.toPlainText(), self._title, self)
        dlg.exec()


class _ExpandDialog(QDialog):
    """The big pop-out editor. Sits against one side of the screen and can be
    flipped to the other side with the button in its top bar."""

    def __init__(self, text, title, source):
        super().__init__(source)
        self.source = source
        self.setWindowTitle(title)
        self.setModal(False)
        self._side = "right"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        tlabel = QLabel(title)
        tlabel.setStyleSheet(f"color:#ccc;font-family:monospace;font-size:{_nfs(11)}px;font-weight:bold;")
        bar.addWidget(tlabel)
        bar.addStretch()
        self.side_btn = QPushButton("\u21c4 side")   # flip left/right
        self.side_btn.setFixedHeight(20)
        self.side_btn.clicked.connect(self._flip_side)
        bar.addWidget(self.side_btn)
        close = QPushButton("done")
        close.setFixedHeight(20)
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        lay.addLayout(bar)

        self.big = DropTextEdit(text)
        self.big.setStyleSheet(f"font-family:monospace;font-size:{_nfs(13)}px;")
        lay.addWidget(self.big, 1)

        # editing the big box flows straight back into the little one
        self.big.textChanged.connect(self._sync_back)
        self._place()

    def _sync_back(self):
        self.source.setPlainText(self.big.toPlainText())

    def _flip_side(self):
        self._side = "left" if self._side == "right" else "right"
        self._place()

    def _place(self):
        scr = self.screen().availableGeometry() if self.screen() else None
        if scr is None:
            self.resize(600, 700)
            return
        w = scr.width() // 2
        self.resize(w, scr.height())
        y = scr.top()
        x = scr.left() if self._side == "left" else scr.left() + scr.width() - w
        self.move(x, y)


class HelpLabel(QWidget):
    """A parameter label with a small (?) that shows the explanation on hover,
    so the row stays short instead of carrying a long description inline."""

    def __init__(self, text, help_text="", accent="#7ecfff"):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:#bbb;font-family:monospace;font-size:{_nfs(11)}px;")
        lay.addWidget(lbl)
        if help_text:
            q = QLabel("(?)")
            # the QToolTip clause is not optional: without it the label's own
            # colour bleeds into its tooltip, giving accent-blue text on the
            # desktop's default yellow tooltip background.
            q.setStyleSheet(
                f"QLabel {{ color:{accent};font-family:monospace;font-size:{_nfs(10)}px; }}"
                f"QToolTip {{ background:#000;color:#fff;border:1px solid {accent};"
                f"border-radius:3px;padding:6px 8px;font-family:monospace;font-size:{_nfs(12)}px; }}"
            )
            q.setToolTip(help_text)
            q.setCursor(Qt.CursorShape.WhatsThisCursor)
            lay.addWidget(q)
        lay.addStretch()
