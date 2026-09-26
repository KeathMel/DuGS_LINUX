"""
switch_rules_widget.py — the rules editor for the Switch node.

Replaces the raw JSON box. One card per output port: the port's name on
top, its condition underneath, a delete button on the right. The number of
ports follows the number of cards, so there is no separate "Number of
Outputs" box to keep in sync by hand.

Nothing about how the Switch actually RUNS changed. This writes exactly the
same params the node has always read:

    rules        [{"field", "operator", "value", "output", "type"}, ...]
    output_names ["T2", "T3", ...]
    num_outputs  how many cards there are

so existing workflows keep working and the engine never had to learn
anything new.

One deliberate simplification: card position IS the output index. A rule on
card 1 goes to output 1. Hand-written configs where two rules pointed at
the same output get rewritten to one-rule-per-port the first time you edit
them here -- worth knowing, but it matches how people actually use it.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QFrame,
)
from PyQt6.QtCore import pyqtSignal, Qt

# same operators as the IF node, so the two behave identically
OPERATORS = [
    "equals", "not equals", "greater than", "less than",
    "greater or equal", "less or equal", "contains", "not contains",
    "exists", "not exists", "is empty", "is not empty", "regex match",
]

# operators that test presence -- they take no comparison value, so the
# value box is hidden rather than left there looking like it matters
NO_VALUE_OPS = {"exists", "not exists", "is empty", "is not empty"}


class SwitchRulesWidget(QWidget):
    changed = pyqtSignal()

    def __init__(self, node, accent="#7ecfff"):
        super().__init__()
        self.node = node
        self.accent = accent
        self._rows = []

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(6)

        self._cards = QVBoxLayout()
        self._cards.setSpacing(6)
        self._root.addLayout(self._cards)

        self.add_btn = QPushButton("+  Add output route")
        self.add_btn.clicked.connect(self._add_blank)
        self._root.addWidget(self.add_btn)

        self._style()
        self._load()

    # ---- look ---------------------------------------------------------
    def _style(self):
        self.add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{self.accent};"
            f"border:1px dashed {self.accent};border-radius:4px;padding:5px;"
            f"font-family:monospace;font-size:11px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,0.08);}}")

    def _field_css(self):
        return ("background:rgba(20,20,20,0.6);color:#fff;border:1px solid #555;"
                "border-radius:3px;padding:3px;font-family:monospace;font-size:11px;")

    # ---- reading / writing the node's params --------------------------
    def _load(self):
        rules = self.node.params.get("rules")
        if isinstance(rules, dict):
            rules = [rules]
        if not isinstance(rules, list):
            rules = []
        names = self.node.params.get("output_names")
        if not isinstance(names, list):
            names = []

        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            self._add_card(rule, names[i] if i < len(names) else "")
        if not self._rows:
            self._add_card({}, "")
        self._renumber()

    def _write(self):
        rules, names = [], []
        for i, row in enumerate(self._rows):
            op = row["op"].currentText()
            rules.append({
                "field": row["field"].text().strip(),
                "operator": op,
                # a presence test has no value to compare against
                "value": "" if op in NO_VALUE_OPS else row["value"].text(),
                "output": i,          # the card's position IS the port
                "type": "auto",
            })
            names.append(row["name"].text().strip())
        self.node.params["rules"] = rules
        self.node.params["output_names"] = names
        # kept in step automatically -- this is what the canvas reads to
        # know how many output dots to draw
        self.node.params["num_outputs"] = max(1, len(rules))
        self.changed.emit()

    # ---- cards --------------------------------------------------------
    def _add_blank(self):
        self._add_card({}, "")
        self._renumber()
        self._write()

    def _add_card(self, rule, name):
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:rgba(255,255,255,0.04);"
            "border:1px solid rgba(255,255,255,0.10);border-radius:5px;}")
        box = QVBoxLayout(card)
        box.setContentsMargins(7, 6, 7, 7)
        box.setSpacing(4)

        # --- top line: which port this is, its name, and remove ---
        top = QHBoxLayout()
        top.setSpacing(5)
        port_lbl = QLabel("")
        port_lbl.setStyleSheet(
            f"color:{self.accent};font-family:monospace;font-size:10px;"
            "font-weight:bold;border:none;")
        port_lbl.setFixedWidth(46)
        top.addWidget(port_lbl)

        name_edit = QLineEdit(str(name or ""))
        name_edit.setStyleSheet(self._field_css())
        name_edit.editingFinished.connect(self._write)
        top.addWidget(name_edit, 1)

        del_btn = QPushButton("\u2715")
        del_btn.setFixedSize(20, 20)
        del_btn.setToolTip("Remove this output route")
        del_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#ff6b6b;"
            "border:1px solid #ff6b6b;border-radius:3px;font-size:10px;}"
            "QPushButton:hover{background:rgba(255,107,107,0.18);}")
        top.addWidget(del_btn)
        box.addLayout(top)

        # --- condition line: IF <field> <operator> <value> ---
        cond = QHBoxLayout()
        cond.setSpacing(5)
        if_lbl = QLabel("IF")
        if_lbl.setStyleSheet("color:#888;font-family:monospace;font-size:10px;border:none;")
        if_lbl.setFixedWidth(20)
        cond.addWidget(if_lbl)

        field_edit = QLineEdit(str(rule.get("field", "") or ""))
        field_edit.setPlaceholderText("{{ $json.field }}")
        field_edit.setStyleSheet(self._field_css())
        field_edit.editingFinished.connect(self._write)
        cond.addWidget(field_edit, 2)

        op_box = QComboBox()
        op_box.addItems(OPERATORS)
        op = str(rule.get("operator", "equals") or "equals")
        if op in OPERATORS:
            op_box.setCurrentText(op)
        op_box.setStyleSheet(self._field_css())
        cond.addWidget(op_box, 1)

        value_edit = QLineEdit(str(rule.get("value", "") or ""))
        value_edit.setPlaceholderText("value")
        value_edit.setStyleSheet(self._field_css())
        value_edit.editingFinished.connect(self._write)
        cond.addWidget(value_edit, 1)
        box.addLayout(cond)

        row = {"card": card, "port": port_lbl, "name": name_edit,
               "field": field_edit, "op": op_box, "value": value_edit}
        self._rows.append(row)
        self._cards.addWidget(card)

        def on_op_change():
            # hide the value box for presence tests, where it means nothing
            value_edit.setVisible(op_box.currentText() not in NO_VALUE_OPS)
            self._write()
        op_box.currentTextChanged.connect(on_op_change)
        value_edit.setVisible(op not in NO_VALUE_OPS)

        del_btn.clicked.connect(lambda: self._remove(row))

    def _remove(self, row):
        # never leave the node with zero routes -- a Switch with no rules
        # silently drops every item, which looks like the node is broken
        if len(self._rows) <= 1:
            row["field"].clear(); row["value"].clear(); row["name"].clear()
            self._write()
            return
        self._rows.remove(row)
        row["card"].setParent(None)
        row["card"].deleteLater()
        self._renumber()
        self._write()

    def _renumber(self):
        for i, row in enumerate(self._rows):
            row["port"].setText(f"Port {i}")
            row["name"].setPlaceholderText(f"Output {i}")


class ConditionRowsWidget(QWidget):
    """The Filter node's conditions, as cards.

    Same card as the Switch editor, minus the port name and port number --
    Filter has no outputs to name, it just keeps or drops. Writes the plain
    [{"field", "operator", "value"}] list the node already reads.
    """
    changed = pyqtSignal()

    def __init__(self, node, accent="#7ecfff", key="conditions"):
        super().__init__()
        self.node, self.accent, self.key = node, accent, key
        self._rows = []
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(6)
        self._cards = QVBoxLayout(); self._cards.setSpacing(6)
        self._root.addLayout(self._cards)
        self.add_btn = QPushButton("+  Add condition")
        self.add_btn.clicked.connect(self._add_blank)
        self.add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{accent};"
            f"border:1px dashed {accent};border-radius:4px;padding:5px;"
            f"font-family:monospace;font-size:11px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,0.08);}}")
        self._root.addWidget(self.add_btn)
        self._load()

    def _css(self):
        return ("background:rgba(20,20,20,0.6);color:#fff;border:1px solid #555;"
                "border-radius:3px;padding:3px;font-family:monospace;font-size:11px;")

    def _load(self):
        rows = self.node.params.get(self.key)
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            rows = []
        for r in rows:
            if isinstance(r, dict):
                self._add_card(r)
        if not self._rows:
            self._add_card({})

    def _write(self):
        out = []
        for row in self._rows:
            op = row["op"].currentText()
            out.append({
                "field": row["field"].text().strip(),
                "operator": op,
                "value": "" if op in NO_VALUE_OPS else row["value"].text(),
            })
        self.node.params[self.key] = out
        self.changed.emit()

    def _add_blank(self):
        self._add_card({}); self._write()

    def _add_card(self, rule):
        card = QFrame()
        card.setStyleSheet("QFrame{background:rgba(255,255,255,0.04);"
                           "border:1px solid rgba(255,255,255,0.10);border-radius:5px;}")
        box = QHBoxLayout(card)
        box.setContentsMargins(7, 6, 7, 6); box.setSpacing(5)

        if_lbl = QLabel("IF")
        if_lbl.setStyleSheet("color:#888;font-family:monospace;font-size:10px;border:none;")
        if_lbl.setFixedWidth(20)
        box.addWidget(if_lbl)

        field = QLineEdit(str(rule.get("field", "") or ""))
        field.setPlaceholderText("{{ $json.field }}")
        field.setStyleSheet(self._css())
        field.editingFinished.connect(self._write)
        box.addWidget(field, 2)

        op_box = QComboBox(); op_box.addItems(OPERATORS)
        op = str(rule.get("operator", "equals") or "equals")
        if op in OPERATORS:
            op_box.setCurrentText(op)
        op_box.setStyleSheet(self._css())
        box.addWidget(op_box, 1)

        value = QLineEdit(str(rule.get("value", "") or ""))
        value.setPlaceholderText("value")
        value.setStyleSheet(self._css())
        value.editingFinished.connect(self._write)
        box.addWidget(value, 1)

        rm = QPushButton("\u2715"); rm.setFixedSize(20, 20)
        rm.setStyleSheet("QPushButton{background:transparent;color:#ff6b6b;"
                         "border:1px solid #ff6b6b;border-radius:3px;font-size:10px;}"
                         "QPushButton:hover{background:rgba(255,107,107,0.18);}")
        box.addWidget(rm)

        row = {"card": card, "field": field, "op": op_box, "value": value}
        self._rows.append(row); self._cards.addWidget(card)

        def on_op():
            value.setVisible(op_box.currentText() not in NO_VALUE_OPS)
            self._write()
        op_box.currentTextChanged.connect(on_op)
        value.setVisible(op not in NO_VALUE_OPS)
        rm.clicked.connect(lambda: self._remove(row))

    def _remove(self, row):
        if len(self._rows) <= 1:
            row["field"].clear(); row["value"].clear(); self._write(); return
        self._rows.remove(row)
        row["card"].setParent(None); row["card"].deleteLater()
        self._write()


class KeyValueRowsWidget(QWidget):
    """Name/value pairs as simple rows -- Set's fields, HTTP headers.

    as_dict=True stores {"name": "value"}; otherwise the
    [{"name":..., "value":...}] list that Set already reads.
    """
    changed = pyqtSignal()

    def __init__(self, node, accent="#7ecfff", key="assignments",
                 as_dict=False, name_hint="name", value_hint="value"):
        super().__init__()
        self.node, self.accent, self.key = node, accent, key
        self.as_dict, self.name_hint, self.value_hint = as_dict, name_hint, value_hint
        self._rows = []
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0); self._root.setSpacing(4)
        self._cards = QVBoxLayout(); self._cards.setSpacing(4)
        self._root.addLayout(self._cards)
        self.add_btn = QPushButton("+  Add")
        self.add_btn.clicked.connect(lambda: (self._add_row("", ""), self._write()))
        self.add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{accent};"
            f"border:1px dashed {accent};border-radius:4px;padding:4px;"
            f"font-family:monospace;font-size:11px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,0.08);}}")
        self._root.addWidget(self.add_btn)
        self._load()

    def _css(self):
        return ("background:rgba(20,20,20,0.6);color:#fff;border:1px solid #555;"
                "border-radius:3px;padding:3px;font-family:monospace;font-size:11px;")

    def _load(self):
        cur = self.node.params.get(self.key)
        if self.as_dict and isinstance(cur, dict):
            for k, v in cur.items():
                self._add_row(k, v)
        elif isinstance(cur, list):
            for e in cur:
                if isinstance(e, dict):
                    self._add_row(e.get("name", ""), e.get("value", ""))
        if not self._rows:
            self._add_row("", "")

    def _write(self):
        if self.as_dict:
            out = {}
            for r in self._rows:
                k = r["name"].text().strip()
                if k:
                    out[k] = r["value"].text()
        else:
            out = [{"name": r["name"].text().strip(), "value": r["value"].text()}
                   for r in self._rows if r["name"].text().strip()]
        self.node.params[self.key] = out
        self.changed.emit()

    def _add_row(self, name, value):
        line = QWidget()
        box = QHBoxLayout(line)
        box.setContentsMargins(0, 0, 0, 0); box.setSpacing(4)
        n = QLineEdit(str(name or "")); n.setPlaceholderText(self.name_hint)
        n.setStyleSheet(self._css()); n.editingFinished.connect(self._write)
        v = QLineEdit(str(value if value is not None else ""))
        v.setPlaceholderText(self.value_hint)
        v.setStyleSheet(self._css()); v.editingFinished.connect(self._write)
        rm = QPushButton("\u2715"); rm.setFixedSize(20, 20)
        rm.setStyleSheet("QPushButton{background:transparent;color:#ff6b6b;"
                         "border:1px solid #ff6b6b;border-radius:3px;font-size:10px;}"
                         "QPushButton:hover{background:rgba(255,107,107,0.18);}")
        box.addWidget(n, 1); box.addWidget(v, 2); box.addWidget(rm)
        row = {"line": line, "name": n, "value": v}
        self._rows.append(row); self._cards.addWidget(line)
        rm.clicked.connect(lambda: self._remove(row))

    def _remove(self, row):
        if len(self._rows) <= 1:
            row["name"].clear(); row["value"].clear(); self._write(); return
        self._rows.remove(row)
        row["line"].setParent(None); row["line"].deleteLater()
        self._write()
