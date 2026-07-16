"""
IF node: splits items into two outputs based on a condition.
  output 0 = items where condition is TRUE
  output 1 = items where condition is FALSE

params:
  field    : which json field to test
  operator : equals | not_equals | greater | less | contains | exists | empty
  value    : value to compare against
"""
from node_base import Node


def _num(v):
    """Try to coerce to a number for numeric comparisons; else return as-is."""
    try:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v
        s = str(v).strip()
        return float(s) if "." in s else int(s)
    except Exception:
        return v


class IfNode(Node):
    TYPE = "logic.if"
    TITLE = "IF"
    CATEGORY = "logic"
    INPUTS = 1
    OUTPUTS = 2   # [true, false]
    PARAMS = [
        {"key": "field", "label": "Field", "type": "text", "default": ""},
        {"key": "operator", "label": "Operator", "type": "select", "default": "exists",
         "options": ["equals", "not_equals", "greater", "less", "contains", "exists", "empty"]},
        {"key": "value", "label": "Value", "type": "text", "default": ""},
    ]

    def run(self, items):
        field = self.params.get("field")
        op = self.params.get("operator", "exists")
        value = self.params.get("value")

        true_items, false_items = [], []
        for item in items:
            j = item.get("json", {})
            actual = j.get(field)

            if op == "equals":
                passed = str(actual) == str(value)
            elif op == "not_equals":
                passed = str(actual) != str(value)
            elif op == "greater":
                a, b = _num(actual), _num(value)
                passed = (actual is not None) and a > b
            elif op == "less":
                a, b = _num(actual), _num(value)
                passed = (actual is not None) and a < b
            elif op == "contains":
                passed = value is not None and str(value) in str(actual)
            elif op == "exists":
                passed = field in j and actual is not None
            elif op == "empty":
                passed = (actual is None) or (actual == "") or (actual == [])
            else:
                passed = False

            (true_items if passed else false_items).append(item)

        return [true_items, false_items]
