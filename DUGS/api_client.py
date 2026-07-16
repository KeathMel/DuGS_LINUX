"""
api_client.py — thin HTTP helpers the UI uses to talk to api.py.
Kept separate from storage.py (local file I/O) and ui.py (widgets).
"""
import json
import urllib.request
from theme import API


def api_get(path):
    with urllib.request.urlopen(f"{API}{path}", timeout=10) as r:
        return json.loads(r.read().decode())


def api_post(path, payload, timeout=60):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def api_post_stream(path, payload, timeout=600):
    """POST and yield parsed Server-Sent-Event payloads as they arrive.
    Each yielded value is the dict from a `data: {...}` line. Used by the
    editor to show live run progress (nodes lighting up, item counts,
    Wait pauses) instead of waiting for the whole run to finish."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    block = []
    for raw in resp:
        line = raw.decode("utf-8", "ignore").rstrip("\n")
        if line == "":
            for l in block:
                if l.startswith("data:"):
                    payload_str = l[5:].strip()
                    if payload_str:
                        try:
                            evt = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue
                        yield evt
                        if evt.get("kind") in ("results", "fatal"):
                            try: resp.close()
                            except Exception: pass
                            return
            block = []
        else:
            block.append(line)
