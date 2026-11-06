#!/usr/bin/env python3
"""
sim_view.py — the bird's-eye view of a robotics graph running.

A log of events tells you WHAT happened. This tells you whether the
thing you built makes sense: the board with its pins labelled, a servo
box with a horn that actually swings to the angle, and the screen at the
size you said, with your text on it where you put it.

Everything is drawn from the events simulate.py emits, so the picture
and the generated C++ come from the same graph. If the horn swings the
wrong way here, it swings the wrong way on your desk.

    python3 sim_view.py myproject.json          standalone
    SimWindow(workflow).show()                  from the editor

WHAT YOU SEE
    board    pin headers down both sides. A pin you named in the Pins
             node shows its name and what uses it. GND and the 5V rail
             are marked amber with a note, because they are the two
             everybody forgets and nothing works without them.
    servo    a box seen from above with a horn on top. It swings at a
             real SG90's speed, so a move that looks instant in the code
             takes the third of a second it really takes.
    screen   drawn at the width and height set in the Screen node, with
             the text at its x/y in its size and colour. Move the
             numbers in the node, watch the layout move here.
"""
import json
import math
import os
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QPainter,
                         QPainterPath, QPen)
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
                             QPushButton, QSlider, QTextEdit, QVBoxLayout,
                             QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import simulate                                              # noqa: E402

# a real SG90 is about 0.1s per 60 degrees at 5V
SERVO_DEG_PER_SEC = 500.0

BG = QColor(20, 20, 24)
BOARD = QColor(32, 44, 38)
BOARD_EDGE = QColor(90, 120, 100)
PIN_IDLE = QColor(70, 70, 76)
PIN_USED = QColor(90, 180, 230)
PIN_POWER = QColor(235, 175, 70)
TEXT = QColor(225, 222, 212)
DIM = QColor(130, 128, 122)
SERVO_BODY = QColor(52, 54, 62)
SERVO_HORN = QColor(240, 240, 245)
SERVO_LIMP = QColor(120, 122, 130)
WIRE = QColor(120, 140, 160)

SCREEN_COLORS = {"white": "#ffffff", "yellow": "#ffd400", "green": "#00e050",
                 "cyan": "#00e5ff", "red": "#ff4040", "grey": "#808080"}


class SimWorker(QThread):
    """Runs simulate.py off the GUI thread and re-emits each event."""
    event = pyqtSignal(dict)

    def __init__(self, workflow, speed=60.0):
        super().__init__()
        self.workflow = workflow
        self.speed = speed
        self._stop = False
        self._presses = []

    def stop(self):
        self._stop = True

    def press(self, name, what):
        self._presses.append((name, what))

    def _drain(self):
        out, self._presses = self._presses, []
        return out

    def run(self):
        try:
            simulate.simulate(self.workflow, self.event.emit,
                              max_loops=None, realtime=True,
                              stop=lambda: self._stop,
                              speed=self.speed, press_queue=self._drain)
        except Exception as e:
            self.event.emit({"t": 0, "kind": "warn", "node": "",
                             "msg": f"simulation failed: {type(e).__name__}: {e}"})


class SimView(QWidget):
    """The picture. Fed events, paints the board, the servos and the screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(760, 420)
        self.reset()
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick)
        self._anim.start(33)               # ~30fps

    def reset(self):
        self.board = "arduino"
        self.pins = []
        self.power = []
        self.servos = {}       # pin -> {"target":deg, "cur":deg, "live":bool}
        self.pin_vals = {}
        self.screen_w = 0
        self.screen_h = 0
        self.screen_items = []  # [{"text","x","y","size","color"}]
        self.backlight = 255
        self.t = 0.0
        self.update()

    # ---- events ----
    def feed(self, e):
        k = e.get("kind")
        self.t = e.get("t", self.t)

        if k == "power_on":
            self.board = e.get("board", "arduino")
            self.pins = e.get("pins", [])
            self.power = e.get("power", [])
            # a sensible default panel until a Screen node says otherwise
            self.screen_w, self.screen_h = (
                (320, 170) if self.board == "t-display-s3" else (128, 64))
            self.screen_items = []
            self.servos = {}
            for p in self.pins:
                if p.get("role") == "servo":
                    self.servos[p["pin"]] = {"target": 0.0, "cur": 0.0, "live": False}

        elif k == "servo":
            s = self.servos.setdefault(e["pin"], {"target": 0.0, "cur": 0.0, "live": False})
            s["target"] = float(e.get("angle", 0))
            s["live"] = True

        elif k == "servo_release":
            if e["pin"] in self.servos:
                self.servos[e["pin"]]["live"] = False

        elif k == "pin":
            self.pin_vals[e["pin"]] = e.get("value", "")

        elif k == "backlight":
            self.backlight = int(e.get("level", 255))

        elif k == "screen":
            if e.get("w"):
                self.screen_w = int(e["w"])
            if e.get("h"):
                self.screen_h = int(e["h"])
            if e.get("clear", True):
                self.screen_items = []
            self.screen_items = [i for i in self.screen_items
                                 if i["y"] != e.get("y", 0)]
            self.screen_items.append({
                "text": str(e.get("text", "")), "x": int(e.get("x", 0)),
                "y": int(e.get("y", 0)), "size": int(e.get("size", 4)),
                "color": str(e.get("color", "white"))})

    def _tick(self):
        """Walk each horn toward its target at a real servo's speed."""
        step = SERVO_DEG_PER_SEC * 0.033
        moved = False
        for s in self.servos.values():
            d = s["target"] - s["cur"]
            if abs(d) < 0.5:
                if s["cur"] != s["target"]:
                    s["cur"] = s["target"]
                    moved = True
                continue
            s["cur"] += max(-step, min(step, d))
            moved = True
        if moved or True:
            self.update()

    # ---- painting ----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), BG)
        self._grid(p)

        w, h = self.width(), self.height()
        board_rect = QRectF(28, 46, 212, max(250, h - 110))
        pin_pts = self._draw_board(p, board_rect)

        # servos to the right of the board, stacked
        sx = board_rect.right() + 96
        sy = 78
        for pin in sorted(self.servos):
            c = self._draw_servo(p, QPointF(sx, sy), pin, self.servos[pin])
            if pin in pin_pts:
                self._wire(p, pin_pts[pin], QPointF(c.x() - 46, c.y()))
            sy += 150

        # screen on the far right, at whatever size the node asked for
        if self.screen_w and self.screen_h:
            self._draw_screen(p, QRectF(sx + 200, 78, 0, 0))
        p.end()

    def _grid(self, p):
        p.setPen(QPen(QColor(32, 32, 38), 1))
        for x in range(0, self.width(), 26):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 26):
            p.drawLine(0, y, self.width(), y)
        p.setPen(QPen(DIM, 1))
        p.setFont(QFont("monospace", 9))
        p.drawText(10, 20, f"t = {self.t:8.2f} s        board: {self.board}")

    def _draw_board(self, p, r):
        """The board from above, pins down both edges. Returns pin -> point."""
        p.setBrush(QBrush(BOARD))
        p.setPen(QPen(BOARD_EDGE, 1.5))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QPen(DIM, 1))
        p.setFont(QFont("monospace", 8, QFont.Weight.Bold))
        p.drawText(QRectF(r.left(), r.top() + 6, r.width(), 14),
                   Qt.AlignmentFlag.AlignCenter, self.board.upper())

        # the two that everything needs and everybody forgets
        rows = [{"name": pw["name"], "pin": "", "role": "power",
                 "note": pw.get("note", "")} for pw in self.power]
        rows += list(self.pins)

        pts = {}
        top = r.top() + 30
        gap = min(26.0, (r.height() - 46) / max(1, len(rows)))
        f = QFont("monospace", 8)
        p.setFont(f)
        fm = QFontMetrics(f)

        for i, row in enumerate(rows):
            y = top + i * gap + gap / 2
            x = r.left() + 14
            power = row.get("role") == "power"
            used = row.get("role") not in ("unused", None) and not power
            col = PIN_POWER if power else (PIN_USED if used else PIN_IDLE)

            p.setBrush(QBrush(col))
            p.setPen(QPen(col.darker(160), 1))
            p.drawEllipse(QPointF(x, y), 5, 5)

            p.setPen(QPen(TEXT if (used or power) else DIM, 1))
            label = row["name"] if power else f"{row['pin']}  {row['name']}"
            p.drawText(QPointF(x + 12, y + 4), label)

            if power:
                # the info badge. The note itself goes in the block at the
                # bottom of the board -- printed beside the pin it ran
                # straight through the servo sitting to the right.
                bx = r.right() - 16
                p.setBrush(QBrush(PIN_POWER))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(bx, y), 6, 6)
                p.setPen(QPen(QColor(30, 24, 10), 1))
                p.drawText(QRectF(bx - 6, y - 7, 12, 14),
                           Qt.AlignmentFlag.AlignCenter, "i")
                p.setFont(f)
            else:
                pts[row["pin"]] = QPointF(r.right() - 4, y)
                role = row.get("role", "unused")
                if role != "unused":
                    p.setPen(QPen(DIM, 1))
                    p.drawText(QPointF(x + 12 + fm.horizontalAdvance(label) + 8,
                                       y + 4), f"({role})")

        # the two notes, in the empty space under the pin list
        ny = top + len(rows) * gap + 14
        p.setPen(QPen(PIN_POWER.darker(110), 1))
        p.setFont(QFont("monospace", 7))
        for pw in self.power:
            box = QRectF(r.left() + 12, ny, r.width() - 24, 30)
            p.drawText(box, int(Qt.AlignmentFlag.AlignLeft |
                                Qt.AlignmentFlag.AlignTop) |
                       int(Qt.TextFlag.TextWordWrap),
                       f"i  {pw['name']}: {pw.get('note', '')}")
            ny += 32
        return pts

    def _wire(self, p, a, b):
        path = QPainterPath(a)
        mid = (a.x() + b.x()) / 2
        path.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(WIRE, 1.4))
        p.drawPath(path)

    def _draw_servo(self, p, top_left, pin, s):
        """A servo from above: body, and a horn that really swings."""
        body = QRectF(top_left.x(), top_left.y(), 92, 46)
        centre = QPointF(body.center().x(), body.center().y())

        p.setBrush(QBrush(SERVO_BODY))
        p.setPen(QPen(QColor(96, 100, 112), 1.4))
        p.drawRoundedRect(body, 4, 4)
        # the mounting tabs, so it reads as a servo and not a box
        p.setBrush(QBrush(SERVO_BODY.lighter(115)))
        p.drawRect(QRectF(body.left() - 10, body.top() + 8, 10, 12))
        p.drawRect(QRectF(body.right(), body.top() + 8, 10, 12))

        live = s["live"]
        horn_col = SERVO_HORN if live else SERVO_LIMP
        # 0 = left, 90 = straight up, 180 = right, which is the half
        # circle the dashed arc shows. Qt's y runs down, so the 180
        # offset is what keeps "up" up.
        ang = math.radians(180 + s["cur"])
        L = 54
        tip = QPointF(centre.x() + L * math.cos(ang), centre.y() + L * math.sin(ang))

        # the arc it can reach, so 0 and 180 are visible as limits
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(70, 72, 80), 1, Qt.PenStyle.DashLine))
        p.drawArc(QRectF(centre.x() - L, centre.y() - L, 2 * L, 2 * L),
                  0 * 16, 180 * 16)

        p.setPen(QPen(horn_col, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(centre, tip)
        p.setBrush(QBrush(QColor(200, 60, 60) if live else QColor(90, 90, 96)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(centre, 6, 6)

        p.setPen(QPen(TEXT, 1))
        p.setFont(QFont("monospace", 8, QFont.Weight.Bold))
        p.drawText(QPointF(body.left(), body.bottom() + 16),
                   f"servo  pin {pin}")
        p.setPen(QPen(DIM, 1))
        p.setFont(QFont("monospace", 8))
        p.drawText(QPointF(body.left(), body.bottom() + 30),
                   f"{s['cur']:5.1f} deg   {'holding' if live else 'limp'}")
        return centre

    def _draw_screen(self, p, anchor):
        """At the node's own width and height, so the layout you see here
        is the layout the board draws."""
        avail_w, avail_h = 300.0, float(self.height() - 150)
        scale = min(avail_w / self.screen_w, avail_h / self.screen_h, 2.0)
        w, h = self.screen_w * scale, self.screen_h * scale
        r = QRectF(anchor.x(), anchor.y(), w, h)

        p.setBrush(QBrush(QColor(60, 62, 68)))
        p.setPen(QPen(QColor(100, 104, 112), 1.4))
        p.drawRoundedRect(r.adjusted(-7, -7, 7, 7), 4, 4)

        dim = max(0.12, self.backlight / 255.0)
        p.setBrush(QBrush(QColor(int(8 * dim), int(9 * dim), int(12 * dim))))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(r)

        p.save()
        p.setClipRect(r)
        for it in self.screen_items:
            col = QColor(SCREEN_COLORS.get(it["color"], "#ffffff"))
            col.setAlphaF(dim)
            p.setPen(QPen(col, 1))
            # Arduino_GFX size N is a 6x8 cell scaled N times
            px = max(5.0, it["size"] * 8 * scale)
            f = QFont("monospace", 1)
            f.setPixelSize(int(px))
            p.setFont(f)
            p.drawText(QPointF(r.left() + it["x"] * scale,
                               r.top() + (it["y"] + it["size"] * 8) * scale),
                       it["text"])
        p.restore()

        p.setPen(QPen(DIM, 1))
        p.setFont(QFont("monospace", 8))
        p.drawText(QPointF(r.left(), r.bottom() + 20),
                   f"screen  {self.screen_w} x {self.screen_h}")
        p.drawText(QPointF(r.left(), r.bottom() + 34),
                   f"backlight {self.backlight}")


class SimWindow(QMainWindow):
    """The view, a speed control, and a press button per declared button.

    The buttons matter: a simulation nobody can press only ever shows you
    the idle path. These inject the same down/up the board would see, so
    tap, hold and repeat all behave as they will on the device.
    """

    def __init__(self, workflow, parent=None):
        super().__init__(parent)
        self.workflow = workflow
        self.setWindowTitle(f"simulate — {workflow.get('name', 'project')}")
        self.worker = None

        # A real window, not a panel and not fullscreen: big enough to
        # read the pin labels, small enough that the editor stays visible
        # behind it. Centred on the editor so it does not open off on
        # whichever monitor Qt last felt like.
        self.setMinimumSize(880, 500)
        self.resize(1100, 620)
        if parent is not None:
            g = parent.geometry()
            self.move(g.center().x() - 550, max(0, g.center().y() - 310))

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        bar = QHBoxLayout()
        self.btn_run = QPushButton("run")
        self.btn_run.clicked.connect(self.toggle)
        bar.addWidget(self.btn_run)

        bar.addWidget(QLabel("speed"))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(1, 600)        # 1x .. 600x
        self.speed.setValue(60)
        self.speed.setFixedWidth(150)
        self.speed_lbl = QLabel("60x")
        self.speed.valueChanged.connect(
            lambda n: self.speed_lbl.setText(f"{n}x"))
        bar.addWidget(self.speed)
        bar.addWidget(self.speed_lbl)
        bar.addSpacing(16)

        # one press button per Button node in the graph
        for n in workflow.get("nodes", []):
            if n["type"] == "device.button":
                nm = str((n.get("params") or {}).get("name", "b1"))
                b = QPushButton(f"press {nm}")
                b.pressed.connect(lambda nm=nm: self._press(nm, "down"))
                b.released.connect(lambda nm=nm: self._press(nm, "up"))
                bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)

        self.view = SimView()
        v.addWidget(self.view, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(110)
        self.log.setStyleSheet(
            "background:#15151a;color:#c8c6c0;font-family:monospace;font-size:11px;")
        v.addWidget(self.log)

    def _press(self, name, what):
        if self.worker:
            self.worker.press(name, what)

    def toggle(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(1500)
            self.worker = None
            self.btn_run.setText("run")
            return
        self.view.reset()
        self.log.clear()
        self.worker = SimWorker(self.workflow, speed=float(self.speed.value()))
        self.worker.event.connect(self.on_event)
        self.worker.start()
        self.btn_run.setText("stop")

    def on_event(self, e):
        self.view.feed(e)
        k = e.get("kind")
        # the screen redraws every pass; logging that is just noise
        if k in ("screen", "branch", "var", "code"):
            return
        bits = {kk: vv for kk, vv in e.items()
                if kk not in ("t", "kind", "node", "pins", "power")}
        self.log.append(f"{e.get('t', 0):8.2f}  {k:<16}"
                        f"{e.get('node', ''):<12}{bits if bits else ''}")
        self.log.verticalScrollBar().setValue(
            self.log.verticalScrollBar().maximum())

    def closeEvent(self, e):
        if self.worker:
            self.worker.stop()
            self.worker.wait(1500)
        super().closeEvent(e)


def main():
    if len(sys.argv) < 2:
        print("usage: python3 sim_view.py <project.json>")
        return 1
    with open(sys.argv[1]) as f:
        wf = json.load(f)
    app = QApplication(sys.argv)
    win = SimWindow(wf)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
