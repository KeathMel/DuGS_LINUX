"""
home_screen.py — the landing screen: Projects | Tabels tabs, each backed by an
icon-grid file browser with right-click Open/Download/Duplicate/Rename/Delete.

This screen has its own small, self-contained theme (grey background, white
accents by default) that the user can customize from the gear icon in the
bottom-left corner: button/accent color, logo color, and an optional
background image. Settings are stored in home_ui_settings.json next to this
file and survive restarts.
"""
import os
import json
import shutil
import weakref

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QStackedWidget, QInputDialog, QMenu, QMessageBox, QLineEdit,
    QDialog, QColorDialog, QFileDialog, QSlider, QFrame, QSizePolicy, QComboBox,
    QScrollArea
)
from PyQt6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QPainterPath, QIcon, QPixmap, QAction

from home_preview import PreviewPane
from storage import (
    PROJECTS_DIR, TABELS_DIR, DOWNLOADS, _ensure, _path,
    list_projects, list_tabels, save_project, new_tabel,
    list_credentials, load_credential, save_credential, delete_credential,
    project_kind,
)


SERVO_RED = "#ff6b6b"
NORMAL_ICON_BLUE = "#7ecfff"   # fixed color for normal (non-servo) file icons —
                               # independent of the customizable button/accent color

# --- Home screen theme (independent of the app-wide theme.py accent) -------
GREY_BG = "#3a3a3a"        # flat background when no image is set
GREY_PANEL = "#333333"     # slightly darker, used for dialogs
DEFAULT_BUTTON_COLOR = "#ffffff"
DEFAULT_LOGO_COLOR = NORMAL_ICON_BLUE   # logo defaults to the same blue as normal icons

HOME_UI_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "home_ui_settings.json")
DEFAULT_HOME_UI_SETTINGS = {
    "button_color": DEFAULT_BUTTON_COLOR,
    "logo_color": DEFAULT_LOGO_COLOR,
    "bg_image": None,        # absolute path to an image, or None for flat grey
    "bg_transparent": False, # True = no background painted at all (see-through)
    # --- workflow/canvas (editor.py + canvas.py) ---
    "canvas_dots": True,          # n8n-style dot grid on the canvas
    "canvas_bg_image": None,      # absolute path to a canvas background image
    "canvas_no_background": False,  # True = see-through everywhere, dark fog
    "panel_color": None,          # user-picked panel/canvas background colour
    "fog_opacity": 150,           # how dark the fog is when see-through (0-255)
    "node_size": 84,              # canvas node square, in px
    "wire_snap": 16,              # how close a dragged wire grabs a port, in px
    # --- text ---
    "node_text_scale": 1.0,       # text inside the node popup
    "panel_text_scale": 1.0,      # text in the panels/modules around the canvas
    # --- behaviour ---
    "autosave_enabled": True,     # False = the editor never autosaves
}


# ---- text scale ---------------------------------------------------------
# Two multipliers, because the two places text lives want different sizes: the
# node popup is a form you read up close, the panels around the canvas are
# chrome you glance at. Each piece keeps its own relative size within its
# group — widgets call fs(9)/pfs(11) instead of hard-coding a number.
_NODE_TEXT_SCALE = 1.0
_PANEL_TEXT_SCALE = 1.0


def _clamp_scale(mult):
    try:
        return max(0.6, min(3.0, float(mult)))
    except (TypeError, ValueError):
        return 1.0


def set_node_text_scale(mult):
    global _NODE_TEXT_SCALE
    _NODE_TEXT_SCALE = _clamp_scale(mult)


def set_panel_text_scale(mult):
    global _PANEL_TEXT_SCALE
    _PANEL_TEXT_SCALE = _clamp_scale(mult)


def node_text_scale():
    return _NODE_TEXT_SCALE


def panel_text_scale():
    return _PANEL_TEXT_SCALE


def fs(base):
    """A font size in px for the NODE POPUP, with its multiplier applied.
    Never smaller than 6px so nothing vanishes."""
    return max(6, round(base * _NODE_TEXT_SCALE))


def pfs(base):
    """A font size in px for the PANELS around the canvas."""
    return max(6, round(base * _PANEL_TEXT_SCALE))


# kept so anything still importing the old names keeps working
text_scale = node_text_scale
set_text_scale = set_node_text_scale


def node_size():
    """Canvas node square in px. Read live so the slider takes effect on the
    next repaint rather than needing a restart."""
    try:
        return max(40, min(200, int(load_home_ui_settings().get("node_size", 84))))
    except Exception:
        return 84


def autosave_enabled():
    """False means the editor never saves on its own — Save is the only way
    a change reaches disk."""
    try:
        return bool(load_home_ui_settings().get("autosave_enabled", True))
    except Exception:
        return True


def wire_snap():
    """How close, in px, a dragged wire has to get before it grabs a port."""
    try:
        return max(4, min(60, int(load_home_ui_settings().get("wire_snap", 16))))
    except Exception:
        return 16


def load_home_ui_settings():
    data = {}
    try:
        with open(HOME_UI_SETTINGS_PATH, "r") as f:
            data = json.load(f)
    except Exception:
        pass
    settings = dict(DEFAULT_HOME_UI_SETTINGS)
    if isinstance(data, dict):
        settings.update({k: v for k, v in data.items() if k in DEFAULT_HOME_UI_SETTINGS})
        # one text_scale used to cover the node popup only — carry an existing
        # setting over to the node slider rather than silently resetting it
        if "text_scale" in data and "node_text_scale" not in data:
            settings["node_text_scale"] = data["text_scale"]
    # keep the multipliers in step with what's saved
    set_node_text_scale(settings.get("node_text_scale", 1.0))
    set_panel_text_scale(settings.get("panel_text_scale", 1.0))
    return settings


def save_home_ui_settings(settings):
    try:
        with open(HOME_UI_SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass


# --- Live theme broadcast ---------------------------------------------------
# Any screen that wants to follow the shared skin (Home, TabelEditor, ...)
# registers itself here. When the settings popup saves, every registered
# screen gets its settings reloaded from disk and apply_theme() re-run —
# so changing the color/background in one place updates ALL open screens
# immediately, not just the one that happened to open the popup.
_themed_screens = []


def register_themed_screen(widget):
    """Call once from a screen's __init__ (after its own apply_theme()) to
    have it follow live settings updates from the settings popup."""
    _themed_screens.append(weakref.ref(widget))


def broadcast_theme_update():
    """Reload settings from disk and re-apply the theme on every registered,
    still-alive screen. Called after the settings popup saves."""
    alive = []
    fresh = load_home_ui_settings()
    for ref in _themed_screens:
        widget = ref()
        if widget is None:
            continue
        try:
            widget.settings = fresh
            widget.apply_theme()
        except Exception:
            pass
        alive.append(ref)
    _themed_screens[:] = alive


def file_icon(size=64, color=None):
    color = color or DEFAULT_BUTTON_COLOR
    pm = QPixmap(size, size); pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = size * 0.62, size * 0.8
    x, y = (size - w) / 2, (size - h) / 2
    fold = size * 0.22
    path = QPainterPath()
    path.moveTo(x, y)
    path.lineTo(x + w - fold, y)
    path.lineTo(x + w, y + fold)
    path.lineTo(x + w, y + h)
    path.lineTo(x, y + h)
    path.closeSubpath()
    fill = QColor(34, 20, 20, 200) if color == SERVO_RED else QColor(40, 40, 40, 200)
    p.setPen(QPen(QColor(color), 2)); p.setBrush(QBrush(fill))
    p.drawPath(path)
    p.setPen(QPen(QColor(color), 1.5))
    p.drawLine(int(x + w - fold), int(y), int(x + w - fold), int(y + fold))
    p.drawLine(int(x + w - fold), int(y + fold), int(x + w), int(y + fold))
    p.end()
    return QIcon(pm)


class IconBrowser(QWidget):
    """File-manager style grid of icons with right-click menu. Used for both
       Projects and Tabels."""
    def __init__(self, kind, app, accent=None):
        super().__init__()
        self.kind = kind            # "project" or "tabel"
        self.app = app
        self.accent = accent or DEFAULT_BUTTON_COLOR
        # Normal-node icons always stay blue and servo icons always stay red —
        # both are fixed/independent of the customizable button/accent color.
        self._icon = file_icon(64, NORMAL_ICON_BLUE)
        self._icon_servo = file_icon(64, SERVO_RED)
        # memory banks share the file look but in the accent colour so they read
        # as a different thing from tabels in the combined Data view
        self._icon_memory = file_icon(64, accent or DEFAULT_BUTTON_COLOR)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.grid_host = QListWidget()
        self.grid_host.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid_host.setIconSize(QSize(64, 64))
        self.grid_host.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid_host.setSpacing(18)
        self.grid_host.setMovement(QListWidget.Movement.Static)
        self.grid_host.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.grid_host.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid_host.customContextMenuRequested.connect(self.menu)
        self.grid_host.itemDoubleClicked.connect(lambda it: self.open(it.text()))
        self.grid_host.setStyleSheet(self._list_style())
        lay.addWidget(self.grid_host)

    def _list_style(self):
        return (
            "QListWidget{background:transparent;border:none;}"
            # no color here on purpose — a stylesheet color rule beats
            # setForeground() every time, which is exactly why deployed
            # projects never turned green: this rule silently overwrote it.
            # setForeground() in _add_item is the only thing setting colour now.
            f"QListWidget::item:selected{{color:{self.accent};background:rgba(255,255,255,0.10);border-radius:4px;}}"
        )

    def set_accent(self, color):
        # Only the selection highlight follows the accent color — the file
        # icons themselves are fixed (blue for normal, red for servo).
        self.accent = color
        self.grid_host.setStyleSheet(self._list_style())
        self.refresh()

    def names(self):
        if self.kind == "project":
            return list_projects()
        if self.kind == "memory":
            from storage import list_memory_banks
            return list_memory_banks()
        return list_tabels()

    def refresh(self):
        self.grid_host.clear()
        if self.kind == "data":
            # one combined view of Tabels + Memory banks, each item tagged with
            # its real kind so open/delete/icon still do the right thing —
            # exactly how Projects folds Normal and Servo into one grid.
            from storage import list_memory_banks
            for n in list_tabels():
                self._add_item(n, "tabel")
            for n in list_memory_banks():
                self._add_item(n, "memory")
            return
        for n in self.names():
            is_servo = (self.kind == "project" and project_kind(n) == "servo")
            self._add_item(n, "servo" if is_servo else self.kind)

    def _add_item(self, name, item_kind):
        # colour: servo=red, memory=accent-ish, everything else the normal icon
        if item_kind == "servo":
            icon = self._icon_servo
        elif item_kind == "memory":
            icon = self._icon_memory
        else:
            icon = self._icon
        it = QListWidgetItem(icon, name)
        it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        it.setSizeHint(QSize(96, 96))
        it.setData(Qt.ItemDataRole.UserRole, item_kind)   # remember what it is
        # explicit default colour, now that the stylesheet no longer sets one
        # (a stylesheet colour rule would silently beat any setForeground call
        # below, which is exactly the bug that stopped deployed names from
        # ever turning green)
        it.setForeground(QColor("#ddd"))
        if item_kind == "servo":
            it.setForeground(QColor(SERVO_RED))
        # a deployed project (sitting in the runner's folder) shows GREEN, so
        # you can see at a glance what's running on the server
        if item_kind == "project":
            try:
                from storage import is_deployed
                if is_deployed(name):
                    it.setForeground(QColor("#4ccf6a"))
                    it.setToolTip("deployed — running on the runner")
            except Exception:
                pass
        self.grid_host.addItem(it)

    def menu(self, pos):
        it = self.grid_host.itemAt(pos)
        if not it: return
        # right-clicking an item outside the current selection replaces it;
        # right-clicking one that's already part of a multi-selection keeps
        # the whole selection so the menu acts on all of it.
        if it not in self.grid_host.selectedItems():
            self.grid_host.clearSelection()
            it.setSelected(True)
        names = [i.text() for i in self.grid_host.selectedItems()]
        if not names:
            return
        multi = len(names) > 1
        m = QMenu(self)
        for label in ("Open", "Download", "Duplicate", "Rename", "Delete"):
            if multi and label in ("Open", "Rename"):
                continue   # only make sense for a single item
            text = f"{label} ({len(names)})" if multi else label
            act = QAction(text, self)
            act.triggered.connect(lambda _=False, l=label, ns=list(names): self.action(l, ns))
            m.addAction(act)
        m.exec(self.grid_host.mapToGlobal(pos))

    def _dir_of(self, name):
        """Which storage folder an item lives in, respecting its kind so the
        combined Data view can hold both tabels and memory banks."""
        from storage import MEMORY_DIR
        k = self._kind_of(name)
        if k == "project":
            return PROJECTS_DIR
        if k == "memory":
            return MEMORY_DIR
        return TABELS_DIR

    def action(self, label, names):
        """Runs one action on one or more selected items at once
        (download/duplicate/delete all support a batch; open/rename only
        make sense for a single item)."""
        d = self._dir_of(names[0]) if names else TABELS_DIR
        if label == "Open":
            if names: self.open(names[0])
        elif label == "Download":
            _ensure(DOWNLOADS)
            ok = 0
            for name in names:
                try:
                    shutil.copy(_path(d, name), os.path.join(DOWNLOADS, f"{name}.json"))
                    ok += 1
                except Exception:
                    pass
            word = "file" if ok == 1 else "files"
            self.app.toast(f"downloaded {ok} {word} to ~/Downloads")
        elif label == "Duplicate":
            existing = set(self.names())
            for name in names:
                base = f"{name}_copy"; i = 1; cand = base
                while cand in existing: i += 1; cand = f"{base}{i}"
                try:
                    shutil.copy(_path(d, name), _path(d, cand))
                    existing.add(cand)
                except Exception:
                    pass
            self.refresh()
        elif label == "Rename":
            if not names: return
            name = names[0]
            new, ok = QInputDialog.getText(self, "Rename", "New name:", text=name)
            if ok and new.strip() and new.strip() != name:
                os.rename(_path(d, name), _path(d, new.strip())); self.refresh()
        elif label == "Delete":
            if len(names) == 1:
                question = f"Delete '{names[0]}'?"
            else:
                question = f"Delete {len(names)} selected items?\n\n" + "\n".join(names)
            if QMessageBox.question(self, "Delete", question) == QMessageBox.StandardButton.Yes:
                for name in names:
                    try:
                        os.remove(_path(d, name))
                    except Exception:
                        pass
                self.refresh()

    def _kind_of(self, name):
        """In the combined Data view each item knows if it's a tabel or a
        memory bank; elsewhere the browser's own kind applies."""
        if self.kind != "data":
            return self.kind
        for i in range(self.grid_host.count()):
            it = self.grid_host.item(i)
            if it.text() == name:
                return it.data(Qt.ItemDataRole.UserRole) or "tabel"
        return "tabel"

    def open(self, name):
        k = self._kind_of(name)
        if k == "project": self.app.open_project(name)
        elif k == "memory": self.app.open_memory(name)
        else: self.app.open_tabel(name)


CRED_TYPES = {
    # Adding a service is one entry here — the panel builds the form from it,
    # so nothing below this dict needs touching.
    #
    # 'token' is the key every existing node already looks for first, so
    # whichever field holds the thing a node needs should keep that key.
    "api_token": {
        "label": "API token (generic)",
        "fields": [
            {"key": "token", "label": "TOKEN", "secret": True,
             "placeholder": "paste the token"},
        ],
    },
    "openai_compatible": {
        "label": "OpenAI-compatible (DeepSeek, OpenRouter, OpenAI…)",
        "fields": [
            {"key": "token", "label": "API KEY", "secret": True,
             "placeholder": "sk-…"},
            {"key": "base_url", "label": "BASE URL", "secret": False,
             "default": "https://api.openai.com/v1",
             "placeholder": "https://openrouter.ai/api/v1"},
            {"key": "model", "label": "DEFAULT MODEL (optional)", "secret": False,
             "placeholder": "deepseek-chat"},
        ],
    },
    "discord_webhook": {
        "label": "Discord webhook",
        "fields": [
            {"key": "token", "label": "WEBHOOK URL", "secret": True,
             "placeholder": "https://discord.com/api/webhooks/…"},
            {"key": "username", "label": "OVERRIDE USERNAME (optional)",
             "secret": False, "placeholder": "DuGS"},
        ],
    },
    "telegram_bot": {
        "label": "Telegram bot",
        "fields": [
            {"key": "token", "label": "BOT TOKEN", "secret": True,
             "placeholder": "123456:ABC-DEF…"},
            {"key": "chat_id", "label": "DEFAULT CHAT ID (optional)",
             "secret": False, "placeholder": "-1001234567890"},
        ],
    },
    "google_oauth": {
        "label": "Google OAuth (Sheets, Drive, Gmail…)",
        "fields": [
            {"key": "client_id", "label": "CLIENT ID", "secret": False,
             "placeholder": "…apps.googleusercontent.com"},
            {"key": "client_secret", "label": "CLIENT SECRET", "secret": True},
            {"key": "token", "label": "REFRESH TOKEN", "secret": True,
             "placeholder": "1//0e…"},
            {"key": "scopes", "label": "SCOPES", "secret": False,
             "placeholder": "https://www.googleapis.com/auth/spreadsheets"},
        ],
    },
    "basic_auth": {
        "label": "Username & password",
        "fields": [
            {"key": "username", "label": "USERNAME", "secret": False},
            {"key": "token", "label": "PASSWORD", "secret": True},
        ],
    },
    "custom_header": {
        "label": "Custom header (any API)",
        "fields": [
            {"key": "header_name", "label": "HEADER NAME", "secret": False,
             "default": "Authorization"},
            {"key": "prefix", "label": "VALUE PREFIX", "secret": False,
             "default": "Bearer", "placeholder": "Bearer, Token, or blank"},
            {"key": "token", "label": "VALUE", "secret": True},
        ],
    },
}
DEFAULT_CRED_TYPE = "api_token"


class SecretField(QWidget):
    """One credential field: label, input, and a Show button when it's a
    secret. Nothing service-specific lives here — the spec dict decides."""

    def __init__(self, spec):
        super().__init__()
        self.key = spec["key"]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lbl = QLabel(spec["label"])
        lbl.setStyleSheet("color:#bbb;font-family:monospace;font-size:11px;letter-spacing:1px;")
        lay.addWidget(lbl)

        row = QHBoxLayout(); row.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setStyleSheet("font-family:monospace;font-size:13px;padding:6px;")
        if spec.get("placeholder"):
            self.edit.setPlaceholderText(spec["placeholder"])
        self.secret = bool(spec.get("secret"))
        if self.secret:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        row.addWidget(self.edit, 1)

        self.show_btn = None
        if self.secret:
            self.show_btn = QPushButton("Show")
            self.show_btn.setCheckable(True)
            self.show_btn.setFixedWidth(64)
            self.show_btn.toggled.connect(self._toggle)
            row.addWidget(self.show_btn)
        lay.addLayout(row)

    def _toggle(self, on):
        self.edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        self.show_btn.setText("Hide" if on else "Show")

    def value(self):
        return self.edit.text().strip()

    def set_value(self, v):
        self.edit.setText(v or "")

    def set_enabled(self, on):
        self.edit.setEnabled(on)
        if self.show_btn:
            self.show_btn.setEnabled(on)


class CredentialsPanel(QWidget):
    """Manage named credentials. Each one is a small JSON file: {name, type,
    …fields}. The form is built from CRED_TYPES, so a service needing more
    than a token (Google's client id + secret + refresh token, Discord's
    webhook URL) is a dict entry rather than new UI.

    Older credentials saved as {name, token} have no type — they load as
    'api_token', and 'token' stays the key nodes read first, so nothing
    already wired up breaks."""

    def __init__(self, app, accent=None):
        super().__init__()
        self.app = app
        self.accent = accent or DEFAULT_BUTTON_COLOR
        self.current = None
        self.fields = []
        root = QHBoxLayout(self); root.setContentsMargins(0, 8, 0, 0); root.setSpacing(20)

        # left: saved credentials
        leftw = QVBoxLayout(); leftw.setSpacing(6)
        leftw.addWidget(self._tag("SAVED CREDENTIALS"))
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.list.itemClicked.connect(self._on_pick)
        leftw.addWidget(self.list, 1)
        row = QHBoxLayout()
        new_btn = QPushButton("+ New"); new_btn.clicked.connect(self._new)
        del_btn = QPushButton("Delete"); del_btn.clicked.connect(self._delete)
        row.addWidget(new_btn); row.addWidget(del_btn)
        leftw.addLayout(row)
        root.addLayout(leftw, 2)

        # right: the editor, as one card. Capped so a 50-character token isn't
        # given the whole window, but wide enough for a Google refresh token.
        rightw = QVBoxLayout(); rightw.setSpacing(6)
        rightw.addWidget(self._tag("CREDENTIAL"))

        self.card = QFrame()
        self.card.setObjectName("credCard")
        self.card.setMaximumWidth(760)
        card = QVBoxLayout(self.card)
        card.setContentsMargins(18, 16, 18, 16)
        card.setSpacing(12)

        self.name_lbl = QLabel("no credential selected")
        card.addWidget(self.name_lbl)

        typerow = QHBoxLayout(); typerow.setSpacing(8)
        tl = QLabel("TYPE")
        tl.setStyleSheet("color:#bbb;font-family:monospace;font-size:11px;letter-spacing:1px;")
        typerow.addWidget(tl)
        self.type_box = QComboBox()
        for key, spec in CRED_TYPES.items():
            self.type_box.addItem(spec["label"], key)
        self.type_box.currentIndexChanged.connect(self._on_type_changed)
        typerow.addWidget(self.type_box, 1)
        card.addLayout(typerow)

        self.fields_box = QVBoxLayout()
        self.fields_box.setSpacing(10)
        card.addLayout(self.fields_box)

        btnrow = QHBoxLayout()
        self.status = QLabel("")
        self.status.setStyleSheet("color:#7CFC9B;font-family:monospace;font-size:11px;")
        btnrow.addWidget(self.status)
        btnrow.addStretch()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save)
        btnrow.addWidget(self.save_btn)
        card.addLayout(btnrow)

        rightw.addWidget(self.card)
        rightw.addStretch()
        root.addLayout(rightw, 3)

        self._apply_card_style()
        self._build_fields(DEFAULT_CRED_TYPE, {})
        self._set_editor_enabled(False)

    # -- form building -------------------------------------------------------
    def _build_fields(self, type_key, data):
        """Rebuild the field rows for a type, filling in whatever `data` has."""
        while self.fields_box.count():
            item = self.fields_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self.fields = []
        spec = CRED_TYPES.get(type_key) or CRED_TYPES[DEFAULT_CRED_TYPE]
        for fspec in spec["fields"]:
            f = SecretField(fspec)
            f.set_value(data.get(fspec["key"], fspec.get("default", "")))
            f.edit.returnPressed.connect(self._save)
            self.fields_box.addWidget(f)
            self.fields.append(f)

    def _on_type_changed(self):
        """Switching type keeps any values whose key exists in both, so
        picking the wrong type first doesn't cost you the token you pasted."""
        if self.current is None:
            self._build_fields(self._type_key(), {})
            self._set_editor_enabled(False)
            return
        kept = {f.key: f.value() for f in self.fields}
        self._build_fields(self._type_key(), kept)

    def _type_key(self):
        return self.type_box.currentData() or DEFAULT_CRED_TYPE

    def _select_type(self, key):
        i = self.type_box.findData(key)
        self.type_box.blockSignals(True)
        self.type_box.setCurrentIndex(i if i >= 0 else 0)
        self.type_box.blockSignals(False)

    # -- styling -------------------------------------------------------------
    def _apply_card_style(self):
        self.card.setStyleSheet(
            "QFrame#credCard{background:rgba(255,255,255,0.03);"
            "border:1px solid rgba(255,255,255,0.10);border-radius:6px;}")

    def _set_editor_enabled(self, on):
        for f in self.fields:
            f.set_enabled(on)
        self.type_box.setEnabled(on)
        self.save_btn.setEnabled(on)
        self.name_lbl.setStyleSheet(
            f"color:{self.accent if on else '#777'};font-family:monospace;font-size:15px;")

    def set_accent(self, color):
        self.accent = color
        self._set_editor_enabled(self.current is not None)

    def _tag(self, t):
        l = QLabel(t); l.setStyleSheet("color:#999;font-family:monospace;font-size:11px;letter-spacing:1px;")
        return l

    def _sublabel(self, t):
        l = QLabel(t); l.setStyleSheet("color:#bbb;font-family:monospace;font-size:12px;")
        return l

    def _say(self, msg, ok=True):
        self.status.setStyleSheet(
            f"color:{'#7CFC9B' if ok else '#ff6b6b'};font-family:monospace;font-size:11px;")
        self.status.setText(msg)

    # -- data ----------------------------------------------------------------
    def refresh(self):
        self.list.clear()
        for name in list_credentials():
            self.list.addItem(QListWidgetItem(name))

    def _on_pick(self, item):
        name = item.text()
        self.current = name
        try:
            data = load_credential(name)
        except Exception:
            data = {}
        # no saved type = a credential from before types existed
        tkey = data.get("type") or DEFAULT_CRED_TYPE
        self._select_type(tkey)
        self._build_fields(tkey, data)
        self.name_lbl.setText(name)
        self.status.setText("")
        self._set_editor_enabled(True)

    def _new(self):
        name, ok = QInputDialog.getText(self, "New Credential", "Name (e.g. 'deepseek'):")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in list_credentials():
            self._say(f"'{name}' already exists — pick another name", ok=False)
            return
        tkey = self._type_key()
        save_credential(name, {"name": name, "type": tkey})
        self.refresh()
        self.current = name
        self._build_fields(tkey, {})
        self.name_lbl.setText(name)
        self._set_editor_enabled(True)
        self._say("created")
        if self.fields:
            self.fields[0].edit.setFocus()

    def _save(self):
        if not self.current:
            self._say("create or select a credential first", ok=False)
            return
        data = {"name": self.current, "type": self._type_key()}
        for f in self.fields:
            data[f.key] = f.value()
        save_credential(self.current, data)
        self._say(f"saved: {self.current}")

    def _delete(self):
        if not self.current:
            return
        confirm = QMessageBox.question(self, "Delete", f"Delete credential '{self.current}'?")
        if confirm == QMessageBox.StandardButton.Yes:
            delete_credential(self.current)
            self.current = None
            self.name_lbl.setText("no credential selected")
            self._build_fields(self._type_key(), {})
            self.status.setText("")
            self.refresh()
            self._set_editor_enabled(False)


class ToggleSwitch(QPushButton):
    """A small ON/OFF pill switch (checkable button styled as a toggle)."""
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(54, 26)
        self.toggled.connect(self._restyle)
        self.setChecked(checked)
        self._restyle(checked)

    def _restyle(self, checked):
        self.setText("ON" if checked else "OFF")
        if checked:
            self.setStyleSheet(
                f"QPushButton{{background:{NORMAL_ICON_BLUE};color:#111;"
                f"border:1px solid {NORMAL_ICON_BLUE};border-radius:13px;"
                "font-family:monospace;font-size:11px;font-weight:bold;}"
            )
        else:
            self.setStyleSheet(
                "QPushButton{background:#555;color:#ddd;border:1px solid #777;"
                "border-radius:13px;font-family:monospace;font-size:11px;}"
            )


class HomeSettingsDialog(QDialog):
    """Popup from the bottom-left gear icon (Home or Tabel Editor).

    Page 1 — Home Screen Settings: button/accent color, logo color,
    background image or see-through switch.

    Page 2 — Workflow UI Settings (reached via the arrow, top-right):
    canvas look for the workflow editor — n8n-style dot grid by default,
    a custom canvas background image, a switch to hide the dots, and a
    switch to remove the canvas background entirely (the old plain look).

    Saving persists everything at once and broadcasts it live to every
    registered screen (Home, TabelEditor, the workflow Editor/Canvas, ...).
    """
    def __init__(self, home, parent=None):
        super().__init__(parent)
        self.home = home
        self.setWindowTitle("Settings")
        self.setMinimumSize(780, 580)
        self.setStyleSheet(
            f"QDialog{{background:{GREY_PANEL};}}"
            "QLabel{color:#ddd;font-family:monospace;font-size:13px;}"
            "QPushButton{background:transparent;color:#eee;border:1px solid #777;"
            "border-radius:4px;padding:6px 10px;font-family:monospace;font-size:12px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.10);}"
            "QListWidget{background:transparent;border:none;font-family:monospace;font-size:12px;}"
            "QListWidget::item{padding:9px 12px;border-radius:4px;color:#bbb;}"
            "QListWidget::item:hover{background:rgba(255,255,255,0.06);}"
            "QListWidget::item:selected{background:rgba(255,255,255,0.10);color:#fff;}"
            "QScrollArea{background:transparent;border:none;}"
        )
        s = home.settings
        self._button_color = s.get("button_color", DEFAULT_BUTTON_COLOR)
        self._logo_color = s.get("logo_color", DEFAULT_LOGO_COLOR)
        self._bg_image = s.get("bg_image")
        self._bg_transparent = s.get("bg_transparent", False)
        self._canvas_bg_image = s.get("canvas_bg_image")
        self._canvas_dots = s.get("canvas_dots", True)
        self._canvas_no_background = s.get("canvas_no_background", False)
        self._panel_color = s.get("panel_color") or GREY_BG
        self._fog_opacity = int(s.get("fog_opacity", 150))
        self._node_size = int(s.get("node_size", 84))
        self._wire_snap = int(s.get("wire_snap", 16))
        self._autosave_enabled = bool(s.get("autosave_enabled", True))
        self._node_text_scale = float(s.get("node_text_scale", s.get("text_scale", 1.0)))
        self._panel_text_scale = float(s.get("panel_text_scale", 1.0))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- header ----------------------------------------------------------
        head = QWidget()
        head.setStyleSheet("background:rgba(0,0,0,0.15);")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(22, 16, 22, 14)
        hl.setSpacing(2)
        t = QLabel("Settings")
        t.setStyleSheet("color:#fff;font-family:monospace;font-size:16px;font-weight:bold;")
        hl.addWidget(t)
        sub = QLabel("Applies everywhere the moment you save")
        sub.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:11px;")
        hl.addWidget(sub)
        outer.addWidget(head)
        outer.addWidget(self._hline())

        # -- body: section list on the left, the section itself on the right --
        # The second page used to hide behind an arrow in the corner, which is
        # how nobody found the canvas settings. Sections are listed instead, so
        # everything the dialog can do is visible from the moment it opens.
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setFixedWidth(168)
        self.nav.setSpacing(2)
        self.nav.setStyleSheet(self.nav.styleSheet() + "QListWidget{padding:12px 10px;}")
        for name in ("Appearance", "Canvas", "Text", "Behaviour"):
            self.nav.addItem(QListWidgetItem(name))
        self.nav.currentRowChanged.connect(self._on_section)
        body.addWidget(self.nav)
        body.addWidget(self._vline())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_appearance_page())
        self.stack.addWidget(self._build_canvas_page())
        self.stack.addWidget(self._build_text_page())
        self.stack.addWidget(self._build_behaviour_page())
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        # -- footer ----------------------------------------------------------
        outer.addWidget(self._hline())
        foot = QHBoxLayout()
        foot.setContentsMargins(22, 12, 22, 14)
        foot.addStretch()
        reset = QPushButton("Reset")
        reset.setToolTip("Put every setting back to its default")
        reset.clicked.connect(self._reset_defaults)
        foot.addWidget(reset)
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save = QPushButton("Save"); save.clicked.connect(self._save)
        save.setStyleSheet(
            f"QPushButton{{background:rgba(126,207,255,0.14);color:{self._button_color};"
            f"border:1px solid {self._button_color};border-radius:4px;padding:6px 18px;"
            "font-family:monospace;font-size:12px;}"
            "QPushButton:hover{background:rgba(126,207,255,0.24);}")
        foot.addWidget(cancel); foot.addWidget(save)
        outer.addLayout(foot)

        self.nav.setCurrentRow(0)

    def _on_section(self, i):
        if i >= 0:
            self.stack.setCurrentIndex(i)

    # -- small building blocks ------------------------------------------------
    def _hline(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setFixedHeight(1); f.setStyleSheet("background:rgba(255,255,255,0.10);border:none;")
        return f

    def _vline(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedWidth(1); f.setStyleSheet("background:rgba(255,255,255,0.10);border:none;")
        return f

    def _group(self, title):
        l = QLabel(title)
        l.setStyleSheet("color:#999;font-family:monospace;font-size:11px;letter-spacing:1px;")
        return l

    def _row(self, label, hint, *widgets):
        """One setting: its name and explanation on the left, its controls on
        the right. Every setting uses this, so the rows line up instead of each
        one inventing its own arrangement."""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)

        textw = QWidget()
        left = QVBoxLayout(textw)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(3)
        nl = QLabel(label)
        nl.setStyleSheet("color:#e4e4e4;font-family:monospace;font-size:12px;")
        left.addWidget(nl)
        if hint:
            hl = QLabel(hint)
            hl.setWordWrap(True)
            hl.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:11px;")
            left.addWidget(hl)
        textw.setMinimumWidth(230)
        lay.addWidget(textw, 1)

        ctlw = QWidget()
        ctl = QHBoxLayout(ctlw)
        ctl.setContentsMargins(0, 0, 0, 0)
        ctl.setSpacing(8)
        ctl.addStretch()
        for x in widgets:
            if isinstance(x, QWidget):
                ctl.addWidget(x)
            else:
                ctl.addLayout(x)
        lay.addWidget(ctlw, 0)
        return w

    def _page(self, blocks):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(16)
        for b in blocks:
            if b is None:
                lay.addWidget(self._hline())
            else:
                lay.addWidget(b)
        lay.addStretch()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        # A QScrollArea and its viewport keep the default (light) palette even
        # inside a dark dialog, which leaves the whole page unreadable. The
        # viewport and the page widget both have to be made transparent.
        sc.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                         "QScrollArea > QWidget > QWidget{background:transparent;}")
        sc.viewport().setStyleSheet("background:transparent;")
        page.setStyleSheet("background:transparent;")
        sc.setWidget(page)
        return sc

    # -- pages ----------------------------------------------------------------
    def _build_appearance_page(self):
        self.btn_swatch = QPushButton(); self.btn_swatch.setFixedSize(28, 28)
        self.btn_swatch.setEnabled(False)
        self._paint_swatch(self.btn_swatch, self._button_color)
        pick1 = QPushButton("Choose…"); pick1.clicked.connect(self._pick_button_color)

        self.logo_swatch = QPushButton(); self.logo_swatch.setFixedSize(28, 28)
        self.logo_swatch.setEnabled(False)
        self._paint_swatch(self.logo_swatch, self._logo_color)
        pick2 = QPushButton("Choose…"); pick2.clicked.connect(self._pick_logo_color)

        choose_bg = QPushButton("Choose…"); choose_bg.clicked.connect(self._pick_bg_image)
        remove_bg = QPushButton("Remove"); remove_bg.clicked.connect(self._remove_bg_image)
        self.bg_status = QLabel(self._bg_status_text())
        self.bg_status.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:11px;")
        self.bg_status.setWordWrap(True)

        self.transparent_switch = ToggleSwitch(checked=self._bg_transparent)
        self.transparent_switch.toggled.connect(self._on_transparent_toggle)

        return self._page([
            self._group("COLOR"),
            self._row("Accent colour",
                      "Buttons, tabs and highlights across every screen.",
                      self.btn_swatch, pick1),
            self._row("Logo colour",
                      "The “DuGS” wordmark, shared across screens.",
                      self.logo_swatch, pick2),
            None,
            self._group("HOME BACKGROUND"),
            self._row("Background image",
                      "Scaled to cover and centred behind the home screen.",
                      choose_bg, remove_bg),
            self.bg_status,
            self._row("See-through",
                      "Drops the background entirely so whatever is behind the "
                      "window shows through.",
                      self.transparent_switch),
        ])

    def _build_canvas_page(self):
        choose_cbg = QPushButton("Choose…"); choose_cbg.clicked.connect(self._pick_canvas_bg_image)
        remove_cbg = QPushButton("Remove"); remove_cbg.clicked.connect(self._remove_canvas_bg_image)
        self.canvas_bg_status = QLabel(self._canvas_bg_status_text())
        self.canvas_bg_status.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:11px;")
        self.canvas_bg_status.setWordWrap(True)

        self.dots_switch = ToggleSwitch(checked=self._canvas_dots)
        self.dots_switch.toggled.connect(self._on_dots_toggle)

        self.canvas_no_bg_switch = ToggleSwitch(checked=self._canvas_no_background)
        self.canvas_no_bg_switch.toggled.connect(self._on_canvas_no_bg_toggle)

        self.panel_swatch = QLabel(); self.panel_swatch.setFixedSize(34, 18)
        self._paint_swatch(self.panel_swatch, self._panel_color)
        pick_panel = QPushButton("Choose…"); pick_panel.clicked.connect(self._pick_panel_color)
        reset_panel = QPushButton("Reset"); reset_panel.clicked.connect(self._reset_panel_color)

        self.fog_slider = QSlider(Qt.Orientation.Horizontal)
        self.fog_slider.setRange(0, 255)
        self.fog_slider.setValue(self._fog_opacity)
        self.fog_slider.setFixedWidth(170)
        self.fog_slider.valueChanged.connect(self._on_fog_change)
        self.fog_value = QLabel(str(self._fog_opacity))
        self.fog_value.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:11px;")
        self.fog_value.setFixedWidth(34)

        self.node_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.node_size_slider.setRange(48, 160)
        self.node_size_slider.setValue(self._node_size)
        self.node_size_slider.setFixedWidth(170)
        self.node_size_slider.valueChanged.connect(self._on_node_size)
        self.node_size_value = QLabel(f"{self._node_size} px")
        self.node_size_value.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:11px;")
        self.node_size_value.setFixedWidth(46)

        self.wire_snap_slider = QSlider(Qt.Orientation.Horizontal)
        self.wire_snap_slider.setRange(4, 60)
        self.wire_snap_slider.setValue(self._wire_snap)
        self.wire_snap_slider.setFixedWidth(170)
        self.wire_snap_slider.valueChanged.connect(self._on_wire_snap)
        self.wire_snap_value = QLabel(f"{self._wire_snap} px")
        self.wire_snap_value.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:11px;")
        self.wire_snap_value.setFixedWidth(46)

        return self._page([
            self._group("NODES"),
            self._row("Node size",
                      "How big a node square is drawn. Robotics nodes stay "
                      "smaller than this, as they always have.",
                      self.node_size_slider, self.node_size_value),
            self._row("Wire snap",
                      "How close a dragged wire has to get before it grabs a "
                      "port. Higher catches more easily, lower gives finer "
                      "control on a crowded canvas.",
                      self.wire_snap_slider, self.wire_snap_value),
            None,
            self._group("CANVAS BACKGROUND"),
            self._row("Background image",
                      "Behind the node graph in the workflow editor.",
                      choose_cbg, remove_cbg),
            self.canvas_bg_status,
            self._row("Grid dots",
                      "The small dot grid over the canvas, like n8n.",
                      self.dots_switch),
            None,
            self._group("SEE-THROUGH MODE"),
            self._row("No background",
                      "Everything goes see-through with a dark fog behind it.",
                      self.canvas_no_bg_switch),
            self._row("Fog",
                      "How dark that haze is, so nodes stay readable.",
                      self.fog_slider, self.fog_value),
            self._row("Panel colour",
                      "Background of the panels and canvas. Ignored while "
                      "No background is on.",
                      self.panel_swatch, pick_panel, reset_panel),
        ])

    def _scale_slider(self, value):
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(60, 250)                        # 0.6x .. 2.5x
        sl.setValue(int(value * 100))
        sl.setFixedWidth(200)
        return sl

    def _build_text_page(self):
        # Two separate multipliers: the node popup is a form you read up close,
        # the panels are chrome you glance at, and they rarely want the same
        # size. One slider for both was always a compromise.
        self.node_text_slider = self._scale_slider(self._node_text_scale)
        self.node_text_slider.valueChanged.connect(self._on_node_text_scale)
        self.node_text_value = QLabel(f"{self._node_text_scale:.2f}x")
        self.node_text_value.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:11px;")
        self.node_text_value.setFixedWidth(46)

        self.panel_text_slider = self._scale_slider(self._panel_text_scale)
        self.panel_text_slider.valueChanged.connect(self._on_panel_text_scale)
        self.panel_text_value = QLabel(f"{self._panel_text_scale:.2f}x")
        self.panel_text_value.setStyleSheet("color:#8a8a8a;font-family:monospace;font-size:11px;")
        self.panel_text_value.setFixedWidth(46)

        return self._page([
            self._group("NODE POPUP"),
            self._row("Node text size",
                      "The text inside a node's popup — inputs, parameters and "
                      "output. Each piece keeps its own relative size.",
                      self.node_text_slider, self.node_text_value),
            None,
            self._group("PANELS"),
            self._row("Panel text size",
                      "The modules around the canvas — node palette, settings, "
                      "run log, JSON.",
                      self.panel_text_slider, self.panel_text_value),
        ])

    def _build_behaviour_page(self):
        self.autosave_switch = ToggleSwitch(checked=self._autosave_enabled)
        self.autosave_switch.toggled.connect(self._on_autosave_toggle)

        return self._page([
            self._group("EDITOR"),
            self._row("Autosave",
                      "Saves shortly after you stop making changes. Turn it "
                      "off and nothing reaches disk until you press Save.",
                      self.autosave_switch),
        ])

    def _on_node_text_scale(self, v):
        self._node_text_scale = v / 100.0
        self.node_text_value.setText(f"{self._node_text_scale:.2f}x")

    def _on_panel_text_scale(self, v):
        self._panel_text_scale = v / 100.0
        self.panel_text_value.setText(f"{self._panel_text_scale:.2f}x")

    def _on_autosave_toggle(self, on):
        self._autosave_enabled = bool(on)

    def _on_node_size(self, v):
        self._node_size = int(v)
        self.node_size_value.setText(f"{self._node_size} px")

    def _on_wire_snap(self, v):
        self._wire_snap = int(v)
        self.wire_snap_value.setText(f"{self._wire_snap} px")

    def _reset_defaults(self):
        """Put every setting back to the shipped default, in the dialog only —
        nothing is written until Save, so this is undoable with Cancel."""
        if QMessageBox.question(
                self, "Reset settings",
                "Put every setting back to its default?\n"
                "Nothing is written until you press Save."
        ) != QMessageBox.StandardButton.Yes:
            return
        d = DEFAULT_HOME_UI_SETTINGS
        self._button_color = d["button_color"]
        self._logo_color = d["logo_color"]
        self._bg_image = d["bg_image"]
        self._bg_transparent = d["bg_transparent"]
        self._canvas_bg_image = d["canvas_bg_image"]
        self._canvas_dots = d["canvas_dots"]
        self._canvas_no_background = d["canvas_no_background"]
        self._panel_color = GREY_BG
        self._fog_opacity = d["fog_opacity"]
        self._node_size = d["node_size"]
        self._node_text_scale = d["node_text_scale"]
        self._panel_text_scale = d["panel_text_scale"]
        self._wire_snap = d["wire_snap"]
        self._autosave_enabled = d["autosave_enabled"]

        self._paint_swatch(self.btn_swatch, self._button_color)
        self._paint_swatch(self.logo_swatch, self._logo_color)
        self._paint_swatch(self.panel_swatch, self._panel_color)
        self.bg_status.setText(self._bg_status_text())
        self.canvas_bg_status.setText(self._canvas_bg_status_text())
        for sw, val in ((self.transparent_switch, self._bg_transparent),
                        (self.dots_switch, self._canvas_dots),
                        (self.canvas_no_bg_switch, self._canvas_no_background),
                        (self.autosave_switch, self._autosave_enabled)):
            sw.blockSignals(True); sw.setChecked(val); sw.blockSignals(False)
        for sl, val in ((self.fog_slider, self._fog_opacity),
                        (self.node_size_slider, self._node_size),
                        (self.wire_snap_slider, self._wire_snap),
                        (self.node_text_slider, int(self._node_text_scale * 100)),
                        (self.panel_text_slider, int(self._panel_text_scale * 100))):
            sl.setValue(val)          # its own handler refreshes the readout
        self.fog_value.setText(str(self._fog_opacity))

    def _pick_panel_color(self):
        c = QColorDialog.getColor(QColor(self._panel_color), self, "Pick Panel Color")
        if c.isValid():
            self._panel_color = c.name()
            self._paint_swatch(self.panel_swatch, self._panel_color)

    def _reset_panel_color(self):
        self._panel_color = GREY_BG
        self._paint_swatch(self.panel_swatch, self._panel_color)

    def _on_fog_change(self, v):
        self._fog_opacity = int(v)
        self.fog_value.setText(str(v))

    # -- shared helpers -------------------------------------------------------
    def _tag(self, t):
        l = QLabel(t); l.setStyleSheet("color:#999;font-family:monospace;font-size:11px;letter-spacing:1px;")
        return l

    def _paint_swatch(self, btn, color):
        btn.setStyleSheet(f"background:{color};border:1px solid #777;border-radius:4px;")

    # -- home page handlers ---------------------------------------------------
    def _bg_status_text(self):
        if getattr(self, "_bg_transparent", False):
            return "Current: see-through (no background)"
        if self._bg_image:
            return f"Current: {os.path.basename(self._bg_image)}"
        return "Current: none (flat grey background)"

    def _on_transparent_toggle(self, checked):
        self._bg_transparent = checked
        self.bg_status.setText(self._bg_status_text())

    def _pick_button_color(self):
        c = QColorDialog.getColor(QColor(self._button_color), self, "Pick Button Color")
        if c.isValid():
            self._button_color = c.name()
            self._paint_swatch(self.btn_swatch, self._button_color)

    def _pick_logo_color(self):
        c = QColorDialog.getColor(QColor(self._logo_color), self, "Pick Logo Color")
        if c.isValid():
            self._logo_color = c.name()
            self._paint_swatch(self.logo_swatch, self._logo_color)

    def _pick_bg_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Background Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self._bg_image = path
            self.bg_status.setText(self._bg_status_text())

    def _remove_bg_image(self):
        self._bg_image = None
        self.bg_status.setText(self._bg_status_text())

    # -- workflow page handlers ------------------------------------------------
    def _canvas_bg_status_text(self):
        if self._canvas_no_background:
            return "Current: no background (plain, dots hidden too)"
        if self._canvas_bg_image:
            return f"Current: {os.path.basename(self._canvas_bg_image)}"
        return "Current: flat grey (n8n default)"

    def _pick_canvas_bg_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Canvas Background Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self._canvas_bg_image = path
            self.canvas_bg_status.setText(self._canvas_bg_status_text())

    def _remove_canvas_bg_image(self):
        self._canvas_bg_image = None
        self.canvas_bg_status.setText(self._canvas_bg_status_text())

    def _on_dots_toggle(self, checked):
        self._canvas_dots = checked

    def _on_canvas_no_bg_toggle(self, checked):
        self._canvas_no_background = checked
        self.canvas_bg_status.setText(self._canvas_bg_status_text())

    def _save(self):
        s = self.home.settings
        s["button_color"] = self._button_color
        s["logo_color"] = self._logo_color
        s["bg_image"] = self._bg_image
        s["bg_transparent"] = self._bg_transparent
        s["canvas_bg_image"] = self._canvas_bg_image
        s["canvas_dots"] = self._canvas_dots
        s["canvas_no_background"] = self._canvas_no_background
        s["panel_color"] = self._panel_color
        s["fog_opacity"] = self._fog_opacity
        s["node_size"] = self._node_size
        s["node_text_scale"] = self._node_text_scale
        s["panel_text_scale"] = self._panel_text_scale
        s["wire_snap"] = self._wire_snap
        s["autosave_enabled"] = self._autosave_enabled
        save_home_ui_settings(s)
        broadcast_theme_update()
        self.accept()


def button_style(color, circular=False):
    """Shared button styling helper — used by Home and any other screen that
    wants to match the same customizable button/accent look (e.g. TabelEditor)."""
    radius = "19px" if circular else "4px"
    pad = "0px" if circular else "8px 14px"
    size = "font-size:18px;" if circular else "font-size:14px;"
    # A faint dark fill rather than fully transparent: with a see-through
    # background there is nothing behind the button, so a transparent one
    # disappears against the desktop.
    return (
        f"QPushButton{{background:rgba(0,0,0,0.35);color:{color};"
        f"border:1px solid {color};"
        f"border-radius:{radius};padding:{pad};font-family:monospace;{size}}}"
        f"QPushButton:hover{{background:rgba(255,255,255,0.15);}}"
    )


def paint_flat_or_image_bg(widget, event, settings, base_grey=GREY_BG):
    """Shared background painter — draws the settings' bg image (scaled to
    cover, with a readability overlay), a flat grey fill, or nothing at all
    if bg_transparent is on. Used by both Home and TabelEditor so the
    background customization behaves identically everywhere."""
    if settings.get("bg_transparent"):
        return False  # caller should just call super().paintEvent(event)
    painter = QPainter(widget)
    bg_path = settings.get("bg_image")
    pix = QPixmap(bg_path) if bg_path and os.path.exists(bg_path) else None
    if pix and not pix.isNull():
        scaled = pix.scaled(
            widget.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (widget.width() - scaled.width()) // 2
        y = (widget.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.fillRect(widget.rect(), QColor(0, 0, 0, 90))
    else:
        painter.fillRect(widget.rect(), QColor(base_grey))
    painter.end()
    return True


class RunCanvasView(QWidget):
    """The node-graph view of a run — same idea as the mini-canvas strip on
    the node popup, but built from a run record's saved layout instead of a
    live canvas.

    Each node draws at its saved position with its icon, a subtle gradient
    fill, and a border colour that says what happened: the accent colour if
    it produced output, red if it's part of a run that errored and never got
    to fire, grey if it just never ran that pass. Under each node that ran,
    its own duration shows in small text -- how long THAT node took before
    the run moved on. AI nodes that spent tokens get an amber badge with the
    count. Wires carry a small arrowhead so the flow direction is obvious at
    a glance. A summary line up top totals the run's time and tokens.
    """

    def __init__(self, accent="#7ecfff"):
        super().__init__()
        self.accent = accent
        self.record = None
        self.setMinimumHeight(150)

    def set_record(self, record):
        self.record = record
        self.update()

    def paintEvent(self, _):
        from PyQt6.QtGui import QFont, QLinearGradient, QPainterPath
        from PyQt6.QtCore import QRectF, QPointF
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # fully opaque, on purpose -- if this were translucent and the
        # detail_stack ever failed to cleanly hide the JSON page underneath,
        # the old text would bleed through it. Solid fill rules that out
        # completely regardless of what else is going on.
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0, QColor(30, 30, 32))
        bg.setColorAt(1, QColor(20, 20, 22))
        p.fillRect(self.rect(), bg)
        self.setAutoFillBackground(True)

        rec = self.record
        if not rec:
            p.setPen(QColor("#777"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "select a run")
            return

        layout = rec.get("layout") or {}
        nodes = layout.get("nodes") or []
        conns = layout.get("connections") or {}
        status = rec.get("node_status") or {}
        had_error = bool(rec.get("error"))

        if not nodes:
            p.setPen(QColor("#777"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "no layout saved for this run")
            return

        # ---- summary strip along the top: total time, total tokens ----
        header_h = 18
        total_ms = rec.get("duration_ms")
        total_tokens = sum(s.get("tokens", 0) for s in status.values())
        bits = []
        if total_ms is not None:
            bits.append(f"{total_ms:.0f}ms total")
        if total_tokens:
            bits.append(f"{total_tokens} tokens")
        if bits:
            f = QFont("monospace"); f.setPointSize(8)
            p.setFont(f)
            p.setPen(QColor("#888"))
            p.drawText(QRectF(8, 2, self.width() - 16, header_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "   \u00b7   ".join(bits))

        xs = [n.get("x", 0) for n in nodes]
        ys = [n.get("y", 0) for n in nodes]
        minx, maxx = min(xs), max(xs) + 90
        miny, maxy = min(ys), max(ys) + 60
        gw = max(1.0, maxx - minx)
        gh = max(1.0, maxy - miny)

        pad = 14
        aw = self.width() - pad * 2
        ah = self.height() - pad * 2 - header_h
        scale = min(aw / gw, ah / gh, 0.65)
        ox = pad + (aw - gw * scale) / 2
        oy = pad + header_h + (ah - gh * scale) / 2

        def sx(x): return ox + (x - minx) * scale
        def sy(y): return oy + (y - miny) * scale

        by_name = {n.get("name"): n for n in nodes}
        bw = max(10.0, 90 * scale)
        bh = max(8.0, 60 * scale)

        # ---- wires, with a small arrowhead so direction is obvious ----
        p.setPen(QPen(QColor(255, 255, 255, 55), 1.2))
        p.setBrush(QBrush(QColor(255, 255, 255, 55)))
        for src, links in conns.items():
            a = by_name.get(src)
            if not a:
                continue
            for link in (links or []):
                b = by_name.get(link.get("to"))
                if not b:
                    continue
                p1 = QPointF(sx(a["x"]) + bw, sy(a["y"]) + bh / 2)
                p2 = QPointF(sx(b["x"]), sy(b["y"]) + bh / 2)
                p.drawLine(p1, p2)
                ang_x = -6 if p2.x() >= p1.x() else 6
                tip = QPointF(p2.x() - (2 if ang_x < 0 else -2), p2.y())
                head = QPainterPath()
                head.moveTo(tip)
                head.lineTo(tip.x() + ang_x, tip.y() - 4)
                head.lineTo(tip.x() + ang_x, tip.y() + 4)
                head.closeSubpath()
                p.drawPath(head)

        try:
            from canvas import node_pixmap
        except Exception:
            node_pixmap = None

        f_small = QFont("monospace"); f_small.setPointSize(7)
        f_badge = QFont("monospace"); f_badge.setPointSize(7); f_badge.setBold(True)

        for n in nodes:
            r = QRectF(sx(n["x"]), sy(n["y"]), bw, bh)
            name = n.get("name")
            st = status.get(name)
            if st is None:
                edge = QColor(100, 100, 100)
            elif had_error and st.get("items_out", 0) == 0:
                edge = QColor("#ff6b6b")
            else:
                edge = QColor(self.accent)

            grad = QLinearGradient(r.topLeft(), r.bottomLeft())
            grad.setColorAt(0, QColor(48, 48, 52))
            grad.setColorAt(1, QColor(26, 26, 30))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(edge, 2 if st else 1))
            p.drawRoundedRect(r, 5, 5)

            if node_pixmap is not None:
                try:
                    pm = node_pixmap(n.get("type", ""), int(min(bw, bh) * 0.55))
                    if pm is not None and not pm.isNull():
                        p.drawPixmap(int(r.center().x() - pm.width() / 2),
                                    int(r.center().y() - pm.height() / 2 - 3), pm)
                except Exception:
                    pass

            if st and st.get("items_out", 0) > 1:
                txt = str(st["items_out"])
                p.setFont(f_badge)
                badge = QRectF(r.right() - 16, r.bottom() - 13, 15, 12)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 190))
                p.drawRoundedRect(badge, 3, 3)
                p.setPen(edge)
                p.drawText(badge, Qt.AlignmentFlag.AlignCenter, txt)

            if st and st.get("tokens"):
                txt = f"{st['tokens']}"
                p.setFont(f_badge)
                fm_w = 8 + len(txt) * 5
                badge = QRectF(r.right() - fm_w, r.top() - 6, fm_w, 12)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(40, 30, 0, 220))
                p.drawRoundedRect(badge, 3, 3)
                p.setPen(QColor("#e0b84c"))
                p.drawText(badge, Qt.AlignmentFlag.AlignCenter, txt)

            if st and st.get("ms") is not None and bh > 16:
                p.setFont(f_small)
                p.setPen(QColor("#888"))
                dur = f"{st['ms']:.0f}ms" if st["ms"] < 1000 else f"{st['ms']/1000:.1f}s"
                p.drawText(QRectF(r.left(), r.bottom() + 1, bw, 11),
                          Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, dur)


class RunLogDrawer(QWidget):
    """The bottom pull-up panel showing the runner's run history.

    Same idea as pulling a module panel open in the editor: a thin arrow tab
    sits at the bottom of the screen, and pulling it up reveals the list —
    every run the runner has done, most recent first, with a translucent
    timestamp list on the left and the run's detail on the right.

    If no runner folder is known yet, this offers the same Scan / browse /
    type-a-path flow as the editor's Deploy dialog, so there's one consistent
    way to point the app at a runner anywhere in the app.
    """

    def __init__(self, app, accent="#7ecfff"):
        super().__init__()
        self.app = app
        self.accent = accent
        self._open = False
        self._h = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # the tab you click/drag to open it
        self.tab = QPushButton("\u25b2  Runs")
        self.tab.setFixedHeight(22)
        self.tab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab.clicked.connect(self.toggle)
        outer.addWidget(self.tab)

        # the panel itself, height animates open/shut
        self.panel = QWidget()
        self.panel.setFixedHeight(0)
        outer.addWidget(self.panel)

        pl = QHBoxLayout(self.panel)
        pl.setContentsMargins(10, 10, 10, 10)
        pl.setSpacing(10)

        # left: translucent list of run timestamps
        self.list = QListWidget()
        self.list.setFixedWidth(240)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.currentRowChanged.connect(self._show_detail)
        pl.addWidget(self.list)

        # right: the selected run's detail, either as raw JSON or as a mini
        # node canvas — the switch flips between them, copy always grabs the
        # underlying JSON regardless of which view is showing
        from PyQt6.QtWidgets import QTextEdit, QStackedWidget
        detail_box = QVBoxLayout()
        detail_box.setSpacing(4)
        detail_header = QHBoxLayout()
        detail_header.addStretch()
        view_label = QLabel("Canvas view")
        view_label.setStyleSheet("color:#888;font-family:monospace;font-size:9px;")
        detail_header.addWidget(view_label)
        self.view_switch = ToggleSwitch(checked=False)
        self.view_switch.setFixedSize(40, 20)
        self.view_switch.setToolTip("Switch between raw JSON and the node canvas")
        self.view_switch.toggled.connect(self._on_view_toggle)
        detail_header.addWidget(self.view_switch)
        self.copy_btn = QPushButton("\u29c9 Copy")
        self.copy_btn.setFixedHeight(22)
        self.copy_btn.setToolTip("Copy this run's full record to the clipboard")
        self.copy_btn.clicked.connect(self._copy_detail)
        detail_header.addWidget(self.copy_btn)
        detail_box.addLayout(detail_header)

        self.detail_stack = QStackedWidget()
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail_stack.addWidget(self.detail)          # index 0: JSON
        self.canvas_view = RunCanvasView(accent)
        self.detail_stack.addWidget(self.canvas_view)      # index 1: canvas
        detail_box.addWidget(self.detail_stack, 1)
        pl.addLayout(detail_box, 1)

        # bottom-right controls: manual refresh, set-the-runs-folder, and how
        # long to keep old run files before they're auto-deleted
        controls = QVBoxLayout()
        controls.setSpacing(6)
        controls.addStretch()
        self.refresh_btn = QPushButton("\u21bb Refresh")
        self.refresh_btn.setToolTip("Reload the run list now")
        self.refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_btn)
        self.folder_btn = QPushButton("\U0001f4c1 Runs folder\u2026")
        self.folder_btn.setToolTip("Point this list at the runner's runs/ folder")
        self.folder_btn.clicked.connect(self._open_runs_folder_dialog)
        controls.addWidget(self.folder_btn)

        cleanup_row = QHBoxLayout()
        cleanup_row.setSpacing(4)
        cleanup_label = QLabel("Wipe older than:")
        cleanup_label.setStyleSheet("color:#888;font-family:monospace;font-size:9px;")
        cleanup_row.addWidget(cleanup_label)
        controls.addLayout(cleanup_row)
        from PyQt6.QtWidgets import QComboBox
        self.cleanup_combo = QComboBox()
        self.cleanup_combo.addItem("Never", "never")
        self.cleanup_combo.addItem("Every 24 hours", "24h")
        self.cleanup_combo.addItem("Every 5 hours", "5h")
        try:
            from storage import run_cleanup_setting
            cur = run_cleanup_setting()
            idx = self.cleanup_combo.findData(cur)
            if idx >= 0:
                self.cleanup_combo.setCurrentIndex(idx)
        except Exception:
            pass
        self.cleanup_combo.currentIndexChanged.connect(self._on_cleanup_changed)
        controls.addWidget(self.cleanup_combo)

        pl.addLayout(controls)

        # empty-state / not-configured-yet prompt, shown instead of the list
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.addWidget(QLabel("No runner folder set yet."))
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("/home/you/Deploy_DuGS/projects")
        row.addWidget(self.path_edit, 1)
        scan_btn = QPushButton("Scan")
        scan_btn.clicked.connect(self._scan)
        row.addWidget(scan_btn)
        browse_btn = QPushButton("\u2026")
        browse_btn.setFixedWidth(32)
        browse_btn.clicked.connect(self._browse)
        row.addWidget(browse_btn)
        el.addLayout(row)
        use_btn = QPushButton("Use this folder")
        use_btn.clicked.connect(self._use_path)
        el.addWidget(use_btn)
        self.empty_status = QLabel("")
        self.empty_status.setStyleSheet("color:#888;font-family:monospace;font-size:10px;")
        el.addWidget(self.empty_status)
        el.addStretch()
        pl.addWidget(self.empty, 1)

        self._anim = QPropertyAnimation(self.panel, b"minimumHeight")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim2 = QPropertyAnimation(self.panel, b"maximumHeight")
        anim2.setDuration(180)
        anim2.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim2 = anim2

        self.set_accent(accent)

    def set_accent(self, accent):
        self.accent = accent
        self.tab.setStyleSheet(
            f"QPushButton{{background:rgba(0,0,0,0.35);color:{accent};"
            f"border:1px solid {accent};border-bottom:none;border-radius:0px;"
            f"font-family:monospace;font-size:10px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,0.10);}}")
        self.panel.setStyleSheet(
            "QWidget{background:rgba(0,0,0,0.55);}"
            "QListWidget{background:rgba(255,255,255,0.05);color:#ccc;"
            "font-family:monospace;font-size:11px;border:1px solid rgba(255,255,255,0.08);}"
            "QTextEdit{background:rgba(0,0,0,0.25);color:#bbb;"
            "font-family:monospace;font-size:11px;border:1px solid rgba(255,255,255,0.08);}")
        self.copy_btn.setStyleSheet(
            f"QPushButton{{background:rgba(0,0,0,0.35);color:{accent};"
            f"border:1px solid {accent};border-radius:4px;font-size:10px;"
            f"font-family:monospace;padding:2px 8px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,0.12);}}")
        self.canvas_view.accent = accent
        self.canvas_view.update()

    def _copy_detail(self):
        """Copy the currently shown run's full record to the clipboard."""
        text = self.detail.toPlainText()
        if not text:
            return
        from PyQt6.QtWidgets import QApplication as _QApp
        _QApp.clipboard().setText(text)
        self.copy_btn.setText("\u2713 Copied")
        from PyQt6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(1200, lambda: self.copy_btn.setText("\u29c9 Copy"))

    def _on_cleanup_changed(self):
        value = self.cleanup_combo.currentData()
        try:
            from storage import set_run_cleanup_setting
            set_run_cleanup_setting(value)
        except Exception:
            pass

    def toggle(self):
        self._open = not self._open
        target = 220 if self._open else 0
        self.tab.setText(("\u25bc" if self._open else "\u25b2") + "  Runs")
        for a in (self._anim, self._anim2):
            a.stop(); a.setStartValue(self.panel.height()); a.setEndValue(target)
            a.start()
        if self._open:
            self.refresh()
            self._show_detail(self.list.currentRow())
        # no timer here on purpose -- refresh only happens when the drawer
        # opens or the Refresh button is clicked. It was auto-polling every
        # 4s regardless of whether anything changed, which is what kept
        # making the list/detail look like they were resetting.

    def refresh(self):
        """Reload the run list from the runner's runs/ folder.

        Reloading used to reset the scroll to the top every time -- annoying
        when you're reading an older run and it auto-refreshes out from under
        you. Now the scrollbar position and whichever run was selected (by
        its file, not its row -- new runs can push everything down a row)
        are restored after the reload.
        """
        try:
            from storage import runs_path, list_runs
        except Exception:
            return
        p = runs_path()
        has_folder = bool(p) and __import__("os").path.isdir(p)
        self.list.setVisible(has_folder)
        self.detail.setVisible(has_folder)
        self.empty.setVisible(not has_folder)
        if not has_folder:
            self.path_edit.setText(p or "")
            return

        # The left list refreshes; the right-hand detail pane does NOT --
        # only clicking a run in the list loads its detail. Refreshing used
        # to re-select a row to "restore" the selection, but setCurrentRow
        # fires currentRowChanged -> _show_detail, which rewrote the detail
        # pane (and reset ITS scroll) on every single refresh tick, even
        # though nothing about the reader's selection actually changed.
        # Simplest fix: block that signal while we repopulate the list, so
        # a refresh only ever touches the list, never the detail pane.
        scroll_pos = self.list.verticalScrollBar().value()
        prev_runs = getattr(self, "_runs", [])
        prev_files = {r.get("_file") for r in prev_runs}
        cur_row = self.list.currentRow()
        selected_file = (prev_runs[cur_row].get("_file")
                         if 0 <= cur_row < len(prev_runs) else None)

        new_runs = list_runs()
        new_files = {r.get("_file") for r in new_runs}

        # Nothing new and nothing gone: the auto-refresh timer was firing
        # every single tick regardless, rewriting the whole list widget even
        # when it was identical to what was already shown -- which is what
        # looked like "the whole thing keeps reloading". Now a no-op tick
        # touches literally nothing: no clear(), no repaint, no risk of the
        # selection or view ever appearing to reset.
        if hasattr(self, "_runs") and new_files == prev_files:
            self._runs = new_runs   # keep the data itself current either way
            return

        self._runs = new_runs

        # only sweep when refresh actually found something it hadn't seen
        # before -- not on every tick, and never at all when set to Never
        # (sweep_old_runs() itself no-ops on 'never', this just avoids the
        # pointless disk scan on every single auto-refresh)
        if new_files - prev_files:
            try:
                from storage import sweep_old_runs, run_cleanup_setting
                if run_cleanup_setting() != "never":
                    removed = sweep_old_runs()
                    if removed:
                        self._runs = list_runs()
            except Exception:
                pass

        self.list.blockSignals(True)
        self.list.clear()
        for r in self._runs:
            ok = r.get("error") is None
            mark = "\u2713" if ok else "\u2717"
            # name and timestamp packed close together, no fixed-width
            # padding forcing every row out to a name-that-never-happens
            # length -- that's what was pushing the list into horizontal
            # scroll. Timestamp trimmed to just the time; the date rarely
            # matters at a glance and the tooltip has the full one anyway.
            name = r.get("workflow", "?")
            ts = r.get("ran_at", "")
            time_only = ts.split("T")[1][:8] if "T" in ts else ts
            label = f"{mark} {name} \u00b7 {time_only}"
            self.list.addItem(label)
            self.list.item(self.list.count() - 1).setToolTip(
                f"{name}\nran at {ts}")

        if not self._runs:
            self.list.blockSignals(False)
            self.detail.setPlainText("no runs yet")
            return

        new_row = 0
        if selected_file:
            for i, r in enumerate(self._runs):
                if r.get("_file") == selected_file:
                    new_row = i
                    break
        self.list.setCurrentRow(new_row)
        self.list.verticalScrollBar().setValue(scroll_pos)
        self.list.blockSignals(False)

    def _show_detail(self, row):
        if row < 0 or row >= len(getattr(self, "_runs", [])):
            self.detail.setPlainText("")
            self.canvas_view.set_record(None)
            return
        import json as _json
        rec = self._runs[row]
        text = _json.dumps(rec, indent=2)
        # always save + restore scroll, unconditionally -- setPlainText resets
        # it to the top on every call, so just put it back after, every time,
        # rather than trying to detect "did the text really change"
        pos = self.detail.verticalScrollBar().value()
        self.detail.setPlainText(text)
        self.detail.verticalScrollBar().setValue(pos)
        self.canvas_view.set_record(rec)

    def _on_view_toggle(self, checked):
        self.detail_stack.setCurrentIndex(1 if checked else 0)

    # ---- first-time setup, same pattern as the editor's Deploy dialog ----
    def _scan(self):
        self.empty_status.setText("scanning\u2026")
        found = self._scan_for_runner()
        if found:
            self.path_edit.setText(found)
            self.empty_status.setText(f"found: {found}")
        else:
            self.empty_status.setText("no runner folder found — type or browse to it")

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Point at the runner's projects folder", self.path_edit.text() or "")
        if folder:
            self.path_edit.setText(folder)

    def _use_path(self):
        p = self.path_edit.text().strip()
        import os as _os
        if not p or not _os.path.isdir(p):
            self.empty_status.setText(f"not a folder: {p}")
            return
        from storage import set_deploy_path
        set_deploy_path(p)
        self.refresh()

    def _scan_for_runner(self):
        """Same signature scan as the editor: a projects/ folder sitting next
        to dugs_runner.py, so we don't match a random 'projects' folder."""
        import os as _os
        root = _os.path.expanduser("~")
        best = None
        for dirpath, dirnames, filenames in _os.walk(root):
            depth = dirpath[len(root):].count(_os.sep)
            if depth > 4:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d != "node_modules"]
            if "dugs_runner.py" in filenames and "projects" in dirnames:
                return _os.path.join(dirpath, "projects")
            if _os.path.basename(dirpath) == "projects" and best is None:
                if any(f.endswith(".json") for f in filenames):
                    best = dirpath
        return best

    def _open_runs_folder_dialog(self):
        """The bottom-right 'runs folder' button: same Scan / browse / type
        popup as Deploy, but points runs_path at a runs/ folder directly
        instead of deriving it from the deploy path."""
        import os as _os
        from storage import runs_path, set_runs_path

        dlg = QDialog(self)
        dlg.setWindowTitle("Runner's runs/ folder")
        dlg.setMinimumWidth(460)
        lay = QVBoxLayout(dlg)

        lay.addWidget(QLabel("Where the runner writes its run history:"))

        row = QHBoxLayout()
        path_edit = QLineEdit(runs_path())
        path_edit.setPlaceholderText("/home/you/Deploy_DuGS/runs")
        row.addWidget(path_edit, 1)
        scan_btn = QPushButton("Scan")
        row.addWidget(scan_btn)
        browse_btn = QPushButton("\u2026")
        browse_btn.setFixedWidth(32)
        row.addWidget(browse_btn)
        lay.addLayout(row)

        status = QLabel("")
        status.setStyleSheet("color:#888;font-family:monospace;font-size:11px;")
        lay.addWidget(status)

        def do_scan():
            status.setText("scanning\u2026")
            dlg.repaint()
            found = self._scan_for_runs_folder()
            if found:
                path_edit.setText(found)
                status.setText(f"found: {found}")
            else:
                status.setText("no runs/ folder found — type or browse to it")
        scan_btn.clicked.connect(do_scan)

        def do_browse():
            folder = QFileDialog.getExistingDirectory(
                dlg, "Point at the runner's runs/ folder", path_edit.text() or "")
            if folder:
                path_edit.setText(folder)
        browse_btn.clicked.connect(do_browse)

        complete = QPushButton("Use this folder")
        complete.setStyleSheet(
            f"QPushButton{{background:rgba(0,0,0,0.35);color:{self.accent};"
            f"border:1px solid {self.accent};border-radius:4px;padding:6px 12px;"
            f"font-family:monospace;}}")
        lay.addWidget(complete)

        def do_complete():
            p = path_edit.text().strip()
            if not p:
                status.setText("enter a folder first (or Scan for it)")
                return
            _os.makedirs(p, exist_ok=True)   # runs/ may not exist yet
            set_runs_path(p)
            self.refresh()
            dlg.accept()
        complete.clicked.connect(do_complete)

        dlg.exec()

    def _scan_for_runs_folder(self):
        """Same idea as the runner-folder scan, but looking for runs/ next to
        dugs_runner.py instead of projects/."""
        import os as _os
        root = _os.path.expanduser("~")
        for dirpath, dirnames, filenames in _os.walk(root):
            depth = dirpath[len(root):].count(_os.sep)
            if depth > 4:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d != "node_modules"]
            if "dugs_runner.py" in filenames:
                return _os.path.join(dirpath, "runs")
        return None


class Home(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.settings = load_home_ui_settings()

        root = QVBoxLayout(self); root.setContentsMargins(24, 16, 24, 14); root.setSpacing(12)

        # ---- top bar: logo mark + wordmark on the left, + New on the right
        topbar = QHBoxLayout()
        topbar.setSpacing(10)
        self.logo_mark = QLabel()
        self.logo_mark.setFixedSize(30, 30)
        self.logo_mark.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logo_mark.mousePressEvent = lambda _e: self.app.go_home()
        self._load_logo_mark()
        topbar.addWidget(self.logo_mark)

        self.dugs = QLabel("DuGS")
        self.dugs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dugs.mousePressEvent = lambda _e: self.app.go_home()
        topbar.addWidget(self.dugs)
        topbar.addStretch()
        self.new_btn = QPushButton("+ New")
        self.new_btn.clicked.connect(self.new_item)
        # Credentials hides this button. Without retainSizeWhenHidden the top
        # bar collapses to the height of the wordmark and the whole tab strip
        # jumps up — so keep the space reserved and only the button disappears.
        _sp = self.new_btn.sizePolicy()
        _sp.setRetainSizeWhenHidden(True)
        self.new_btn.setSizePolicy(_sp)
        topbar.addWidget(self.new_btn)
        root.addLayout(topbar)

        # ---- tabs: one connected strip spanning the full width, so the space
        # reads as a deliberate bar instead of three buttons floating in a gap
        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        self.tab_projects = QPushButton("Projects")
        self.tab_data = QPushButton("Data")
        self.tab_creds = QPushButton("Credentials")
        self.tab_projects.clicked.connect(lambda: self.select("project"))
        self.tab_data.clicked.connect(lambda: self.select("data"))
        self.tab_creds.clicked.connect(lambda: self.select("credential"))
        for t in (self.tab_projects, self.tab_data, self.tab_creds):
            t.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            t.setFixedHeight(34)
            tabs.addWidget(t, 1)
        root.addLayout(tabs)

        # ---- work area: the browser on the left, a live preview on the right
        btn_color = self.settings.get("button_color", DEFAULT_BUTTON_COLOR)
        body = QHBoxLayout()
        body.setSpacing(14)

        self.browsers = QStackedWidget()
        self.proj_browser = IconBrowser("project", app, accent=btn_color)
        self.data_browser = IconBrowser("data", app, accent=btn_color)
        self.creds_panel = CredentialsPanel(app, accent=btn_color)
        self.browsers.addWidget(self.proj_browser)
        self.browsers.addWidget(self.data_browser)
        self.browsers.addWidget(self.creds_panel)

        # an outline around the file area so it looks like a defined region
        self.browser_frame = QFrame()
        self.browser_frame.setObjectName("browserFrame")
        bf = QVBoxLayout(self.browser_frame)
        bf.setContentsMargins(10, 10, 10, 10)
        bf.addWidget(self.browsers)
        body.addWidget(self.browser_frame, 3)

        self.preview = PreviewPane(accent=btn_color)
        self.preview.setFixedWidth(300)
        body.addWidget(self.preview, 0)
        root.addLayout(body, 1)

        # selecting a project draws it in the preview pane
        try:
            # selectionChanged (not currentItemChanged) so selecting several
            # projects clears the pane instead of showing the last one clicked
            self.proj_browser.grid_host.itemSelectionChanged.connect(
                self._on_project_selected)
        except Exception:
            pass

        # settings gear, pinned bottom-left
        bottom_bar = QHBoxLayout()
        self.settings_btn = QPushButton("\u2699")   # gear glyph
        self.settings_btn.setFixedSize(38, 38)
        self.settings_btn.setToolTip("Home screen settings")
        self.settings_btn.clicked.connect(self.open_settings)
        bottom_bar.addWidget(self.settings_btn)
        bottom_bar.addStretch()
        root.addLayout(bottom_bar)

        # the run-history pull-up, at the very bottom of the screen
        self.run_log = RunLogDrawer(app, accent=btn_color)
        root.addWidget(self.run_log)

        # one-time catch-up: if projects were deployed before this tracked
        # registry existed (or the folder was touched by hand), make the
        # registry match what's actually sitting in the runner's folder, so
        # existing deploys don't silently lose their green name on upgrade
        try:
            from storage import sync_deployed_from_disk
            sync_deployed_from_disk()
        except Exception:
            pass

        self.section = "project"
        self.apply_theme()
        self._load_node_meta()
        self.select("project")
        register_themed_screen(self)

    def _load_logo_mark(self):
        """The app icon shown next to the DuGS wordmark, if it is available."""
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            for name in ("dugs-64.png", "dugs.png", "dugs-128.png"):
                fp = os.path.join(here, "icons", name)
                if os.path.isfile(fp):
                    pm = QPixmap(fp).scaled(
                        30, 30, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
                    self.logo_mark.setPixmap(pm)
                    return
        except Exception:
            pass
        self.logo_mark.setVisible(False)   # no icon shipped: just the wordmark

    def _on_project_selected(self):
        """Show the selected project's contents.

        Exactly one selection shows its detail; none or several clears the
        pane, since there is no single project to describe.
        """
        try:
            items = self.proj_browser.grid_host.selectedItems()
        except Exception:
            items = []
        if len(items) != 1:
            self.preview.show_project(None)
            return
        item = items[0]
        # the item text IS the project name; UserRole holds the kind
        # ("project"/"tabel"/"memory"), so reading UserRole here loaded a file
        # literally called "project" and the preview came up empty
        name = item.text()
        self.preview.show_project(name)

    def _load_node_meta(self):
        """Fetch the node list once so the inventory tiles can use the same
        titles and icons as the editor palette."""
        try:
            from api_client import api_get
            resp = api_get("/nodes") or {}
            # the endpoint returns {"nodes": [...]}, older builds a bare list
            items = resp.get("nodes", resp) if isinstance(resp, dict) else resp
            meta = {n["type"]: n for n in items
                    if isinstance(n, dict) and n.get("type")}
            self.preview.set_node_meta(meta)
        except Exception:
            pass   # no API running: tiles fall back to names derived from type

    # -- theme -------------------------------------------------------------
    def _btn_style(self, color, circular=False):
        return button_style(color, circular)

    def _tab_style(self, active, color, pos="mid"):
        """Segmented-control styling: the three tabs form one connected strip.

        `pos` says whether this is the left end, the right end or a middle
        segment, so only the outer corners get rounded and neighbours share a
        single border line instead of each drawing its own.
        """
        radius = {
            "left":  "border-top-left-radius:5px;border-bottom-left-radius:5px;",
            "right": "border-top-right-radius:5px;border-bottom-right-radius:5px;",
            "mid":   "",
        }[pos]
        # middle and right segments drop their left border so the strip reads
        # as one control rather than three touching buttons
        no_left = "border-left:none;" if pos in ("mid", "right") else ""
        if active:
            return (
                f"QPushButton{{background:rgba(255,255,255,0.16);color:{color};"
                f"border:1px solid {color};{no_left}{radius}"
                f"padding:8px 12px;font-family:monospace;font-size:13px;}}"
            )
        return (
            "QPushButton{background:rgba(0,0,0,0.20);color:#bbb;"
            f"border:1px solid #5a5a5a;{no_left}{radius}"
            "padding:8px 12px;font-family:monospace;font-size:13px;}"
            f"QPushButton:hover{{color:{color};background:rgba(255,255,255,0.07);}}"
        )

    def apply_theme(self):
        """(Re)apply button/logo colors + background from self.settings.
        Called at startup and again after the settings dialog is saved."""
        btn_color = self.settings.get("button_color", DEFAULT_BUTTON_COLOR)
        logo_color = self.settings.get("logo_color", DEFAULT_LOGO_COLOR)

        self.dugs.setStyleSheet(
            f"color:{logo_color};font-family:monospace;font-size:24px;font-weight:bold;"
        )
        self.new_btn.setStyleSheet(self._btn_style(btn_color))
        self.settings_btn.setStyleSheet(self._btn_style(btn_color, circular=True))

        for t, sec, pos in (
            (self.tab_projects, "project", "left"),
            (self.tab_data, "data", "mid"),
            (self.tab_creds, "credential", "right"),
        ):
            t.setStyleSheet(self._tab_style(sec == self.section, btn_color, pos))

        # the outline around the file area
        self.browser_frame.setStyleSheet(
            "QFrame#browserFrame{background:rgba(0,0,0,0.18);"
            "border:1px solid rgba(255,255,255,0.10);border-radius:8px;}")

        self.proj_browser.set_accent(btn_color)
        self.data_browser.set_accent(btn_color)
        self.creds_panel.set_accent(btn_color)
        self.preview.set_accent(btn_color)

        self.update()  # repaint background (grey or image)

    def open_settings(self):
        dlg = HomeSettingsDialog(self, self)
        dlg.exec()

    def paintEvent(self, event):
        """Draws the home screen background: the user's chosen image (scaled
        to cover, centered), a flat grey fill, or nothing at all if the
        see-through switch is on (lets whatever's behind this widget show
        through instead)."""
        if not paint_flat_or_image_bg(self, event, self.settings):
            super().paintEvent(event)
            return
        super().paintEvent(event)

    # -- sections ------------------------------------------------------------
    def select(self, section):
        self.section = section
        btn_color = self.settings.get("button_color", DEFAULT_BUTTON_COLOR)
        self.tab_projects.setStyleSheet(
            self._tab_style(section == "project", btn_color, "left"))
        self.tab_data.setStyleSheet(
            self._tab_style(section == "data", btn_color, "mid"))
        self.tab_creds.setStyleSheet(
            self._tab_style(section == "credential", btn_color, "right"))
        # the preview only makes sense for projects
        self.preview.setVisible(section == "project")
        if section == "project":
            self.browsers.setCurrentWidget(self.proj_browser); self.proj_browser.refresh()
            self.new_btn.setText("+ New Project"); self.new_btn.setVisible(True)
        elif section == "data":
            self.browsers.setCurrentWidget(self.data_browser); self.data_browser.refresh()
            self.new_btn.setText("+ New"); self.new_btn.setVisible(True)
        else:
            self.browsers.setCurrentWidget(self.creds_panel); self.creds_panel.refresh()
            self.new_btn.setVisible(False)

    def refresh(self):
        self.select(self.section)

    def new_item(self):
        if self.section == "project":
            dlg = NewProjectDialog(self, accent=self.settings.get("button_color", DEFAULT_BUTTON_COLOR))
            if dlg.exec() == QDialog.DialogCode.Accepted:
                name = dlg.name(); kind = dlg.kind()
                if name:
                    save_project(name, {"name": name, "kind": kind,
                                        "nodes": [], "connections": {}})
                    self.app.open_project(name)
        elif self.section == "data":
            # Data holds both Tabels and Memory banks, so ask which one —
            # the same way New Project asks Normal vs Servo
            choice, ok = QInputDialog.getItem(
                self, "New", "Create:", ["Tabel", "Memory Bank"], 0, False)
            if not ok:
                return
            if choice == "Memory Bank":
                name, ok = QInputDialog.getText(self, "New Memory Bank", "Bank name:")
                if ok and name.strip():
                    from storage import new_memory_bank
                    new_memory_bank(name.strip()); self.select("data")
            else:
                name, ok = QInputDialog.getText(self, "New Tabel", "Tabel name:")
                if ok and name.strip():
                    new_tabel(name.strip()); self.app.open_tabel(name.strip())


class NewProjectDialog(QDialog):
    """New Project popup: name + project type.

    normal -> a regular workflow (saves JSON, runs in the engine)
    servo  -> a hardware workflow; instead of running, it GENERATES Arduino
              code (.ino) that you upload to the board.
    """
    def __init__(self, parent=None, accent=None):
        super().__init__(parent)
        self.accent = accent or DEFAULT_BUTTON_COLOR
        self.setWindowTitle("New Project")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"QDialog{{background:{GREY_PANEL};}}"
                           "QLabel{color:#ccc;font-family:monospace;}"
                           "QLineEdit{background:#262626;color:#fff;border:1px solid #666;"
                           "border-radius:3px;padding:6px;font-family:monospace;font-size:13px;}")
        lay = QVBoxLayout(self); lay.setSpacing(10)

        lay.addWidget(QLabel("Project name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("my project")
        lay.addWidget(self.name_edit)

        lay.addWidget(QLabel("Project type:"))
        self._kind = "normal"

        self.btn_normal = QPushButton("Normal\nworkflow — runs in the engine, saves JSON")
        self.btn_servo = QPushButton("Servo\nhardware — generates Arduino code (.ino)")
        for b in (self.btn_normal, self.btn_servo):
            b.setMinimumHeight(58)
        self.btn_normal.clicked.connect(lambda: self._pick("normal"))
        self.btn_servo.clicked.connect(lambda: self._pick("servo"))
        lay.addWidget(self.btn_normal)
        lay.addWidget(self.btn_servo)
        self._restyle()

        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        create = QPushButton("Create"); create.clicked.connect(self._create)
        row.addWidget(cancel); row.addWidget(create)
        lay.addLayout(row)

    def _pick(self, k):
        self._kind = k
        self._restyle()

    def _restyle(self):
        for b, k in ((self.btn_normal, "normal"), (self.btn_servo, "servo")):
            if self._kind == k:
                b.setStyleSheet(f"QPushButton{{background:rgba(255,255,255,0.16);color:{self.accent};"
                                f"border:1px solid {self.accent};border-radius:4px;padding:8px;"
                                f"text-align:left;font-family:monospace;font-size:12px;}}")
            else:
                b.setStyleSheet("QPushButton{background:transparent;color:#bbb;"
                                "border:1px solid #666;border-radius:4px;padding:8px;"
                                "text-align:left;font-family:monospace;font-size:12px;}"
                                f"QPushButton:hover{{color:{self.accent};border-color:{self.accent};}}")

    def _create(self):
        if not self.name_edit.text().strip():
            return
        self.accept()

    def name(self):
        return self.name_edit.text().strip()

    def kind(self):
        return self._kind
