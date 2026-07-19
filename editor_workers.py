"""
editor_workers.py — the background threads the editor runs work on.

  RunWorker     : runs a workflow through the API and streams events back, so
                  the UI stays responsive and the canvas can light up live.
  SimWorker     : runs a robotics graph through the simulator, streaming what
                  the board would be doing.
  EventListener : a persistent subscriber to the server's /events stream, so
                  webhook-triggered runs light up the canvas even though the
                  user never pressed Run.

All three talk back to the editor with Qt signals — never by touching widgets
directly, which would not be thread-safe.
"""
import json
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

from theme import API
from api_client import api_post, api_post_stream


class SimWorker(QThread):
    """Runs a robotics graph simulation in the background, streaming what the
    board would be doing (servo moves, pin writes, delays) so you can watch it
    play out live without any hardware."""
    event = pyqtSignal(dict)

    def __init__(self, workflow, loops=None, realtime=True):
        super().__init__()
        self.workflow = workflow
        self.loops = loops
        self.realtime = realtime
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            import simulate
            simulate.simulate(self.workflow, self.event.emit,
                              max_loops=self.loops, realtime=self.realtime,
                              stop=lambda: self._stop)
        except Exception as e:
            self.event.emit({"t": 0, "kind": "warn", "node": "",
                             "msg": f"simulation failed: {e}"})


class RunWorker(QThread):
    """Streams a workflow run from the API and re-emits each execution event
    as a Qt signal, so the canvas can update live on the GUI thread."""
    event = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, workflow):
        super().__init__()
        self.workflow = workflow

    def run(self):
        try:
            for evt in api_post_stream("/run-stream", self.workflow):
                self.event.emit(evt)
        except Exception as e:
            self.failed.emit(str(e))


class EventListener(QThread):
    """Persistent background subscriber to the server's /events stream, so the
    canvas lights up when a webhook fires the current workflow. Reconnects
    automatically if the server restarts."""
    event = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._stop = False

    def run(self):
        import urllib.request, json as _json
        while not self._stop:
            try:
                req = urllib.request.Request(f"{API}/events")
                with urllib.request.urlopen(req, timeout=60) as resp:
                    block = []
                    for raw in resp:
                        if self._stop:
                            break
                        line = raw.decode("utf-8", "ignore").rstrip("\n")
                        if line == "":
                            for l in block:
                                if l.startswith("data:"):
                                    payload = l[5:].strip()
                                    if payload:
                                        try:
                                            self.event.emit(_json.loads(payload))
                                        except Exception:
                                            pass
                            block = []
                        elif not line.startswith(":"):
                            block.append(line)
            except Exception:
                pass
            # brief pause before reconnecting
            if not self._stop:
                self.msleep(1500)

    def stop(self):
        self._stop = True


