"""
ServoNode — one servo, on whatever board the Pins node says.

    On an Uno this is the Servo library and nothing interesting happens.

    On an ESP32 there IS NO Servo.h. The chip drives servos with its LEDC
    PWM peripheral instead, and the catch that costs an afternoon is the
    duty resolution: the original ESP32 does 20 bits, but the S3 and C3
    max out at 14. Every tutorial on the internet says 16, ledcAttach()
    quietly returns false, and the servo sits there doing nothing while
    you check your wiring six times. So: 14 bits here, and the generated
    code prints a line to Serial if the attach fails rather than failing
    silently the way it did to us.

    A servo also does not have to stay powered. "Release after moving"
    cuts the PWM once the move is done, which lets you turn the horn by
    hand -- the difference between a servo that flips your light switch
    and one that stops you using the switch yourself.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device_base import DeviceNode


class ServoNode(DeviceNode):
    TYPE = "device.servo"
    TITLE = "Servo"
    CATEGORY = "robotics"
    PARAMS = [
        {"key": "pin", "label": "Pin (as labelled on the board)",
         "type": "text", "default": "9"},
        {"key": "angle", "label": "Angle (0-180) — can be a variable",
         "type": "text", "default": "90"},
        {"key": "hold_ms", "label": "Hold after moving (ms, 0 = none)",
         "type": "number", "default": 0},
        {"key": "release", "label": "Release after moving (lets you turn it by hand)",
         "type": "bool", "default": False},
    ]

    # ESP32 LEDC
    FREQ = 50
    RES = 14            # the S3/C3 ceiling -- 16 is silently rejected
    MIN_US = 500
    MAX_US = 2500

    def _var(self):
        return f"servo_{self.pin_var('pin', '9')}"

    def _angle(self):
        return str(self.p("angle", "90")).strip()

    # ---- includes ------------------------------------------------------
    def includes(self):
        return [] if self.is_esp32() else ["#include <Servo.h>"]

    # ---- globals -------------------------------------------------------
    def globals(self):
        if not self.is_esp32():
            return [f"Servo {self._var()};"]
        v = self._var()
        maxduty = (1 << self.RES) - 1
        # ONE string, not a list of lines. codegen de-duplicates globals
        # line by line, so a multi-line block loses every bare "}" after
        # the first and the sketch will not compile. As one block the
        # de-dup still does the right thing: two servos on the same pin
        # emit these helpers once.
        return ["\n".join([
            f"// --- {v}: LEDC servo, {self.RES}-bit duty "
            f"(the S3 cannot do 16) ---",
            f"bool {v}_on = false;",
            f"void {v}_write(int deg) {{",
            f"  deg = constrain(deg, 0, 180);",
            f"  if (!{v}_on) {{",
            f"    if (!ledcAttach({self.pin('pin', '9')}, {self.FREQ}, {self.RES})) {{",
            f'      Serial.println("{v}: ledcAttach FAILED");',
            f"      return;",
            f"    }}",
            f"    {v}_on = true;",
            f"  }}",
            f"  unsigned long us = map(deg, 0, 180, {self.MIN_US}, {self.MAX_US});",
            f"  ledcWrite({self.pin('pin', '9')}, "
            f"((uint64_t)us * {maxduty}UL) / 20000UL);",
            f"}}",
            f"void {v}_release() {{",
            f"  if ({v}_on) {{ ledcDetach({self.pin('pin', '9')}); {v}_on = false; }}",
            f"}}",
        ])]

    # ---- setup ---------------------------------------------------------
    def setup(self):
        if self.is_esp32():
            # so the "ledcAttach FAILED" line above can actually reach you
            return ["Serial.begin(115200);"]
        return [f"{self._var()}.attach({self.pin('pin', '9')});",
                f"{self._var()}.write(0);"]

    # ---- loop ----------------------------------------------------------
    def loop(self):
        v = self._var()
        if self.is_esp32():
            lines = [f"{v}_write({self._angle()});"]
        else:
            lines = [f"{v}.write({self._angle()});"]

        hold = self.num("hold_ms", 0)
        if hold:
            lines.append(f"delay({hold});")

        if self.p("release", False):
            if not hold:
                # it has to actually arrive before the power is cut, or it
                # stops halfway and you blame the servo
                lines.append("delay(400);")
            if self.is_esp32():
                lines.append(f"{v}_release();")
            else:
                lines.append(f"{v}.detach();")
        return lines
