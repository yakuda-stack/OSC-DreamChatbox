"""
ui/mainwindow.py – main window of OSC-DreamChatbox
(pages: Text Apps, Textbox, Options)
"""

import os
import random
import re
import sys
import json
import time
import subprocess
import threading
import queue as _queue
from collections import deque
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QFrame, QCheckBox, QSpinBox, QStackedWidget,
    QScrollArea, QComboBox, QFileDialog, QListWidget
)

from core.constants import (APP_NAME, VERSION, GITHUB_REPO, DISCORD_URL,
                            DONATE_URL, CONFIG_DIR, CONFIG_FILE,
                            OLD_CONFIG_FILE, SLIM_SUFFIX, CHATBOX_INPUT,
                            CHATBOX_LIMIT, TITLE_MAX_LEN, SONGBAR_LEN)
from core.textutils import (fmt_time, fmt_time_hm,
                            apply_template, make_songbar,
                            SONGBAR_STYLES, CUSTOM_STYLE_INDEX,
                            DEFAULT_CUSTOM_BAR)
from core import queryfix
from core.oscquery import OSCQueryService, HAS_ZEROCONF
from core.mediafetch import MediaFetcher
from core.hardware import HardwareMonitor
from core.speechtotext import SpeechWorker, LANGUAGES, OUTPUT_LANGUAGES
from core.translators import (METHODS as TR_METHODS, METHOD_LINGVA,
                              METHOD_GOOGLE, METHOD_LIBRE, METHOD_DEEPL,
                              DEFAULT_LIBRE_URL, libretranslate_installed,
                              LibreTranslateServer, get_translator)
from ui.ui_main import (STYLE, ToggleSwitch, ToggleLabel, DebugConsole,
                        DragHandle, EmojiPopup)

try:
    from pythonosc.udp_client import SimpleUDPClient
except ImportError:
    print("Error: python-osc is not installed.  ->  pip install python-osc")
    sys.exit(1)


# ----------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OSC DreamChatbox")
        self.resize(1024, 760)
        self.setMinimumSize(760, 420)  # freely resizable, pages scroll instead

        # --- state / settings ---
        self.cfg = self.load_config()
        self.osc_client = None
        self.debug_console = DebugConsole(APP_NAME)
        self.emoji_popup = EmojiPopup()
        self.status_index = 0
        self.media = MediaFetcher(self.log)
        self.media_info = None
        self.manual_pause_until = 0.0
        self.last_manual_text = ""
        self.aio_index = 0
        self.stt = SpeechWorker()
        self.stt_recording = False
        self.oscq = OSCQueryService(APP_NAME, self.log)
        self.libre_server = LibreTranslateServer(self.log)
        self._oscq_applied = None   # zuletzt uebernommenes VRChat-Ziel
        self._block_updating = False
        self.hw = HardwareMonitor(self.log)
        self.hw_info = None

        # --- timers ---
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._write_config)
        self.send_timer = QTimer(self)
        self.send_timer.timeout.connect(self.send_now)
        self.media_timer = QTimer(self)
        self.media_timer.timeout.connect(self.poll_media)
        self.rotate_timer = QTimer(self)
        self.rotate_timer.timeout.connect(self.advance_status)
        self.aio_timer = QTimer(self)
        self.aio_timer.timeout.connect(self.advance_aio)
        self.stt_timer = QTimer(self)
        self.stt_timer.timeout.connect(self.poll_stt)
        self.hw_timer = QTimer(self)
        self.hw_timer.timeout.connect(self.poll_hw)

        self.build_ui()
        self.apply_config_to_ui()
        # natives OSCQuery: dynamische Ports + VRChat-Discovery
        self.oscq_timer = QTimer(self)
        self.oscq_timer.timeout.connect(self.poll_oscquery)
        if self.cfg.get("oscquery_enabled") and HAS_ZEROCONF:
            if self.oscq.start():
                self.oscq_timer.start(2000)
        self.update_osc_client()
        self.update_timers()

    # ------------------------------------------------------------------ config
    def load_config(self):
        defaults = {
            "status_text": "",
            "status_texts": [""] * 10,
            "status_count": 1,
            "status_cycle_sec": 10,
            "status_active": True,
            "media_active": False,
            "media_show_artist": True,
            "media_show_title": True,
            "media_show_time": True,
            "media_show_bar": True,
            "oscquery_enabled": True,   # natives OSCQuery (mDNS)
            "media_bar_style": 2,   # 0-5 presets, 6 = custom
            "media_bar_custom": dict(DEFAULT_CUSTOM_BAR),
            "media_poll_sec": 1,
            "hw_active": False,
            "app_order": ["status", "media", "hardware"],
            "textbox_presets": ["Hey! How are you doing? \U0001F60A",
                                "What are you up to? \U0001F440",
                                "What's up? status: chilling \u2728",
                                "BRB / AFK for a moment! \u2615",
                                "ERP please ?"] + [""] * 15,
            "textbox_preset_count": 5,
            "textbox_pause_sec": 10,
            "textbox_order": ["chat", "stt", "presets"],
            "stt_language": "de-DE",
            "stt_block": False,
            "stt_output": "",
            "stt_method": METHOD_LINGVA,  # lingva | libre | deepl
            "stt_deepl_key": "",
            "stt_libre_url": "",
            "stt_block_saved": [],
            "aio_active": False,
            "aio_count": 1,
            "aio_rotate": False,
            "aio_rotate_sec": 10,
            "aio_templates": ["{text} \\n {artist} : {title} | {time} \\n {bar}",
                              "", "", "", ""],
            "hw_flame": False,
            "hw_custom": False,
            "hw_custom_template": "\U0001F3AE {gpu_name} {gpu_usage} | {gpu_temp} {temp_icon} \\n "
                                  "\u2699\uFE0F {cpu_name} {cpu_usage} | {cpu_temp} {temp_icon} \\n "
                                  "VRAM {vram_usage} RAM {ram_usage} {ram_type}",
            "media_icon": False,
            "media_custom": False,
            "media_custom_template": "{artist} : {title} | {time}\\n{bar}",
            "hw_poll_sec": 2,
            "hw_gpu_usage": True,
            "hw_gpu_name": True,
            "hw_gpu_custom": False,
            "hw_gpu_custom_name": "",
            "hw_gpu_temp": True,
            "hw_vram_used": True,
            "hw_vram_pct": False,
            "hw_ram_used": True,
            "hw_ram_pct": False,
            "hw_ram_type": "",
            "hw_cpu_usage": True,
            "hw_cpu_name": True,
            "hw_cpu_custom": False,
            "hw_cpu_custom_name": "",
            "hw_cpu_temp": True,
            "send_to_vrchat": False,
            "interval_sec": 5,
            "slim_chatbox": True,   # slim bar instead of big box, default ON
            "osc_ip": "127.0.0.1",
            "osc_port": 9000,
            "debug": False,
        }
        try:
            if CONFIG_FILE.exists():
                defaults.update(json.loads(CONFIG_FILE.read_text()))
            elif OLD_CONFIG_FILE.exists():
                # migrate settings from the old location
                defaults.update(json.loads(OLD_CONFIG_FILE.read_text()))
        except Exception:
            pass
        # migrate the old single status text into the text list
        texts = defaults.get("status_texts")
        if not isinstance(texts, list):
            texts = [""] * 10
        texts = [str(t) for t in texts][:10] + [""] * max(0, 10 - len(texts))
        if defaults.get("status_text") and not any(t.strip() for t in texts):
            texts[0] = defaults["status_text"]
        defaults["status_texts"] = texts
        defaults["status_count"] = min(10, max(1, int(defaults.get("status_count", 1))))
        # migrate old default templates to the current one
        old_defaults = (
            "{gpu_name}: {gpu_usage} {gpu_temp} {vram_usage} | "
            "{cpu_name}: {cpu_usage} {cpu_temp} {ram_usage} {ram_type}",
            "{gpu_name}: {gpu_usage} {gpu_temp} | Vram {vram_usage} | "
            "{cpu_name}: {cpu_usage} {cpu_temp} {ram_usage} {ram_type}",
            "{gpu_name}: {gpu_usage} {gpu_temp} | VRAM {vram_usage} \\n "
            "{cpu_name}: {cpu_usage} {cpu_temp} \\n RAM {ram_usage} {ram_type}",
        )
        if defaults.get("hw_custom_template") in old_defaults:
            defaults["hw_custom_template"] = (
                "\U0001F3AE {gpu_name} {gpu_usage} | {gpu_temp} {temp_icon} \\n "
                "\u2699\uFE0F {cpu_name} {cpu_usage} | {cpu_temp} {temp_icon} \\n "
                "VRAM {vram_usage} RAM {ram_usage} {ram_type}")
        # validate app order (keep known keys, append missing ones)
        valid = ["status", "media", "hardware"]
        order = [k for k in defaults.get("app_order", []) if k in valid]
        order += [k for k in valid if k not in order]
        defaults["app_order"] = order
        presets = defaults.get("textbox_presets")
        if not isinstance(presets, list):
            presets = [""] * 20
        presets = [str(p) for p in presets][:20]
        defaults["textbox_presets"] = presets + [""] * (20 - len(presets))
        defaults["textbox_preset_count"] = min(20, max(1, int(
            defaults.get("textbox_preset_count", 5))))
        tvalid = ["chat", "stt", "presets"]
        torder = [k for k in defaults.get("textbox_order", []) if k in tvalid]
        torder += [k for k in tvalid if k not in torder]
        defaults["textbox_order"] = torder
        aio = defaults.get("aio_templates")
        if not isinstance(aio, list):
            aio = ["{text} \\n {artist} : {title} | {time} \\n {bar}", "", "", "", ""]
        aio = [str(t) for t in aio][:5]
        defaults["aio_templates"] = aio + [""] * (5 - len(aio))
        defaults["aio_count"] = min(5, max(1, int(defaults.get("aio_count", 1))))
        return defaults

    def save_config(self):
        """Writes the config immediately (used for toggles, checkboxes,
        spinboxes - things you change once)."""
        self._save_timer.stop()
        self._write_config()

    def save_config_later(self):
        """Debounced variant used ONLY by text fields: while typing, the
        file is written at most once every 800 ms instead of per keystroke.
        The single-shot timer is only armed while you type and costs
        nothing otherwise."""
        self._save_timer.start(800)

    def _write_config(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self.cfg, indent=2))
        except Exception as e:
            self.log(f"Could not save settings: {e}")

    # ---------------------------------------------------------------------- ui
    def build_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        # ===================== sidebar (left) =====================
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 20, 12, 12)
        sb_layout.setSpacing(6)

        self.btn_apps = QPushButton("Text Apps")
        self.btn_textbox = QPushButton("Textbox")
        self.btn_options = QPushButton("Options")
        self.nav_buttons = (self.btn_apps, self.btn_textbox,
                            self.btn_options)
        for i, b in enumerate(self.nav_buttons):
            b.setObjectName("navbtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, idx=i: self.switch_page(idx))
            sb_layout.addWidget(b)
        self.btn_apps.setChecked(True)
        sb_layout.addStretch()

        # ===================== middle (pages) =====================
        self.pages = QStackedWidget()
        self.pages.addWidget(self._wrap_scroll(self.build_apps_page()))
        self.pages.addWidget(self._wrap_scroll(self.build_textbox_page()))
        self.pages.addWidget(self._wrap_scroll(self.build_options_page()))

        # ===================== right column =====================
        right = QFrame()
        right.setObjectName("rightpanel")
        right.setFixedWidth(250)
        r_layout = QVBoxLayout(right)
        r_layout.setContentsMargins(14, 14, 14, 10)
        r_layout.setSpacing(14)

        preview_frame = QFrame()
        preview_frame.setObjectName("previewbox")
        pv_layout = QVBoxLayout(preview_frame)
        pv_layout.setContentsMargins(10, 8, 10, 10)
        pv_title = QLabel("Preview")
        pv_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        pv_title.setObjectName("previewtitle")
        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.preview_label.setMinimumHeight(140)
        pv_layout.addWidget(pv_title)
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setObjectName("hline")
        pv_layout.addWidget(line)
        pv_layout.addWidget(self.preview_label, 1)
        self.char_count_lbl = QLabel("")
        self.char_count_lbl.setObjectName("dim")
        self.char_count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        pv_layout.addWidget(self.char_count_lbl)
        r_layout.addWidget(preview_frame)

        # SendToVRChat (below Preview, above Debug)
        row1 = QHBoxLayout()
        self.toggle_send = ToggleSwitch()
        self.toggle_send.toggled.connect(self.on_send_toggled)
        row1.addWidget(self.toggle_send)
        row1.addWidget(ToggleLabel("SendToVRChat", self.toggle_send))
        row1.addStretch()
        r_layout.addLayout(row1)

        # Debug Toggle
        row2 = QHBoxLayout()
        self.toggle_debug = ToggleSwitch()
        self.toggle_debug.toggled.connect(self.on_debug_toggled)
        row2.addWidget(self.toggle_debug)
        row2.addWidget(ToggleLabel("Debug Toggle", self.toggle_debug))
        row2.addStretch()
        r_layout.addLayout(row2)

        r_layout.addStretch()

        ver = QLabel(VERSION)
        ver.setObjectName("dim")
        ver.setAlignment(Qt.AlignmentFlag.AlignRight)
        r_layout.addWidget(ver)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.pages, 1)
        root_layout.addWidget(right)

        self.setStyleSheet(STYLE)

    @staticmethod
    def _wrap_scroll(widget):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(widget)
        return sa

    # ------------------------------------------------- expandable settings box
    def make_settings_expander(self, on_toggled):
        btn = QPushButton("›  Settings")
        btn.setObjectName("expander")
        btn.setCheckable(True)
        btn.setChecked(False)  # collapsed by default on start
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.toggled.connect(on_toggled)
        return btn

    @staticmethod
    def set_expanded(btn, content, expanded):
        content.setVisible(expanded)
        btn.setText(("⌄  Settings") if expanded else ("›  Settings"))

    def build_apps_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("Text Apps")
        title.setObjectName("pagetitle")
        layout.addWidget(title)

        # ================= Personal Status card =================
        card = QFrame()
        card.setObjectName("card")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(16, 14, 16, 16)
        c_layout.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(DragHandle(lambda pos: self.card_drag("status", pos),
                                  lambda: self.card_drag_end("status")))
        h_title = QLabel("Personal Status")
        h_title.setObjectName("cardtitle")
        head.addWidget(h_title)
        head.addStretch()
        self.toggle_active = ToggleSwitch()
        self.toggle_active.toggled.connect(self.on_active_toggled)
        head.addWidget(self.toggle_active)
        head.addWidget(ToggleLabel("Active", self.toggle_active))
        c_layout.addLayout(head)

        box = QFrame()
        box.setObjectName("innerbox")
        b_layout = QVBoxLayout(box)
        b_layout.setContentsMargins(14, 10, 14, 14)
        b_layout.setSpacing(8)

        self.status_content = QWidget()
        sc = QVBoxLayout(self.status_content)
        sc.setContentsMargins(0, 0, 0, 0)
        sc.setSpacing(8)
        cnt_row = QHBoxLayout()
        cnt_row.addWidget(QLabel("Number of texts"))
        self.status_count_spin = QSpinBox()
        self.status_count_spin.setObjectName("smallspin")
        self.status_count_spin.setRange(1, 10)
        self.status_count_spin.setFixedSize(64, 28)
        self.status_count_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_count_spin.valueChanged.connect(self.on_status_count)
        cnt_row.addWidget(self.status_count_spin)
        cnt_row.addSpacing(16)
        cnt_row.addWidget(QLabel("Change text every"))
        self.status_cycle_spin = QSpinBox()
        self.status_cycle_spin.setObjectName("smallspin")
        self.status_cycle_spin.setRange(2, 3600)
        self.status_cycle_spin.setFixedSize(72, 28)
        self.status_cycle_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_cycle_spin.valueChanged.connect(self.on_status_cycle)
        cnt_row.addWidget(self.status_cycle_spin)
        cnt_row.addWidget(QLabel("sec"))
        cnt_row.addStretch()
        sc.addLayout(cnt_row)

        # 10 text fields, visibility follows "Number of texts"
        self.status_rows = []
        self.status_edits = []
        for i in range(10):
            row_w = QWidget()
            row = QHBoxLayout(row_w)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            lbl = QLabel(f"Text {i + 1}:")
            lbl.setFixedWidth(52)
            row.addWidget(lbl)
            edit = QLineEdit()
            edit.setPlaceholderText("[Status Text goes here]")
            edit.setMaxLength(CHATBOX_LIMIT - len(SLIM_SUFFIX))
            edit.textChanged.connect(lambda t, idx=i: self.on_status_text(idx, t))
            row.addWidget(edit, 1)
            icon_btn = QPushButton("\U0001F600")
            icon_btn.setObjectName("iconbtn")
            icon_btn.setFixedSize(30, 30)
            icon_btn.setToolTip("Insert icon")
            icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            icon_btn.clicked.connect(
                lambda _, e=edit, b=icon_btn: self.emoji_popup.open_for(e, b))
            row.addWidget(icon_btn)
            sc.addWidget(row_w)
            self.status_rows.append(row_w)
            self.status_edits.append(edit)

        self.status_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.status_expander, self.status_content, on))
        b_layout.addWidget(self.status_expander)
        b_layout.addWidget(self.status_content)
        self.status_content.setVisible(False)

        c_layout.addWidget(box)

        # ================= MediaPlay card =================
        mcard = QFrame()
        mcard.setObjectName("card")
        m_layout = QVBoxLayout(mcard)
        m_layout.setContentsMargins(16, 14, 16, 16)
        m_layout.setSpacing(12)

        mhead = QHBoxLayout()
        mhead.addWidget(DragHandle(lambda pos: self.card_drag("media", pos),
                                   lambda: self.card_drag_end("media")))
        m_title = QLabel("MediaPlay")
        m_title.setObjectName("cardtitle")
        mhead.addWidget(m_title)
        mhead.addStretch()
        self.toggle_media = ToggleSwitch()
        self.toggle_media.toggled.connect(self.on_media_toggled)
        mhead.addWidget(self.toggle_media)
        mhead.addWidget(ToggleLabel("Active", self.toggle_media))
        m_layout.addLayout(mhead)

        mdesc = QLabel("Shows the song you are currently listening to "
                       "(Spotify, YT Music, browser, any media player – via MPRIS).")
        mdesc.setObjectName("dim")
        mdesc.setWordWrap(True)
        m_layout.addWidget(mdesc)

        mbox = QFrame()
        mbox.setObjectName("innerbox")
        mb_layout = QVBoxLayout(mbox)
        mb_layout.setContentsMargins(14, 10, 14, 14)
        mb_layout.setSpacing(8)

        self.media_content = QWidget()
        mc = QVBoxLayout(self.media_content)
        mc.setContentsMargins(0, 0, 0, 0)
        mc.setSpacing(8)

        mc.addWidget(QLabel("Show:"))
        self.chk_artist = QCheckBox("Artist")
        self.chk_title = QCheckBox(f"Song title (max {TITLE_MAX_LEN} characters)")
        self.chk_time = QCheckBox("Time  (current / total)")
        self.chk_bar = QCheckBox("Songbar  (progress bar)")
        for chk, key in ((self.chk_artist, "media_show_artist"),
                         (self.chk_title, "media_show_title"),
                         (self.chk_time, "media_show_time"),
                         (self.chk_bar, "media_show_bar")):
            chk.toggled.connect(lambda on, k=key: self.on_media_option(k, on))
            mc.addWidget(chk)

        # songbar style picker (the 5 selectable bar designs)
        style_row = QHBoxLayout()
        style_row.setContentsMargins(24, 0, 0, 0)
        style_row.addWidget(QLabel("Songbar style:"))
        self.bar_style_combo = QComboBox()
        for preview in SONGBAR_STYLES:
            self.bar_style_combo.addItem(preview)
        self.bar_style_combo.addItem("Custom \u2026")   # own style
        self.bar_style_combo.currentIndexChanged.connect(self.on_bar_style)
        style_row.addWidget(self.bar_style_combo)
        style_row.addStretch()
        mc.addLayout(style_row)

        # custom style editor (only visible when "Custom" is selected)
        self.bar_custom_box = QWidget()
        cb = QVBoxLayout(self.bar_custom_box)
        cb.setContentsMargins(24, 0, 0, 0)
        cb.setSpacing(6)
        chint = QLabel("Build your own songbar: start/end are optional "
                       "brackets, \"filled\"/\"empty\" are the bar "
                       "characters. If \"knob\" is set, a knob travels "
                       "over the empty character instead of filling.")
        chint.setObjectName("dim")
        chint.setWordWrap(True)
        cb.addWidget(chint)
        crow = QHBoxLayout()
        self.bar_custom_inputs = {}
        for key, label, width in (("prefix", "Start", 44),
                                  ("filled", "Filled", 44),
                                  ("knob", "Knob", 44),
                                  ("empty", "Empty", 44),
                                  ("suffix", "End", 44)):
            crow.addWidget(QLabel(label + ":"))
            edit = QLineEdit()
            edit.setFixedWidth(width)
            edit.setMaxLength(4)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.textChanged.connect(
                lambda text, k=key: self.on_bar_custom(k, text))
            self.bar_custom_inputs[key] = edit
            crow.addWidget(edit)
        crow.addSpacing(10)
        self.bar_custom_preview = QLabel("")
        self.bar_custom_preview.setObjectName("dim")
        crow.addWidget(self.bar_custom_preview)
        crow.addStretch()
        cb.addLayout(crow)
        mc.addWidget(self.bar_custom_box)

        poll_row = QHBoxLayout()
        poll_row.addWidget(QLabel("Query media player every"))
        self.poll_spin = QSpinBox()
        self.poll_spin.setObjectName("smallspin")
        self.poll_spin.setRange(1, 30)
        self.poll_spin.setFixedSize(64, 28)
        self.poll_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poll_spin.valueChanged.connect(self.on_poll_changed)
        poll_row.addWidget(self.poll_spin)
        poll_row.addWidget(QLabel("sec"))
        poll_row.addStretch()
        mc.addLayout(poll_row)

        # ----- Config -----
        mcfg_lbl = QLabel("Config:")
        mcfg_lbl.setObjectName("cardtitle")
        mcfg_lbl.setStyleSheet("font-size: 14px;")
        mc.addWidget(mcfg_lbl)

        self.chk_media_icon = QCheckBox("Media icon  (\U0001F3B5 before & after the song line)")
        self.chk_media_icon.toggled.connect(lambda on: self.on_media_option("media_icon", on))
        mc.addWidget(self.chk_media_icon)

        self.chk_media_custom = QCheckBox("Custom string  (build your own layout)")
        self.chk_media_custom.toggled.connect(lambda on: self.on_media_option("media_custom", on))
        mc.addWidget(self.chk_media_custom)
        m_custom_row = QHBoxLayout()
        self.media_custom_input = QLineEdit()
        self.media_custom_input.setMaxLength(200)
        self.media_custom_input.textChanged.connect(self.on_media_template)
        m_custom_row.addWidget(self.media_custom_input, 1)
        m_ico = QPushButton("\U0001F600")
        m_ico.setObjectName("iconbtn")
        m_ico.setFixedSize(30, 30)
        m_ico.setToolTip("Insert icon")
        m_ico.setCursor(Qt.CursorShape.PointingHandCursor)
        m_ico.clicked.connect(
            lambda _, e=self.media_custom_input, b=m_ico: self.emoji_popup.open_for(e, b))
        m_custom_row.addWidget(m_ico)
        mc.addLayout(m_custom_row)
        m_ph = QLabel("Placeholders: {artist} {title} {time} {position} {length} "
                      "{bar} {player} {icon_sound}  \u2013  use \\n for a line break. "
                      "Values follow the checkboxes above.")
        m_ph.setObjectName("dim")
        m_ph.setWordWrap(True)
        mc.addWidget(m_ph)

        self.media_status_lbl = QLabel("")
        self.media_status_lbl.setObjectName("dim")
        self.media_status_lbl.setWordWrap(True)
        mc.addWidget(self.media_status_lbl)

        self.media_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.media_expander, self.media_content, on))
        mb_layout.addWidget(self.media_expander)
        mb_layout.addWidget(self.media_content)
        self.media_content.setVisible(False)

        m_layout.addWidget(mbox)

        # ================= Hardware card =================
        hcard = QFrame()
        hcard.setObjectName("card")
        h_layout = QVBoxLayout(hcard)
        h_layout.setContentsMargins(16, 14, 16, 16)
        h_layout.setSpacing(12)

        hhead = QHBoxLayout()
        hhead.addWidget(DragHandle(lambda pos: self.card_drag("hardware", pos),
                                   lambda: self.card_drag_end("hardware")))
        h_title = QLabel("Hardware")
        h_title.setObjectName("cardtitle")
        hhead.addWidget(h_title)
        hhead.addStretch()
        self.toggle_hw = ToggleSwitch()
        self.toggle_hw.toggled.connect(self.on_hw_toggled)
        hhead.addWidget(self.toggle_hw)
        hhead.addWidget(ToggleLabel("Active", self.toggle_hw))
        h_layout.addLayout(hhead)

        hdesc = QLabel("Shows GPU / RAM / CPU stats in the chatbox "
                       "(usage, temperature, VRAM, ...).")
        hdesc.setObjectName("dim")
        hdesc.setWordWrap(True)
        h_layout.addWidget(hdesc)

        hbox = QFrame()
        hbox.setObjectName("innerbox")
        hb_layout = QVBoxLayout(hbox)
        hb_layout.setContentsMargins(14, 10, 14, 14)
        hb_layout.setSpacing(8)

        self.hw_content = QWidget()
        hc = QVBoxLayout(self.hw_content)
        hc.setContentsMargins(0, 0, 0, 0)
        hc.setSpacing(6)

        def hw_chk(label, key):
            chk = QCheckBox(label)
            chk.toggled.connect(lambda on, k=key: self.on_hw_option(k, on))
            hc.addWidget(chk)
            return chk

        # ----- GPU -----
        gpu_lbl = QLabel("GPU:")
        gpu_lbl.setObjectName("cardtitle")
        gpu_lbl.setStyleSheet("font-size: 14px;")
        hc.addWidget(gpu_lbl)
        self.chk_gpu_usage = hw_chk("GPU usage  (e.g. GPU: 27%)", "hw_gpu_usage")
        self.chk_gpu_temp = hw_chk("GPU temp", "hw_gpu_temp")
        self.chk_gpu_name = hw_chk("GPU name", "hw_gpu_name")
        gname_row = QHBoxLayout()
        self.chk_gpu_custom = QCheckBox("Custom GPU name:")
        self.chk_gpu_custom.toggled.connect(lambda on: self.on_hw_option("hw_gpu_custom", on))
        self.gpu_custom_input = QLineEdit()
        self.gpu_custom_input.setPlaceholderText("RX 9060 XT / RTX 5060 Ti / ...")
        self.gpu_custom_input.setMaxLength(30)
        self.gpu_custom_input.textChanged.connect(
            lambda t: self.on_hw_text("hw_gpu_custom_name", t))
        gname_row.addWidget(self.chk_gpu_custom)
        gname_row.addWidget(self.gpu_custom_input, 1)
        hc.addLayout(gname_row)

        # ----- VRAM -----
        vram_lbl = QLabel("VRAM:")
        vram_lbl.setObjectName("cardtitle")
        vram_lbl.setStyleSheet("font-size: 14px;")
        hc.addWidget(vram_lbl)
        self.chk_vram_used = hw_chk("VRAM usage in numbers  (e.g. 12/16GB)", "hw_vram_used")
        self.chk_vram_pct = hw_chk("VRAM usage in %", "hw_vram_pct")


        # ----- CPU -----
        cpu_lbl = QLabel("CPU:")
        cpu_lbl.setObjectName("cardtitle")
        cpu_lbl.setStyleSheet("font-size: 14px;")
        hc.addWidget(cpu_lbl)
        self.chk_cpu_usage = hw_chk("CPU usage  (e.g. CPU: 27%)", "hw_cpu_usage")
        self.chk_cpu_temp = hw_chk("CPU temp", "hw_cpu_temp")
        self.chk_cpu_name = hw_chk("CPU name", "hw_cpu_name")
        cname_row = QHBoxLayout()
        self.chk_cpu_custom = QCheckBox("Custom CPU name:")
        self.chk_cpu_custom.toggled.connect(lambda on: self.on_hw_option("hw_cpu_custom", on))
        self.cpu_custom_input = QLineEdit()
        self.cpu_custom_input.setPlaceholderText("Ryzen 7 9700X / i7 12700K / ...")
        self.cpu_custom_input.setMaxLength(30)
        self.cpu_custom_input.textChanged.connect(
            lambda t: self.on_hw_text("hw_cpu_custom_name", t))
        cname_row.addWidget(self.chk_cpu_custom)
        cname_row.addWidget(self.cpu_custom_input, 1)
        hc.addLayout(cname_row)

        # ----- RAM -----
        ram_lbl = QLabel("RAM:")
        ram_lbl.setObjectName("cardtitle")
        ram_lbl.setStyleSheet("font-size: 14px;")
        hc.addWidget(ram_lbl)
        self.chk_ram_used = hw_chk("RAM usage in numbers  (e.g. 12/16GB)", "hw_ram_used")
        self.chk_ram_pct = hw_chk("RAM usage in %", "hw_ram_pct")
        ramtype_row = QHBoxLayout()
        ramtype_row.addWidget(QLabel("RAM type (optional, e.g. DDR5):"))
        self.ram_type_input = QLineEdit()
        self.ram_type_input.setPlaceholderText("DDR5")
        self.ram_type_input.setMaxLength(10)
        self.ram_type_input.setFixedWidth(100)
        self.ram_type_input.textChanged.connect(
            lambda t: self.on_hw_text("hw_ram_type", t))
        ramtype_row.addWidget(self.ram_type_input)
        ramtype_row.addStretch()
        hc.addLayout(ramtype_row)

        # ----- Config -----
        cfg_lbl = QLabel("Config:")
        cfg_lbl.setObjectName("cardtitle")
        cfg_lbl.setStyleSheet("font-size: 14px;")
        hc.addWidget(cfg_lbl)

        self.chk_hw_flame = QCheckBox("Flame icon for temps  (62\U0001F525 instead of 62\u00b0C)")
        self.chk_hw_flame.toggled.connect(lambda on: self.on_hw_option("hw_flame", on))
        hc.addWidget(self.chk_hw_flame)

        self.chk_hw_custom = QCheckBox("Custom string  (build your own layout)")
        self.chk_hw_custom.toggled.connect(lambda on: self.on_hw_option("hw_custom", on))
        hc.addWidget(self.chk_hw_custom)
        hw_custom_row = QHBoxLayout()
        self.hw_custom_input = QLineEdit()
        self.hw_custom_input.setMaxLength(200)
        self.hw_custom_input.textChanged.connect(
            lambda t: self.on_hw_text("hw_custom_template", t))
        hw_custom_row.addWidget(self.hw_custom_input, 1)
        hw_ico = QPushButton("\U0001F600")
        hw_ico.setObjectName("iconbtn")
        hw_ico.setFixedSize(30, 30)
        hw_ico.setToolTip("Insert icon")
        hw_ico.setCursor(Qt.CursorShape.PointingHandCursor)
        hw_ico.clicked.connect(
            lambda _, e=self.hw_custom_input, b=hw_ico: self.emoji_popup.open_for(e, b))
        hw_custom_row.addWidget(hw_ico)
        hc.addLayout(hw_custom_row)
        hw_ph = QLabel("Placeholders: {gpu_name} {gpu_usage} {gpu_temp} {vram_usage} "
                       "{cpu_name} {cpu_usage} {cpu_temp} {ram_usage} {ram_type} "
                       "{icon_flame} {temp_icon}  \u2013  use \\n for a line break. Values follow "
                       "the checkboxes above (unchecked = empty, name unchecked = GPU/CPU).")
        hw_ph.setObjectName("dim")
        hw_ph.setWordWrap(True)
        hc.addWidget(hw_ph)

        hpoll_row = QHBoxLayout()
        hpoll_row.addWidget(QLabel("Query hardware every"))
        self.hw_poll_spin = QSpinBox()
        self.hw_poll_spin.setObjectName("smallspin")
        self.hw_poll_spin.setRange(1, 60)
        self.hw_poll_spin.setFixedSize(64, 28)
        self.hw_poll_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hw_poll_spin.valueChanged.connect(self.on_hw_poll_changed)
        hpoll_row.addWidget(self.hw_poll_spin)
        hpoll_row.addWidget(QLabel("sec"))
        hpoll_row.addStretch()
        hc.addLayout(hpoll_row)

        self.hw_status_lbl = QLabel("")
        self.hw_status_lbl.setObjectName("dim")
        self.hw_status_lbl.setWordWrap(True)
        hc.addWidget(self.hw_status_lbl)

        self.hw_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.hw_expander, self.hw_content, on))
        hb_layout.addWidget(self.hw_expander)
        hb_layout.addWidget(self.hw_content)
        self.hw_content.setVisible(False)

        h_layout.addWidget(hbox)

        # ================= All in one card =================
        acard = QFrame()
        acard.setObjectName("card")
        a_layout = QVBoxLayout(acard)
        a_layout.setContentsMargins(16, 14, 16, 16)
        a_layout.setSpacing(12)

        ahead = QHBoxLayout()
        a_title = QLabel("All in one")
        a_title.setObjectName("cardtitle")
        ahead.addWidget(a_title)
        ahead.addStretch()
        self.toggle_aio = ToggleSwitch()
        self.toggle_aio.toggled.connect(self.on_aio_toggled)
        ahead.addWidget(self.toggle_aio)
        ahead.addWidget(ToggleLabel("Active", self.toggle_aio))
        a_layout.addLayout(ahead)

        adesc = QLabel("When active, Personal Status, MediaPlay and Hardware no "
                       "longer send their own lines \u2013 everything is combined "
                       "here in one custom string (AIO) and only that gets sent "
                       "to VRChat.")
        adesc.setObjectName("dim")
        adesc.setWordWrap(True)
        a_layout.addWidget(adesc)

        abox = QFrame()
        abox.setObjectName("innerbox")
        ab_layout = QVBoxLayout(abox)
        ab_layout.setContentsMargins(14, 10, 14, 14)
        ab_layout.setSpacing(8)

        self.aio_content = QWidget()
        ac = QVBoxLayout(self.aio_content)
        ac.setContentsMargins(0, 0, 0, 0)
        ac.setSpacing(8)

        acnt_row = QHBoxLayout()
        acnt_row.addWidget(QLabel("Number of strings"))
        self.aio_count_spin = QSpinBox()
        self.aio_count_spin.setObjectName("smallspin")
        self.aio_count_spin.setRange(1, 5)
        self.aio_count_spin.setFixedSize(64, 28)
        self.aio_count_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.aio_count_spin.valueChanged.connect(self.on_aio_count)
        acnt_row.addWidget(self.aio_count_spin)
        acnt_row.addSpacing(16)
        self.chk_aio_rotate = QCheckBox("Rotate strings every")
        self.chk_aio_rotate.toggled.connect(self.on_aio_rotate)
        acnt_row.addWidget(self.chk_aio_rotate)
        self.aio_rotate_spin = QSpinBox()
        self.aio_rotate_spin.setObjectName("smallspin")
        self.aio_rotate_spin.setRange(2, 3600)
        self.aio_rotate_spin.setFixedSize(72, 28)
        self.aio_rotate_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.aio_rotate_spin.valueChanged.connect(self.on_aio_rotate_sec)
        acnt_row.addWidget(self.aio_rotate_spin)
        acnt_row.addWidget(QLabel("sec"))
        acnt_row.addStretch()
        ac.addLayout(acnt_row)

        self.aio_rows = []
        self.aio_edits = []
        for i in range(5):
            row_w = QWidget()
            row = QHBoxLayout(row_w)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            lbl = QLabel(f"AIO {i + 1}:")
            lbl.setFixedWidth(48)
            row.addWidget(lbl)
            edit = QLineEdit()
            edit.setPlaceholderText("{text} \\n {artist} : {title} | {time} \u2026")
            edit.setMaxLength(300)
            edit.textChanged.connect(lambda t, idx=i: self.on_aio_text(idx, t))
            row.addWidget(edit, 1)
            a_ico = QPushButton("\U0001F600")
            a_ico.setObjectName("iconbtn")
            a_ico.setFixedSize(30, 30)
            a_ico.setCursor(Qt.CursorShape.PointingHandCursor)
            a_ico.clicked.connect(
                lambda _, e=edit, b=a_ico: self.emoji_popup.open_for(e, b))
            row.addWidget(a_ico)
            ac.addWidget(row_w)
            self.aio_rows.append(row_w)
            self.aio_edits.append(edit)

        a_ph = QLabel("Placeholders: {text} (current rotating status text), "
                      "{text_1} \u2026 {text_10}, all Hardware placeholders "
                      "({gpu_name} {gpu_usage} {gpu_temp} {temp_icon} {vram_usage} "
                      "{cpu_name} {cpu_usage} {cpu_temp} {ram_usage} {ram_type} "
                      "{icon_flame}) and all MediaPlay placeholders ({artist} "
                      "{title} {time} {bar} {icon_sound} \u2026). Use \\n for a "
                      "line break. The apps must be Active for their values to fill in.")
        a_ph.setObjectName("dim")
        a_ph.setWordWrap(True)
        ac.addWidget(a_ph)

        self.aio_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.aio_expander, self.aio_content, on))
        ab_layout.addWidget(self.aio_expander)
        ab_layout.addWidget(self.aio_content)
        self.aio_content.setVisible(False)
        a_layout.addWidget(abox)

        # add the cards in the saved order (drag the 3x3 dots to reorder;
        # the order also defines the line order in the VRChat chatbox)
        self.app_cards = {"status": card, "media": mcard, "hardware": hcard}
        self.apps_layout = layout
        for key in self.cfg["app_order"]:
            layout.addWidget(self.app_cards[key])
        layout.addWidget(acard)
        layout.addStretch()
        return page

    # --------------------------------------------------- card drag & drop
    def card_drag(self, key, global_pos):
        order = self.cfg["app_order"]
        cur = order.index(key)
        y = global_pos.y()
        others = [k for k in order if k != key]
        new_idx = sum(1 for k in others
                      if y > self.app_cards[k].mapToGlobal(
                          self.app_cards[k].rect().center()).y())
        if new_idx != cur:
            order.remove(key)
            order.insert(new_idx, key)
            self.apps_layout.removeWidget(self.app_cards[key])
            self.apps_layout.insertWidget(1 + new_idx, self.app_cards[key])
            self.update_preview()

    def card_drag_end(self, key):
        self.save_config()
        self.log("App order: " + " > ".join(self.cfg["app_order"]))

    def build_textbox_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("Textbox")
        title.setObjectName("pagetitle")
        layout.addWidget(title)

        # ----- free chat field -----
        card = QFrame()
        card.setObjectName("card")
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 14, 16, 16)
        c.setSpacing(10)
        chead = QHBoxLayout()
        chead.addWidget(DragHandle(lambda pos: self.tb_card_drag("chat", pos),
                                   lambda: self.tb_card_drag_end("chat")))
        ct = QLabel("Chat")
        ct.setObjectName("cardtitle")
        chead.addWidget(ct)
        chead.addStretch()
        c.addLayout(chead)
        cd = QLabel("Type anything and send it straight to the VRChat chatbox. "
                    "While a manual message is shown, the apps (Personal Status, "
                    "MediaPlay, Hardware, WindowActivity) pause briefly to avoid "
                    "overwriting it.")
        cd.setObjectName("dim")
        cd.setWordWrap(True)
        c.addWidget(cd)

        tb_row = QHBoxLayout()
        self.textbox_input = QLineEdit()
        self.textbox_input.setPlaceholderText("Type a message \u2026")
        self.textbox_input.setMaxLength(CHATBOX_LIMIT - len(SLIM_SUFFIX))
        self.textbox_input.returnPressed.connect(self.send_manual)
        tb_row.addWidget(self.textbox_input, 1)
        tb_ico = QPushButton("\U0001F600")
        tb_ico.setObjectName("iconbtn")
        tb_ico.setFixedSize(34, 34)
        tb_ico.setToolTip("Insert icon")
        tb_ico.setCursor(Qt.CursorShape.PointingHandCursor)
        tb_ico.clicked.connect(
            lambda _, e=self.textbox_input, b=tb_ico: self.emoji_popup.open_for(e, b))
        tb_row.addWidget(tb_ico)
        self.textbox_send_btn = QPushButton("Send")
        self.textbox_send_btn.setObjectName("sendbtn")
        self.textbox_send_btn.setFixedHeight(34)
        self.textbox_send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.textbox_send_btn.clicked.connect(self.send_manual)
        tb_row.addWidget(self.textbox_send_btn)
        c.addLayout(tb_row)

        pause_row = QHBoxLayout()
        pause_row.addWidget(QLabel("Pause apps for"))
        self.pause_spin = QSpinBox()
        self.pause_spin.setObjectName("smallspin")
        self.pause_spin.setRange(2, 120)
        self.pause_spin.setFixedSize(64, 28)
        self.pause_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pause_spin.valueChanged.connect(self.on_pause_changed)
        pause_row.addWidget(self.pause_spin)
        pause_row.addWidget(QLabel("sec after sending"))
        pause_row.addStretch()
        c.addLayout(pause_row)
        # ----- speech to text -----
        scard = QFrame()
        scard.setObjectName("card")
        sc = QVBoxLayout(scard)
        sc.setContentsMargins(16, 14, 16, 16)
        sc.setSpacing(10)
        st_head = QHBoxLayout()
        st_head.addWidget(DragHandle(lambda pos: self.tb_card_drag("stt", pos),
                                     lambda: self.tb_card_drag_end("stt")))
        st = QLabel("Speech to Text")
        st.setObjectName("cardtitle")
        st_head.addWidget(st)
        st_head.addStretch()
        self.toggle_stt_block = ToggleSwitch()
        self.toggle_stt_block.toggled.connect(self.on_stt_block)
        st_head.addWidget(self.toggle_stt_block)
        st_head.addWidget(ToggleLabel("Block apps", self.toggle_stt_block))
        sc.addLayout(st_head)
        blk = QLabel("Block apps: while ON, NO app sends anything via OSC "
                     "(Personal Status, MediaPlay, Hardware, AIO) \u2013 "
                     "everything stays blocked until you turn it OFF again.")
        blk.setObjectName("dim")
        blk.setWordWrap(True)
        sc.addWidget(blk)
        sd = QLabel("Speak into your microphone \u2013 your voice is transcribed "
                    "in realtime and sent to the VRChat chatbox. While recording, "
                    "all apps (Personal Status, MediaPlay, Hardware, AIO) are "
                    "blocked so nothing overwrites your speech.")
        sd.setObjectName("dim")
        sd.setWordWrap(True)
        sc.addWidget(sd)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Language you speak:"))
        self.stt_lang_combo = QComboBox()
        for name, code in LANGUAGES:
            self.stt_lang_combo.addItem(name, code)
        self.stt_lang_combo.currentIndexChanged.connect(self.on_stt_language)
        lang_row.addWidget(self.stt_lang_combo)
        lang_row.addStretch()
        sc.addLayout(lang_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output language (VRChat):"))
        self.stt_out_combo = QComboBox()
        for name, code in OUTPUT_LANGUAGES:
            self.stt_out_combo.addItem(name, code)
        self.stt_out_combo.currentIndexChanged.connect(self.on_stt_output)
        out_row.addWidget(self.stt_out_combo)
        out_row.addStretch()
        sc.addLayout(out_row)
        tr_hint = QLabel("Example: speak German, pick English as output \u2013 "
                         "your speech gets translated live before it is sent "
                         "to VRChat.")
        tr_hint.setObjectName("dim")
        tr_hint.setWordWrap(True)
        sc.addWidget(tr_hint)

        # ---- translation method (three-tier system) ----
        method_row = QHBoxLayout()
        method_row.addWidget(QLabel("Translation service:"))
        self.tr_method_combo = QComboBox()
        for label, mid in TR_METHODS:
            self.tr_method_combo.addItem(label, mid)
        self.tr_method_combo.currentIndexChanged.connect(
            self.on_tr_method)
        method_row.addWidget(self.tr_method_combo, 1)
        self.tr_test_btn = QPushButton("\U0001F9EA  Test")
        self.tr_test_btn.setObjectName("linkbtn")
        self.tr_test_btn.setFixedHeight(30)
        self.tr_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tr_test_btn.setToolTip(
            "Sends a short test phrase through the selected service "
            "and shows the result or the exact error.")
        self.tr_test_btn.clicked.connect(self.on_tr_test)
        method_row.addWidget(self.tr_test_btn)
        sc.addLayout(method_row)

        # method 3: DeepL API key (only visible when DeepL is selected)
        self.deepl_row = QWidget()
        key_row = QHBoxLayout(self.deepl_row)
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(QLabel("DeepL API key:"))
        self.deepl_key_input = QLineEdit()
        self.deepl_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.deepl_key_input.setPlaceholderText("xxxxxxxx-xxxx-...-xxxx:fx")
        self.deepl_key_input.textChanged.connect(self.on_deepl_key)
        key_row.addWidget(self.deepl_key_input, 1)
        sc.addWidget(self.deepl_row)

        # method 2: LibreTranslate URL (only visible when selected)
        self.libre_row = QWidget()
        lr = QHBoxLayout(self.libre_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.addWidget(QLabel("LibreTranslate URL:"))
        self.libre_url_input = QLineEdit()
        self.libre_url_input.setPlaceholderText(DEFAULT_LIBRE_URL)
        self.libre_url_input.textChanged.connect(self.on_libre_url)
        lr.addWidget(self.libre_url_input, 1)
        # server Start/Stop button (only shown while LibreTranslate
        # is selected and installed)
        self.libre_install_btn = QPushButton(
            "\U0001F680  Start LibreTranslate")
        self.libre_install_btn.setObjectName("linkbtn")
        self.libre_install_btn.setFixedHeight(30)
        self.libre_install_btn.setCursor(
            Qt.CursorShape.PointingHandCursor)
        self.libre_install_btn.clicked.connect(self.on_libre_btn)
        lr.addWidget(self.libre_install_btn)
        sc.addWidget(self.libre_row)

        self.tr_method_hint = QLabel("")
        self.tr_method_hint.setObjectName("dim")
        self.tr_method_hint.setWordWrap(True)
        sc.addWidget(self.tr_method_hint)

        rec_row = QHBoxLayout()
        self.stt_button = QPushButton("\U0001F3A4  Start recording")
        self.stt_button.setObjectName("recbtn")
        self.stt_button.setCheckable(True)
        self.stt_button.setFixedHeight(38)
        self.stt_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stt_button.toggled.connect(self.on_stt_toggled)
        rec_row.addWidget(self.stt_button)
        rec_row.addStretch()
        sc.addLayout(rec_row)

        self.stt_status_lbl = QLabel("")
        self.stt_status_lbl.setObjectName("dim")
        self.stt_status_lbl.setWordWrap(True)
        sc.addWidget(self.stt_status_lbl)
        if not SpeechWorker.available():
            self.stt_button.setEnabled(False)
            self.stt_status_lbl.setText(
                "Not available: install SpeechRecognition + pyaudio "
                "(pip install SpeechRecognition pyaudio \u2013 "
                "Arch: sudo pacman -S python-pyaudio).")
        # ----- presets -----
        pcard = QFrame()
        pcard.setObjectName("card")
        pc = QVBoxLayout(pcard)
        pc.setContentsMargins(16, 14, 16, 16)
        pc.setSpacing(8)
        phead = QHBoxLayout()
        phead.addWidget(DragHandle(lambda pos: self.tb_card_drag("presets", pos),
                                   lambda: self.tb_card_drag_end("presets")))
        pt = QLabel("Presets")
        pt.setObjectName("cardtitle")
        phead.addWidget(pt)
        phead.addStretch()
        pc.addLayout(phead)
        pd = QLabel("Editable text templates \u2013 hit Send to fire one directly.")
        pd.setObjectName("dim")
        pc.addWidget(pd)

        pcnt_row = QHBoxLayout()
        pcnt_row.addWidget(QLabel("Number of presets"))
        self.preset_count_spin = QSpinBox()
        self.preset_count_spin.setObjectName("smallspin")
        self.preset_count_spin.setRange(1, 20)
        self.preset_count_spin.setFixedSize(64, 28)
        self.preset_count_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preset_count_spin.valueChanged.connect(self.on_preset_count)
        pcnt_row.addWidget(self.preset_count_spin)
        pcnt_row.addStretch()
        pc.addLayout(pcnt_row)

        self.preset_edits = []
        self.preset_rows = []
        for i in range(20):
            row_w = QWidget()
            row = QHBoxLayout(row_w)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            edit = QLineEdit()
            edit.setPlaceholderText(f"Preset {i + 1} \u2026")
            edit.setMaxLength(CHATBOX_LIMIT - len(SLIM_SUFFIX))
            edit.textChanged.connect(lambda t, idx=i: self.on_preset_text(idx, t))
            row.addWidget(edit, 1)
            p_ico = QPushButton("\U0001F600")
            p_ico.setObjectName("iconbtn")
            p_ico.setFixedSize(30, 30)
            p_ico.setCursor(Qt.CursorShape.PointingHandCursor)
            p_ico.clicked.connect(
                lambda _, e=edit, b=p_ico: self.emoji_popup.open_for(e, b))
            row.addWidget(p_ico)
            p_send = QPushButton("Send")
            p_send.setObjectName("sendbtn")
            p_send.setFixedSize(64, 30)
            p_send.setCursor(Qt.CursorShape.PointingHandCursor)
            p_send.clicked.connect(lambda _, idx=i: self.send_preset(idx))
            row.addWidget(p_send)
            pc.addWidget(row_w)
            self.preset_edits.append(edit)
            self.preset_rows.append(row_w)

        # add the cards in the saved order (drag the 3x3 dots to reorder)
        self.tb_cards = {"chat": card, "stt": scard, "presets": pcard}
        self.tb_layout = layout
        for key in self.cfg["textbox_order"]:
            layout.addWidget(self.tb_cards[key])
        layout.addStretch()
        return page

    def tb_card_drag(self, key, global_pos):
        order = self.cfg["textbox_order"]
        cur = order.index(key)
        y = global_pos.y()
        others = [k for k in order if k != key]
        new_idx = sum(1 for k in others
                      if y > self.tb_cards[k].mapToGlobal(
                          self.tb_cards[k].rect().center()).y())
        if new_idx != cur:
            order.remove(key)
            order.insert(new_idx, key)
            self.tb_layout.removeWidget(self.tb_cards[key])
            self.tb_layout.insertWidget(1 + new_idx, self.tb_cards[key])

    def tb_card_drag_end(self, key):
        self.save_config()
        self.log("Textbox order: " + " > ".join(self.cfg["textbox_order"]))

    # ---------------------------------------------------- manual sending
    def on_stt_block(self, on):
        self.cfg["stt_block"] = on
        if self._block_updating:
            self.save_config()
            return
        app_toggles = {"status": self.toggle_active, "media": self.toggle_media,
                       "hardware": self.toggle_hw, "aio": self.toggle_aio}
        self._block_updating = True
        try:
            if on:
                # remember which apps were on, then switch them off
                saved = [k for k, t in app_toggles.items() if t.isChecked()]
                self.cfg["stt_block_saved"] = saved
                for k in saved:
                    app_toggles[k].setChecked(False)
                self.log(f"Block apps: ON \u2013 switched off: "
                         f"{', '.join(saved) if saved else 'nothing was on'}")
            else:
                # switch the remembered apps back on
                saved = self.cfg.get("stt_block_saved", [])
                for k in saved:
                    if k in app_toggles:
                        app_toggles[k].setChecked(True)
                self.cfg["stt_block_saved"] = []
                self.log(f"Block apps: OFF \u2013 switched back on: "
                         f"{', '.join(saved) if saved else 'nothing'}")
        finally:
            self._block_updating = False
        self.save_config()
        self.update_preview()

    def _manual_app_enable(self):
        """If the user manually turns an app back on while Block apps is
        active, the block toggle deactivates itself (without restoring
        the other remembered apps)."""
        if self.cfg.get("stt_block") and not self._block_updating:
            self._block_updating = True
            try:
                self.cfg["stt_block"] = False
                self.cfg["stt_block_saved"] = []
                self.toggle_stt_block.setChecked(False)
                self.log("Block apps: auto-deactivated (an app was turned "
                         "on manually)")
            finally:
                self._block_updating = False
            self.save_config()

    def on_stt_language(self, idx):
        self.cfg["stt_language"] = self.stt_lang_combo.itemData(idx)
        self.save_config()
        self.stt.language = self.cfg["stt_language"]  # applies live
        self.log(f"Speech to Text language: {self.cfg['stt_language']}")

    def on_stt_output(self, idx):
        self.cfg["stt_output"] = self.stt_out_combo.itemData(idx)
        self.save_config()
        self.stt.translate_to = self.cfg["stt_output"]  # applies live
        self.log(f"Speech to Text output: "
                 f"{self.cfg['stt_output'] or 'same as spoken'}")

    def on_tr_method(self, idx):
        method = self.tr_method_combo.itemData(idx) or METHOD_LINGVA
        self.cfg["stt_method"] = method
        self.save_config()
        self.stt.method = method  # applies live
        self._update_tr_method_ui()
        self.log(f"Translation service: {method}")

    def _update_tr_method_ui(self):
        """Shows only the option fields of the selected method and
        updates the hint text. The LibreTranslate install button only
        appears while LibreTranslate is selected and not installed."""
        method = self.cfg.get("stt_method", METHOD_LINGVA)
        self.deepl_row.setVisible(method == METHOD_DEEPL)
        self.libre_row.setVisible(method == METHOD_LIBRE)
        if method == METHOD_LIBRE:
            btn = self.libre_install_btn
            if self.libre_server.running:
                btn.setVisible(True)
                btn.setText("\U0001F6D1  Stop LibreTranslate")
                btn.setStyleSheet(
                    "QPushButton { background: #c95b5b; color: #ffffff;"
                    " border: 1px solid #c95b5b; border-radius: 8px;"
                    " padding: 4px 16px; font-weight: 600; }"
                    "QPushButton:hover { background: #d46d6d; }")
            elif libretranslate_installed():
                btn.setVisible(True)
                btn.setText("\U0001F680  Start LibreTranslate")
                btn.setStyleSheet("")
            else:
                # not installed -> no button; the hint explains the
                # manual install command
                btn.setVisible(False)
        hints = {
            METHOD_GOOGLE: (
                "Direct Google Translate web endpoint \u2013 fastest "
                "(no proxy hop), no API key. Note: requests go straight "
                "to Google, so tracking is possible."),
            METHOD_LINGVA: (
                "Anonymous Lingva-Translate proxy (lingva.adminforge.de) "
                "\u2013 no API key, no direct Google tracking."),
            METHOD_LIBRE: (
                "Local LibreTranslate instance \u2013 100% offline on "
                "your own PC. Install it yourself once: "
                "pip install libretranslate \u2013 afterwards the "
                "Start/Stop button appears here (default "
                "http://127.0.0.1:5000). If it is not reachable, "
                "Lingva is used as fallback."),
            METHOD_DEEPL: (
                "Official DeepL API \u2013 free key at deepl.com (API "
                "Free plan, 500k chars/month); keys ending in ':fx' are "
                "detected as free-plan keys automatically. If DeepL "
                "fails (e.g. monthly limit reached), Lingva is used as "
                "fallback."),
        }
        self.tr_method_hint.setText(hints.get(method, ""))

    def on_tr_test(self):
        """Tests the currently selected translation service with a
        short phrase and shows the translation or the EXACT error in
        the hint line – no more guessing why the fallback kicked in."""
        method = self.cfg.get("stt_method", METHOD_LINGVA)
        self.tr_test_btn.setEnabled(False)
        self.tr_method_hint.setText(
            f"\U0001F9EA Testing '{method}' \u2026")
        if not hasattr(self, "_tr_test_result"):
            self._tr_test_result = _queue.Queue()

        def worker():
            tr = get_translator(method,
                                deepl_key=self.cfg["stt_deepl_key"],
                                libre_url=self.cfg["stt_libre_url"])
            out = tr.translate("wie geht es dir", "de", "en")
            self._tr_test_result.put((tr.name, out, tr.last_error))
        threading.Thread(target=worker, daemon=True).start()
        if not hasattr(self, "_tr_test_timer"):
            self._tr_test_timer = QTimer(self)
            self._tr_test_timer.timeout.connect(self._poll_tr_test)
        self._tr_test_timer.start(300)

    def _poll_tr_test(self):
        try:
            name, out, err = self._tr_test_result.get_nowait()
        except _queue.Empty:
            return
        self._tr_test_timer.stop()
        self.tr_test_btn.setEnabled(True)
        if out:
            self.tr_method_hint.setText(
                f"\u2705 {name} works: \"wie geht es dir\" \u2192 "
                f"\"{out}\"")
            self.log(f"Translation test ({name}): OK -> {out}")
        else:
            self.tr_method_hint.setText(
                f"\u274C {name} failed: {err or 'no result'}")
            self.log(f"Translation test ({name}): {err or 'no result'}")

    def _libre_port(self):
        """Port from the configured LibreTranslate URL (default 5000)."""
        try:
            from urllib.parse import urlparse
            p = urlparse(self.cfg.get("stt_libre_url")
                         or DEFAULT_LIBRE_URL)
            return p.port or 5000
        except Exception:
            return 5000

    def on_libre_btn(self):
        """One dynamic button: Start <-> Stop, depending on the
        current state."""
        if self.libre_server.running:
            self.on_stop_libre()
        elif libretranslate_installed():
            self.on_start_libre()

    def on_start_libre(self):
        """'Start LibreTranslate': spawns the server detached and
        watches readiness via a poll timer (UI stays fluid)."""
        port = self._libre_port()
        if not self.libre_server.start(port):
            self.tr_method_hint.setText(
                f"\u274C Could not start LibreTranslate: "
                f"{self.libre_server.error}")
            return
        if not hasattr(self, "_libre_srv_timer"):
            self._libre_srv_timer = QTimer(self)
            self._libre_srv_timer.timeout.connect(self._poll_libre_server)
        self._libre_srv_timer.start(750)
        self._update_tr_method_ui()
        # status line AFTER the generic refresh (which resets the hint)
        self.tr_method_hint.setText(
            "\u23F3 Starting LibreTranslate server \u2026 (first run "
            "downloads language models and can take a while)")

    def on_stop_libre(self):
        """'Stop LibreTranslate': terminates the process group in the
        background (SIGTERM, SIGKILL after 5 s)."""
        self.libre_server.stop()
        if hasattr(self, "_libre_srv_timer"):
            self._libre_srv_timer.stop()
        self._update_tr_method_ui()
        self.tr_method_hint.setText("LibreTranslate server stopped.")

    def _poll_libre_server(self):
        """Watches the starting/running server: flips the status line
        to 'running' once it answers, reports errors if it dies."""
        srv = self.libre_server
        if srv.check_ready():
            self._libre_srv_timer.setInterval(3000)  # watchdog mode
            self._update_tr_method_ui()
            self.tr_method_hint.setText(
                f"\u2705 LibreTranslate Server running on port "
                f"{srv.port}")
            return
        if not srv.running:
            self._libre_srv_timer.stop()
            msg = srv.error or "server exited"
            self.log(f"LibreTranslate: {msg}")
            self._update_tr_method_ui()
            self.tr_method_hint.setText(
                f"\u274C LibreTranslate: {msg}")

    def on_libre_url(self, text):
        self.cfg["stt_libre_url"] = text.strip()
        self.save_config_later()
        self.stt.libre_url = text.strip()  # applies live

    def on_deepl_key(self, text):
        self.cfg["stt_deepl_key"] = text
        self.save_config_later()
        self.stt.deepl_key = text  # applies live

    def on_stt_toggled(self, on):
        if on:
            if not SpeechWorker.available():
                self.stt_button.setChecked(False)
                return
            self.stt_recording = True
            self.stt_button.setText("\u23F9  Stop recording")
            self.stt_status_lbl.setText("Starting microphone \u2026")
            self.log(f"Speech to Text: recording started "
                     f"({self.cfg['stt_language']}) \u2013 apps are blocked")
            self.stt.start(self.cfg["stt_language"], self.cfg["stt_output"],
                           self.cfg["stt_method"],
                           self.cfg["stt_deepl_key"],
                           self.cfg["stt_libre_url"])
            self.stt_timer.start(200)
        else:
            self.stt.stop()
            self.stt_recording = False
            self.stt_timer.stop()
            self.stt_button.setText("\U0001F3A4  Start recording")
            self.log("Speech to Text: recording stopped \u2013 apps resume")
            self.update_preview()

    def poll_stt(self):
        while not self.stt.messages.empty():
            kind, payload = self.stt.messages.get_nowait()
            if kind == "text":
                self.log(f"Speech to Text heard: \"{payload}\"")
                self.send_manual_text(payload)
                self.stt_status_lbl.setText(f"Sent: {payload}")
            elif kind == "status":
                self.stt_status_lbl.setText(payload)
            elif kind == "error":
                self.stt_status_lbl.setText(payload)
                self.log(f"Speech to Text ERROR: {payload}")
                self.stt_button.setChecked(False)
            elif kind == "stopped":
                if self.stt_button.isChecked():
                    self.stt_button.setChecked(False)

    def on_pause_changed(self, val):
        self.cfg["textbox_pause_sec"] = val
        self.save_config()

    def on_preset_count(self, val):
        self.cfg["textbox_preset_count"] = val
        self.save_config()
        for i, row in enumerate(self.preset_rows):
            row.setVisible(i < val)

    def on_preset_text(self, idx, text):
        self.cfg["textbox_presets"][idx] = text
        self.save_config_later()

    def send_preset(self, idx):
        text = self.cfg["textbox_presets"][idx].strip()
        if text:
            self.send_manual_text(text)

    def send_manual(self):
        text = self.textbox_input.text().strip()
        if text:
            self.send_manual_text(text)
            self.textbox_input.clear()

    def send_manual_text(self, text):
        """Sends a manual message and pauses the apps briefly so they
        don't overwrite it."""
        if self.osc_client is None:
            return
        if self.cfg["slim_chatbox"]:
            text = text[:CHATBOX_LIMIT - len(SLIM_SUFFIX)]
            payload = text + SLIM_SUFFIX
        else:
            payload = text[:CHATBOX_LIMIT]
        try:
            self.osc_client.send_message(CHATBOX_INPUT, [payload, True, False])
            pause = self.cfg["textbox_pause_sec"]
            self.manual_pause_until = time.time() + pause
            self.last_manual_text = text
            self.log(f"-> MANUAL {CHATBOX_INPUT} \"{text}\" "
                     f"(apps paused for {pause}s)")
            self.update_preview()
            QTimer.singleShot(pause * 1000 + 100, self.update_preview)
        except Exception as e:
            self.log(f"ERROR while sending manual message: {e}")

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
        don_btn = QPushButton("\u2764\uFE0F  Donate (PayPal)")
        don_btn.setObjectName("linkbtn")
        don_btn.setFixedHeight(34)
        don_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        don_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        btn_row.addWidget(don_btn)
        btn_row.addStretch()
        uc.addLayout(btn_row)

        self.update_lbl = QLabel(f"Current version: {VERSION}")
        self.update_lbl.setObjectName("dim")
        self.update_lbl.setWordWrap(True)
        self.update_lbl.setOpenExternalLinks(True)
        uc.addWidget(self.update_lbl)
        layout.addWidget(ucard)

        layout.addStretch()
        return page

    # -------------------------------------------------------- update check
    def check_for_updates(self):
        self.update_lbl.setText("Checking for updates \u2026")
        self._update_result = None

        def worker():
            import urllib.request
            try:
                url = (f"https://api.github.com/repos/{GITHUB_REPO}"
                       "/releases/latest")
                req = urllib.request.Request(
                    url, headers={"User-Agent": "OSC-DreamChatbox"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = json.loads(r.read().decode("utf-8"))
                self._update_result = (data.get("tag_name", ""),
                                       data.get("html_url", ""))
            except Exception as e:
                self._update_result = ("__error__", str(e))

        import threading
        threading.Thread(target=worker, daemon=True).start()
        self._update_poll = QTimer(self)
        self._update_poll.setInterval(250)

        def poll():
            if self._update_result is None:
                return
            self._update_poll.stop()
            tag, info = self._update_result
            if tag == "__error__":
                self.update_lbl.setText(
                    f"Update check failed (no releases yet or offline). "
                    f"Current version: {VERSION}")
            elif tag and tag != VERSION:
                self.update_lbl.setText(
                    f"\U0001F389 New version available: <b>{tag}</b> "
                    f"(you have {VERSION}) \u2013 "
                    f"<a href=\"{info}\">open download page</a>")
            else:
                self.update_lbl.setText(
                    f"\u2705 You are up to date ({VERSION}).")
        self._update_poll.timeout.connect(poll)
        self._update_poll.start()

    # ------------------------------------------------------------- ui events
    def switch_page(self, idx):
        self.pages.setCurrentIndex(idx)
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == idx)

    def apply_config_to_ui(self):
        self._block_updating = True
        for i, edit in enumerate(self.status_edits):
            edit.setText(self.cfg["status_texts"][i])
        self.status_count_spin.setValue(self.cfg["status_count"])
        self.status_cycle_spin.setValue(self.cfg["status_cycle_sec"])
        for i, row in enumerate(self.status_rows):
            row.setVisible(i < self.cfg["status_count"])
        self.toggle_active.setChecked(self.cfg["status_active"])
        self.toggle_media.setChecked(self.cfg["media_active"])
        self.chk_artist.setChecked(self.cfg["media_show_artist"])
        self.chk_title.setChecked(self.cfg["media_show_title"])
        self.chk_time.setChecked(self.cfg["media_show_time"])
        self.chk_bar.setChecked(self.cfg["media_show_bar"])
        self.bar_style_combo.blockSignals(True)
        idx = min(CUSTOM_STYLE_INDEX,
                  max(0, int(self.cfg.get("media_bar_style", 2))))
        self.bar_style_combo.setCurrentIndex(idx)
        self.bar_style_combo.blockSignals(False)
        custom = dict(DEFAULT_CUSTOM_BAR)
        custom.update(self.cfg.get("media_bar_custom", {}))
        self.cfg["media_bar_custom"] = custom
        for key, edit in self.bar_custom_inputs.items():
            edit.blockSignals(True)
            edit.setText(custom.get(key, ""))
            edit.blockSignals(False)
        self.bar_custom_box.setVisible(idx == CUSTOM_STYLE_INDEX)
        self._update_bar_custom_preview()
        self.poll_spin.setValue(self.cfg["media_poll_sec"])
        self.chk_media_icon.setChecked(self.cfg["media_icon"])
        self.chk_media_custom.setChecked(self.cfg["media_custom"])
        self.media_custom_input.setText(self.cfg["media_custom_template"])
        for i, edit in enumerate(self.preset_edits):
            edit.setText(self.cfg["textbox_presets"][i])
        self.preset_count_spin.setValue(self.cfg["textbox_preset_count"])
        for i, row in enumerate(self.preset_rows):
            row.setVisible(i < self.cfg["textbox_preset_count"])
        self.pause_spin.setValue(self.cfg["textbox_pause_sec"])
        self.toggle_stt_block.setChecked(self.cfg["stt_block"])
        idx = self.stt_lang_combo.findData(self.cfg["stt_language"])
        if idx >= 0:
            self.stt_lang_combo.setCurrentIndex(idx)
        oidx = self.stt_out_combo.findData(self.cfg["stt_output"])
        if oidx >= 0:
            self.stt_out_combo.setCurrentIndex(oidx)
        # Migration: alte "stt_deepl"-Checkbox-Configs uebernehmen
        if self.cfg.get("stt_deepl") and self.cfg.get(
                "stt_method", METHOD_LINGVA) == METHOD_LINGVA:
            self.cfg["stt_method"] = METHOD_DEEPL
        self.tr_method_combo.blockSignals(True)
        midx = next((i for i in range(self.tr_method_combo.count())
                     if self.tr_method_combo.itemData(i)
                     == self.cfg.get("stt_method", METHOD_LINGVA)), 0)
        self.tr_method_combo.setCurrentIndex(midx)
        self.tr_method_combo.blockSignals(False)
        self.deepl_key_input.setText(self.cfg["stt_deepl_key"])
        self.libre_url_input.setText(self.cfg.get("stt_libre_url", ""))
        self._update_tr_method_ui()
        self.toggle_aio.setChecked(self.cfg["aio_active"])
        self.aio_count_spin.setValue(self.cfg["aio_count"])
        self.chk_aio_rotate.setChecked(self.cfg["aio_rotate"])
        self.aio_rotate_spin.setValue(self.cfg["aio_rotate_sec"])
        for i, edit in enumerate(self.aio_edits):
            edit.setText(self.cfg["aio_templates"][i])
        for i, row in enumerate(self.aio_rows):
            row.setVisible(i < self.cfg["aio_count"])
        self.chk_hw_flame.setChecked(self.cfg["hw_flame"])
        self.chk_hw_custom.setChecked(self.cfg["hw_custom"])
        self.hw_custom_input.setText(self.cfg["hw_custom_template"])
        self.toggle_hw.setChecked(self.cfg["hw_active"])
        self.chk_gpu_usage.setChecked(self.cfg["hw_gpu_usage"])
        self.chk_gpu_name.setChecked(self.cfg["hw_gpu_name"])
        self.chk_gpu_custom.setChecked(self.cfg["hw_gpu_custom"])
        self.gpu_custom_input.setText(self.cfg["hw_gpu_custom_name"])
        self.chk_gpu_temp.setChecked(self.cfg["hw_gpu_temp"])
        self.chk_vram_used.setChecked(self.cfg["hw_vram_used"])
        self.chk_vram_pct.setChecked(self.cfg["hw_vram_pct"])
        self.chk_ram_used.setChecked(self.cfg["hw_ram_used"])
        self.chk_ram_pct.setChecked(self.cfg["hw_ram_pct"])
        self.ram_type_input.setText(self.cfg["hw_ram_type"])
        self.chk_cpu_usage.setChecked(self.cfg["hw_cpu_usage"])
        self.chk_cpu_name.setChecked(self.cfg["hw_cpu_name"])
        self.chk_cpu_custom.setChecked(self.cfg["hw_cpu_custom"])
        self.cpu_custom_input.setText(self.cfg["hw_cpu_custom_name"])
        self.chk_cpu_temp.setChecked(self.cfg["hw_cpu_temp"])
        self.hw_poll_spin.setValue(self.cfg["hw_poll_sec"])
        self.toggle_send.setChecked(self.cfg["send_to_vrchat"])
        self.interval_spin.setValue(self.cfg["interval_sec"])
        self.toggle_slim.setChecked(self.cfg["slim_chatbox"])
        self.toggle_oscquery.blockSignals(True)
        self.toggle_oscquery.setChecked(
            bool(self.cfg.get("oscquery_enabled", True)) and HAS_ZEROCONF)
        self.toggle_oscquery.blockSignals(False)
        self.ip_input.setText(self.cfg["osc_ip"])
        self.port_input.setValue(self.cfg["osc_port"])
        self.toggle_debug.setChecked(self.cfg["debug"])
        self.update_preview()
        self._block_updating = False

    def on_status_text(self, idx, text):
        self.cfg["status_texts"][idx] = text
        self.save_config_later()
        self.update_preview()

    def on_status_count(self, val):
        self.cfg["status_count"] = val
        self.save_config()
        for i, row in enumerate(self.status_rows):
            row.setVisible(i < val)
        self.status_index = 0
        self.update_timers()
        self.update_preview()

    def on_status_cycle(self, val):
        self.cfg["status_cycle_sec"] = val
        self.save_config()
        self.update_timers()

    def advance_status(self):
        """Switches to a RANDOM other status text (never the same one
        twice in a row) instead of cycling sequentially."""
        texts = [t.strip() for t in
                 self.cfg["status_texts"][:self.cfg["status_count"]]]
        texts = [t for t in texts if t]
        if len(texts) > 1:
            current = self.status_index % len(texts)
            choices = [i for i in range(len(texts)) if i != current]
            self.status_index = random.choice(choices)
        self.update_preview()

    def current_status_text(self):
        """Returns the currently shown status text (switches randomly
        between the non-empty texts every status_cycle_sec seconds)."""
        texts = [t.strip() for t in
                 self.cfg["status_texts"][:self.cfg["status_count"]]]
        texts = [t for t in texts if t]
        if not texts:
            return ""
        return texts[self.status_index % len(texts)]

    def on_active_toggled(self, on):
        if on:
            self._manual_app_enable()
        self.cfg["status_active"] = on
        self.save_config()
        self.log(f"Personal Status: {'ACTIVE' if on else 'inactive'}")
        self.update_timers()
        self.update_preview()

    def on_media_toggled(self, on):
        if on:
            self._manual_app_enable()
        self.cfg["media_active"] = on
        self.save_config()
        self.log(f"MediaPlay: {'ACTIVE' if on else 'inactive'}")
        if on:
            self.poll_media()
        else:
            self.media_info = None
        self.update_timers()
        self.update_preview()

    def on_media_template(self, text):
        self.cfg["media_custom_template"] = text
        self.save_config_later()
        self.update_preview()

    def on_bar_style(self, idx):
        self.cfg["media_bar_style"] = int(idx)
        self.bar_custom_box.setVisible(idx == CUSTOM_STYLE_INDEX)
        self._update_bar_custom_preview()
        self.save_config()
        self.update_preview()

    def on_bar_custom(self, key, text):
        custom = dict(DEFAULT_CUSTOM_BAR)
        custom.update(self.cfg.get("media_bar_custom", {}))
        custom[key] = text
        self.cfg["media_bar_custom"] = custom
        self._update_bar_custom_preview()
        self.save_config_later()
        self.update_preview()

    def _update_bar_custom_preview(self):
        try:
            bar = make_songbar(0.4, CUSTOM_STYLE_INDEX, SONGBAR_LEN,
                               self.cfg.get("media_bar_custom"))
        except Exception:
            bar = ""
        self.bar_custom_preview.setText(f"Preview:  {bar}")

    def on_media_option(self, key, on):
        self.cfg[key] = on
        self.save_config()
        self.update_preview()

    def on_poll_changed(self, val):
        self.cfg["media_poll_sec"] = val
        self.save_config()
        self.log(f"MediaPlay poll interval: every {val} seconds")
        self.update_timers()

    def on_hw_toggled(self, on):
        if on:
            self._manual_app_enable()
        self.cfg["hw_active"] = on
        self.save_config()
        self.log(f"Hardware: {'ACTIVE' if on else 'inactive'}")
        if on:
            self.hw.cpu_usage()  # prime the CPU counter
            self.poll_hw()
        else:
            self.hw_info = None
        self.update_timers()
        self.update_preview()

    def on_hw_option(self, key, on):
        self.cfg[key] = on
        self.save_config()
        self.update_preview()

    def on_hw_text(self, key, text):
        self.cfg[key] = text
        self.save_config_later()
        self.update_preview()

    def on_hw_poll_changed(self, val):
        self.cfg["hw_poll_sec"] = val
        self.save_config()
        self.log(f"Hardware poll interval: every {val} seconds")
        self.update_timers()

    def on_aio_toggled(self, on):
        if on:
            self._manual_app_enable()
        self.cfg["aio_active"] = on
        self.save_config()
        self.log(f"All in one: {'ACTIVE' if on else 'inactive'} "
                 f"{'(apps now feed into the AIO string)' if on else ''}")
        self.aio_index = 0
        self.update_timers()
        self.update_preview()

    def on_aio_count(self, val):
        self.cfg["aio_count"] = val
        self.save_config()
        for i, row in enumerate(self.aio_rows):
            row.setVisible(i < val)
        self.aio_index = 0
        self.update_timers()
        self.update_preview()

    def on_aio_rotate(self, on):
        self.cfg["aio_rotate"] = on
        self.save_config()
        self.aio_index = 0
        self.update_timers()
        self.update_preview()

    def on_aio_rotate_sec(self, val):
        self.cfg["aio_rotate_sec"] = val
        self.save_config()
        self.update_timers()

    def on_aio_text(self, idx, text):
        self.cfg["aio_templates"][idx] = text
        self.save_config_later()
        self.update_preview()

    def advance_aio(self):
        self.aio_index += 1
        self.update_preview()

    def _aio_active_templates(self):
        tpls = [t for t in self.cfg["aio_templates"][:self.cfg["aio_count"]]
                if t.strip()]
        return tpls

    def build_aio_lines(self):
        """Builds the AIO output: one combined custom string with values
        from all active apps."""
        tpls = self._aio_active_templates()
        if not tpls:
            return []
        tpl = tpls[self.aio_index % len(tpls)]
        vals = {}
        # Personal Status texts
        if self.cfg["status_active"]:
            vals["text"] = self.current_status_text() or None
            for i in range(10):
                vals[f"text_{i + 1}"] = (self.cfg["status_texts"][i].strip()
                                         or None)
        else:
            vals["text"] = None
            for i in range(10):
                vals[f"text_{i + 1}"] = None
        # MediaPlay values
        if self.cfg["media_active"] and self.media_info:
            vals.update(self._media_values(self.media_info))
        vals.setdefault("icon_sound", "\U0001F3B5")
        # Hardware values (incl. temp_icon behaviour)
        if self.cfg["hw_active"] and self.hw_info:
            hw = self._hw_values(self.hw_info)
            if re.search(r"\{\s*temp_icon\s*\}", tpl, re.IGNORECASE):
                gpu = self.hw_info.get("gpu") or {}
                if self.cfg["hw_gpu_temp"] and gpu.get("temp") is not None:
                    hw["gpu_temp"] = f"{gpu['temp']:.0f}"
                if self.cfg["hw_cpu_temp"] and self.hw_info.get("cpu_temp") is not None:
                    hw["cpu_temp"] = f"{self.hw_info['cpu_temp']:.0f}"
            vals.update(hw)
        vals["temp_icon"] = "\U0001F525" if self.cfg["hw_flame"] else "\u00b0C"
        vals.setdefault("icon_flame", "\U0001F525")
        text = apply_template(tpl, vals)
        return text.split("\n") if text else []

    def on_send_toggled(self, on):
        self.cfg["send_to_vrchat"] = on
        self.save_config()
        self.log(f"SendToVRChat: {'ON' if on else 'OFF'}")
        self.update_timers()
        if on:
            self.send_now()  # send once immediately

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

    # --------------------------------------------------------------- logic
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
        lost) VRChat target; also refreshes the status label."""
        target = self.oscq.vrchat_target()
        if target != self._oscq_applied:
            self._oscq_applied = target
            self.update_osc_client()
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

    def anything_to_send(self):
        status_on = self.cfg["status_active"] and bool(self.current_status_text())
        media_on = self.cfg["media_active"] and self.media_info is not None
        return status_on or media_on

    def update_timers(self):
        # media poll timer
        if self.cfg["media_active"]:
            self.media_timer.start(self.cfg["media_poll_sec"] * 1000)
        else:
            self.media_timer.stop()
        # hardware poll timer
        if self.cfg["hw_active"]:
            self.hw_timer.start(self.cfg["hw_poll_sec"] * 1000)
        else:
            self.hw_timer.stop()
        # status text rotation
        active_texts = [t for t in
                        self.cfg["status_texts"][:self.cfg["status_count"]]
                        if t.strip()]
        if (self.cfg["status_active"] and self.cfg["status_count"] > 1
                and len(active_texts) > 1):
            self.rotate_timer.start(self.cfg["status_cycle_sec"] * 1000)
        else:
            self.rotate_timer.stop()
            self.status_index = 0
        # AIO string rotation (only when AIO active, rotation enabled
        # and more than one non-empty string exists)
        if (self.cfg["aio_active"] and self.cfg["aio_rotate"]
                and len(self._aio_active_templates()) > 1):
            self.aio_timer.start(self.cfg["aio_rotate_sec"] * 1000)
        else:
            self.aio_timer.stop()
            self.aio_index = 0
        # send timer
        if self.cfg["send_to_vrchat"]:
            self.send_timer.start(self.cfg["interval_sec"] * 1000)
        else:
            self.send_timer.stop()

    def poll_media(self):
        info = self.media.fetch()
        changed = (info or {}).get("title") != (self.media_info or {}).get("title")
        self.media_info = info
        if info:
            self.media_status_lbl.setText(
                f"Detected player: {info['player']}"
                f"  ({'playing' if info['playing'] else 'paused'})")
            if changed:
                self.log(f"MediaPlay: now playing \"{info['artist']} – {info['title']}\" "
                         f"({info['player']})")
        else:
            self.media_status_lbl.setText("No media player detected.")
        self.update_preview()

    def _media_values(self, info):
        """Placeholder values for the custom string. They automatically
        follow the checkboxes above (unchecked -> empty)."""
        c = self.cfg
        t = info["title"]
        if len(t) > TITLE_MAX_LEN:
            t = t[:TITLE_MAX_LEN - 1] + "\u2026"
        bar = ""
        if info["length"] > 0:
            frac = min(1.0, max(0.0, info["position"] / info["length"]))
            bar = make_songbar(frac, self.cfg["media_bar_style"],
                               SONGBAR_LEN,
                               self.cfg.get("media_bar_custom"))
        # music timer WITHOUT seconds – hours and minutes only
        time_str = (f"{fmt_time_hm(info['position'])}/"
                    f"{fmt_time_hm(info['length'])}"
                    if info["length"] > 0
                    else fmt_time_hm(info["position"]))
        return {
            "artist": info["artist"] if c["media_show_artist"] else None,
            "title": t if c["media_show_title"] else None,
            "position": fmt_time_hm(info["position"]),
            "length": (fmt_time_hm(info["length"])
                       if info["length"] > 0 else None),
            "time": time_str if c["media_show_time"] else None,
            "bar": (bar or None) if c["media_show_bar"] else None,
            "player": info["player"],
            "icon_sound": "\U0001F3B5",
        }

    def build_media_lines(self):
        """Builds the media text lines based on the checkboxes."""
        info = self.media_info
        if not info:
            return []
        # custom string mode
        if self.cfg["media_custom"] and self.cfg["media_custom_template"].strip():
            text = apply_template(self.cfg["media_custom_template"],
                                  self._media_values(info))
            lines = text.split("\n") if text else []
            if lines and self.cfg["media_icon"]:
                lines[0] = f"\U0001F3B5 {lines[0]} \U0001F3B5"
            return lines
        lines = []
        parts = []
        if self.cfg["media_show_artist"] and info["artist"]:
            parts.append(info["artist"])
        if self.cfg["media_show_title"] and info["title"]:
            t = info["title"]
            if len(t) > TITLE_MAX_LEN:
                t = t[:TITLE_MAX_LEN - 1] + "…"
            parts.append(t)
        text = " : ".join(parts)
        if self.cfg["media_show_time"] and info["length"] > 0:
            time_str = (f"{fmt_time_hm(info['position'])}/"
                        f"{fmt_time_hm(info['length'])}")
            text = f"{text} | {time_str}" if text else time_str
        if text:
            lines.append(text)
        if self.cfg["media_show_bar"] and info["length"] > 0:
            frac = min(1.0, max(0.0, info["position"] / info["length"]))
            lines.append(make_songbar(frac, self.cfg["media_bar_style"],
                                      SONGBAR_LEN,
                                      self.cfg.get("media_bar_custom")))
        if lines and self.cfg["media_icon"]:
            lines[0] = f"\U0001F3B5 {lines[0]} \U0001F3B5"
        return lines

    def poll_hw(self):
        self.hw_info = self.hw.snapshot()
        gpu = self.hw_info.get("gpu")
        self.hw_status_lbl.setText(
            "GPU backend: " + ("NVIDIA (nvidia-smi)" if self.hw.has_nvidia
                               else ("AMD (sysfs)" if self.hw.amd_card
                                     else "none detected – GPU values unavailable")))
        self.update_preview()

    def _temp_str(self, t):
        if t is None:
            return None
        return f"{t:.0f}\U0001F525" if self.cfg["hw_flame"] else f"{t:.0f}\u00b0C"

    def _hw_values(self, info):
        """Placeholder values for the custom string. They automatically
        follow the checkboxes above (unchecked -> empty / generic name)."""
        c = self.cfg
        gpu = info.get("gpu") or {}
        ram = info.get("ram") or {}
        # names: custom > auto-detected (if "name" is checked) > generic
        if c["hw_gpu_custom"] and c["hw_gpu_custom_name"].strip():
            gpu_name = c["hw_gpu_custom_name"].strip()
        elif c["hw_gpu_name"]:
            gpu_name = self.hw.gpu_name_auto
        else:
            gpu_name = "GPU"
        if c["hw_cpu_custom"] and c["hw_cpu_custom_name"].strip():
            cpu_name = c["hw_cpu_custom_name"].strip()
        elif c["hw_cpu_name"]:
            cpu_name = self.hw.cpu_name_auto
        else:
            cpu_name = "CPU"
        # VRAM / RAM: numbers and/or % depending on the checkboxes
        vram_parts = []
        if c["hw_vram_used"] and gpu.get("vram_used") is not None and gpu.get("vram_total"):
            vram_parts.append(f"{gpu['vram_used']:.0f}/{gpu['vram_total']:.0f}GB")
        if c["hw_vram_pct"] and gpu.get("vram_pct") is not None:
            vram_parts.append(f"{gpu['vram_pct']:.0f}%")
        ram_parts = []
        if ram:
            if c["hw_ram_used"]:
                ram_parts.append(f"{ram['used']:.0f}/{ram['total']:.0f}GB")
            if c["hw_ram_pct"]:
                ram_parts.append(f"{ram['pct']:.0f}%")
        return {
            "gpu_name": gpu_name,
            "gpu_usage": (f"{gpu['usage']:.0f}%"
                          if c["hw_gpu_usage"] and gpu.get("usage") is not None else None),
            "gpu_temp": (self._temp_str(gpu.get("temp")) if c["hw_gpu_temp"] else None),
            "vram_usage": " ".join(vram_parts) or None,
            "vram_pct": (f"{gpu['vram_pct']:.0f}%"
                         if c["hw_vram_pct"] and gpu.get("vram_pct") is not None else None),
            "cpu_name": cpu_name,
            "cpu_usage": (f"{info['cpu_usage']:.0f}%"
                          if c["hw_cpu_usage"] and info.get("cpu_usage") is not None else None),
            "cpu_temp": (self._temp_str(info.get("cpu_temp")) if c["hw_cpu_temp"] else None),
            "ram_usage": " ".join(ram_parts) or None,
            "ram_pct": (f"{ram['pct']:.0f}%" if c["hw_ram_pct"] and ram else None),
            "ram_type": c["hw_ram_type"].strip() or None,
            "icon_flame": "\U0001F525",
        }

    def build_hw_lines(self):
        info = self.hw_info
        if not info:
            return []
        # custom string mode
        if self.cfg["hw_custom"] and self.cfg["hw_custom_template"].strip():
            tpl = self.cfg["hw_custom_template"]
            vals = self._hw_values(info)
            # {temp_icon} = the unit as its own variable (flame or degC).
            # If the template uses it, the temps become bare numbers so
            # you can format/replace the unit yourself.
            if re.search(r"\{\s*temp_icon\s*\}", tpl, re.IGNORECASE):
                gpu = info.get("gpu") or {}
                if self.cfg["hw_gpu_temp"] and gpu.get("temp") is not None:
                    vals["gpu_temp"] = f"{gpu['temp']:.0f}"
                if self.cfg["hw_cpu_temp"] and info.get("cpu_temp") is not None:
                    vals["cpu_temp"] = f"{info['cpu_temp']:.0f}"
            vals["temp_icon"] = "\U0001F525" if self.cfg["hw_flame"] else "\u00b0C"
            text = apply_template(tpl, vals)
            return text.split("\n") if text else []
        lines = []
        # ---------- GPU line ----------
        gpu = info.get("gpu") or {}
        parts = []
        if self.cfg["hw_gpu_custom"] and self.cfg["hw_gpu_custom_name"].strip():
            parts.append(self.cfg["hw_gpu_custom_name"].strip())
        elif self.cfg["hw_gpu_name"]:
            parts.append(self.hw.gpu_name_auto)
        else:
            parts.append("GPU")
        vals = []
        if self.cfg["hw_gpu_usage"] and gpu.get("usage") is not None:
            vals.append(f"{gpu['usage']:.0f}%")
        if self.cfg["hw_gpu_temp"] and gpu.get("temp") is not None:
            vals.append(self._temp_str(gpu["temp"]))
        vram = []
        if self.cfg["hw_vram_used"] and gpu.get("vram_used") is not None and gpu.get("vram_total"):
            vram.append(f"{gpu['vram_used']:.0f}/{gpu['vram_total']:.0f}GB")
        if self.cfg["hw_vram_pct"] and gpu.get("vram_pct") is not None:
            vram.append(f"{gpu['vram_pct']:.0f}%")
        line = parts[0]
        if vals:
            line += ": " + " ".join(vals)
        if vram:
            line += " | VRAM " + " ".join(vram)
        if vals or vram:
            lines.append(line)
        # ---------- CPU line ----------
        cparts = []
        if self.cfg["hw_cpu_custom"] and self.cfg["hw_cpu_custom_name"].strip():
            cname = self.cfg["hw_cpu_custom_name"].strip()
        elif self.cfg["hw_cpu_name"]:
            cname = self.hw.cpu_name_auto
        else:
            cname = "CPU"
        cvals = []
        if self.cfg["hw_cpu_usage"] and info.get("cpu_usage") is not None:
            cvals.append(f"{info['cpu_usage']:.0f}%")
        if self.cfg["hw_cpu_temp"] and info.get("cpu_temp") is not None:
            cvals.append(self._temp_str(info["cpu_temp"]))
        if cvals:
            lines.append(f"{cname}: " + " ".join(cvals))
        # ---------- RAM line ----------
        ram = info.get("ram")
        if ram:
            rvals = []
            if self.cfg["hw_ram_used"]:
                rvals.append(f"{ram['used']:.0f}/{ram['total']:.0f}GB")
            if self.cfg["hw_ram_pct"]:
                rvals.append(f"{ram['pct']:.0f}%")
            if rvals:
                rtype = self.cfg["hw_ram_type"].strip()
                lines.append("RAM: " + " ".join(rvals) + (f" {rtype}" if rtype else ""))
        return lines

    def build_payload(self):
        """Combines all active apps in the order of the cards (drag to change).
        If All in one is active, only the AIO string is sent instead."""
        if self.cfg["aio_active"]:
            return "\n".join(self.build_aio_lines())
        lines = []
        for key in self.cfg["app_order"]:
            if key == "status" and self.cfg["status_active"]:
                cur = self.current_status_text()
                if cur:
                    lines.append(cur)
            elif key == "media" and self.cfg["media_active"]:
                lines.extend(self.build_media_lines())
            elif key == "hardware" and self.cfg["hw_active"]:
                lines.extend(self.build_hw_lines())
        return "\n".join(lines)

    def send_now(self):
        if self.stt_recording:
            return  # speech to text is recording - sending is blocked
        if time.time() < self.manual_pause_until:
            return  # a manual textbox message is currently shown
        text = self.build_payload()
        if not text or self.osc_client is None:
            return
        if self.cfg["slim_chatbox"]:
            # the slim suffix ALWAYS stays at the end - if the text is too
            # long, the text itself gets trimmed instead of dropping the
            # suffix (otherwise the big box would suddenly come back)
            text = text[:CHATBOX_LIMIT - len(SLIM_SUFFIX)]
            payload = text + SLIM_SUFFIX
        else:
            payload = text[:CHATBOX_LIMIT]
        try:
            # /chatbox/input  [text, send immediately (no keyboard), no sound]
            self.osc_client.send_message(CHATBOX_INPUT, [payload, True, False])
            slim = " [+SLIM]" if payload != text else ""
            self.log(f"-> OSC {CHATBOX_INPUT} {text.count(chr(10)) + 1} line(s), "
                     f"{len(payload)} chars{slim} "
                     f"to {self.cfg['osc_ip']}:{self.cfg['osc_port']}\n{text}")
        except Exception as e:
            self.log(f"ERROR while sending: {e}")

    def update_preview(self):
        if time.time() < self.manual_pause_until and self.last_manual_text:
            text = self.last_manual_text
        else:
            text = self.build_payload()
        self.preview_label.setText(text if text else "[Status Text goes here]")
        n = len(text) + (len(SLIM_SUFFIX) if self.cfg["slim_chatbox"] else 0)
        if not text:
            self.char_count_lbl.setText("")
        elif n > CHATBOX_LIMIT:
            self.char_count_lbl.setText(f"⚠ {n}/{CHATBOX_LIMIT} – too long, will be cut!")
            self.char_count_lbl.setStyleSheet("color: #d9884a; font-size: 12px;")
        else:
            self.char_count_lbl.setText(f"{n}/{CHATBOX_LIMIT}")
            self.char_count_lbl.setStyleSheet("")

    def log(self, msg):
        if self.debug_console is not None:
            self.debug_console.log(msg)
        print(msg)

    def closeEvent(self, ev):
        self.stt.stop()
        self.libre_server.stop_sync()   # no orphaned server on exit
        self.oscq.stop()
        self._save_timer.stop()
        self._write_config()
        self.debug_console.close()
        super().closeEvent(ev)
