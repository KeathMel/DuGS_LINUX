"""
home_screen.py — the landing screen: Projects | Tabels tabs, each backed by an
icon-grid file browser with right-click Open/Download/Duplicate/Rename/Delete.
"""
import os
import shutil

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QStackedWidget, QInputDialog, QMenu, QMessageBox, QLineEdit,
    QDialog
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QPainterPath, QIcon, QPixmap, QAction

from theme import ACCENT
from storage import (
    PROJECTS_DIR, TABELS_DIR, DOWNLOADS, _ensure, _path,
    list_projects, list_tabels, save_project, new_tabel,
    list_credentials, load_credential, save_credential, delete_credential,
    project_kind,
)


SERVO_RED = "#ff6b6b"


def file_icon(size=64, color=None):
    color = color or ACCENT
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
    fill = QColor(34, 20, 20, 200) if color == SERVO_RED else QColor(20, 28, 34, 200)
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
    def __init__(self, kind, app):
        super().__init__()
        self.kind = kind            # "project" or "tabel"
        self.app = app
        self._icon = file_icon(64)
        self._icon_servo = file_icon(64, SERVO_RED)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.grid_host = QListWidget()
        self.grid_host.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid_host.setIconSize(QSize(64, 64))
        self.grid_host.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid_host.setSpacing(18)
        self.grid_host.setMovement(QListWidget.Movement.Static)
        self.grid_host.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid_host.customContextMenuRequested.connect(self.menu)
        self.grid_host.itemDoubleClicked.connect(lambda it: self.open(it.text()))
        self.grid_host.setStyleSheet(
            "QListWidget{background:transparent;border:none;}"
            "QListWidget::item{color:#ddd;}"
            f"QListWidget::item:selected{{color:{ACCENT};background:rgba(126,207,255,0.10);border-radius:4px;}}")
        lay.addWidget(self.grid_host)

    def names(self):
        return list_projects() if self.kind == "project" else list_tabels()

    def refresh(self):
        self.grid_host.clear()
        for n in self.names():
            # servo projects get a RED file icon so they stand out from the
            # normal (blue) workflow projects at a glance.
            is_servo = (self.kind == "project" and project_kind(n) == "servo")
            icon = self._icon_servo if is_servo else self._icon
            it = QListWidgetItem(icon, n)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            it.setSizeHint(QSize(96, 96))
            if is_servo:
                it.setForeground(QColor(SERVO_RED))
            self.grid_host.addItem(it)

    def menu(self, pos):
        it = self.grid_host.itemAt(pos)
        if not it: return
        name = it.text()
        m = QMenu(self)
        for label in ("Open", "Download", "Duplicate", "Rename", "Delete"):
            act = QAction(label, self)
            act.triggered.connect(lambda _=False, l=label, n=name: self.action(l, n))
            m.addAction(act)
        m.exec(self.grid_host.mapToGlobal(pos))

    def action(self, label, name):
        d = PROJECTS_DIR if self.kind == "project" else TABELS_DIR
        if label == "Open":
            self.open(name)
        elif label == "Download":
            _ensure(DOWNLOADS)
            shutil.copy(_path(d, name), os.path.join(DOWNLOADS, f"{name}.json"))
            self.app.toast(f"downloaded {name}.json to ~/Downloads")
        elif label == "Duplicate":
            base = f"{name}_copy"; i = 1; cand = base
            while cand in self.names(): i += 1; cand = f"{base}{i}"
            shutil.copy(_path(d, name), _path(d, cand)); self.refresh()
        elif label == "Rename":
            new, ok = QInputDialog.getText(self, "Rename", "New name:", text=name)
            if ok and new.strip() and new.strip() != name:
                os.rename(_path(d, name), _path(d, new.strip())); self.refresh()
        elif label == "Delete":
            if QMessageBox.question(self, "Delete", f"Delete '{name}'?") == QMessageBox.StandardButton.Yes:
                os.remove(_path(d, name)); self.refresh()

    def open(self, name):
        if self.kind == "project": self.app.open_project(name)
        else: self.app.open_tabel(name)


class CredentialsPanel(QWidget):
    """Manage named credentials (e.g. a DeepSeek token). Each credential is a
    small JSON file {name, token}. AI nodes can pick one by name instead of
    pasting the token every time."""
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.current = None
        root = QHBoxLayout(self); root.setContentsMargins(0, 8, 0, 0); root.setSpacing(16)

        # left: list of saved credentials + new/delete
        leftw = QVBoxLayout(); leftw.setSpacing(6)
        leftw.addWidget(self._tag("SAVED CREDENTIALS"))
        self.list = QListWidget(); self.list.setFixedWidth(260)
        self.list.itemClicked.connect(self._on_pick)
        leftw.addWidget(self.list, 1)
        row = QHBoxLayout()
        new_btn = QPushButton("+ New"); new_btn.clicked.connect(self._new)
        del_btn = QPushButton("Delete"); del_btn.clicked.connect(self._delete)
        row.addWidget(new_btn); row.addWidget(del_btn)
        leftw.addLayout(row)
        root.addLayout(leftw)

        # right: editor for the selected credential
        rightw = QVBoxLayout(); rightw.setSpacing(6)
        rightw.addWidget(self._tag("CREDENTIAL"))
        self.name_lbl = QLabel("(select or create a credential)")
        self.name_lbl.setStyleSheet(f"color:{ACCENT};font-family:monospace;font-size:15px;")
        rightw.addWidget(self.name_lbl)
        rightw.addWidget(self._sublabel("DeepSeek API Token"))
        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("paste your DeepSeek token here")
        self.token_edit.setStyleSheet("font-family:monospace;font-size:13px;padding:6px;")
        rightw.addWidget(self.token_edit)
        save_btn = QPushButton("Save Credential"); save_btn.clicked.connect(self._save)
        rightw.addWidget(save_btn)
        self.status = QLabel(""); self.status.setStyleSheet("color:#7CFC9B;font-family:monospace;font-size:11px;")
        rightw.addWidget(self.status)
        rightw.addStretch()
        root.addLayout(rightw, 1)

    def _tag(self, t):
        l = QLabel(t); l.setStyleSheet("color:#888;font-family:monospace;font-size:11px;letter-spacing:1px;")
        return l

    def _sublabel(self, t):
        l = QLabel(t); l.setStyleSheet("color:#aaa;font-family:monospace;font-size:12px;")
        return l

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
        self.name_lbl.setText(name)
        self.token_edit.setText(data.get("token", ""))
        self.status.setText("")

    def _new(self):
        name, ok = QInputDialog.getText(self, "New Credential", "Name (e.g. 'deepseek'):")
        if not ok or not name.strip():
            return
        name = name.strip()
        save_credential(name, {"name": name, "token": ""})
        self.refresh(); self.current = name
        self.name_lbl.setText(name); self.token_edit.setText(""); self.status.setText("created")

    def _save(self):
        if not self.current:
            self.status.setStyleSheet("color:#ff6b6b;font-family:monospace;font-size:11px;")
            self.status.setText("create or select a credential first"); return
        save_credential(self.current, {"name": self.current, "token": self.token_edit.text().strip()})
        self.status.setStyleSheet("color:#7CFC9B;font-family:monospace;font-size:11px;")
        self.status.setText(f"saved: {self.current}")

    def _delete(self):
        if not self.current:
            return
        confirm = QMessageBox.question(self, "Delete", f"Delete credential '{self.current}'?")
        if confirm == QMessageBox.StandardButton.Yes:
            delete_credential(self.current)
            self.current = None; self.name_lbl.setText("(select or create a credential)")
            self.token_edit.clear(); self.status.setText(""); self.refresh()


class Home(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        root = QVBoxLayout(self); root.setContentsMargins(24, 18, 24, 24); root.setSpacing(14)

        topbar = QHBoxLayout()
        self.dugs = QLabel("dugs")
        self.dugs.setStyleSheet(f"color:{ACCENT};font-family:monospace;font-size:24px;")
        self.dugs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dugs.mousePressEvent = lambda _e: self.app.go_home()
        topbar.addWidget(self.dugs); topbar.addStretch()
        self.new_btn = QPushButton("+ New")
        self.new_btn.clicked.connect(self.new_item)
        topbar.addWidget(self.new_btn)
        root.addLayout(topbar)

        tabs = QHBoxLayout(); tabs.addStretch()
        self.tab_projects = QPushButton("Projects")
        self.tab_tabels = QPushButton("Tabels")
        self.tab_creds = QPushButton("Credentials")
        for t in (self.tab_projects, self.tab_tabels, self.tab_creds):
            t.setFixedWidth(200); t.setStyleSheet(self._tab_style(False))
        self.tab_projects.clicked.connect(lambda: self.select("project"))
        self.tab_tabels.clicked.connect(lambda: self.select("tabel"))
        self.tab_creds.clicked.connect(lambda: self.select("credential"))
        tabs.addWidget(self.tab_projects); tabs.addSpacing(12)
        tabs.addWidget(self.tab_tabels); tabs.addSpacing(12)
        tabs.addWidget(self.tab_creds)
        tabs.addStretch()
        root.addLayout(tabs)

        self.browsers = QStackedWidget()
        self.proj_browser = IconBrowser("project", app)
        self.tabel_browser = IconBrowser("tabel", app)
        self.creds_panel = CredentialsPanel(app)
        self.browsers.addWidget(self.proj_browser)
        self.browsers.addWidget(self.tabel_browser)
        self.browsers.addWidget(self.creds_panel)
        root.addWidget(self.browsers, 1)

        self.section = "project"

    def _tab_style(self, active):
        if active:
            return (f"QPushButton{{background:rgba(126,207,255,0.18);color:{ACCENT};"
                    f"border:1px solid {ACCENT};border-radius:4px;padding:10px;text-align:left;"
                    f"font-family:monospace;font-size:14px;}}")
        return ("QPushButton{background:transparent;color:#aaa;"
                "border:1px solid #555;border-radius:4px;padding:10px;text-align:left;"
                "font-family:monospace;font-size:14px;}"
                f"QPushButton:hover{{color:{ACCENT};border-color:{ACCENT};}}")

    def select(self, section):
        self.section = section
        self.tab_projects.setStyleSheet(self._tab_style(section == "project"))
        self.tab_tabels.setStyleSheet(self._tab_style(section == "tabel"))
        self.tab_creds.setStyleSheet(self._tab_style(section == "credential"))
        if section == "project":
            self.browsers.setCurrentWidget(self.proj_browser); self.proj_browser.refresh()
            self.new_btn.setText("+ New Project"); self.new_btn.setVisible(True)
        elif section == "tabel":
            self.browsers.setCurrentWidget(self.tabel_browser); self.tabel_browser.refresh()
            self.new_btn.setText("+ New Tabel"); self.new_btn.setVisible(True)
        else:
            self.browsers.setCurrentWidget(self.creds_panel); self.creds_panel.refresh()
            self.new_btn.setVisible(False)

    def refresh(self):
        self.select(self.section)

    def new_item(self):
        if self.section == "project":
            dlg = NewProjectDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                name = dlg.name(); kind = dlg.kind()
                if name:
                    save_project(name, {"name": name, "kind": kind,
                                        "nodes": [], "connections": {}})
                    self.app.open_project(name)
        else:
            name, ok = QInputDialog.getText(self, "New Tabel", "Tabel name:")
            if ok and name.strip():
                name = name.strip(); new_tabel(name); self.app.open_tabel(name)


class NewProjectDialog(QDialog):
    """New Project popup: name + project type.

    normal -> a regular workflow (saves JSON, runs in the engine)
    servo  -> a hardware workflow; instead of running, it GENERATES Arduino
              code (.ino) that you upload to the board.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setMinimumWidth(420)
        self.setStyleSheet("QDialog{background:#141414;}"
                           "QLabel{color:#ccc;font-family:monospace;}"
                           "QLineEdit{background:#1e1e1e;color:#fff;border:1px solid #555;"
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
                b.setStyleSheet(f"QPushButton{{background:rgba(126,207,255,0.18);color:{ACCENT};"
                                f"border:1px solid {ACCENT};border-radius:4px;padding:8px;"
                                f"text-align:left;font-family:monospace;font-size:12px;}}")
            else:
                b.setStyleSheet("QPushButton{background:transparent;color:#aaa;"
                                "border:1px solid #555;border-radius:4px;padding:8px;"
                                "text-align:left;font-family:monospace;font-size:12px;}"
                                f"QPushButton:hover{{color:{ACCENT};border-color:{ACCENT};}}")

    def _create(self):
        if not self.name_edit.text().strip():
            return
        self.accept()

    def name(self):
        return self.name_edit.text().strip()

    def kind(self):
        return self._kind
