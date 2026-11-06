"""
ButtonNode — a button that knows how long you held it.

    The old version could do two things, and both were bad. "Wait here
    until pressed" compiles to

        while (digitalRead(pin) == HIGH) { }

    which freezes the entire board: no screen, no countdown, no second
    button. And the other mode just read the pin level, which tells you
    nothing about *when* it changed, so you cannot tell a tap from a
    hold, and a single press fires on every one of the thousands of loop
    passes your finger is down for.

    This one polls, debounces, and reports EVENTS, each of which happens
    once:

        output 0  "tap"     -> pressed and let go, under the long time
        output 1  "hold"    -> held past the long time (fires once, while
                               still held, so you feel it happen)
        output 2  "repeat"  -> once on the press, then over and over
                               while held, for +1 fields that run up

    At most one fires per pass, so they compile to one if/else-if chain
    and never both run.

    It also leaves a plain bool you can test in an If node:

        btn_<name>_down     true for as long as it is held

    Two buttons is enough for a whole interface: tap to move between
    fields, hold to confirm, repeat to run a number up.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device_base import DeviceNode


class ButtonNode(DeviceNode):
    TYPE = "device.button"
    TITLE = "Button"
    CATEGORY = "robotics"
    INPUTS = 1
    OUTPUTS = 3          # [0] tap, [1] hold, [2] repeat
    IS_BRANCH = True

    PARAMS = [
        {"key": "name", "label": "Button name", "type": "text", "default": "b1"},
        {"key": "pin", "label": "Pin (as labelled on the board)",
         "type": "text", "default": "4"},
        {"key": "wiring", "label": "Wiring", "type": "select",
         "default": "pullup (press = LOW)",
         "options": ["pullup (press = LOW)", "pulldown (press = HIGH)"]},
        {"key": "long_ms", "label": "Hold counts as a hold after (ms)",
         "type": "number", "default": 700},
        {"key": "repeat_delay", "label": "Repeat starts after (ms)",
         "type": "number", "default": 450},
        {"key": "repeat_rate", "label": "Then one repeat every (ms)",
         "type": "number", "default": 60},
        {"key": "debounce_ms", "label": "Debounce (ms)", "type": "number",
         "default": 25},
    ]

    def _var(self):
        raw = str(self.p("name", "b1")).strip()
        return "btn_" + ("".join(c if (c.isalnum() or c == "_") else "_"
                                 for c in raw) or "b1")

    def _pressed_is_low(self):
        return str(self.p("wiring", "pullup")).startswith("pullup")

    def globals(self):
        v = self._var()
        pin = self.pin("pin", "4")
        level = "LOW" if self._pressed_is_low() else "HIGH"
        long_ms = self.num("long_ms", 700)
        rdelay = self.num("repeat_delay", 450)
        rrate = self.num("repeat_rate", 60)
        deb = self.num("debounce_ms", 25)
        # ONE block: codegen de-duplicates globals line by line, which
        # would eat every bare "}" after the first.
        return ["\n".join([
            f"// --- {v}: debounced, non-blocking, reports events ---",
            f"bool {v}_down = false, {v}_longDone = false;",
            f"bool {v}_tap = false, {v}_hold = false, {v}_rep = false;",
            f"unsigned long {v}_t0 = 0, {v}_lastRep = 0, {v}_edge = 0;",
            f"void {v}_poll() {{",
            f"  {v}_tap = {v}_hold = {v}_rep = false;",
            f"  bool now = (digitalRead({pin}) == {level});",
            f"  unsigned long t = millis();",
            f"  if (now != {v}_down) {{",
            f"    // a real contact bounces for a few ms; ignore edges",
            f"    // that come too soon after the last one",
            f"    if (t - {v}_edge < {deb}UL) return;",
            f"    {v}_edge = t;",
            f"    if (now) {{",
            f"      {v}_down = true; {v}_longDone = false;",
            f"      {v}_t0 = {v}_lastRep = t; {v}_rep = true;",
            f"    }} else {{",
            f"      {v}_down = false;",
            f"      if (!{v}_longDone) {v}_tap = true;   // let go in time",
            f"    }}",
            f"    return;",
            f"  }}",
            f"  if ({v}_down) {{",
            f"    if (!{v}_longDone && t - {v}_t0 >= {long_ms}UL) {{",
            f"      {v}_longDone = true; {v}_hold = true;",
            f"    }}",
            f"    if (t - {v}_t0 > {rdelay}UL && t - {v}_lastRep > {rrate}UL) {{",
            f"      {v}_lastRep = t; {v}_rep = true;",
            f"    }}",
            f"  }}",
            f"}}",
        ])]

    def setup(self):
        mode = "INPUT_PULLUP" if self._pressed_is_low() else "INPUT"
        return [f"pinMode({self.pin('pin', '4')}, {mode});"]

    def loop(self):
        """Runs before the branch, every pass, whichever way it goes."""
        return [f"{self._var()}_poll();"]

    def condition(self, port=0):
        v = self._var()
        return {0: f"{v}_tap", 1: f"{v}_hold", 2: f"{v}_rep"}.get(port)
