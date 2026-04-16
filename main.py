#!/usr/bin/env python3
"""
OpenVPN3 PyQt5 Client  –  SAML/SSO edition
============================================
Install:
    sudo apt install openvpn3
    pip install PyQt5

Run (no sudo needed):
    python3 openvpn_client.py

How the SAML flow works
-----------------------
1. `openvpn3 session-start --config <path>` is run; it exits immediately
   after spawning the daemon session and triggering web-auth.
2. We capture the session path from that output
   (line: "Session path: /net/openvpn/v3/sessions/…").
3. We call `openvpn3 session-auth --path <session_path>` which prints
   the actual SAML URL → we open it in the browser.
4. A QTimer polls `openvpn3 sessions-list` every 3 s to detect when
   the session status changes from "Auth pending" → "Connected".
5. Disconnect uses:
     openvpn3 session-manage --path <session_path> --disconnect
   with a sessions-list fallback for stale sessions.
"""

import os
import re
import sys
import math
import webbrowser
import subprocess
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTextEdit, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt5.QtGui import QFont, QColor, QPalette, QPainter, QBrush, QDesktopServices


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

_URL_RE       = re.compile(r'(https?://\S+)', re.IGNORECASE)
_PATH_RE      = re.compile(r'Session path:\s*(\S+)')


# ── Helper: run a command and return (returncode, combined output) ────────────
def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "Command timed out"
    except FileNotFoundError:
        return -1, f"{cmd[0]!r} not found"
    except Exception as exc:
        return -1, str(exc)


# ── Worker: openvpn3 session-start (exits quickly) ───────────────────────────
class StartWorker(QThread):
    log_line    = pyqtSignal(str)
    session_path = pyqtSignal(str)   # emitted when "Session path: …" is seen
    needs_auth  = pyqtSignal()       # "Web based authentication required"
    error       = pyqtSignal(str)

    def __init__(self, ovpn_path: str):
        super().__init__()
        self.ovpn_path = ovpn_path

    def run(self):
        try:
            proc = subprocess.Popen(
                ["openvpn3", "session-start", "--config", self.ovpn_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            found_path = None
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                self.log_line.emit(line)

                m = _PATH_RE.search(line)
                if m:
                    found_path = m.group(1)
                    self.session_path.emit(found_path)

                if "web based authentication" in line.lower():
                    self.needs_auth.emit()

            proc.wait()
            if proc.returncode not in (0, 1) and not found_path:
                self.error.emit(
                    f"session-start exited with code {proc.returncode}")
        except FileNotFoundError:
            self.error.emit(
                "openvpn3 not found.\nInstall:  sudo apt install openvpn3")
        except Exception as exc:
            self.error.emit(str(exc))


# ── Worker: openvpn3 session-auth (fetches SAML URL) ─────────────────────────
class AuthWorker(QThread):
    log_line = pyqtSignal(str)
    auth_url = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, session_path: str):
        super().__init__()
        self.session_path = session_path

    def run(self):
        # Give the daemon a moment to register the session
        self.msleep(1200)
        self.log_line.emit(
            f"openvpn3 session-auth --path {self.session_path}")
        code, out = _run(
            ["openvpn3", "session-auth", "--path", self.session_path],
            timeout=20,
        )
        for line in out.splitlines():
            self.log_line.emit(line)
        m = _URL_RE.search(out)
        if m:
            self.auth_url.emit(m.group(1))
        else:
            # session-auth might not print a URL if the browser was already
            # opened by openvpn3 itself; log and carry on polling.
            self.log_line.emit(
                "No URL found in session-auth output — "
                "browser may have been opened automatically.")


# ── Worker: disconnect ────────────────────────────────────────────────────────
class DisconnectWorker(QThread):
    log_line = pyqtSignal(str)
    done     = pyqtSignal(bool, str)

    def __init__(self, session_path: str | None, ovpn_path: str):
        super().__init__()
        self.session_path = session_path
        self.ovpn_path    = ovpn_path

    def run(self):
        # Strategy 1 – use the known session path directly
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

        # Strategy 2 – sessions-list grep by config basename
        self.log_line.emit("Trying sessions-list fallback…")
        code, out = _run(["openvpn3", "sessions-list"], timeout=10)
        config_name = os.path.basename(self.ovpn_path)
        lines  = out.splitlines()
        paths  = []
        for i, line in enumerate(lines):
            if config_name in line:
                for j in range(i - 1, max(i - 15, -1), -1):
                    if "Path" in lines[j]:
                        p = lines[j].split(":", 1)[-1].strip()
                        if p:
                            paths.append(p)
                        break

        if not paths:
            self.done.emit(False,
                "No matching sessions found in sessions-list.")
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
            "All sessions disconnected." if ok
            else "Some sessions may not have disconnected cleanly.")


# ── Session status poller ─────────────────────────────────────────────────────
class SessionPoller(QTimer):
    """
    Polls `openvpn3 sessions-list` every interval_ms milliseconds.
    Emits status_changed(status_str) when the status line for our session
    changes, and connected() when status contains "Connected".
    """
    status_changed = pyqtSignal(str)
    connected      = pyqtSignal()
    log_line       = pyqtSignal(str)

    def __init__(self, session_path: str, interval_ms: int = 3000,
                 parent=None):
        super().__init__(parent)
        self.session_path = session_path
        self._last_status = ""
        self.setInterval(interval_ms)
        self.timeout.connect(self._poll)

    def _poll(self):
        code, out = _run(["openvpn3", "sessions-list"], timeout=8)
        if code != 0:
            return
        lines = out.splitlines()
        status = ""
        in_our_session = False
        for line in lines:
            if self.session_path in line:
                in_our_session = True
            if in_our_session and "Status:" in line:
                status = line.split("Status:", 1)[-1].strip()
                break

        if not status:
            return
        if status != self._last_status:
            self._last_status = status
            self.log_line.emit(f"Session status: {status}")
            self.status_changed.emit(status)
            if "connected" in status.lower():
                self.stop()
                self.connected.emit()


# ── Animated status dot ───────────────────────────────────────────────────────
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


# ── File pill ─────────────────────────────────────────────────────────────────
class FilePill(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setStyleSheet(
            f"QFrame {{ background:{BG_DARK}; border:1px solid {BORDER};"
            f"border-radius:8px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        icon = QLabel("📁")
        icon.setFont(QFont("Segoe UI Emoji", 13))
        lay.addWidget(icon)
        self.label = QLabel("No .ovpn file selected")
        self.label.setFont(QFont("JetBrains Mono, Consolas, monospace", 9))
        self.label.setStyleSheet(
            f"color:{TEXT_MUTED}; background:transparent; border:none;")
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self.label)

    def set_path(self, path: str):
        display = path if len(path) <= 60 else "…" + path[-57:]
        self.label.setText(display)
        self.label.setStyleSheet(
            f"color:{TEXT_PRIMARY}; background:transparent; border:none;")


# ── SAML banner ───────────────────────────────────────────────────────────────
class SAMLBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._url = ""
        self.setStyleSheet(
            f"QFrame {{ background:#12082a; border:1px solid {ACCENT_PURPLE};"
            f"border-radius:8px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)

        lay.addWidget(_emoji("🔐", 14))

        texts = QVBoxLayout()
        title = QLabel("SAML / Web Authentication Required")
        title.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        title.setStyleSheet(
            f"color:{ACCENT_PURPLE}; background:transparent; border:none;")
        texts.addWidget(title)
        self._url_lbl = QLabel(
            "Browser should open automatically. "
            "Click the button if it didn't.")
        self._url_lbl.setFont(QFont("Segoe UI", 8))
        self._url_lbl.setStyleSheet(
            f"color:{TEXT_MUTED}; background:transparent; border:none;")
        self._url_lbl.setWordWrap(True)
        texts.addWidget(self._url_lbl)
        lay.addLayout(texts)

        self._btn = QPushButton("Open Browser")
        self._btn.setFixedHeight(34)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self._btn.setStyleSheet(f"""
            QPushButton {{ background:{ACCENT_PURPLE}; color:{BG_DARK};
                           border:none; border-radius:6px; padding:0 14px; }}
            QPushButton:hover {{ background:#d4a8ff; }}
            QPushButton:disabled {{ background:#3d2a5c; color:{TEXT_MUTED}; }}
        """)
        self._btn.clicked.connect(self._open)
        lay.addWidget(self._btn)
        self.hide()

    def show_waiting(self):
        """Show banner even before URL is known."""
        self._url = ""
        self._btn.setEnabled(False)
        self.show()

    def show_url(self, url: str):
        self._url = url
        short = url[:68] + "…" if len(url) > 68 else url
        self._url_lbl.setText(short)
        self._btn.setEnabled(True)
        self.show()

    def _open(self):
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))
        else:
            webbrowser.open(self._url)

    def clear(self):
        self._url = ""
        self.hide()


# ── Log panel ─────────────────────────────────────────────────────────────────
class LogPanel(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("JetBrains Mono, Consolas, Courier New", 8))
        self.setStyleSheet(f"""
            QTextEdit {{
                background:{BG_DARK}; color:{TEXT_MUTED};
                border:1px solid {BORDER}; border-radius:8px; padding:10px;
                selection-background-color:{ACCENT_CYAN};
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
            f'<span style="color:{color};">{line}</span>'
        )
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ── Small helpers ─────────────────────────────────────────────────────────────
def _emoji(ch: str, size: int = 13) -> QLabel:
    lbl = QLabel(ch)
    lbl.setFont(QFont("Segoe UI Emoji", size))
    return lbl


def make_btn(text, bg, hover, fg=TEXT_PRIMARY, dis="#2a3038"):
    b = QPushButton(text)
    b.setFixedHeight(44)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
    b.setStyleSheet(f"""
        QPushButton {{ background:{bg}; color:{fg}; border:none;
                       border-radius:8px; padding:0 20px; letter-spacing:.5px; }}
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


# ── Main window ───────────────────────────────────────────────────────────────
class OpenVPN3Client(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ovpn_path: str | None     = None
        self._session_path: str | None = None
        self._start_worker: StartWorker | None      = None
        self._auth_worker: AuthWorker | None        = None
        self._disc_worker: DisconnectWorker | None  = None
        self._poller: SessionPoller | None          = None
        self._state   = "idle"
        self._elapsed = 0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._build_ui()
        self._apply_state("idle")

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle("OpenVPN3 Client")
        self.setMinimumSize(700, 660)
        self.resize(760, 720)
        self.setStyleSheet(f"QMainWindow {{ background:{BG_DARK}; }}")

        root = QWidget()
        root.setStyleSheet(f"background:{BG_DARK};")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # Header
        hdr = QHBoxLayout()
        for txt, col in [("OpenVPN", TEXT_PRIMARY), ("3", ACCENT_CYAN)]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Segoe UI", 20, QFont.Bold))
            lbl.setStyleSheet(f"color:{col};")
            hdr.addWidget(lbl)
        sub = QLabel("CLIENT")
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet(
            f"color:{ACCENT_CYAN}; padding-top:9px; letter-spacing:2px;")
        hdr.addWidget(sub)
        hdr.addStretch()
        self.dot = StatusDot()
        hdr.addWidget(self.dot, alignment=Qt.AlignVCenter)
        self.status_lbl = QLabel("IDLE")
        self.status_lbl.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self.status_lbl.setStyleSheet(
            f"color:{TEXT_MUTED}; letter-spacing:1.5px;")
        hdr.addWidget(self.status_lbl, alignment=Qt.AlignVCenter)
        outer.addLayout(hdr)
        outer.addWidget(h_sep())

        # Config card
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:{BG_CARD}; border:1px solid {BORDER};"
            f"border-radius:12px; }}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(14)

        lbl = QLabel("Configuration File")
        lbl.setFont(QFont("Segoe UI", 9))
        lbl.setStyleSheet(
            f"color:{TEXT_MUTED}; letter-spacing:.5px;"
            f"background:transparent; border:none;")
        cl.addWidget(lbl)

        fr = QHBoxLayout()
        self.file_pill = FilePill()
        fr.addWidget(self.file_pill)
        self.browse_btn = make_btn("Browse", BG_PANEL, "#252d38")
        self.browse_btn.setFixedWidth(100)
        self.browse_btn.clicked.connect(self._browse)
        fr.addWidget(self.browse_btn)
        cl.addLayout(fr)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.box_duration = self._stat_box("Duration", "—")
        self.box_ip       = self._stat_box("Tunnel IP", "—")
        self.box_proto    = self._stat_box("Protocol", "—")
        self.box_status   = self._stat_box("Session", "—")
        for b in (self.box_duration, self.box_ip,
                  self.box_proto, self.box_status):
            stats.addWidget(b)
        cl.addLayout(stats)
        outer.addWidget(card)

        # SAML banner
        self.saml_banner = SAMLBanner()
        outer.addWidget(self.saml_banner)

        # Buttons
        br = QHBoxLayout()
        br.setSpacing(10)
        self.connect_btn = make_btn("⏵  Connect",     "#1a7f37", "#238636")
        self.connect_btn.clicked.connect(self._connect)
        br.addWidget(self.connect_btn)
        self.disconnect_btn = make_btn("⏹  Disconnect", "#7d1f1f", "#b62324")
        self.disconnect_btn.clicked.connect(self._disconnect)
        br.addWidget(self.disconnect_btn)
        self.clear_btn = make_btn("Clear Log", BG_PANEL, "#252d38")
        self.clear_btn.setFixedWidth(110)
        self.clear_btn.clicked.connect(lambda: self.log.clear())
        br.addWidget(self.clear_btn)
        outer.addLayout(br)

        # Log
        log_hdr = QLabel("Session Log")
        log_hdr.setFont(QFont("Segoe UI", 9))
        log_hdr.setStyleSheet(f"color:{TEXT_MUTED}; letter-spacing:.5px;")
        outer.addWidget(log_hdr)
        self.log = LogPanel()
        outer.addWidget(self.log)
        self.log.append_log(
            "Ready. Select an .ovpn file and click Connect.", ACCENT_CYAN)

    def _stat_box(self, label: str, value: str) -> QFrame:
        box = QFrame()
        box.setStyleSheet(
            f"QFrame {{ background:{BG_DARK}; border:1px solid {BORDER};"
            f"border-radius:8px; }}")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)
        lbl = QLabel(label.upper())
        lbl.setFont(QFont("Segoe UI", 7))
        lbl.setStyleSheet(
            f"color:{TEXT_MUTED}; letter-spacing:1.2px;"
            f"background:transparent; border:none;")
        v.addWidget(lbl)
        val = QLabel(value)
        val.setFont(QFont("JetBrains Mono, Consolas", 11, QFont.Bold))
        val.setStyleSheet(
            f"color:{TEXT_PRIMARY}; background:transparent; border:none;")
        val.setObjectName("val")
        v.addWidget(val)
        return box

    def _stat(self, box: QFrame) -> QLabel:
        return box.findChild(QLabel, "val")

    # ── State machine ─────────────────────────────────────────────────────────
    def _apply_state(self, state: str):
        self._state = state
        cfg = {
            "idle":          (TEXT_MUTED,    "IDLE",           True,  False, True),
            "connecting":    (ACCENT_ORANGE, "CONNECTING",     False, True,  False),
            "authing":       (ACCENT_PURPLE, "AUTHENTICATING", False, True,  False),
            "connected":     (ACCENT_GREEN,  "CONNECTED",      False, True,  False),
            "disconnecting": (ACCENT_ORANGE, "DISCONNECTING",  False, False, False),
            "error":         (ACCENT_RED,    "ERROR",          True,  False, True),
        }
        col, label, conn_en, disc_en, browse_en = cfg.get(
            state, (TEXT_MUTED, "IDLE", True, False, True))
        self.dot.set_state(state)
        self.status_lbl.setText(label)
        self.status_lbl.setStyleSheet(f"color:{col}; letter-spacing:1.5px;")
        self.connect_btn.setEnabled(conn_en)
        self.disconnect_btn.setEnabled(disc_en)
        self.browse_btn.setEnabled(browse_en)
        if state == "connected":
            self._elapsed = 0
            self._elapsed_timer.start(1000)
        elif state == "idle":
            self._elapsed_timer.stop()
            self._stat(self.box_duration).setText("—")
            self._stat(self.box_ip).setText("—")
            self._stat(self.box_status).setText("—")
            self.saml_banner.clear()
            self._session_path = None
            self._stop_poller()

    def _tick_elapsed(self):
        self._elapsed += 1
        h = self._elapsed // 3600
        m = (self._elapsed % 3600) // 60
        s = self._elapsed % 60
        self._stat(self.box_duration).setText(f"{h:02d}:{m:02d}:{s:02d}")

    # ── Browse ────────────────────────────────────────────────────────────────
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select OpenVPN3 Config", "",
            "OpenVPN Config (*.ovpn *.conf);;All Files (*)")
        if not path:
            return
        self.ovpn_path = path
        self.file_pill.set_path(path)
        self.log.append_log(f"Config: {os.path.basename(path)}", ACCENT_CYAN)
        try:
            with open(path) as f:
                content = f.read().lower()
            proto = ("UDP" if "proto udp" in content
                     else "TCP" if "proto tcp" in content else "—")
            self._stat(self.box_proto).setText(proto)
        except Exception:
            pass

    # ── Connect ───────────────────────────────────────────────────────────────
    def _connect(self):
        if not self.ovpn_path or not os.path.isfile(self.ovpn_path):
            self.log.append_log(
                "No valid config file selected.", ACCENT_RED)
            return
        self._apply_state("connecting")
        self._stat(self.box_status).setText("starting")
        self.log.append_log(
            f"openvpn3 session-start --config {self.ovpn_path}", ACCENT_CYAN)

        self._start_worker = StartWorker(self.ovpn_path)
        self._start_worker.log_line.connect(self._on_log)
        self._start_worker.session_path.connect(self._on_session_path)
        self._start_worker.needs_auth.connect(self._on_needs_auth)
        self._start_worker.error.connect(self._on_error)
        self._start_worker.start()

    # ── Disconnect ────────────────────────────────────────────────────────────
    def _disconnect(self):
        self._elapsed_timer.stop()
        self._stop_poller()
        self._apply_state("disconnecting")
        self.log.append_log("Disconnecting…", ACCENT_ORANGE)

        if self._start_worker and self._start_worker.isRunning():
            self._start_worker.terminate()
        if self._auth_worker and self._auth_worker.isRunning():
            self._auth_worker.terminate()

        self._disc_worker = DisconnectWorker(self._session_path, self.ovpn_path)
        self._disc_worker.log_line.connect(
            lambda l: self.log.append_log(l, TEXT_MUTED))
        self._disc_worker.done.connect(self._on_disc_done)
        self._disc_worker.start()

    # ── StartWorker signals ───────────────────────────────────────────────────
    def _on_session_path(self, path: str):
        self._session_path = path
        self._stat(self.box_status).setText("auth pending")
        self.log.append_log(f"Session path: {path}", ACCENT_CYAN)

    def _on_needs_auth(self):
        """openvpn3 said web auth is needed — show banner, fetch URL."""
        self._apply_state("authing")
        self.saml_banner.show_waiting()
        self.log.append_log(
            "Web authentication required — fetching SAML URL…", ACCENT_PURPLE)

        if self._session_path:
            self._auth_worker = AuthWorker(self._session_path)
            self._auth_worker.log_line.connect(self._on_log)
            self._auth_worker.auth_url.connect(self._on_auth_url)
            self._auth_worker.start()

        # Start polling sessions-list for Connected status
        self._start_poller()

    # ── AuthWorker signals ────────────────────────────────────────────────────
    def _on_auth_url(self, url: str):
        self.saml_banner.show_url(url)
        self.log.append_log(f"Auth URL: {url}", ACCENT_PURPLE)
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
            lambda s: self._stat(self.box_status).setText(s))
        self._poller.connected.connect(self._on_connected)
        self._poller.start()

    def _stop_poller(self):
        if self._poller:
            self._poller.stop()
            self._poller = None

    # ── Connected ─────────────────────────────────────────────────────────────
    def _on_connected(self):
        self._apply_state("connected")
        self.saml_banner.clear()
        self._stat(self.box_status).setText("connected")
        self.log.append_log("✓ VPN tunnel is up.", ACCENT_GREEN)
        # Try to read tunnel IP from sessions-list
        self._refresh_ip()

    def _refresh_ip(self):
        if not self._session_path:
            return
        _, out = _run(["openvpn3", "sessions-list"], timeout=8)
        for line in out.splitlines():
            m = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
            if m:
                self._stat(self.box_ip).setText(m.group(1))
                break

    # ── Generic log colouring ─────────────────────────────────────────────────
    def _on_log(self, line: str):
        ll = line.lower()
        if any(k in ll for k in ("error", "failed", "auth_failed")):
            color = ACCENT_RED
        elif any(k in ll for k in ("warning", "deprecated")):
            color = ACCENT_ORANGE
        elif any(k in ll for k in ("connected", "session is ready")):
            color = ACCENT_GREEN
        elif any(k in ll for k in ("saml", "browser", "https://",
                                    "authenticate", "webauth", "web auth",
                                    "web based")):
            color = ACCENT_PURPLE
        elif any(k in ll for k in ("tls", "verify", "tun",
                                    "ifconfig", "route", "session path")):
            color = ACCENT_CYAN
        else:
            color = TEXT_MUTED
        self.log.append_log(line, color)

    def _on_error(self, msg: str):
        self._stop_poller()
        self._apply_state("error")
        self.log.append_log(f"ERROR: {msg}", ACCENT_RED)

    # ── DisconnectWorker ──────────────────────────────────────────────────────
    def _on_disc_done(self, ok: bool, msg: str):
        self.log.append_log(msg, ACCENT_GREEN if ok else ACCENT_RED)
        self._apply_state("idle")

    # ── Close ─────────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self._stop_poller()
        for w in (self._start_worker, self._auth_worker, self._disc_worker):
            if w and w.isRunning():
                w.terminate()
                w.wait(2000)
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