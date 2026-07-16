"""
Log node: prints each item it receives, then passes them through unchanged.
Lets you SEE the data flowing in the terminal.
"""
import json
from node_base import Node


class LogNode(Node):
    TYPE = "core.log"
    TITLE = "Log"
    CATEGORY = "core"
    INPUTS = 1
    OUTPUTS = 1
    PARAMS = [
        {"key": "label", "label": "Log label", "type": "text", "default": ""},
    ]

    def run(self, items):
        label = self.params.get("label") or self.name
        for i, item in enumerate(items):
            print(f"    [{label}] item {i}: {json.dumps(item.get('json', {}))}")
        return items
