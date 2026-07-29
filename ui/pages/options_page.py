"""
ui/pages/options_page.py – Options page: OSC target, OSCQuery, updates, fixes, sending, debug.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.
"""

import json
import os
import shutil
import sys
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)
from core import desktop_integration, queryfix, vrc_pictures
from core.constants import (
    CHATBOX_INPUT, DISCORD_URL, DONATE_URL, GITHUB_REPO, VERSION, VRCHAT_GROUP_URL)
from core.oscquery import HAS_ZEROCONF
from ui.ui_main import ToggleLabel, ToggleSwitch
try:
    from pythonosc.udp_client import SimpleUDPClient
except ImportError:
    print("Error: python-osc is not installed.  ->  pip install python-osc")
    sys.exit(1)


class OptionsPageMixin:
    def build_options_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("Options")
        title.setObjectName("pagetitle")
        layout.addWidget(title)

        # ---------------- OSCQuery Fix (core/queryfix.py) ----------------
        qcard = QFrame()
        qcard.setObjectName("card")
        qc = QVBoxLayout(qcard)
        qc.setContentsMargins(16, 14, 16, 16)
        qc.setSpacing(10)
        qhead = QHBoxLayout()
        qtitle = QLabel("OSCQuery")
        qtitle.setObjectName("cardtitle")
        qhead.addWidget(qtitle)
        qhead.addStretch()
        self.queryfix_btn = QPushButton("\U0001F527  Fix OSCQuery")
        self.queryfix_btn.setObjectName("sendbtn")
        self.queryfix_btn.setFixedHeight(30)
        self.queryfix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.queryfix_btn.clicked.connect(self.on_queryfix)
        qhead.addWidget(self.queryfix_btn)
        qc.addLayout(qhead)
        qdesc = QLabel("Native OSCQuery: on startup the app picks a free "
                       "dynamic port, registers itself via mDNS and "
                       "discovers the real OSC input port of the running "
                       "VRChat instance – no more hard-coded 9000/9001, "
                       "no port conflicts with other VR tools.")
        qdesc.setObjectName("dim")
        qdesc.setWordWrap(True)
        qc.addWidget(qdesc)
        qtog_row = QHBoxLayout()
        self.toggle_oscquery = ToggleSwitch()
        self.toggle_oscquery.toggled.connect(self.on_oscquery_toggled)
        qtog_row.addWidget(self.toggle_oscquery)
        qtog_row.addWidget(ToggleLabel(
            "Native OSCQuery (dynamic port + VRChat auto-detect)",
            self.toggle_oscquery))
        qtog_row.addStretch()
        qc.addLayout(qtog_row)
        self.oscq_status = QLabel("")
        self.oscq_status.setObjectName("dim")
        self.oscq_status.setWordWrap(True)
        qc.addWidget(self.oscq_status)
        if not HAS_ZEROCONF:
            self.toggle_oscquery.setEnabled(False)

        qline = QFrame()
        qline.setFrameShape(QFrame.Shape.HLine)
        qline.setObjectName("hline")
        qc.addWidget(qline)

        qfix_desc = QLabel("\"Fix OSCQuery\" enables OSCQuery directly in "
                           "the config of every supported program (all "
                           "other settings in the file stay untouched). "
                           "The program list lives in core/queryfix.py – "
                           "easy to extend.")
        qfix_desc.setObjectName("dim")
        qfix_desc.setWordWrap(True)
        qc.addWidget(qfix_desc)

        # collapsible, scrollable list of supported programs
        self.qf_expander = QPushButton(
            "\u25B8  Show supported programs "
            f"({len(queryfix.PROGRAMS)})")
        self.qf_expander.setObjectName("expander")
        self.qf_expander.setCursor(Qt.CursorShape.PointingHandCursor)
        self.qf_expander.clicked.connect(self.on_qf_expand)
        qc.addWidget(self.qf_expander)

        self.qf_body = QWidget()
        qfb = QVBoxLayout(self.qf_body)
        qfb.setContentsMargins(12, 0, 0, 0)
        qfb.setSpacing(6)
        self.qf_list = QListWidget()
        self.qf_list.setMaximumHeight(140)   # fixed height -> scrollbar
        self.qf_list.setStyleSheet(
            "QListWidget { background: #14161c; border: 1px solid #2c313c;"
            " border-radius: 10px; padding: 4px; }"
            "QListWidget::item { padding: 5px 8px; border-radius: 6px; }"
            "QListWidget::item:hover { background: #232833; }"
            "QListWidget::item:selected { background: #2a2f3a;"
            " color: #ffffff; }")
        for prog in queryfix.PROGRAMS:
            self.qf_list.addItem(prog["name"])
        self.qf_list.itemClicked.connect(self.on_qf_select)
        qfb.addWidget(self.qf_list)
        # per-program details, fold in/out on click
        self.qf_details = QFrame()
        self.qf_details.setObjectName("innerbox")
        qfd = QVBoxLayout(self.qf_details)
        qfd.setContentsMargins(14, 10, 14, 12)
        self.qf_details_lbl = QLabel("")
        self.qf_details_lbl.setObjectName("dim")
        self.qf_details_lbl.setStyleSheet(
            "font-family: monospace; font-size: 12px;")
        self.qf_details_lbl.setWordWrap(True)
        qfd.addWidget(self.qf_details_lbl)
        self.qf_details.hide()
        self._qf_details_idx = -1
        qfb.addWidget(self.qf_details)
        self.qf_body.hide()
        qc.addWidget(self.qf_body)

        self.queryfix_result = QLabel("")
        self.queryfix_result.setObjectName("dim")
        self.queryfix_result.setWordWrap(True)
        qc.addWidget(self.queryfix_result)
        layout.addWidget(qcard)

        card = QFrame()
        card.setObjectName("card")
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 14, 16, 16)
        c.setSpacing(14)

        # Slim Chatbox – default ON
        row = QHBoxLayout()
        self.toggle_slim = ToggleSwitch()
        self.toggle_slim.toggled.connect(self.on_slim_toggled)
        row.addWidget(self.toggle_slim)
        row.addWidget(ToggleLabel('Slim Chatbox  (slim bar instead of big box – "BlankEgg" trick)',
                                  self.toggle_slim))
        row.addStretch()
        c.addLayout(row)
        hint = QLabel("Appends invisible characters (\\u0003\\u001f) to the text so "
                      "VRChat renders the chatbox as a slim bar only. Default: ON")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        c.addWidget(hint)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setObjectName("hline")
        c.addWidget(line)

        # Send interval – "sec" outside the field
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Send to OSC every"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setObjectName("smallspin")
        self.interval_spin.setRange(2, 300)   # VRChat throttles anything below ~2s
        self.interval_spin.setFixedSize(64, 28)
        self.interval_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.interval_spin.valueChanged.connect(self.on_interval_changed)
        interval_row.addWidget(self.interval_spin)
        interval_row.addWidget(QLabel("sec"))
        interval_row.addStretch()
        c.addLayout(interval_row)

        line2 = QFrame(); line2.setFrameShape(QFrame.Shape.HLine); line2.setObjectName("hline")
        c.addWidget(line2)

        # OSC target
        c.addWidget(QLabel("OSC target (VRChat):"))
        osc_row = QHBoxLayout()
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("127.0.0.1")
        self.ip_input.editingFinished.connect(self.on_osc_target_changed)
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(9000)
        self.port_input.valueChanged.connect(self.on_osc_target_changed)
        osc_row.addWidget(QLabel("IP:"))
        osc_row.addWidget(self.ip_input, 1)
        osc_row.addWidget(QLabel("Port:"))
        osc_row.addWidget(self.port_input)
        c.addLayout(osc_row)
        hint2 = QLabel("Default: 127.0.0.1 : 9000 – do not change unless VRChat runs "
                       "on another PC. OSC must be enabled in VRChat "
                       "(Action Menu → Options → OSC → Enabled).")
        hint2.setObjectName("dim")
        hint2.setWordWrap(True)
        c.addWidget(hint2)

        layout.addWidget(card)

        # ----- Community & Updates -----
        ucard = QFrame()
        ucard.setObjectName("card")
        uc = QVBoxLayout(ucard)
        uc.setContentsMargins(16, 14, 16, 16)
        uc.setSpacing(10)
        ut = QLabel("Community & Updates")
        ut.setObjectName("cardtitle")
        uc.addWidget(ut)

        btn_row = QHBoxLayout()
        upd_btn = QPushButton("\U0001F504  Check for updates")
        upd_btn.setObjectName("sendbtn")
        upd_btn.setFixedHeight(34)
        upd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        upd_btn.clicked.connect(self.check_for_updates)
        btn_row.addWidget(upd_btn)
        dc_btn = QPushButton("\U0001F4AC  Discord")
        dc_btn.setObjectName("linkbtn")
        dc_btn.setFixedHeight(34)
        dc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dc_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DISCORD_URL)))
        btn_row.addWidget(dc_btn)
        don_btn = QPushButton("\u2615  Support on Ko-fi")
        don_btn.setObjectName("linkbtn")
        don_btn.setFixedHeight(34)
        don_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        don_btn.setToolTip("Support development on Ko-fi")
        don_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        btn_row.addWidget(don_btn)

        vrc_btn = QPushButton("\U0001F465  VRChat Group")
        vrc_btn.setObjectName("linkbtn")
        vrc_btn.setFixedHeight(34)
        vrc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        vrc_btn.setToolTip("Join the OSC-DreamChatbox VRChat group")
        vrc_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(VRCHAT_GROUP_URL)))
        btn_row.addWidget(vrc_btn)

        btn_row.addStretch()
        uc.addLayout(btn_row)

        # App Tray Fix sits on its own row directly under "Check for updates"
        fix_row = QHBoxLayout()
        self.tray_fix_btn = QPushButton("\U0001F527  App Tray Fix")
        self.tray_fix_btn.setObjectName("linkbtn")
        self.tray_fix_btn.setFixedHeight(34)
        self.tray_fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tray_fix_btn.setToolTip(
            "Registers a desktop entry so the correct taskbar/tray icon shows "
            "and the app appears in your application menu. For install-script "
            "users – does nothing if an entry already exists.")
        self.tray_fix_btn.clicked.connect(self.run_app_tray_fix)
        fix_row.addWidget(self.tray_fix_btn)

        self.vrc_pic_btn = QPushButton("\U0001F5BC\uFE0F  VRC Picture Folder Fix")
        self.vrc_pic_btn.setObjectName("linkbtn")
        self.vrc_pic_btn.setFixedHeight(34)
        self.vrc_pic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vrc_pic_btn.setToolTip(
            "Creates a symlink so VRChat's camera photos – normally saved "
            "inside the Proton prefix – land directly in your Linux Pictures "
            "folder (~/Pictures/VRChat). Existing photos in the prefix are "
            "moved over. Does nothing if it's already set up.")
        self.vrc_pic_btn.clicked.connect(self.run_vrc_picture_fix)
        fix_row.addWidget(self.vrc_pic_btn)

        fix_row.addStretch()
        uc.addLayout(fix_row)

        self.update_lbl = QLabel(f"Current version: {VERSION}")
        self.update_lbl.setObjectName("dim")
        self.update_lbl.setWordWrap(True)
        self.update_lbl.setOpenExternalLinks(True)
        uc.addWidget(self.update_lbl)
        # Community & Updates goes to the TOP of the page (index 0 is the
        # "Options" title, so this card lands right underneath it)
        layout.insertWidget(1, ucard)

        layout.addStretch()
        return page

    def _aur_helper(self):
        """The installed AUR helper ('yay' or 'paru', yay preferred), or
        None if neither is on PATH."""
        for helper in ("yay", "paru"):
            if shutil.which(helper):
                return helper
        return None

    def _install_kind(self):
        """How this instance was installed – decides the update guidance.
        'appimage' | 'aur' (system package) | 'source' (script/git)."""
        if os.environ.get("APPIMAGE"):
            return "appimage"
        try:
            if desktop_integration.system_entry_present():
                return "aur"
        except Exception:
            pass
        if os.path.exists("/usr/bin/osc-dreamchatbox"):
            return "aur"
        return "source"

    def check_for_updates(self):
        self.update_lbl.setText("Checking for updates \u2026")

        def work():
            import urllib.request
            try:
                url = (f"https://api.github.com/repos/{GITHUB_REPO}"
                       "/releases/latest")
                req = urllib.request.Request(
                    url, headers={"User-Agent": "OSC-DreamChatbox"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = json.loads(r.read().decode("utf-8"))
                return (data.get("tag_name", ""), data.get("html_url", ""))
            except Exception as e:
                return ("__error__", str(e))
        self.run_async(work, self._on_update_result, interval=250)

    def _on_update_result(self, result):
        tag, info = result
        if tag == "__error__":
            self.update_lbl.setText(
                f"Update check failed (no releases yet or offline). "
                f"Current version: {VERSION}")
        elif tag and tag != VERSION:
            kind = self._install_kind()
            if kind == "appimage":
                how = (f" \u2013 <a href=\"{info}\">download the new "
                       "AppImage from the release page</a>")
            elif kind == "aur":
                helper = self._aur_helper()
                if helper:
                    how = (f" \u2013 update via {helper}: "
                           f"{helper} -S osc-dreamchatbox "
                           f"(or <a href=\"{info}\">release page</a>)")
                else:
                    how = (" \u2013 update with your AUR helper "
                           "(yay or paru), e.g. yay -S osc-dreamchatbox "
                           f"(or <a href=\"{info}\">release page</a>)")
            else:
                how = (f" \u2013 <a href=\"{info}\">open download page</a>, "
                       "or update with git pull / re-run install.sh")
            self.update_lbl.setText(
                f"\U0001F389 New version available: <b>{tag}</b> "
                f"(you have {VERSION}){how}")
        else:
            self.update_lbl.setText(
                f"\u2705 You are up to date ({VERSION}).")

    def run_app_tray_fix(self):
        """Leaves a correct entry alone (AUR entry, or an already-current
        user entry with the themed icon). Only when the existing entry is
        old/incomplete – e.g. a previous fix without the icon fix – does it
        delete it and create a fresh one."""
        if desktop_integration.is_installed():
            QMessageBox.information(
                self, "App Tray Fix",
                "A desktop entry already exists \u2013 nothing to do.")
            return
        try:
            changed, msg = desktop_integration.install_desktop_entry()
        except OSError as e:
            QMessageBox.critical(
                self, "App Tray Fix", f"Could not create desktop entry:\n{e}")
            return
        box = QMessageBox.information if changed else QMessageBox.warning
        box(self, "App Tray Fix", msg)

    def run_vrc_picture_fix(self):
        """Symlink the in-prefix VRChat picture folder to the Linux Pictures
        folder – only if it isn't already set up."""
        if vrc_pictures.is_fixed():
            QMessageBox.information(
                self, "VRC Picture Folder Fix",
                "Already set up \u2013 VRChat photos already land in your "
                "Linux Pictures folder.")
            return
        try:
            changed, msg = vrc_pictures.install_picture_fix()
        except OSError as e:
            QMessageBox.critical(
                self, "VRC Picture Folder Fix",
                f"Could not apply the fix:\n{e}")
            return
        box = QMessageBox.information if changed else QMessageBox.warning
        box(self, "VRC Picture Folder Fix", msg)

    def on_send_toggled(self, on):
        self.cfg["send_to_vrchat"] = on
        self.save_config()
        self.log(f"SendToVRChat: {'ON' if on else 'OFF'}")
        self.update_timers()
        if on:
            self.send_now()  # send once immediately
        else:
            # clear the chatbox in VRChat right away – otherwise the
            # last text keeps hanging there for minutes
            self.clear_chatbox()

    def clear_chatbox(self):
        """Sends one empty chatbox message so VRChat removes the
        currently shown text immediately."""
        if self.osc_client is None:
            return
        try:
            self.osc_client.send_message(CHATBOX_INPUT, ["", True, False])
            self.log(f"-> OSC {CHATBOX_INPUT} cleared (empty message)")
        except Exception as e:
            self.log(f"ERROR while clearing chatbox: {e}")

    def on_debug_toggled(self, on):
        self.cfg["debug"] = on
        self.save_config()
        if on:
            self.debug_console.show()
            self.log("Debug mode ON – console opened")
        else:
            self.debug_console.hide()

    def on_interval_changed(self, val):
        self.cfg["interval_sec"] = val
        self.save_config()
        self.log(f"Send interval: every {val} seconds")
        self.update_timers()

    def on_qf_expand(self):
        """Folds the supported-programs list in/out."""
        show = self.qf_body.isHidden()
        self.qf_body.setVisible(show)
        n = len(queryfix.PROGRAMS)
        self.qf_expander.setText(
            ("\u25BE  Hide supported programs" if show
             else f"\u25B8  Show supported programs ({n})"))
        if not show:
            self.qf_details.hide()
            self._qf_details_idx = -1

    def on_qf_select(self, item):
        """Click on a program: fold its details (path + parameter)
        in/out below the list."""
        idx = self.qf_list.row(item)
        if idx == self._qf_details_idx and not self.qf_details.isHidden():
            self.qf_details.hide()
            self._qf_details_idx = -1
            self.qf_list.clearSelection()
            return
        prog = queryfix.PROGRAMS[idx]
        self.qf_details_lbl.setText(
            f"{prog['name']}\n"
            f"      path:      {prog['path']}\n"
            f"      parameter: \"{prog['key']}\": "
            f"{json.dumps(prog['value'])}")
        self.qf_details.show()
        self._qf_details_idx = idx

    def on_queryfix(self):
        """'Fix OSCQuery' button: writes the OSCQuery parameter into the
        config of every supported program (list in core/queryfix.py)."""
        results = queryfix.fix_all(self.log)
        parts = [f"{'\u2705' if ok else '\u274C'} {name}: {msg}"
                 for name, ok, msg in results]
        self.queryfix_result.setText("\n".join(parts)
                                     + "\n\u21BB Restart the programs to "
                                       "apply the change.")

    def on_slim_toggled(self, on):
        self.cfg["slim_chatbox"] = on
        self.save_config()
        self.log(f"Slim Chatbox (slim bar mode): {'ON' if on else 'OFF'}")

    def on_osc_target_changed(self):
        self.cfg["osc_ip"] = self.ip_input.text().strip() or "127.0.0.1"
        self.cfg["osc_port"] = self.port_input.value()
        self.save_config()
        self.update_osc_client()

    def update_osc_client(self):
        """Creates the UDP client. With native OSCQuery active and a
        discovered VRChat instance, its REAL input port is used –
        otherwise the manually configured target (fallback)."""
        ip, port = self.cfg["osc_ip"], self.cfg["osc_port"]
        via = ""
        if self.cfg.get("oscquery_enabled"):
            target = self.oscq.vrchat_target()
            if target is not None:
                ip, port = target
                via = " (via OSCQuery)"
        try:
            self.osc_client = SimpleUDPClient(ip, port)
            self.log(f"OSC target: {ip}:{port}{via}")
        except Exception as e:
            self.osc_client = None
            self.log(f"ERROR creating OSC client: {e}")

    def poll_oscquery(self):
        """Checks the discovery thread and applies a newly found (or
        lost) VRChat target. Cheap by design: the mDNS browser is
        event-driven (no active re-scanning), this timer only reads a
        flag. Once VRChat is found the interval slows to 10 s; the
        label is only repainted when the text actually changes."""
        target = self.oscq.vrchat_target()
        if target != self._oscq_applied:
            self._oscq_applied = target
            self.update_osc_client()
        # adaptive interval: fast while searching, relaxed once found
        want = 10000 if target is not None else 2000
        if self.oscq_timer.interval() != want:
            self.oscq_timer.setInterval(want)
        if hasattr(self, "oscq_status"):
            if not self.cfg.get("oscquery_enabled"):
                txt = "OSCQuery off – manual target is used."
            elif not HAS_ZEROCONF:
                txt = ("zeroconf not installed "
                       "(pip install zeroconf) – manual target is used.")
            elif not self.oscq.running:
                txt = (f"not running ({self.oscq.error}) – "
                       "manual target is used.")
            elif target is not None:
                txt = (f"\u2705 VRChat found: {target[0]}:{target[1]} "
                       f"\u2013 registered as dynamic udp/"
                       f"{self.oscq.osc_port}, http/{self.oscq.http_port}")
            else:
                txt = (f"\u23F3 searching for VRChat \u2026 registered "
                       f"as dynamic udp/{self.oscq.osc_port}, "
                       f"http/{self.oscq.http_port} "
                       "(manual target used until found)")
            if self.oscq_status.text() != txt:
                self.oscq_status.setText(txt)

    def on_oscquery_toggled(self, on):
        self.cfg["oscquery_enabled"] = bool(on)
        self.save_config()
        if on and HAS_ZEROCONF:
            if self.oscq.start():
                self.oscq_timer.start(2000)
        else:
            self.oscq_timer.stop()
            self.oscq.stop()
            self._oscq_applied = None
        self.update_osc_client()
        self.poll_oscquery()
