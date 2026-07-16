# dugs

A clean, modular node engine. Build workflows as blocks that pass data to each
other — for both web stuff (APIs, data) and, later, hardware (Bluetooth, robots,
serial). Keeps the good idea behind n8n (data flows as a list of items, decorated
node by node) but fixes the bad part: every node is one self-contained drop-in
file, not a tangled monorepo.

## Run it

```bash
python3 engine.py                       # runs demo_workflow.json
python3 engine.py branching_workflow.json
```

## How it works (the whole thing, briefly)

A workflow is a JSON file: a list of **nodes** + a **connections** map of
who-feeds-whom. Data passed between nodes is always a list of items, each item a
dict `{"json": {...}}`. The engine finds the start node, runs it, passes its
output list to the connected node, runs that, and repeats until done.

A node is a function: items in -> items out. That's it.

## Project layout

```
dugs/
├── engine.py            # the core: discover nodes, load workflow, walk graph
├── node_base.py         # the Node contract every node follows
├── nodes/               # one file per node — drop a new file in, it appears
│   ├── trigger_manual.py
│   ├── core_set.py
│   ├── core_log.py
│   └── logic_if.py
├── demo_workflow.json
└── branching_workflow.json
```

## Adding a node (the point of dugs)

Create a new file in `nodes/`, e.g. `nodes/core_wait.py`:

```python
from node_base import Node

class WaitNode(Node):
    TYPE = "core.wait"
    TITLE = "Wait"
    CATEGORY = "core"
    INPUTS = 1
    OUTPUTS = 1

    def run(self, items):
        import time
        time.sleep(self.params.get("seconds", 1))
        return items
```

Save it. The engine auto-discovers it next run. No changes to engine.py.
Reference it in a workflow JSON by its TYPE (`"type": "core.wait"`).

## Node data shape

```python
item = {"json": {"any": "data"}}      # one item
items = [item, item, ...]             # what flows between nodes
```

A node returning a single list -> goes out output port 0.
A node returning a list-of-lists -> one list per output port (e.g. IF: [true, false]).

## API server (the spine)

Run the engine as a service so a UI, a container, or another machine can drive it:

```bash
python3 api.py                 # http://127.0.0.1:5800 (local only)
python3 api.py 0.0.0.0 5800    # all interfaces (for hosting/remote/container)
```

Endpoints:
- `GET /health` -> `{"status":"ok"}`
- `GET /nodes`  -> list of available node types (for a UI palette)
- `POST /run`   -> body is a workflow JSON; runs it; returns per-node results

Example:
```bash
curl -X POST http://127.0.0.1:5800/run \
     -H "Content-Type: application/json" \
     -d @demo_workflow.json
```

This is the line between engine and face. Local now, hostable later — same code.

## Roadmap

- [x] core engine: discovery, graph walk, item passing, multi-output branching
- [x] useful web nodes: HTTP request, Code, Wait
- [x] local API so a UI or container can drive the engine (the "run anywhere" line)
- [ ] transparent native UI (the face)
- [ ] hardware nodes: Bluetooth, serial, GPIO
- [ ] self-firing triggers, loops, timers

## Status

Early. The core loop works. Runs each node once from trigger to end. Does not yet
handle loops, waiting/timers across runs, or triggers that fire on their own.
Those come as the roadmap above gets built.
