# DuGS

A node-based workflow editor for Linux. Drag nodes onto a canvas, wire them
together, press Run, and watch the data move. Then hand the finished workflow
to [DuGS Runner](https://github.com/KeathMel/DuGS_Runner) so it keeps running
without the editor open.

Built in PyQt6 on pure standard library underneath. It also compiles a second
kind of project — a graph of hardware nodes — down to an Arduino sketch, and
simulates it first so you can see what the board would do before you own the
board.

---

## Contents

- [Running it](#running-it)
- [The five screens](#the-five-screens)
- [The editor](#the-editor)
- [How the engine executes a workflow](#how-the-engine-executes-a-workflow)
- [Expressions](#expressions)
- [Voice: audio in and audio out](#voice-audio-in-and-audio-out)
- [Where your data lives](#where-your-data-lives)
- [Credentials](#credentials)
- [Deploying to a runner](#deploying-to-a-runner)
- [The node library](#the-node-library)
- [Writing a node](#writing-a-node)
- [Writing a panel](#writing-a-panel)
- [Robotics projects](#robotics-projects)
- [The HTTP API](#the-http-api)
- [Known gaps](#known-gaps)

---

## Running it

Two processes, two terminals:

```bash
python3 api.py     # the engine + HTTP server, port 5800
python3 ui.py      # the window
```

`api.py` is where workflows actually execute. `ui.py` is only a face: it talks
to the API over HTTP, which is why a run can stream node-by-node into the
canvas while it happens.

On Hyprland, if the window misbehaves:

```bash
GDK_BACKEND=x11 python3 ui.py
```

Requirements: Python 3.10 or newer (the code uses `dict[str, X]` and `str |
None` syntax) and PyQt6. Nothing else — no virtualenv needed unless you want
one.

---

## The five screens

One stacked window, five screens, click the **DuGS** logo top-left to go home.

| Screen | What it is |
|---|---|
| **Home** | Projects, Tabels, Memory Banks, Semantic Tables. Everything starts here. |
| **Editor** | The node canvas. Where workflows get built and run. |
| **Tabel editor** | A spreadsheet grid. Columns, rows, right-click a header or a row to delete. Adding or renaming a column writes immediately; typing in cells is debounced. |
| **Memory bank viewer** | Entry list on the left, editable detail on the right. Sort oldest/newest, select and bulk delete. |
| **Semantic table editor** | Intents and the phrasings that mean them, for the Semantic Router node. |

---

## The editor

### Canvas

Nodes are squares with an icon, a title and the name you gave them. Drag to
move, drag from an output dot to an input dot to wire. Hover a node for the
delete button.

Output ports show what they **mean** rather than a number where that is
knowable: IF and Keyword Match show green `true` and red `false`, Loop shows
`loop` and `done`, and a Switch shows your own route names straight from the
node's settings — rename a route and the port renames with it. Labels hide
below 55% zoom so a wide graph stays readable.

Sticky notes live in the same file as the nodes, so they travel with a
workflow. They have no ports and the engine skips them.

### Panels

Three collapsible panels — left, right, bottom — with an arrow on each edge of
the work area. They start **empty**: pull one open, press `[+]`, tick which
modules it should hold. The modules that ship:

| Module | Side | What it shows |
|---|---|---|
| `NODES` | right | The node palette, grouped by category. Drag onto the canvas. |
| `TABELS & MEMORY` | left | Which Tabels and Memory Banks *this* workflow actually references. |
| `RUN LOG` | left | Past runs. |
| `OTHER PROJECTS` | left | Jump between workflows without going home. |
| `SETTINGS` | left | Editor settings. |
| `JSON` | bottom | The live workflow JSON. |

Panel layout is remembered between sessions.

### The node popup

Double-click a node. Three columns:

**INPUT** — every upstream node and the fields it produced, drag a field into
a parameter box to insert the expression for it. Not just the node directly
wired in: the whole chain back to the trigger.

**PARAMETERS** — one card per setting, with a `(?)` for the description and a
live preview underneath showing what the expression resolves to right now.

**OUTPUT** — what this node produced. Two things worth knowing:

- It shows **only the fields this node added or changed**. An item collects
  fields all the way down a chain, so by the time it reaches a node near the
  end it is carrying a memory summary, a file's contents and everything else
  picked up on the way. Calculator shows the sum and its answer; Date & Time
  shows the date. The `full item` toggle in the corner shows everything if you
  are chasing something from further upstream.
- A node that ran **more than once in a run** gets one tab per activation —
  `activation 1 2 3`. That is how you read a loop: what the AI asked for on
  pass one, what it answered on pass two. Nothing from a previous run is ever
  shown; the history is wiped when a new run starts.

Closing the popup commits every field, however you close it. You do not have
to click out of a box first.

### Running

**Run** executes the workflow in `api.py` and streams events back, so nodes
light up in order: yellow running, green done, red errored, with item counts
travelling along the wires. The log line for a repeat says which pass it was.

**Simulate** is for robotics projects — it runs the hardware graph virtually
and prints what the board would do, pin by pin, with timings.

### Autosave and undo

Every edit pushes an undo snapshot and queues an autosave 600 ms later, so
rapid edits do not hammer the disk. Autosave can be switched off in settings.

---

## How the engine executes a workflow

Identical in the editor and the runner — the same `engine.py` file.

### The shape of everything

An **item** is `{"json": {...}}`. A node receives a list of them and returns a
list of them. A node with several outputs returns a list of lists, one per
output port.

### Starting

Start nodes are those with `INPUTS == 0` or no incoming connection. A webhook
run instead starts at one specific node with the request as its data.

### Waiting for inputs

A node runs when **every wire into every connected input port has delivered** —
not when the first one does. Where two wires meet on one input ("read the file,
or skip straight past it"), whichever arrived first used to win, and if the
empty one won the real data was thrown away. Both are counted now.

### Dead branches

An IF or Switch sends items down one branch; the others deliver zero items. A
node with at least one wired input that receives **nothing on all of them** is
marked `SKIPPED (branch not taken)`:

- its `run()` is never called, so it cannot raise a config error for work
  nobody asked for
- it still emits empty output on every port, so a Merge waiting downstream does
  not deadlock

A node that genuinely wants to fire on nothing opts out with
`RUNS_ON_EMPTY = True`. And if real items turn up later at a node that was
collapsed this way, it runs after all — which is what makes the node *after* a
loop fire on the pass the loop exits.

### Loops

Two ways, and you rarely need the first:

**A Loop node** (`core.loop`) batches items and fires repeatedly, resetting
everything downstream of it on each pass.

**Any cycle in the graph.** Wire a node's output back round to it — through an
IF, normally — and the engine reads from the connections that those nodes sit
on a cycle and lets them run again. No special node, no checkbox. This is what
makes an AI node answerable twice: it asks for a calculation, the calculator
runs, and the AI is asked again with the real number.

Both are bounded:

- a back-edge carrying **zero items** does not re-trigger, so the loop ends
  when its IF stops sending anything round
- a hard cap of **25 passes** per node as a backstop, overridable per workflow
  with a top-level `"max_loops": 50`

`results` is never cleared between passes, which is why
`{{ $('Some Node').item.json.x }}` still resolves after a loop.

### Responding mid-run

A **Respond to Webhook** node records the reply and the run **keeps going** —
nodes wired after it, and nodes on other branches, still execute. The HTTP
reply is sent when the whole run finishes.

### Events

The engine calls `on_event` as it goes. This is what lights up the canvas:

| kind | carries |
|---|---|
| `start` | `nodes` |
| `node_running` | `node`, `type`, `items_in`, `pass` |
| `node_done` | `node`, `items_out`, `ports`, `ms`, `sample`, `in_sample`, `pass` |
| `edge` | `from`, `out`, `to`, `in`, `items` |
| `node_error` | `node`, `error` |
| `done` | — |

`pass` is how many times that node has executed **in this run**, which is what
the activation tabs are built on. `in_sample` is what went in, which is what
lets the output pane subtract it. Exceptions inside a listener are swallowed —
a broken listener can never break a run.

---

## Expressions

Any text parameter can contain `{{ }}`:

```
{{ $json.field }}                      a field on the item arriving here
{{ $json.body.message }}               nested works
{{ $('Some Node').item.json.field }}   a field on THAT node's own output
```

The third form is the important one. It reads the engine's stored results, not
the item on the wire, so it still works after a loop, across a branch, or when
an intermediate node stripped the item down to one value.

A parameter that is *entirely* one expression keeps the original type — a
number stays a number. Mixed into a sentence it is converted to text.

---

## Voice: audio in and audio out

### Posting a file at a webhook

A webhook body does not have to be JSON. POST a `.webm` voice note straight at
`/hook/<path>` with `Content-Type: audio/webm` and `api.py` **writes it to
`uploads/` and hands the workflow the path**:

```json
{ "audio_path": "uploads/upload_1760000000000.webm",
  "file_path":  "uploads/upload_1760000000000.webm",
  "filename":   "upload_1760000000000.webm",
  "content_type": "audio/webm",
  "bytes": 29348,
  "is_binary": true }
```

so a **Speech to Text** node reads it with source `file path` and

```
{{ $json.body.audio_path }}
```

Note which field. `body.filename` is the bare name and will not open —
`body.audio_path` is the one that resolves.

Binary bodies used to be decoded as UTF-8 with `errors="replace"`, which turns
every byte that is not valid UTF-8 into `U+FFFD`. The audio was destroyed
before any node could see it. Now the bytes reach disk untouched.

JSON and text bodies behave exactly as before. The routing rule is the
Content-Type: `json`, `text/*`, `xml`, `csv` and friends are text, everything
else becomes a file. Uploads are working data, not an archive — anything older
than 24 hours is swept on the next upload.

To branch on it, test `{{ $json.body.is_binary }}` with **exists**, which is
truer than matching the Content-Type string — browsers send
`audio/webm;codecs=opus`, not `audio/webm`.

### Replying with a file

The mirror of the above. Set **Respond to Webhook**'s Body to `file` and point
"File to send" at a path — normally the wav a **Text to Speech** node just
wrote:

```
{{ $json.audio_path }}
```

The reply is then the file itself: real bytes, the right `Content-Type`, no
JSON wrapper and no base64. Leave Content-Type blank and it is worked out from
the extension — and do leave it blank, because a half-filled field resolving
to `wav` is not a MIME type and will be sent as one.

The node hands over the **path**, not the bytes, and the server streams the
file. So a few hundred KB of audio never enters the item stream: run logs stay
readable and memory does not balloon on a long reply.

A client reading that reply must check the Content-Type before decoding.
Calling `.decode()` on a wav raises
`'utf-8' codec can't decode byte 0xac in position 29`.

### Running the voice stack

Whisper and Piper are not bundled; you run them and point the nodes at them.
Both of these are containers on the same machine as the app.

**Whisper** — [Speaches](https://speaches.ai), OpenAI-compatible, models
download on first use:

```bash
podman run -d --name speaches --replace --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v speaches-hf-cache:/home/ubuntu/.cache/huggingface/hub \
  ghcr.io/speaches-ai/speaches:latest-cpu

curl -X POST "http://127.0.0.1:8000/v1/models/Systran/faster-whisper-small"
```

Swap `latest-cpu` for `latest-cuda` plus `--device=nvidia.com/gpu=all` if you
have an NVIDIA card and `nvidia-container-toolkit` with CDI set up. The CUDA
image is several GB and podman stages pulls in `/var/tmp` — if root is tight,
`TMPDIR=~/tmp podman pull ...` puts the staging somewhere roomier.

**Piper** — no official image, so a four-line one:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir "piper-tts[http]"
ENV PIPER_VOICE=en_US-lessac-medium
RUN python3 -m piper.download_voices ${PIPER_VOICE} --data-dir /voices
EXPOSE 5000
CMD python3 -m piper.http_server -m ${PIPER_VOICE} --data-dir /voices --host 0.0.0.0 --port 5000
```

```bash
podman build -t localhost/piper .
podman run -d --name piper --replace --restart unless-stopped \
  -p 127.0.0.1:5000:5000 localhost/piper
```

The voice is baked into the image, not set on the node — Piper's `http_server`
is launched with one voice and `/synthesize` takes only `{"text": ...}`. To
change it, edit `PIPER_VOICE` and rebuild. Samples:
[rhasspy.github.io/piper-samples](https://rhasspy.github.io/piper-samples/).

**Node settings**, with the app running on the host:

| Node | Setting | Value |
|---|---|---|
| Speech to Text | Endpoint | `http://127.0.0.1:8000/v1/audio/transcriptions` |
| | Source | `file path` |
| | Audio | `{{ $json.body.audio_path }}` |
| | Model | `Systran/faster-whisper-small` |
| | Language | `en` — leave blank only if you really do switch languages |
| Text to Speech | Endpoint | `http://127.0.0.1:5000/synthesize` |
| | Request shape | `piper json` |

If you later run the app itself in a container, put all three on one podman
network and use the container names instead — `localhost` inside a container
means that container.

Whisper mangles names it has never heard. The **Hint** field exists for exactly
that: list your proper nouns and they stop coming out as nonsense. Leaving
Language blank makes it detect per request, which is slower and sometimes
wrong; set it if you always speak one language.

### Surviving a reboot

`--restart unless-stopped` covers crashes, not power cycles. Rootless podman
needs two more things, once:

```bash
sudo loginctl enable-linger $USER
systemctl --user enable --now podman-restart.service
```

Then both models come back on their own, with the models already downloaded
into the volume.

---

## Where your data lives

In the repo folder, beside the code:

```
projects/          workflow JSON
tabels/            spreadsheet-style tables
memory_banks/      key/value stores for the Memory nodes
semantic_tables/   intents for the Semantic Router
credentials/       named secrets, scrambled
sketches/          generated Arduino code
runs/              past run records (path configurable in settings)
uploads/           files POSTed at a webhook, swept after 24h
nodes/             workflow node types — drop a .py in to add one
robotics_nodes/    hardware node types
panels/            editor panel modules
```

> **There is no `.gitignore` in this repo.** `credentials/` sits inside the
> repo folder, so a careless `git add -A` will commit your API tokens. Worth
> adding one covering at least `credentials/`, `runs/`, `__pycache__/`.

A **memory bank** is one file:

```json
{ "name": "Schwortz",
  "entries": {
    "summary":             {"value": "...", "expires_at": null, "updated_at": 1760000000.0},
    "chat__1791519578220": {"value": "...", "expires_at": null, "updated_at": 1760000001.0}
  } }
```

Memory Write in *append* mode makes a **new** key with a millisecond timestamp
suffix rather than growing an existing value, so each append stays its own item
you can read back individually.

A **tabel** is one file:

```json
{ "name": "Finances",
  "columns": ["DATE", "Current", "IN", "OUT", "REASON"],
  "rows": [ {"id": 1, "DATE": "2026-10-10", "IN": 0, "OUT": 42.8, "REASON": "Rewe"} ] }
```

Row `id` is **renumbered 1…N on every save**. If you match rows on `id` and
then delete one, every row after it shifts identity — match on a column you
control if that matters to you.

---

## Credentials

A credential is a named secret — an API token — that nodes reference by name
instead of embedding. Stored scrambled:

```json
{"__enc__": "…"}
```

**Be clear-eyed about what that is.** It is an HMAC-SHA256 keystream keyed off
`DUGS_SECRET`, and with the built-in default key it is *obfuscation, not
security* — it stops a token being readable at a glance in a file or a diff. It
protects nothing against someone holding the repo, because the default key is
in the repo.

For real encryption, set your own, identically on every machine that touches
these files:

```bash
export DUGS_SECRET='something long and random'
```

A mismatch between the app and a runner is a confusing failure: the credential
loads, fails to unscramble, and the AI node behaves as though it had no key.

---

## Deploying to a runner

Point the app at a runner's folder once, then **Deploy** sends:

1. the workflow JSON into `projects/`
2. the **Tabels** and **Memory Banks** its nodes actually reference
3. the **credentials** its nodes reference, scrambled on the way out

The runner picks the file up within seconds and registers its triggers. No
restart, no copying by hand.

**Undeploy** syncs back — memory banks and tabels the runner has been writing
to come home, so a conversation it had while you were away is not lost.

---

## The node library

41 workflow node types in `nodes/`, plus 22 hardware ones in
`robotics_nodes/`. Categories are how the palette groups them.

**trigger** — `webhook.trigger`, `trigger.schedule`, `trigger.manual`

**core** — `core.set`, `core.edit_fields`, `core.code`, `core.merge`,
`core.loop`, `core.batch`, `core.split_out`, `core.aggregate`, `core.sort`,
`core.limit`, `core.dedupe`, `core.text`, `core.datetime`, `core.hash`,
`core.wait`, `core.log`

**logic** — `logic.if`, `logic.switch`, `logic.filter`, `logic.keywords`

**data** — `data.tabel`, `data.semantic`, `core.calculator`, `memory.read`,
`memory.write`, `memory.manage`

**action** — `file.read`, `file.create`, `file.edit`, `file.delete`,
`web.http`, `webhook.respond`, `action.telegram`, `action.discord`

**ai** — `ai.agent`, `ai.openrouter`, `audio.stt`, `audio.tts`

A few worth knowing about:

- **`core.calculator`** — an AST-walking arithmetic evaluator. It does **not**
  use `eval`: the expression is parsed and walked one node at a time, and
  anything that is not arithmetic is refused — no imports, no attribute
  access, no function calls beyond a small whitelist. Point an AI at it instead
  of letting the model do sums and even a weak model becomes reliable at
  numbers. Its `Output` setting decides whether you get the whole item back or
  just the answer.
- **`logic.keywords`** — true/false on whether any of a list of words or
  phrases appear in some text. Cheap routing without an AI call.
- **`data.semantic`** — routes by meaning rather than exact words, from a local
  semantic table. Also no model call.
- **`memory.manage`** — watches a bank's token count and, past a threshold,
  asks a model to compact it into a summary.
- **`audio.stt` / `audio.tts`** — a self-hosted Whisper and Piper. Neither
  bundles a model; see [Voice](#voice-audio-in-and-audio-out).
- **`web.http`** — besides JSON it can upload a file (raw body or multipart)
  and save a binary reply to disk rather than mangling it into a string.
- **`data.tabel`** — an empty read no longer kills the chain: it sends one item
  saying `{"count": 0, "empty": true}` so the nodes after it still run (set
  `If the table is empty` to `stop the branch` for the old behaviour). It can
  also map values to columns one at a time, or split **one** JSON field from an
  AI into the right columns.
- **`logic.if` / `logic.switch` / `logic.filter`** — `exists` and `not exists`
  used to compare the literal expression text against the item's keys, so they
  were always wrong on an expression. They now test whether the resolved field
  is actually missing.

`nodes/tunnel.py` is not a node — it is a standalone script that keeps a
cloudflared tunnel alive in front of port 5800. It sits in `nodes/` and loads
harmlessly, defining nothing.

---

## Writing a node

Drop a `.py` file in `nodes/` and restart. That is the whole process — no
registry, no manifest.

```python
from node_base import Node


class ShoutNode(Node):
    TYPE = "text.shout"          # unique id, used in the workflow JSON
    TITLE = "Shout"              # what the canvas shows
    CATEGORY = "core"            # core | logic | data | action | ai | trigger | robotics
    INPUTS = 1
    OUTPUTS = 1
    PARAMS = [
        {"key": "field", "label": "Field", "type": "text", "default": "text",
         "desc": "Which field to shout.",
         "example": "{{ $json.message }}"},
    ]

    def run(self, items):
        field = self.p("field", "text")
        out = []
        for it in (items or [{"json": {}}]):
            j = dict(it.get("json", {}))
            j[field] = str(self.rexpr(j.get(field, ""), j)).upper()
            out.append({"json": j})
        return out
```

What the base class gives you:

- `self.p(key, default)` — a parameter, with `None` treated as missing
- `self.rexpr(value, item_json)` — resolve `{{ }}` including `$('Node')` refs
- `self.resolve(key, item_json, default)` — both at once
- `self.params` — the raw dict
- `self._context` — every node's output so far, set by the engine before `run()`

Optional class flags:

- `ALLOW_RERUN = True` — may execute more than once per run (loop nodes)
- `RUNS_ON_EMPTY = True` — run even with zero input items

Raising inside `run()` does not kill the workflow: the engine catches it, emits
`node_error`, and passes an item carrying `{"error": "..."}` downstream.

### Parameter types

What a `"type"` draws in the settings panel and the popup:

| type | widget |
|---|---|
| `text` | one line, accepts dragged fields |
| `multiline` | expandable text area |
| `number` | one line, value coerced to int/float |
| `bool` | checkbox |
| `select` | dropdown from `options`, or `options_from: "credentials"` |
| `json` / `json_object` | JSON editor |
| `kv_rows` | name/value cards → `[{"name":…, "value":…}]` |
| `kv_dict` | name/value cards → `{"name": "value"}` |
| `switch_rules` | a card per output route, with the port name |
| `filter_rules` | a card per condition |
| `tabel` / `memory` / `semantic` | dropdown of saved ones |

Extra keys a parameter can carry: `desc` (hover help), `example` (appended to
the help), `name_hint` / `value_hint` (placeholders in the card widgets).

A `kv_dict` on a **Tabel** node gets its left-hand side as a dropdown of that
table's real column names, so you pick a column instead of spelling it. Still
typable, for a column you are about to create.

### Adding the icon and the palette entry

- icon: drop a PNG in `nodes_images/` named after the file (`core_calculator.py`
  → `core_calculator.png`)
- palette: add the `TYPE` string to the matching list in `NODE_GROUPS` in
  `editor.py` (around line 314). Robotics nodes go in `SERVO_GROUPS` just
  above it.

A node that loads fine but is missing from `NODE_GROUPS` simply never appears
in the palette. It still runs, and a workflow that already references it still
works — you just cannot drag a new one out.

---

## Writing a panel

Drop a `.py` in `panels/` with a class subclassing `Panel`:

```python
from panel_base import Panel


class MyPanel(Panel):
    ID = "my_panel"
    TITLE = "MY PANEL"
    SIDE = "left"        # left | right | bottom
    ORDER = 100

    def build(self):
        ...              # return a QWidget
```

Optional hooks, all called by the editor:

```python
def on_project_opened(self, name): ...
def on_selection_changed(self, node): ...
def on_workflow_changed(self): ...
def on_run_event(self, evt): ...
def refresh(self): ...
def apply_theme(self, css, colors): ...
def header_widgets(self): return []
```

`on_workflow_changed` fires on every edit, so a panel can stay live as nodes
are added and removed rather than only updating on save.

---

## Robotics projects

A second project kind. Instead of items flowing through nodes, you build a
hardware graph from the 22 `device.*` nodes in `robotics_nodes/` — pins,
servos, buttons, encoders, screens, timers, variables, states, loops — and the
editor compiles it to an Arduino sketch in `sketches/`.

Device nodes draw smaller and in red on the canvas, so a hardware graph reads
differently at a glance.

**Simulate** runs the graph virtually first and prints what the board would do:

```
  0.0s  SERVO pin 9  -> 90 deg   [Servo 1]
  1.0s  PIN 13 = 1              [Pin 2]
  1.0s  wait 500ms              [Wait 3]
```

so you can find a logic mistake before wiring anything, or before the hardware
has even arrived.

---

## The HTTP API

`api.py` on port **5800**.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` | Liveness. |
| `GET` | `/nodes` | Every node type, with its params — this is what fills the palette. |
| `GET` | `/webhooks` | Currently registered webhook paths. |
| `GET` | `/events` | Server-sent event stream. The editor subscribes so a webhook firing lights up the canvas. |
| `POST` | `/run` | Run a workflow, get the results in one response. |
| `POST` | `/run-stream` | Run it and stream each execution event as it happens. This is what the Run button uses. |
| `POST` | `/generate` | Compile a robotics project to an Arduino sketch. |
| `POST` | `/webhooks/register` | Register a workflow's webhook paths. |
| `ANY` | `/hook/<path>` | Fire a registered webhook. JSON and text bodies arrive as fields; anything else is written to `uploads/` and the workflow gets the path. |
| `ANY` | `/resume/<id>` | Resume a paused run. |

Note the `/hook/` prefix — it is **not** there on the runner, where a webhook
at `/bruh` is simply `http://host:5801/bruh`. Mixing the two up is a common
five-minute confusion.

---

## Known gaps

Honest list of things that are declared but not true, or true but annoying.

**`show_if` is not implemented.** Several nodes declare parameters that should
only appear for a given operation. They appear always. Harmless, but do not
trust it, and do not add parameters that are *dangerous* when ignored.

**Parameter widgets are a hardcoded if/elif chain, in two files.** Both
`node_popup.py` and `editor_settings.py` have their own copy. A node cannot
bring its own widget, which is why adding a new parameter type means editing
the editor rather than just the node. This is the one piece of structural debt
worth paying off — it is also why `show_if` was easy to declare and never got
built.

**`core_set.py` calls bare `resolve_expr`.** It passes no context, so
`{{ $('Other Node').item.json.x }}` silently resolves to nothing inside a Set
node. Same bug was fixed in IF and Switch; Set still has it. One line.

**Tabel row ids are renumbered on every save.** Covered above — match on a
stable column if it matters.

**`NODE_GROUPS` in `editor.py` is out of sync with `nodes/`.** It is a
hand-maintained list, so it drifts in both directions:

- missing, so they never show in the palette despite loading fine —
  `core.calculator`, `audio.stt`, `audio.tts`
- listed but no such node exists in this repo — `core.wait_webhook`,
  `data.notes` (`data.notes` lives in the runner's `nodes/`, not the app's)

Neither breaks anything at runtime. Worth reconciling, or better, worth
generating the palette from the registry instead of typing it twice.

**A script lives in `nodes/`.** `tunnel.py` is a cloudflared keeper, not a
node. It belongs at the top level.

**No tests.** Everything is verified by running it. That works because it is
used daily, but a refactor has no safety net.

**No `.gitignore`.** See [Where your data lives](#where-your-data-lives).
