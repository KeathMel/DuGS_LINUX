"""
device_base.py — base class for HARDWARE nodes (servo projects).

A normal DUGS node runs Python on your PC. A device node is different: it does
not run at all — it EMITS ARDUINO C++ CODE. The workflow graph gets compiled
into a .ino sketch that you upload to the board, so the board runs standalone.

Each device node can contribute to four parts of the sketch:

    includes()   -> #include lines            (e.g. #include <Servo.h>)
    globals()    -> global declarations       (e.g. Servo servo9;)
    setup()      -> lines inside setup()      (e.g. servo9.attach(9);)
    loop()       -> lines inside loop()       (the node's actual action)

The generator walks the graph in execution order and stitches these together.
Duplicate includes/globals/setup lines are automatically de-duplicated, so two
Servo nodes on the same pin don't emit the header twice.

THE BOARD
    Which board you are building for changes what a node must emit, not just
    which pin number it writes. A servo on an Uno is Servo.h; on an ESP32-S3
    there is no Servo.h at all and it is the LEDC peripheral instead. So the
    board is read once from the Pins node before generation and every node can
    ask for it with self.is_esp32() / self.is_tdisplay().
"""

# Set once per generate() from the Pins node. All node modules share this,
# because they all import this one module.
BOARD = "arduino"

ESP32_BOARDS = ("esp32", "esp32-s3", "t-display-s3")


def set_board(name):
    global BOARD
    BOARD = (str(name or "arduino")).strip().lower()


def get_board():
    return BOARD


class DeviceNode:
    TYPE = "device.base"
    TITLE = "Device"
    CATEGORY = "device"
    INPUTS = 1
    OUTPUTS = 1
    PARAMS = []

    # marks this as a code-generating node (servo projects only)
    IS_DEVICE = True

    def __init__(self, name, params=None):
        self.name = name
        self.params = params or {}

    # ---- the board -----------------------------------------------------
    def board(self):
        return get_board()

    def is_esp32(self):
        """True for anything in the ESP32 family.

        Matters because the whole PWM story is different: no Servo.h, no
        analogWrite channels, it is ledcAttach/ledcWrite instead.
        """
        return get_board() in ESP32_BOARDS

    def is_tdisplay(self):
        """The LilyGO T-Display-S3 specifically -- it has a screen wired to
        fixed pins, so the Screen node can configure itself."""
        return get_board() == "t-display-s3"

    # ---- helpers -------------------------------------------------------
    def p(self, key, default=None):
        v = self.params.get(key, default)
        return default if v in (None, "") else v

    def pin(self, key="pin", default="9"):
        """The pin as WRITTEN ON THE BOARD, used verbatim in the generated code.

        Whatever you type goes straight through: 9, A0, D13, GPIO17, LED_BUILTIN.
        That means this works on any board — we never translate or guess, we
        just emit the name you gave. Only whitespace is stripped.
        """
        v = self.params.get(key, default)
        if v is None or v == "":
            v = default
        return str(v).strip()

    def pin_var(self, key="pin", default="9"):
        """A safe C++ identifier derived from the pin name, for naming objects.
        Pin 'A0' -> 'A0'; 'GPIO17' -> 'GPIO17'; '9' -> '9' (prefixed by caller)."""
        raw = self.pin(key, default)
        return "".join(c if (c.isalnum() or c == "_") else "_" for c in raw)

    def num(self, key, default=0):
        try:
            v = float(self.p(key, default))
            return int(v) if v == int(v) else v
        except (TypeError, ValueError):
            return default

    # ---- code contributions (override these) ---------------------------
    def includes(self) -> list[str]:
        return []

    def globals(self) -> list[str]:
        return []

    def setup(self) -> list[str]:
        return []

    def loop(self) -> list[str]:
        """The lines this node contributes to the main loop, in graph order."""
        return []

    # device nodes never execute in the Python engine
    def run(self, items):
        return items
