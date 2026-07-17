"""
simulate.py — run a robotics graph virtually, like the board would.

Instead of compiling to C++ and flashing, this walks the SAME graph in Python
and pretends to be the microcontroller:

    setup()  -> the 'On Start' chain, once
    loop()   -> the 'On Repeat' chain, over and over

Every action a node takes is reported as an event with a virtual timestamp, so
you can watch the sketch run in real time and catch mistakes (a servo told to
go to the same angle twice, a missing delay, an empty Repeat) without ever
plugging in hardware.

Events look like:
    {"t": 1.0, "kind": "servo", "pin": "9", "angle": 90, "node": "Servo 2"}
    {"t": 1.0, "kind": "wait",  "ms": 1000,             "node": "Wait 7"}
    {"t": 2.0, "kind": "pin",   "pin": "13", "value": "HIGH", "node": "Led"}
    {"t": 2.0, "kind": "screen","text": "READY",        "node": "Splash"}
    {"t": 2.0, "kind": "warn",  "msg": "..." }

`realtime=True` makes it actually sleep for delays so you watch it unfold at
the speed the board would run it.
"""
import time


class SimState:
    """The virtual board: pin values, servo angles, variables, the clock."""
    def __init__(self):
        self.t = 0.0            # virtual seconds since power-on
        self.servos = {}        # pin -> angle
        self.pins = {}          # pin -> value
        self.vars = {}          # variable name -> value
        self.screen = ""
        self.loop_count = 0


def _chain_from(start, conns):
    order, seen = [], {start}
    stack = [l["to"] for l in conns.get(start, [])]
    while stack:
        cur = stack.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        order.append(cur)
        for l in conns.get(cur, []):
            if l["to"] not in seen:
                stack.append(l["to"])
    return order


def _all_order(workflow):
    nodes = [n["name"] for n in workflow.get("nodes", [])]
    conns = workflow.get("connections", {})
    incoming = {l["to"] for links in conns.values() for l in links}
    starts = [n for n in nodes if n not in incoming] or nodes[:1]
    order, seen = [], set()
    stack = list(reversed(starts))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur); order.append(cur)
        for l in conns.get(cur, []):
            if l["to"] not in seen:
                stack.append(l["to"])
    return order


def _resolve_pin(raw, pin_map):
    """A node's pin field may be a NAME declared in the Pins node."""
    raw = str(raw).strip()
    return pin_map.get(raw, raw)


def simulate(workflow, emit, max_loops=None, realtime=False, stop=None):
    """Run the graph. `emit(event)` is called for everything that happens.

    max_loops : how many times to run the loop() body (None = forever)
    realtime  : actually sleep during delays, so it plays at real speed
    stop      : a callable returning True to abort (used by the UI's stop button)
    """
    nodes_by_name = {n["name"]: n for n in workflow.get("nodes", [])}
    conns = workflow.get("connections", {})
    st = SimState()

    # ---- pin map from the Pins node ----
    pin_map = {}
    for n in workflow.get("nodes", []):
        if n["type"] == "device.pins":
            for entry in (n.get("params", {}).get("pins") or []):
                if isinstance(entry, dict) and entry.get("name"):
                    pin_map[str(entry["name"]).strip()] = str(entry.get("pin", "")).strip()

    def should_stop():
        return stop is not None and stop()

    def advance(seconds):
        st.t += seconds
        if realtime and seconds > 0:
            # sleep in slices so a stop request is responsive
            end = time.time() + seconds
            while time.time() < end:
                if should_stop():
                    return
                time.sleep(min(0.05, max(0.0, end - time.time())))

    def ev(kind, node, **kw):
        emit({"t": round(st.t, 3), "kind": kind, "node": node, **kw})

    # ---- run one node ----
    def run_node(name):
        spec = nodes_by_name.get(name)
        if not spec:
            return
        t = spec["type"]
        p = spec.get("params", {}) or {}

        if t == "device.servo":
            pin = _resolve_pin(p.get("pin", "9"), pin_map)
            try: angle = int(float(p.get("angle", 90)))
            except (TypeError, ValueError): angle = 90
            prev = st.servos.get(pin)
            st.servos[pin] = angle
            ev("servo", name, pin=pin, angle=angle, prev=prev)
            if prev == angle:
                ev("warn", name,
                   msg=f"servo on pin {pin} was already at {angle}° — it won't move")
            try: hold = float(p.get("hold_ms", 0) or 0)
            except (TypeError, ValueError): hold = 0
            if hold:
                ev("wait", name, ms=hold)
                advance(hold / 1000.0)

        elif t == "device.pin":
            pin = _resolve_pin(p.get("pin", "13"), pin_map)
            mode = p.get("mode", "digital write")
            if mode in ("digital write", "analog write (PWM)"):
                val = str(p.get("value", "HIGH"))
                st.pins[pin] = val
                ev("pin", name, pin=pin, value=val, mode=mode)
                if pin in st.servos:
                    ev("warn", name,
                       msg=f"pin {pin} is also driving a servo — writing to it directly will fight the servo")
            else:
                # a read: we have no real world, so report it as unknown
                into = p.get("into", "reading")
                st.vars[into] = 0
                ev("read", name, pin=pin, into=into, mode=mode)

        elif t == "device.wait":
            try: ms = float(p.get("ms", 1000) or 0)
            except (TypeError, ValueError): ms = 0
            ev("wait", name, ms=ms)
            advance(ms / 1000.0)

        elif t == "device.screen":
            var = str(p.get("show_var", "")).strip()
            txt = str(st.vars.get(var, "")) if var else str(p.get("text", ""))
            st.screen = txt
            ev("screen", name, text=txt)

        elif t == "device.random":
            import random as _r
            into = p.get("into", "pick")
            try: lo = int(float(p.get("min", 0))); hi = int(float(p.get("max", 3)))
            except (TypeError, ValueError): lo, hi = 0, 3
            val = _r.randint(lo, hi)
            st.vars[into] = val
            ev("random", name, into=into, value=val, min=lo, max=hi)

        elif t == "device.var":
            n_ = p.get("name", "count")
            op = p.get("op", "set")
            try: v = float(p.get("value", 0))
            except (TypeError, ValueError): v = 0
            v = int(v) if v == int(v) else v
            cur = st.vars.get(n_, 0)
            if op == "add": cur = cur + v
            elif op == "subtract": cur = cur - v
            else: cur = v
            st.vars[n_] = cur
            ev("var", name, var=n_, op=op, value=cur)

        elif t == "device.button":
            pin = _resolve_pin(p.get("pin", "4"), pin_map)
            if p.get("wait_for_press", True):
                # in a simulation there's nobody to press it — we auto-press
                # after a beat, and say so, rather than hanging forever.
                ev("button", name, pin=pin, note="simulated press")
                advance(0.5)
            else:
                st.vars[p.get("into", "btn")] = 0
                ev("read", name, pin=pin, into=p.get("into", "btn"))

        elif t in ("device.pins", "device.on_start", "device.on_repeat"):
            pass    # declarations / entry points, nothing happens

    # ---- run a chain, honouring Repeat blocks ----
    def run_chain(names):
        i = 0
        while i < len(names):
            if should_stop():
                return
            name = names[i]
            spec = nodes_by_name.get(name)
            if spec and spec["type"] == "device.repeat":
                p = spec.get("params", {}) or {}
                try: times = int(float(str(p.get("times", 10)).strip()))
                except (TypeError, ValueError): times = 10
                body = names[i + 1:]           # everything after it is the body
                if not body:
                    ev("warn", name, msg="Repeat has nothing wired after it — it does nothing")
                for r in range(max(0, times)):
                    if should_stop():
                        return
                    ev("repeat", name, iteration=r, of=times)
                    for b in body:
                        if should_stop():
                            return
                        run_node(b)
                return      # the body was consumed by the repeat
            run_node(name)
            i += 1

    # ---- figure out setup vs loop ----
    starts = [n["name"] for n in workflow.get("nodes", []) if n["type"] == "device.on_start"]
    repeats = [n["name"] for n in workflow.get("nodes", []) if n["type"] == "device.on_repeat"]

    emit({"t": 0.0, "kind": "power_on", "node": ""})

    if not starts and not repeats:
        # no trigger nodes: everything behaves like loop()
        body = _all_order(workflow)
        emit({"t": 0.0, "kind": "phase", "node": "", "phase": "loop"})
        n = 0
        while max_loops is None or n < max_loops:
            if should_stop():
                break
            st.loop_count = n
            emit({"t": round(st.t, 3), "kind": "loop_start", "node": "", "n": n})
            run_chain(body)
            n += 1
        emit({"t": round(st.t, 3), "kind": "end", "node": ""})
        return st

    if starts:
        emit({"t": 0.0, "kind": "phase", "node": "", "phase": "setup"})
        for s in starts:
            run_chain(_chain_from(s, conns))

    if not repeats:
        emit({"t": round(st.t, 3), "kind": "warn", "node": "",
              "msg": "nothing wired to 'On Repeat' — after setup the board just sits there"})
        emit({"t": round(st.t, 3), "kind": "end", "node": ""})
        return st

    emit({"t": round(st.t, 3), "kind": "phase", "node": "", "phase": "loop"})
    n = 0
    while max_loops is None or n < max_loops:
        if should_stop():
            break
        st.loop_count = n
        emit({"t": round(st.t, 3), "kind": "loop_start", "node": "", "n": n})
        for r in repeats:
            run_chain(_chain_from(r, conns))
        n += 1

    emit({"t": round(st.t, 3), "kind": "end", "node": ""})
    return st
