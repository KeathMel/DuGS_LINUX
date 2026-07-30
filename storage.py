"""
storage.py — local filesystem read/write for projects (workflows) and tabels
(spreadsheets). Pure file I/O, no Qt imports here on purpose.
"""
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(HERE, "projects")
TABELS_DIR = os.path.join(HERE, "tabels")
CREDENTIALS_DIR = os.path.join(HERE, "credentials")
MEMORY_DIR = os.path.join(HERE, "memory_banks")
DOWNLOADS = os.path.expanduser("~/Downloads")


def _ensure(d):
    os.makedirs(d, exist_ok=True)


def _list(d):
    _ensure(d)
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))


def _path(d, name):
    return os.path.join(d, f"{name}.json")


def _load(d, name):
    with open(_path(d, name)) as f:
        return json.load(f)


def _save(d, name, data):
    _ensure(d)
    with open(_path(d, name), "w") as f:
        json.dump(data, f, indent=2)


def list_projects(): return _list(PROJECTS_DIR)
def load_project(n): return _load(PROJECTS_DIR, n)
def save_project(n, d): _save(PROJECTS_DIR, n, d)


# ---- project kind: "normal" (runs in the engine) or "servo" (generates
#      Arduino code instead of running). Stored in the project JSON.
def project_kind(n):
    """Return 'normal' or 'servo' for a saved project."""
    try:
        d = _load(PROJECTS_DIR, n)
        return d.get("kind", "normal")
    except Exception:
        return "normal"


# where generated .ino sketches get written
SKETCHES_DIR = os.path.join(HERE, "sketches")


def save_sketch(name, code):
    """Write a generated Arduino sketch. Arduino requires the .ino file to sit
    in a folder of the same name, so we make sketches/<name>/<name>.ino"""
    _ensure(SKETCHES_DIR)
    folder = os.path.join(SKETCHES_DIR, name)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}.ino")
    with open(path, "w") as f:
        f.write(code)
    return path


def list_tabels(): return _list(TABELS_DIR)
def load_tabel(n): return _load(TABELS_DIR, n)


def save_tabel(n, d):
    for i, row in enumerate(d.get("rows", []), start=1):
        row["id"] = i
    _save(TABELS_DIR, n, d)


# ---- credentials: named secrets (e.g. a DeepSeek token) reusable by nodes ----
def list_credentials(): return _list(CREDENTIALS_DIR)
def load_credential(n): return _load(CREDENTIALS_DIR, n)
def save_credential(n, d): _save(CREDENTIALS_DIR, n, d)


def delete_credential(n):
    p = _path(CREDENTIALS_DIR, n)
    if os.path.exists(p):
        os.remove(p)


# ---- UI layout state (panel sizes etc.), so the window remembers itself ----
_UI_STATE = os.path.join(HERE, "ui_state.json")


def load_ui_state():
    try:
        with open(_UI_STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_ui_state(d):
    try:
        with open(_UI_STATE, "w") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass


def new_tabel(n):
    save_tabel(n, {"name": n, "columns": ["column1"], "rows": []})


# ---- memory banks -------------------------------------------------------
# A memory bank is a small key/value store the AI/workflow can save things
# into, like a Tabel but simpler: each key holds a value plus optional
# expiry. Stored as plain JSON files so it works anywhere, no database.
import time as _time


def list_memory_banks():
    return _list(MEMORY_DIR)


def load_memory_bank(n):
    try:
        return _load(MEMORY_DIR, n)
    except Exception:
        return {"name": n, "entries": {}}


def save_memory_bank(n, d):
    _ensure(MEMORY_DIR)
    _save(MEMORY_DIR, n, d)


def new_memory_bank(n):
    save_memory_bank(n, {"name": n, "entries": {}})


def delete_memory_bank(n):
    try:
        os.remove(_path(MEMORY_DIR, n))
    except Exception:
        pass


def _bank_alive(entry):
    """An entry is alive if it has no expiry, or its expiry is still ahead."""
    exp = entry.get("expires_at")
    return exp is None or exp > _time.time()


def memory_get(bank, key):
    """Read one key, honouring expiry. Returns None if missing or expired."""
    d = load_memory_bank(bank)
    entry = (d.get("entries") or {}).get(key)
    if entry is None or not _bank_alive(entry):
        return None
    return entry.get("value")


def memory_all(bank):
    """Every live key/value in the bank, dropping expired ones as we go."""
    d = load_memory_bank(bank)
    entries = d.get("entries") or {}
    out, changed = {}, False
    for k, e in list(entries.items()):
        if _bank_alive(e):
            out[k] = e.get("value")
        else:
            del entries[k]; changed = True
    if changed:
        save_memory_bank(bank, d)
    return out


def memory_set(bank, key, value, ttl_seconds=None, append=False):
    """Write a key. ttl_seconds=None means it never expires. append=True keeps
    the old value and adds to it (list or string) instead of overwriting."""
    d = load_memory_bank(bank)
    entries = d.setdefault("entries", {})
    expires = (_time.time() + ttl_seconds) if ttl_seconds else None
    if append and key in entries and _bank_alive(entries[key]):
        old = entries[key].get("value")
        if isinstance(old, list):
            value = old + (value if isinstance(value, list) else [value])
        else:
            value = f"{old}\n{value}"
    entries[key] = {"value": value, "expires_at": expires,
                    "updated_at": _time.time()}
    save_memory_bank(bank, d)
    return value


# ---- deploy: copying a workflow into a runner's projects/ folder ----------
# The runner (DuGS_Runner container) watches a projects/ folder and runs
# whatever lands there. "Deploy" just copies a project's JSON into that folder;
# the runner picks it up within a few seconds on its own. We remember the
# folder path so the person only points at it once.
def deploy_path():
    """The runner's projects/ folder the app deploys into, or '' if unset."""
    return load_ui_state().get("deploy_path", "")


def set_deploy_path(path):
    st = load_ui_state()
    st["deploy_path"] = path or ""
    save_ui_state(st)


def list_deployed():
    """Names of projects currently sitting in the runner's folder."""
    p = deploy_path()
    if not p or not os.path.isdir(p):
        return []
    return sorted(f[:-5] for f in os.listdir(p) if f.endswith(".json"))


# ---- deployed-state registry ---------------------------------------------
# is_deployed() used to re-derive the answer by checking the filesystem every
# time (deploy_path() + does the file exist). That re-check could disagree
# with what Deploy/Undeploy just did — different working directory, a stale
# deploy_path, timing — so the button and the green name could drift out of
# sync with each other and with reality.
#
# Now the editor's Deploy/Undeploy actions are the single source of truth:
# they explicitly mark a project deployed or not, right here, at the moment
# it happens. is_deployed() just reads that record — no re-derivation, so it
# can't disagree with the button that changed it.
def mark_deployed(name, deployed=True):
    st = load_ui_state()
    deployed_set = set(st.get("deployed_projects", []))
    if deployed:
        deployed_set.add(name)
    else:
        deployed_set.discard(name)
    st["deployed_projects"] = sorted(deployed_set)
    save_ui_state(st)


def is_deployed(name):
    st = load_ui_state()
    return name in set(st.get("deployed_projects", []))


def deploy_project(name):
    """Copy a saved project into the runner's folder. Returns the path written.
    Raises if no deploy path is set or it doesn't exist, so the caller can ask
    the person to point at the folder."""
    p = deploy_path()
    if not p:
        raise RuntimeError("no deploy folder set")
    if not os.path.isdir(p):
        raise RuntimeError(f"deploy folder not found: {p}")
    data = load_project(name)          # the current saved version
    dest = os.path.join(p, f"{name}.json")
    with open(dest, "w") as f:
        json.dump(data, f, indent=2)
    mark_deployed(name, True)
    return dest


def undeploy_project(name):
    """Remove a project from the runner's folder. The runner stops running it
    within a few seconds (its auto-reload notices the file is gone)."""
    p = deploy_path()
    if p:
        dest = os.path.join(p, f"{name}.json")
        if os.path.isfile(dest):
            os.remove(dest)
    mark_deployed(name, False)


def sync_deployed_from_disk():
    """One-time reconciliation: whatever is actually sitting in the runner's
    folder becomes the tracked deployed set. Covers upgrading from the old
    filesystem-check version, or the folder being edited by hand outside
    the app."""
    on_disk = set(list_deployed())
    st = load_ui_state()
    st["deployed_projects"] = sorted(on_disk)
    save_ui_state(st)
    return on_disk


def export_project(name, dest_path):
    """Write a project's JSON to any path the person chose (the Download
    button), so they can move a workflow to another machine by hand."""
    data = load_project(name)
    with open(dest_path, "w") as f:
        json.dump(data, f, indent=2)
    return dest_path


# ---- run log: the runner's history of every run it has done ---------------
# The runner writes one file per run into its runs/ folder, sitting right next
# to its projects/ folder — same idea as deploy. We remember the runner's
# base folder once (same value as deploy_path, since runs/ and projects/ are
# siblings inside it) and read whatever's in runs/.
def runs_path():
    """The runner's runs/ folder, derived from the deploy path (they're
    siblings: <runner>/projects and <runner>/runs)."""
    dp = deploy_path()
    if not dp:
        return ""
    # deploy_path points AT the projects/ folder itself; runs/ is next to it
    base = os.path.dirname(dp.rstrip("/\\"))
    return os.path.join(base, "runs")


def set_runs_path_from_base(base_folder):
    """Point the deploy path at <base_folder>/projects, so runs_path() can
    derive <base_folder>/runs from it. Used by the run-log scan/browse dialog
    when the person points at the runner's root folder instead of projects/
    directly."""
    set_deploy_path(os.path.join(base_folder, "projects"))


def list_runs(limit=200):
    """Every run record, most recent first. Each is the parsed JSON the
    runner wrote — workflow name, timestamp, duration, input, result, error."""
    p = runs_path()
    if not p or not os.path.isdir(p):
        return []
    files = sorted(
        (f for f in os.listdir(p) if f.endswith(".json")),
        reverse=True,   # filenames start with name__TIMESTAMP, so this isn't
    )                    # perfectly chronological across workflows; re-sort below
    out = []
    for f in files[:limit * 2]:   # a little slack before trimming to `limit`
        try:
            with open(os.path.join(p, f)) as fh:
                rec = json.load(fh)
            rec["_file"] = f
            out.append(rec)
        except Exception:
            continue
    out.sort(key=lambda r: r.get("ran_at", ""), reverse=True)
    return out[:limit]
