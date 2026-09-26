"""
ui/pages/options_page.py – Options page, split into three tabs:

    General   Community & Updates, Highlights + Changelog, Linux fixes
    OSC       OSCQuery / OSC input / hotkeys, Slim Chatbox, sending, target
    Design    theme, colours, background

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QColorDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)
from core import desktop_integration, profiles, queryfix, vrc_pictures
from core.theming import (
    TOKEN_LABELS, import_background, list_backgrounds, remove_background,
    resolve_tokens, theme_ids, theme_name)
from core.constants import (
    CHATBOX_INPUT, DISCORD_URL, DONATE_URL, GITHUB_REPO, OSC_MIN_SEND_GAP_SEC, OSC_RATE_MAX_SENDS, OSC_RATE_WINDOW_SEC, VERSION, VRCHAT_GROUP_URL)
from core.oscin import DEFAULT_IN_PORT
from core.oscquery import HAS_ZEROCONF
from core.plugin_store import compare_versions
from core.osinfo import IS_WINDOWS, OS_NAME
from ui.docviewer import CHANGELOG_FILE, HIGHLIGHTS_FILE, show_doc
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

        # ---- General / OSC / Design switch ---------------------------
        # Same look and placement as Installed / Store on the Plugins
        # page: own row under the title, packed left, so a narrow window
        # never cuts them off.
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(8)
        self.options_tab_group = QButtonGroup(self)
        self.options_tab_group.setExclusive(True)
        for i, label in enumerate(("\u2699\uFE0F  General",
                                   "\U0001F4E1  OSC",
                                   "\U0001F3A8  Design")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedHeight(30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton { background: #232833; border: 1px solid #333947;"
                " border-radius: 8px; color: #aeb4bf; padding: 0 14px; }"
                "QPushButton:hover { border-color: #5b8dc9; }"
                "QPushButton:checked { background: #5b8dc9;"
                " border-color: #5b8dc9; color: #ffffff; }")
            self.options_tab_group.addButton(b, i)
            tabs_row.addWidget(b)
        tabs_row.addStretch()
        self.options_tab_group.button(0).setChecked(True)
        self.options_tab_group.idClicked.connect(self.on_options_tab)
        layout.addLayout(tabs_row)

        # one plain widget per tab; the cards below are added to these
        # instead of straight to the page
        tab_general, tab_osc, tab_design = QWidget(), QWidget(), QWidget()
        general_lay, osc_lay, design_lay = (
            QVBoxLayout(tab_general), QVBoxLayout(tab_osc),
            QVBoxLayout(tab_design))
        for lay in (general_lay, osc_lay, design_lay):
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(16)

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

        # ---- OSC input (core/oscin.py) -------------------------------
        # Off by default and on purpose: this binds a port, and 9001 is
        # exactly the port every other OSC tool wants as well. Switching
        # it on is a decision, not a default.
        iline = QFrame()
        iline.setFrameShape(QFrame.Shape.HLine)
        iline.setObjectName("hline")
        qc.addWidget(iline)

        itog_row = QHBoxLayout()
        self.toggle_osc_in = ToggleSwitch()
        self.toggle_osc_in.toggled.connect(self.on_osc_input_toggled)
        itog_row.addWidget(self.toggle_osc_in)
        itog_row.addWidget(ToggleLabel(
            "Receive avatar parameters (OSC input)", self.toggle_osc_in))
        itog_row.addSpacing(16)
        itog_row.addWidget(QLabel("Port"))
        self.osc_in_port = QSpinBox()
        self.osc_in_port.setRange(1024, 65535)
        self.osc_in_port.setFixedWidth(90)
        self.osc_in_port.valueChanged.connect(self.on_osc_input_port)
        itog_row.addWidget(self.osc_in_port)
        itog_row.addStretch()
        qc.addLayout(itog_row)

        idesc = QLabel(
            "Lets the Advanced mode canvas read your avatar's toggles, "
            "sliders and menu values \u2013 the \u201cAvatar parameter\u201d "
            "block. VRChat sends them to 9001 by default; with native "
            "OSCQuery on, the dynamically negotiated port is used "
            "instead. Nothing else in the app reads OSC, so leaving this "
            "off costs you only those blocks.")
        idesc.setObjectName("dim")
        idesc.setWordWrap(True)
        qc.addWidget(idesc)

        ext_row = QHBoxLayout()
        ext_row.addWidget(QLabel("External OSC target"))
        self.osc_ext_ip = QLineEdit()
        self.osc_ext_ip.setFixedWidth(140)
        self.osc_ext_ip.setPlaceholderText("127.0.0.1")
        self.osc_ext_ip.editingFinished.connect(self.on_osc_ext_ip)
        ext_row.addWidget(self.osc_ext_ip)
        ext_row.addWidget(QLabel("Port"))
        self.osc_ext_port = QSpinBox()
        self.osc_ext_port.setRange(1, 65535)
        self.osc_ext_port.setFixedWidth(90)
        self.osc_ext_port.valueChanged.connect(self.on_osc_ext_port)
        ext_row.addWidget(self.osc_ext_port)
        ext_row.addStretch()
        qc.addLayout(ext_row)
        ext_desc = QLabel(
            "Where the \u201cExternal OSC out\u201d block sends when it "
            "has no target of its own \u2013 a script, a smart home "
            "bridge, anything that speaks OSC. Separate from the VRChat "
            "target above on purpose, so pointing one somewhere else "
            "cannot break the chatbox.")
        ext_desc.setObjectName("dim")
        ext_desc.setWordWrap(True)
        qc.addWidget(ext_desc)

        kline = QFrame()
        kline.setFrameShape(QFrame.Shape.HLine)
        kline.setObjectName("hline")
        qc.addWidget(kline)

        ktog_row = QHBoxLayout()
        self.toggle_hotkey_in = ToggleSwitch()
        self.toggle_hotkey_in.toggled.connect(self.on_hotkey_input_toggled)
        ktog_row.addWidget(self.toggle_hotkey_in)
        ktog_row.addWidget(ToggleLabel(
            "Watch the keyboard (Get Hotkey block)", self.toggle_hotkey_in))
        ktog_row.addStretch()
        qc.addLayout(ktog_row)

        kdesc = QLabel(
            "Lets the \u201cGet Hotkey\u201d block on the Advanced canvas "
            "react to a key combination pressed anywhere, not just in "
            "VRChat. It watches which keys are down and never swallows "
            "them or records what you type \u2013 but it is still the "
            "keyboard, so it stays off until you switch it on. On Linux "
            "it reads /dev/input, which usually means your user has to "
            "be in the \u201cinput\u201d group.")
        kdesc.setObjectName("dim")
        kdesc.setWordWrap(True)
        qc.addWidget(kdesc)

        self.hotkey_in_status = QLabel("")
        self.hotkey_in_status.setObjectName("dim")
        self.hotkey_in_status.setWordWrap(True)
        qc.addWidget(self.hotkey_in_status)

        self.osc_in_status = QLabel("")
        self.osc_in_status.setObjectName("dim")
        self.osc_in_status.setWordWrap(True)
        qc.addWidget(self.osc_in_status)

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
            "font-family: Consolas, monospace; font-size: 12px;")
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
        osc_lay.addWidget(qcard)

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

        # Instant send: push a changed text straight to VRChat instead of
        # waiting for the next tick above. Community request - the app
        # preview updated instantly while VRChat lagged behind by a whole
        # interval. Always stays inside VRChat's chatbox rate limit.
        instant_row = QHBoxLayout()
        self.toggle_instant = ToggleSwitch()
        self.toggle_instant.toggled.connect(self.on_instant_send_toggled)
        instant_row.addWidget(self.toggle_instant)
        instant_row.addWidget(ToggleLabel("Send changes instantly",
                                          self.toggle_instant))
        instant_row.addStretch()
        c.addLayout(instant_row)
        instant_hint = QLabel(
            "A changed text goes to VRChat right away instead of waiting "
            "for the interval above. Stays within VRChat's chatbox limit "
            f"({OSC_RATE_MAX_SENDS} messages per "
            f"{int(OSC_RATE_WINDOW_SEC)} s, min "
            f"{OSC_MIN_SEND_GAP_SEC:g} s apart) - going over it makes "
            "VRChat hide the chatbox for about 30 seconds, so extra "
            "sends are delayed, never dropped.")
        instant_hint.setObjectName("dim")
        instant_hint.setWordWrap(True)
        c.addWidget(instant_hint)

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

        osc_lay.addWidget(card)
        design_lay.addWidget(self.build_customization_card())

        # ----- General: three cards, one job each ---------------------
        # 1 Updates    what version you have, what changed
        # 2 Community  where to talk to people / support the project
        # 3 Fixes      one-off repairs for Linux desktops

        # 1 ---- Updates
        upd_card, upd = self._opt_card(
            "Updates",
            "Check whether a new version is out, and read what changed.")
        upd_row = QHBoxLayout()
        upd_row.setSpacing(8)
        upd_row.addWidget(self._opt_button(
            "\U0001F504  Check for updates", "sendbtn",
            self.check_for_updates))
        upd_row.addWidget(self._opt_button(
            "\u2728  Highlights", "linkbtn",
            lambda: show_doc(self, "Highlights", HIGHLIGHTS_FILE),
            "The most important changes of every release, in a few lines each"))
        upd_row.addWidget(self._opt_button(
            "\U0001F4DC  Changelog", "linkbtn",
            lambda: show_doc(self, "Changelog", CHANGELOG_FILE),
            "Every change in detail"))
        upd_row.addStretch()
        upd.addLayout(upd_row)

        self.update_lbl = QLabel(f"Current version: {VERSION}")
        self.update_lbl.setObjectName("dim")
        self.update_lbl.setWordWrap(True)
        self.update_lbl.setOpenExternalLinks(True)
        upd.addWidget(self.update_lbl)
        general_lay.addWidget(upd_card)

        # 2 ---- Community
        com_card, com = self._opt_card(
            "Community",
            "Questions, ideas and bug reports are welcome on Discord.")
        com_row = QHBoxLayout()
        com_row.setSpacing(8)
        com_row.addWidget(self._opt_button(
            "\U0001F4AC  Discord", "linkbtn",
            lambda: QDesktopServices.openUrl(QUrl(DISCORD_URL)),
            "Join the OSC-DreamChatbox Discord server"))
        com_row.addWidget(self._opt_button(
            "\u2615  Support on Ko-fi", "linkbtn",
            lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)),
            "Support development on Ko-fi"))
        com_row.addWidget(self._opt_button(
            "\U0001F465  VRChat Group", "linkbtn",
            lambda: QDesktopServices.openUrl(QUrl(VRCHAT_GROUP_URL)),
            "Join the OSC-DreamChatbox VRChat group"))
        com_row.addStretch()
        com.addLayout(com_row)
        general_lay.addWidget(com_card)

        # 2b ---- Profiles (switching lives in the sidebar dropdown)
        prof_card, prof = self._opt_card(
            "Profiles",
            "Switch profiles and save new ones in the Profile dropdown at "
            "the bottom of the sidebar. Rename or delete the ACTIVE "
            "profile here.")
        prof_row = QHBoxLayout()
        prof_row.setSpacing(8)
        prof_row.addWidget(self._opt_button(
            "\U0001F4C2  Open profiles folder", "linkbtn",
            self.on_profile_open_folder,
            "Each profile is one .json file in this folder \u2013 copy "
            "them to back up a setup or share it."))
        prof_row.addWidget(self._opt_button(
            "\u270F\uFE0F  Rename active", "linkbtn",
            self.on_profile_rename))
        prof_row.addWidget(self._opt_button(
            "\U0001F5D1  Delete active", "linkbtn",
            self.on_profile_delete))
        prof_row.addStretch()
        prof.addLayout(prof_row)

        io_row = QHBoxLayout()
        io_row.setSpacing(8)
        io_row.addWidget(self._opt_button(
            "\U0001F4E4  Export active", "linkbtn",
            self.on_profile_export,
            "One file with all settings of the active profile, plugin "
            "settings included \u2013 to back it up or share it."))
        io_row.addWidget(self._opt_button(
            "\U0001F4E5  Import", "linkbtn",
            self.on_profile_import,
            "Adds a profile from an exported file. Missing plugins are "
            "offered from the store when you switch to it."))
        io_row.addStretch()
        prof.addLayout(io_row)

        exit_row = QHBoxLayout()
        self.toggle_profile_exit = ToggleSwitch()
        self.toggle_profile_exit.setChecked(
            bool(self.cfg.get(profiles.SAVE_ON_EXIT_KEY, True)))
        self.toggle_profile_exit.toggled.connect(
            self.on_profile_save_on_exit)
        exit_row.addWidget(self.toggle_profile_exit)
        exit_row.addWidget(ToggleLabel(
            "Save the active profile when the app closes  "
            "(settings and plugin settings)", self.toggle_profile_exit))
        exit_row.addStretch()
        prof.addLayout(exit_row)
        general_lay.addWidget(prof_card)

        # ---- Terminal mode (core/headless.py)
        term_card, term = self._opt_card(
            "Terminal mode",
            "Runs the chatbox without this window – same settings, "
            "same plugins, less than half the memory. The window closes "
            "and a terminal opens; type DCB-UI there to come back.")
        term_row = QHBoxLayout()
        term_row.setSpacing(8)
        term_row.addWidget(self._opt_button(
            "⌨️  Start in terminal mode", "linkbtn",
            self.on_start_terminal_mode,
            "Closes the window and continues in a terminal "
            "(osc-dreamchatbox --headless). Commands: DCB-help."))
        term_row.addStretch()
        term.addLayout(term_row)
        general_lay.addWidget(term_card)

        # 3 ---- Fixes
        # Both buttons fix problems that only exist on Linux:
        #   App Tray Fix        writes a freedesktop .desktop entry so
        #                       Wayland/KDE can match the window to an icon.
        #                       Windows takes the icon from the .exe itself,
        #                       and the AppUserModelID set in
        #                       osc_dreamchatbox.py already handles the
        #                       taskbar grouping.
        #   Picture Folder Fix  symlinks VRChat's screenshots out of the
        #                       Proton prefix. On Windows there IS no
        #                       prefix - VRChat writes straight into
        #                       %USERPROFILE%\Pictures\VRChat.
        # So on Windows the whole card is skipped rather than shown greyed
        # out: a disabled button invites the question "what am I missing?",
        # and the honest answer is "nothing".
        self.tray_fix_btn = self._opt_button(
            "\U0001F527  App Tray Fix", "linkbtn", self.run_app_tray_fix,
            "Registers a desktop entry so the correct taskbar/tray icon shows "
            "and the app appears in your application menu. For install-script "
            "users – does nothing if an entry already exists.")
        self.vrc_pic_btn = self._opt_button(
            "\U0001F5BC\uFE0F  VRC Picture Folder Fix", "linkbtn",
            self.run_vrc_picture_fix,
            "Creates a symlink so VRChat's camera photos – normally saved "
            "inside the Proton prefix – land directly in your Linux Pictures "
            "folder (~/Pictures/VRChat). Existing photos in the prefix are "
            "moved over. Does nothing if it's already set up.")
        if IS_WINDOWS:
            # created but never shown: other code (and any future preset)
            # may still reference the attributes
            self.tray_fix_btn.setVisible(False)
            self.vrc_pic_btn.setVisible(False)
        else:
            fix_card, fix = self._opt_card(
                "Fixes",
                "One-click repairs for Linux desktops. Each one does "
                "nothing if it is already set up.")
            fix_row = QHBoxLayout()
            fix_row.setSpacing(8)
            fix_row.addWidget(self.tray_fix_btn)
            fix_row.addWidget(self.vrc_pic_btn)
            fix_row.addStretch()
            fix.addLayout(fix_row)
            general_lay.addWidget(fix_card)
        # cards keep their natural height and sit at the top of their tab
        for lay in (general_lay, osc_lay, design_lay):
            lay.addStretch(1)

        # All three tabs sit in the page, only one is visible. Not a
        # QStackedWidget on purpose: that one is always as tall as its
        # TALLEST page (also for word-wrapped labels), so the short General
        # tab would scroll into empty space sized for the OSC tab. Hidden
        # widgets take no room in a layout, so this is only as tall as the
        # tab you are looking at.
        self.options_tabs = (tab_general, tab_osc, tab_design)
        for tab in self.options_tabs:
            layout.addWidget(tab)
        self.on_options_tab(0)

        layout.addStretch()
        return page

    @staticmethod
    def _opt_card(title, description=""):
        """A card with a title and an optional dim line under it.
        Returns (card, layout) - add rows to the layout."""
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(10)
        head = QLabel(title)
        head.setObjectName("cardtitle")
        lay.addWidget(head)
        if description:
            desc = QLabel(description)
            desc.setObjectName("dim")
            desc.setWordWrap(True)
            lay.addWidget(desc)
        return card, lay

    @staticmethod
    def _opt_button(label, object_name, on_click, tooltip=""):
        """The 34 px buttons used on the General tab."""
        btn = QPushButton(label)
        btn.setObjectName(object_name)
        btn.setFixedHeight(34)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            btn.setToolTip(tooltip)
        btn.clicked.connect(on_click)
        return btn

    def on_start_terminal_mode(self):
        """Hands over to terminal mode: opens a terminal running this
        app with --headless, then closes the window.

        The new copy waits for the instance lock (core/instancelock.py).
        It is released right after close() - config saved, chatbox
        cleared, plugins stopped - and NOT at process exit, which a
        plugin thread can delay for a long time. That delay is what made
        the first version say "already running" here."""
        from core import instancelock, selflaunch
        cmd = selflaunch.self_command(
            ["--headless", f"--wait-pid={os.getpid()}"])
        ok, msg = selflaunch.open_in_terminal(cmd)
        if not ok:
            QMessageBox.warning(
                self, "Terminal mode",
                f"Could not open a terminal:\n{msg}\n\n"
                "You can start it by hand:\n"
                "osc-dreamchatbox --headless")
            return
        self.log("Switching to terminal mode ...")
        self.close()                # runs closeEvent: the whole tidy-up
        instancelock.release()      # -> the terminal may start now
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def on_options_tab(self, idx):
        """Show one Options tab (0 General, 1 OSC, 2 Design)."""
        for i, tab in enumerate(self.options_tabs):
            tab.setVisible(i == idx)


    # ================================================================
    # customization
    # ================================================================
    def build_customization_card(self):
        """Theme presets, per-colour overrides and background images.

        Lives on the Options page next to the other app-wide settings -
        it changes how the whole window looks, so it does not belong in
        any single feature's card.
        """
        card = QFrame()
        card.setObjectName("card")
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 12, 16, 14)
        c.setSpacing(8)

        t = QLabel("Customization")
        t.setObjectName("cardtitle")
        c.addWidget(t)
        hint = QLabel("Pick a theme, then recolour anything you like or drop "
                      "an image behind the window.")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        c.addWidget(hint)

        # ---- theme tiles
        self.theme_grid = QGridLayout()
        self.theme_grid.setSpacing(8)
        c.addLayout(self.theme_grid)
        self._build_theme_tiles()

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("hline")
        c.addWidget(line)

        # ---- colour pickers
        col_head = QHBoxLayout()
        col_head.addWidget(QLabel("Colors"))
        col_head.addStretch()
        reset = QPushButton("\u21BA  Reset colors")
        reset.setObjectName("linkbtn")
        reset.setFixedHeight(28)
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.setToolTip("Back to the colours of the selected theme")
        reset.clicked.connect(self.on_theme_reset_colors)
        col_head.addWidget(reset)
        c.addLayout(col_head)

        self.color_grid = QGridLayout()
        self.color_grid.setSpacing(6)
        c.addLayout(self.color_grid)
        self._build_color_buttons()

        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setObjectName("hline")
        c.addWidget(line2)

        # ---- backgrounds
        bg_head = QHBoxLayout()
        bg_head.addWidget(QLabel("Background"))
        bg_head.addStretch()
        add_bg = QPushButton("\u2795  Add image")
        add_bg.setObjectName("sendbtn")
        add_bg.setFixedHeight(28)
        add_bg.setCursor(Qt.CursorShape.PointingHandCursor)
        add_bg.clicked.connect(self.on_background_add)
        bg_head.addWidget(add_bg)
        c.addLayout(bg_head)

        self.bg_grid = QGridLayout()
        self.bg_grid.setSpacing(8)
        c.addLayout(self.bg_grid)

        op_row = QHBoxLayout()
        self.bg_opacity_lbl = QLabel("")
        op_row.addWidget(QLabel("Card opacity"))
        self.bg_opacity = QSlider(Qt.Orientation.Horizontal)
        self.bg_opacity.setRange(25, 100)
        self.bg_opacity.setValue(int(float(self.cfg.get("theme_opacity",
                                                        0.82)) * 100))
        self.bg_opacity.setMinimumWidth(160)
        self.bg_opacity.setToolTip("How solid the cards are drawn on top of "
                                   "a background image")
        self.bg_opacity.valueChanged.connect(self.on_theme_opacity)
        op_row.addWidget(self.bg_opacity, 1)
        self.bg_opacity_lbl.setObjectName("dim")
        self.bg_opacity_lbl.setMinimumWidth(48)
        op_row.addWidget(self.bg_opacity_lbl)
        c.addLayout(op_row)
        self._build_background_tiles()
        self._sync_opacity_row()
        return card

    # ------------------------------------------------------------ tiles
    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _theme_swatch(self, tokens, w=104, h=64):
        """Draws the theme as vertical colour bars, the way VRChat shows
        its UI themes - faster to read than a name."""
        pm = QPixmap(w, h)
        pm.fill(QColor(tokens["bg"]))
        painter = QPainter(pm)
        bars = [tokens["panel"], tokens["card"], tokens["inner"],
                tokens["accent"], tokens["text"]]
        bw = w / len(bars)
        for i, col in enumerate(bars):
            painter.fillRect(int(i * bw), 0, int(bw) + 1, h, QColor(col))
        painter.end()
        return pm

    def _build_theme_tiles(self):
        self._clear_layout(self.theme_grid)
        current = self.cfg.get("theme", "default")
        for i, tid in enumerate(theme_ids()):
            tokens = resolve_tokens(tid, self.cfg.get("theme_colors", {})
                                    .get(tid, {}))
            tile = QFrame()
            tile.setObjectName("innerbox")
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setFixedWidth(116)
            v = QVBoxLayout(tile)
            v.setContentsMargins(5, 5, 5, 5)
            v.setSpacing(4)
            img = QLabel()
            img.setPixmap(self._theme_swatch(tokens))
            img.setFixedSize(104, 64)
            v.addWidget(img)
            name = QLabel(theme_name(tid))
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(name)
            if tid == current:
                tile.setStyleSheet(
                    "QFrame#innerbox { border: 2px solid %s; }"
                    % tokens["accent"])
                name.setStyleSheet("font-weight: 600;")
            tile.mousePressEvent = (
                lambda ev, k=tid: self.on_theme_selected(k))
            self.theme_grid.addWidget(tile, i // 5, i % 5)
        self.theme_grid.setColumnStretch(5, 1)

    def _build_color_buttons(self):
        self._clear_layout(self.color_grid)
        tid = self.cfg.get("theme", "default")
        overrides = self.cfg.get("theme_colors", {}).get(tid, {})
        tokens = resolve_tokens(tid, overrides)
        for i, (key, label) in enumerate(TOKEN_LABELS):
            btn = QPushButton(f"  {label}")
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            edited = key in overrides
            btn.setStyleSheet(
                f"QPushButton {{ background: {tokens[key]};"
                f" border: 1px solid {'#ffffff' if edited else '#333947'};"
                f" border-radius: 6px; color: {self._readable(tokens[key])};"
                f" text-align: left; padding-left: 8px; }}")
            btn.setToolTip(f"{tokens[key]}"
                           + ("  (changed)" if edited else ""))
            btn.clicked.connect(
                lambda _, k=key, l=label: self.on_pick_color(k, l))
            self.color_grid.addWidget(btn, i // 3, i % 3)

    @staticmethod
    def _readable(hex_colour):
        """Black or white label text, whichever survives on that swatch."""
        try:
            r = int(hex_colour[1:3], 16)
            g = int(hex_colour[3:5], 16)
            b = int(hex_colour[5:7], 16)
        except (ValueError, IndexError):
            return "#ffffff"
        return "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 \
            else "#ffffff"

    def _build_background_tiles(self):
        self._clear_layout(self.bg_grid)
        current = self.cfg.get("theme_background", "")
        items = [("", None)] + [(p.name, p) for p in list_backgrounds()]
        for i, (name, path) in enumerate(items):
            tile = QFrame()
            tile.setObjectName("innerbox")
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setFixedWidth(132)
            v = QVBoxLayout(tile)
            v.setContentsMargins(5, 5, 5, 5)
            v.setSpacing(4)
            img = QLabel()
            img.setFixedSize(120, 68)
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if path is None:
                pm = QPixmap(120, 68)
                tokens = resolve_tokens(self.cfg.get("theme", "default"))
                pm.fill(QColor(tokens["bg"]))
                img.setPixmap(pm)
            else:
                loaded = QPixmap(str(path))
                img.setPixmap(loaded.scaled(
                    120, 68, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation))
            v.addWidget(img)
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel("None" if path is None else Path(name).stem[:14])
            lbl.setObjectName("dim")
            row.addWidget(lbl)
            row.addStretch()
            if path is not None:
                rm = QPushButton("\U0001F5D1")
                rm.setObjectName("iconbtn")
                rm.setFixedSize(22, 22)
                rm.setCursor(Qt.CursorShape.PointingHandCursor)
                rm.setToolTip("Remove this image")
                rm.clicked.connect(
                    lambda _, n=name: self.on_background_remove(n))
                row.addWidget(rm)
            v.addLayout(row)
            if name == current:
                tokens = resolve_tokens(self.cfg.get("theme", "default"))
                tile.setStyleSheet("QFrame#innerbox { border: 2px solid %s; }"
                                   % tokens["accent"])
            tile.mousePressEvent = (
                lambda ev, n=name: self.on_background_selected(n))
            self.bg_grid.addWidget(tile, i // 4, i % 4)
        self.bg_grid.setColumnStretch(4, 1)

    def _sync_opacity_row(self):
        on = bool(self.cfg.get("theme_background"))
        self.bg_opacity.setEnabled(on)
        self.bg_opacity_lbl.setText(f"{self.bg_opacity.value()}%")

    def _refresh_customization(self):
        self._build_theme_tiles()
        self._build_color_buttons()
        self._build_background_tiles()
        self._sync_opacity_row()

    # --------------------------------------------------------- handlers
    def on_theme_selected(self, theme_id):
        self.cfg["theme"] = theme_id
        self.save_config()
        self.apply_theme()
        self._refresh_customization()
        self.log(f"Theme: {theme_name(theme_id)}")

    def on_pick_color(self, key, label):
        tid = self.cfg.get("theme", "default")
        overrides = self.cfg.setdefault("theme_colors", {}).setdefault(tid, {})
        tokens = resolve_tokens(tid, overrides)
        chosen = QColorDialog.getColor(
            QColor(tokens[key]), self, f"{label} color")
        if not chosen.isValid():
            return
        overrides[key] = chosen.name().lower()
        self.save_config()
        self.apply_theme()
        self._refresh_customization()

    def on_theme_reset_colors(self):
        tid = self.cfg.get("theme", "default")
        self.cfg.setdefault("theme_colors", {}).pop(tid, None)
        self.save_config()
        self.apply_theme()
        self._refresh_customization()
        self.log(f"Theme: colors reset to {theme_name(tid)}")

    def on_background_add(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a background image", str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            name = import_background(path)
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "Image not added", str(e))
            return
        self.cfg["theme_background"] = name
        self.save_config()
        self.apply_theme()
        self._refresh_customization()
        self.log(f"Background: {name}")

    def on_background_selected(self, name):
        self.cfg["theme_background"] = name
        self.save_config()
        self.apply_theme()
        self._refresh_customization()

    def on_background_remove(self, name):
        if self.cfg.get("theme_background") == name:
            self.cfg["theme_background"] = ""
        remove_background(name)
        self.save_config()
        self.apply_theme()
        self._refresh_customization()

    def on_theme_opacity(self, val):
        self.cfg["theme_opacity"] = val / 100.0
        self.bg_opacity_lbl.setText(f"{val}%")
        self.save_config_later()
        self.apply_theme()

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
        # plugins live in their own repos, so they get their own check -
        # both run in parallel, neither blocks the window
        self.check_plugin_updates()

    def _on_update_result(self, result):
        tag, info = result
        if tag == "__error__":
            self.update_lbl.setText(
                f"Update check failed (no releases yet or offline). "
                f"Current version: {VERSION}")
        elif tag and compare_versions(tag, VERSION) < 0:
            # a dev build or a release that is not published yet: "!="
            # used to call that an update, and pointed at an OLDER one
            self.update_lbl.setText(
                f"\u2705 You are ahead of the latest release "
                f"({VERSION}, latest is {tag}).")
        elif tag and compare_versions(tag, VERSION) > 0:
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
        if IS_WINDOWS:
            QMessageBox.information(
                self, "App Tray Fix",
                "Not needed on Windows: the taskbar icon comes from the "
                "executable itself. This fix writes a freedesktop .desktop "
                "entry, which only Linux desktops use.")
            return
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
        if IS_WINDOWS:
            # `box` is only bound at the END of this method - calling it
            # here raised NameError, and PyQt6 routes an exception out of
            # a slot to sys.excepthook, which kills the process. So this
            # button closed the whole app on Windows.
            QMessageBox.information(
                self, "VRC Picture Folder Fix",
                "Not needed on Windows: VRChat saves its photos straight "
                "to your Pictures folder. This fix only exists because on "
                "Linux they end up inside the Proton prefix.")
            return
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
            # counts against VRChat's chatbox budget like any other
            # message, and there is nothing on screen afterwards - so the
            # next payload is always "different" and goes out at once
            self._send_times.append(time.time())
            self._last_sent_payload = None
            self.pending_send_timer.stop()
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

    def on_instant_send_toggled(self, on):
        self.cfg["osc_instant_send"] = bool(on)
        self.save_config()
        self.log(f"Instant send: {'ON' if on else 'OFF'}")
        if on:
            self.request_send()

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
            f"      path:      {queryfix.display_path(prog)}\n"
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
            elif not self.oscq.announced:
                txt = (f"\u23F3 announcing via mDNS \u2026 "
                       f"(dynamic udp/{self.oscq.osc_port}, "
                       f"http/{self.oscq.http_port})")
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

    def on_hotkey_input_toggled(self, on):
        self.cfg["hotkey_input_enabled"] = bool(on)
        self.save_config()
        self.update_hotkey_input()

    def update_hotkey_input(self):
        """Starts or stops the global key watcher and repaints its
        status line."""
        want = bool(self.cfg.get("hotkey_input_enabled"))
        if not want:
            if self.hotkey_in.running:
                self.hotkey_in.stop()
                self.log("Hotkey input: stopped")
            self._set_hotkey_in_status(
                "Off \u2013 the Get Hotkey block has nothing to read.")
            return
        if self.hotkey_in.running:
            return
        if self.hotkey_in.start():
            self._set_hotkey_in_status(
                f"Watching via {self.hotkey_in.backend}.")
        else:
            self._set_hotkey_in_status(
                f"Not watching: {self.hotkey_in.error}")

    def _set_hotkey_in_status(self, text):
        if hasattr(self, "hotkey_in_status") and \
                self.hotkey_in_status.text() != text:
            self.hotkey_in_status.setText(text)

    def on_osc_ext_ip(self):
        value = self.osc_ext_ip.text().strip() or "127.0.0.1"
        if value == self.cfg.get("osc_ext_ip"):
            return
        self.cfg["osc_ext_ip"] = value
        self.save_config()
        self.reset_ext_osc_clients()

    def on_osc_ext_port(self, val):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["osc_ext_port"] = int(val)
        self.save_config()
        self.reset_ext_osc_clients()

    def on_osc_input_toggled(self, on):
        self.cfg["osc_input_enabled"] = bool(on)
        self.save_config()
        self.update_osc_input()

    def on_osc_input_port(self, val):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["osc_input_port"] = int(val)
        self.save_config()
        if self.cfg.get("osc_input_enabled"):
            self.update_osc_input()

    def update_osc_input(self):
        """Starts or stops the parameter listener and repaints its
        status line. Safe to call as often as you like - it returns
        early when nothing has to change."""
        want = bool(self.cfg.get("osc_input_enabled"))
        if not want:
            if self.osc_in.running:
                self.osc_in.stop()
                self.log("OSC input: stopped")
            self._set_osc_in_status("Off \u2013 the Avatar parameter block "
                                    "has nothing to read.")
            return
        if self.osc_in.running:
            self._set_osc_in_status(
                f"Listening on udp/{self.osc_in.port} \u2013 "
                f"{len(self.osc_in.snapshot())} parameters seen.")
            return
        port = int(self.cfg.get("osc_input_port", DEFAULT_IN_PORT))
        if self.osc_in.start(port):
            self._set_osc_in_status(f"Listening on udp/{self.osc_in.port}.")
        else:
            self._set_osc_in_status(
                f"Port {port} could not be opened: {self.osc_in.error}. "
                "Another OSC app is probably using it \u2013 close it, or "
                "pick a different port here and point VRChat at it.")

    def _set_osc_in_status(self, text):
        if hasattr(self, "osc_in_status") and \
                self.osc_in_status.text() != text:
            self.osc_in_status.setText(text)

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
