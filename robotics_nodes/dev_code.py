"""
CodeNode — raw C++, for the one line no node covers.

    Every visual tool eventually meets something its blocks cannot say.
    Without a way out you either wait for someone to build the node or
    you abandon the graph and hand-write the sketch. This is the way
    out: whatever you type goes into the generated code verbatim.

    The obvious use is starting a Countdown, which otherwise has no
    trigger:

        Button --hold--> Code:  cd1_start();

    It can also reach anything another node declared, because they all
    end up in the same file:

        cd1_end = millis() + 60000;     // five more minutes
        servo_SERVO_1_release();
        Serial.println(setH);

    Lines go in exactly as typed, semicolons and all. If it does not
    compile, the error will point at the line you wrote -- the generated
    sketch is on disk and readable, which is the point of generating a
    file instead of hiding it.

    "Where" decides whether it lands in setup() or in loop().
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device_base import DeviceNode


class CodeNode(DeviceNode):
    TYPE = "device.code"
    TITLE = "Code"
    CATEGORY = "robotics"
    PARAMS = [
        {"key": "code", "label": "C++ lines (one per line, verbatim)",
         "type": "text", "default": "// your code here"},
        {"key": "where", "label": "Put it in", "type": "select",
         "default": "loop", "options": ["loop", "setup"]},
        {"key": "includes", "label": "Extra #include lines (optional, one per line)",
         "type": "text", "default": ""},
        {"key": "globals", "label": "Global declarations (optional, one per line)",
         "type": "text", "default": ""},
    ]

    def _lines(self, key):
        raw = str(self.p(key, "") or "")
        return [l.rstrip() for l in raw.splitlines() if l.strip()]

    def includes(self):
        return self._lines("includes")

    def globals(self):
        got = self._lines("globals")
        # as one block, so a multi-line helper does not lose its closing
        # braces to the line-by-line de-duplication in codegen
        return ["\n".join(got)] if got else []

    def setup(self):
        return self._lines("code") if self.p("where", "loop") == "setup" else []

    def loop(self):
        return self._lines("code") if self.p("where", "loop") == "loop" else []
