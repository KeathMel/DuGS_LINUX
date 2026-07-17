"""
canvas.py — the node-graph editor surface: CanvasNode (visual model for a
node) and Canvas (the QWidget that draws/drags/wires nodes together).
"""
import os
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPainterPath, QFont, QPixmap, QIcon
)
try:
    from PyQt6.QtSvg import QSvgRenderer
    _HAS_SVG = True
except Exception:
    _HAS_SVG = False

from theme import ACCENT, NODE_SIZE


# ---------------------------------------------------------------------------
# Node icons
# ---------------------------------------------------------------------------
# Icons live in a folder next to this file (default: ./nodes_images). For each
# node type we try a list of likely filenames so it works no matter how the
# image files happen to be named. Resolved pixmaps are cached by (type, size).
#
# IF and Switch intentionally share one icon (both are "branch" logic).
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes_images")

# extra/alias name stems to try per node type, beyond the automatic ones
_ICON_ALIASES = {
    "logic.if":         ["if", "logic_if", "branch", "switch", "logic_switch"],
    "logic.switch":     ["switch", "logic_switch", "branch", "if", "logic_if"],
    "core.merge":       ["merge", "core_merge"],
    "core.set":         ["set", "core_set", "edit", "edit_fields"],
    "core.code":        ["code", "core_code"],
    "core.log":         ["log", "core_log", "noop"],
    "core.wait":        ["wait", "core_wait", "clock"],
    "data.tabel":       ["tabel", "table", "data_tabel", "sheet"],
    "web.http":         ["http", "web_http", "httprequest", "http_request", "globe"],
    "ai.agent":         ["ai", "ai_agent", "agent", "brain", "sparkle", "claude"],
    "trigger.manual":   ["manual", "trigger_manual", "manualtrigger", "play"],
    "webhook.trigger":  ["webhook", "webhook_trigger", "hook"],
    "webhook.respond":  ["respond", "webhook_respond", "respondtowebhook", "reply"],
}

_EXTS = (".png", ".svg", ".jpg", ".jpeg", ".webp")
_icon_path_cache = {}     # type_id -> resolved file path or None
_pixmap_cache = {}        # (path, w, h) -> QPixmap


def _candidate_stems(type_id):
    stems = []
    stems.extend(_ICON_ALIASES.get(type_id, []))
    # derive from the type id itself: "logic.switch" -> "logic_switch", "switch"
    flat = type_id.replace(".", "_")
    tail = type_id.split(".")[-1]
    for s in (flat, tail, type_id.replace(".", "-")):
        if s not in stems:
            stems.append(s)
    return stems


_icon_debug_done = False


def _icon_debug():
    """Print, once, what the icon loader sees — so a missing icon is obvious."""
    global _icon_debug_done
    if _icon_debug_done:
        return
    _icon_debug_done = True
    print("\n[icons] looking in:", ICON_DIR)
    if not os.path.isdir(ICON_DIR):
        print("[icons] FOLDER NOT FOUND — create it and put your images there,")
        print("[icons] it must sit right next to canvas.py.")
        return
    try:
        files = os.listdir(ICON_DIR)
    except OSError as e:
        print("[icons] cannot read folder:", e); return
    print("[icons] files present:", files if files else "(empty!)")


def resolve_icon_path(type_id):
    if type_id in _icon_path_cache:
        return _icon_path_cache[type_id]
    _icon_debug()
    found = None
    if os.path.isdir(ICON_DIR):
        # build a lowercased index of files in the dir once per lookup
        try:
            entries = os.listdir(ICON_DIR)
        except OSError:
            entries = []
        lower = {e.lower(): e for e in entries}
        for stem in _candidate_stems(type_id):
            for ext in _EXTS:
                key = (stem + ext).lower()
                if key in lower:
                    found = os.path.join(ICON_DIR, lower[key])
                    break
            if found:
                break
    _icon_path_cache[type_id] = found
    return found


def node_pixmap(type_id, size):
    """Return a QPixmap for the node type at the given square size, or None."""
    path = resolve_icon_path(type_id)
    if not path:
        return None
    ck = (path, size, size)
    if ck in _pixmap_cache:
        return _pixmap_cache[ck]
    pm = None
    if path.lower().endswith(".svg") and _HAS_SVG:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        r = QSvgRenderer(path)
        from PyQt6.QtGui import QPainter as _QP
        p = _QP(pm); r.render(p); p.end()
    else:
        src = QPixmap(path)
        if not src.isNull():
            pm = src.scaled(size, size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
    _pixmap_cache[ck] = pm
    return pm


def node_qicon(type_id, size=18):
    pm = node_pixmap(type_id, size)
    return QIcon(pm) if pm is not None else None


class CanvasNode:
    _counter = 0

    def __init__(self, type_id, title, inputs, outputs, x, y, name=None, params=None,
                 category=None):
        CanvasNode._counter += 1
        self.id = CanvasNode._counter
        self.type_id = type_id; self.title = title
        self.inputs = inputs; self.outputs = outputs
        self.name = name or f"{title} {self.id}"
        self.x = x; self.y = y
        # robotics/device nodes are wiring pieces, not full logic blocks —
        # draw them noticeably smaller so a hardware graph stays readable.
        self.is_device = str(type_id).startswith("device.")
        self.category = category or ("robotics" if self.is_device else "")
        self.s = int(NODE_SIZE * 0.6) if self.is_device else NODE_SIZE
        self.params = params or {}

    def rect(self): return QRectF(self.x, self.y, self.s, self.s)
    def del_rect(self): return QRectF(self.x + self.s - 18, self.y + 2, 16, 16)

    # ---- effective port counts (some nodes vary with their params) -------
    def n_inputs(self):
        if self.type_id == "core.merge":
            try: return max(1, int(self.params.get("num_inputs", 2) or 2))
            except (TypeError, ValueError): return 2
        return self.inputs

    def n_outputs(self):
        if self.type_id == "logic.switch":
            try: n = max(1, int(self.params.get("num_outputs", 4) or 4))
            except (TypeError, ValueError): n = 4
            if self.params.get("fallback") == "extra":
                n += 1
            return n
        return self.outputs

    # ---- per-port positions (evenly spaced down the side) ----------------
    def _port_y(self, idx, count):
        if count <= 1:
            return self.y + self.s / 2
        # spread across the node height with small margins
        top = self.y + 10
        usable = self.s - 20
        return top + usable * (idx / (count - 1))

    def in_port(self, idx=0):
        return QPointF(self.x, self._port_y(idx, self.n_inputs()))

    def out_port(self, idx=0):
        return QPointF(self.x + self.s, self._port_y(idx, self.n_outputs()))


class Canvas(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setMinimumSize(500, 500)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.nodes = []; self.connections = []
        self.dragging = None; self.drag_off = QPointF()
        self.wire_from = None; self.selected = None; self.selected_conn = None
        self.selected_nodes = set()      # multi-selection for mass move
        self._band_start = None          # rubber-band selection origin (world)
        self._band_now = None
        self._group_drag = None          # {node: (dx,dy)} offsets during group move
        self._mouse = QPointF(); self.hovered = None
        self.hovered_conn = None
        self.offset = QPointF(0, 0)
        self.scale = 1.0          # canvas zoom factor (scroll to change)
        self.panning = False; self.pan_start = QPointF()
        self.running_node = None
        self.ran_nodes = set()
        # --- live run visualisation state ---
        self.run_states = {}      # node name -> "running" | "done" | "error"
        self.edge_counts = {}     # (src, out, dst, in) -> item count shown on wire
        self.active_edge = None   # edge key currently pulsing
        self._pulse_t = 0.0       # 0..1 progress of the travelling dot
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._advance_pulse)
        self.setMouseTracking(True)

    def pulse_edge(self, key):
        """Start a dot travelling along the given wire to show data moving."""
        self.active_edge = key
        self._pulse_t = 0.0
        if not self._pulse_timer.isActive():
            self._pulse_timer.start(16)   # ~60fps

    def _advance_pulse(self):
        self._pulse_t += 0.06
        if self._pulse_t >= 1.0:
            self._pulse_t = 0.0
            self.active_edge = None
            self._pulse_timer.stop()
        self.update()

    def world(self, pos):
        return QPointF((pos.x() - self.offset.x()) / self.scale,
                       (pos.y() - self.offset.y()) / self.scale)

    def clear(self):
        self.nodes.clear(); self.connections.clear()
        self.selected = None; self.selected_conn = None
        self.running_node = None; self.ran_nodes.clear()
        self.run_states.clear(); self.edge_counts.clear()
        self.active_edge = None
        self.update()

    def add_node(self, meta):
        n = CanvasNode(meta["type"], meta["title"], meta["inputs"], meta["outputs"],
                       60 + (len(self.nodes) * 24) % 280, 60 + (len(self.nodes) * 30) % 280,
                       category=meta.get("category"))
        for p in meta.get("params", []): n.params[p["key"]] = p.get("default")
        self.nodes.append(n); self.select_node(n); self.update(); return n

    def select_node(self, n):
        self.selected = n; self.selected_conn = None; self.editor.show_node_settings(n)

    def node_at(self, wpos):
        for n in reversed(self.nodes):
            if n.rect().contains(wpos): return n
        return None

    def port_at(self, wpos):
        r = 16
        for n in self.nodes:
            no = n.n_outputs()
            for i in range(no):
                if (wpos - n.out_port(i)).manhattanLength() < r:
                    return ("out", n, i)
            ni = n.n_inputs()
            for i in range(ni):
                if n.inputs > 0 and (wpos - n.in_port(i)).manhattanLength() < r:
                    return ("in", n, i)
        return None

    def conn_at(self, wpos):
        for i, (src, oi, dst, ii) in enumerate(self.connections):
            a, b = src.out_port(oi), dst.in_port(ii)
            mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
            if (wpos - mid).manhattanLength() < 18: return i
        return None

    def conn_mid(self, idx):
        src, oi, dst, ii = self.connections[idx]
        a, b = src.out_port(oi), dst.in_port(ii)
        return QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)

    def conn_del_rect(self, idx):
        m = self.conn_mid(idx)
        return QRectF(m.x() - 9, m.y() - 9, 18, 18)

    def run_rect(self, n):
        return QRectF(n.x + 2, n.y + 2, 16, 16)

    def delete_selected(self):
        # a multi-selection deletes every node in it
        if len(self.selected_nodes) > 1:
            targets = set(self.selected_nodes)
            self.connections = [c for c in self.connections
                                if c[0] not in targets and c[2] not in targets]
            self.nodes = [x for x in self.nodes if x not in targets]
            self.selected_nodes = set(); self.selected = None
            self.editor.show_node_settings(None)
            self.editor.mark_changed(); self.update(); return
        if self.selected is not None:
            n = self.selected
            self.connections = [c for c in self.connections if c[0] is not n and c[2] is not n]
            self.nodes = [x for x in self.nodes if x is not n]
            self.selected = None; self.selected_nodes = set()
            self.editor.show_node_settings(None)
        elif self.selected_conn is not None:
            del self.connections[self.selected_conn]; self.selected_conn = None
        self.editor.mark_changed(); self.update()

    def mouseDoubleClickEvent(self, e):
        wpos = self.world(QPointF(e.position()))
        n = self.node_at(wpos)
        if n is not None:
            self.select_node(n)
            self.editor.open_node_popup(n)

    def wheelEvent(self, e):
        # scroll up = zoom in, scroll down = zoom out, anchored at the cursor
        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = 1.0015 ** delta
        new_scale = max(0.2, min(4.0, self.scale * factor))
        if new_scale == self.scale:
            return
        cpos = QPointF(e.position())
        before = self.world(cpos)
        self.scale = new_scale
        # keep the same world point under the cursor: offset = screen - world*scale
        self.offset = QPointF(cpos.x() - before.x() * self.scale,
                              cpos.y() - before.y() * self.scale)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.offset)
        p.scale(self.scale, self.scale)
        for i, (src, oi, dst, ii) in enumerate(self.connections):
            a, b = src.out_port(oi), dst.in_port(ii); sel = (i == self.selected_conn)
            key = (src.name, oi, dst.name, ii)
            is_active = (self.active_edge == key)
            if is_active:
                wire_col = QColor("#ffd166")
            elif sel:
                wire_col = QColor("#ff6b6b")
            else:
                wire_col = QColor(ACCENT)
            p.setPen(QPen(wire_col, 2.6 if (sel or is_active) else 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(a); cx = (a.x() + b.x()) / 2
            c1 = QPointF(cx, a.y()); c2 = QPointF(cx, b.y())
            path.cubicTo(c1, c2, b); p.drawPath(path)

            # item-count badge at wire midpoint (after a run delivers items)
            cnt = self.edge_counts.get(key)
            if cnt is not None:
                t = 0.5
                mt = path.pointAtPercent(t)
                badge = QRectF(mt.x() - 13, mt.y() - 8, 26, 16)
                p.setBrush(QBrush(QColor(20, 20, 20, 230)))
                p.setPen(QPen(wire_col, 1))
                p.drawRoundedRect(badge, 7, 7)
                p.setPen(QColor("#fff")); fb = QFont("monospace"); fb.setPointSize(7); fb.setBold(True); p.setFont(fb)
                p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(cnt))

            # travelling pulse dot showing data moving along this wire
            if is_active:
                pt = path.pointAtPercent(max(0.0, min(1.0, self._pulse_t)))
                p.setBrush(QBrush(QColor("#ffd166"))); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(pt, 5, 5)

            # delete badge when this connection is hovered or selected
            if i == self.hovered_conn or i == self.selected_conn:
                m = self.conn_mid(i)
                br = QRectF(m.x() - 9, m.y() - 9, 18, 18)
                p.setBrush(QBrush(QColor(40, 16, 16, 240)))
                p.setPen(QPen(QColor("#ff6b6b"), 1.4))
                p.drawEllipse(br)
                p.setPen(QColor("#ff6b6b")); ft = QFont("monospace"); ft.setPointSize(10); ft.setBold(True); p.setFont(ft)
                p.drawText(br, Qt.AlignmentFlag.AlignCenter, "x")
        if self.wire_from:
            n, oi = self.wire_from
            p.setPen(QPen(QColor(ACCENT), 1.2, Qt.PenStyle.DashLine))
            p.drawLine(n.out_port(oi), self.world(self._mouse))
        for n in self.nodes:
            is_sel = (n is self.selected) or (n in self.selected_nodes)
            state = self.run_states.get(n.name)
            running = (state == "running")
            done = (state == "done")
            errored = (state == "error")
            # base colour by category: triggers = white, robotics = red,
            # everything else keeps the normal accent.
            if getattr(n, "is_device", False) or n.category == "robotics":
                base = QColor("#ff6b6b")
            elif n.category == "trigger":
                base = QColor("#ffffff")
            else:
                base = QColor(ACCENT)

            if running:    border = QColor("#ffd166")
            elif errored:  border = QColor("#ff6b6b")
            elif done:     border = QColor("#7CFC9B")
            elif is_sel:   border = QColor(ACCENT)
            else:          border = base
            p.setPen(QPen(border, 2.6 if (running or is_sel or errored) else 1))
            if running:    fill = QColor(46, 42, 14, 240)
            elif errored:  fill = QColor(46, 16, 16, 240)
            elif done:     fill = QColor(14, 34, 20, 240)
            else:          fill = QColor(15, 15, 15, 235)
            p.setBrush(QBrush(fill)); p.drawRoundedRect(n.rect(), 4, 4)

            # --- node icon, centered (n8n-style) ---
            if getattr(n, "is_device", False):
                # --- compact hardware node: just the title inside, no type id ---
                p.setPen(base); f = QFont("monospace")
                f.setPointSize(7); f.setBold(True); p.setFont(f)
                p.drawText(n.rect(), Qt.AlignmentFlag.AlignCenter, n.title)
                # the node's NAME sits under the block (n8n style) so the small
                # box stays uncluttered
                p.setPen(QColor("#888")); f2 = QFont("monospace"); f2.setPointSize(7); p.setFont(f2)
                p.drawText(QRectF(n.x - 20, n.y + n.s + 2, n.s + 40, 12),
                           Qt.AlignmentFlag.AlignCenter, n.name)
            else:
                icon_sz = int(n.s * 0.5)
                pm = node_pixmap(n.type_id, icon_sz)
                if pm is not None:
                    ix = n.x + (n.s - pm.width()) / 2
                    iy = n.y + (n.s - pm.height()) / 2 - 6
                    p.drawPixmap(int(ix), int(iy), pm)
                    p.setPen(base); f = QFont("monospace"); f.setPointSize(8); f.setBold(True); p.setFont(f)
                    p.drawText(QRectF(n.x, n.y + n.s - 30, n.s, 14),
                               Qt.AlignmentFlag.AlignCenter, n.title)
                else:
                    p.setPen(base); f = QFont("monospace"); f.setPointSize(9); f.setBold(True); p.setFont(f)
                    p.drawText(n.rect(), Qt.AlignmentFlag.AlignCenter, n.title)

                p.setPen(QColor(ACCENT)); f2 = QFont("monospace"); f2.setPointSize(7); p.setFont(f2)
                p.drawText(QRectF(n.x, n.y + n.s - 18, n.s, 16), Qt.AlignmentFlag.AlignCenter, n.type_id)
            # status glyph top-right corner during/after a run
            if state:
                glyph = {"running": "▶", "done": "✓", "error": "✗"}.get(state, "")
                gcol = {"running": "#ffd166", "done": "#7CFC9B", "error": "#ff6b6b"}.get(state, "#fff")
                p.setPen(QColor(gcol)); fg = QFont("monospace"); fg.setPointSize(10); fg.setBold(True); p.setFont(fg)
                p.drawText(QRectF(n.x + n.s - 20, n.y + 1, 18, 16), Qt.AlignmentFlag.AlignCenter, glyph)
            p.setBrush(QBrush(QColor(ACCENT))); p.setPen(QPen(QColor(ACCENT), 1))
            ni = n.n_inputs()
            if n.inputs > 0:
                for i in range(ni):
                    p.setBrush(QBrush(base)); p.setPen(QPen(base, 1))
                    p.drawEllipse(n.in_port(i), 7, 7)
                    p.setPen(QColor("#000")); f3 = QFont("monospace"); f3.setPointSize(5); f3.setBold(True); p.setFont(f3)
                    lbl = "IN" if ni == 1 else str(i)
                    p.drawText(QRectF(n.x - 16, n.in_port(i).y() - 6, 16, 12), Qt.AlignmentFlag.AlignCenter, lbl)
            no = n.n_outputs()
            if n.outputs > 0:
                for i in range(no):
                    p.setBrush(QBrush(base)); p.setPen(QPen(base, 1))
                    p.drawEllipse(n.out_port(i), 7, 7)
                    p.setPen(QColor("#000")); f3 = QFont("monospace"); f3.setPointSize(5); f3.setBold(True); p.setFont(f3)
                    lbl = "OUT" if no == 1 else str(i)
                    p.drawText(QRectF(n.x + n.s, n.out_port(i).y() - 6, 16, 12), Qt.AlignmentFlag.AlignCenter, lbl)
            p.setPen(QPen(QColor(ACCENT), 1)); p.setBrush(QBrush(QColor(ACCENT)))
            if n is self.hovered:
                dr = n.del_rect()
                p.setPen(QPen(QColor('#ff6b6b'), 1)); p.setBrush(QBrush(QColor(40, 15, 15, 230)))
                p.drawRoundedRect(dr, 3, 3)
                p.setPen(QColor('#ff6b6b')); fx = QFont('monospace'); fx.setPointSize(9); p.setFont(fx)
                p.drawText(dr, Qt.AlignmentFlag.AlignCenter, 'x')
                rr = self.run_rect(n)
                p.setPen(QPen(QColor('#7CFC9B'), 1)); p.setBrush(QBrush(QColor(15, 40, 20, 230)))
                p.drawRoundedRect(rr, 3, 3)
                p.setPen(QColor('#7CFC9B'))
                tri = QPainterPath()
                tri.moveTo(rr.x() + 5, rr.y() + 4); tri.lineTo(rr.x() + 12, rr.y() + 8)
                tri.lineTo(rr.x() + 5, rr.y() + 12); tri.closeSubpath()
                p.setBrush(QBrush(QColor('#7CFC9B'))); p.drawPath(tri)

        # rubber-band selection rectangle (drawn on top of everything)
        band = self._band_rect()
        if band is not None:
            p.setPen(QPen(QColor(ACCENT), 1, Qt.PenStyle.DashLine))
            p.setBrush(QBrush(QColor(126, 207, 255, 40)))
            p.drawRect(band)

    def mousePressEvent(self, e):
        self.setFocus()
        spos = QPointF(e.position()); wpos = self.world(spos)
        if e.button() == Qt.MouseButton.MiddleButton:
            self.panning = True; self.pan_start = spos; return
        for n in self.nodes:
            if n is self.hovered and self.run_rect(n).contains(wpos):
                self.editor.run_from(n.name); return
            if n is self.hovered and n.del_rect().contains(wpos):
                self.connections = [c for c in self.connections if c[0] is not n and c[2] is not n]
                self.nodes = [x for x in self.nodes if x is not n]
                if self.selected is n: self.selected = None; self.editor.show_node_settings(None)
                self.editor.mark_changed(); self.update(); return
        hit = self.port_at(wpos)
        if hit and hit[0] == "out":
            self.wire_from = (hit[1], hit[2]); self._mouse = spos; return
        n = self.node_at(wpos)
        if n:
            # if this node is part of a multi-selection, drag the WHOLE group
            if n in self.selected_nodes and len(self.selected_nodes) > 1:
                self.dragging = n
                self._drag_start_pos = (n.x, n.y)
                self.drag_off = wpos - QPointF(n.x, n.y)
                # remember each selected node's offset from the grabbed one
                self._group_drag = {m: (m.x - n.x, m.y - n.y) for m in self.selected_nodes}
                self.update(); return
            # otherwise single-select and drag just this node
            self.select_node(n); self.dragging = n
            self.selected_nodes = {n}
            self._group_drag = None
            self._drag_start_pos = (n.x, n.y)
            self.drag_off = wpos - QPointF(n.x, n.y); self.update(); return
        # click on a hovered/selected connection's delete badge removes it
        for ci_check in (self.hovered_conn, self.selected_conn):
            if ci_check is not None and ci_check < len(self.connections):
                if self.conn_del_rect(ci_check).contains(wpos):
                    del self.connections[ci_check]
                    self.hovered_conn = None; self.selected_conn = None
                    self.editor.mark_changed(); self.update(); return
        ci = self.conn_at(wpos)
        if ci is not None:
            self.selected = None; self.selected_conn = ci
            self.selected_nodes = set()
            self.editor.show_node_settings(None); self.update(); return
        # empty space: start a rubber-band box selection
        self.selected = None; self.selected_conn = None
        self.selected_nodes = set()
        self._band_start = wpos; self._band_now = wpos
        self.editor.show_node_settings(None); self.update()

    def mouseMoveEvent(self, e):
        spos = QPointF(e.position()); self._mouse = spos; wpos = self.world(spos)
        if self.panning:
            d = spos - self.pan_start; self.offset += d; self.pan_start = spos; self.update(); return
        new_hover = self.node_at(wpos)
        if new_hover is not self.hovered: self.hovered = new_hover; self.update()
        # track which connection (if any) the cursor is near, to show a
        # delete badge on its midpoint
        new_chover = self.conn_at(wpos) if new_hover is None else None
        if new_chover is not getattr(self, "hovered_conn", None):
            self.hovered_conn = new_chover; self.update()
        if self.dragging:
            gx = (wpos - self.drag_off).x()
            gy = (wpos - self.drag_off).y()
            if self._group_drag:
                # move every selected node, keeping their relative offsets
                for m, (ox, oy) in self._group_drag.items():
                    m.x = gx + ox; m.y = gy + oy
            else:
                self.dragging.x = gx; self.dragging.y = gy
            self.update()
        elif self._band_start is not None:
            # extend the rubber-band box and live-select nodes inside it
            self._band_now = wpos
            self.selected_nodes = set(self._nodes_in_band())
            self.update()
        elif self.wire_from: self.update()

    def _band_rect(self):
        """The rubber-band rectangle in world coords, or None."""
        if self._band_start is None or self._band_now is None:
            return None
        x1, y1 = self._band_start.x(), self._band_start.y()
        x2, y2 = self._band_now.x(), self._band_now.y()
        return QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def _nodes_in_band(self):
        r = self._band_rect()
        if r is None:
            return []
        return [n for n in self.nodes if r.intersects(n.rect())]

    def mouseReleaseEvent(self, e):
        spos = QPointF(e.position()); wpos = self.world(spos)
        if e.button() == Qt.MouseButton.MiddleButton:
            self.panning = False; return
        if self.wire_from:
            hit = self.port_at(wpos)
            if hit and hit[0] == "in" and hit[1] is not self.wire_from[0]:
                src, oi = self.wire_from
                self.connections.append((src, oi, hit[1], hit[2]))
                self.editor.mark_changed()
            self.wire_from = None; self.update()
        # finish a rubber-band selection
        if self._band_start is not None:
            self.selected_nodes = set(self._nodes_in_band())
            self._band_start = None; self._band_now = None
            # if exactly one got selected, treat it as the normal selection
            if len(self.selected_nodes) == 1:
                only = next(iter(self.selected_nodes))
                self.select_node(only)
            self.update()
        if self.dragging is not None:
            moved = (self.dragging.x, self.dragging.y) != getattr(self, "_drag_start_pos", None)
            self.dragging = None
            self._group_drag = None
            if moved:
                self.editor.mark_changed()
        self.dragging = None

    def event(self, e):
        # Tab is normally consumed by focus traversal; intercept it so the
        # canvas can use it to open the hovered node's quick-edit popup.
        from PyQt6.QtCore import QEvent
        if e.type() == QEvent.Type.KeyPress and e.key() == Qt.Key.Key_Tab:
            target = self.hovered or self.selected
            if target is not None:
                self.editor.open_node_popup(target)
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        elif e.key() == Qt.Key.Key_Tab:
            target = self.hovered or self.selected
            if target is not None:
                self.editor.open_node_popup(target)

    def to_workflow(self, name="untitled"):
        nodes = [{"name": n.name, "type": n.type_id, "params": n.params,
                  "_x": n.x, "_y": n.y} for n in self.nodes]
        conns = {}
        for src, oi, dst, ii in self.connections:
            conns.setdefault(src.name, []).append({"to": dst.name, "out": oi, "in": ii})
        return {"name": name, "nodes": nodes, "connections": conns}

    def load_workflow(self, wf, meta_by_type):
        self.clear(); by_name = {}
        for nspec in wf.get("nodes", []):
            meta = meta_by_type.get(nspec["type"], {"title": nspec["type"], "inputs": 1, "outputs": 1})
            n = CanvasNode(nspec["type"], meta.get("title", nspec["type"]),
                           meta.get("inputs", 1), meta.get("outputs", 1),
                           nspec.get("_x", 80), nspec.get("_y", 80),
                           name=nspec["name"], params=nspec.get("params", {}),
                           category=meta.get("category"))
            self.nodes.append(n); by_name[n.name] = n
        for src_name, links in wf.get("connections", {}).items():
            for link in links:
                src = by_name.get(src_name); dst = by_name.get(link["to"])
                if src and dst:
                    self.connections.append((src, link.get("out", 0), dst, link.get("in", 0)))
        self.update()
