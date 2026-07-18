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

## WHAT THE FILES DO

### UI

| File | What it does |
|---|---|
| `ui.py` | The entry point. Builds one window holding three screens (Home, Editor, TabelEditor) and switches between them. Everything else lives in its own module. |
| `home_screen.py` | The landing screen. Project grid, New Project popup where you pick Normal or Servo, credentials tab, tabels list. Servo projects show up red. |
| `editor.py` | The main editor. Palette on the left, canvas in the middle, JSON or CODE panel bottom right. Run / Export Code / Simulate buttons, node popup, undo redo, the red theme for servo projects. |
| `canvas.py` | The actual node graph. Draws nodes and wires, drag, zoom, pan, box select and mass move, wire delete badges, hover a node and press Tab for its popup. |
| `editor_settings.py` | The right hand settings panel for the selected node. |
| `tabel_editor.py` | The spreadsheet grid editor for tabels. |
| `theme.py` | Colors, accent, node size, the stylesheet. |

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
| `nodes/` | Every node, one file each. Both kinds live here. Normal nodes are `core_*`, `logic_*`, `web_*`, `action_*`, `trigger_*`, `webhook_*`. Robotics nodes are `dev_*` and `pins.py`. |
| `icons/` | The app icon in all the sizes a desktop needs. |
| `nodes_images/` | Icons shown on the nodes themselves in the palette and canvas. |
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

Drop a new file in `nodes/`, restart api.py, it shows up. Normal nodes subclass `Node` from `node_base.py` and have a `run()`. Robotics nodes subclass `DeviceNode` from `device_base.py`, their type starts with `device.`, and they emit C++ instead of running. Copy an existing file thats close to what you want and change it.

To put it in a specific palette group, add its type to `NODE_GROUPS` or `ROBOTICS_GROUPS` in `editor.py`.
