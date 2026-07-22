"""
node_popup.py — the floating node popup (Tab on a hovered node, or double-click).

A three-pane view of one node: INPUT on the left, PARAMETERS in the middle,
OUTPUT on the right — the same shape n8n uses. You can drag a field from the
input tree straight into a parameter box to insert a {{ }} reference, rename the
node by double-clicking its title, and see a live preview of what each
expression currently resolves to (green = it resolved from the last run, grey =
no value yet).

This is a mixin on the Editor, like editor_settings.py, so `self` here is the
Editor instance and it can reach self.canvas, self.meta_by_type, and so on.
Kept in its own file because it is by far the biggest single piece of the
editor UI and it changes independently of everything else.
"""
import json

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QLabel, QCheckBox, QTreeWidgetItem, QDialog, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QPlainTextEdit, QComboBox, QPushButton,
    QScrollArea, QWidget,
)

from theme import ACCENT
from node_base import resolve_expr
from storage import list_credentials
from editor_widgets import (DragJsonTree, DropLineEdit, DropTextEdit,
                            ExpandableText, HelpLabel)


class NodePopupMixin:
    def open_node_popup(self, node):
        """Tab on a hovered node: floating popup to quick-view/edit it,
        while the left settings bar stays as-is."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                                     QLineEdit, QPlainTextEdit, QComboBox, QLabel,
                                     QPushButton, QScrollArea, QWidget as _QW)
        meta = self.meta_by_type.get(node.type_id, {})
        params_spec = meta.get("params", [])

        # robotics nodes use red where a normal node uses the blue accent
        NACC = "#ff6b6b" if str(node.type_id).startswith("device.") else ACCENT

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{node.name}  ({node.type_id})")
        dlg.setMinimumWidth(820); dlg.setMinimumHeight(420)
        QShortcut(QKeySequence("Escape"), dlg, dlg.accept)
        dlg.setStyleSheet("QDialog{background:#141414;}"
                          "QLabel{color:#ccc;font-family:monospace;}"
                          "QLineEdit,QPlainTextEdit,QComboBox{background:#1e1e1e;color:#fff;"
                          "border:1px solid #555;border-radius:3px;padding:4px;font-family:monospace;font-size:12px;}")
        outer = QVBoxLayout(dlg)

        title = QLabel(node.name)
        title.setStyleSheet(f"color:{NACC};font-family:monospace;font-size:16px;font-weight:bold;")
        title.setToolTip("double-click to rename")
        title.setCursor(Qt.CursorShape.IBeamCursor)
        outer.addWidget(title)
        sub = QLabel(node.type_id); sub.setStyleSheet("color:#666;font-family:monospace;font-size:10px;")
        outer.addWidget(sub)

        # double-click the title to rename inline (replaces the old name field)
        def _start_rename(_e):
            editor_line = QLineEdit(node.name)
            editor_line.setStyleSheet(f"color:{NACC};font-family:monospace;font-size:16px;font-weight:bold;"
                                      "background:#1e1e1e;border:1px solid #555;border-radius:3px;padding:2px;")
            # swap the label for the editor in the layout
            outer.replaceWidget(title, editor_line)
            title.hide(); editor_line.setFocus(); editor_line.selectAll()
            def _commit():
                new = editor_line.text().strip()
                if new and "{{" not in new and "$(" not in new and new != node.name:
                    node.name = new; title.setText(new)
                    dlg.setWindowTitle(f"{node.name}  ({node.type_id})")
                    self.mark_changed()
                    if self.canvas.selected is node:
                        self.show_node_settings(node)
                outer.replaceWidget(editor_line, title)
                editor_line.deleteLater(); title.show()
            editor_line.editingFinished.connect(_commit)
        title.mouseDoubleClickEvent = _start_rename

        # three columns: INPUT | PARAMS | OUTPUT  (n8n-style)
        cols = QHBoxLayout(); cols.setSpacing(10)

        def col_label(t):
            l = QLabel(t); l.setStyleSheet("color:#888;font-family:monospace;font-size:11px;letter-spacing:1px;")
            return l

        # ---- LEFT: input JSON (from upstream nodes' last output) ----
        left_box = QVBoxLayout(); left_box.setSpacing(4)
        left_box.addWidget(col_label("INPUT  (drag a field into a box →)"))
        ups = self._upstream_nodes(node)
        input_data = {}
        for up in ups:
            vals = self._last_results.get(up)
            if vals:
                input_data[up] = vals
        in_tree = DragJsonTree()
        if input_data:
            for src_node, items_in in input_data.items():
                top = QTreeWidgetItem([f"$('{src_node}')", f"{len(items_in)} item(s)"])
                top.setData(0, Qt.ItemDataRole.UserRole, f"$('{src_node}').item.json")
                in_tree.addTopLevelItem(top)
                if items_in:
                    self._json_to_tree(top, items_in[0], f"$('{src_node}').item.json", src_node)
                top.setExpanded(True)
        else:
            placeholder = QTreeWidgetItem(
                ["(run to see input)" if ups else "(no upstream nodes)", ""])
            in_tree.addTopLevelItem(placeholder)
        left_box.addWidget(in_tree, 1)
        cols.addLayout(left_box, 2)

        # ---- MIDDLE: params ----
        mid_box = QVBoxLayout(); mid_box.setSpacing(4)
        mid_box.addWidget(col_label("PARAMETERS"))
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        host = _QW(); form = QFormLayout(host)

        # (no name field here — double-click the title above to rename)

        # build the same cross-node context the engine uses, from the last run,
        # so we can show what each {{ }} expression currently resolves to.
        from node_base import resolve_expr, EXPR_RE
        preview_ctx = {}
        for up in self._upstream_nodes(node):
            vals = self._last_results.get(up)
            if vals:
                # _last_results holds flat json dicts; the resolver expects
                # items shaped {"json": {...}}, so wrap them.
                preview_ctx[up] = [
                    v if (isinstance(v, dict) and "json" in v) else {"json": v}
                    for v in vals
                ]
        # the "current item" for $json previews = first item of the first
        # upstream node's output (that's what $json refers to inside this node)
        cur_item = {}
        for up_vals in preview_ctx.values():
            if up_vals:
                first = up_vals[0]
                cur_item = first.get("json", first) if isinstance(first, dict) else first
                break

        def make_preview(get_text):
            """A label that shows the resolved value of any {{ }} in the text:
            green if it resolves to something, grey if not."""
            lbl = QLabel("")
            lbl.setWordWrap(True)
            def refresh():
                txt = get_text()
                if not txt or "{{" not in txt:
                    lbl.setText(""); return
                try:
                    val = resolve_expr(txt, cur_item, preview_ctx)
                except Exception:
                    val = None
                # did anything actually resolve? (value present and not the raw expr)
                resolved = val is not None and str(val).strip() != "" and "{{" not in str(val)
                if resolved:
                    shown = val if isinstance(val, str) else json.dumps(val)
                    if len(shown) > 200: shown = shown[:200] + "…"
                    lbl.setStyleSheet("color:#7CFC9B;font-family:monospace;font-size:10px;")
                    lbl.setText("= " + shown)
                else:
                    lbl.setStyleSheet("color:#666;font-family:monospace;font-size:10px;")
                    lbl.setText("= (no value — run the workflow first)" if preview_ctx
                                else "= (no upstream data yet)")
            return lbl, refresh

        # one editor per param (text/number/multiline/select/bool)
        for p in params_spec:
            key = p["key"]; ptype = p.get("type", "text")
            cur = node.params.get(key, p.get("default"))
            preview = None; refresh_preview = None
            if ptype == "multiline":
                w = ExpandableText(str(cur) if cur is not None else "",
                                   title=p.get("label", key).upper())
                preview, refresh_preview = make_preview(lambda ww=w: ww.toPlainText())
                def mk(k, ww, rp):
                    def s(): node.params[k] = ww.toPlainText(); self.mark_changed(push_undo=False); rp()
                    return s
                cb = mk(key, w, refresh_preview); w.textChanged.connect(cb); w._on_change = cb
            elif ptype in ("tabel", "memory"):
                w = QComboBox()
                if ptype == "tabel":
                    from storage import list_tabels
                    opts = [""] + list_tabels()
                else:
                    from storage import list_memory_banks
                    opts = [""] + list_memory_banks()
                w.addItems(opts)
                if cur is not None and str(cur) in opts:
                    w.setCurrentText(str(cur))
                def mkmemsel(k, ww):
                    def s(): node.params[k] = ww.currentText() or None; self.mark_changed()
                    return s
                w.currentTextChanged.connect(mkmemsel(key, w))
            elif ptype == "select":
                w = QComboBox()
                opts = [str(o) for o in p.get("options", [])]
                if p.get("options_from") == "credentials":
                    from storage import list_credentials
                    opts = [""] + list_credentials()
                w.addItems(opts)
                if cur is not None and str(cur) in opts: w.setCurrentText(str(cur))
                def mks(k, ww):
                    def s(): node.params[k] = ww.currentText(); self.mark_changed()
                    return s
                w.currentTextChanged.connect(mks(key, w))
            elif ptype == "bool":
                from PyQt6.QtWidgets import QCheckBox
                w = QCheckBox(); w.setChecked(bool(cur))
                def mkb(k, ww):
                    def s(_=None): node.params[k] = ww.isChecked(); self.mark_changed()
                    return s
                w.stateChanged.connect(mkb(key, w))
            else:
                w = DropLineEdit(str(cur) if cur is not None else "")
                preview, refresh_preview = make_preview(lambda ww=w: ww.text())
                def mkt(k, ww, rp, isnum=(ptype == "number")):
                    def s():
                        v = ww.text()
                        if isnum:
                            try: v = int(v)
                            except ValueError:
                                try: v = float(v)
                                except ValueError: pass
                        node.params[k] = v; self.mark_changed(push_undo=False); rp()
                    return s
                cb = mkt(key, w, refresh_preview); w.editingFinished.connect(cb); w._on_change = cb
                # also live-update the preview as you type/drop, not just on commit
                w.textChanged.connect(refresh_preview)
            # short label with the explanation on hover, so rows stay compact
            row_label = p.get("label", key)
            help_text = p.get("desc", "")
            ex = p.get("example")
            res = p.get("result")
            if ex:
                help_text = (help_text + "\n\n" if help_text else "") + f"example: {ex}"
            if res:
                help_text = (help_text + "\n" if help_text else "") + f"result: {res}"
            form.addRow(HelpLabel(row_label, help_text), w)
            if preview is not None:
                form.addRow("", preview)
                refresh_preview()   # show initial state

        scroll.setWidget(host); mid_box.addWidget(scroll, 1)
        cols.addLayout(mid_box, 3)

        # ---- RIGHT: this node's own last output ----
        right_box = QVBoxLayout(); right_box.setSpacing(4)
        right_box.addWidget(col_label("OUTPUT"))
        own = self._last_results.get(node.name)
        out_view = QPlainTextEdit(); out_view.setReadOnly(True)
        out_view.setStyleSheet("color:#9fb;font-size:10px;")
        if own:
            out_view.setPlainText(json.dumps(own[:3], indent=2))
        else:
            out_view.setPlainText("(run the workflow to see output)")
        right_box.addWidget(out_view, 1)
        cols.addLayout(right_box, 2)

        outer.addLayout(cols, 1)

        close = QPushButton("Close"); close.clicked.connect(dlg.accept)
        outer.addWidget(close)
        dlg.exec()
        # after closing, refresh the left panel + json in case things changed
        if self.canvas.selected is node:
            self.show_node_settings(node)
        self.refresh_json()

