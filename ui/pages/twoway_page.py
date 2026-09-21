"""
ui/pages/twoway_page.py - two-way translation: hear the OTHER side too

Speech to Text translates what YOU say before it reaches the chatbox.
This is the way back: a second, independent listener records what the
game is PLAYING (a monitor of the output on Linux, "Stereo Mix" or a
virtual cable on Windows), transcribes the other players in their
language and shows the translation in yours - inside the app, never in
the chatbox. Everyone else already hears the original; broadcasting it
again would only overwrite your own messages.

It is a second core.speechtotext.SpeechWorker with its own helper
process, so it runs next to your own recording without touching it and
does NOT block the apps. Translation settings (service, keys, servers)
are shared with Speech to Text and picked up live.

A small text field sits underneath for the other direction of the same
problem: paste or type what someone wrote (their chatbox, a Discord
message) and read it in your language.

Mixin for MainWindow; all `self.*` refer to the MainWindow instance.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout,
                             QLabel, QLineEdit, QMenu, QPlainTextEdit,
                             QPushButton,
                             QSlider, QSpinBox, QVBoxLayout, QWidget)

from core import audiolevel, micgroups
from core.constants import (CHAT_MODE_DIRECT, CHAT_MODE_LINE, CHAT_MODE_VARS,
                            ORIGIN_TWOWAY)
from core.plugins import ANCHORS, DEFAULT_ANCHOR
from core.backends import app_capture, mic_pactl
from core.osinfo import IS_WINDOWS
from core.speechtotext import (LANGUAGES, OUTPUT_LANGUAGES, MicTest,
                               SpeechWorker, clear_driver_stuck,
                               list_microphone_groups, resolve_entry)
from core.translators import translate_with_fallback
from ui.miclevel import LevelMeter
from ui.ui_main import ToggleLabel, ToggleSwitch

#: sensitivity defaults for game audio. Automatic ON by default; with loud
#: world music the automatic value can climb until nothing counts as
#: speech - then switch it off and use Measure. The phrase cap is shorter
#: than for your own voice, because an instance rarely goes fully quiet.
TWOWAY_DEFAULTS = {
    "stt_twoway_energy_auto": True,
    "stt_twoway_energy_threshold": 400,
    "stt_twoway_pause_sec": 0.7,
    "stt_twoway_min_phrase_sec": 0.3,
    "stt_twoway_phrase_limit": 8,
}

#: "Send as" for Two-way - the same three routes as the To Text card
TWOWAY_SEND_MODES = (
    ("Standard \u2013 message on its own, apps paused", CHAT_MODE_DIRECT),
    ("Line \u2013 as a line inside the normal output", CHAT_MODE_LINE),
    ("Variables \u2013 only {2wayin} / {2wayout}", CHAT_MODE_VARS),
)
TWOWAY_MODE_HINTS = {
    CHAT_MODE_DIRECT: (
        "The translation takes over the chatbox on its own and the apps "
        "pause. Careful: it also overwrites what YOU just said."),
    CHAT_MODE_LINE: (
        "The translation becomes a line inside the normal output, at the "
        "position and for the hold time set for To Text above."),
    CHAT_MODE_VARS: (
        "Nothing shows up on its own: {2wayin} (what they said) and "
        "{2wayout} (the translation) are filled, and an All-in-one string "
        "or a template decides where they go. Hold time as above."),
}

#: which programs Two-way records (Linux, core/backends/app_capture.py)
TWOWAY_FILTER_MODES = (
    ("All sound of the source above", app_capture.MODE_OFF),
    ("Only these apps (e.g. VRChat)", app_capture.MODE_ONLY),
    ("Everything except these apps (e.g. Spotify)", app_capture.MODE_EXCEPT),
)

#: how many translated lines the log keeps before the oldest go
TWOWAY_MAX_LINES = 200

#: config value of "my language" = follow the Speech to Text input
TWOWAY_FOLLOW = ""


class TwoWayMixin:
    # ------------------------------------------------------------ build
    def build_twoway_section(self, sc):
        """Appends the collapsible Two-way block to the To Text card."""
        self.stt_twoway = SpeechWorker()
        self.twoway_router = app_capture.AppRouter(self.log)
        self.twoway_listening = False
        self._twoway_preflight = 0
        self.twoway_timer = QTimer(self)
        self.twoway_timer.timeout.connect(self.poll_twoway)

        self.twoway_expander = self.make_settings_expander(
            lambda on: self.set_expanded(
                self.twoway_expander, self.twoway_box, on,
                "Two-way translation (hear others)"),
            "Two-way translation (hear others)")
        sc.addWidget(self.twoway_expander)
        self.twoway_box = QWidget()
        tw = QVBoxLayout(self.twoway_box)
        tw.setContentsMargins(8, 4, 0, 4)
        tw.setSpacing(6)

        intro = QLabel(
            "Translates the OTHER players for you: the app listens to "
            "what VRChat plays, transcribes it and shows the translation "
            "here. By default only you see it \u2013 switch on \u201cSend "
            "to chatbox\u201d at the bottom to share it. The apps keep "
            "running. Uses the translation service selected above. Works "
            "best with one speaker at a time: several voices at once, or "
            "loud music, confuse the recogniser \u2013 VRChat's Earmuffs "
            "mode and a higher threshold help.")
        intro.setObjectName("dim")
        intro.setWordWrap(True)
        tw.addWidget(intro)

        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Listen to:"))
        self.twoway_src_combo = QComboBox()
        self.twoway_src_combo.currentIndexChanged.connect(
            self.on_twoway_source)
        src_row.addWidget(self.twoway_src_combo, 1)
        tw.addLayout(src_row)
        src_hint = QLabel(
            "Windows: pick “Stereo Mix” or a virtual cable "
            "(VB-CABLE) that VRChat plays into." if IS_WINDOWS else
            "Pick the “Monitor” of the output VRChat plays on "
            "(your headset / speakers) – not your microphone.")
        src_hint.setObjectName("dim")
        src_hint.setWordWrap(True)
        tw.addWidget(src_hint)
        self._build_twoway_filter(tw)
        self._build_twoway_tuning(tw)

        their_row = QHBoxLayout()
        their_row.addWidget(QLabel("They speak:"))
        self.twoway_lang_combo = QComboBox()
        for name, code in LANGUAGES:
            self.twoway_lang_combo.addItem(name, code)
        self.twoway_lang_combo.currentIndexChanged.connect(
            self.on_twoway_language)
        their_row.addWidget(self.twoway_lang_combo)
        their_row.addStretch()
        tw.addLayout(their_row)

        mine_row = QHBoxLayout()
        mine_row.addWidget(QLabel("Translate into:"))
        self.twoway_target_combo = QComboBox()
        self.twoway_target_combo.addItem(
            "My input language (from above)", TWOWAY_FOLLOW)
        for name, code in OUTPUT_LANGUAGES:
            if code:
                self.twoway_target_combo.addItem(name, code)
        self.twoway_target_combo.currentIndexChanged.connect(
            self.on_twoway_target)
        mine_row.addWidget(self.twoway_target_combo)
        mine_row.addStretch()
        tw.addLayout(mine_row)

        btn_row = QHBoxLayout()
        self.twoway_btn = QPushButton("\U0001F442  Start listening")
        self.twoway_btn.setObjectName("recbtn")
        self.twoway_btn.setCheckable(True)
        self.twoway_btn.setFixedHeight(34)
        self.twoway_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.twoway_btn.toggled.connect(self.on_twoway_toggled)
        btn_row.addWidget(self.twoway_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("linkbtn")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(lambda _=False: self.twoway_log.clear())
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        tw.addLayout(btn_row)

        self.twoway_status_lbl = QLabel("")
        self.twoway_status_lbl.setObjectName("dim")
        self.twoway_status_lbl.setWordWrap(True)
        tw.addWidget(self.twoway_status_lbl)

        self.twoway_log = QPlainTextEdit()
        self.twoway_log.setReadOnly(True)
        self.twoway_log.setMaximumBlockCount(TWOWAY_MAX_LINES)
        self.twoway_log.setMinimumHeight(120)
        self.twoway_log.setPlaceholderText(
            "Translations of what the others say appear here …")
        tw.addWidget(self.twoway_log)

        # ---- typed/pasted text from someone else ----
        in_row = QHBoxLayout()
        self.twoway_text_input = QLineEdit()
        self.twoway_text_input.setPlaceholderText(
            "Paste what someone wrote … (Enter = translate for me)")
        self.twoway_text_input.returnPressed.connect(self.on_twoway_text)
        in_row.addWidget(self.twoway_text_input, 1)
        self.twoway_text_btn = QPushButton("Translate")
        self.twoway_text_btn.setObjectName("sendbtn")
        self.twoway_text_btn.setFixedHeight(30)
        self.twoway_text_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.twoway_text_btn.clicked.connect(self.on_twoway_text)
        in_row.addWidget(self.twoway_text_btn)
        tw.addLayout(in_row)
        txt_hint = QLabel(
            "Language is detected automatically for typed text.")
        txt_hint.setObjectName("dim")
        tw.addWidget(txt_hint)

        # ---- optionally: into the chatbox ----
        send_row = QHBoxLayout()
        self.twoway_send_toggle = ToggleSwitch()
        self.twoway_send_toggle.toggled.connect(self.on_twoway_send)
        send_row.addWidget(self.twoway_send_toggle)
        send_row.addWidget(ToggleLabel("Send to chatbox",
                                       self.twoway_send_toggle))
        send_row.addStretch()
        tw.addLayout(send_row)
        self.twoway_send_w = QWidget()
        sw = QVBoxLayout(self.twoway_send_w)
        sw.setContentsMargins(0, 0, 0, 0)
        sw.setSpacing(4)
        sm = QHBoxLayout()
        sm.addWidget(QLabel("Send as:"))
        self.twoway_mode_combo = QComboBox()
        for label, val in TWOWAY_SEND_MODES:
            self.twoway_mode_combo.addItem(label, val)
        self.twoway_mode_combo.currentIndexChanged.connect(
            self.on_twoway_send_mode)
        sm.addWidget(self.twoway_mode_combo, 1)
        sw.addLayout(sm)
        self.twoway_mode_hint = QLabel("")
        self.twoway_mode_hint.setObjectName("dim")
        self.twoway_mode_hint.setWordWrap(True)
        sw.addWidget(self.twoway_mode_hint)
        tw.addWidget(self.twoway_send_w)

        self.twoway_box.setVisible(False)
        sc.addWidget(self.twoway_box)

    def _build_twoway_filter(self, tw):
        """Only some programs / all but some - see app_capture.py."""
        f_row = QHBoxLayout()
        f_row.addWidget(QLabel("Apps:"))
        self.twoway_filter_combo = QComboBox()
        for label, val in TWOWAY_FILTER_MODES:
            self.twoway_filter_combo.addItem(label, val)
        self.twoway_filter_combo.currentIndexChanged.connect(
            self.on_twoway_filter_mode)
        f_row.addWidget(self.twoway_filter_combo, 1)
        tw.addLayout(f_row)

        self.twoway_filter_w = QWidget()
        fw = QHBoxLayout(self.twoway_filter_w)
        fw.setContentsMargins(0, 0, 0, 0)
        self.twoway_filter_edit = QLineEdit()
        self.twoway_filter_edit.setPlaceholderText("VRChat, Discord \u2026")
        self.twoway_filter_edit.setToolTip(
            "Program names, separated by commas. Matched case-insensitively "
            "against the name the program reports to the sound server "
            "(\u201cvrchat\u201d also hits VRChat.exe under Proton).")
        self.twoway_filter_edit.textChanged.connect(self.on_twoway_filter_text)
        fw.addWidget(self.twoway_filter_edit, 1)
        self.twoway_filter_add = QPushButton("\u2795  Running app")
        self.twoway_filter_add.setObjectName("linkbtn")
        self.twoway_filter_add.setFixedHeight(28)
        self.twoway_filter_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.twoway_filter_add.setToolTip(
            "Lists the programs playing sound right now - click one to add "
            "it.")
        self.twoway_filter_add.clicked.connect(
            lambda _=False: self.on_twoway_filter_menu())
        fw.addWidget(self.twoway_filter_add)
        tw.addWidget(self.twoway_filter_w)
        self.twoway_filter_hint = QLabel("")
        self.twoway_filter_hint.setObjectName("dim")
        self.twoway_filter_hint.setWordWrap(True)
        tw.addWidget(self.twoway_filter_hint)
        if IS_WINDOWS or not app_capture.available():
            self.twoway_filter_combo.setEnabled(False)

    def _twoway_capture_method(self):
        """PipeWire link mode or PulseAudio move mode - checked once."""
        m = getattr(self, "_tw_capture_method", None)
        if m is None:
            m = self._tw_capture_method = app_capture.method()
        return m

    def _twoway_filter_mode(self):
        if IS_WINDOWS or not app_capture.available():
            return app_capture.MODE_OFF
        return self.cfg.get("stt_twoway_filter_mode", app_capture.MODE_OFF)

    def _twoway_filter_key(self, mode=None):
        mode = mode or self._twoway_filter_mode()
        return ("stt_twoway_filter_only" if mode == app_capture.MODE_ONLY
                else "stt_twoway_filter_except")

    def _twoway_patterns(self):
        return app_capture.parse_patterns(
            self.cfg.get(self._twoway_filter_key(), ""))

    def sync_twoway_filter_ui(self):
        mode = self._twoway_filter_mode()
        self.twoway_filter_combo.blockSignals(True)
        pos = self.twoway_filter_combo.findData(mode)
        self.twoway_filter_combo.setCurrentIndex(pos if pos >= 0 else 0)
        self.twoway_filter_combo.blockSignals(False)
        on = mode != app_capture.MODE_OFF
        self.twoway_filter_w.setVisible(on)
        self.twoway_src_combo.setEnabled(not on)
        self.twoway_filter_edit.blockSignals(True)
        self.twoway_filter_edit.setText(
            self.cfg.get(self._twoway_filter_key(), "") if on else "")
        self.twoway_filter_edit.blockSignals(False)
        if IS_WINDOWS:
            hint = ("Windows cannot record single programs without a "
                    "driver. Instead set VRChat's output to a virtual "
                    "cable (VB-CABLE) in Settings \u203a Sound \u203a "
                    "Volume mixer and pick that cable above.")
        elif not app_capture.available():
            hint = "Needs pactl (PulseAudio or PipeWire)."
        elif on and self._twoway_capture_method() == app_capture.METHOD_LINK:
            hint = ("PipeWire: the chosen programs get an EXTRA link to a "
                    "virtual output \u201c"
                    f"{app_capture.SINK_DESC}\u201d, which is what gets "
                    "recorded. Your headphones keep their direct path "
                    "\u2013 nothing is moved, no added latency. "
                    "\u201cListen to\u201d is not used while this is on.")
        elif on:
            hint = ("PulseAudio (no PipeWire found): the chosen programs "
                    "are MOVED to a virtual output \u201c"
                    f"{app_capture.SINK_DESC}\u201d that is looped back to "
                    "your headphones \u2013 about 30 ms extra delay on "
                    "what you hear. With PipeWire (pw-link) this is "
                    "latency-free. Everything is put back when you stop.")
        else:
            hint = ("Music in the background? Pick \u201cOnly these "
                    "apps\u201d with VRChat, or exclude Spotify / YouTube "
                    "Music.")
        self.twoway_filter_hint.setText(hint)
        self.twoway_router.configure(mode, self._twoway_patterns())

    def on_twoway_filter_mode(self, idx):
        self.cfg["stt_twoway_filter_mode"] = (
            self.twoway_filter_combo.itemData(idx) or app_capture.MODE_OFF)
        self.save_config()
        self.sync_twoway_filter_ui()
        if self.twoway_listening or self.twoway_test.running:
            self.twoway_status_lbl.setText(
                "Filter changed \u2013 stop and start listening to "
                "apply it.")

    def on_twoway_filter_text(self, text):
        self.cfg[self._twoway_filter_key()] = text
        self.save_config_later()
        # a new app list applies live: the router re-checks every 2 s
        self.twoway_router.configure(self._twoway_filter_mode(),
                                     self._twoway_patterns())

    def on_twoway_filter_menu(self):
        def done(apps):
            menu = QMenu(self)
            if not apps:
                act = menu.addAction("(nothing is playing sound right now)")
                act.setEnabled(False)
            for name in apps:
                menu.addAction(name, lambda n=name: self._twoway_add_app(n))
            menu.exec(self.twoway_filter_add.mapToGlobal(
                self.twoway_filter_add.rect().bottomLeft()))
        self.run_async(app_capture.running_apps, done, interval=100,
                       on_error=lambda _e: done([]))

    def _twoway_add_app(self, name):
        cur = [p.strip() for p in self.twoway_filter_edit.text().split(",")
               if p.strip()]
        if name.lower() not in (c.lower() for c in cur):
            cur.append(name)
        self.twoway_filter_edit.setText(", ".join(cur))

    def _twoway_source_work(self, who, eid):
        """Worker-thread half of starting: sets up the app filter when it
        is on. Returns (eid to record from, error or '')."""
        if self._twoway_filter_mode() == app_capture.MODE_OFF:
            return eid, ""
        if not self._twoway_patterns():
            return eid, "App filter is on but the app list is empty."
        err = self.twoway_router.acquire(who)
        if err:
            return eid, f"App filter: {err}"
        return app_capture.SOURCE_ID, ""

    def _twoway_release(self, who):
        import threading
        threading.Thread(target=self.twoway_router.release, args=(who,),
                         daemon=True).start()

    def _build_twoway_tuning(self, tw):
        """Source test & sensitivity - the same controls as the
        microphone block above, with their own values for game audio."""
        self.twoway_test = MicTest()
        self._tw_measure_until = 0.0
        self._tw_measure_peak = 0.0
        self.twoway_meter_timer = QTimer(self)
        self.twoway_meter_timer.timeout.connect(self.poll_twoway_level)

        self.twoway_tune_expander = self.make_settings_expander(
            self.on_twoway_tune_expanded, "Source test & sensitivity")
        tw.addWidget(self.twoway_tune_expander)
        self.twoway_tune_box = QWidget()
        tb = QVBoxLayout(self.twoway_tune_box)
        tb.setContentsMargins(8, 4, 0, 4)
        tb.setSpacing(6)

        meter_row = QHBoxLayout()
        self.twoway_meter = LevelMeter()
        meter_row.addWidget(self.twoway_meter, 1)
        self.twoway_test_btn = QPushButton("\U0001F3A7  Test")
        self.twoway_test_btn.setObjectName("linkbtn")
        self.twoway_test_btn.setCheckable(True)
        self.twoway_test_btn.setFixedHeight(30)
        self.twoway_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.twoway_test_btn.setToolTip(
            "Opens the selected source and shows its level. Play a video "
            "or stand next to someone talking in VRChat: the bar has to "
            "move. If it moves when YOU talk, the microphone is selected, "
            "not the output.")
        self.twoway_test_btn.toggled.connect(self.on_twoway_test)
        meter_row.addWidget(self.twoway_test_btn)
        tb.addLayout(meter_row)
        self.twoway_meter_lbl = QLabel("")
        self.twoway_meter_lbl.setObjectName("dim")
        self.twoway_meter_lbl.setWordWrap(True)
        tb.addWidget(self.twoway_meter_lbl)

        auto_row = QHBoxLayout()
        self.twoway_toggle_auto = ToggleSwitch()
        self.twoway_toggle_auto.toggled.connect(self.on_twoway_energy_auto)
        auto_row.addWidget(self.twoway_toggle_auto)
        auto_row.addWidget(ToggleLabel("Automatic sensitivity",
                                       self.twoway_toggle_auto))
        auto_row.addStretch()
        tb.addLayout(auto_row)

        self.twoway_energy_w = QWidget()
        er = QHBoxLayout(self.twoway_energy_w)
        er.setContentsMargins(0, 0, 0, 0)
        er.addWidget(QLabel("Speech starts above:"))
        self.twoway_energy_slider = QSlider(Qt.Orientation.Horizontal)
        self.twoway_energy_slider.setMinimum(audiolevel.THRESHOLD_MIN)
        self.twoway_energy_slider.setMaximum(audiolevel.THRESHOLD_MAX)
        self.twoway_energy_slider.setSingleStep(10)
        self.twoway_energy_slider.setPageStep(100)
        self.twoway_energy_slider.valueChanged.connect(
            self.on_twoway_energy)
        er.addWidget(self.twoway_energy_slider, 1)
        self.twoway_energy_lbl = QLabel("")
        self.twoway_energy_lbl.setFixedWidth(46)
        er.addWidget(self.twoway_energy_lbl)
        meas = QPushButton("\U0001F4CF  Measure")
        meas.setObjectName("linkbtn")
        meas.setFixedHeight(30)
        meas.setCursor(Qt.CursorShape.PointingHandCursor)
        meas.setToolTip("Listens to the source for 3 seconds while nobody "
                        "talks (world music, ambience) and puts the "
                        "threshold above it.")
        meas.clicked.connect(lambda _=False: self.on_twoway_measure())
        er.addWidget(meas)
        tb.addWidget(self.twoway_energy_w)

        timing = QHBoxLayout()
        timing.addWidget(QLabel("Silence ends a phrase after:"))
        self.twoway_pause_spin = QDoubleSpinBox()
        self.twoway_pause_spin.setRange(0.2, 3.0)
        self.twoway_pause_spin.setSingleStep(0.1)
        self.twoway_pause_spin.setDecimals(1)
        self.twoway_pause_spin.setSuffix(" s")
        self.twoway_pause_spin.setFixedWidth(80)
        self.twoway_pause_spin.valueChanged.connect(
            lambda v: self._twoway_set("stt_twoway_pause_sec",
                                       round(float(v), 2)))
        timing.addWidget(self.twoway_pause_spin)
        timing.addSpacing(12)
        timing.addWidget(QLabel("Ignore shorter than:"))
        self.twoway_min_spin = QDoubleSpinBox()
        self.twoway_min_spin.setRange(0.05, 2.0)
        self.twoway_min_spin.setSingleStep(0.05)
        self.twoway_min_spin.setDecimals(2)
        self.twoway_min_spin.setSuffix(" s")
        self.twoway_min_spin.setFixedWidth(85)
        self.twoway_min_spin.valueChanged.connect(
            lambda v: self._twoway_set("stt_twoway_min_phrase_sec",
                                       round(float(v), 2)))
        timing.addWidget(self.twoway_min_spin)
        timing.addStretch()
        tb.addLayout(timing)

        lim = QHBoxLayout()
        lim.addWidget(QLabel("Longest single phrase:"))
        self.twoway_limit_spin = QSpinBox()
        self.twoway_limit_spin.setRange(3, 60)
        self.twoway_limit_spin.setSuffix(" s")
        self.twoway_limit_spin.setFixedWidth(80)
        self.twoway_limit_spin.setToolTip(
            "An instance is rarely quiet - this cap makes sure something "
            "gets translated even when the audio never stops.")
        self.twoway_limit_spin.valueChanged.connect(
            lambda v: self._twoway_set("stt_twoway_phrase_limit", int(v)))
        lim.addWidget(self.twoway_limit_spin)
        lim.addStretch()
        reset = QPushButton("Reset to defaults")
        reset.setObjectName("linkbtn")
        reset.setFixedHeight(28)
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(lambda _=False: self.on_twoway_tune_reset())
        lim.addWidget(reset)
        tb.addLayout(lim)
        hint = QLabel(
            "Changes apply the next time you press Start listening.")
        hint.setObjectName("dim")
        tb.addWidget(hint)

        self.twoway_tune_box.setVisible(False)
        tw.addWidget(self.twoway_tune_box)

    # --------------------------------------------- sensitivity values
    def _twoway_cfg(self, key):
        return self.cfg.get(key, TWOWAY_DEFAULTS[key])

    def _twoway_set(self, key, value):
        self.cfg[key] = value
        self.save_config_later()

    def _twoway_sensitivity(self):
        return {
            "energy_auto": bool(self._twoway_cfg("stt_twoway_energy_auto")),
            "energy_threshold": audiolevel.clamp_threshold(
                self._twoway_cfg("stt_twoway_energy_threshold")),
            "pause_sec": float(self._twoway_cfg("stt_twoway_pause_sec")),
            "min_phrase_sec": float(
                self._twoway_cfg("stt_twoway_min_phrase_sec")),
            "phrase_limit": int(self._twoway_cfg("stt_twoway_phrase_limit")),
        }

    def _twoway_threshold(self):
        if self._twoway_cfg("stt_twoway_energy_auto"):
            return 0
        return audiolevel.clamp_threshold(
            self._twoway_cfg("stt_twoway_energy_threshold"))

    def sync_twoway_tuning_ui(self):
        sens = self._twoway_sensitivity()
        for w, v in ((self.twoway_toggle_auto, sens["energy_auto"]),
                     (self.twoway_energy_slider, sens["energy_threshold"]),
                     (self.twoway_pause_spin, sens["pause_sec"]),
                     (self.twoway_min_spin, sens["min_phrase_sec"]),
                     (self.twoway_limit_spin, sens["phrase_limit"])):
            w.blockSignals(True)
            if isinstance(v, bool):
                w.setChecked(v)
            else:
                w.setValue(v)
            w.blockSignals(False)
        self.twoway_energy_lbl.setText(str(sens["energy_threshold"]))
        self.twoway_energy_w.setEnabled(not sens["energy_auto"])
        self.twoway_meter.set_threshold(self._twoway_threshold())

    def on_twoway_energy_auto(self, on):
        self._twoway_set("stt_twoway_energy_auto", bool(on))
        self.sync_twoway_tuning_ui()

    def on_twoway_energy(self, value):
        value = audiolevel.clamp_threshold(value)
        self._twoway_set("stt_twoway_energy_threshold", value)
        self.twoway_energy_lbl.setText(str(value))
        self.twoway_meter.set_threshold(value)

    def on_twoway_tune_reset(self):
        self.cfg.update(TWOWAY_DEFAULTS)
        self.save_config()
        self.sync_twoway_tuning_ui()
        self._twoway_note("Sensitivity back to the defaults.")

    def _twoway_note(self, text, warn=False):
        self.twoway_meter_lbl.setText(text or "")
        self.twoway_meter_lbl.setStyleSheet("color: #d9884a;" if warn
                                            else "")

    # --------------------------------------------------- source test
    def on_twoway_tune_expanded(self, on):
        self.set_expanded(self.twoway_tune_expander, self.twoway_tune_box,
                          on, "Source test & sensitivity")
        if not on and self.twoway_test.running:
            self.twoway_test_btn.setChecked(False)

    def on_twoway_test(self, on):
        if not on:
            self.twoway_test.stop()
            self._twoway_release("test")
            self.twoway_test_btn.setText("\U0001F3A7  Test")
            self._tw_measure_until = 0.0
            self.twoway_meter.set_idle()
            self._twoway_note("")
            self._sync_twoway_meter()
            return
        if self.twoway_listening:
            self.twoway_test_btn.blockSignals(True)
            self.twoway_test_btn.setChecked(False)
            self.twoway_test_btn.blockSignals(False)
            self._twoway_note("Listening is running \u2013 the bar already "
                              "shows its input.")
            return
        if not SpeechWorker.available():
            self.twoway_test_btn.blockSignals(True)
            self.twoway_test_btn.setChecked(False)
            self.twoway_test_btn.blockSignals(False)
            self._twoway_note("Speech to Text is not installed.", warn=True)
            return
        eid = self._twoway_selected()
        self.twoway_test_btn.setText("\u23F9  Stop")
        self._twoway_note("Opening the source \u2026")

        def work():
            src, err = self._twoway_source_work("test", eid)
            if err:
                return None, "", err
            return resolve_entry(src, self.log)

        self.run_async(
            work, self._on_twoway_test_resolved,
            interval=120,
            on_error=lambda e: self._on_twoway_test_resolved(
                (None, "", f"The source could not be resolved ({e}).")))

    def _on_twoway_test_resolved(self, result):
        index, node, note = result
        if not self.twoway_test_btn.isChecked():
            return
        if index is None:
            self._twoway_note(note or "The source is not available.",
                              warn=True)
            self.twoway_test_btn.setChecked(False)
            return
        self.twoway_test.start(mic_index=index, node=node,
                               threshold=self._twoway_threshold(),
                               log=self.log)
        self._twoway_note("Play something in VRChat \u2013 the bar should "
                          "pass the dashed line when someone talks.")
        self._sync_twoway_meter()

    def on_twoway_measure(self):
        self._twoway_set("stt_twoway_energy_auto", False)
        self.sync_twoway_tuning_ui()
        self._tw_measure_peak = 0.0
        self._tw_measure_until = time.monotonic() + 3.0
        if not (self.twoway_test.running or self.twoway_listening):
            self.twoway_test_btn.setChecked(True)
        self._twoway_note("\U0001F4CF Measuring the background for three "
                          "seconds \u2026")
        self._sync_twoway_meter()

    def _twoway_finish_measure(self):
        self._tw_measure_until = 0.0
        floor = self._tw_measure_peak
        if floor <= 0:
            self._twoway_note("Nothing was measured \u2013 the source "
                              "delivered no audio. Wrong source?", warn=True)
            return
        value = audiolevel.clamp_threshold(max(floor * 1.8, floor + 120))
        self.cfg["stt_twoway_energy_threshold"] = value
        self.save_config()
        self.sync_twoway_tuning_ui()
        self._twoway_note(f"Threshold set to {value} (background peaked "
                          f"at {floor:.0f}).")

    def _sync_twoway_meter(self):
        want = bool(self.twoway_listening or self.twoway_test.running)
        if want and not self.twoway_meter_timer.isActive():
            self.twoway_meter.apply_tokens(self.current_theme_tokens())
            self.twoway_meter_timer.start(80)
        elif not want and self.twoway_meter_timer.isActive():
            self.twoway_meter_timer.stop()
            self.twoway_meter.set_idle()

    def _twoway_feed(self, rms, peak, threshold):
        if not self._twoway_cfg("stt_twoway_energy_auto"):
            threshold = self._twoway_threshold()
        self.twoway_meter.set_level(rms, peak, threshold)
        if self._tw_measure_until and time.monotonic() < self._tw_measure_until:
            self._tw_measure_peak = max(self._tw_measure_peak, float(rms))
        elif self._tw_measure_until:
            self._twoway_finish_measure()

    def poll_twoway_level(self):
        while not self.twoway_test.messages.empty():
            try:
                kind, payload = self.twoway_test.messages.get_nowait()
            except Exception:      # noqa: BLE001
                break
            if kind == "level":
                self._twoway_feed(*payload)
            elif kind == "ready" and payload:
                self._twoway_source_note(payload)
            elif kind == "error":
                self._twoway_note(payload, warn=True)
                self.twoway_test_btn.setChecked(False)
            elif kind == "stopped" and self.twoway_test_btn.isChecked():
                self.twoway_test_btn.setChecked(False)
        if self.twoway_listening:
            level = self.stt_twoway.latest_level()
            if level is not None:
                self._twoway_feed(*level)
        self._sync_twoway_meter()

    def _twoway_source_note(self, actual):
        """Shows what is REALLY being recorded - and warns when a
        monitor was chosen but a microphone is what got attached."""
        pretty = mic_pactl.describe_source(actual) or actual
        want = micgroups.normalize(
            app_capture.SOURCE_ID
            if self._twoway_filter_mode() != app_capture.MODE_OFF
            else self._twoway_selected())
        if want.endswith(".monitor") and not str(actual).endswith(
                ".monitor"):
            msg = (f"\u26A0 Recording from \u201c{pretty}\u201d \u2013 "
                   f"that is not the selected output monitor. The sound "
                   f"server ignored the choice; try another entry.")
            self._twoway_note(msg, warn=True)
            self.twoway_status_lbl.setText(msg)
            self.log(f"Two-way: {msg}")
        else:
            self._twoway_note(f"\u2705 Recording from: {pretty}")
            self.log(f"Two-way: recording from \u201c{pretty}\u201d")

    def _twoway_selected(self):
        eid = self.twoway_src_combo.currentData()
        if eid is None:
            eid = self.cfg.get("stt_twoway_source", "")
        return eid or ""

    # ----------------------------------------------------------- config
    def load_twoway_config(self):
        """Puts the saved choices into the widgets (after cfg loaded)."""
        for combo, key, default in (
                (self.twoway_lang_combo, "stt_twoway_language", "en-US"),
                (self.twoway_target_combo, "stt_twoway_target",
                 TWOWAY_FOLLOW)):
            combo.blockSignals(True)
            idx = combo.findData(self.cfg.get(key, default))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)
        self.sync_twoway_tuning_ui()
        self._sync_twoway_send_ui()
        self.sync_twoway_filter_ui()

    def _twoway_target(self):
        """Language code the others get translated into."""
        tgt = self.cfg.get("stt_twoway_target", TWOWAY_FOLLOW)
        if tgt:
            return tgt
        # follow the Speech to Text INPUT language: that is the one you
        # speak, so it is the one you read
        return (self.cfg.get("stt_language") or "en-US").split("-")[0]

    def _twoway_sync_translation(self):
        """Service/keys/servers are shared with Speech to Text; copied on
        every poll so a change up there applies without a restart."""
        w = self.stt_twoway
        w.method = self.cfg.get("stt_method") or w.method
        w.deepl_key = self.cfg.get("stt_deepl_key", "")
        w.libre_url = self.cfg.get("stt_libre_url", "")
        w.libre_online_url = self.cfg.get("stt_libre_online_url", "")
        w.libre_online_key = self.cfg.get("stt_libre_online_key", "")
        w.google_key = self.cfg.get("stt_google_key", "")
        w.custom_snippet = self.cfg.get("stt_custom_snippet", "")
        w.custom_file = self.cfg.get("stt_custom_file", "")
        w.translate_to = self._twoway_target()
        w.language = self.cfg.get("stt_twoway_language", "en-US")

    def on_twoway_source(self, idx):
        data = self.twoway_src_combo.itemData(idx)
        if data is None:          # a group header
            return
        self.cfg["stt_twoway_source"] = data
        self.save_config_later()

    def on_twoway_language(self, idx):
        self.cfg["stt_twoway_language"] = self.twoway_lang_combo.itemData(idx)
        self.save_config_later()
        self.stt_twoway.language = self.cfg["stt_twoway_language"]

    def on_twoway_target(self, idx):
        self.cfg["stt_twoway_target"] = \
            self.twoway_target_combo.itemData(idx) or TWOWAY_FOLLOW
        self.save_config_later()
        self.stt_twoway.translate_to = self._twoway_target()

    # ---------------------------------------------------- device list
    def apply_twoway_devices(self, entries):
        """Paints the source dropdown from the same grouped list the
        microphone dropdown uses. Monitors come first here - for this
        feature they are the right answer, not the exotic one."""
        if not hasattr(self, "twoway_src_combo"):
            return
        want = micgroups.normalize(self.cfg.get("stt_twoway_source", "")) \
            if hasattr(self, "cfg") else ""
        combo = self.twoway_src_combo
        combo.blockSignals(True)
        combo.clear()
        model = combo.model()
        by_group = {}
        for item in entries or ():
            by_group.setdefault(item["group"], []).append(item)
        order = [micgroups.G_MONITOR] + [
            g for g in micgroups.GROUP_ORDER if g != micgroups.G_MONITOR]
        first_real = None
        for group in order:
            rows = by_group.get(group)
            if not rows:
                continue
            combo.addItem(
                f"— {micgroups.LABELS.get(group, group)} —", None)
            try:
                model.item(combo.count() - 1).setFlags(
                    Qt.ItemFlag.NoItemFlags)
            except Exception:      # noqa: BLE001
                pass
            for item in rows:
                combo.addItem(item["label"], item["id"])
                if first_real is None:
                    first_real = combo.count() - 1
                tip = item.get("detail") or ""
                if tip:
                    combo.setItemData(combo.count() - 1, tip,
                                      Qt.ItemDataRole.ToolTipRole)
        pos = combo.findData(want) if want else -1
        if pos < 0:
            # nothing saved yet: the first monitor, if there is one
            pos = first_real if first_real is not None else 0
        combo.setCurrentIndex(pos)
        combo.blockSignals(False)

    # ------------------------------------------------------ listening
    def on_twoway_toggled(self, on):
        if not on:
            self._twoway_preflight = 0
            self.stt_twoway.stop()
            self._twoway_release("listen")
            self.twoway_listening = False
            self.twoway_timer.stop()
            self._sync_twoway_meter()
            self.twoway_btn.setText("\U0001F442  Start listening")
            self.twoway_status_lbl.setText("Stopped.")
            self.log("Two-way: listening stopped")
            return
        if not SpeechWorker.available():
            self.twoway_status_lbl.setText(
                "Speech to Text is not installed – see above.")
            self._twoway_abort()
            return
        eid = self._twoway_selected()
        self.cfg["stt_twoway_source"] = eid
        # the test would be a second stream on the same source
        if self.twoway_test.running:
            self.twoway_test_btn.setChecked(False)
        self._twoway_preflight += 1
        token = self._twoway_preflight
        self.twoway_btn.setText("⏳  Checking source …")
        self.twoway_status_lbl.setText("Checking the audio source …")

        def work():
            clear_driver_stuck()
            src, err = self._twoway_source_work("listen", eid)
            if err:
                return None, "", err
            _entries, devices, sources = list_microphone_groups(
                self.log, force=True, selected=src)
            return resolve_entry(src, self.log, devices=devices,
                                 sources=sources)

        self.run_async(
            work, lambda res, t=token: self._on_twoway_preflight(t, res),
            interval=150,
            on_error=lambda e, t=token: self._on_twoway_preflight(
                t, (None, "", f"Source check failed: {e}")))

    def _twoway_abort(self):
        self._twoway_release("listen")
        self._twoway_preflight = 0
        self.twoway_listening = False
        self.twoway_btn.blockSignals(True)
        self.twoway_btn.setChecked(False)
        self.twoway_btn.blockSignals(False)
        self.twoway_btn.setText("\U0001F442  Start listening")

    def _on_twoway_preflight(self, token, result):
        if token != self._twoway_preflight:
            return
        index, node, note = result
        if note or index is None:
            msg = note or "The selected source is not available."
            self.twoway_status_lbl.setText(f"⚠ {msg}")
            self.log(f"Two-way: {msg}")
            self._twoway_abort()
            return
        if not self.twoway_btn.isChecked():
            return
        self.twoway_listening = True
        self.twoway_btn.setText("⏹  Stop listening")
        self.twoway_status_lbl.setText("Starting …")
        self._twoway_sync_translation()
        self.stt_twoway.start(
            self.cfg.get("stt_twoway_language", "en-US"),
            self._twoway_target(),
            self.cfg.get("stt_method"),
            self.cfg.get("stt_deepl_key", ""),
            self.cfg.get("stt_libre_url", ""),
            index,
            google_key=self.cfg.get("stt_google_key", ""),
            libre_online_url=self.cfg.get("stt_libre_online_url", ""),
            libre_online_key=self.cfg.get("stt_libre_online_key", ""),
            mic_node=node or "",
            sensitivity=self._twoway_sensitivity())
        self._sync_twoway_meter()
        self.log(f"Two-way: listening to "
                 f"{micgroups.label_for_id(self.cfg['stt_twoway_source'])}"
                 f" ({self.cfg.get('stt_twoway_language', 'en-US')} → "
                 f"{self._twoway_target()})")
        self.twoway_timer.start(200)

    def poll_twoway(self):
        self._twoway_sync_translation()
        while not self.stt_twoway.messages.empty():
            kind, payload = self.stt_twoway.messages.get_nowait()
            if kind == "text":
                src, out = payload if isinstance(payload, (tuple, list)) \
                    else (payload, payload)
                self._twoway_append(src, out)
            elif kind == "status":
                self.twoway_status_lbl.setText(payload)
            elif kind == "source":
                self._twoway_source_note(payload)
            elif kind == "error":
                self.twoway_status_lbl.setText(f"⚠ {payload}")
                self.log(f"Two-way ERROR: {payload}")
                self.twoway_btn.setChecked(False)
            elif kind == "stopped":
                if self.twoway_btn.isChecked():
                    self.twoway_btn.setChecked(False)

    # ------------------------------------------------ send to chatbox
    def on_twoway_send(self, on):
        self.cfg["stt_twoway_send"] = bool(on)
        self.save_config()
        if not on:
            self.clear_twoway_text()
        self._sync_twoway_send_ui()

    def on_twoway_send_mode(self, idx):
        mode = self.twoway_mode_combo.itemData(idx) or CHAT_MODE_VARS
        self.cfg["stt_twoway_send_mode"] = mode
        self.save_config()
        if mode == CHAT_MODE_DIRECT:
            self.clear_twoway_text()
        self._sync_twoway_send_ui()
        self.update_preview()

    def _sync_twoway_send_ui(self):
        on = bool(self.cfg.get("stt_twoway_send", False))
        mode = self.cfg.get("stt_twoway_send_mode", CHAT_MODE_VARS)
        self.twoway_send_toggle.blockSignals(True)
        self.twoway_send_toggle.setChecked(on)
        self.twoway_send_toggle.blockSignals(False)
        self.twoway_mode_combo.blockSignals(True)
        pos = self.twoway_mode_combo.findData(mode)
        self.twoway_mode_combo.setCurrentIndex(pos if pos >= 0 else 0)
        self.twoway_mode_combo.blockSignals(False)
        self.twoway_send_w.setVisible(on)
        self.twoway_mode_hint.setText(TWOWAY_MODE_HINTS.get(mode, ""))

    def park_twoway_text(self, source_text, final_text):
        """The Line / Variables slot of Two-way. Same hold time as the
        To Text card (chat_hold_sec); 0 = until the next one."""
        hold = int(self.cfg.get("chat_hold_sec", 0) or 0)
        self.twoway_msg_input = source_text or ""
        self.twoway_msg_output = final_text or ""
        self.twoway_msg_until = (time.time() + hold) if hold else 0.0
        self.update_preview()

    def clear_twoway_text(self):
        had = bool(self.twoway_msg_output)
        self.twoway_msg_input = ""
        self.twoway_msg_output = ""
        self.twoway_msg_until = 0.0
        if had:
            self.update_preview()

    def twoway_text_expired(self):
        return bool(self.twoway_msg_until
                    and time.time() >= self.twoway_msg_until)

    def twoway_payload_lines(self):
        """(anchor, lines) for Two-way in Line mode, like the To Text one.
        Position is shared with To Text (chat_anchor)."""
        anchor = self.cfg.get("chat_anchor", DEFAULT_ANCHOR)
        if anchor not in ANCHORS:
            anchor = DEFAULT_ANCHOR
        if not (self.cfg.get("stt_twoway_send")
                and self.cfg.get("stt_twoway_send_mode") == CHAT_MODE_LINE):
            return anchor, []
        text = (self.twoway_msg_output or "").strip()
        return anchor, (text.split("\n") if text else [])

    def _twoway_to_chatbox(self, source, translated):
        if not self.cfg.get("stt_twoway_send", False):
            return
        out = translated or source
        if not out:
            return
        self.send_manual_text(out, source_text=source, origin=ORIGIN_TWOWAY)

    def _twoway_append(self, source, translated):
        self._twoway_to_chatbox(source, translated)
        stamp = time.strftime("%H:%M")
        if translated and translated != source:
            line = f"[{stamp}]  {translated}\n          ↳ {source}"
        else:
            line = f"[{stamp}]  {source}"
        self.twoway_log.appendPlainText(line)
        sb = self.twoway_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    # --------------------------------------------------- typed text
    def on_twoway_text(self):
        text = self.twoway_text_input.text().strip()
        if not text:
            return
        self.twoway_text_input.clear()
        self.twoway_text_btn.setEnabled(False)
        tgt = self._twoway_target()
        cfg = dict(self.cfg)

        def work():
            logs = []
            out = translate_with_fallback(
                # "" = auto-detect in every backend (DeepL included,
                # which rejects the literal "auto")
                cfg.get("stt_method"), text, "", tgt,
                deepl_key=cfg.get("stt_deepl_key", ""),
                libre_url=cfg.get("stt_libre_url", ""),
                google_key=cfg.get("stt_google_key", ""),
                libre_online_url=cfg.get("stt_libre_online_url", ""),
                libre_online_key=cfg.get("stt_libre_online_key", ""),
                custom_snippet=cfg.get("stt_custom_snippet", ""),
                custom_file=cfg.get("stt_custom_file", ""),
                log=logs.append)
            return out, logs

        def done(res):
            self.twoway_text_btn.setEnabled(True)
            out, logs = res
            for m in logs:
                self.log(f"Two-way: {m}")
            if out:
                self._twoway_append(text, out)
            else:
                self.twoway_status_lbl.setText(
                    "⚠ Translation failed – see the log.")

        self.run_async(work, done, interval=150,
                       on_error=lambda e: done((None, [str(e)])))
