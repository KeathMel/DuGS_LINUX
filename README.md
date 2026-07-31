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
