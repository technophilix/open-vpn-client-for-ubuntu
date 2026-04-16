#!/usr/bin/env python3
"""
OpenVPN3 GUI Client  –  SAML/SSO edition
Developed by Agniswar Chakraborty
"""

import os
import re
import sys
import json
import math
import webbrowser
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTextEdit, QFrame, QSizePolicy,
    QListWidget, QListWidgetItem, QDialog, QLineEdit, QMessageBox,
    QSplitter, QAbstractItemView, QMenu, QAction, QInputDialog,
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QUrl, QSize, QPoint,
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QPainter, QBrush, QDesktopServices,
    QIcon, QPen,
)

# ── Palette ───────────────────────────────────────────────────────────────────
BG_DARK       = "#0d1117"
BG_CARD       = "#161b22"
BG_PANEL      = "#1c2129"
ACCENT_GREEN  = "#39d353"
ACCENT_CYAN   = "#58a6ff"
ACCENT_RED    = "#f85149"
ACCENT_ORANGE = "#e3b341"
ACCENT_PURPLE = "#bc8cff"
TEXT_PRIMARY  = "#e6edf3"
TEXT_MUTED    = "#7d8590"
BORDER        = "#30363d"

_URL_RE  = re.compile(r'(https?://\S+)', re.IGNORECASE)
_PATH_RE = re.compile(r'Session path:\s*(\S+)')

PROFILES_FILE = Path.home() / ".config" / "openvpn3-gui" / "profiles.json"


# ── Profile store ─────────────────────────────────────────────────────────────
def load_profiles() -> list[dict]:
    try:
        if PROFILES_FILE.exists():
            return json.loads(PROFILES_FILE.read_text())
    except Exception:
        pass
    return []


def save_profiles(profiles: list[dict]):
    PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(json.dumps(profiles, indent=2))


# ── Helper: run a command safely ─────────────────────────────────────────────
def _run(cmd, timeout=15):
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            # Prevent the subprocess from blocking the GUI event loop
            # by detaching it from the terminal
            env={**os.environ, "TERM": "dumb"},
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "Command timed out"
    except FileNotFoundError:
        return -1, f"{cmd[0]!r} not found"
    except Exception as exc:
        return -1, str(exc)


# ── Worker: openvpn3 session-start ───────────────────────────────────────────
class StartWorker(QThread):
    log_line     = pyqtSignal(str)
    session_path = pyqtSignal(str)
    needs_auth   = pyqtSignal()
    connected    = pyqtSignal()
    error        = pyqtSignal(str)

    def __init__(self, ovpn_path: str):
        super().__init__()
        self.ovpn_path = ovpn_path
        self._proc = None

    def run(self):
        try:
            # Use Popen with non-blocking I/O to avoid freezing
            self._proc = subprocess.Popen(
                ["openvpn3", "session-start", "--config", self.ovpn_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "TERM": "dumb"},
            )
            found_path = None
            for raw in self._proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                self.log_line.emit(line)
                m = _PATH_RE.search(line)
                if m:
                    found_path = m.group(1)
                    self.session_path.emit(found_path)
                ll = line.lower()
                if "web based authentication" in ll:
                    self.needs_auth.emit()
                if "connected" in ll and "session" in ll:
                    self.connected.emit()
            self._proc.wait()
        except FileNotFoundError:
            self.error.emit(
                "openvpn3 not found.\nInstall:  sudo apt install openvpn3")
        except Exception as exc:
            self.error.emit(str(exc))

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


# ── Worker: fetch SAML URL via session-auth ───────────────────────────────────
class AuthWorker(QThread):
    log_line = pyqtSignal(str)
    auth_url = pyqtSignal(str)

    def __init__(self, session_path: str):
        super().__init__()
        self.session_path = session_path

    def run(self):
        self.msleep(1500)   # let daemon register
        self.log_line.emit(
            f"openvpn3 session-auth --path {self.session_path}")
        code, out = _run(
            ["openvpn3", "session-auth", "--path", self.session_path],
            timeout=25,
        )
        for line in out.splitlines():
            self.log_line.emit(line)
        m = _URL_RE.search(out)
        if m:
            self.auth_url.emit(m.group(1))
        else:
            self.log_line.emit(
                "Browser was opened by openvpn3 automatically — "
                "complete login there to continue.")


# ── Worker: disconnect ────────────────────────────────────────────────────────
class DisconnectWorker(QThread):
    log_line = pyqtSignal(str)
    done     = pyqtSignal(bool, str)

    def __init__(self, session_path: str | None, ovpn_path: str):
        super().__init__()
        self.session_path = session_path
        self.ovpn_path    = ovpn_path

    def run(self):
        if self.session_path:
            self.log_line.emit(
                f"openvpn3 session-manage --path {self.session_path} --disconnect")
            code, out = _run(
                ["openvpn3", "session-manage",
                 "--path", self.session_path, "--disconnect"])
            if out:
                self.log_line.emit(out)
            if code == 0:
                self.done.emit(True, "Session disconnected.")
                return

        # Fallback: sessions-list grep
        self.log_line.emit("Trying sessions-list fallback…")
        code, out = _run(["openvpn3", "sessions-list"], timeout=10)
        config_name = os.path.basename(self.ovpn_path)
        lines = out.splitlines()
        paths = []
        for i, line in enumerate(lines):
            if config_name in line:
                for j in range(i - 1, max(i - 15, -1), -1):
                    if "Path" in lines[j]:
                        p = lines[j].split(":", 1)[-1].strip()
                        if p:
                            paths.append(p)
                        break
        if not paths:
            self.done.emit(False, "No matching sessions found.")
            return
        ok = True
        for p in paths:
            self.log_line.emit(f"Disconnecting: {p}")
            c2, o2 = _run(
                ["openvpn3", "session-manage", "--path", p, "--disconnect"])
            if o2:
                self.log_line.emit(o2)
            if c2 != 0:
                ok = False
        self.done.emit(ok,
            "Disconnected." if ok else "Some sessions may not have disconnected.")


# ── Session status poller ─────────────────────────────────────────────────────
class SessionPoller(QTimer):
    status_changed = pyqtSignal(str)
    connected      = pyqtSignal()
    log_line       = pyqtSignal(str)

    def __init__(self, session_path: str, interval_ms=3000, parent=None):
        super().__init__(parent)
        self.session_path = session_path
        self._last = ""
        self.setInterval(interval_ms)
        self.timeout.connect(self._poll)

    def _poll(self):
        code, out = _run(["openvpn3", "sessions-list"], timeout=8)
        if code != 0:
            return
        lines = out.splitlines()
        status = ""
        in_ours = False
        for line in lines:
            if self.session_path in line:
                in_ours = True
            if in_ours and "Status:" in line:
                status = line.split("Status:", 1)[-1].strip()
                break
        if not status or status == self._last:
            return
        self._last = status
        self.log_line.emit(f"Session status: {status}")
        self.status_changed.emit(status)
        if "connected" in status.lower():
            self.stop()
            self.connected.emit()


# ══════════════════════════════════════════════════════════════════════════════
# UI Components
# ══════════════════════════════════════════════════════════════════════════════

class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = QColor(TEXT_MUTED)
        self._pulse = 0.0
        self._step  = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state: str):
        self._timer.stop()
        self._pulse = 0.0
        self._color = QColor({
            "idle":          TEXT_MUTED,
            "connecting":    ACCENT_ORANGE,
            "authing":       ACCENT_PURPLE,
            "connected":     ACCENT_GREEN,
            "disconnecting": ACCENT_ORANGE,
            "error":         ACCENT_RED,
        }.get(state, TEXT_MUTED))
        if state in ("connecting", "authing", "disconnecting"):
            self._step = 0
            self._timer.start(40)
        self.update()

    def _tick(self):
        self._step += 1
        self._pulse = (math.sin(self._step * 0.15) + 1) / 2
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, r = 7, 7, 5
        if self._pulse > 0:
            glow = QColor(self._color)
            glow.setAlphaF(self._pulse * 0.4)
            p.setBrush(QBrush(glow))
            p.setPen(Qt.NoPen)
            p.drawEllipse(cx - 7, cy - 7, 14, 14)
        p.setBrush(QBrush(self._color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)


class ProfileItem(QListWidgetItem):
    def __init__(self, name: str, path: str):
        super().__init__()
        self.profile_name = name
        self.profile_path = path
        self._connected   = False
        self._refresh_text()

    def _refresh_text(self):
        indicator = "● " if self._connected else "○ "
        self.setText(f"{indicator}{self.profile_name}")

    def set_connected(self, val: bool):
        self._connected = val
        self._refresh_text()


class ProfilePanel(QFrame):
    """Left panel: list of saved profiles + add/remove controls."""
    profile_selected  = pyqtSignal(str, str)   # name, path
    profile_connect   = pyqtSignal(str, str)   # name, path (double-click)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet(f"""
            QFrame {{
                background: {BG_CARD};
                border: none;
                border-right: 1px solid {BORDER};
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setFixedHeight(48)
        hdr.setStyleSheet(
            f"background:{BG_PANEL}; border-bottom:1px solid {BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 8, 0)
        title = QLabel("Profiles")
        title.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        title.setStyleSheet(f"color:{TEXT_PRIMARY}; background:transparent;")
        hl.addWidget(title)
        hl.addStretch()

        self._add_btn = self._icon_btn("+", ACCENT_GREEN, "#2ea043")
        self._add_btn.setToolTip("Add profile")
        self._add_btn.clicked.connect(self._add_profile)
        hl.addWidget(self._add_btn)
        lay.addWidget(hdr)

        # List
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._ctx_menu)
        self._list.itemClicked.connect(self._on_click)
        self._list.itemDoubleClicked.connect(self._on_dbl_click)
        self._list.setStyleSheet(f"""
            QListWidget {{
                background: {BG_CARD};
                border: none;
                color: {TEXT_PRIMARY};
                font-family: "Segoe UI", sans-serif;
                font-size: 9pt;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px 14px;
                border-bottom: 1px solid {BORDER};
            }}
            QListWidget::item:selected {{
                background: {BG_PANEL};
                color: {ACCENT_CYAN};
            }}
            QListWidget::item:hover:!selected {{
                background: #1a2030;
            }}
            QScrollBar:vertical {{
                background:{BG_DARK}; width:5px; border-radius:2px;
            }}
            QScrollBar::handle:vertical {{
                background:{BORDER}; border-radius:2px; min-height:16px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        lay.addWidget(self._list)

        # Footer hint
        hint = QLabel("Double-click to connect")
        hint.setFont(QFont("Segoe UI", 7))
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            f"color:{TEXT_MUTED}; background:{BG_PANEL};"
            f"border-top:1px solid {BORDER}; padding:6px;")
        lay.addWidget(hint)

        self._profiles: list[dict] = load_profiles()
        self._reload_list()

    def _icon_btn(self, text, bg, hover):
        b = QPushButton(text)
        b.setFixedSize(26, 26)
        b.setCursor(Qt.PointingHandCursor)
        b.setFont(QFont("Segoe UI", 13, QFont.Bold))
        b.setStyleSheet(f"""
            QPushButton {{
                background:{bg}; color:{BG_DARK};
                border:none; border-radius:5px;
            }}
            QPushButton:hover {{ background:{hover}; }}
        """)
        return b

    def _reload_list(self):
        self._list.clear()
        for p in self._profiles:
            item = ProfileItem(p["name"], p["path"])
            self._list.addItem(item)

    def _add_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select .ovpn Config", "",
            "OpenVPN Config (*.ovpn *.conf);;All Files (*)")
        if not path:
            return
        default_name = Path(path).stem
        name, ok = QInputDialog.getText(
            self, "Profile Name", "Enter a name for this profile:",
            text=default_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        # Avoid duplicates
        if any(p["name"] == name for p in self._profiles):
            QMessageBox.warning(self, "Duplicate",
                f'A profile named "{name}" already exists.')
            return
        self._profiles.append({"name": name, "path": path})
        save_profiles(self._profiles)
        self._reload_list()
        # Select the new item
        self._list.setCurrentRow(self._list.count() - 1)

    def _ctx_menu(self, pos: QPoint):
        item = self._list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background:{BG_PANEL}; color:{TEXT_PRIMARY};
                border:1px solid {BORDER}; border-radius:6px; padding:4px;
            }}
            QMenu::item {{ padding:6px 18px; border-radius:4px; }}
            QMenu::item:selected {{ background:{BG_CARD}; color:{ACCENT_CYAN}; }}
        """)
        rename_act = QAction("✏  Rename", self)
        delete_act = QAction("🗑  Remove", self)
        menu.addAction(rename_act)
        menu.addAction(delete_act)

        action = menu.exec_(self._list.viewport().mapToGlobal(pos))
        if action == rename_act:
            self._rename(item)
        elif action == delete_act:
            self._remove(item)

    def _rename(self, item: ProfileItem):
        new_name, ok = QInputDialog.getText(
            self, "Rename Profile", "New name:",
            text=item.profile_name)
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        for p in self._profiles:
            if p["name"] == item.profile_name:
                p["name"] = new_name
                break
        save_profiles(self._profiles)
        self._reload_list()

    def _remove(self, item: ProfileItem):
        self._profiles = [
            p for p in self._profiles if p["name"] != item.profile_name]
        save_profiles(self._profiles)
        self._reload_list()

    def _on_click(self, item: ProfileItem):
        self.profile_selected.emit(item.profile_name, item.profile_path)

    def _on_dbl_click(self, item: ProfileItem):
        self.profile_connect.emit(item.profile_name, item.profile_path)

    def mark_connected(self, name: str | None):
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.set_connected(item.profile_name == name)
            if item.profile_name == name:
                item.setForeground(QColor(ACCENT_GREEN))
            else:
                item.setForeground(QColor(TEXT_PRIMARY))

    def get_profiles(self):
        return self._profiles


class SAMLBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._url = ""
        self.setStyleSheet(
            f"QFrame {{ background:#12082a; border:1px solid {ACCENT_PURPLE};"
            f"border-radius:8px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        icon = QLabel("🔐")
        icon.setFont(QFont("Segoe UI Emoji", 14))
        lay.addWidget(icon)
        texts = QVBoxLayout()
        title = QLabel("SAML / Web Authentication Required")
        title.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        title.setStyleSheet(
            f"color:{ACCENT_PURPLE}; background:transparent; border:none;")
        texts.addWidget(title)
        self._sub = QLabel(
            "Browser should open automatically. Click the button if it didn't.")
        self._sub.setFont(QFont("Segoe UI", 8))
        self._sub.setStyleSheet(
            f"color:{TEXT_MUTED}; background:transparent; border:none;")
        self._sub.setWordWrap(True)
        texts.addWidget(self._sub)
        lay.addLayout(texts)
        self._btn = QPushButton("Open Browser")
        self._btn.setFixedHeight(32)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self._btn.setStyleSheet(f"""
            QPushButton {{
                background:{ACCENT_PURPLE}; color:{BG_DARK};
                border:none; border-radius:6px; padding:0 14px;
            }}
            QPushButton:hover {{ background:#d4a8ff; }}
            QPushButton:disabled {{ background:#3d2a5c; color:{TEXT_MUTED}; }}
        """)
        self._btn.setEnabled(False)
        self._btn.clicked.connect(self._open)
        lay.addWidget(self._btn)
        self.hide()

    def show_waiting(self):
        self._url = ""
        self._btn.setEnabled(False)
        self._sub.setText(
            "Browser should open automatically. Waiting for auth URL…")
        self.show()

    def show_url(self, url: str):
        self._url = url
        short = url[:65] + "…" if len(url) > 65 else url
        self._sub.setText(short)
        self._btn.setEnabled(True)
        self.show()

    def _open(self):
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))

    def clear(self):
        self._url = ""
        self.hide()


class LogPanel(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("JetBrains Mono, Consolas, Courier New", 8))
        self.setStyleSheet(f"""
            QTextEdit {{
                background:{BG_DARK}; color:{TEXT_MUTED};
                border:none; padding:12px;
            }}
            QScrollBar:vertical {{
                background:{BG_DARK}; width:6px; border-radius:3px;
            }}
            QScrollBar::handle:vertical {{
                background:{BORDER}; border-radius:3px; min-height:20px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height:0; }}
        """)

    def append_log(self, line: str, color: str = TEXT_MUTED):
        ts = datetime.now().strftime("%H:%M:%S")
        self.append(
            f'<span style="color:{TEXT_MUTED};">[{ts}]</span> '
            f'<span style="color:{color};">{line}</span>')
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum())


def make_btn(text, bg, hover, fg=TEXT_PRIMARY, dis="#2a3038"):
    b = QPushButton(text)
    b.setFixedHeight(40)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
    b.setStyleSheet(f"""
        QPushButton {{
            background:{bg}; color:{fg}; border:none;
            border-radius:7px; padding:0 18px; letter-spacing:.4px;
        }}
        QPushButton:hover    {{ background:{hover}; }}
        QPushButton:pressed  {{ background:{dis}; }}
        QPushButton:disabled {{ background:{dis}; color:{TEXT_MUTED}; }}
    """)
    return b


def h_sep():
    s = QFrame()
    s.setFrameShape(QFrame.HLine)
    s.setStyleSheet(f"background:{BORDER}; max-height:1px; border:none;")
    return s


def stat_box(label: str, value: str) -> QFrame:
    box = QFrame()
    box.setStyleSheet(
        f"QFrame {{ background:{BG_DARK}; border:1px solid {BORDER};"
        f"border-radius:8px; }}")
    v = QVBoxLayout(box)
    v.setContentsMargins(12, 9, 12, 9)
    v.setSpacing(3)
    lbl = QLabel(label.upper())
    lbl.setFont(QFont("Segoe UI", 7))
    lbl.setStyleSheet(
        f"color:{TEXT_MUTED}; letter-spacing:1.2px;"
        f"background:transparent; border:none;")
    v.addWidget(lbl)
    val = QLabel(value)
    val.setFont(QFont("JetBrains Mono, Consolas", 10, QFont.Bold))
    val.setStyleSheet(
        f"color:{TEXT_PRIMARY}; background:transparent; border:none;")
    val.setObjectName("val")
    v.addWidget(val)
    return box


def get_stat(box: QFrame) -> QLabel:
    return box.findChild(QLabel, "val")


# ══════════════════════════════════════════════════════════════════════════════
# Main Window
# ══════════════════════════════════════════════════════════════════════════════

class OpenVPN3Client(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ovpn_path: str | None     = None
        self.active_profile: str | None = None
        self._session_path: str | None  = None
        self._start_worker: StartWorker | None     = None
        self._auth_worker: AuthWorker | None       = None
        self._disc_worker: DisconnectWorker | None = None
        self._poller: SessionPoller | None         = None
        self._state   = "idle"
        self._elapsed = 0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._build_ui()
        self._apply_state("idle")

    def _build_ui(self):
        self.setWindowTitle("OpenVPN3 Client")
        self.setMinimumSize(880, 620)
        self.resize(980, 700)
        self.setStyleSheet(f"QMainWindow {{ background:{BG_DARK}; }}")

        # Central splitter: profile panel | main area
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background:{BORDER}; }}")
        self.setCentralWidget(splitter)

        # ── Left: profile panel ───────────────────────────────────────────
        self.profile_panel = ProfilePanel()
        self.profile_panel.profile_selected.connect(self._on_profile_selected)
        self.profile_panel.profile_connect.connect(self._on_profile_connect)
        splitter.addWidget(self.profile_panel)

        # ── Right: main content ───────────────────────────────────────────
        right = QWidget()
        right.setStyleSheet(f"background:{BG_DARK};")
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        outer = QVBoxLayout(right)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        # Header
        hdr = QHBoxLayout()
        for txt, col in [("OpenVPN", TEXT_PRIMARY), ("3", ACCENT_CYAN)]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Segoe UI", 18, QFont.Bold))
            lbl.setStyleSheet(f"color:{col};")
            hdr.addWidget(lbl)
        sub = QLabel("CLIENT")
        sub.setFont(QFont("Segoe UI", 8))
        sub.setStyleSheet(
            f"color:{ACCENT_CYAN}; padding-top:8px; letter-spacing:2px;")
        hdr.addWidget(sub)
        hdr.addStretch()

        # Active profile badge
        self.active_badge = QLabel("No profile selected")
        self.active_badge.setFont(QFont("Segoe UI", 8))
        self.active_badge.setStyleSheet(
            f"color:{TEXT_MUTED}; background:{BG_PANEL};"
            f"border:1px solid {BORDER}; border-radius:5px;"
            f"padding:3px 10px;")
        hdr.addWidget(self.active_badge, alignment=Qt.AlignVCenter)

        hdr.addSpacing(10)
        self.dot = StatusDot()
        hdr.addWidget(self.dot, alignment=Qt.AlignVCenter)
        self.status_lbl = QLabel("IDLE")
        self.status_lbl.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self.status_lbl.setStyleSheet(
            f"color:{TEXT_MUTED}; letter-spacing:1.5px;")
        hdr.addWidget(self.status_lbl, alignment=Qt.AlignVCenter)
        outer.addLayout(hdr)
        outer.addWidget(h_sep())

        # Stats row
        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.box_duration = stat_box("Duration", "—")
        self.box_ip       = stat_box("Tunnel IP", "—")
        self.box_proto    = stat_box("Protocol", "—")
        self.box_session  = stat_box("Session", "—")
        for b in (self.box_duration, self.box_ip,
                  self.box_proto, self.box_session):
            stats.addWidget(b)
        outer.addLayout(stats)

        # SAML banner
        self.saml_banner = SAMLBanner()
        outer.addWidget(self.saml_banner)

        # Action buttons
        br = QHBoxLayout()
        br.setSpacing(8)
        self.connect_btn = make_btn("⏵  Connect",    "#1a7f37", "#238636")
        self.connect_btn.clicked.connect(self._connect)
        br.addWidget(self.connect_btn)
        self.disconnect_btn = make_btn("⏹  Disconnect","#7d1f1f","#b62324")
        self.disconnect_btn.clicked.connect(self._disconnect)
        br.addWidget(self.disconnect_btn)
        br.addStretch()
        self.clear_btn = make_btn("Clear Log", BG_PANEL, "#252d38")
        self.clear_btn.setFixedWidth(100)
        self.clear_btn.clicked.connect(lambda: self.log.clear())
        br.addWidget(self.clear_btn)
        outer.addLayout(br)

        # Log
        log_frame = QFrame()
        log_frame.setStyleSheet(
            f"QFrame {{ background:{BG_DARK}; border:1px solid {BORDER};"
            f"border-radius:8px; }}")
        lf = QVBoxLayout(log_frame)
        lf.setContentsMargins(0, 0, 0, 0)
        log_hdr_frame = QFrame()
        log_hdr_frame.setStyleSheet(
            f"background:{BG_PANEL}; border-bottom:1px solid {BORDER};"
            f"border-top-left-radius:8px; border-top-right-radius:8px;")
        lhfl = QHBoxLayout(log_hdr_frame)
        lhfl.setContentsMargins(12, 6, 12, 6)
        log_title = QLabel("Session Log")
        log_title.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
        log_title.setStyleSheet(f"color:{TEXT_MUTED}; background:transparent;")
        lhfl.addWidget(log_title)
        lf.addWidget(log_hdr_frame)
        self.log = LogPanel()
        lf.addWidget(self.log)
        outer.addWidget(log_frame)

        # Footer: credits
        footer = QHBoxLayout()
        footer.addStretch()
        credit = QLabel("Designed & Developed by  "
                        "<span style='color:#58a6ff;'>Agniswar Chakraborty</span>")
        credit.setFont(QFont("Segoe UI", 7))
        credit.setStyleSheet(f"color:{TEXT_MUTED};")
        credit.setTextFormat(Qt.RichText)
        footer.addWidget(credit)
        outer.addLayout(footer)

        self.log.append_log(
            "Ready. Select a profile on the left or add one with +", ACCENT_CYAN)

    # ── State machine ─────────────────────────────────────────────────────────
    def _apply_state(self, state: str):
        self._state = state
        cfg = {
            "idle":          (TEXT_MUTED,    "IDLE",           True,  False),
            "connecting":    (ACCENT_ORANGE, "CONNECTING",     False, True),
            "authing":       (ACCENT_PURPLE, "AUTHENTICATING", False, True),
            "connected":     (ACCENT_GREEN,  "CONNECTED",      False, True),
            "disconnecting": (ACCENT_ORANGE, "DISCONNECTING",  False, False),
            "error":         (ACCENT_RED,    "ERROR",          True,  False),
        }
        col, label, conn_en, disc_en = cfg.get(
            state, (TEXT_MUTED, "IDLE", True, False))
        self.dot.set_state(state)
        self.status_lbl.setText(label)
        self.status_lbl.setStyleSheet(f"color:{col}; letter-spacing:1.5px;")
        self.connect_btn.setEnabled(conn_en and self.ovpn_path is not None)
        self.disconnect_btn.setEnabled(disc_en)

        if state == "connected":
            self._elapsed = 0
            self._elapsed_timer.start(1000)
            self.profile_panel.mark_connected(self.active_profile)
        elif state == "idle":
            self._elapsed_timer.stop()
            get_stat(self.box_duration).setText("—")
            get_stat(self.box_ip).setText("—")
            get_stat(self.box_session).setText("—")
            self.saml_banner.clear()
            self._session_path = None
            self._stop_poller()
            self.profile_panel.mark_connected(None)

    def _tick_elapsed(self):
        self._elapsed += 1
        h = self._elapsed // 3600
        m = (self._elapsed % 3600) // 60
        s = self._elapsed % 60
        get_stat(self.box_duration).setText(f"{h:02d}:{m:02d}:{s:02d}")

    # ── Profile selection ─────────────────────────────────────────────────────
    def _on_profile_selected(self, name: str, path: str):
        if self._state != "idle":
            return
        self.ovpn_path = path
        self.active_profile = name
        self.active_badge.setText(f"  {name}  ")
        self.active_badge.setStyleSheet(
            f"color:{ACCENT_CYAN}; background:{BG_PANEL};"
            f"border:1px solid {ACCENT_CYAN}; border-radius:5px;"
            f"padding:3px 10px;")
        self.connect_btn.setEnabled(True)
        self.log.append_log(f"Profile selected: {name}  ({path})", ACCENT_CYAN)
        try:
            with open(path) as f:
                content = f.read().lower()
            proto = ("UDP" if "proto udp" in content
                     else "TCP" if "proto tcp" in content else "—")
            get_stat(self.box_proto).setText(proto)
        except Exception:
            pass

    def _on_profile_connect(self, name: str, path: str):
        """Double-click: select and immediately connect."""
        self._on_profile_selected(name, path)
        if self._state == "idle":
            self._connect()

    # ── Connect ───────────────────────────────────────────────────────────────
    def _connect(self):
        if not self.ovpn_path or not os.path.isfile(self.ovpn_path):
            self.log.append_log("No valid profile / config file.", ACCENT_RED)
            return
        self._apply_state("connecting")
        get_stat(self.box_session).setText("starting")
        self.log.append_log(
            f"openvpn3 session-start --config {self.ovpn_path}", ACCENT_CYAN)

        self._start_worker = StartWorker(self.ovpn_path)
        self._start_worker.log_line.connect(self._on_log)
        self._start_worker.session_path.connect(self._on_session_path)
        self._start_worker.needs_auth.connect(self._on_needs_auth)
        self._start_worker.connected.connect(self._on_connected)
        self._start_worker.error.connect(self._on_error)
        self._start_worker.start()

    # ── Disconnect ────────────────────────────────────────────────────────────
    def _disconnect(self):
        self._elapsed_timer.stop()
        self._stop_poller()
        self._apply_state("disconnecting")
        self.log.append_log("Disconnecting…", ACCENT_ORANGE)

        # Cleanly stop any running workers WITHOUT blocking the GUI
        for w in (self._start_worker, self._auth_worker):
            if w and w.isRunning():
                w.stop() if hasattr(w, "stop") else w.terminate()
                # Do NOT call w.wait() here — that blocks the GUI thread

        self._disc_worker = DisconnectWorker(
            self._session_path, self.ovpn_path)
        self._disc_worker.log_line.connect(
            lambda l: self.log.append_log(l, TEXT_MUTED))
        self._disc_worker.done.connect(self._on_disc_done)
        self._disc_worker.start()

    # ── StartWorker signals ───────────────────────────────────────────────────
    def _on_session_path(self, path: str):
        self._session_path = path
        get_stat(self.box_session).setText("auth pending")
        self.log.append_log(f"Session: {path}", ACCENT_CYAN)

    def _on_needs_auth(self):
        self._apply_state("authing")
        self.saml_banner.show_waiting()
        self.log.append_log(
            "Web authentication required — fetching SAML URL…", ACCENT_PURPLE)
        if self._session_path:
            self._auth_worker = AuthWorker(self._session_path)
            self._auth_worker.log_line.connect(self._on_log)
            self._auth_worker.auth_url.connect(self._on_auth_url)
            self._auth_worker.start()
        self._start_poller()

    def _on_auth_url(self, url: str):
        self.saml_banner.show_url(url)
        self.log.append_log(f"Auth URL received.", ACCENT_PURPLE)
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            webbrowser.open(url)

    # ── Poller ────────────────────────────────────────────────────────────────
    def _start_poller(self):
        if not self._session_path:
            return
        self._poller = SessionPoller(self._session_path, 3000, self)
        self._poller.log_line.connect(
            lambda l: self.log.append_log(l, TEXT_MUTED))
        self._poller.status_changed.connect(
            lambda s: get_stat(self.box_session).setText(s))
        self._poller.connected.connect(self._on_connected)
        self._poller.start()

    def _stop_poller(self):
        if self._poller:
            self._poller.stop()
            self._poller = None

    def _on_connected(self):
        self._apply_state("connected")
        self.saml_banner.clear()
        get_stat(self.box_session).setText("connected")
        self.log.append_log("✓ VPN tunnel is up.", ACCENT_GREEN)
        self._refresh_ip()

    def _refresh_ip(self):
        if not self._session_path:
            return
        _, out = _run(["openvpn3", "sessions-list"], timeout=8)
        in_ours = False
        for line in out.splitlines():
            if self._session_path in line:
                in_ours = True
            if in_ours:
                m = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                if m:
                    get_stat(self.box_ip).setText(m.group(1))
                    break

    # ── Generic log colouring ─────────────────────────────────────────────────
    def _on_log(self, line: str):
        ll = line.lower()
        if any(k in ll for k in ("error", "failed")):
            c = ACCENT_RED
        elif any(k in ll for k in ("warning", "deprecated")):
            c = ACCENT_ORANGE
        elif any(k in ll for k in ("connected", "session is ready")):
            c = ACCENT_GREEN
        elif any(k in ll for k in ("saml", "browser", "https://",
                                    "web based", "authenticate", "webauth")):
            c = ACCENT_PURPLE
        elif any(k in ll for k in ("tls", "verify", "tun",
                                    "ifconfig", "route", "session path")):
            c = ACCENT_CYAN
        else:
            c = TEXT_MUTED
        self.log.append_log(line, c)

    def _on_error(self, msg: str):
        self._stop_poller()
        self._apply_state("error")
        self.log.append_log(f"ERROR: {msg}", ACCENT_RED)

    def _on_disc_done(self, ok: bool, msg: str):
        self.log.append_log(msg, ACCENT_GREEN if ok else ACCENT_RED)
        self._apply_state("idle")

    # ── Close — never block GUI on wait() ────────────────────────────────────
    def closeEvent(self, event):
        self._stop_poller()
        for w in (self._start_worker, self._auth_worker, self._disc_worker):
            if w and w.isRunning():
                w.stop() if hasattr(w, "stop") else w.terminate()
                # Use a short non-blocking wait; if it doesn't exit, move on
                w.wait(500)
        event.accept()


# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(BG_DARK))
    pal.setColor(QPalette.WindowText,      QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.Base,            QColor(BG_CARD))
    pal.setColor(QPalette.AlternateBase,   QColor(BG_PANEL))
    pal.setColor(QPalette.Text,            QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.Button,          QColor(BG_PANEL))
    pal.setColor(QPalette.ButtonText,      QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.Highlight,       QColor(ACCENT_CYAN))
    pal.setColor(QPalette.HighlightedText, QColor(BG_DARK))
    app.setPalette(pal)
    win = OpenVPN3Client()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()