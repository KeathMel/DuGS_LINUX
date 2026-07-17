"""
theme.py — shared visual constants used across every UI module.
"""
HERE_PLACEHOLDER = None  # set by ui.py at startup if needed

API = "http://127.0.0.1:5800"
ACCENT = "#7ecfff"
DIM = "#888888"
NODE_SIZE = 84

STYLESHEET = f"""
    QWidget {{ background: transparent; color:#fff; font-family:monospace; font-size:13px; }}
    QPushButton {{ background: transparent; color:{ACCENT}; border:1px solid {ACCENT}; border-radius:3px; padding:5px 10px; font-size:13px; }}
    QPushButton:hover {{ background: rgba(126,207,255,0.12); }}
    QListWidget {{ background: rgba(15,15,15,0.4); border:1px solid #444; border-radius:3px; font-size:13px; }}
    QListWidget::item {{ padding:7px; }}
    QListWidget::item:hover {{ color:{ACCENT}; }}
    QListWidget::item:selected {{ color:{ACCENT}; background: rgba(126,207,255,0.10); }}
    QLineEdit, QPlainTextEdit {{ background: rgba(20,20,20,0.6); color:#fff; border:1px solid #555; border-radius:3px; padding:4px; font-family:monospace; font-size:13px; }}
    QComboBox {{ background: rgba(20,20,20,0.6); color:#fff; border:1px solid #555; border-radius:3px; padding:4px 8px; font-family:monospace; font-size:13px; }}
    QComboBox:hover {{ border:1px solid {ACCENT}; }}
    QComboBox QAbstractItemView {{ background:#141414; color:#eee; border:1px solid {ACCENT}; selection-background-color: rgba(126,207,255,0.20); selection-color:{ACCENT}; font-size:13px; }}
    QCheckBox {{ color:#fff; font-family:monospace; font-size:13px; }}
    QCheckBox::indicator {{ width:16px; height:16px; border:1px solid #555; border-radius:3px; background: rgba(20,20,20,0.6); }}
    QCheckBox::indicator:checked {{ background:{ACCENT}; border:1px solid {ACCENT}; }}
    QMenu {{ background: #141414; color:#eee; border:1px solid {ACCENT}; font-family:monospace; font-size:13px; }}
    QMenu::item:selected {{ background: rgba(126,207,255,0.20); color:{ACCENT}; }}
    QScrollBar:vertical {{ background: rgba(20,20,20,0.3); width:6px; border-radius:3px; }}
    QScrollBar::handle:vertical {{ background: #444; border-radius:3px; min-height:20px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0px; }}
"""
