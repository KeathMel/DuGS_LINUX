"""
BacklightNode — turn the screen down, or off.

    A screen that stays lit all night in a bedroom is a lamp. This drives
    the backlight pin, either hard on/off or dimmed with PWM.

    On the T-Display-S3 the backlight is GPIO38 and the default here is
    already right. On any other board, point it at whatever pin feeds
    your panel's LED line.

    Dimming needs PWM, which on an ESP32 is the LEDC peripheral, so this
    emits ledcAttach/ledcWrite there and analogWrite everywhere else.
    Note the resolution: 8 bits at 5kHz, well inside what the S3 allows
    (it tops out at 14, which is the thing that makes 16-bit servo code
    off the internet fail silently).

    Pair it with a Timer to drop the screen after a while:

        On Repeat -> Timer(20000) --done----> Backlight(off)
                          |
                          +--waiting--------> Screen(...)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device_base import DeviceNode


class BacklightNode(DeviceNode):
    TYPE = "device.backlight"
    TITLE = "Backlight"
    CATEGORY = "robotics"
    PARAMS = [
        {"key": "pin", "label": "Backlight pin (38 = T-Display-S3)",
         "type": "text", "default": "38"},
        {"key": "state", "label": "Set it to", "type": "select",
         "default": "on", "options": ["on", "off", "level"]},
        {"key": "level", "label": "Level 0-255 (when set to 'level')",
         "type": "text", "default": "60"},
    ]

    FREQ = 5000
    RES = 8

    def _var(self):
        return f"bl_{self.pin_var('pin', '38')}"

    def globals(self):
        if not self.is_esp32():
            return []
        v = self._var()
        return ["\n".join([
            f"// --- {v}: backlight, PWM dimmable ---",
            f"bool {v}_on = false;",
            f"void {v}_set(int lvl) {{",
            f"  lvl = constrain(lvl, 0, 255);",
            f"  if (!{v}_on) {{",
            f"    if (!ledcAttach({self.pin('pin', '38')}, {self.FREQ}, {self.RES})) {{",
            f'      Serial.println("{v}: ledcAttach FAILED");',
            f"      return;",
            f"    }}",
            f"    {v}_on = true;",
            f"  }}",
            f"  ledcWrite({self.pin('pin', '38')}, lvl);",
            f"}}",
        ])]

    def setup(self):
        if self.is_esp32():
            return []        # it attaches itself on the first write
        return [f"pinMode({self.pin('pin', '38')}, OUTPUT);"]

    def loop(self):
        state = self.p("state", "on")
        lvl = {"on": "255", "off": "0"}.get(
            state, str(self.p("level", "60")).strip() or "60")
        if self.is_esp32():
            return [f"{self._var()}_set({lvl});"]
        return [f"analogWrite({self.pin('pin', '38')}, {lvl});"]
