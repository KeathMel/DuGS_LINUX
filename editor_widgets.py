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
            "font-family:monospace;font-size:10px;border:1px solid #444;}"
            "QTreeWidget::item{padding:1px;}"
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


