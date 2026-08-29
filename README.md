# DuGS

DuGS vision is for it to be a node builder like n8n and also for Robotics. But one that is esaly hostabale from most if not any device. Its currenty in devlopment mostly build with AI.

DuGS is two things sharing one canvas. Normal projects run in the engine like n8n does. Servo projects dont run, they generate real Arduino code you can flash to a board, and they have a simulator so you can watch what the board would do without pluging anything in.

---

## INSTALL

One command, does everything. Clones the repo, installs what it needs, puts the icon and app entry in place so DuGS shows up in your application menu.

```
curl -fsSL https://raw.githubusercontent.com/KeathMel/DuGS/main/install.sh | bash
```

Run the same command again later to update.

After that just launch DuGS from your app menu, or run `~/DuGS/DuGS.sh`.

Linux only for now. The app itself runs anywhere Python and PyQt6 do, its only the installer that is Linux specific.

---

## REQUIRMENTS

Python 3.9 or higher

```
sudo apt install python3-pip
pip install --break-system-packages PyQt6
sudo apt install libxcb-cursor0 libxcb-icccm4
```

---

## COMMANDS

To Start open the terminal, for linux you use this comand structure

```
cd "PATH"
python3 api.py
```

Open another Termnal and use this command structure

```
cd "PATH"
GDK_BACKEND=x11 python3 ui.py
```

Or skip both and just use `./DuGS.sh` which starts them together and shuts the api down again when you close the window.

If something changed but doesnt show up, its almost always old bytecode:

```
find . -name __pycache__ -type d -exec rm -rf {} +
```

---

## LEAVING WORKFLOWS RUNNING

The app is for building. If you want workflows running when the app is closed —
on a Pi, a server, a phone — thats the runner:

https://github.com/KeathMel/Deploy_DuGS

Build here, hit **Deploy** in the top bar. First time, it asks for the
runner's `projects/` folder — a Scan button hunts for it on disk, or point at
it by hand. After that it's remembered.

Deploy copies the workflow in, and if it uses a **Tabel** or a **Memory
Bank**, those come with it — copied into `tabels/` and `memory_banks/` next
to the runner's `projects/` folder, so the nodes actually have something to
read on the other end. Two workflows sharing the same Tabel don't duplicate
it. **Undeploy** removes the workflow, and cleans up its Tabel/Memory Bank
data too — but only if nothing else still deployed needs it.

**Download** does the same trick for taking a workflow somewhere by hand: one
file with the workflow plus whatever Tabels/Memory Banks it uses, bundled in,
ready to move to another machine.

Once deployed, a project's name shows **green** on the home screen so you can
see what's live at a glance. A deployed project can't be renamed — undeploy
first.

### Watching what the runner's done

The home screen has a pull-up panel at the very bottom — **▲ Runs**. Opens to
show every run the runner's done: timestamp, whether it errored, and the full
input/result it worked with. Useful for exactly the thing you'd expect: a
webhook fired from somewhere and you want to see precisely what arrived.

The switch next to Copy flips between the raw JSON and a **node view** — the
run drawn as a small graph, same as it'd look on the canvas, coloured by what
happened: normal colour if a node produced output, red if it's part of a run
that errored and never fired, grey if it never ran that pass at all.

Nothing here refreshes on its own — hit **↻ Refresh**, or the **📁 Runs
folder…** button if you need to point it at a different runner. There's also
a "wipe older than" setting (Never / 24 hours / 5 hours) if the run history
piles up.

---

## THE EDITOR LAYOUT

The tools around the canvas are not fixed in place. Each one is a MODULE, and
they sit inside PANELS along the left, right and bottom edges.

- The arrow on each edge pulls that panel open or shut.
- The `+` at the bottom of a panel lists every module it can show. Tick one to
  add it, untick to take it away.
- Hold the middle mouse button on a module and drop it on another panel to move
  it. Right click a module for the same thing plus remove.
- Several modules in one panel get the three dot grip lines between them so you
  can resize them against each other.
- Your layout is saved, so its there again next time you open DuGS.

First launch gives you a starting layout (settings, projects and run log on the
left, nodes on the right, code on the bottom). After that its yours.

---

## WHAT THE FILES DO

### UI

| File | What it does |
|---|---|
| `ui.py` | The entry point. Builds one window holding three screens (Home, Editor, TabelEditor) and switches between them. Everything else lives in its own module. |
| `home_screen.py` | The landing screen. Project grid, New Project popup where you pick Normal or Servo, tabels, credentials, and the settings popup. Servo projects show up red. |
| `home_preview.py` | The detail pane on the home screen. Shows what nodes a selected project uses, like an inventory with a count on each one, plus a description you can edit. |
| `editor.py` | The editor shell. Top bar, canvas, and the panel system that holds the modules. Run / Export Code / Simulate, undo redo, autosave, the red theme for servo projects. |
| `canvas.py` | The actual node graph. Draws nodes and wires, drag, zoom, pan, box select and mass move, wire delete badges, hover a node and press Tab for its popup. Also draws the background, the dot grid and the see-through mode. |
| `node_popup.py` | The big node popup (Tab on a node, or double click). Input, parameters and output side by side, drag a field into a box to make a `{{ }}` reference. |
| `panel_base.py` | The module and panel system. What a module is, how panels hold them, the grip dots, the arrows, the `+` menu. |
| `editor_settings.py` | Builds the parameter form for whichever node is selected. |
| `editor_widgets.py` | Small custom widgets the editor is made of: the splitters with grip handles, and the drag-and-drop parameter boxes. |
| `editor_workers.py` | The background threads, so running or simulating never freezes the window. |
| `tabel_editor.py` | The spreadsheet grid editor for tabels. |
| `theme.py` | Colors, accent, node size, the stylesheet. |

### MODULES (the tools around the canvas)

Each of these is a file in `panels/`. Drop a new one in and it turns up in the
`+` menu.

| File | What it does |
|---|---|
| `panel_nodes.py` | The node palette you drag from, with its search box. |
| `panel_settings.py` | The parameters of the selected node. |
| `panel_run_log.py` | The output from a run, an export or a simulation. |
| `panel_other_projects.py` | Your other projects, click one to switch. |
| `panel_json.py` | The workflow as JSON, or the live Arduino code for servo projects, with a copy button. |

### ENGINE (the n8n side)

| File | What it does |
|---|---|
| `engine.py` | Runs a workflow. Walks the graph, waits for all inputs before running a node, handles loops, streams live events so the canvas lights up, and can pause a run and resume it later. |
| `node_base.py` | The base class every normal node builds on, plus the expression resolver that makes `{{ $json.x }}` and `{{ $('Node').item.json.x }}` work. |
| `api.py` | The HTTP server on port 5800. Serves the node list, runs workflows, handles webhooks, resumes paused runs, generates sketches, streams run events. |
| `api_client.py` | Small helper the GUI uses to talk to api.py. |
| `storage.py` | Saves and loads projects, credentials, sketches, window layout. |
| `tabel_store.py` | Storage for tabels. |

### ROBOTICS (the Arduino side)

| File | What it does |
|---|---|
| `device_base.py` | The base class every robotics node builds on. Pin names get used exactly as you type them (9, A0, GPIO17, LED_BUILTIN) so any board works. |
| `codegen.py` | Turns the graph into real Arduino code. Splits setup and loop, builds if else, for loops, state machine switches, arrays, servo banks. |
| `simulate.py` | Runs the graph virtually so you can watch what the board would do. Catches things like a servo already sitting at the angle you told it to go to, an empty Repeat, or a Pin node fighting a Servo on the same pin. |

### LAUNCH

| File | What it does |
|---|---|
| `install.sh` | The one command installer. |
| `DuGS.sh` | Starts api.py and ui.py together, kills the api again when you close the window, clears old bytecode first. |
| `requirements.txt` | What pip needs to install. |
| `tunnel.py` | Keeps a cloudflared tunnel alive so webhooks are reachable from outside. Optional, its a script not a node. |

---

## FOLDERS

| Folder | Whats in it |
|---|---|
| `nodes/` | The normal nodes, one file each: `core_*`, `logic_*`, `web_*`, `action_*`, `trigger_*`, `webhook_*`. |
| `robotics_nodes/` | The robotics nodes, one file each: `dev_*` and `pins.py`. |
| `panels/` | The modules that sit around the canvas. |
| `icons/` | The app icon in all the sizes a desktop needs. |
| `nodes_images/` | Icons for the normal nodes, shown in the palette and on the canvas. |
| `robotics_nodes_images/` | Same but for the robotics nodes. |
| `projects/` | Your saved workflows. |
| `tabels/` | Your saved tabels. |
| `sketches/` | Arduino code that Export Code writes out, one folder per project. |
| `credentials/` | Saved tokens and keys. |
| `paused_runs/` | Runs that are sitting paused waiting on a webhook to wake them up. |

---

## THE NODES

### Normal nodes

**Triggers** — Manual Trigger, Schedule, Webhook, Respond to Webhook

**Logic** — IF, Switch, Filter, Merge

**Data** — Set, Edit Fields, Text Template, Code, Split Out, Aggregate, Sort, Limit, Remove Duplicates, Date & Time, Hash

**Flow** — Loop Over Items, Wait, Wait for Webhook (this one pauses the whole workflow until something calls it back, no time limit)

**Action** — HTTP Request, Telegram, Discord

**Other** — Tabel, Log

### Robotics nodes

**Flow** — On Start (runs once at power on), On Repeat (runs forever), Repeat, Comment

**Servo** — Servo, Servo Array, Servo Move

**Screen** — Screen

**Input** — Button, Encoder

**Logic** — If, State, Go To State, Random

**Timing** — Wait, Timer (this one is non blocking so the screen stays alive)

**Routing** — Pins, Pin, Array, Array Set, Variable, Map

---

## ADDING A NODE

Normal nodes go in `nodes/`, robotics nodes go in `robotics_nodes/`. Drop the
file in, restart api.py, and it shows up in the palette.

Copy an existing file thats close to what you want and change it. Below is one
node pulled apart so you can see every piece.

### A node, dissected

```python
"""
Memory Write — save a value into a Memory Bank.       <- the docstring shows up
                                                          nowhere in the UI, its
Longer explanation for whoever reads the file.            for you and for me
"""
import os, sys
from node_base import Node                    # every normal node subclasses this

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage                                # anything at the repo root, after
                                              # that sys.path line

class MemoryWriteNode(Node):
    TYPE     = "memory.write"    # unique id. Also decides the icon filename and
                                 # which palette group it lands in
    TITLE    = "Memory Write"    # what the palette and the node show
    CATEGORY = "data"            # colours the node and sorts the palette
    INPUTS   = 1                 # how many input ports (0 = its a trigger)
    OUTPUTS  = 1                 # how many output ports (2+ = it branches)

    PARAMS = [ ... ]             # every setting the node shows, see below

    def run(self, items):        # the actual work
        ...
```

### The parameters, one of each kind

`PARAMS` is a list of dicts. Every one needs `key` (where the value is stored)
and `label` (what the user sees). Everything else is optional.

```python
PARAMS = [

    # --- plain text --------------------------------------------------------
    {"key": "bank_key", "label": "Key", "type": "text", "default": "",
     "desc": "The key to store the value under.",   # hover help, see below
     "example": "chat_history"},

    # --- big text box, gets an expand button in the popup ------------------
    {"key": "value", "label": "Value", "type": "multiline", "default": "",
     "desc": "What to store. Expressions allowed.",
     "example": "{{ $json.message }}"},

    # --- number ------------------------------------------------------------
    {"key": "ttl_minutes", "label": "Expire after (minutes)",
     "type": "number", "default": 0,
     "desc": "How long it lives. 0 means never."},

    # --- switch ------------------------------------------------------------
    {"key": "append", "label": "Append instead of replace",
     "type": "bool", "default": False},

    # --- dropdown, fixed list ----------------------------------------------
    {"key": "mode", "label": "Result", "type": "select",
     "default": "replace", "options": ["replace", "append"]},

    # --- dropdown filled from your saved stuff ------------------------------
    {"key": "credential", "label": "AI credential", "type": "select",
     "default": "", "options_from": "credentials"},

    # --- pick a Tabel / a Memory Bank ---------------------------------------
    {"key": "tabel", "label": "Tabel",  "type": "tabel",  "default": ""},
    {"key": "bank",  "label": "Memory Bank", "type": "memory", "default": ""},

    # --- raw JSON box --------------------------------------------------------
    {"key": "payload", "label": "Body", "type": "json", "default": {}},

    # --- only show this while another setting says so -----------------------
    {"key": "system_prompt", "label": "Compaction instructions",
     "type": "multiline", "default": "",
     "show_if": {"compact": True}},        # hidden until 'compact' is on
]
```

**Every type:** `text`, `multiline`, `number`, `bool`, `select`, `tabel`,
`memory`, `json`. Leave `type` out and you get `text`.

**`show_if`** takes `{"other_key": value}`. The row only appears while that
other setting matches. A list works too: `{"mode": ["a", "b"]}`.

**`desc` / `example` / `result`** are the hover help. The row shows a small
`(?)` next to the label and hovering it shows those — so the label stays short
instead of a paragraph wrecking the layout.

### The run method

```python
    def run(self, items):
        # `items` is a list of {"json": {...}} — that's the shape everything
        # passes around. Return the same shape.
        out = []
        for it in items:
            j = it.get("json", {})

            bank = self.p("bank")                  # a raw setting
            key  = self.rexpr(self.p("key"), j)    # a setting with {{ }} resolved
                                                   # against THIS item

            storage.memory_set(bank, key, "...")

            out.append({"json": {**j, "memory_key": key}})   # keep the old data,
        return out                                          # add yours
```

`self.p(key, default)` reads a setting as-is. `self.rexpr(value, item_json)`
resolves `{{ $json.x }}` and `{{ $('Other Node').item.json.x }}` against the
item being processed. Use `rexpr` for anything the user might put an expression
in.

**Branching:** return a list of lists instead, one per output port —
`return [true_items, false_items]`. Set `OUTPUTS = 2` to match.

**Triggers:** set `INPUTS = 0`. The engine treats it as a starting point.

### The icon

Drop a png in `nodes_images/` (or `robotics_nodes_images/` for robotics)
**named after the node type**. For `core.set` any of these work:

```
set.png            <- just the last bit
core_set.png       <- dot swapped for underscore   (safest)
core.set.png       <- the whole type id
core-set.png
```

`core_set.png` is the one to use if you are unsure — it always matches.

Two things that catch people out:

- The icons are cached at startup. Add the image **before** launching, or
  restart after.
- White backgrounds show up as a white box on the dark node. Use a png with a
  transparent background, and light-coloured art so it reads.

### Palette grouping

To put the node in a particular group, add its type to `NODE_GROUPS` (or
`ROBOTICS_GROUPS` for robotics) in `editor.py`. Anything not listed falls into
MORE.

### Robotics nodes are different

They subclass `DeviceNode` from `device_base.py`, their `TYPE` starts with
`device.`, and they never run — they emit C++ instead:

```python
class ServoNode(DeviceNode):
    TYPE = "device.servo"

    def includes(self): return ["#include <Servo.h>"]        # top of the sketch
    def globals(self):  return [f"Servo servo_{self.pin_var()};"]
    def setup(self):    return [f"servo_{self.pin_var()}.attach({self.pin()});"]
    def loop(self):     return [f"servo_{self.pin_var()}.write({self.num('angle')});"]
```

`self.pin()` gives the pin name exactly as typed — `9`, `A0`, `GPIO17`,
`LED_BUILTIN` — so any board works.

---

## ADDING A MODULE

Same idea as nodes, but for the tools around the canvas. Drop a file in
`panels/`, restart, and it turns up in the `+` menu on every panel.

```python
from panel_base import Panel
from PyQt6.QtWidgets import QLabel

class NotesModule(Panel):
    ID    = "notes"       # unique, used when saving the layout
    TITLE = "NOTES"       # shown in the header and the + menu
    SIDE  = "left"        # where it goes if nothing is saved yet
    ORDER = 50            # order within that side
    STRETCH = 1           # share of space against its neighbours

    def build(self):
        return QLabel("hello")
```

`self.editor` gets you the Editor, so a module can reach the canvas, the
current project, the API, whatever it needs.

There are optional hooks you can add if you want them, all of them safe to
leave out:

| Hook | When it fires |
|---|---|
| `on_project_opened(name)` | a project was opened or switched |
| `on_selection_changed(node)` | a node was selected, None when deselected |
| `on_workflow_changed()` | the graph changed |
| `on_run_event(evt)` | a live run event arrived |
| `refresh()` | asked to redraw itself |
| `apply_theme(css, colors)` | the appearance settings changed |
| `header_widgets()` | extra buttons to sit next to the title |

A module that crashes gets logged and skipped instead of taking the editor down
with it.


---

# SYSTEM ARCHITECTURE — how this actually works internally

Everything below this line is written for whoever (human or AI) needs to
change something and doesn't want to rediscover the internals by reading
every file cold. Where something is stated as fact, it was read directly out
of the current source, not inferred or guessed — that distinction matters
because guessed internals are exactly what caused wasted turns before this
section existed. Where a detail comes from earlier work in this same
project (not re-verified this pass) it says so.

## The three processes, and which one runs a workflow

DuGS is not one program. It's three, and knowing which one you're looking
at answers most confusion before it starts:

| Process | File | Talks Qt? | Runs `engine.py`? |
|---|---|---|---|
| The desktop app | `ui.py` (+ editor/home/tabel/memory screens) | yes | no — never directly |
| The local API server | `api.py` | no | yes, server-side |
| The headless runner | `dugs_runner.py` (separate repo) | no | yes, standalone |

**The app never runs a workflow itself.** Pressing Run in the editor does
not call `engine.run_workflow()` in the app's own process. It starts a
`RunWorker` (in `editor_workers.py`) which does an HTTP POST to
`api.py`'s `/run-stream` endpoint. `api.py` is the one that actually calls
`engine.run_workflow(workflow, on_event=push)`, and streams the results
back over Server-Sent Events. The app just relays and displays.

This matters because "why doesn't my change to editor.py affect what
happens when I press Run" is answered by: because the actual execution
happens in a different process (`api.py`), not the one you're editing.

The headless runner (`dugs_runner.py`) is the third path: it imports and
calls `engine.run_workflow()` **directly**, no HTTP, no Qt, nothing — that's
what lets it run on a phone under Termux with zero dependencies beyond
Python itself. All three consumers (app-via-api, webhooks-via-api, and the
standalone runner) share the exact same `engine.py` and the exact same node
files — that's the one core the whole system is built around.

## The engine (`engine.py`) — the actual execution core

`Engine.run_workflow(workflow, start_node=None, start_data=None, on_event=None)`
is the only entry point. It:

1. Instantiates every node in `workflow["nodes"]` via `self.registry` (built
   by `discover_nodes()`, which imports every `.py` file in a `nodes/`
   folder and registers any `Node` subclass by its `TYPE`).
2. Works out **start nodes** — nodes with `INPUTS == 0`, or nodes with no
   incoming connection — and seeds them with either empty items, or (if
   `start_node`/`start_data` were given, which is how a real webhook hit or
   a headless-runner trigger kicks things off) the real incoming data.
3. Walks a work queue of `(target_name, in_port, items)` deliveries. A node
   only actually runs once **every** connected input port has delivered —
   this is what makes a Merge-style multi-input node correctly wait for
   every branch instead of firing on the first one to arrive.
4. Builds `node._context` before calling `node.run()` — a dict of
   `{other_node_name: [that node's first-output-port items]}` for every
   node that's already produced output. This is exactly what powers
   `{{ $('Other Node').item.json.x }}` expressions, and it means **any**
   already-run node is referenceable, not just the one directly wired in
   (this is the mechanism the popup's variable picker was fixed to actually
   expose — see "the upstream-nodes bug" below).
5. Nodes with `ALLOW_RERUN = True` on their class can fire more than once
   — this is how a feedback loop works: an IF's "false" branch wiring back
   into a Loop node re-triggers it, clearing that node's (and everything
   downstream of it's) prior run-state so it can go again. A back-edge
   delivering **zero** items into an already-run loop node does NOT
   re-trigger it — that's the guard against a false/empty branch spinning
   the loop forever.
6. A node can raise `WebhookRespondSignal(status, body)` (from
   `webhook_respond.py`) to short-circuit the entire run immediately and
   return `{"__webhook_response__": {"status":..., "body":...}, **results}`
   — this is how "Respond to Webhook" sends an HTTP reply and stops the
   workflow in one move, from deep inside the node itself, not by any
   special-casing in the engine.

### The `on_event` callback — exact shapes, verbatim from the engine's own docstring

```
{"kind": "start", "nodes": [...names...]}
{"kind": "node_running", "node": name, "type": type_id, "items_in": N}
{"kind": "node_done", "node": name, "items_out": N,
                       "ports": [N0, N1, ...], "ms": float,
                       "sample": [ ...up to 3 item jsons... ]}
{"kind": "edge", "from": name, "out": i, "to": name, "in": j, "items": N}
{"kind": "node_error", "node": name, "error": str}
{"kind": "done"}
```

`sample` is exactly `[item.get("json", {}) for item in first_output_port[:3]]`
— the first up to 3 items' json dicts from the node's **first** output port
only. This is the field that carries anything a node stamped onto its own
output — including AI token counts (see "Token tracking" below). A failure
inside `on_event` itself is swallowed (`try/except: pass`) so a broken
listener can never break the actual run.

## How a Run button press actually flows, end to end

1. `Editor.run()` builds the workflow dict, creates a `RunWorker(wf)`
   (`editor_workers.py`), connects `run_worker.event` to
   `Editor._on_run_event`, and starts the thread.
2. `RunWorker.run()` does `for evt in api_post_stream("/run-stream", wf): self.event.emit(evt)`
   — it does **no interpretation**, it just relays whatever comes back.
3. On the server side, `api.py`'s `_handle_run_stream` calls
   `engine.run_workflow(workflow, on_event=push)`, where `push(evt)` writes
   `f"data: {json.dumps(evt)}\n\n"` to the open HTTP response — a
   Server-Sent-Events stream. It does not reformat or filter events; every
   `emit()` call inside the engine reaches the client as-is.
4. Back in the app, `Editor._on_run_event(evt)` is where the human-readable
   text actually gets built. For a `node_done` event:
   ```python
   self._last_results[evt["node"]] = evt.get("sample", [])
   ms = evt.get("ms", 0)
   self._append_result(
       f"{evt['node']}  →  {evt.get('items_out', 0)} item(s)  ({ms:.0f} ms)"
   )
   ```
   `self._append_result` writes into `editor.results` — the `QTextEdit`
   from the Run Log module — and `self._last_results[node_name]` is what
   feeds the node popup's OUTPUT column when you reopen a node after a run.

A webhook hit follows the same `engine.run_workflow(..., on_event=...)`
call, inside `api.py`'s `_handle_webhook_hit` — but it broadcasts through
the general `/events` stream instead of `/run-stream`. Before running, it
fires `{"kind": "webhook_run_start", "workflow": name, "path": path}`, and
every subsequent engine event gets tagged with `workflow` and
`"source": "webhook"` before being broadcast, so a listening UI knows which
project's canvas to light up even though nobody personally pressed Run.
`EventListener` (a persistent background subscriber in `editor_workers.py`)
is what's listening on that `/events` stream, reconnecting automatically if
the server restarts.

The **headless runner** (`dugs_runner.py`) does not go through any of this
— it calls `engine.run_workflow()` directly in its own process and writes
one JSON file per run into `runs/`, with its own separate schema (see
"The two run-history systems" below). It is not wired to `editor.py` at
all; the two are independent consumers of the same engine.

## The Node contract (`node_base.py`)

Every node subclasses `Node` and sets, at minimum, `TYPE` (a unique string
like `"core.set"`), and implements `run(self, items) -> items`.

Class attributes: `TITLE`, `CATEGORY` (which palette group it sorts into
and what colour it gets), `INPUTS`, `OUTPUTS` (integers; `INPUTS = 0` marks
it as a trigger), `PARAMS` (the settings list — see the "ADDING A NODE"
section above for every param type).

Instance helpers, all inherited:
- `self.p(key, default)` — the raw param value, no `{{ }}` resolving.
- `self.resolve(key, item_json, default)` / `self.rexpr(value, item_json)`
  — resolves `{{ }}` expressions, including cross-node references, against
  `self._context` (set by the engine right before `run()` is called — see
  step 4 above).
- `params` is a plain dict the engine builds from the saved workflow JSON's
  `node["params"]`.

**Branching**: return a list of lists instead of a flat list — one list per
output port. Set `OUTPUTS` to match. The engine treats `output[0]` being a
list as "this is multi-port" and normalises accordingly.

**Triggers**: `INPUTS = 0`. The engine seeds it directly, no upstream
delivery needed.

## Token tracking — the actual mechanism, and the current known gap

There is **no special AI-node handling anywhere in the engine**. Token
counts flow through the exact same `sample` field every other node's
output does — an AI node just needs to put a `tokens_used` (or
`tokens_this_call`) key onto its own output item's `json`, the same way it
puts `reply` there. Nothing else needs to know AI nodes exist as a
category.

`ai_helper.py` (carried from earlier work this session, not re-verified
this pass — flag if something here doesn't match a fresh read) is a small
shared module: a process-wide token counter (`tokens_used()`,
`_add_tokens(n)`, `reset_tokens()`) plus a generic OpenAI-compatible
`chat()` helper. `ai_agent.py` calls `ai_helper._add_tokens()` after every
API call and stamps `tokens_used` onto its output — this is the pattern
every AI node is meant to follow.

**Known gap, verified by reading the current file**: `ai_openrouter.py`'s
`_call()` method reads the full API response (`payload`) but only extracts
`payload["choices"][0]["message"]["content"]`. It never touches
`payload.get("usage")` — which is where OpenRouter (same OpenAI-compatible
shape as everywhere else) puts `prompt_tokens` / `completion_tokens` /
`total_tokens`. This is why token counts show up nowhere for this node: the
data is thrown away before it ever reaches the item, so there's nothing in
`sample` for any consumer (the editor's live log, the headless runner's
run-history, anything) to find.

**The exact fix, verified against the real call chain**: in
`ai_openrouter.py`'s `_call()`, after parsing `payload`, pull
`payload.get("usage", {})` and return it alongside the reply text; in
`run()`, stamp it onto the output item (e.g. `out.append({"json": {**j,
"reply": reply_text, "tokens_used": usage.get("total_tokens")}})`). Once
that's in the item's json, it automatically appears in `evt["sample"]` on
the `node_done` event with zero engine or transport changes needed — and
`Editor._on_run_event` can then read `evt.get("sample", [{}])[0].get("tokens_used")`
to append it to the log line, exactly where the existing
`f"{evt['node']} → {items_out} item(s) ({ms:.0f} ms)"` line is built.

## The panel/module system (carried from earlier work this session)

Panels live down the left/right/bottom edges of the editor, start empty,
and are populated via a `+` menu that lists every discovered module. A
module is a `Panel` subclass (`panel_base.py`) with `ID`, `TITLE`, `SIDE`,
`ORDER`, `STRETCH`, and a `build()` method returning the widget it shows.

Optional hooks (all safe to skip): `on_project_opened(name)`,
`on_selection_changed(node)`, `on_workflow_changed()`, `on_run_event(evt)`,
`refresh()`, `apply_theme(css, colors)`, `header_widgets()`.

By convention, `Editor.results` is the `QTextEdit` the Run Log module
exposes (`panel_run_log.py` sets `self.editor.results = box` in its
`build()`) — any code anywhere that wants to write a status line calls
`self.results.setText(...)` / the `_append_result` helper, without needing
to know or care whether the Run Log module is currently even visible.

`on_workflow_changed` exists on every panel but historically was never
actually called by anything — `mark_changed()` (called after every node
add/move/delete/param edit) now fires it, so a panel like "Tabels &
Memory" (which lists what the *live* canvas references, not just the last
save) updates immediately as you edit, not only after an autosave.

## The two run-history systems — do not confuse them

There are **two separate places** a "run log" can mean, and they are not
the same code, the same file format, or the same UI:

1. **The editor's live text log** — `panel_run_log.py`'s `QTextEdit`
   (`editor.results`), filled line-by-line by `_on_run_event` as described
   above. Text only, ephemeral, cleared on each new run, exists only while
   the app is open and a run is happening live.

2. **The headless runner's persisted history** — `dugs_runner.py` writes
   one JSON file per run into `runs/`, with fields: `workflow`, `ran_at`,
   `duration_ms`, `input`, `result`, `error`, `layout` (a snapshot of node
   positions/wiring, captured separately via `_extract_layout(wf)` so a run
   can be redrawn without needing the original project file), and
   `node_status` (per-node `items_out`, `ms`, and `tokens` — built from the
   SAME `on_event` callback mechanism, just consumed differently: the
   runner's own `run_workflow()` wrapper installs an `on_event` that
   accumulates `node_done` events into `node_timing`/`node_tokens` dicts
   over the course of one run, then bakes them into the saved record).
   This is what `home_screen.py`'s Runs drawer / `RunCanvasView` reads —
   it's a completely separate, disk-persisted system, unrelated to the
   app's live text log, and it works whether or not the desktop app was
   ever open for that run.

If you're asked to "add tokens to the run log," always ask (or check)
**which** of these two is meant — the fixes live in different files
(`editor.py` for #1, `dugs_runner.py` for #2), and doing one doesn't
touch the other at all.

## Storage layer (`storage.py`) — the five kinds of saved things

All pure filesystem I/O, no Qt. Five categories, each its own folder:
`projects/` (workflows), `tabels/` (spreadsheets), `credentials/`,
`memory_banks/`, and (runner-only) `runs/`.

Key functions worth knowing exist rather than rediscovering:
`load_project`/`save_project`, `load_tabel`/`save_tabel`,
`load_memory_bank`/`save_memory_bank`, `memory_get`/`memory_set`/`memory_all`/
`memory_all_sorted`/`memory_clear`, `deploy_project`/`undeploy_project`
(which also carry a workflow's Tabel/Memory dependencies along to the
runner folder — see `workflow_dependencies()`), `export_project` (the
single-file portable bundle format for Download).

`memory_set(bank, key, value, ttl_seconds=None, append=False)` — with
`append=True`, writes a **brand new, separate entry** under an
auto-generated timestamp-suffixed key, rather than growing whatever's
already under `key`. It does not merge or concatenate. Returns
`(value, actual_key)` — the actual key matters because it won't equal the
`key` you passed in when appending.

---
