"""
simulate.py — run a robotics graph virtually, like the board would.

Instead of compiling to C++ and flashing, this walks the SAME graph in
Python and pretends to be the microcontroller:

    setup()  -> the 'On Start' chain, once
    loop()   -> the 'On Repeat' chain, over and over

WHAT CHANGED FROM THE OLD ONE
    It used to walk every node in the graph in order, which meant an
    If node ran BOTH its branches and a Timer ran its "done" chain on
    every single pass. The picture it painted was not the sketch you
    were about to flash. Now branches are evaluated for real, port by
    port, exactly the way codegen.py emits them -- one branch runs, the
    others do not.

    It also has a clock now. Timer and Countdown are checked against
    virtual milliseconds, so a 7h30 countdown really does tick down,
    and `speed` lets you watch it in a minute instead of in 7h30.

    And buttons can be pressed. The old one auto-pressed and blocked;
    this one takes presses from the UI through `press_queue`, so a tap
    and a hold are two different things, as they are on the board.

EVENTS
    Everything that happens is reported through emit(). The visual view
    draws from these; the log view prints them.

    {"kind":"board",   "board":"t-display-s3", "pins":[...]}
    {"kind":"servo",   "pin":"1", "angle":180, "prev":0, "node":"Slap"}
    {"kind":"servo_release", "pin":"1"}
    {"kind":"pin",     "pin":"13", "value":"HIGH"}
    {"kind":"screen",  "text":"07:30:00", "x":14, "y":60, "size":6,
                       "color":"#00ffff", "clear":True, "w":320, "h":170}
    {"kind":"backlight","level":40}
    {"kind":"var",     "var":"setH", "value":8}
    {"kind":"branch",  "node":"CD", "port":0, "label":"done"}
    {"kind":"warn",    "msg":"..."}

    Every event also carries "t", the virtual seconds since power-on.
"""
import time

# node types that pick ONE output port instead of flowing straight on
BRANCH_TYPES = ("device.if", "device.timer", "device.countdown", "device.button")

# nodes that only declare things; they run no action of their own
DECL_TYPES = ("device.pins", "device.on_start", "device.on_repeat",
              "device.comment", "device.array", "device.servo_array")

PORT_LABELS = {
    "device.if":        {0: "true", 1: "false"},
    "device.timer":     {0: "done", 1: "waiting"},
    "device.countdown": {0: "done", 1: "ticking"},
    "device.button":    {0: "tap", 1: "hold", 2: "repeat"},
}

# what a pin is being used for, so the board view can label it
ROLE_BY_TYPE = {
    "device.servo": "servo",
    "device.button": "button",
    "device.pin": "pin",
    "device.encoder": "encoder",
    "device.backlight": "backlight",
}


class SimState:
    """The virtual board: pin values, servo angles, variables, the clock."""

    def __init__(self):
        self.t = 0.0            # virtual seconds since power-on
        self.servos = {}        # pin -> angle
        self.attached = {}      # pin -> bool (a released servo goes limp)
        self.pins = {}          # pin -> value
        self.vars = {}          # variable name -> value
        self.timers = {}        # name -> due time in virtual seconds
        self.counts = {}        # name -> {"end": secs, "fired": bool}
        self.buttons = {}       # name -> {"down": bool, "since": secs, ...}
        self.arrays = {}        # name -> list of values
        self.banks = {}         # bank name -> list of pins
        self.state = None       # current state machine state
        self.screen = ""
        self.loop_count = 0

    def millis(self):
        return self.t * 1000.0


def _num(v, default=0):
    try:
        f = float(str(v).strip())
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return default


def _resolve_pin(raw, pin_map):
    """A node's pin field may be a NAME declared in the Pins node."""
    return pin_map.get(str(raw).strip(), str(raw).strip())


def _targets(name, conns, port=0):
    return [l["to"] for l in conns.get(name, []) if l.get("out", 0) == port]


def board_info(workflow):
    """What the board view needs before anything runs: the pin map, what
    each named pin is for, and the power pins it should warn about."""
    pins, roles = [], {}
    board = "arduino"
    for n in workflow.get("nodes", []):
        if n["type"] == "device.pins":
            p = n.get("params", {}) or {}
            board = str(p.get("board", "arduino"))
            for entry in (p.get("pins") or []):
                if isinstance(entry, dict) and entry.get("name"):
                    pins.append({"name": str(entry["name"]).strip(),
                                 "pin": str(entry.get("pin", "")).strip()})
    # which node uses which pin decides the label
    lookup = {p["name"]: p for p in pins}
    for n in workflow.get("nodes", []):
        role = ROLE_BY_TYPE.get(n["type"])
        if not role:
            continue
        p = n.get("params", {}) or {}
        for key in ("pin", "pin_a", "pin_b"):
            raw = str(p.get(key, "")).strip()
            if not raw:
                continue
            if raw in lookup:
                lookup[raw]["role"] = role
            else:
                pins.append({"name": raw, "pin": raw, "role": role})
                lookup[raw] = pins[-1]
    for p in pins:
        p.setdefault("role", "unused")
    return {"board": board, "pins": pins, "power": [
        {"name": "GND", "note": "needed for operation — every part shares it"},
        {"name": "5V" if board == "arduino" else "5V (USB rail)",
         "note": "needed for operation — servos must NOT run off 3V3"},
    ]}


def simulate(workflow, emit, max_loops=None, realtime=False, stop=None,
             speed=1.0, press_queue=None, idle_ms=5.0):
    """Run the graph. `emit(event)` is called for everything that happens.

    max_loops   how many times to run loop() (None = forever)
    realtime    actually sleep during delays, so it plays at board speed
    stop        a callable returning True to abort
    speed       virtual seconds per real second. 600 watches a ten-hour
                countdown in a minute; 1 is real time.
    press_queue a callable returning a list of ("name", "down"/"up")
                from the UI's buttons, drained each pass
    idle_ms     virtual time a loop pass costs when nothing waits. Without
                it a loop with no delay spins forever at t=0 and no timer
                ever comes due.
    """
    nodes_by_name = {n["name"]: n for n in workflow.get("nodes", [])}
    conns = workflow.get("connections", {})
    st = SimState()
    speed = max(0.01, float(speed or 1.0))

    pin_map = {}
    for n in workflow.get("nodes", []):
        if n["type"] == "device.pins":
            for entry in (n.get("params", {}).get("pins") or []):
                if isinstance(entry, dict) and entry.get("name"):
                    pin_map[str(entry["name"]).strip()] = str(entry.get("pin", "")).strip()

    def should_stop():
        return stop is not None and stop()

    def ev(kind, node="", **kw):
        emit({"t": round(st.t, 3), "kind": kind, "node": node, **kw})

    def advance(seconds):
        st.t += seconds
        if realtime and seconds > 0:
            end = time.time() + (seconds / speed)
            while time.time() < end:
                if should_stop():
                    return
                time.sleep(min(0.02, max(0.0, end - time.time())))

    # ---- variables -------------------------------------------------
    def value_of(expr, default=0):
        """A field may be a number, or the name of a Var, or a countdown
        helper like cd1_secs(). Anything else falls back."""
        s = str(expr).strip()
        if not s:
            return default
        if s in st.vars:
            return st.vars[s]
        for cname, c in st.counts.items():
            if s == f"{cname}_secs()":
                return max(0, int((c["end"] - st.t) + 0.999))
            if s == f"{cname}_mins()":
                return max(0, int((c["end"] - st.t) + 0.999)) // 60
            if s == f"{cname}_clock()":
                left = max(0, int((c["end"] - st.t) + 0.999))
                return f"{left//3600:02d}:{(left%3600)//60:02d}:{left%60:02d}"
        return _num(s, default)

    # ---- buttons ---------------------------------------------------
    def drain_presses():
        if not press_queue:
            return
        for name, what in (press_queue() or []):
            b = st.buttons.setdefault(name, {"down": False, "since": 0.0,
                                             "longDone": False, "lastRep": 0.0})
            if what == "down" and not b["down"]:
                b.update(down=True, since=st.t, longDone=False, lastRep=st.t)
                b["edge"] = "press"
            elif what == "up" and b["down"]:
                b["down"] = False
                b["edge"] = "release"

    def button_events(name, p):
        """Same three events the generated C++ produces: tap, hold, repeat."""
        b = st.buttons.setdefault(name, {"down": False, "since": 0.0,
                                         "longDone": False, "lastRep": 0.0})
        long_ms = _num(p.get("long_ms", 700), 700)
        rdelay = _num(p.get("repeat_delay", 450), 450)
        rrate = _num(p.get("repeat_rate", 60), 60)
        tap = hold = rep = False
        edge = b.pop("edge", None)
        if edge == "press":
            rep = True
        elif edge == "release":
            if not b["longDone"]:
                tap = True
        elif b["down"]:
            held = (st.t - b["since"]) * 1000.0
            if not b["longDone"] and held >= long_ms:
                b["longDone"] = True
                hold = True
            if held > rdelay and (st.t - b["lastRep"]) * 1000.0 > rrate:
                b["lastRep"] = st.t
                rep = True
        return tap, hold, rep

    # ---- one node --------------------------------------------------
    def run_node(name):
        spec = nodes_by_name.get(name)
        if not spec:
            return
        t = spec["type"]
        p = spec.get("params", {}) or {}

        if t == "device.servo":
            pin = _resolve_pin(p.get("pin", "9"), pin_map)
            angle = int(_num(value_of(p.get("angle", 90), 90), 90))
            angle = max(0, min(180, angle))
            prev = st.servos.get(pin)
            st.servos[pin] = angle
            st.attached[pin] = True
            ev("servo", name, pin=pin, angle=angle, prev=prev)
            if prev == angle:
                ev("warn", name,
                   msg=f"servo on pin {pin} was already at {angle} degrees — it will not move")
            hold = _num(p.get("hold_ms", 0), 0)
            if hold:
                ev("wait", name, ms=hold)
                advance(hold / 1000.0)
            if p.get("release", False):
                if not hold:
                    advance(0.4)
                st.attached[pin] = False
                ev("servo_release", name, pin=pin,
                   note="PWM cut — the horn can be turned by hand again")

        elif t == "device.pin":
            pin = _resolve_pin(p.get("pin", "13"), pin_map)
            mode = p.get("mode", "digital write")
            if mode in ("digital write", "analog write (PWM)"):
                val = str(p.get("value", "HIGH"))
                st.pins[pin] = val
                ev("pin", name, pin=pin, value=val, mode=mode)
                if st.attached.get(pin):
                    ev("warn", name,
                       msg=f"pin {pin} is also driving a servo — writing it directly fights the servo")
            else:
                into = p.get("into", "reading")
                st.vars[into] = 0
                ev("read", name, pin=pin, into=into, mode=mode)

        elif t == "device.wait":
            ms = _num(p.get("ms", 1000), 0)
            ev("wait", name, ms=ms)
            advance(ms / 1000.0)

        elif t == "device.screen":
            var = str(p.get("show_var", "")).strip()
            txt = str(value_of(var, "")) if var else str(p.get("text", ""))
            st.screen = txt
            sizes = {"small": 2, "medium": 4, "big": 6}
            ev("screen", name, text=txt,
               x=_num(p.get("x", 20), 20), y=_num(p.get("y", 36), 36),
               size=sizes.get(str(p.get("size", "medium")), 4),
               color=str(p.get("color", "white")),
               clear=bool(p.get("clear", True)),
               w=_num(p.get("width", 0), 0), h=_num(p.get("height", 0), 0))

        elif t == "device.backlight":
            state = str(p.get("state", "on"))
            lvl = {"on": 255, "off": 0}.get(state, int(_num(p.get("level", 60), 60)))
            ev("backlight", name, level=lvl,
               pin=_resolve_pin(p.get("pin", "38"), pin_map))

        elif t == "device.random":
            import random as _r
            into = p.get("into", "pick")
            lo, hi = int(_num(p.get("min", 0), 0)), int(_num(p.get("max", 3), 3))
            val = _r.randint(min(lo, hi), max(lo, hi))
            st.vars[into] = val
            ev("random", name, into=into, value=val, min=lo, max=hi)

        elif t == "device.var":
            n_ = str(p.get("name", "count")).strip() or "count"
            if n_ not in st.vars:
                st.vars[n_] = _num(p.get("initial", 0), 0)
            op = p.get("op", "set")
            if op != "nothing":
                v = value_of(p.get("value", 0), 0)
                cur = st.vars.get(n_, 0)
                cur = {"add": cur + v, "subtract": cur - v,
                       "multiply": cur * v,
                       "divide": (cur / v if v else cur)}.get(op, v)
                st.vars[n_] = cur
            lo = str(p.get("min", "")).strip()
            hi = str(p.get("max", "")).strip()
            if lo or hi:
                cur = st.vars[n_]
                lov, hiv = _num(lo, None), _num(hi, None)
                if p.get("wrap", False) and lo and hi:
                    if cur > hiv: cur = lov
                    if cur < lov: cur = hiv
                else:
                    if lo and cur < lov: cur = lov
                    if hi and cur > hiv: cur = hiv
                st.vars[n_] = cur
            ev("var", name, var=n_, op=op, value=st.vars[n_])

        elif t == "device.code":
            # raw C++ -- there is nothing to execute here, but the one
            # line everybody writes is starting a countdown, so honour it
            for line in str(p.get("code", "")).splitlines():
                line = line.strip().rstrip(";")
                for cname in list(st.counts):
                    if line == f"{cname}_start":
                        hrs = value_of(st.counts[cname]["hours"], 0)
                        mins = value_of(st.counts[cname]["minutes"], 0)
                        st.counts[cname].update(
                            end=st.t + hrs * 3600 + mins * 60, fired=False)
                        ev("countdown_start", name, name_=cname,
                           seconds=hrs * 3600 + mins * 60)
            ev("code", name, lines=len(str(p.get("code", "")).splitlines()))

        elif t == "device.encoder":
            into = str(p.get("into", "turn")).strip() or "turn"
            st.vars[into] = 0          # nothing is turning it in here
            ev("read", name, into=into, note="no encoder to turn in a simulation")

        elif t == "device.goto_state":
            nxt = str(p.get("target", "STATE_1")).strip()
            if nxt != st.state:
                ev("state", name, **{"from": st.state, "to": nxt})
            st.state = nxt

        elif t == "device.array_set":
            arr = str(p.get("array", "myList")).strip()
            idx = int(_num(value_of(p.get("index", 0), 0), 0))
            lst = st.arrays.setdefault(arr, [])
            while len(lst) <= idx:
                lst.append(0)
            v = value_of(p.get("value", 0), 0)
            op = str(p.get("op", "set"))
            lst[idx] = {"add": lst[idx] + v, "subtract": lst[idx] - v}.get(op, v)
            ev("array", name, array=arr, index=idx, value=lst[idx])

        elif t == "device.map":
            lo1 = _num(value_of(p.get("from_low", 0), 0), 0)
            hi1 = _num(value_of(p.get("from_high", 1023), 1023), 1023)
            lo2 = _num(value_of(p.get("to_low", 0), 0), 0)
            hi2 = _num(value_of(p.get("to_high", 180), 180), 180)
            x = _num(value_of(p.get("input", 0), 0), 0)
            out = lo2 if hi1 == lo1 else (x - lo1) * (hi2 - lo2) / (hi1 - lo1) + lo2
            if p.get("clamp", True):
                out = max(min(lo2, hi2), min(max(lo2, hi2), out))
            into = str(p.get("into", "mapped")).strip() or "mapped"
            st.vars[into] = int(out)
            ev("var", name, var=into, op="map", value=st.vars[into])

        elif t == "device.servo_move":
            bank = str(p.get("bank", "servos")).strip()
            pins = st.banks.get(bank, [])
            idx = int(_num(value_of(p.get("index", 0), 0), 0))
            if 0 <= idx < len(pins):
                pin = pins[idx]
                angle = max(0, min(180, int(_num(value_of(p.get("angle", 90), 90), 90))))
                prev = st.servos.get(pin)
                st.servos[pin] = angle
                st.attached[pin] = True
                ev("servo", name, pin=pin, angle=angle, prev=prev, bank=bank, index=idx)
                hold = _num(p.get("hold_ms", 0), 0)
                if hold:
                    ev("wait", name, ms=hold)
                    advance(hold / 1000.0)
            else:
                ev("warn", name,
                   msg=f"servo bank {bank!r} has no slot {idx} — nothing moved")

        elif t in DECL_TYPES:
            pass    # declarations / entry points / comments

    # ---- branches --------------------------------------------------
    def branch_port(name):
        """Which ONE output port this branch node takes right now.

        The old simulator had no idea branches existed and ran every
        chain, so an If showed both sides happening at once and a Timer
        fired on every pass. This picks one, like the board does.
        """
        spec = nodes_by_name[name]
        t = spec["type"]
        p = spec.get("params", {}) or {}

        if t == "device.if":
            left = value_of(p.get("left", "0"), 0)
            right = value_of(p.get("right", "0"), 0)
            op = str(p.get("op", "==")).strip()
            try:
                ok = {"==": left == right, "!=": left != right,
                      ">": left > right, "<": left < right,
                      ">=": left >= right, "<=": left <= right}.get(op, False)
            except TypeError:
                ok = False
            return 0 if ok else 1

        if t == "device.timer":
            tname = str(p.get("name", "t1")).strip() or "t1"
            if tname not in st.timers:
                st.timers[tname] = (st.t + _num(value_of(p.get("ms", 1000), 1000), 1000) / 1000.0
                                    if p.get("autostart", True) else float("inf"))
            if st.t >= st.timers[tname]:
                st.timers[tname] = st.t + _num(value_of(p.get("ms", 1000), 1000), 1000) / 1000.0
                return 0
            return 1

        if t == "device.countdown":
            cname = str(p.get("name", "cd1")).strip() or "cd1"
            if cname not in st.counts:
                hrs = value_of(p.get("hours", 0), 0)
                mins = value_of(p.get("minutes", 0), 0)
                st.counts[cname] = {
                    "end": (st.t + hrs * 3600 + mins * 60)
                           if p.get("autostart", True) else float("inf"),
                    "fired": False,
                    "hours": p.get("hours", 0), "minutes": p.get("minutes", 0)}
            c = st.counts[cname]
            if st.t >= c["end"] and not c["fired"]:
                if p.get("rearm", False):
                    hrs = value_of(c["hours"], 0)
                    mins = value_of(c["minutes"], 0)
                    c["end"] = st.t + hrs * 3600 + mins * 60
                else:
                    c["fired"] = True
                return 0
            return 1

        if t == "device.button":
            bname = str(p.get("name", "b1")).strip() or "b1"
            tap, hold, rep = button_events(bname, p)
            if tap:
                return 0
            if hold:
                return 1
            if rep:
                return 2
            return None     # nothing happened this pass
        return 0

    # ---- walking the graph -----------------------------------------
    def run_from(name, visited):
        while name:
            if should_stop() or name in visited:
                return
            visited.add(name)
            spec = nodes_by_name.get(name)
            if not spec:
                return
            t = spec["type"]

            if t == "device.repeat":
                p = spec.get("params", {}) or {}
                times = int(_num(p.get("times", 10), 10))
                body = _targets(name, conns, 0)
                if not body:
                    ev("warn", name, msg="Repeat has nothing wired after it")
                for r in range(max(0, times)):
                    if should_stop():
                        return
                    ev("repeat", name, iteration=r, of=times)
                    for b in body:
                        run_from(b, set(visited))
                return

            if t in BRANCH_TYPES:
                run_node(name)                  # buttons poll here
                port = branch_port(name)
                if port is None:
                    return
                ev("branch", name, port=port,
                   label=PORT_LABELS.get(t, {}).get(port, str(port)))
                for tgt in _targets(name, conns, port):
                    run_from(tgt, set(visited))
                return

            run_node(name)
            nxt = _targets(name, conns, 0)
            name = nxt[0] if nxt else None

    # ---- go --------------------------------------------------------
    # state machine: name -> the State node that owns it
    state_nodes = {}
    for nd in workflow.get("nodes", []):
        if nd["type"] == "device.state":
            nm = str((nd.get("params") or {}).get("name", "STATE_1")).strip()
            state_nodes.setdefault(nm, nd["name"])
    if state_nodes:
        st.state = next(iter(state_nodes))

    # servo banks, so a Servo Move knows which pin a slot means
    for nd in workflow.get("nodes", []):
        if nd["type"] == "device.servo_array":
            pr = nd.get("params") or {}
            bank = str(pr.get("name", "servos")).strip()
            pins = [x.strip() for x in str(pr.get("pins", "")).split(",") if x.strip()]
            st.banks[bank] = [_resolve_pin(x, pin_map) for x in pins]
            start = int(_num(pr.get("start", 0), 0))
            for pin in st.banks[bank]:
                st.servos[pin] = start
        if nd["type"] == "device.array":
            pr = nd.get("params") or {}
            vals = [_num(x, 0) for x in str(pr.get("values", "")).split(",") if x.strip()]
            size = int(_num(pr.get("size", 4), 4))
            st.arrays[str(pr.get("name", "myList")).strip()] = (
                vals + [0] * max(0, size - len(vals)))[:max(size, len(vals))]

    emit({"t": 0.0, "kind": "power_on", "node": "", **board_info(workflow)})

    starts = [n["name"] for n in workflow.get("nodes", []) if n["type"] == "device.on_start"]
    repeats = [n["name"] for n in workflow.get("nodes", []) if n["type"] == "device.on_repeat"]

    if starts:
        ev("phase", phase="setup")
        for s in starts:
            for tgt in _targets(s, conns, 0):
                run_from(tgt, set())

    if not starts and not repeats:
        ev("warn", msg="no On Start or On Repeat node — running everything as loop()")
        roots = [n["name"] for n in workflow.get("nodes", [])
                 if n["name"] not in {l["to"] for ls in conns.values() for l in ls}]
        repeats_body = roots[:1]
    elif repeats:
        repeats_body = None
    else:
        ev("warn", msg="nothing wired to 'On Repeat' — after setup the board just sits there")
        ev("end")
        return st

    ev("phase", phase="loop")
    n = 0
    while max_loops is None or n < max_loops:
        if should_stop():
            break
        st.loop_count = n
        drain_presses()
        before = st.t
        if state_nodes:
            # codegen turns State nodes into a switch that REPLACES the
            # loop body, so the simulation has to do the same or it
            # would run every state at once
            cur = state_nodes.get(st.state)
            if cur is None:
                ev("warn", msg=f"no State node named {st.state!r}")
            else:
                for tgt in _targets(cur, conns, 0):
                    run_from(tgt, set())
        elif repeats_body is None:
            for r in repeats:
                for tgt in _targets(r, conns, 0):
                    run_from(tgt, set())
        else:
            for b in repeats_body:
                run_from(b, set())
        # a pass that waited on nothing still costs time on a real board;
        # without this the clock never moves and no timer ever comes due
        if st.t == before:
            advance(idle_ms / 1000.0)
        n += 1

    ev("end")
    return st
