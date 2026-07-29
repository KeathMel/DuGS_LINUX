"""
api.py — the spine. Wraps the dugs engine in a small HTTP service so anything
(a UI, a container, curl, another machine) can drive it over the network.

Pure Python standard library. No installs.

Endpoints:
  GET  /nodes              -> list available node types (for a UI palette)
  GET  /health             -> {"status": "ok"}
  POST /run                -> body = workflow JSON; runs it; returns per-node results
  POST /webhooks/register  -> body = workflow JSON; scans for webhook.trigger nodes
                               and registers their paths so real HTTP hits route to them
  ANY  /hook/<path>        -> a real webhook hit; runs the matching workflow

Run:
  python3 api.py                 # listens on http://127.0.0.1:5800
  python3 api.py 0.0.0.0 5800    # listen on all interfaces (for container/remote)
"""

from __future__ import annotations
import os
import sys
import json
import queue
import threading
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from engine import Engine, discover_nodes

HERE = os.path.dirname(os.path.abspath(__file__))
NODES_DIR = os.path.join(HERE, "nodes")
ROBOTICS_DIR = os.path.join(HERE, "robotics_nodes")

engine = Engine(NODES_DIR)

# path -> {"workflow": {...}, "node_name": "...", "method": "POST"}
# Registered whenever a workflow containing a webhook.trigger node is saved
# (the UI should POST to /webhooks/register after every save) or on server boot
# by scanning the projects folder.
webhook_registry: dict[str, dict] = {}

PROJECTS_DIR = os.path.join(HERE, "projects")

# ---- paused runs (Wait for Webhook): kept in memory AND on disk so a resume
# call works even if it lands on a fresh process ----
_paused_runs: dict = {}
_PAUSED_DIR = os.path.join(HERE, "paused_runs")


def _save_paused_run(rid, paused):
    try:
        os.makedirs(_PAUSED_DIR, exist_ok=True)
        with open(os.path.join(_PAUSED_DIR, f"{rid}.json"), "w") as f:
            json.dump(paused, f)
    except Exception as e:
        print(f"  [warn] could not save paused run {rid}: {e}")


def _load_paused_run(rid):
    try:
        with open(os.path.join(_PAUSED_DIR, f"{rid}.json")) as f:
            return json.load(f)
    except Exception:
        return None


def _delete_paused_run(rid):
    try:
        os.remove(os.path.join(_PAUSED_DIR, f"{rid}.json"))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Live event broadcast — lets the editor UI watch webhook-triggered runs as
# they happen (canvas lights up just like the Run button). Each connected UI
# gets its own queue; the webhook handler pushes engine events to all of them.
# ---------------------------------------------------------------------------
_subscribers: list[queue.Queue] = []
_sub_lock = threading.Lock()


def broadcast_event(evt: dict):
    with _sub_lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(evt)
        except Exception:
            pass


def add_subscriber() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=1000)
    with _sub_lock:
        _subscribers.append(q)
    return q


def remove_subscriber(q: queue.Queue):
    with _sub_lock:
        if q in _subscribers:
            _subscribers.remove(q)


def node_catalog() -> list[dict]:
    out = []
    for type_id, cls in sorted(engine.registry.items()):
        out.append({
            "type": type_id,
            "title": cls.TITLE,
            "category": cls.CATEGORY,
            "inputs": cls.INPUTS,
            "outputs": cls.OUTPUTS,
            "params": getattr(cls, "PARAMS", []),
        })
    # ---- robotics / device nodes (servo projects) ----
    # These don't run in the engine — they generate Arduino code. They're
    # served here so the editor can show them in a ROBOTICS palette section.
    try:
        import codegen
        dev_reg = codegen.discover_device_nodes(None, ROBOTICS_DIR)
        for type_id, cls in sorted(dev_reg.items()):
            out.append({
                "type": type_id,
                "title": cls.TITLE,
                "category": getattr(cls, "CATEGORY", "robotics"),
                "inputs": cls.INPUTS,
                "outputs": cls.OUTPUTS,
                "params": getattr(cls, "PARAMS", []),
                "device": True,          # marks it as a code-generating node
            })
    except Exception as e:
        print(f"  [warn] could not load device nodes: {e}")
    return out


def generate_sketch(workflow: dict) -> str:
    """Compile a servo project's graph into Arduino .ino source."""
    import codegen
    reg = codegen.discover_device_nodes(None, ROBOTICS_DIR)
    return codegen.generate(workflow, reg)


def register_webhooks_from_workflow(workflow: dict):
    """Scan a workflow for webhook.trigger nodes and register their paths."""
    for n in workflow.get("nodes", []):
        if n.get("type") == "webhook.trigger":
            path = (n.get("params", {}).get("path") or "/webhook").strip()
            if not path.startswith("/"):
                path = "/" + path
            method = (n.get("params", {}).get("method") or "ANY").upper()
            webhook_registry[path] = {
                "workflow": workflow,
                "node_name": n["name"],
                "method": method,
            }
            print(f"  [webhook] registered {method} /hook{path} -> '{n['name']}' in '{workflow.get('name','?')}'")


def register_all_saved_webhooks():
    """On boot, scan every saved project for webhook triggers."""
    if not os.path.isdir(PROJECTS_DIR):
        return
    for fname in os.listdir(PROJECTS_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(PROJECTS_DIR, fname)) as f:
                wf = json.load(f)
            register_webhooks_from_workflow(wf)
        except Exception as e:
            print(f"  [warn] could not scan {fname} for webhooks: {e}")


def mark_respond_nodes_as_real(workflow: dict):
    """Flip 'is_test_run' to True on every webhook.respond node so it
    actually raises the signal instead of passing data through (used only
    when a REAL hook hits, not when testing from the editor)."""
    for n in workflow.get("nodes", []):
        if n.get("type") == "webhook.respond":
            n.setdefault("params", {})["is_test_run"] = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  api: " + (fmt % args) + "\n")

    def _send(self, code: int, payload, is_raw=False):
        if is_raw:
            body = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
            ctype = "text/plain"
        else:
            body = json.dumps(payload).encode("utf-8")
            ctype = "application/json"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, {"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self._send(200, {"status": "ok"})
        elif path == "/nodes":
            engine.registry = discover_nodes(NODES_DIR)
            self._send(200, {"nodes": node_catalog()})
        elif path == "/webhooks":
            self._send(200, {"registered": [
                {"path": p, "method": v["method"], "node": v["node_name"], "workflow": v["workflow"].get("name")}
                for p, v in webhook_registry.items()
            ]})
        elif path.startswith("/resume/"):
            self._handle_resume(path[len("/resume/"):], parsed, "GET")
        elif path.startswith("/hook/"):
            self._handle_webhook_hit(path[5:], "GET", parsed)
        elif path == "/events":
            self._handle_events_stream()
        else:
            self._send(404, {"error": "not found", "path": path})

    def _handle_events_stream(self):
        """Server-Sent-Events stream of live run events (currently webhook
        runs). The editor UI subscribes here so its canvas can light up when
        a webhook fires."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = add_subscriber()
        try:
            # initial comment so the client knows it's connected
            self.wfile.write(b": connected\n\n"); self.wfile.flush()
            while True:
                try:
                    evt = q.get(timeout=15)
                except Exception:
                    # heartbeat keeps the connection alive through idle periods
                    try:
                        self.wfile.write(b": ping\n\n"); self.wfile.flush()
                        continue
                    except Exception:
                        break
                try:
                    self.wfile.write(f"data: {json.dumps(evt)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    break
        finally:
            remove_subscriber(q)

    def _do_any(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/run":
            self._handle_run()
        elif path == "/generate":
            self._handle_generate()
        elif path == "/run-stream":
            self._handle_run_stream()
        elif path == "/webhooks/register":
            self._handle_register()
        elif path.startswith("/resume/"):
            self._handle_resume(path[len("/resume/"):], parsed, method)
        elif path.startswith("/hook/"):
            self._handle_webhook_hit(path[5:], method, parsed)
        else:
            self._send(404, {"error": "not found", "path": path})

    def do_POST(self):
        self._do_any("POST")

    def do_PUT(self):
        self._do_any("PUT")

    def do_PATCH(self):
        self._do_any("PATCH")

    def do_DELETE(self):
        self._do_any("DELETE")

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None, b""
        # transparently handle gzip/deflate-compressed bodies (many HTTP
        # clients and webhook senders compress by default)
        encoding = (self.headers.get("Content-Encoding") or "").lower()
        data = raw
        if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
            try:
                import gzip
                data = gzip.decompress(raw)
            except Exception:
                data = raw
        elif encoding == "deflate":
            try:
                import zlib
                data = zlib.decompress(raw)
            except Exception:
                try:
                    import zlib
                    data = zlib.decompress(raw, -zlib.MAX_WBITS)
                except Exception:
                    data = raw
        # try to parse JSON; on ANY failure (bad JSON, binary, bad encoding)
        # return the decoded text instead of crashing the request thread.
        try:
            return json.loads(data), data
        except Exception:
            try:
                return None, data.decode("utf-8", "replace").encode("utf-8")
            except Exception:
                return None, raw

    def _handle_generate(self):
        """Compile a servo project into an Arduino sketch and save it."""
        body, raw = self._read_json_body()
        if body is None and raw:
            self._send(400, {"error": "invalid JSON"}); return
        workflow = body or {}
        try:
            code = generate_sketch(workflow)
            from storage import save_sketch
            name = workflow.get("name", "sketch")
            path = save_sketch(name, code)
            self._send(200, {"ok": True, "path": path, "code": code})
        except Exception as e:
            import traceback; traceback.print_exc()
            self._send(500, {"ok": False, "error": str(e)})

    def _handle_run(self):
        body, raw = self._read_json_body()
        if body is None and raw:
            self._send(400, {"error": "invalid JSON"}); return
        workflow = body or {}
        try:
            engine.registry = discover_nodes(NODES_DIR)
            results = engine.run_workflow(workflow)
            self._send(200, {"ok": True, "results": results})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

    def _handle_run_stream(self):
        """Run a workflow and stream execution events as Server-Sent Events.
        Each event is a line:  data: {json}\\n\\n
        The engine's on_event callback writes here as nodes actually execute,
        so the client sees real timing (a Wait node pauses the stream at its
        own position, etc.). The final event carries the full results."""
        body, raw = self._read_json_body()
        if body is None and raw:
            self._send(400, {"error": "invalid JSON"}); return
        workflow = body or {}

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def push(evt):
            try:
                self.wfile.write(f"data: {json.dumps(evt)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

        try:
            engine.registry = discover_nodes(NODES_DIR)
            results = engine.run_workflow(workflow, on_event=push)
            push({"kind": "results", "results": results})
        except Exception as e:
            push({"kind": "fatal", "error": str(e)})

    def _handle_register(self):
        body, raw = self._read_json_body()
        if body is None:
            self._send(400, {"error": "invalid JSON"}); return
        try:
            register_webhooks_from_workflow(body)
            paths = [n.get("params", {}).get("path", "/webhook")
                     for n in body.get("nodes", []) if n.get("type") == "webhook.trigger"]
            self._send(200, {"ok": True, "registered_paths": paths})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

    def _handle_webhook_hit(self, path, method, parsed):
        if not path.startswith("/"):
            path = "/" + path
        entry = webhook_registry.get(path)
        if entry is None:
            self._send(404, {"error": f"no webhook registered for {path}",
                              "hint": "save/open the project in the editor so it auto-registers, "
                                      "or POST the workflow to /webhooks/register"})
            return
        if entry["method"] != "ANY" and entry["method"] != method:
            self._send(405, {"error": f"webhook at {path} expects {entry['method']}, got {method}"})
            return

        body_json, raw = self._read_json_body() if method in ("POST", "PUT", "PATCH", "DELETE") else (None, b"")
        if body_json is None and raw:
            body_json = raw.decode("utf-8", errors="replace")

        query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
        headers = {k: v for k, v in self.headers.items()}

        request_data = {
            "method": method,
            "path": path,
            "query": query,
            "headers": headers,
            "body": body_json,
        }

        workflow = json.loads(json.dumps(entry["workflow"]))  # deep copy
        mark_respond_nodes_as_real(workflow)

        wf_name = workflow.get("name", "?")
        # tell any listening UI which workflow is about to run via webhook,
        # so it can switch to / highlight the right canvas.
        broadcast_event({"kind": "webhook_run_start", "workflow": wf_name, "path": path})

        def _relay(evt):
            # tag each engine event with the workflow + source so the UI can
            # replay it on the matching canvas
            evt = dict(evt); evt["workflow"] = wf_name; evt["source"] = "webhook"
            broadcast_event(evt)

        try:
            engine.registry = discover_nodes(NODES_DIR)
            results = engine.run_workflow(workflow, start_node=entry["node_name"],
                                          start_data=request_data, on_event=_relay)
        except Exception as e:
            import traceback
            traceback.print_exc()
            broadcast_event({"kind": "webhook_run_error", "workflow": wf_name, "error": str(e)})
            try:
                self._send(500, {"ok": False, "error": str(e),
                                 "where": "workflow execution"})
            except Exception:
                pass
            return

        try:
            paused = results.get("__paused__")
            if paused:
                import uuid as _uuid
                rid = _uuid.uuid4().hex[:12]
                _paused_runs[rid] = paused
                _save_paused_run(rid, paused)
                broadcast_event({"kind": "webhook_run_paused", "workflow": wf_name,
                                 "resume_id": rid, "label": paused.get("label", "")})
                self._send(200, {"ok": True, "paused": True, "resume_id": rid,
                                 "resume_url": f"/resume/{rid}",
                                 "label": paused.get("label", ""),
                                 "note": "workflow paused; POST to resume_url to continue it"})
                return
            webhook_resp = results.get("__webhook_response__")
            if webhook_resp:
                self._send(webhook_resp["status"], webhook_resp["body"])
            else:
                # no Respond node was reached — auto-ack
                self._send(200, {"ok": True, "note": "workflow finished, no Respond to Webhook node was hit"})
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self._send(500, {"ok": False, "error": str(e), "where": "sending response"})
            except Exception:
                pass

    def _handle_resume(self, rid, parsed, method):
        """Resume a workflow that paused at a 'Wait for Webhook' node."""
        paused = _paused_runs.get(rid) or _load_paused_run(rid)
        if paused is None:
            self._send(404, {"ok": False, "error": f"no paused run with id {rid}"})
            return

        body_json, raw = self._read_json_body() if method in ("POST", "PUT", "PATCH", "DELETE") else (None, b"")
        if body_json is None and raw:
            body_json = raw.decode("utf-8", errors="replace")
        query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
        resume_data = {
            "method": method,
            "query": query,
            "body": body_json,
        }

        workflow = paused["workflow"]
        wf_name = workflow.get("name", "?")

        def _relay(evt):
            evt = dict(evt); evt["workflow"] = wf_name; evt["source"] = "resume"
            broadcast_event(evt)

        broadcast_event({"kind": "webhook_run_resumed", "workflow": wf_name, "resume_id": rid})

        try:
            engine.registry = discover_nodes(NODES_DIR)
            results = engine.resume_workflow(workflow, paused["state"], paused["node"],
                                             resume_data=resume_data, on_event=_relay)
        except Exception as e:
            import traceback; traceback.print_exc()
            self._send(500, {"ok": False, "error": str(e), "where": "resuming"})
            return

        # the resumed run might pause AGAIN at a later wait node
        again = results.get("__paused__")
        if again:
            _paused_runs[rid] = again
            _save_paused_run(rid, again)
            self._send(200, {"ok": True, "paused": True, "resume_id": rid,
                             "resume_url": f"/resume/{rid}",
                             "note": "workflow paused again at a later wait node"})
            return

        # finished — clean up the stored paused run
        _paused_runs.pop(rid, None)
        _delete_paused_run(rid)
        webhook_resp = results.get("__webhook_response__")
        if webhook_resp:
            self._send(webhook_resp["status"], webhook_resp["body"])
        else:
            self._send(200, {"ok": True, "resumed": True, "note": "workflow finished"})


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5800
    register_all_saved_webhooks()
    server = ThreadingHTTPServer((host, port), Handler)
    print("=" * 44)
    print("  dugs — api server")
    print("=" * 44)
    print(f"  listening on http://{host}:{port}")
    print(f"  nodes dir:   {NODES_DIR}")
    print( "  endpoints:   GET /health  GET /nodes  POST /run")
    print( "               POST /webhooks/register  GET /webhooks")
    print( "               ANY  /hook/<path>   <- real webhook hits land here")
    print( "  (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")


if __name__ == "__main__":
    main()
