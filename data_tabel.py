"""
Tabel node: read from / write to a dugs Tabel (built-in spreadsheet).

params:
  tabel     : name of the Tabel to use (dropdown of existing Tabels)
  operation : read | append | update
      read   -> outputs one item per row (ignores input)
      append -> adds each incoming item's json as a new row
      update -> updates rows matching an "id" in the incoming json
"""
import os
import sys
from node_base import Node

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tabel_store


class TabelNode(Node):
    TYPE = "data.tabel"
    TITLE = "Tabel"
    CATEGORY = "data"
    INPUTS = 1
    OUTPUTS = 1
    PARAMS = [
        {"key": "tabel", "label": "Tabel", "type": "tabel", "default": ""},
        {"key": "operation", "label": "Operation", "type": "select", "default": "read",
         "options": ["read", "append", "update"]},
    ]

    def run(self, items):
        name = self.params.get("tabel")
        op = (self.params.get("operation") or "read").lower()
        if not name:
            raise ValueError("Tabel node needs a 'tabel' name")
        try:
            data = tabel_store.load_tabel(name)
        except FileNotFoundError:
            raise ValueError(f"Tabel '{name}' does not exist")

        cols = data.get("columns", [])
        rows = data.get("rows", [])

        if op == "read":
            return [{"json": dict(r)} for r in rows]

        if op == "append":
            added = []
            for it in (items or []):
                j = it.get("json", {})
                row = {c: j.get(c) for c in cols}
                rows.append(row)
                added.append(row)
            data["rows"] = rows
            tabel_store.save_tabel(name, data)
            data = tabel_store.load_tabel(name)
            return [{"json": dict(r)} for r in data["rows"][-len(added):]] if added else []

        if op == "update":
            updated = []
            by_id = {r.get("id"): r for r in rows}
            for it in (items or []):
                j = it.get("json", {})
                rid = j.get("id")
                if rid in by_id:
                    for c in cols:
                        if c in j:
                            by_id[rid][c] = j[c]
                    updated.append({"json": dict(by_id[rid])})
            data["rows"] = rows
            tabel_store.save_tabel(name, data)
            return updated

        raise ValueError(f"Unknown Tabel operation: {op}")
