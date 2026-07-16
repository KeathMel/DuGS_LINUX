"""
Set node: adds or overwrites fields on every item's json.
The "decorate the JSON as it flows" workhorse (n8n's Set node).
"""
from node_base import Node


class SetNode(Node):
    TYPE = "core.set"
    TITLE = "Set"
    CATEGORY = "core"
    INPUTS = 1
    OUTPUTS = 1
    PARAMS = [
        {"key": "fields", "label": "Fields to set", "type": "json", "default": {}},
    ]

    def run(self, items):
        fields = self.params.get("fields") or {}
        out = []
        for item in items:
            new_json = dict(item.get("json", {}))
            new_json.update(fields)
            out.append({"json": new_json})
        return out
