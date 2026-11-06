"""
VarNode — a number the sketch remembers between passes.

    The old one always declared `int x = 0`, which meant a setting could
    never start anywhere but zero: no alarm defaulting to 7:30, no
    counter starting at 1. It also only ever held an int, so a
    millisecond stamp (which needs 32 bits unsigned) or a yes/no flag
    had to be faked.

    Now it has a type and a starting value. The declaration is emitted
    once per variable name; the node's operation runs wherever it sits
    in the graph.

    Use the same name in several Var nodes to change one variable from
    several places -- but give the type and initial value only once, or
    the sketch gets two conflicting declarations and will not compile.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device_base import DeviceNode


class VarNode(DeviceNode):
    TYPE = "device.var"
    TITLE = "Variable"
    CATEGORY = "robotics"
    PARAMS = [
        {"key": "name", "label": "Variable name", "type": "text", "default": "count"},
        {"key": "type", "label": "Type", "type": "select", "default": "int",
         "options": ["int", "long", "unsigned long", "float", "bool"]},
        {"key": "initial", "label": "Starting value", "type": "text", "default": "0"},
        {"key": "declare", "label": "Declare it here (off if another Var node does)",
         "type": "bool", "default": True},
        {"key": "op", "label": "Operation", "type": "select", "default": "set",
         "options": ["set", "add", "subtract", "multiply", "divide", "nothing"]},
        {"key": "value", "label": "Value — can be another variable",
         "type": "text", "default": "0"},
        {"key": "min", "label": "Keep at or above (optional)", "type": "text", "default": ""},
        {"key": "max", "label": "Keep at or below (optional)", "type": "text", "default": ""},
        {"key": "wrap", "label": "Wrap round instead of stopping at the limits",
         "type": "bool", "default": False},
    ]

    OPS = {"set": "=", "add": "+=", "subtract": "-=",
           "multiply": "*=", "divide": "/="}

    def _name(self):
        raw = str(self.p("name", "count")).strip()
        return "".join(c if (c.isalnum() or c == "_") else "_" for c in raw) or "count"

    def globals(self):
        if not self.p("declare", True):
            return []
        init = str(self.p("initial", "0")).strip() or "0"
        return [f"{self.p('type', 'int')} {self._name()} = {init};"]

    def loop(self):
        n = self._name()
        op = self.p("op", "set")
        lines = []
        if op != "nothing":
            v = str(self.p("value", "0")).strip() or "0"
            lines.append(f"{n} {self.OPS.get(op, '=')} {v};")

        lo = str(self.p("min", "")).strip()
        hi = str(self.p("max", "")).strip()
        if lo or hi:
            if self.p("wrap", False) and lo and hi:
                # counting hours or minutes: 23 then 1 more is 0, not 23
                lines.append(f"if ({n} > {hi}) {n} = {lo};")
                lines.append(f"if ({n} < {lo}) {n} = {hi};")
            else:
                if lo:
                    lines.append(f"if ({n} < {lo}) {n} = {lo};")
                if hi:
                    lines.append(f"if ({n} > {hi}) {n} = {hi};")
        return lines
