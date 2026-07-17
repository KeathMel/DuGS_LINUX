"""
Wait node: pause the flow for a number of seconds, then pass items through.
"""
import time
from node_base import Node


class WaitNode(Node):
    TYPE = "core.wait"
    TITLE = "Wait"
    CATEGORY = "core"
    INPUTS = 1
    OUTPUTS = 1
    PARAMS = [
        {"key": "seconds", "label": "Seconds", "type": "number", "default": 1},
    ]

    def run(self, items):
        time.sleep(float(self.params.get("seconds", 1) or 0))
        return items
