"""
CountdownNode — hours and minutes down to zero, then fire.

    Timer counts milliseconds, which is no use when you want "seven and a
    half hours from now": 27000000 is not a number anyone should type.
    This takes hours and minutes, and gives you the time left as a ready
    string to put on the screen.

    Two outputs, like Timer:

        output 0  "done"     -> it reached zero (runs once, then re-arms)
        output 1  "ticking"  -> still going; draw the screen, read buttons

    Nothing blocks. The board stays responsive the whole way down.

        On Repeat -> Countdown(7h 30m) --done-----> Servo(180)
                           |
                           +---ticking-----------> Screen(show cd1_clock())

    In a Screen node's "Show a variable" field:

        cd1_clock()   "07:29:58"  -- hours:minutes:seconds left
        cd1_secs()    27298       -- whole seconds left, as a number
        cd1_mins()    455         -- whole minutes left

    (swap cd1 for whatever you named it)

    "Re-arm after firing" off means it fires once and stays fired, which
    is what an alarm wants -- otherwise it would go off again every seven
    and a half hours forever.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device_base import DeviceNode


class CountdownNode(DeviceNode):
    TYPE = "device.countdown"
    TITLE = "Countdown"
    CATEGORY = "robotics"
    INPUTS = 1
    OUTPUTS = 2          # [0] = done, [1] = still ticking
    IS_BRANCH = True     # compiles to a real if/else

    PARAMS = [
        {"key": "name", "label": "Countdown name", "type": "text", "default": "cd1"},
        {"key": "hours", "label": "Hours — can be a variable",
         "type": "text", "default": "7"},
        {"key": "minutes", "label": "Minutes — can be a variable",
         "type": "text", "default": "30"},
        {"key": "autostart", "label": "Start it at power-on",
         "type": "bool", "default": True},
        {"key": "rearm", "label": "Re-arm after firing (off = fire once)",
         "type": "bool", "default": False},
    ]

    def _var(self):
        raw = str(self.p("name", "cd1")).strip()
        return "".join(c if (c.isalnum() or c == "_") else "_" for c in raw) or "cd1"

    def _total_ms(self):
        h = str(self.p("hours", "0")).strip() or "0"
        m = str(self.p("minutes", "0")).strip() or "0"
        return f"((unsigned long)({h}) * 3600000UL + (unsigned long)({m}) * 60000UL)"

    def globals(self):
        v = self._var()
        # ONE string: codegen de-duplicates globals line by line, which
        # eats every bare "}" after the first in a multi-line block.
        return ["\n".join([
            f"// --- {v}: countdown ---",
            f"unsigned long {v}_end = 0;",
            f"bool {v}_fired = false;",
            f"char {v}_buf[12];",
            f"long {v}_secs() {{",
            # both are unsigned, so once the deadline has passed the
            # subtraction wraps; the cast turns that back into a negative
            f"  long d = (long)({v}_end - millis());",
            f"  return d > 0 ? (d + 999) / 1000 : 0;",
            f"}}",
            f"long {v}_mins() {{ return {v}_secs() / 60; }}",
            f"const char* {v}_clock() {{",
            f"  long s = {v}_secs();",
            f'  snprintf({v}_buf, sizeof({v}_buf), "%02ld:%02ld:%02ld",',
            f"           s / 3600, (s % 3600) / 60, s % 60);",
            f"  return {v}_buf;",
            f"}}",
            f"void {v}_start() {{ {v}_end = millis() + {self._total_ms()}; "
            f"{v}_fired = false; }}",
        ])]

    def setup(self):
        if self.p("autostart", True):
            return [f"{self._var()}_start();"]
        return []

    def condition(self):
        v = self._var()
        if self.p("rearm", False):
            return f"millis() >= {v}_end"
        # fire once and stay fired: an alarm that repeats every 7h30 is
        # not an alarm, it is a problem
        return f"(millis() >= {v}_end && !{v}_fired)"

    def rearm(self):
        v = self._var()
        if self.p("rearm", False):
            return f"{v}_start();"
        return f"{v}_fired = true;"

    def loop(self):
        return []
