"""
editor.py — the workflow editor screen: palette, canvas, JSON preview,
run/save controls. Settings-panel rendering lives in editor_settings.py
(mixed in here) since that part changes most often.
"""
import json
import os

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QScrollArea, QApplication,
    QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QKeySequence, QShortcut, QColor, QImage

from theme import ACCENT, API
from api_client import api_get, api_post, api_post_stream
from storage import list_projects, load_project, save_project, load_ui_state, save_ui_state
from canvas import Canvas, node_pixmap
from editor_settings import SettingsPanelMixin

from PyQt6.QtWidgets import QSplitterHandle
from PyQt6.QtGui import QPainter, QColor as _QColor


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


class SimWorker(QThread):
    """Runs a robotics graph simulation in the background, streaming what the
    board would be doing (servo moves, pin writes, delays) so you can watch it
    play out live without any hardware."""
    event = pyqtSignal(dict)

    def __init__(self, workflow, loops=None, realtime=True):
        super().__init__()
        self.workflow = workflow
        self.loops = loops
        self.realtime = realtime
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            import simulate
            simulate.simulate(self.workflow, self.event.emit,
                              max_loops=self.loops, realtime=self.realtime,
                              stop=lambda: self._stop)
        except Exception as e:
            self.event.emit({"t": 0, "kind": "warn", "node": "",
                             "msg": f"simulation failed: {e}"})


class RunWorker(QThread):
    """Streams a workflow run from the API and re-emits each execution event
    as a Qt signal, so the canvas can update live on the GUI thread."""
    event = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, workflow):
        super().__init__()
        self.workflow = workflow

    def run(self):
        try:
            for evt in api_post_stream("/run-stream", self.workflow):
                self.event.emit(evt)
        except Exception as e:
            self.failed.emit(str(e))


class EventListener(QThread):
    """Persistent background subscriber to the server's /events stream, so the
    canvas lights up when a webhook fires the current workflow. Reconnects
    automatically if the server restarts."""
    event = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._stop = False

    def run(self):
        import urllib.request, json as _json
        while not self._stop:
            try:
                req = urllib.request.Request(f"{API}/events")
                with urllib.request.urlopen(req, timeout=60) as resp:
                    block = []
                    for raw in resp:
                        if self._stop:
                            break
                        line = raw.decode("utf-8", "ignore").rstrip("\n")
                        if line == "":
                            for l in block:
                                if l.startswith("data:"):
                                    payload = l[5:].strip()
                                    if payload:
                                        try:
                                            self.event.emit(_json.loads(payload))
                                        except Exception:
                                            pass
                            block = []
                        elif not line.startswith(":"):
                            block.append(line)
            except Exception:
                pass
            # brief pause before reconnecting
            if not self._stop:
                self.msleep(1500)

    def stop(self):
        self._stop = True


class Editor(QWidget, SettingsPanelMixin):
    def __init__(self, app):
        super().__init__()
        self.app = app; self.current_project = None; self.meta_by_type = {}
        self._last_results = {}        # node name -> ports (kept after a run)
        self._last_inputs = {}         # node name -> items that entered it
        root = QHBoxLayout(self); root.setContentsMargins(8, 8, 8, 8); root.setSpacing(0)

        def col(width=None):
            w = QWidget()
            if width:
                w.setMinimumWidth(60)
            return w

        # ===================== LEFT COLUMN (settings / projects / json-of-selected)
        left_col = QWidget()
        lc = QVBoxLayout(left_col); lc.setContentsMargins(0, 0, 6, 0); lc.setSpacing(6)
        home = QLabel("DuGS")
        home.setStyleSheet(f"color:{ACCENT}; font-family:monospace; font-size:20px;")
        home.setCursor(Qt.CursorShape.PointingHandCursor)
        home.mousePressEvent = lambda _e: self.app.go_home()
        self.logo = home
        lc.addWidget(home)

        # a vertical splitter so Settings / Projects / Results can be resized
        left_split = GripSplitter(Qt.Orientation.Vertical)
        left_split.setChildrenCollapsible(True)
        left_split.setHandleWidth(6)

        # -- Settings (top, biggest)
        settings_wrap = QWidget(); sw = QVBoxLayout(settings_wrap); sw.setContentsMargins(0,0,0,0); sw.setSpacing(4)
        sw.addWidget(self._tag("SETTINGS"))
        self.settings_area = QScrollArea(); self.settings_area.setWidgetResizable(True)
        self.settings_host = QWidget(); self.settings_layout = QVBoxLayout(self.settings_host)
        self.settings_layout.addStretch(); self.settings_area.setWidget(self.settings_host)
        sw.addWidget(self.settings_area, 1)
        left_split.addWidget(settings_wrap)

        # -- Projects (smaller, as requested)
        proj_wrap = QWidget(); pw = QVBoxLayout(proj_wrap); pw.setContentsMargins(0,0,0,0); pw.setSpacing(4)
        pw.addWidget(self._tag("OTHER PROJECTS"))
        self.other_projects = QListWidget()
        self.other_projects.itemClicked.connect(self.switch_project)
        pw.addWidget(self.other_projects, 1)
        left_split.addWidget(proj_wrap)

        # -- Results / run log (below projects)
        res_wrap = QWidget(); rw = QVBoxLayout(res_wrap); rw.setContentsMargins(0,0,0,0); rw.setSpacing(4)
        rw.addWidget(self._tag("RUN LOG"))
        self.results = QTextEdit(); self.results.setReadOnly(True)
        self.results.setStyleSheet("background: rgba(10,10,10,0.5); color:#ddd; font-family:monospace; font-size:9px; border:1px solid #444;")
        rw.addWidget(self.results, 1)
        left_split.addWidget(res_wrap)

        # initial vertical proportions: settings big, projects small, log medium
        left_split.setStretchFactor(0, 5)
        left_split.setStretchFactor(1, 2)
        left_split.setStretchFactor(2, 3)
        lc.addWidget(left_split, 1)

        # ===================== CENTER COLUMN (canvas)
        center_col = QWidget()
        cc = QVBoxLayout(center_col); cc.setContentsMargins(6, 0, 6, 0); cc.setSpacing(6)
        bar = QHBoxLayout()
        self.proj_label = QLabel("-"); self.proj_label.setStyleSheet(f"color:{ACCENT}; font-family:monospace; font-size:14px;")
        bar.addWidget(self.proj_label); bar.addStretch()
        self.run_btn = QPushButton("Run"); self.run_btn.clicked.connect(self.run)
        run_btn = self.run_btn
        self.sim_btn = QPushButton("▶ Simulate")
        self.sim_btn.clicked.connect(self.simulate)
        self.sim_btn.setVisible(False)      # servo projects only
        save_btn = QPushButton("Save"); save_btn.clicked.connect(self.save)
        for b in (save_btn, self.sim_btn, run_btn): bar.addWidget(b)
        cc.addLayout(bar)
        self.canvas = Canvas(self); cc.addWidget(self.canvas, 1)

        # ===================== RIGHT COLUMN (palette + json)
        right_col = QWidget()
        rc = QVBoxLayout(right_col); rc.setContentsMargins(6, 0, 0, 0); rc.setSpacing(6)
        right_split = GripSplitter(Qt.Orientation.Vertical)
        right_split.setChildrenCollapsible(True)
        right_split.setHandleWidth(6)

        pal_wrap = QWidget(); plw = QVBoxLayout(pal_wrap); plw.setContentsMargins(0,0,0,0); plw.setSpacing(4)
        plw.addWidget(self._tag("NODES"))
        self.palette_search = QLineEdit()
        self.palette_search.setPlaceholderText("search nodes...")
        self.palette_search.textChanged.connect(self.filter_palette)
        plw.addWidget(self.palette_search)
        self.palette = QListWidget()
        self.palette.setStyleSheet("QListWidget::item { padding: 0px; }")
        self.palette.itemClicked.connect(self.drop_node)
        plw.addWidget(self.palette, 1)
        right_split.addWidget(pal_wrap)

        json_wrap = QWidget(); jw = QVBoxLayout(json_wrap); jw.setContentsMargins(0,0,0,0); jw.setSpacing(4)
        json_header = QHBoxLayout()
        self.json_label = self._tag("JSON")
        json_header.addWidget(self.json_label)
        json_header.addStretch()
        copy_btn = QPushButton("⎘ copy"); copy_btn.setFixedSize(54, 18)
        copy_btn.setStyleSheet("font-size:9px; padding:0px 4px; border:1px solid #444; color:#888; border-radius:3px;")
        copy_btn.clicked.connect(self._copy_json)
        json_header.addWidget(copy_btn)
        jw.addLayout(json_header)
        self.json_view = QTextEdit(); self.json_view.setReadOnly(True)
        self.json_view.setStyleSheet("background: rgba(10,10,10,0.5); color:#9fb; font-family:monospace; font-size:9px; border:1px solid #444;")
        self.json_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        jw.addWidget(self.json_view, 1)
        right_split.addWidget(json_wrap)
        right_split.setStretchFactor(0, 3)
        right_split.setStretchFactor(1, 2)
        rc.addWidget(right_split, 1)

        # ===================== MAIN HORIZONTAL SPLITTER (the 3 columns)
        main_split = GripSplitter(Qt.Orientation.Horizontal)
        main_split.setChildrenCollapsible(True)
        main_split.setHandleWidth(8)
        main_split.addWidget(left_col)
        main_split.addWidget(center_col)
        main_split.addWidget(right_col)
        # sensible starting widths: sides ~250, center takes the rest
        main_split.setStretchFactor(0, 0)
        main_split.setStretchFactor(1, 1)
        main_split.setStretchFactor(2, 0)
        main_split.setSizes([250, 800, 200])
        self._main_split = main_split
        self._left_split = left_split
        self._right_split = right_split

        # restore saved panel sizes, and persist them whenever they change
        self._restore_layout()
        for sp, key in ((main_split, "main"), (left_split, "left"), (right_split, "right")):
            sp.splitterMoved.connect(lambda _p, _i, k=key: self._save_layout())

        root.addWidget(main_split)

        # --- undo/redo + autosave state ---
        self._undo_stack = []      # list of workflow-JSON snapshots (strings)
        self._redo_stack = []
        self._undo_limit = 30
        self._suppress_snapshot = False   # set while applying undo/redo
        self._autosave_timer = QTimer(self); self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._do_autosave)

        QShortcut(QKeySequence("Delete"), self, lambda: self.canvas.delete_selected())
        QShortcut(QKeySequence("Ctrl+Z"), self, self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)

        # listen for webhook-triggered runs so the canvas lights up live
        self._evt_listener = EventListener()
        self._evt_listener.event.connect(self._on_webhook_event)
        self._evt_listener.start()

        # follow the settings popup: apply the workflow appearance now, and
        # register so future saves update this screen too
        self.apply_theme()
        try:
            from home_screen import register_themed_screen
            register_themed_screen(self)
        except Exception:
            pass

    def filter_palette(self, text):
        text = text.lower().strip()
        for i in range(self.palette.count()):
            it = self.palette.item(i)
            nd = it.data(Qt.ItemDataRole.UserRole) or {}
            if nd.get("__header__"):
                it.setHidden(False)   # keep section headers visible
                continue
            hay = (nd.get("title", "") + " " + nd.get("type", "")).lower()
            it.setHidden(bool(text) and text not in hay)

    def _add_palette_header(self, label, color=None):
        it = QListWidgetItem(label)
        it.setData(Qt.ItemDataRole.UserRole, {"__header__": True})
        it.setFlags(Qt.ItemFlag.NoItemFlags)   # not selectable/clickable
        f = it.font(); f.setBold(True); f.setPointSize(f.pointSize() - 1); it.setFont(f)
        it.setForeground(QColor(color or ACCENT))
        it.setSizeHint(QSize(180, 30))
        self.palette.addItem(it)

    def _add_palette_node(self, nd, color="#ffffff"):
        """One palette row: node name on the left, its icon on the FAR right
        (just past the name slot, not overlapping the text)."""
        it = QListWidgetItem()
        it.setData(Qt.ItemDataRole.UserRole, nd)
        self.palette.addItem(it)

        ROW_H = 34   # comfortable height; text was getting vertically clipped
        row = QWidget()
        row.setFixedHeight(ROW_H)
        lay = QHBoxLayout(row); lay.setContentsMargins(10, 0, 10, 0); lay.setSpacing(6)
        name = QLabel(nd["title"])
        name.setStyleSheet(f"color: {color}; background: transparent;")
        name.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(name)
        lay.addStretch(1)                      # pushes the icon to the right edge
        pm = node_pixmap(nd["type"], 20)
        if pm is not None:
            ic = QLabel(); ic.setPixmap(pm)
            ic.setFixedSize(22, 22)
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic.setStyleSheet("background: transparent;")
            lay.addWidget(ic)
        # padding is overridden to 0 on the palette, so the hint == row height
        it.setSizeHint(QSize(180, ROW_H))
        self.palette.setItemWidget(it, row)

    # robotics sub-groups: which node types live under each sub-header
    ROBOTICS_GROUPS = [
        ("FLOW",    ["device.on_start", "device.on_repeat", "device.repeat", "device.comment"]),
        ("SERVO",   ["device.servo", "device.servo_array", "device.servo_move"]),
        ("SCREEN",  ["device.screen"]),
        ("INPUT",   ["device.button", "device.encoder"]),
        ("LOGIC",   ["device.if", "device.state", "device.goto_state", "device.random"]),
        ("TIMING",  ["device.wait", "device.timer"]),
        ("ROUTING", ["device.pins", "device.pin", "device.array", "device.array_set",
                     "device.var", "device.map"]),
    ]

    # normal-node sub-groups for the NODES section (non-servo projects)
    NODE_GROUPS = [
        ("LOGIC",   ["logic.if", "logic.switch", "logic.filter", "core.merge"]),
        ("DATA",    ["core.set", "core.edit_fields", "core.text", "core.code",
                     "core.split_out", "core.aggregate", "core.sort", "core.limit",
                     "core.dedupe", "core.datetime", "core.hash"]),
        ("FLOW",    ["core.loop", "core.wait", "core.wait_webhook"]),
        ("ACTION",  ["web.http", "action.telegram", "action.discord",
                     "webhook.respond"]),
        ("DATA STORE", ["data.tabel"]),
        ("DEBUG",   ["core.log"]),
    ]

    def load_palette(self):
        self.palette.clear(); self.meta_by_type.clear()
        try:
            data = api_get("/nodes")
        except Exception as e:
            self.palette.addItem(QListWidgetItem("[API offline]"))
            self.results.setText(f"Can't reach API at {API}\nStart it: python3 api.py\n\n{e}"); return

        nodes = data["nodes"]
        for nd in nodes:
            self.meta_by_type[nd["type"]] = nd

        WHITE = "#ffffff"
        RED = "#ff6b6b"

        robotics = [n for n in nodes if n.get("category") == "robotics" or n.get("device")]
        is_servo = (getattr(self, "project_kind", "normal") == "servo")

        # ---- SERVO project: ONLY robotics nodes, grouped into sub-sections ----
        if is_servo:
            by_type = {n["type"]: n for n in robotics}
            placed = set()
            for group_name, types in self.ROBOTICS_GROUPS:
                group_nodes = [by_type[t] for t in types if t in by_type]
                if not group_nodes:
                    continue
                self._add_palette_header(group_name, RED)
                for nd in group_nodes:
                    self._add_palette_node(nd, WHITE)
                    placed.add(nd["type"])
            leftover = [n for n in robotics if n["type"] not in placed]
            if leftover:
                self._add_palette_header("OTHER", RED)
                for nd in leftover:
                    self._add_palette_node(nd, WHITE)
            return

        # ---- NORMAL project: triggers, then grouped nodes, NO robotics ----
        triggers = [n for n in nodes
                    if n.get("category") == "trigger" and n not in robotics]
        others   = [n for n in nodes
                    if n.get("category") not in ("trigger", "robotics")
                    and not n.get("device")]

        if triggers:
            self._add_palette_header("TRIGGERS", WHITE)
            for nd in triggers:
                self._add_palette_node(nd, WHITE)

        by_type = {n["type"]: n for n in others}
        placed = set()
        for group_name, types in self.NODE_GROUPS:
            group_nodes = [by_type[t] for t in types if t in by_type]
            if not group_nodes:
                continue
            self._add_palette_header(group_name, ACCENT)
            for nd in group_nodes:
                self._add_palette_node(nd, WHITE)
                placed.add(nd["type"])
        leftover = [n for n in others if n["type"] not in placed]
        if leftover:
            self._add_palette_header("MORE", ACCENT)
            for nd in leftover:
                self._add_palette_node(nd, WHITE)

    def apply_theme(self):
        """Re-apply the workflow appearance settings from the settings popup.

        The canvas repaints its background, and the panels AROUND the canvas
        (palette, settings, log, code) get tinted to match that background's
        brightness — so a light photo gives light panels and a dark one gives
        dark panels, instead of the surroundings clashing with the image.
        """
        try:
            from home_screen import load_home_ui_settings
            s = load_home_ui_settings()
        except Exception:
            s = {}
        self.ui_settings = s

        # let the canvas pick up the new background/grid
        try:
            self.canvas.reload_theme()
        except Exception:
            pass

        panel, text, border = self._panel_colors(s)
        self._panel_css = (f"background: {panel}; color:{text}; "
                           f"font-family:monospace; font-size:9px; "
                           f"border:1px solid {border};")
        for w in (getattr(self, "results", None), getattr(self, "json_view", None)):
            if w is not None:
                w.setStyleSheet(self._panel_css)
        for w in (getattr(self, "palette", None),
                  getattr(self, "settings_area", None),
                  getattr(self, "proj_list", None)):
            if w is not None:
                w.setStyleSheet(f"background: {panel}; border:1px solid {border};")
        self.update()

    def _panel_colors(self, s):
        """Work out panel colours from the chosen canvas background image.

        Samples the image's average brightness. Dark image -> dark translucent
        panels with light text; light image -> light panels with dark text.
        Falls back to the original dark styling when no image is set.
        """
        default = ("rgba(10,10,10,0.5)", "#ddd", "#444")
        if s.get("canvas_no_background", False):
            return default
        path = s.get("canvas_bg_image")
        if not path or not os.path.isfile(path):
            return default
        try:
            img = QImage(path)
            if img.isNull():
                return default
            # scale to a tiny thumbnail; averaging those pixels is fast and
            # gives the overall tone of the image
            thumb = img.scaled(16, 16, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            tot = n = 0
            for y in range(thumb.height()):
                for x in range(thumb.width()):
                    c = thumb.pixelColor(x, y)
                    tot += 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
                    n += 1
            if not n:
                return default
            lum = tot / n
        except Exception:
            return default

        if lum > 140:      # light image -> light panels, dark text
            return ("rgba(245,245,245,0.72)", "#181818", "#999")
        if lum > 70:       # mid -> neutral
            return ("rgba(40,40,40,0.62)", "#eee", "#666")
        return ("rgba(10,10,10,0.55)", "#ddd", "#444")   # dark image

    def open_project(self, name):
        self.current_project = name; self.proj_label.setText(name)
        try: wf = load_project(name)
        except Exception: wf = {"name": name, "nodes": [], "connections": {}}
        # servo projects generate Arduino code instead of running in the engine
        self.project_kind = wf.get("kind", "normal")
        self._apply_project_kind()
        self.load_palette()
        self.canvas.load_workflow(wf, self.meta_by_type)
        self.refresh_other_projects(); self.refresh_json(); self.show_node_settings(None)

    def _apply_project_kind(self):
        """Swap the Run button for Export Code on servo (hardware) projects,
        and turn the whole editor red-themed."""
        servo = (getattr(self, "project_kind", "normal") == "servo")
        self.sim_btn.setVisible(servo)
        if servo:
            self.run_btn.setText("Export Code")
            self.run_btn.setStyleSheet(
                "QPushButton{background:rgba(255,107,107,0.15);color:#ff6b6b;"
                "border:1px solid #ff6b6b;border-radius:4px;padding:5px 12px;"
                "font-family:monospace;}")
            self.proj_label.setStyleSheet(
                "color:#ff6b6b;font-family:monospace;font-size:14px;")
            # logo goes RED and UPPERCASE
            if hasattr(self, "logo"):
                self.logo.setText("DuGS")
                self.logo.setStyleSheet(
                    "color:#ff6b6b; font-family:monospace; font-size:20px; font-weight:bold;")
        else:
            self.run_btn.setText("Run")
            self.run_btn.setStyleSheet("")
            self.proj_label.setStyleSheet(
                f"color:{ACCENT};font-family:monospace;font-size:14px;")
            if hasattr(self, "logo"):
                self.logo.setText("DuGS")
                self.logo.setStyleSheet(
                    f"color:{ACCENT}; font-family:monospace; font-size:20px;")

    def refresh_other_projects(self):
        self.other_projects.clear()
        for p in list_projects():
            if p == self.current_project: continue
            self.other_projects.addItem(QListWidgetItem(p))

    def switch_project(self, item):
        self.save(); self.open_project(item.text())

    def drop_node(self, item):
        nd = item.data(Qt.ItemDataRole.UserRole)
        if nd and not nd.get("__header__"):
            self.canvas.add_node(nd); self.mark_changed()

    def open_node_popup(self, node):
        """Tab on a hovered node: floating popup to quick-view/edit it,
        while the left settings bar stays as-is."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                                     QLineEdit, QPlainTextEdit, QComboBox, QLabel,
                                     QPushButton, QScrollArea, QWidget as _QW)
        meta = self.meta_by_type.get(node.type_id, {})
        params_spec = meta.get("params", [])

        # robotics nodes use red where a normal node uses the blue accent
        NACC = "#ff6b6b" if str(node.type_id).startswith("device.") else ACCENT

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{node.name}  ({node.type_id})")
        dlg.setMinimumWidth(820); dlg.setMinimumHeight(420)
        QShortcut(QKeySequence("Escape"), dlg, dlg.accept)
        dlg.setStyleSheet("QDialog{background:#141414;}"
                          "QLabel{color:#ccc;font-family:monospace;}"
                          "QLineEdit,QPlainTextEdit,QComboBox{background:#1e1e1e;color:#fff;"
                          "border:1px solid #555;border-radius:3px;padding:4px;font-family:monospace;font-size:12px;}")
        outer = QVBoxLayout(dlg)

        title = QLabel(node.name)
        title.setStyleSheet(f"color:{NACC};font-family:monospace;font-size:16px;font-weight:bold;")
        title.setToolTip("double-click to rename")
        title.setCursor(Qt.CursorShape.IBeamCursor)
        outer.addWidget(title)
        sub = QLabel(node.type_id); sub.setStyleSheet("color:#666;font-family:monospace;font-size:10px;")
        outer.addWidget(sub)

        # double-click the title to rename inline (replaces the old name field)
        def _start_rename(_e):
            editor_line = QLineEdit(node.name)
            editor_line.setStyleSheet(f"color:{NACC};font-family:monospace;font-size:16px;font-weight:bold;"
                                      "background:#1e1e1e;border:1px solid #555;border-radius:3px;padding:2px;")
            # swap the label for the editor in the layout
            outer.replaceWidget(title, editor_line)
            title.hide(); editor_line.setFocus(); editor_line.selectAll()
            def _commit():
                new = editor_line.text().strip()
                if new and "{{" not in new and "$(" not in new and new != node.name:
                    node.name = new; title.setText(new)
                    dlg.setWindowTitle(f"{node.name}  ({node.type_id})")
                    self.mark_changed()
                    if self.canvas.selected is node:
                        self.show_node_settings(node)
                outer.replaceWidget(editor_line, title)
                editor_line.deleteLater(); title.show()
            editor_line.editingFinished.connect(_commit)
        title.mouseDoubleClickEvent = _start_rename

        # three columns: INPUT | PARAMS | OUTPUT  (n8n-style)
        cols = QHBoxLayout(); cols.setSpacing(10)

        def col_label(t):
            l = QLabel(t); l.setStyleSheet("color:#888;font-family:monospace;font-size:11px;letter-spacing:1px;")
            return l

        # ---- LEFT: input JSON (from upstream nodes' last output) ----
        left_box = QVBoxLayout(); left_box.setSpacing(4)
        left_box.addWidget(col_label("INPUT  (drag a field into a box →)"))
        ups = self._upstream_nodes(node)
        input_data = {}
        for up in ups:
            vals = self._last_results.get(up)
            if vals:
                input_data[up] = vals
        in_tree = DragJsonTree()
        if input_data:
            for src_node, items_in in input_data.items():
                top = QTreeWidgetItem([f"$('{src_node}')", f"{len(items_in)} item(s)"])
                top.setData(0, Qt.ItemDataRole.UserRole, f"$('{src_node}').item.json")
                in_tree.addTopLevelItem(top)
                if items_in:
                    self._json_to_tree(top, items_in[0], f"$('{src_node}').item.json", src_node)
                top.setExpanded(True)
        else:
            placeholder = QTreeWidgetItem(
                ["(run to see input)" if ups else "(no upstream nodes)", ""])
            in_tree.addTopLevelItem(placeholder)
        left_box.addWidget(in_tree, 1)
        cols.addLayout(left_box, 2)

        # ---- MIDDLE: params ----
        mid_box = QVBoxLayout(); mid_box.setSpacing(4)
        mid_box.addWidget(col_label("PARAMETERS"))
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        host = _QW(); form = QFormLayout(host)

        # (no name field here — double-click the title above to rename)

        # build the same cross-node context the engine uses, from the last run,
        # so we can show what each {{ }} expression currently resolves to.
        from node_base import resolve_expr, EXPR_RE
        preview_ctx = {}
        for up in self._upstream_nodes(node):
            vals = self._last_results.get(up)
            if vals:
                # _last_results holds flat json dicts; the resolver expects
                # items shaped {"json": {...}}, so wrap them.
                preview_ctx[up] = [
                    v if (isinstance(v, dict) and "json" in v) else {"json": v}
                    for v in vals
                ]
        # the "current item" for $json previews = first item of the first
        # upstream node's output (that's what $json refers to inside this node)
        cur_item = {}
        for up_vals in preview_ctx.values():
            if up_vals:
                first = up_vals[0]
                cur_item = first.get("json", first) if isinstance(first, dict) else first
                break

        def make_preview(get_text):
            """A label that shows the resolved value of any {{ }} in the text:
            green if it resolves to something, grey if not."""
            lbl = QLabel("")
            lbl.setWordWrap(True)
            def refresh():
                txt = get_text()
                if not txt or "{{" not in txt:
                    lbl.setText(""); return
                try:
                    val = resolve_expr(txt, cur_item, preview_ctx)
                except Exception:
                    val = None
                # did anything actually resolve? (value present and not the raw expr)
                resolved = val is not None and str(val).strip() != "" and "{{" not in str(val)
                if resolved:
                    shown = val if isinstance(val, str) else json.dumps(val)
                    if len(shown) > 200: shown = shown[:200] + "…"
                    lbl.setStyleSheet("color:#7CFC9B;font-family:monospace;font-size:10px;")
                    lbl.setText("= " + shown)
                else:
                    lbl.setStyleSheet("color:#666;font-family:monospace;font-size:10px;")
                    lbl.setText("= (no value — run the workflow first)" if preview_ctx
                                else "= (no upstream data yet)")
            return lbl, refresh

        # one editor per param (text/number/multiline/select/bool)
        for p in params_spec:
            key = p["key"]; ptype = p.get("type", "text")
            cur = node.params.get(key, p.get("default"))
            preview = None; refresh_preview = None
            if ptype == "multiline":
                w = DropTextEdit(str(cur) if cur is not None else "")
                w.setFixedHeight(70)
                preview, refresh_preview = make_preview(lambda ww=w: ww.toPlainText())
                def mk(k, ww, rp):
                    def s(): node.params[k] = ww.toPlainText(); self.mark_changed(push_undo=False); rp()
                    return s
                cb = mk(key, w, refresh_preview); w.textChanged.connect(cb); w._on_change = cb
            elif ptype == "select":
                w = QComboBox()
                opts = [str(o) for o in p.get("options", [])]
                if p.get("options_from") == "credentials":
                    from storage import list_credentials
                    opts = [""] + list_credentials()
                w.addItems(opts)
                if cur is not None and str(cur) in opts: w.setCurrentText(str(cur))
                def mks(k, ww):
                    def s(): node.params[k] = ww.currentText(); self.mark_changed()
                    return s
                w.currentTextChanged.connect(mks(key, w))
            elif ptype == "bool":
                from PyQt6.QtWidgets import QCheckBox
                w = QCheckBox(); w.setChecked(bool(cur))
                def mkb(k, ww):
                    def s(_=None): node.params[k] = ww.isChecked(); self.mark_changed()
                    return s
                w.stateChanged.connect(mkb(key, w))
            else:
                w = DropLineEdit(str(cur) if cur is not None else "")
                preview, refresh_preview = make_preview(lambda ww=w: ww.text())
                def mkt(k, ww, rp, isnum=(ptype == "number")):
                    def s():
                        v = ww.text()
                        if isnum:
                            try: v = int(v)
                            except ValueError:
                                try: v = float(v)
                                except ValueError: pass
                        node.params[k] = v; self.mark_changed(push_undo=False); rp()
                    return s
                cb = mkt(key, w, refresh_preview); w.editingFinished.connect(cb); w._on_change = cb
                # also live-update the preview as you type/drop, not just on commit
                w.textChanged.connect(refresh_preview)
            form.addRow(p.get("label", key), w)
            if preview is not None:
                form.addRow("", preview)
                refresh_preview()   # show initial state

        scroll.setWidget(host); mid_box.addWidget(scroll, 1)
        cols.addLayout(mid_box, 3)

        # ---- RIGHT: this node's own last output ----
        right_box = QVBoxLayout(); right_box.setSpacing(4)
        right_box.addWidget(col_label("OUTPUT"))
        own = self._last_results.get(node.name)
        out_view = QPlainTextEdit(); out_view.setReadOnly(True)
        out_view.setStyleSheet("color:#9fb;font-size:10px;")
        if own:
            out_view.setPlainText(json.dumps(own[:3], indent=2))
        else:
            out_view.setPlainText("(run the workflow to see output)")
        right_box.addWidget(out_view, 1)
        cols.addLayout(right_box, 2)

        outer.addLayout(cols, 1)

        close = QPushButton("Close"); close.clicked.connect(dlg.accept)
        outer.addWidget(close)
        dlg.exec()
        # after closing, refresh the left panel + json in case things changed
        if self.canvas.selected is node:
            self.show_node_settings(node)
        self.refresh_json()

    def refresh_json(self):
        wf = self.canvas.to_workflow(self.current_project or "untitled")

        # robotics projects don't care about the workflow JSON — they want the
        # ARDUINO CODE the graph compiles to, updated live as you build.
        if getattr(self, "project_kind", "normal") == "servo":
            try:
                import os, codegen
                here = os.path.dirname(os.path.abspath(__file__))
                reg = codegen.discover_device_nodes(
                    None, os.path.join(here, "robotics_nodes"))
                self.json_view.setPlainText(codegen.generate(wf, reg))
            except Exception as e:
                self.json_view.setPlainText(f"// code generation failed:\n// {e}")
            self.json_label.setText("CODE")
            return

        self.json_label.setText("JSON")
        self.json_view.setText(json.dumps(wf, indent=2))

    def _copy_json(self):
        QApplication.clipboard().setText(self.json_view.toPlainText())
        btn = self.sender()
        if btn:
            btn.setText("✓ copied"); btn.setStyleSheet(f"font-size:9px; padding:0px 4px; border:1px solid {ACCENT}; color:{ACCENT}; border-radius:3px;")
            QTimer.singleShot(1200, lambda: (btn.setText("⎘ copy"), btn.setStyleSheet("font-size:9px; padding:0px 4px; border:1px solid #444; color:#888; border-radius:3px;")))

    def save(self):
        if not self.current_project: return
        wf = self.canvas.to_workflow(self.current_project)
        wf["kind"] = getattr(self, "project_kind", "normal")
        save_project(self.current_project, wf)
        has_webhook = any(n.get("type") == "webhook.trigger" for n in wf.get("nodes", []))
        if has_webhook:
            try:
                api_post("/webhooks/register", wf)
                self.results.setText(f"saved: {self.current_project}  (webhook registered)")
            except Exception as e:
                self.results.setText(f"saved: {self.current_project}  (webhook register failed: {e})")
        else:
            self.results.setText(f"saved: {self.current_project}")

    # ================= autosave + undo/redo =================
    def _save_layout(self):
        try:
            save_ui_state({
                "main": self._main_split.sizes(),
                "left": self._left_split.sizes(),
                "right": self._right_split.sizes(),
            })
        except Exception:
            pass

    def _restore_layout(self):
        st = load_ui_state()
        try:
            if st.get("main"): self._main_split.setSizes(st["main"])
            if st.get("left"): self._left_split.setSizes(st["left"])
            if st.get("right"): self._right_split.setSizes(st["right"])
        except Exception:
            pass

    def _snapshot(self):
        """Current workflow as a JSON string (used for undo history)."""
        return json.dumps(self.canvas.to_workflow(self.current_project or "untitled"))

    def mark_changed(self, push_undo=True):
        """Call after ANY edit (node add/move/delete, connection change,
        param edit, etc). Pushes an undo snapshot and schedules an autosave."""
        if self._suppress_snapshot:
            return
        if push_undo:
            snap = self._snapshot()
            # avoid duplicate consecutive snapshots
            if not self._undo_stack or self._undo_stack[-1] != snap:
                self._undo_stack.append(snap)
                if len(self._undo_stack) > self._undo_limit:
                    self._undo_stack.pop(0)
                self._redo_stack.clear()
        self.refresh_json()
        # debounce autosave so rapid edits don't hammer the disk
        self._autosave_timer.start(600)

    def _do_autosave(self):
        if not self.current_project:
            return
        try:
            wf = self.canvas.to_workflow(self.current_project)
            wf["kind"] = getattr(self, "project_kind", "normal")
            save_project(self.current_project, wf)
            has_webhook = any(n.get("type") == "webhook.trigger" for n in wf.get("nodes", []))
            if has_webhook:
                try: api_post("/webhooks/register", wf)
                except Exception: pass
        except Exception as e:
            self.results.setText(f"autosave failed: {e}")

    def _apply_snapshot(self, snap):
        self._suppress_snapshot = True
        try:
            wf = json.loads(snap)
            self.canvas.load_workflow(wf, self.meta_by_type)
            self.show_node_settings(None)
            self.refresh_json()
        finally:
            self._suppress_snapshot = False
        self._autosave_timer.start(600)

    def undo(self):
        if len(self._undo_stack) < 1:
            return
        # current state goes onto redo; restore previous
        current = self._snapshot()
        prev = self._undo_stack.pop()
        if prev == current and self._undo_stack:
            # top of stack equals current (snapshot was taken post-edit) -> step back one more
            self._redo_stack.append(current)
            prev = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._apply_snapshot(prev)

    def redo(self):
        if not self._redo_stack:
            return
        snap = self._redo_stack.pop()
        self._undo_stack.append(self._snapshot())
        self._apply_snapshot(snap)

    def _exec_order(self, wf):
        conns = wf.get("connections", {})
        has_incoming = set()
        for src, links in conns.items():
            for l in links: has_incoming.add(l["to"])
        names = [n["name"] for n in wf["nodes"]]
        starts = [n for n in names if n not in has_incoming]
        order = []; queue = list(starts); seen = set()
        while queue:
            cur = queue.pop(0)
            if cur in seen: continue
            seen.add(cur); order.append(cur)
            for l in conns.get(cur, []):
                if l["to"] not in seen: queue.append(l["to"])
        for n in names:
            if n not in seen: order.append(n)
        return order

    def _on_webhook_event(self, evt):
        """A webhook-triggered run is happening on the server. If it's the
        workflow currently open, replay its events on the canvas live."""
        kind = evt.get("kind")
        wf = evt.get("workflow")
        # only react to the project that's open in front of the user
        if self.current_project and wf and wf != self.current_project:
            return
        if kind == "webhook_run_start":
            self.results.clear()
            self._append_result(f"⚡ webhook fired → running '{wf}'")
            self.canvas.run_states.clear(); self.canvas.edge_counts.clear()
            self.canvas.running_node = None; self.canvas.update()
            return
        if kind == "webhook_run_error":
            self._append_result(f"webhook run error: {evt.get('error','')}")
            return
        # all other engine events (node_running/node_done/edge/results/...) are
        # handled by the exact same logic as a manual run
        self._on_run_event(evt)

    def closeEvent(self, e):
        try:
            self._evt_listener.stop()
        except Exception:
            pass
        super().closeEvent(e)

    def _on_run_event(self, evt):
        """Handle one live execution event on the GUI thread."""
        kind = evt.get("kind")
        c = self.canvas
        if kind == "start":
            c.run_states.clear(); c.edge_counts.clear()
            c.running_node = None; c.active_edge = None
            c.update()
        elif kind == "node_running":
            c.running_node = evt["node"]
            c.run_states[evt["node"]] = "running"
            c.update()
        elif kind == "node_done":
            c.run_states[evt["node"]] = "done"
            if c.running_node == evt["node"]:
                c.running_node = None
            # keep this node's output sample so the I/O panel can show it
            self._last_results[evt["node"]] = evt.get("sample", [])
            ms = evt.get("ms", 0)
            self._append_result(
                f"{evt['node']}  →  {evt.get('items_out', 0)} item(s)  ({ms:.0f} ms)"
            )
            # if this node is the one open in settings, refresh its I/O view
            if getattr(self, "_io_node", None) == evt["node"]:
                self._refresh_io_panel()
            c.update()
        elif kind == "node_error":
            c.run_states[evt["node"]] = "error"
            if c.running_node == evt["node"]:
                c.running_node = None
            self._append_result(f"{evt['node']}  ✗  ERROR: {evt.get('error','')}")
            c.update()
        elif kind == "edge":
            key = (evt["from"], evt.get("out", 0), evt["to"], evt.get("in", 0))
            c.edge_counts[key] = evt.get("items", 0)
            c.pulse_edge(key)   # animate a dot travelling the wire
            c.update()
        elif kind == "results":
            full = evt.get("results", {})
            # normalise: results[node] = [port0_items, port1_items, ...].
            # flatten to the first port's items for the I/O viewer.
            for nm, ports in full.items():
                if isinstance(ports, list) and ports and isinstance(ports[0], list):
                    self._last_results[nm] = [it.get("json", it) for it in ports[0]]
                elif isinstance(ports, list):
                    self._last_results[nm] = [it.get("json", it) for it in ports]
            c.running_node = None; c.active_edge = None; c.update()
            if getattr(self, "_io_node", None):
                self._refresh_io_panel()
        elif kind == "fatal":
            self._append_result(f"RUN FAILED: {evt.get('error','')}")
            c.running_node = None; c.update()

    def _append_result(self, line):
        prev = self.results.toPlainText()
        # keep the log readable: cap to last ~40 lines
        lines = (prev.splitlines() + [line])[-40:]
        self.results.setPlainText("\n".join(lines))
        sb = self.results.verticalScrollBar()
        sb.setValue(sb.maximum())

    def simulate(self):
        """Run the robotics graph virtually and show what the board would do."""
        if getattr(self, "_sim_worker", None) and self._sim_worker.isRunning():
            self._sim_worker.stop()
            self.sim_btn.setText("\u25b6 Simulate")
            return

        wf = self.canvas.to_workflow(self.current_project or "untitled")
        if not wf["nodes"]:
            self.results.setText("Canvas empty - drop some nodes first."); return

        self.results.clear()
        self.canvas.run_states.clear(); self.canvas.edge_counts.clear()
        self.canvas.running_node = None; self.canvas.update()
        self._sim_warnings = 0

        self.sim_btn.setText("\u25a0 Stop")
        self._sim_worker = SimWorker(wf, loops=None, realtime=True)
        self._sim_worker.event.connect(self._on_sim_event)
        self._sim_worker.finished.connect(lambda: self.sim_btn.setText("\u25b6 Simulate"))
        self._sim_worker.start()

    def _on_sim_event(self, e):
        """One thing the virtual board just did."""
        k = e.get("kind"); t = e.get("t", 0); node = e.get("node", "")
        c = self.canvas

        if node and k not in ("warn", "phase", "end", "power_on", "loop_start"):
            for prev in list(c.run_states):
                if c.run_states[prev] == "running":
                    c.run_states[prev] = "done"
            c.run_states[node] = "running"
            c.running_node = node
            c.update()

        if k == "power_on":
            self._append_result("\u26a1 POWER ON")
        elif k == "phase":
            ph = e.get("phase")
            self._append_result("- setup(): runs once -" if ph == "setup"
                                else "- loop(): repeats forever -")
        elif k == "loop_start":
            self._append_result(f"  pass {e.get('n', 0) + 1}")
        elif k == "servo":
            prev = e.get("prev")
            arrow = f"{prev} -> {e['angle']} deg" if prev is not None else f"-> {e['angle']} deg"
            self._append_result(f"{t:6.1f}s  SERVO pin {e['pin']}  {arrow}   [{node}]")
        elif k == "pin":
            self._append_result(f"{t:6.1f}s  PIN {e['pin']} = {e['value']}   [{node}]")
        elif k == "read":
            self._append_result(f"{t:6.1f}s  READ pin {e.get('pin')} -> {e.get('into')}   [{node}]")
        elif k == "wait":
            self._append_result(f"{t:6.1f}s  wait {e.get('ms', 0):.0f}ms   [{node}]")
        elif k == "screen":
            self._append_result(f"{t:6.1f}s  SCREEN: \"{e.get('text','')}\"   [{node}]")
        elif k == "random":
            self._append_result(f"{t:6.1f}s  RANDOM {e.get('into')} = {e.get('value')}   [{node}]")
        elif k == "var":
            self._append_result(f"{t:6.1f}s  {e.get('var')} {e.get('op')} -> {e.get('value')}   [{node}]")
        elif k == "button":
            self._append_result(f"{t:6.1f}s  BUTTON pin {e.get('pin')} ({e.get('note','')})   [{node}]")
        elif k == "repeat":
            self._append_result(f"{t:6.1f}s  repeat {e.get('iteration',0)+1}/{e.get('of','?')}   [{node}]")
        elif k == "warn":
            self._sim_warnings = getattr(self, "_sim_warnings", 0) + 1
            self._append_result(f"  !! {e.get('msg','')}" + (f"   [{node}]" if node else ""))
            if node:
                c.run_states[node] = "error"; c.update()
        elif k == "end":
            c.running_node = None; c.update()
            w = getattr(self, "_sim_warnings", 0)
            self._append_result(f"- finished ({w} warning{'s' if w != 1 else ''}) -")

    def run(self):
        wf = self.canvas.to_workflow(self.current_project or "untitled")
        if not wf["nodes"]:
            self.results.setText("Canvas empty - drop some nodes first."); return

        # ---- servo project: compile the graph to an Arduino sketch ----
        if getattr(self, "project_kind", "normal") == "servo":
            wf["kind"] = "servo"
            self.results.clear()
            try:
                res = api_post("/generate", wf)
            except Exception as e:
                self.results.setText(f"Export failed:\n{e}"); return
            if not res.get("ok"):
                self.results.setText(f"Export failed:\n{res.get('error')}"); return
            path = res.get("path", "")
            self._append_result(f"exported: {path}")
            self._append_result("open it in the Arduino IDE and upload.")
            self.json_view.setPlainText(res.get("code", ""))
            return

        self.results.clear()
        self.canvas.run_states.clear(); self.canvas.edge_counts.clear()
        self.canvas.running_node = None; self.canvas.update()
        self._run_worker = RunWorker(wf)
        self._run_worker.event.connect(self._on_run_event)
        self._run_worker.failed.connect(lambda e: self._append_result(f"Run failed:\n{e}"))
        self._run_worker.start()

    def run_from(self, node_name):
        # run the whole workflow but visually anchor on the chosen node;
        # the live stream will still light up everything as it executes.
        self.run()
