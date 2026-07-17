"""
Manual Trigger: starts the workflow and emits the first item.
The 'data' param becomes the initial json that flows downstream.
"""
from node_base import Node, make_item


class ManualTrigger(Node):
    TYPE = "trigger.manual"
    TITLE = "Manual Trigger"
    CATEGORY = "trigger"
    INPUTS = 0
    OUTPUTS = 1
    PARAMS = [
        {"key": "data", "label": "Start data", "type": "json", "default": {}},
    ]

    def run(self, items):
        start_data = self.params.get("data")
        if not start_data:
            start_data = {"started": True}
        return [make_item(start_data)]
