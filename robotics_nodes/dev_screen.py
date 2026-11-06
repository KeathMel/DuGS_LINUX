"""
ScreenNode — write text on the display.

    Two completely different screens hide behind one node:

    arduino / esp32   a 128x64 SH1106 OLED over I2C, drawn with U8g2 into
                      a buffer that you push with sendBuffer().

    t-display-s3      the 170x320 ST7789 soldered to the LilyGO board,
                      driven over an 8-bit parallel bus with Arduino_GFX.
                      There is no buffer; you draw straight at it.

    The one that wastes an evening on the T-Display-S3: GPIO15 is a power
    enable for the panel rail. Leave it low and the board boots fine,
    Serial works, the sketch runs -- and the screen stays black, which
    looks exactly like a dead display. It is driven HIGH in setup() here.

    Library for the S3: "GFX Library for Arduino" by moononournation.
      git clone --depth 1 https://github.com/moononournation/Arduino_GFX.git \\
          ~/Arduino/libraries/Arduino_GFX
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device_base import DeviceNode


class ScreenNode(DeviceNode):
    TYPE = "device.screen"
    TITLE = "Screen"
    CATEGORY = "robotics"
    PARAMS = [
        {"key": "text", "label": "Text to show", "type": "text", "default": "HELLO"},
        {"key": "x", "label": "X position", "type": "number", "default": 20},
        {"key": "y", "label": "Y position", "type": "number", "default": 36},
        {"key": "size", "label": "Text size", "type": "select",
         "default": "medium", "options": ["small", "medium", "big"]},
        {"key": "color", "label": "Colour (T-Display only)", "type": "select",
         "default": "white",
         "options": ["white", "yellow", "green", "cyan", "red", "grey"]},
        {"key": "clear", "label": "Clear behind the text first",
         "type": "bool", "default": True},
        {"key": "redraw_ms", "label": "Redraw at most every (ms, 0 = every pass)",
         "type": "number", "default": 250},
        # The panel's size. The generated code does not need it -- the
        # driver knows its own panel -- but the simulator draws the
        # screen at exactly this, so you can shove the x/y around and
        # watch your layout move instead of reflashing to find out.
        {"key": "width", "label": "Panel width in pixels (for the simulator)",
         "type": "number", "default": 320},
        {"key": "height", "label": "Panel height in pixels (for the simulator)",
         "type": "number", "default": 170},
        {"key": "show_var", "label": "Show a variable instead (name, optional)",
         "type": "text", "default": ""},
    ]

    FONTS = {
        "small":  "u8g2_font_5x8_tr",
        "medium": "u8g2_font_6x12_tr",
        "big":    "u8g2_font_logisoso28_tn",
    }
    SIZES = {"small": 2, "medium": 4, "big": 6}
    COLORS = {"white": "0xFFFF", "yellow": "0xFFE0", "green": "0x07E0",
              "cyan": "0x07FF", "red": "0xF800", "grey": "0x7BEF"}

    # ---- includes ------------------------------------------------------
    def includes(self):
        if self.is_tdisplay():
            return ["#include <Arduino_GFX_Library.h>"]
        return ["#include <U8g2lib.h>", "#include <Wire.h>"]

    # ---- globals -------------------------------------------------------
    def globals(self):
        if not self.is_tdisplay():
            return ["U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);"]
        # ONE string, for the same de-dup reason as the servo node.
        return ["\n".join([
            "// --- T-Display-S3: ST7789 170x320 on an 8-bit parallel bus ---",
            "#define TDISP_POWER_ON 15   // panel rail enable -- without this,",
            "#define TDISP_BL       38   // black screen on a board that works",
            "Arduino_DataBus *tdisp_bus = new Arduino_ESP32LCD8(",
            "    7 /*DC*/, 6 /*CS*/, 8 /*WR*/, 9 /*RD*/,",
            "    39, 40, 41, 42, 45, 46, 47, 48 /*D0-D7*/);",
            "Arduino_GFX *gfx = new Arduino_ST7789(",
            "    tdisp_bus, 5 /*RST*/, 1 /*rotation*/, true /*IPS*/,",
            "    170, 320, 35, 0, 35, 0);",
        ])]

    # ---- setup ---------------------------------------------------------
    def setup(self):
        if not self.is_tdisplay():
            return ["u8g2.begin();"]
        return [
            "pinMode(TDISP_POWER_ON, OUTPUT);",
            "digitalWrite(TDISP_POWER_ON, HIGH);",
            "gfx->begin();",
            "gfx->fillScreen(0x0000);",
            "pinMode(TDISP_BL, OUTPUT);",
            "digitalWrite(TDISP_BL, HIGH);",
        ]

    # ---- loop ----------------------------------------------------------
    def loop(self):
        return self._loop_tdisplay() if self.is_tdisplay() else self._loop_u8g2()

    def _loop_tdisplay(self):
        """Drawn straight at the panel, so two things matter that do not on
        the buffered OLED.

        The loop runs thousands of times a second. Redrawing that often
        saturates the parallel bus and the screen tears visibly, so the
        draw is throttled -- a clock does not need more than four frames
        a second.

        And "clear" wipes only the band behind this text, not the whole
        screen: fillScreen() between two draws is what you see as a
        flicker, and it would also erase every other Screen node's text.
        """
        size = self.SIZES.get(self.p("size", "medium"), 4)
        x, y = self.num("x", 20), self.num("y", 36)
        every = self.num("redraw_ms", 250)
        tag = "".join(c if (c.isalnum() or c == "_") else "_" for c in self.name)

        body = []
        if self.p("clear", True):
            body.append(f"gfx->fillRect(0, {y - 2}, 320, {size * 8 + 6}, 0x0000);")
        body.append(f"gfx->setTextColor({self.COLORS.get(self.p('color','white'), '0xFFFF')});")
        body.append(f"gfx->setTextSize({size});")
        body.append(f"gfx->setCursor({x}, {y});")
        var = str(self.p("show_var", "")).strip()
        if var:
            # print() takes an int, a float, a char* or a String, so a
            # countdown's clock string and a plain counter both just work
            body.append(f"gfx->print({var});")
        else:
            txt = str(self.p("text", "")).replace('"', '\\"')
            body.append(f'gfx->print("{txt}");')

        if not every:
            return body
        out = [f"static unsigned long _draw_{tag} = 0;",
               f"if (millis() - _draw_{tag} >= {every}) {{",
               f"  _draw_{tag} = millis();"]
        out += [f"  {l}" for l in body]
        out.append("}")
        return out

    def _loop_u8g2(self):
        lines = []
        if self.p("clear", True):
            lines.append("u8g2.clearBuffer();")
        font = self.FONTS.get(self.p("size", "medium"), self.FONTS["medium"])
        lines.append(f"u8g2.setFont({font});")
        x, y = self.num("x", 20), self.num("y", 36)
        var = str(self.p("show_var", "")).strip()
        if var:
            lines.append("{ char _b[16]; sprintf(_b, \"%d\", " + var + ");")
            lines.append(f"  u8g2.drawStr({x}, {y}, _b); }}")
        else:
            txt = str(self.p("text", "")).replace('"', '\\"')
            lines.append(f'u8g2.drawStr({x}, {y}, "{txt}");')
        lines.append("u8g2.sendBuffer();")
        return lines
