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
from PyQt6.QtCore import Qt, QTimer, QObject, QSize
from PyQt6.QtGui import QKeySequence, QShortcut, QColor, QImage

from theme import ACCENT, API
from api_client import api_get, api_post, api_post_stream
from storage import list_projects, load_project, save_project, load_ui_state, save_ui_state
from canvas import Canvas, node_pixmap
from editor_widgets import (GripSplitter, DragJsonTree,
                            DropLineEdit, DropTextEdit)
from panel_base import PanelBox, EdgeArrow, DotSplitter
from editor_workers import SimWorker, RunWorker, EventListener
from editor_settings import SettingsPanelMixin
from node_popup import NodePopupMixin

from PyQt6.QtGui import QPainter, QColor as _QColor










class _NullWidget:
    """Stand-in for a module widget that is not on screen.

    Panels start empty, so the editor may try to write to a run log or a code
    view that the user has not added yet. Rather than guarding every call site
    with a hasattr check, those attributes point here: every method quietly
    does nothing, and any attribute lookup returns another no-op.
    """
    def __getattr__(self, _name):
        return self._noop
    def _noop(self, *a, **k):
        return None


class _NullList(_NullWidget):
    """Same idea for list widgets, where a few calls expect a number back."""
    def count(self):
        return 0
    def item(self, _i):
        return None


class Editor(QWidget, SettingsPanelMixin, NodePopupMixin):
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

        # ---- PANELS -----------------------------------------------------
        # Panels are containers down each edge. They start EMPTY and collapsed:
        # you pull one open with its edge arrow, press [+], and tick which
        # modules it should show. Modules themselves are plugins in panels/.
        self._load_modules()

        self.panel_left = PanelBox("left", self)
        self.panel_right = PanelBox("right", self)
        self.panel_bottom = PanelBox("bottom", self)
        self.panels_by_side = {
            "left": self.panel_left,
            "right": self.panel_right,
            "bottom": self.panel_bottom,
        }

        self.arrow_left = EdgeArrow("left", self.toggle_panel)
        self.arrow_right = EdgeArrow("right", self.toggle_panel)
        self.arrow_bottom = EdgeArrow("bottom", self.toggle_panel)
        self.arrows_by_side = {
            "left": self.arrow_left,
            "right": self.arrow_right,
            "bottom": self.arrow_bottom,
        }

        lc.addWidget(self.panel_left, 1)

        # ===================== CENTER COLUMN (canvas)
        center_col = QWidget()
        cc = QVBoxLayout(center_col); cc.setContentsMargins(6, 0, 6, 0); cc.setSpacing(6)
        bar = QHBoxLayout()
        # the arrows that pull each side panel open sit in the toolbar
        bar.addWidget(self.arrow_left)
        self.proj_label = QLabel("-"); self.proj_label.setStyleSheet(f"color:{ACCENT}; font-family:monospace; font-size:14px;")
        bar.addWidget(self.proj_label); bar.addStretch()
        self.run_btn = QPushButton("Run"); self.run_btn.clicked.connect(self.run)
        self.sim_btn = QPushButton("\u25b6 Simulate")
        self.sim_btn.clicked.connect(self.simulate)
        self.sim_btn.setVisible(False)      # servo projects only
        save_btn = QPushButton("Save"); save_btn.clicked.connect(self.save)
        for b in (save_btn, self.sim_btn, self.run_btn): bar.addWidget(b)
        bar.addWidget(self.arrow_right)
        cc.addLayout(bar)

        self.canvas = Canvas(self)
        cc.addWidget(self.canvas, 1)

        # the bottom panel lives under the canvas, with its arrow beside it
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(0, 0, 0, 0)
        bottom_bar.addWidget(self.arrow_bottom)
        bottom_bar.addStretch()
        cc.addLayout(bottom_bar)
        cc.addWidget(self.panel_bottom)

        # ===================== RIGHT COLUMN
        right_col = QWidget()
        rc = QVBoxLayout(right_col); rc.setContentsMargins(6, 0, 0, 0); rc.setSpacing(6)
        rc.addWidget(self.panel_right, 1)

        # ===================== MAIN HORIZONTAL SPLITTER (the 3 columns)
        main_split = DotSplitter(Qt.Orientation.Horizontal)
        main_split.setChildrenCollapsible(True)
        main_split.setHandleWidth(8)
        main_split.addWidget(left_col)
        main_split.addWidget(center_col)
        main_split.addWidget(right_col)
        main_split.setStretchFactor(0, 0)
        main_split.setStretchFactor(1, 1)
        main_split.setStretchFactor(2, 0)
        main_split.setSizes([250, 800, 250])
        self._main_split = main_split

        # everything starts hidden until the user pulls a panel open
        for side in ("left", "right", "bottom"):
            self.toggle_panel(side, False)

        self._restore_layout()
        main_split.splitterMoved.connect(lambda _p, _i: self._save_layout())

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

    def paintEvent(self, event):
        """Paint the editor's own background.

        The app window is translucent (ui.py sets WA_TranslucentBackground), so
        a screen that paints nothing lets whatever was behind it — the home
        screen — stay visible underneath the workflow. Filling here stops that.
        """
        try:
            from home_screen import GREY_BG as base
        except Exception:
            base = "#3a3a3a"
        p = QPainter(self)
        p.fillRect(self.rect(), _QColor(base))
        p.end()
        super().paintEvent(event)

    def _load_modules(self):
        """Discover every module in panels/. They are NOT placed anywhere yet —
        panels start empty and the user picks what goes in them."""
        # Panels start empty, so the widgets modules normally provide may not
        # exist. These stand-ins keep the editor working either way: writing to
        # a log that isn't on screen simply goes nowhere instead of crashing.
        self.results = _NullWidget()
        self.json_view = _NullWidget()
        self.json_label = _NullWidget()
        self.palette = _NullList()
        self.palette_search = _NullWidget()
        self.other_projects = _NullList()
        self.settings_area = None
        self.settings_host = None
        self.settings_layout = None

        self.all_modules = []
        try:
            from panel_base import discover_modules
            here = os.path.dirname(os.path.abspath(__file__))
            for cls in discover_modules(os.path.join(here, "panels")):
                try:
                    self.all_modules.append(cls(self))
                except Exception as e:
                    print(f"  [module warn] {cls.__name__} failed to start: {e}")
        except Exception as e:
            print(f"  [module warn] module system unavailable: {e}")

    @property
    def panels(self):
        """Every module currently placed in a panel (what the hooks fire on)."""
        out = []
        for box in getattr(self, "panels_by_side", {}).values():
            out.extend(box.modules)
        return out

    def toggle_panel(self, side, is_open):
        """Show or hide one edge panel."""
        box = self.panels_by_side.get(side)
        if box is None:
            return
        box.setVisible(is_open)
        arrow = self.arrows_by_side.get(side)
        if arrow is not None and arrow.open != is_open:
            arrow.set_open(is_open)
        self._save_layout()

    def toggle_module(self, module, panel, wanted):
        """Tick/untick a module in a panel's [+] menu."""
        if wanted:
            # a module lives in exactly one panel — take it out of its old one
            if module.host is not None and module.host is not panel:
                module.host.remove_module(module)
            panel.add_module(module)
            if not panel.isVisible():
                self.toggle_panel(panel.side, True)
            try:
                module.on_project_opened(self.current_project)
            except Exception:
                pass
        else:
            if module.host is not None:
                module.host.remove_module(module)
        self.apply_theme()
        self._save_layout()

    def move_module(self, module, target_panel):
        """Middle-mouse drag dropped a module onto another panel."""
        if module.host is target_panel:
            return
        if module.host is not None:
            module.host.remove_module(module)
        target_panel.add_module(module)
        if not target_panel.isVisible():
            self.toggle_panel(target_panel.side, True)
        self.apply_theme()
        self._save_layout()

    def panel_at_global(self, gpos):
        """Which panel is under this screen position (for middle-mouse drops)."""
        for box in self.panels_by_side.values():
            if not box.isVisible():
                continue
            top_left = box.mapToGlobal(box.rect().topLeft())
            rect = box.rect().translated(top_left)
            if rect.contains(gpos):
                return box
        return None

    def _panels_notify(self, hook, *args):
        """Call an optional hook on every panel, ignoring ones that don't have
        it and never letting a broken panel take the editor down."""
        for p in getattr(self, "panels", []):
            fn = getattr(p, hook, None)
            if fn is None:
                continue
            try:
                fn(*args)
            except Exception as e:
                print(f"  [panel warn] {type(p).__name__}.{hook}: {e}")

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
        # The window is translucent, so each panel's container must paint an
        # opaque background or old frames stay on screen and the UI smears.
        try:
            from home_screen import GREY_BG as base
        except Exception:
            base = "#3a3a3a"
        # panels and the module frames inside them must paint opaque, or the
        # translucent window lets old frames show through
        for side, box in getattr(self, "panels_by_side", {}).items():
            box.setStyleSheet(f"QWidget#panelbox_{side}{{background:{base};}}")
            box.setAutoFillBackground(True)
        for m in getattr(self, "panels", []):
            if m.container is not None:
                m.container.setStyleSheet(
                    f"QWidget#modframe_{m.ID}{{background:{base};}}")
                m.container.setAutoFillBackground(True)
        # each panel then styles its own inner widget
        self._panels_notify("apply_theme", self._panel_css, (panel, text, border))
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
        self._panels_notify("on_project_opened", name)

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
        """Remember which panels are open and which modules each one holds, so
        the layout you build is the one you get back next launch."""
        try:
            layout = {}
            for side, box in getattr(self, "panels_by_side", {}).items():
                layout[side] = {
                    "open": box.isVisible(),
                    "modules": [m.ID for m in box.modules],
                    "sizes": box.stack.sizes(),
                }
            save_ui_state({
                "main": self._main_split.sizes(),
                "panels": layout,
            })
        except Exception:
            pass

    def _restore_layout(self):
        st = load_ui_state()
        try:
            if st.get("main"):
                self._main_split.setSizes(st["main"])
        except Exception:
            pass
        # put the saved modules back where they were
        by_id = {m.ID: m for m in getattr(self, "all_modules", [])}
        for side, info in (st.get("panels") or {}).items():
            box = getattr(self, "panels_by_side", {}).get(side)
            if box is None:
                continue
            for mid in info.get("modules", []):
                mod = by_id.get(mid)
                if mod is not None and mod.host is None:
                    box.add_module(mod)
            if info.get("open"):
                self.toggle_panel(side, True)
            try:
                if info.get("sizes"):
                    box.stack.setSizes(info["sizes"])
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
