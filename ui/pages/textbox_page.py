"""
ui/pages/textbox_page.py – Textbox page: STT, translation, LibreTranslate, presets, manual send.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.
"""

import os
import time
from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFileDialog, QPlainTextEdit, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)
from core.constants import (
    CHATBOX_INPUT, CHATBOX_LIMIT, CHAT_MODE_DIRECT, CHAT_MODE_LINE,
    CHAT_MODE_VARS, DEFAULT_TRANSLATE_NOTICE, ORIGIN_CHAT, ORIGIN_LABELS, ORIGIN_STT, ORIGIN_TTT, ORIGIN_TWOWAY,
    SLIM_SUFFIX)
from core import audiolevel, micgroups
from core.osinfo import IS_WINDOWS
from core.backends import mic_pactl
from core.speechtotext import (
    LANGUAGES, OUTPUT_LANGUAGES, SpeechWorker, cached_microphones,
    clear_driver_stuck, default_device_note, describe_entry, driver_stuck,
    has_sr, list_microphone_groups, list_microphones, microphone_mode,
    missing_dependency, reload_sr, resolve_entry, has_microphone_driver,
    reload_mic_driver)
from ui.miclevel import LevelMeter
from ui.history_edit import attach_history
from core.plugins import ANCHOR_LABELS
from core import pyextras
from core.constants import EXTRAS_DIR
from core.translators import (
    DEFAULT_LIBRE_ONLINE_URL, DEFAULT_LIBRE_URL, LIBRE_ONLINE_CUSTOM, LIBRE_ONLINE_SERVERS, METHODS as TR_METHODS, METHOD_DEEPL, METHOD_GOOGLE, METHOD_LIBRE, METHOD_LIBRE_ONLINE, METHOD_LINGVA, METHOD_CUSTOM, get_translator, libretranslate_installed, translate_with_fallback)
from ui.ui_main import DragHandle, ToggleLabel, ToggleSwitch
from core import ai_translator as ai


#: where the two paid/keyed backends hand out their API keys. Kept next
#: to the UI that links them rather than in constants.py, because they are
#: third-party account pages, not app identity.
GOOGLE_KEYS_URL = "https://console.cloud.google.com/apis/credentials"
DEEPL_KEYS_URL = "https://www.deepl.com/your-account/keys"
LIBRE_INSTALL_URL = "https://docs.libretranslate.com/guides/installation/"

#: The three ways a message can reach the chatbox. Applies to everything
#: that produces text here - the Chat field, the Presets, Speech to Text
#: and Text to Text - so the route is one decision instead of four.
CHAT_SEND_MODES = (
    ("Standard", CHAT_MODE_DIRECT),
    ("Line", CHAT_MODE_LINE),
    ("Variables", CHAT_MODE_VARS),
)

#: The same three, phrased for the To Text card - "the message" there is
#: what you spoke or typed, and the pause/anchor controls live in the
#: Chat card, so the wording points at them instead of repeating them.
STT_MODE_HINTS = {
    CHAT_MODE_DIRECT: (
        "Takes over the chatbox; the apps pause meanwhile."),
    CHAT_MODE_LINE: (
        "One line inside the normal output; the apps keep running."),
    CHAT_MODE_VARS: (
        "No line of its own \u2013 only fills the variables below, an "
        "All-in-one string places it."),
}

#: What each mode does, spelled out under the dropdown.
CHAT_MODE_HINTS = {
    CHAT_MODE_DIRECT: (
        "The message takes over the chatbox: it is sent immediately and "
        "every app (Personal Status, MediaPlay, Hardware, All in one) "
        "stays quiet for the pause below, so nothing overwrites it. When "
        "the pause is over, the apps come back on their own."),
    CHAT_MODE_LINE: (
        "The message becomes one more line of the normal output, at the "
        "position you pick above \u2013 exactly the way a plugin is "
        "placed. The apps keep running around it, so you get your status "
        "AND what you just said, together in one chatbox."),
    CHAT_MODE_VARS: (
        "The message gets no line of its own. It only fills "
        "{text_input} (what you typed or said) and {text_output} (what "
        "is actually sent, i.e. the translation when there is one), so "
        "an All-in-one string decides where it goes and what it looks "
        "like. Nothing shows up until a template asks for it."),
}


#: v1.6.5: group headers in the service dropdowns
TR_HEADERS = ("\u2500\u2500\u2500\u2500  Translator  \u2500\u2500\u2500\u2500",
              "\u2500\u2500\u2500\u2500  AI Translation  \u2500\u2500\u2500\u2500")


#: v1.6.6: status marks behind the AI entries of the "Settings for"
#: dropdown - set up / still to install
AI_MARK_OK = "  \u2714"
AI_MARK_MISSING = "  \U0001F4E6 install"
AI_MARK_SETUP = "  \u2699 set up"      # Custom AI: no program to install


def fill_service_combo(combo, items, mark=False):
    """Services grouped under a "Translator" and an "AI Translation"
    header. Headers carry no data and cannot be picked; a group
    without entries (only AI favorites, say) gets no header.
    mark=True (v1.6.6): AI entries show whether they are set up."""
    groups = ([i for i in items if not ai.is_ai(i[1])],
              [i for i in items if ai.is_ai(i[1])])
    for head, group in zip(TR_HEADERS, groups):
        if not group:
            continue
        combo.addItem(head)
        item = combo.model().item(combo.count() - 1)
        if item is not None:
            item.setEnabled(False)
            item.setSelectable(False)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        for label, mid in group:
            if mark and ai.is_ai(mid):
                label += AI_MARK_OK if ai.configured(mid) else (
                    AI_MARK_SETUP if mid == ai.METHOD_AI_CUSTOM
                    else AI_MARK_MISSING)
            combo.addItem(label, mid)


def first_service_index(combo):
    return next((i for i in range(combo.count()) if combo.itemData(i)), -1)


class TextboxPageMixin:
    @staticmethod
    def _key_link(text, url, tooltip=""):
        """Small clickable line under an API key field.

        A rich-text QLabel with setOpenExternalLinks() hands the URL to
        the desktop's default browser through Qt, which is the same route
        QDesktopServices takes - so it works on Windows and Linux without
        a platform branch here.
        """
        lbl = QLabel(f'\U0001F517 <a href="{url}" '
                     f'style="color:#5b8dc9; text-decoration:none;">'
                     f'{text}</a>')
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setOpenExternalLinks(True)
        lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        lbl.setStyleSheet("font-size: 11px;")
        lbl.setWordWrap(True)
        if tooltip:
            lbl.setToolTip(f"{tooltip}\n\n{url}")
        else:
            lbl.setToolTip(url)
        return lbl

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
        # v1.6.6: Arrow Up = last sent message
        self.textbox_history = attach_history(self.textbox_input)
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

        # No "Send as" here on purpose. The Chat card is the "take over
        # the chatbox right now" control - that is what typing a message
        # and pressing Send means - and the other two routes only ever
        # made sense for the To Text card, where a spoken line wants to
        # live alongside the apps instead of replacing them.

        # anchor picker – same vocabulary as the Plugins page, so "where
        # does this line sit" means the same thing everywhere
        self.chat_anchor_w = QWidget()
        anchor_row = QHBoxLayout(self.chat_anchor_w)
        anchor_row.setContentsMargins(0, 0, 0, 0)
        anchor_row.addWidget(QLabel("Position:"))
        self.chat_anchor_combo = QComboBox()
        for key, label in ANCHOR_LABELS:
            self.chat_anchor_combo.addItem(label, key)
        self.chat_anchor_combo.currentIndexChanged.connect(
            self.on_chat_anchor)
        anchor_row.addWidget(self.chat_anchor_combo, 1)
        # added to the To Text card further down, not here: Position,
        # Keep for and the mode hint all describe what Line / Variables
        # do, and those are now only reachable from there

        self.chat_mode_hint = QLabel("")
        self.chat_mode_hint.setObjectName("dim")
        self.chat_mode_hint.setWordWrap(True)

        # how long the apps stay quiet after a send
        self.chat_pause_w = QWidget()
        pause_row = QHBoxLayout(self.chat_pause_w)
        pause_row.setContentsMargins(0, 0, 0, 0)
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
        c.addWidget(self.chat_pause_w)

        # Line / Variables: the text STAYS, so it needs a way out
        self.chat_hold_w = QWidget()
        hold_row = QHBoxLayout(self.chat_hold_w)
        hold_row.setContentsMargins(0, 0, 0, 0)
        hold_row.addWidget(QLabel("Keep for"))
        self.chat_hold_spin = QSpinBox()
        self.chat_hold_spin.setObjectName("smallspin")
        self.chat_hold_spin.setRange(0, 3600)
        self.chat_hold_spin.setFixedSize(70, 28)
        self.chat_hold_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chat_hold_spin.setSpecialValueText("\u221E")
        self.chat_hold_spin.setToolTip(
            "Seconds the text stays in the chatbox. 0 (\u221E) keeps it "
            "until you clear it or send something new.")
        self.chat_hold_spin.valueChanged.connect(self.on_chat_hold)
        hold_row.addWidget(self.chat_hold_spin)
        hold_row.addWidget(QLabel("sec"))
        self.chat_clear_btn = QPushButton("\u2715  Clear now")
        self.chat_clear_btn.setObjectName("linkbtn")
        self.chat_clear_btn.setFixedHeight(28)
        self.chat_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chat_clear_btn.clicked.connect(lambda _=False: self.clear_chat_text())
        hold_row.addWidget(self.chat_clear_btn)
        hold_row.addStretch()
        # ----- speech to text -----
        scard = QFrame()
        scard.setObjectName("card")
        sc = QVBoxLayout(scard)
        sc.setContentsMargins(16, 14, 16, 16)
        sc.setSpacing(10)
        st_head = QHBoxLayout()
        st_head.addWidget(DragHandle(lambda pos: self.tb_card_drag("stt", pos),
                                     lambda: self.tb_card_drag_end("stt")))
        st = QLabel("To Text")
        st.setObjectName("cardtitle")
        st_head.addWidget(st)
        st_head.addStretch()
        self.toggle_stt_block = ToggleSwitch()
        self.toggle_stt_block.toggled.connect(self.on_stt_block)
        self.toggle_stt_block.setToolTip(
            "While ON, no app sends anything via OSC until you switch "
            "it OFF again. Details: \u201cBlock exceptions\u201d below.")
        st_head.addWidget(self.toggle_stt_block)
        st_head.addWidget(ToggleLabel("Block apps", self.toggle_stt_block))
        sc.addLayout(st_head)

        # ---- main mode switch: Speech to Text vs Text to Text ----
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Speech or Text:"))
        self.toggle_stt_mode = ToggleSwitch()
        self.toggle_stt_mode.toggled.connect(self.on_stt_mode)
        mode_row.addWidget(self.toggle_stt_mode)
        self.stt_mode_lbl = QLabel("")
        self.stt_mode_lbl.setStyleSheet("font-weight: 600;")
        mode_row.addWidget(self.stt_mode_lbl)
        mode_row.addStretch()
        sc.addLayout(mode_row)
        mode_hint = QLabel("OFF = Speech to Text (microphone) \u00b7 "
                           "ON = Text to Text (type & translate).")
        mode_hint.setObjectName("dim")
        mode_hint.setWordWrap(True)
        sc.addWidget(mode_hint)

        self.stt_speech_desc = QLabel(
            "Speak into your microphone \u2013 it is transcribed live "
            "and sent to the chatbox.")
        self.stt_speech_desc.setObjectName("dim")
        self.stt_speech_desc.setWordWrap(True)
        sc.addWidget(self.stt_speech_desc)

        # the service actually used - only the favorites when some are
        # set in the Translation card, otherwise all of them
        svc_row = QHBoxLayout()
        svc_row.addWidget(QLabel("Translation service:"))
        self.tr_active_combo = QComboBox()
        self.tr_active_combo.setToolTip(
            "Favorites only, once you have marked some in the "
            "Translation card \u2013 otherwise every service.")
        self.tr_active_combo.currentIndexChanged.connect(self.on_tr_active)
        svc_row.addWidget(self.tr_active_combo, 1)
        sc.addLayout(svc_row)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Input language:"))
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
        tr_hint = QLabel("Output \u2260 input \u2192 the message is "
                         "translated first (settings: Translation card).")
        tr_hint.setObjectName("dim")
        tr_hint.setWordWrap(True)
        sc.addWidget(tr_hint)

        # ---- microphone selection (speech mode only) ----
        self.mic_row_w = QWidget()
        mic_row = QHBoxLayout(self.mic_row_w)
        mic_row.setContentsMargins(0, 0, 0, 0)
        mic_row.addWidget(QLabel("Microphone:"))
        self.mic_combo = QComboBox()
        self._fill_mic_combo()
        self.mic_combo.currentIndexChanged.connect(self.on_mic_changed)
        mic_row.addWidget(self.mic_combo, 1)
        mic_refresh = QPushButton("\u27F3")
        mic_refresh.setObjectName("iconbtn")
        mic_refresh.setFixedSize(30, 30)
        mic_refresh.setToolTip(
            "Refresh microphone list.\n\nAlso the way back after the audio "
            "driver stopped responding \u2013 plug the device back in (or "
            "start VR again), then press this.")
        mic_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        mic_refresh.clicked.connect(lambda _=False: self.on_mic_refresh())
        mic_row.addWidget(mic_refresh)
        sc.addWidget(self.mic_row_w)

        # ---- what the dropdown is allowed to show ----
        self.mic_raw_w = QWidget()
        raw_row = QVBoxLayout(self.mic_raw_w)
        raw_row.setContentsMargins(0, 0, 0, 0)
        raw_row.setSpacing(4)
        rr = QHBoxLayout()
        rr.setContentsMargins(0, 0, 0, 0)
        self.toggle_mic_raw = ToggleSwitch()
        self.toggle_mic_raw.toggled.connect(self.on_mic_show_raw)
        rr.addWidget(self.toggle_mic_raw)
        rr.addWidget(ToggleLabel(
            "Also show duplicate host-API entries" if IS_WINDOWS
            else "Also show direct hardware devices",
            self.toggle_mic_raw))
        rr.addStretch()
        raw_row.addLayout(rr)
        self.mic_raw_hint = QLabel("")
        self.mic_raw_hint.setObjectName("dim")
        self.mic_raw_hint.setWordWrap(True)
        raw_row.addWidget(self.mic_raw_hint)
        sc.addWidget(self.mic_raw_w)

        # ---- what to do when the chosen device is gone ----
        self.mic_strict_w = QWidget()
        strict_row = QVBoxLayout(self.mic_strict_w)
        strict_row.setContentsMargins(0, 0, 0, 0)
        strict_row.setSpacing(4)
        sr_row = QHBoxLayout()
        sr_row.setContentsMargins(0, 0, 0, 0)
        self.toggle_mic_strict = ToggleSwitch()
        self.toggle_mic_strict.toggled.connect(self.on_mic_strict)
        sr_row.addWidget(self.toggle_mic_strict)
        sr_row.addWidget(ToggleLabel("Stop if the microphone is missing",
                                     self.toggle_mic_strict))
        sr_row.addStretch()
        strict_row.addLayout(sr_row)
        strict_hint = QLabel(
            "ON (recommended): a missing device stops recording instead "
            "of falling back to the system default.")
        strict_hint.setObjectName("dim")
        strict_hint.setWordWrap(True)
        strict_row.addWidget(strict_hint)
        sc.addWidget(self.mic_strict_w)

        # ---- record button (speech mode only) ----
        self.rec_row_w = QWidget()
        rec_row = QHBoxLayout(self.rec_row_w)
        rec_row.setContentsMargins(0, 0, 0, 0)
        self.stt_button = QPushButton("\U0001F3A4  Start recording")
        self.stt_button.setObjectName("recbtn")
        self.stt_button.setCheckable(True)
        self.stt_button.setFixedHeight(38)
        self.stt_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stt_button.toggled.connect(self.on_stt_toggled)
        rec_row.addWidget(self.stt_button)
        rec_row.addStretch()
        sc.addWidget(self.rec_row_w)

        # ---- text input (text mode only) ----
        self.stt_text_box = QWidget()
        tb = QVBoxLayout(self.stt_text_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(6)
        ttt_desc = QLabel("Type and hit Enter \u2013 same translation "
                          "and output as speech.")
        ttt_desc.setObjectName("dim")
        ttt_desc.setWordWrap(True)
        tb.addWidget(ttt_desc)
        ttt_row = QHBoxLayout()
        self.ttt_input = QLineEdit()
        self.ttt_input.setPlaceholderText("Type your message \u2026")
        self.ttt_input.setMaxLength(CHATBOX_LIMIT - len(SLIM_SUFFIX))
        self.ttt_input.returnPressed.connect(self.send_ttt)
        self.ttt_history = attach_history(self.ttt_input)
        ttt_row.addWidget(self.ttt_input, 1)
        ttt_emoji = QPushButton("\U0001F600")
        ttt_emoji.setObjectName("iconbtn")
        ttt_emoji.setFixedSize(30, 30)
        ttt_emoji.setCursor(Qt.CursorShape.PointingHandCursor)
        ttt_emoji.clicked.connect(
            lambda _, b=ttt_emoji: self.emoji_popup.open_for(self.ttt_input, b))
        ttt_row.addWidget(ttt_emoji)
        self.ttt_send_btn = QPushButton("Send")
        self.ttt_send_btn.setObjectName("sendbtn")
        self.ttt_send_btn.setFixedSize(64, 30)
        self.ttt_send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ttt_send_btn.clicked.connect(self.send_ttt)
        ttt_row.addWidget(self.ttt_send_btn)
        tb.addLayout(ttt_row)
        sc.addWidget(self.stt_text_box)

        self.stt_status_lbl = QLabel("")
        self.stt_status_lbl.setObjectName("dim")
        self.stt_status_lbl.setWordWrap(True)
        sc.addWidget(self.stt_status_lbl)
        # one-click installer for the pure-python half of Speech to Text.
        # Arch has no working package for it (the AUR one drags in
        # backends we do not use and currently fails to build), so the app
        # can put it into its own folder instead - see core/pyextras.py.
        self.stt_install_btn = QPushButton(
            "\u2B07  Install SpeechRecognition")
        self.stt_install_btn.setObjectName("linkbtn")
        self.stt_install_btn.setFixedHeight(30)
        self.stt_install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stt_install_btn.setToolTip(
            f"Installs it with pip into {EXTRAS_DIR} - your system packages "
            f"are not touched")
        self._stt_install_target = "speech_recognition"
        self.stt_install_btn.clicked.connect(self.on_install_speech)
        self.stt_install_btn.setVisible(False)
        sc.addWidget(self.stt_install_btn)

        # ---- Send as: collapsed, the summary sits in the arrow ----
        self.send_opts_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.send_opts_expander,
                                         self.send_opts_box, on,
                                         self._send_opts_label()),
            "Send as")
        sc.addWidget(self.send_opts_expander)
        self.send_opts_box = QWidget()
        so = QVBoxLayout(self.send_opts_box)
        so.setContentsMargins(8, 4, 0, 4)
        so.setSpacing(6)
        # ---- the send route, mirrored from the Chat card ----
        # The only "Send as" left. It used to be mirrored from the Chat
        # card, which shared the setting - but a typed chat message is
        # the one case where "take over the chatbox now" is always what
        # was meant, so Chat is fixed to Standard and this dropdown
        # belongs to speech and typed-to-text alone.
        sm_row = QHBoxLayout()
        sm_row.addWidget(QLabel("Send as:"))
        self.stt_mode_combo = QComboBox()
        for label, val in CHAT_SEND_MODES:
            self.stt_mode_combo.addItem(label, val)
        self.stt_mode_combo.currentIndexChanged.connect(self.on_stt_send_mode)
        sm_row.addWidget(self.stt_mode_combo)
        sm_row.addStretch()
        so.addLayout(sm_row)
        so.addWidget(self.chat_anchor_w)
        so.addWidget(self.chat_hold_w)
        self.stt_mode_hint = QLabel("")
        self.stt_mode_hint.setObjectName("dim")
        self.stt_mode_hint.setWordWrap(True)
        so.addWidget(self.stt_mode_hint)
        var_hint = QLabel(
            "{stt_\u2026} spoken \u00b7 {ttt_\u2026} typed \u00b7 "
            "{chat_\u2026} Chat card \u00b7 {text_\u2026} whichever "
            "sent last \u2013 each as _input / _output.")
        var_hint.setObjectName("dim")
        var_hint.setWordWrap(True)
        so.addWidget(var_hint)
        self.send_opts_box.setVisible(False)
        sc.addWidget(self.send_opts_box)

        # ---- microphone test + sensitivity ----
        # Collapsed by default: two thirds of the people using Speech to
        # Text never need to touch a threshold, and the ones who DO need
        # it are the ones for whom nothing gets transcribed - who go
        # looking. What they find is a bar that answers the actual
        # question ("is this device hearing me at all") before any
        # setting has to be understood.
        self.mic_tune_w = QWidget()
        tune_outer = QVBoxLayout(self.mic_tune_w)
        tune_outer.setContentsMargins(0, 0, 0, 0)
        tune_outer.setSpacing(4)
        self.mic_tune_expander = self.make_settings_expander(
            lambda on: self.on_mic_tune_expanded(on),
            "Microphone test & sensitivity")
        tune_outer.addWidget(self.mic_tune_expander)

        self.mic_tune_box = QWidget()
        tb = QVBoxLayout(self.mic_tune_box)
        tb.setContentsMargins(8, 4, 0, 4)
        tb.setSpacing(6)

        meter_row = QHBoxLayout()
        meter_row.setContentsMargins(0, 0, 0, 0)
        self.mic_meter = LevelMeter()
        meter_row.addWidget(self.mic_meter, 1)
        self.mic_test_btn = QPushButton("\U0001F3A7  Test")
        self.mic_test_btn.setObjectName("linkbtn")
        self.mic_test_btn.setCheckable(True)
        self.mic_test_btn.setFixedHeight(30)
        self.mic_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic_test_btn.setToolTip(
            "Opens the selected device and shows its level, without "
            "recording or transcribing anything.\n\nThis is the check "
            "worth doing before you rely on a device in an instance: if "
            "the bar does not move when you speak, the wrong source is "
            "selected \u2013 and that is a lot easier to notice here "
            "than from the reactions of the people around you.")
        self.mic_test_btn.toggled.connect(self.on_mic_test)
        meter_row.addWidget(self.mic_test_btn)
        tb.addLayout(meter_row)

        self.mic_meter_lbl = QLabel("")
        self.mic_meter_lbl.setObjectName("dim")
        self.mic_meter_lbl.setWordWrap(True)
        tb.addWidget(self.mic_meter_lbl)

        # ---- automatic vs manual sensitivity ----
        auto_row = QHBoxLayout()
        auto_row.setContentsMargins(0, 0, 0, 0)
        self.toggle_energy_auto = ToggleSwitch()
        self.toggle_energy_auto.toggled.connect(self.on_energy_auto)
        auto_row.addWidget(self.toggle_energy_auto)
        auto_row.addWidget(ToggleLabel("Automatic sensitivity",
                                       self.toggle_energy_auto))
        auto_row.addStretch()
        tb.addLayout(auto_row)
        auto_hint = QLabel(
            "ON: the app keeps re-learning how loud your room is. Right "
            "for a quiet one. OFF: the threshold below is used as-is \u2013 "
            "which is what you want next to a fan, in a game with sound, "
            "or with a VR headset whose own audio bleeds into the "
            "microphone, because in those the automatic value drifts "
            "upwards until nothing counts as speech any more.")
        auto_hint.setObjectName("dim")
        auto_hint.setWordWrap(True)
        tb.addWidget(auto_hint)

        self.energy_row_w = QWidget()
        er = QVBoxLayout(self.energy_row_w)
        er.setContentsMargins(0, 0, 0, 0)
        er.setSpacing(4)
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.addWidget(QLabel("Speech starts above:"))
        self.energy_slider = QSlider(Qt.Orientation.Horizontal)
        self.energy_slider.setMinimum(audiolevel.THRESHOLD_MIN)
        self.energy_slider.setMaximum(audiolevel.THRESHOLD_MAX)
        self.energy_slider.setSingleStep(10)
        self.energy_slider.setPageStep(100)
        self.energy_slider.valueChanged.connect(self.on_energy_threshold)
        slider_row.addWidget(self.energy_slider, 1)
        self.energy_value_lbl = QLabel("")
        self.energy_value_lbl.setFixedWidth(46)
        slider_row.addWidget(self.energy_value_lbl)
        self.energy_measure_btn = QPushButton("\U0001F4CF  Measure")
        self.energy_measure_btn.setObjectName("linkbtn")
        self.energy_measure_btn.setFixedHeight(30)
        self.energy_measure_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.energy_measure_btn.setToolTip(
            "Listens to your room for a moment WITHOUT you talking and "
            "puts the threshold just above what it heard.\n\nStay quiet "
            "while it runs \u2013 it is measuring the noise you want "
            "ignored, so anything you say during it raises the bar "
            "against you.")
        self.energy_measure_btn.clicked.connect(self.on_energy_measure)
        slider_row.addWidget(self.energy_measure_btn)
        er.addLayout(slider_row)
        energy_hint = QLabel(
            "The dashed line in the bar. Everything below it is treated "
            "as background noise; the first chunk above it starts a "
            "phrase. Too low and every keystroke gets transcribed, too "
            "high and quiet speech is dropped without a trace.")
        energy_hint.setObjectName("dim")
        energy_hint.setWordWrap(True)
        er.addWidget(energy_hint)
        tb.addWidget(self.energy_row_w)

        # ---- timing ----
        timing_row = QHBoxLayout()
        timing_row.setContentsMargins(0, 0, 0, 0)
        timing_row.addWidget(QLabel("Silence ends a phrase after:"))
        # stt_pause_spin, NOT pause_spin: the Presets card above already
        # owns self.pause_spin (the chatbox pause, textbox_pause_sec).
        # Reusing the name silently replaced it - so apply_config_to_ui()
        # pushed a 10-second chatbox pause into a 0.2-3.0 s speech
        # setting, which clamped to 3.0 and wrote THAT back to the
        # config on every single start. Two settings, both broken, no
        # error message anywhere.
        self.stt_pause_spin = QDoubleSpinBox()
        self.stt_pause_spin.setRange(0.2, 3.0)
        self.stt_pause_spin.setSingleStep(0.1)
        self.stt_pause_spin.setDecimals(1)
        self.stt_pause_spin.setSuffix(" s")
        self.stt_pause_spin.setFixedWidth(80)
        self.stt_pause_spin.setToolTip(
            "How long you have to stop talking before the phrase is sent "
            "off to be transcribed.\n\nShort = the chatbox keeps up with "
            "you but sentences get cut at every breath. Long = whole "
            "sentences, arriving later.")
        self.stt_pause_spin.valueChanged.connect(self.on_pause_sec)
        timing_row.addWidget(self.stt_pause_spin)
        timing_row.addSpacing(12)
        timing_row.addWidget(QLabel("Ignore sounds shorter than:"))
        self.stt_min_phrase_spin = QDoubleSpinBox()
        self.stt_min_phrase_spin.setRange(0.05, 2.0)
        self.stt_min_phrase_spin.setSingleStep(0.05)
        self.stt_min_phrase_spin.setDecimals(2)
        self.stt_min_phrase_spin.setSuffix(" s")
        self.stt_min_phrase_spin.setFixedWidth(85)
        self.stt_min_phrase_spin.setToolTip(
            "A sound has to last at least this long before it counts as "
            "speech at all.\n\nThis is the setting that keeps a "
            "keyboard, a mouse click or a door from turning into a "
            "transcription request.")
        self.stt_min_phrase_spin.valueChanged.connect(self.on_min_phrase_sec)
        timing_row.addWidget(self.stt_min_phrase_spin)
        timing_row.addStretch()
        tb.addLayout(timing_row)

        limit_row = QHBoxLayout()
        limit_row.setContentsMargins(0, 0, 0, 0)
        limit_row.addWidget(QLabel("Longest single phrase:"))
        self.stt_phrase_limit_spin = QSpinBox()
        self.stt_phrase_limit_spin.setRange(3, 60)
        self.stt_phrase_limit_spin.setSuffix(" s")
        self.stt_phrase_limit_spin.setFixedWidth(80)
        self.stt_phrase_limit_spin.setToolTip(
            "A hard cap, so a microphone that never goes quiet (an open "
            "mic in a loud instance) still sends something instead of "
            "recording forever.")
        self.stt_phrase_limit_spin.valueChanged.connect(self.on_phrase_limit)
        limit_row.addWidget(self.stt_phrase_limit_spin)
        limit_row.addStretch()
        tb.addLayout(limit_row)

        reset_row = QHBoxLayout()
        reset_row.setContentsMargins(0, 0, 0, 0)
        reset_row.addStretch()
        self.mic_tune_reset_btn = QPushButton("Reset to defaults")
        self.mic_tune_reset_btn.setObjectName("linkbtn")
        self.mic_tune_reset_btn.setFixedHeight(28)
        self.mic_tune_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic_tune_reset_btn.clicked.connect(self.on_mic_tune_reset)
        reset_row.addWidget(self.mic_tune_reset_btn)
        tb.addLayout(reset_row)

        self.mic_tune_box.setVisible(False)
        tune_outer.addWidget(self.mic_tune_box)
        sc.addWidget(self.mic_tune_w)
        # "Measure" state: the deadline it runs until, and the loudest
        # thing heard so far. Plain attributes rather than a small class
        # because the whole interaction is three seconds long and lives
        # entirely inside _feed_meter().
        self._measure_until = 0.0
        self._measure_peak = 0.0

        # ---- what the block covers, and what it lets through ----
        self.block_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.block_expander,
                                         self.block_box, on,
                                         "Block exceptions"),
            "Block exceptions")
        sc.addWidget(self.block_expander)
        self.block_box = QWidget()
        bb = QVBoxLayout(self.block_box)
        bb.setContentsMargins(8, 4, 0, 4)
        bb.setSpacing(6)
        bb_intro = QLabel(
            "Block apps (top right): while ON, no app sends anything "
            "until you switch it OFF. These two extend it to plugins and "
            "the Custom Box; the list names what keeps running anyway.")
        bb_intro.setObjectName("dim")
        bb_intro.setWordWrap(True)
        bb.addWidget(bb_intro)

        bp_row = QHBoxLayout()
        self.toggle_block_plugins = ToggleSwitch()
        self.toggle_block_plugins.toggled.connect(self.on_block_plugins)
        bp_row.addWidget(self.toggle_block_plugins)
        bp_row.addWidget(ToggleLabel("Also block plugins",
                                     self.toggle_block_plugins))
        bp_row.addStretch()
        bb.addLayout(bp_row)

        bx_row = QHBoxLayout()
        self.toggle_block_box = ToggleSwitch()
        self.toggle_block_box.toggled.connect(self.on_block_box)
        bx_row.addWidget(self.toggle_block_box)
        bx_row.addWidget(ToggleLabel("Also block the Custom Box",
                                     self.toggle_block_box))
        bx_row.addStretch()
        bb.addLayout(bx_row)

        exc_lbl = QLabel("Keep running while blocked:")
        exc_lbl.setStyleSheet("font-weight: 600;")
        bb.addWidget(exc_lbl)
        # rebuilt whenever the plugin list changes - see
        # refresh_block_exceptions()
        self.block_exc_box = QWidget()
        self.block_exc_layout = QVBoxLayout(self.block_exc_box)
        self.block_exc_layout.setContentsMargins(0, 0, 0, 0)
        self.block_exc_layout.setSpacing(2)
        bb.addWidget(self.block_exc_box)
        self.block_box.setVisible(False)
        sc.addWidget(self.block_box)
        # two-way translation: the other players, translated for you
        # (ui/pages/twoway_page.py)
        self.build_twoway_section(sc)
        self._sync_stt_availability()

        # ----- translation -----
        # Its own card since v1.6.5: the service, keys and how a
        # translation looks in the chatbox used to sit in the middle of
        # the To Text card and buried the record button.
        tcard = QFrame()
        tcard.setObjectName("card")
        tco = QVBoxLayout(tcard)
        tco.setContentsMargins(16, 14, 16, 16)
        tco.setSpacing(10)
        thead = QHBoxLayout()
        thead.addWidget(DragHandle(lambda pos: self.tb_card_drag("translate", pos),
                                   lambda: self.tb_card_drag_end("translate")))
        tt = QLabel("Translation")
        tt.setObjectName("cardtitle")
        thead.addWidget(tt)
        thead.addStretch()
        # what is active, readable while the card is collapsed
        self.tr_summary_lbl = QLabel("")
        self.tr_summary_lbl.setObjectName("dim")
        thead.addWidget(self.tr_summary_lbl)
        tco.addLayout(thead)
        self.tr_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.tr_expander, self.tr_box, on))
        tco.addWidget(self.tr_expander)
        self.tr_box = QWidget()
        ts = QVBoxLayout(self.tr_box)
        ts.setContentsMargins(8, 4, 0, 4)
        ts.setSpacing(8)

        # ---- translation method (four-tier system) ----
        method_row = QHBoxLayout()
        # only picks whose settings are shown - the service in use is
        # chosen in the To Text card (tr_active_combo)
        method_row.addWidget(QLabel("Settings for:"))
        self.tr_method_combo = QComboBox()
        fill_service_combo(self.tr_method_combo, TR_METHODS, mark=True)
        self.tr_method_combo.setToolTip(
            "Pick a service to set it up. AI services marked "
            "\U0001F4E6 still need installing \u2013 only services that "
            "are set up appear in the To Text dropdown.")
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
        ts.addLayout(method_row)

        fav_row = QHBoxLayout()
        self.toggle_tr_fav = ToggleSwitch()
        self.toggle_tr_fav.toggled.connect(self.on_tr_favorite)
        self.toggle_tr_fav.setToolTip(
            "Favorites are the only services in the To Text dropdown. "
            "No favorites = all services.")
        fav_row.addWidget(self.toggle_tr_fav)
        fav_row.addWidget(ToggleLabel("\u2605 Favorite", self.toggle_tr_fav))
        fav_row.addStretch()
        ts.addLayout(fav_row)

        # method 2: Google API key (only visible when Google is selected).
        # Empty = the keyless, unofficial gtx endpoint is used.
        self.google_row = QWidget()
        gr = QVBoxLayout(self.google_row)
        gr.setContentsMargins(0, 0, 0, 0)
        gr.setSpacing(4)
        gkey_row = QHBoxLayout()
        gkey_row.setContentsMargins(0, 0, 0, 0)
        gkey_row.addWidget(QLabel("Google API key:"))
        self.google_key_input = QLineEdit()
        self.google_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_key_input.setPlaceholderText(
            "optional \u2013 leave empty to use the keyless endpoint")
        self.google_key_input.textChanged.connect(self.on_google_key)
        gkey_row.addWidget(self.google_key_input, 1)
        gr.addLayout(gkey_row)
        gr.addWidget(self._key_link(
            "Get a key in the Google Cloud console", GOOGLE_KEYS_URL,
            "Create a project, enable the Cloud Translation API and "
            "generate an API key under Credentials."))
        self.google_warn_lbl = QLabel("")
        self.google_warn_lbl.setObjectName("dim")
        self.google_warn_lbl.setWordWrap(True)
        gr.addWidget(self.google_warn_lbl)
        ts.addWidget(self.google_row)

        # method 4: DeepL API key (only visible when DeepL is selected)
        self.deepl_row = QWidget()
        dr = QVBoxLayout(self.deepl_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.setSpacing(4)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(QLabel("DeepL API key:"))
        self.deepl_key_input = QLineEdit()
        self.deepl_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.deepl_key_input.setPlaceholderText("xxxxxxxx-xxxx-...-xxxx:fx")
        self.deepl_key_input.textChanged.connect(self.on_deepl_key)
        key_row.addWidget(self.deepl_key_input, 1)
        dr.addLayout(key_row)
        dr.addWidget(self._key_link(
            "Get a key in your DeepL account", DEEPL_KEYS_URL,
            "DeepL API Free gives 500,000 characters a month; the key "
            "for it ends in \u201c:fx\u201d."))
        ts.addWidget(self.deepl_row)

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
        # the official install guide, always there: Docker, pip, Windows
        self.libre_docs_btn = QPushButton("\U0001F4D6  Installation")
        self.libre_docs_btn.setObjectName("linkbtn")
        self.libre_docs_btn.setFixedHeight(30)
        self.libre_docs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.libre_docs_btn.setToolTip(
            f"Opens the LibreTranslate installation guide\n{LIBRE_INSTALL_URL}")
        self.libre_docs_btn.clicked.connect(
            lambda _=False: QDesktopServices.openUrl(QUrl(LIBRE_INSTALL_URL)))
        lr.addWidget(self.libre_docs_btn)
        ts.addWidget(self.libre_row)

        # method 5: Custom - an own API call, an installed CLI translator
        # or a Python file (core/custom_translator.py)
        self.custom_row = QWidget()
        cr = QVBoxLayout(self.custom_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(4)
        cr_head = QHBoxLayout()
        cr_head.setContentsMargins(0, 0, 0, 0)
        cr_head.addWidget(QLabel("Command / API call:"))
        cr_head.addStretch()
        ex_btn = QPushButton("LibreTranslate example")
        ex_btn.setObjectName("linkbtn")
        ex_btn.setFixedHeight(28)
        ex_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ex_btn.clicked.connect(lambda _=False: self.on_custom_example())
        cr_head.addWidget(ex_btn)
        cr.addLayout(cr_head)
        self.custom_snippet_edit = QPlainTextEdit()
        self.custom_snippet_edit.setFixedHeight(110)
        self.custom_snippet_edit.setPlaceholderText(
            "curl -X POST -H \"Content-Type: application/json\" -d "
            "'{\"q\": \"{text}\", \"source\": \"{source}\", "
            "\"target\": \"{target}\"}' http://localhost:5000/translate"
            "\n\n\u2026 or a command:  argos-translate --from {source} "
            "--to {target} {text}")
        self.custom_snippet_edit.textChanged.connect(self.on_custom_snippet)
        cr.addWidget(self.custom_snippet_edit)
        cf_row = QHBoxLayout()
        cf_row.setContentsMargins(0, 0, 0, 0)
        cf_row.addWidget(QLabel("or file:"))
        self.custom_file_input = QLineEdit()
        self.custom_file_input.setPlaceholderText(
            "(none) \u2013 .txt/.sh with the command, or .py with "
            "translate(text, source, target)")
        self.custom_file_input.textChanged.connect(self.on_custom_file)
        cf_row.addWidget(self.custom_file_input, 1)
        cf_btn = QPushButton("\U0001F4C2  Choose \u2026")
        cf_btn.setObjectName("linkbtn")
        cf_btn.setFixedHeight(28)
        cf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cf_btn.clicked.connect(lambda _=False: self.on_custom_choose())
        cf_row.addWidget(cf_btn)
        cr.addLayout(cf_row)
        cr_hint = QLabel(
            "Placeholders: {text} {source} {target}. A curl command is "
            "sent by the app itself (works on Windows too); anything else "
            "is run as a program and its output is the translation. A "
            "file, when set, wins over the text field. Pasted doc "
            "examples without placeholders work too \u2013 q/text, "
            "source and target in a JSON body are filled in. If the "
            "answer is not found, add  # response: field.path")
        cr_hint.setObjectName("dim")
        cr_hint.setWordWrap(True)
        cr.addWidget(cr_hint)
        ts.addWidget(self.custom_row)

        # method 3b: hosted LibreTranslate. Server picker (preset or a
        # URL you paste yourself) plus an optional API key, because most
        # public instances want one for anything beyond a trickle.
        self.libre_online_row = QWidget()
        lo = QVBoxLayout(self.libre_online_row)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(4)
        lo_srv = QHBoxLayout()
        lo_srv.setContentsMargins(0, 0, 0, 0)
        lo_srv.addWidget(QLabel("Server:"))
        self.libre_online_combo = QComboBox()
        for label, val in LIBRE_ONLINE_SERVERS:
            self.libre_online_combo.addItem(label, val)
        self.libre_online_combo.currentIndexChanged.connect(
            self.on_libre_online_server)
        lo_srv.addWidget(self.libre_online_combo, 1)
        lo.addLayout(lo_srv)
        # only shown for "Custom server ..."
        self.libre_online_url_row = QWidget()
        lo_url = QHBoxLayout(self.libre_online_url_row)
        lo_url.setContentsMargins(0, 0, 0, 0)
        lo_url.addWidget(QLabel("URL:"))
        self.libre_online_url_input = QLineEdit()
        self.libre_online_url_input.setPlaceholderText(
            "https://your-server.tld")
        self.libre_online_url_input.setToolTip(
            "Any LibreTranslate server, e.g. https://your-instance.tld "
            "\u2013 https:// is added automatically if you leave it out.")
        self.libre_online_url_input.textChanged.connect(
            self.on_libre_online_url)
        lo_url.addWidget(self.libre_online_url_input, 1)
        lo.addWidget(self.libre_online_url_row)
        lo_key = QHBoxLayout()
        lo_key.setContentsMargins(0, 0, 0, 0)
        lo_key.addWidget(QLabel("API key:"))
        self.libre_online_key_input = QLineEdit()
        self.libre_online_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.libre_online_key_input.setPlaceholderText(
            "optional \u2013 only needed if the instance asks for one")
        self.libre_online_key_input.textChanged.connect(
            self.on_libre_online_key)
        lo_key.addWidget(self.libre_online_key_input, 1)
        lo.addLayout(lo_key)
        ts.addWidget(self.libre_online_row)

        # v1.6.5: AI services (core/ai_translator.py) - status, install /
        # log in / start buttons, model and, for Custom AI, the command
        self.ai_row = QWidget()
        ar = QVBoxLayout(self.ai_row)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.setSpacing(6)
        self.ai_status_lbl = QLabel("")
        self.ai_status_lbl.setWordWrap(True)
        ar.addWidget(self.ai_status_lbl)
        ab = QHBoxLayout()
        ab.setContentsMargins(0, 0, 0, 0)

        def _btn(text, slot, tip=""):
            b = QPushButton(text)
            b.setObjectName("linkbtn")
            b.setFixedHeight(30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _=False: slot())
            ab.addWidget(b)
            return b
        self.ai_install_btn = _btn(
            "📦  Install", self.on_ai_install,
            "Installs the program right here – Claude Code with its "
            "official installer, Gemini CLI / Codex with npm into "
            "~/.local (no sudo; a missing npm is installed first, a "
            "password window asks). Ollama and Windows open a terminal.")
        self.ai_login_btn = _btn(
            "🔑  Log in", self.on_ai_login,
            "Opens a terminal with the program – log in there once "
            "with your account, then close it.")
        self.ai_start_btn = _btn(
            "🚀  Start Ollama", self.on_ai_start_ollama,
            "Starts “ollama serve” in the background.")
        self.ai_pull_btn = _btn(
            "📥  Download model", self.on_ai_pull,
            "Opens a terminal with “ollama pull <model>”.")
        self.ai_refresh_btn = _btn(
            "⟳", lambda: self._sync_ai_ui(self._tr_view_method()),
            "Check again (after installing / logging in)")
        self.ai_refresh_btn.setFixedWidth(36)
        ab.addStretch()
        ar.addLayout(ab)
        am = QHBoxLayout()
        am.setContentsMargins(0, 0, 0, 0)
        am.addWidget(QLabel("Model:"))
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.setEditable(True)
        self.ai_model_combo.setToolTip(
            "Pick one or type any other model name.")
        self.ai_model_combo.currentTextChanged.connect(self.on_ai_model)
        am.addWidget(self.ai_model_combo, 1)
        ar.addLayout(am)
        self.ai_url_row = QWidget()
        au = QHBoxLayout(self.ai_url_row)
        au.setContentsMargins(0, 0, 0, 0)
        au.addWidget(QLabel("Ollama URL:"))
        self.ai_url_input = QLineEdit()
        self.ai_url_input.setPlaceholderText(ai.DEFAULT_OLLAMA_URL)
        self.ai_url_input.textChanged.connect(self.on_ai_url)
        au.addWidget(self.ai_url_input, 1)
        ar.addWidget(self.ai_url_row)
        self.ai_custom_box = QWidget()
        ac = QVBoxLayout(self.ai_custom_box)
        ac.setContentsMargins(0, 0, 0, 0)
        ac.setSpacing(4)
        ac_head = QHBoxLayout()
        ac_head.setContentsMargins(0, 0, 0, 0)
        ac_head.addWidget(QLabel("Command / API call:"))
        ac_head.addStretch()
        ac_ex = QPushButton("OpenAI-compatible example")
        ac_ex.setObjectName("linkbtn")
        ac_ex.setFixedHeight(28)
        ac_ex.setCursor(Qt.CursorShape.PointingHandCursor)
        ac_ex.clicked.connect(
            lambda _=False: self.ai_custom_edit.setPlainText(
                ai.CUSTOM_EXAMPLE))
        ac_head.addWidget(ac_ex)
        ac.addLayout(ac_head)
        self.ai_custom_edit = QPlainTextEdit()
        self.ai_custom_edit.setFixedHeight(110)
        self.ai_custom_edit.setPlaceholderText(
            "ollama run {model} {prompt}\n\n\u2026 or a curl call to your "
            "own AI server")
        self.ai_custom_edit.textChanged.connect(self.on_ai_custom_cmd)
        ac.addWidget(self.ai_custom_edit)
        ac_hint = QLabel(
            "Placeholders: {prompt} (the finished translation request), "
            "{text} {source} {target} {model}. Without {prompt}/{text} "
            "the request goes in on stdin. curl is sent by the app; "
            "name the answer field with  # response: field.path")
        ac_hint.setObjectName("dim")
        ac_hint.setWordWrap(True)
        ac.addWidget(ac_hint)
        ar.addWidget(self.ai_custom_box)
        ts.addWidget(self.ai_row)

        self.tr_method_hint = QLabel("")
        self.tr_method_hint.setObjectName("dim")
        self.tr_method_hint.setWordWrap(True)
        ts.addWidget(self.tr_method_hint)

        # ---- how a translation shows up in the chatbox ----
        self.tr_display_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.tr_display_expander,
                                         self.tr_display_box, on,
                                         "Chatbox display"),
            "Chatbox display")
        ts.addWidget(self.tr_display_expander)
        self.tr_display_box = QWidget()
        dx = QVBoxLayout(self.tr_display_box)
        dx.setContentsMargins(8, 4, 0, 4)
        dx.setSpacing(6)
        # show original + translation together in the chatbox
        both_row = QHBoxLayout()
        self.toggle_stt_both = ToggleSwitch()
        self.toggle_stt_both.toggled.connect(self.on_stt_show_both)
        both_row.addWidget(self.toggle_stt_both)
        both_row.addWidget(ToggleLabel("Show original + translation",
                                       self.toggle_stt_both))
        both_row.addStretch()
        dx.addLayout(both_row)
        self.toggle_stt_both.setToolTip(
            "Chatbox shows \"original \u2192 translation\".")
        # placeholder in the chatbox while the translation is in flight
        notice_row = QHBoxLayout()
        self.toggle_translate_notice = ToggleSwitch()
        self.toggle_translate_notice.toggled.connect(
            self.on_translate_notice)
        notice_row.addWidget(self.toggle_translate_notice)
        notice_row.addWidget(ToggleLabel(
            "Say when a translation is running",
            self.toggle_translate_notice))
        notice_row.addSpacing(12)
        self.translate_notice_edit = QLineEdit()
        self.translate_notice_edit.setFixedWidth(180)
        self.translate_notice_edit.setPlaceholderText(
            DEFAULT_TRANSLATE_NOTICE)
        self.translate_notice_edit.editingFinished.connect(
            self.on_translate_notice_text)
        notice_row.addWidget(self.translate_notice_edit)
        notice_row.addStretch()
        dx.addLayout(notice_row)
        self.toggle_translate_notice.setToolTip(
            "Shows this text in the chatbox while the translation is "
            "still on its way, so the gap does not look like nothing "
            "happening. Goes out the same route as the message itself.")
        self.tr_display_box.setVisible(False)
        ts.addWidget(self.tr_display_box)
        self.tr_box.setVisible(False)
        tco.addWidget(self.tr_box)

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
        self.tb_cards = {"chat": card, "stt": scard,
                         "translate": tcard, "presets": pcard}
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

    # ================================================================
    # Block apps
    # ================================================================
    #: everything the block can cover, besides the plugins. The four app
    #: keys match the toggles; "custombox" is the frame in build_payload.
    BLOCK_TARGETS = (("status", "Personal Status"),
                     ("media", "MediaPlay"),
                     ("hardware", "Hardware"),
                     ("aio", "All in one"),
                     ("custombox", "Custom Box"))

    def block_exceptions(self):
        """The set of keys that keep running while Block apps is on."""
        raw = self.cfg.get("stt_block_except")
        return set(raw) if isinstance(raw, list) else set()

    def blocked_plugin_ids(self):
        """Plugin ids the block currently silences. Empty set when the
        block is off or plugins are excluded from it - MainWindow hands
        this to the PluginManager on every frame."""
        if not (self.cfg.get("stt_block")
                and self.cfg.get("stt_block_plugins", True)):
            return set()
        keep = self.block_exceptions()
        return {p.pid for p in self.plugins.ordered()
                if f"plugin:{p.pid}" not in keep}

    def box_blocked(self):
        """True when the Custom Box frame has to stay away this frame."""
        return bool(self.cfg.get("stt_block")
                    and self.cfg.get("stt_block_box", True)
                    and "custombox" not in self.block_exceptions())

    def on_block_plugins(self, on):
        self.cfg["stt_block_plugins"] = bool(on)
        self.save_config()
        self.update_preview()

    def on_block_box(self, on):
        self.cfg["stt_block_box"] = bool(on)
        self.save_config()
        self.update_preview()

    def on_block_exception(self, key, on):
        keep = self.block_exceptions()
        if on:
            keep.add(key)
        else:
            keep.discard(key)
        self.cfg["stt_block_except"] = sorted(keep)
        self.save_config()
        # An app that just became an exception while the block is active
        # has to come back on right now, not on the next toggle - the
        # checkbox would otherwise look like it did nothing.
        if self.cfg.get("stt_block") and on:
            toggles = self._app_toggles()
            if key in toggles and key in self.cfg.get("stt_block_saved", []):
                self._block_updating = True
                try:
                    toggles[key].setChecked(True)
                    saved = [k for k in self.cfg["stt_block_saved"]
                             if k != key]
                    self.cfg["stt_block_saved"] = saved
                finally:
                    self._block_updating = False
                self.save_config()
        self.update_preview()

    def refresh_block_exceptions(self):
        """(Re)builds the checkbox list. Called from refresh_plugin_list(),
        so installing or removing a plugin is reflected here as well."""
        layout = self.block_exc_layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        keep = self.block_exceptions()
        for key, label in self.BLOCK_TARGETS:
            box = QCheckBox(label)
            box.setChecked(key in keep)
            box.toggled.connect(
                lambda on, k=key: self.on_block_exception(k, on))
            layout.addWidget(box)
        plugins = self.plugins.ordered()
        if plugins:
            head = QLabel("Plugins")
            head.setObjectName("dim")
            layout.addWidget(head)
        for plugin in plugins:
            key = f"plugin:{plugin.pid}"
            box = QCheckBox(plugin.name or plugin.pid)
            box.setChecked(key in keep)
            box.toggled.connect(
                lambda on, k=key: self.on_block_exception(k, on))
            layout.addWidget(box)

    def _app_toggles(self):
        return {"status": self.toggle_active, "media": self.toggle_media,
                "hardware": self.toggle_hw, "aio": self.toggle_aio}

    def on_stt_block(self, on):
        self.cfg["stt_block"] = on
        if self._block_updating:
            self.save_config()
            return
        app_toggles = self._app_toggles()
        keep = self.block_exceptions()
        self._block_updating = True
        try:
            if on:
                # remember which apps were on, then switch them off -
                # except the ones the exception list protects
                saved = [k for k, t in app_toggles.items()
                         if t.isChecked() and k not in keep]
                self.cfg["stt_block_saved"] = saved
                for k in saved:
                    app_toggles[k].setChecked(False)
                kept = [k for k in keep if k in app_toggles]
                self.log(f"Block apps: ON \u2013 switched off: "
                         f"{', '.join(saved) if saved else 'nothing was on'}"
                         + (f" | kept running: {', '.join(sorted(kept))}"
                            if kept else ""))
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
        self._update_tr_summary()

    def _tr_view_method(self):
        """The service whose settings the Translation card shows."""
        return (self.tr_method_combo.currentData()
                or self.cfg.get("stt_method", METHOD_LINGVA))

    def on_tr_method(self, idx):
        """Translation card selector - only switches which settings are
        shown, the service in use is picked in the To Text card."""
        self._update_tr_method_ui()

    def on_tr_active(self, idx):
        """To Text dropdown: the service actually used."""
        method = self.tr_active_combo.itemData(idx)
        if not method:
            return
        if method != self.cfg.get("stt_method"):
            self.cfg["stt_method"] = method
            self.save_config()
            self.stt.method = method  # applies live
            self.log(f"Translation service: {method}")
        # the Translation card follows, so its settings match
        j = self.tr_method_combo.findData(method)
        if j >= 0 and j != self.tr_method_combo.currentIndex():
            self.tr_method_combo.setCurrentIndex(j)
        self._update_tr_summary()

    def on_tr_favorite(self, on):
        method = self.tr_method_combo.currentData()
        if not method:
            return
        favs = [m for m in self.cfg.get("stt_tr_favorites", [])
                if m != method]
        if on:
            favs.append(method)
        self.cfg["stt_tr_favorites"] = favs
        self.save_config()
        self._fill_tr_active_combo()

    def _fill_tr_active_combo(self):
        """Favorites only when there are any, else every service. If the
        service in use is no favorite, the first favorite takes over."""
        favs = set(self.cfg.get("stt_tr_favorites") or [])
        cur = self.cfg.get("stt_method", METHOD_LINGVA)
        # v1.6.6: AI services only once they are set up (installed /
        # command entered) - the one in use always stays
        usable = [(l, m) for l, m in TR_METHODS
                  if not ai.is_ai(m) or m == cur or ai.configured(m)]
        items = [(l, m) for l, m in usable if m in favs] or usable
        c = self.tr_active_combo
        c.blockSignals(True)
        c.clear()
        fill_service_combo(c, items)
        idx = c.findData(self.cfg.get("stt_method", METHOD_LINGVA))
        c.setCurrentIndex(idx if idx >= 0 else first_service_index(c))
        c.blockSignals(False)
        self.on_tr_active(c.currentIndex())

    def _update_tr_method_ui(self):
        """Shows only the option fields of the selected method and
        updates the hint text. The LibreTranslate install button only
        appears while LibreTranslate is selected and not installed."""
        method = self._tr_view_method()
        self.toggle_tr_fav.blockSignals(True)
        self.toggle_tr_fav.setChecked(
            method in (self.cfg.get("stt_tr_favorites") or []))
        self.toggle_tr_fav.blockSignals(False)
        self.deepl_row.setVisible(method == METHOD_DEEPL)
        self.google_row.setVisible(method == METHOD_GOOGLE)
        self.libre_row.setVisible(method == METHOD_LIBRE)
        self.libre_online_row.setVisible(method == METHOD_LIBRE_ONLINE)
        self.custom_row.setVisible(method == METHOD_CUSTOM)
        self.ai_row.setVisible(ai.is_ai(method))
        if ai.is_ai(method):
            self._sync_ai_ui(method)
        if method == METHOD_LIBRE_ONLINE:
            self._sync_libre_online_ui()
        if method == METHOD_GOOGLE:
            self._update_google_warning()
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
                "Direct Google Translate \u2013 fastest (no proxy hop). "
                "With your own API key the official Cloud Translation "
                "API is used; without a key the unofficial endpoint is "
                "used. Either way the request goes straight to Google, "
                "so tracking is possible."),
            METHOD_LINGVA: (
                "Anonymous Lingva-Translate proxy (lingva.ml) \u2013 no "
                "API key, no direct Google tracking. Currently broken on "
                "every public instance (text comes back untranslated) "
                "\u2013 the app notices and falls back to LibreTranslate "
                "(translate.adminforge.de), then Google. Lingva is no "
                "longer used as an automatic fallback."),
            METHOD_LIBRE: (
                "Local LibreTranslate instance \u2013 100% offline on "
                "your own PC. Install it yourself once (\u201cInstallation\u201d "
                "opens the guide), e.g.  pip install libretranslate "
                "\u2013 afterwards the Start/Stop button appears here (default "
                "http://127.0.0.1:5000). If it is not reachable, "
                "the fallback chain (adminForge, then Google) takes over."),
            METHOD_LIBRE_ONLINE: (
                "Default. LibreTranslate on somebody else's server \u2013 nothing "
                "to install, works on Windows and Linux alike. The preset "
                "(de.libretranslate.com) and libretranslate.com need an "
                "API key; translate.adminforge.de and lt.pyrine.net work "
                "without one (adminForge publishes an imprint and says it "
                "logs nothing; lt.pyrine.net has no imprint or privacy "
                "notice). Pick \u201cCustom server\u201d for any other "
                "instance. If the server fails, the fallback chain "
                "(adminForge, then Google) takes over."),
            METHOD_DEEPL: (
                "Official DeepL API \u2013 free key at deepl.com (API "
                "Free plan, 500k chars/month); keys ending in ':fx' are "
                "detected as free-plan keys automatically. If DeepL "
                "fails (e.g. monthly limit reached), the fallback chain "
                "(adminForge, then Google) takes over."),
            METHOD_CUSTOM: (
                "Your own translator: paste the API call from its "
                "documentation (curl), a command of an installed CLI "
                "translator, or pick a file. Press Test to check it. If it "
                "fails, the fallback chain (adminForge, then Google) "
                "takes over."),
            ai.METHOD_OLLAMA: (
                "A local AI on your own PC – offline, free, nothing "
                "leaves your machine. Needs Ollama and one model "
                "(gemma3:4b ≈ 3 GB). It shares the GPU with VR, so a "
                "small model is best. If it fails, the normal fallback "
                "chain takes over."),
            ai.METHOD_CLAUDE: (
                "Claude via the Claude Code program – uses your "
                "Claude login (Pro/Max or API key). Install, log in once, "
                "done. Takes a few seconds per message; haiku is the "
                "fastest. Your text goes to Anthropic."),
            ai.METHOD_GEMINI: (
                "Gemini via the Gemini CLI – uses your Google login "
                "(free tier available). Install (needs npm), log in once. "
                "Your text goes to Google."),
            ai.METHOD_CHATGPT: (
                "ChatGPT via OpenAI's Codex CLI – uses your ChatGPT "
                "login. Install (needs npm), log in once. The luna model "
                "is the fastest. Your text goes to OpenAI."),
            ai.METHOD_AI_CUSTOM: (
                "Your own AI: a command or a curl call to any server "
                "(LM Studio, llama.cpp, vLLM, a remote Ollama …). "
                "The app builds the translation request and puts it in "
                "{prompt}. Press Test to check it."),
        }
        self.tr_method_hint.setText(hints.get(method, ""))
        self._update_tr_summary()

    # ---------------------------------------------------- AI services
    def _sync_ai_ui(self, method):
        """Status line, buttons and model list of an AI service. The
        checks (Ollama HTTP probe, login files) run off the GUI thread."""
        if not ai.is_ai(method):
            return
        is_cli = method in ai.CLI_METHODS
        is_ollama = method == ai.METHOD_OLLAMA
        self.ai_url_row.setVisible(is_ollama)
        self.ai_custom_box.setVisible(method == ai.METHOD_AI_CUSTOM)
        self.ai_install_btn.setVisible(False)
        self.ai_login_btn.setVisible(False)
        self.ai_start_btn.setVisible(False)
        self.ai_pull_btn.setVisible(False)
        self.ai_refresh_btn.setVisible(method != ai.METHOD_AI_CUSTOM)
        self._fill_ai_models(method, ai.MODELS.get(method, []))
        if method == ai.METHOD_AI_CUSTOM:
            self.ai_status_lbl.setText("")
            return
        self.ai_status_lbl.setText("⏳ Checking …")

        def work():
            st = {"installed": ai.installed(method)}
            if is_cli:
                st["login"] = ai.logged_in(method)
            if is_ollama:
                st["running"] = ai.ollama_running()
                st["models"] = ai.models_for(method) if st["running"] \
                    else list(ai.MODELS[method])
                st["have"] = ai.ollama_models() if st["running"] else []
            return st
        self.run_async(work, lambda st, m=method: self._on_ai_status(m, st),
                       interval=150)

    def _on_ai_status(self, method, st):
        self.refresh_ai_setup()
        if method != self._tr_view_method():
            return      # switched to another service meanwhile
        inst = st.get("installed")
        name = {ai.METHOD_CLAUDE: "Claude Code", ai.METHOD_GEMINI:
                "Gemini CLI", ai.METHOD_CHATGPT: "Codex CLI"}.get(
                    method, ai.BINARIES.get(method, ""))
        self.ai_install_btn.setVisible(not inst)
        if method == ai.METHOD_OLLAMA:
            running = st.get("running")
            model = ai.model_of(method)
            have = st.get("have", [])
            self._fill_ai_models(method, st.get("models", []))
            self.ai_start_btn.setVisible(bool(inst) and not running)
            self.ai_pull_btn.setVisible(bool(running))
            if running:
                ok = model in have or f"{model}:latest" in have
                self.ai_status_lbl.setText(
                    f"✅ Ollama is running – {len(have)} "
                    f"model(s) installed" + ("" if ok else
                    f" · ⚠ “{model}” not downloaded "
                    f"yet"))
            elif inst or not self._ai_url_is_local():
                self.ai_status_lbl.setText(
                    "⚠ Ollama is not running (or not reachable).")
            else:
                self.ai_status_lbl.setText(
                    "❌ Ollama is not installed.")
            return
        login = st.get("login")
        self.ai_login_btn.setVisible(bool(inst))
        if not inst:
            npm = (" (needs npm / Node.js)" if ai.needs_npm(method)
                   else "")
            self.ai_status_lbl.setText(
                f"❌ {name} is not installed{npm}.")
        elif login is False:
            self.ai_status_lbl.setText(
                f"⚠ {name} is installed – log in once.")
        elif login is None:
            self.ai_status_lbl.setText(
                f"✅ {name} is installed (login not detectable "
                f"– press Test).")
        else:
            self.ai_status_lbl.setText(
                f"✅ {name} is installed and logged in.")

    def refresh_ai_setup(self):
        """v1.6.6: re-reads which AI services are set up - the marks
        in "Settings for" and the entries of the To Text dropdown."""
        c = self.tr_method_combo
        cur = c.currentData()
        state = tuple(ai.configured(m) for m in ai.AI_METHODS)
        if state == getattr(self, "_ai_setup_state", None):
            return
        self._ai_setup_state = state
        c.blockSignals(True)
        c.clear()
        fill_service_combo(c, TR_METHODS, mark=True)
        j = c.findData(cur)
        c.setCurrentIndex(j if j >= 0 else first_service_index(c))
        c.blockSignals(False)
        self._fill_tr_active_combo()

    def _ai_url_is_local(self):
        url = ai.ollama_url()
        return "127.0.0.1" in url or "localhost" in url

    def _fill_ai_models(self, method, models):
        c = self.ai_model_combo
        cur = ai.model_of(method)
        c.blockSignals(True)
        c.clear()
        for m in models:
            c.addItem(m)
        if cur and c.findText(cur) < 0:
            c.addItem(cur)
        c.setCurrentText(cur)
        c.blockSignals(False)

    def on_ai_model(self, text):
        method = self._tr_view_method()
        key = ai.MODEL_KEYS.get(method)
        if not key:
            return
        self.cfg[key] = text.strip()
        self.save_config_later()
        self._update_tr_summary()

    def on_ai_url(self, text):
        self.cfg["stt_ai_ollama_url"] = text.strip()
        self.save_config_later()

    def on_ai_custom_cmd(self):
        self.cfg["stt_ai_custom_cmd"] = self.ai_custom_edit.toPlainText()
        self.save_config_later()
        self.refresh_ai_setup()     # v1.6.6: To Text dropdown follows

    def on_ai_install(self):
        method = self._tr_view_method()
        if ai.can_install_in_app(method):
            self._ai_install_in_app(method)
            return
        cmd = ai.install_command(method)
        if cmd is None:
            QDesktopServices.openUrl(QUrl(ai.OLLAMA_DOWNLOAD_URL))
            self.ai_status_lbl.setText(
                "Download page opened – install Ollama, then press "
                "⟳.")
            return
        ok, msg = ai.run_in_terminal(cmd)
        self.ai_status_lbl.setText(
            "⏳ Installing in the terminal – press ⟳ when "
            "it is done." if ok else f"❌ {msg}")
        self.log(f"AI install ({method}): {cmd}")

    def _ai_install_in_app(self, method):
        """v1.6.6: runs the install steps right here (like
        LinuxVR-ViewShot) - no terminal, no command to type. npm goes
        to ~/.local without sudo; a missing npm is installed first via
        pkexec (password window)."""
        from PyQt6.QtCore import QProcess
        if getattr(self, "_ai_install_proc", None) is not None:
            return
        steps = ai.install_steps(method)
        self.ai_install_btn.setEnabled(False)
        self.ai_install_btn.setText("⏳  Installing …")

        def done(error=""):
            self._ai_install_proc = None
            self.ai_install_btn.setEnabled(True)
            self.ai_install_btn.setText("📦  Install")
            if error:
                self.log(f"AI install ({method}) failed: {error}")
            self._sync_ai_ui(self._tr_view_method())
            if error:
                QTimer.singleShot(1500, lambda: self.ai_status_lbl.setText(
                    f"❌ Install failed: {error}\nManual: "
                    f"{ai.install_command(method) or ''}"))
            else:
                self.log(f"AI install ({method}): done")
                self.refresh_ai_setup()

        def next_step():
            if not steps:
                done()
                return
            argv = steps.pop(0)()
            if not argv:
                done("npm is missing and could not be installed")
                return
            if argv[0] == "pkexec":
                self.ai_status_lbl.setText(
                    "🔐 A password window opens to install npm …")
            else:
                shown = argv[2] if argv[:2] == ["bash", "-c"] \
                    else " ".join(argv[1:])
                self.ai_status_lbl.setText(
                    f"⏳ Installing: {shown}\n(can take 1–2 minutes)")
            self.log(f"AI install ({method}): {' '.join(argv)}")
            proc = QProcess(self)
            proc.setWorkingDirectory(os.path.expanduser("~"))
            self._ai_install_proc = proc

            def finished(code, _status):
                if code != 0:
                    err = bytes(proc.readAllStandardError()).decode(
                        errors="replace").strip()
                    done(err.splitlines()[-1] if err else f"exit {code}")
                    return
                next_step()

            def failed(err):
                # finished() never comes for a program that did not start
                if err == QProcess.ProcessError.FailedToStart:
                    done(proc.errorString())
            proc.finished.connect(finished)
            proc.errorOccurred.connect(failed)
            proc.start(argv[0], argv[1:])
        next_step()

    def on_ai_login(self):
        method = self._tr_view_method()
        argv = ai.login_command(method)
        if argv is None:
            self.ai_status_lbl.setText("❌ Not installed yet.")
            return
        ok, msg = ai.run_in_terminal(argv)
        self.ai_status_lbl.setText(
            "🔑 Log in in the terminal (Claude: type /login), "
            "close it – this updates by itself." if ok else f"❌ {msg}")
        if ok:
            # v1.6.6: notice the login by itself (every 2 s, max 5 min)
            self._ai_login_polls = 0
            self._ai_login_method = method
            t = getattr(self, "_ai_login_timer", None)
            if t is None:
                t = self._ai_login_timer = QTimer(self)
                t.setInterval(2000)
                t.timeout.connect(self._poll_ai_login)
            t.start()

    def _poll_ai_login(self):
        self._ai_login_polls += 1
        method = self._ai_login_method
        if ai.logged_in(method) or self._ai_login_polls > 150:
            self._ai_login_timer.stop()
            if self._tr_view_method() == method:
                self._sync_ai_ui(method)

    def on_ai_start_ollama(self):
        from core.constants import CONFIG_DIR
        ok, msg = ai.start_ollama(CONFIG_DIR / "ollama.log")
        if not ok:
            self.ai_status_lbl.setText(f"❌ {msg}")
            return
        self.ai_status_lbl.setText("⏳ Starting Ollama …")
        QTimer.singleShot(2500, lambda: self._sync_ai_ui(
            self._tr_view_method()))

    def on_ai_pull(self):
        model = ai.model_of(ai.METHOD_OLLAMA)
        exe = ai.find_binary("ollama")
        if not exe:
            QDesktopServices.openUrl(QUrl(ai.OLLAMA_LIBRARY_URL))
            return
        ok, msg = ai.run_in_terminal([exe, "pull", model])
        self.ai_status_lbl.setText(
            f"📥 Downloading “{model}” in the terminal "
            f"– press ⟳ when it is done." if ok
            else f"❌ {msg}")

    def _update_tr_summary(self):
        """Short "service -> language" line in the Translation card head,
        readable while the card is collapsed."""
        lbl = getattr(self, "tr_summary_lbl", None)
        if lbl is None:
            return
        combo = getattr(self, "tr_active_combo", None)
        if combo is None:
            return
        service = combo.currentText().split(" (")[0]
        model = ai.model_of(combo.currentData() or "")
        if model:
            service = f"{service} \u00b7 {model}"
        if self.stt_out_combo.currentData():
            text = f"{service} \u2192 {self.stt_out_combo.currentText()}"
        else:
            text = f"{service} \u00b7 no translation"
        lbl.setText(text)

    def _fill_mic_combo(self, force=False):
        """(Re)populates the microphone dropdown; keeps the configured
        selection when the device is still present.

        ENUMERATION RUNS ON A WORKER THREAD. Asking PortAudio for the
        device list is a blocking C call with no timeout, and when a
        device vanished while the system still lists it - which is what
        leaving VR does to a virtual microphone - it can block forever.
        This used to run right here, on the GUI thread, so the window
        froze and, because a frozen Qt client on Wayland keeps its input
        grab, the whole desktop went with it.

        Until the answer arrives the dropdown shows the last known list,
        so the entry you picked is still selectable the whole time.
        """
        if getattr(self, "_mic_scan_busy", False):
            return
        self._mic_scan_busy = True
        show_raw = bool(self.cfg.get("stt_mic_show_raw", False)) \
            if hasattr(self, "cfg") else False
        want = self.cfg.get("stt_mic", "") if hasattr(self, "cfg") else ""
        self._apply_mic_list(self._cached_entries(show_raw, want),
                             scanning=True)

        def work():
            entries, _devices, _sources = list_microphone_groups(
                self.log, force=force, show_raw=show_raw, selected=want)
            return entries

        self.run_async(
            work, self._on_mic_list, interval=150,
            on_error=lambda _e: self._on_mic_list(
                self._cached_entries(show_raw, want)))

    @staticmethod
    def _cached_entries(show_raw, selected):
        """The last known list, built without touching anything.

        Both halves are cached separately (core/speechtotext.py), so a
        scan that hangs or fails still leaves a dropdown with the user's
        own choice in it rather than a single "System default".
        """
        from core.speechtotext import cached_sources
        return micgroups.build(cached_microphones(),
                               sources=cached_sources(),
                               show_raw=show_raw, selected=selected)

    def _on_mic_list(self, entries):
        self._mic_scan_busy = False
        self._apply_mic_list(entries or [])
        self._update_mic_raw_hint(entries or [])
        stuck = driver_stuck()
        if stuck:
            self.stt_status_lbl.setText(
                f"\u26A0 The audio driver is not responding ({stuck}). "
                f"Showing the last known device list \u2013 press \u27F3 "
                f"to try again.")
            self.stt_status_lbl.setStyleSheet("color: #d9884a;")

    def _apply_mic_list(self, entries, scanning=False):
        """Paints the dropdown. GUI thread only, and it never touches
        PortAudio - `entries` is already resolved.

        The groups are real, non-selectable rows in the model rather
        than a prefix on every label. That is the whole point of the
        rewrite: a flat list of forty ALSA PCMs cannot be read, and
        naming the group on each line just makes each line longer. The
        headers also carry the explanation of what the group IS, which
        is where "a monitor records your speakers, not your voice" can
        be said once instead of forty times.
        """
        want = micgroups.normalize(
            self.cfg.get("stt_mic", "") if hasattr(self, "cfg") else "")
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        model = self.mic_combo.model()
        by_group = {}
        for item in entries or ():
            by_group.setdefault(item["group"], []).append(item)
        first = True
        for group in micgroups.GROUP_ORDER:
            rows = by_group.get(group)
            if not rows:
                continue
            if group != micgroups.G_SYSTEM:
                self.mic_combo.addItem(
                    f"\u2014 {micgroups.LABELS.get(group, group)} \u2014",
                    None)
                pos = self.mic_combo.count() - 1
                self.mic_combo.setItemData(
                    pos, micgroups.HINTS.get(group, ""),
                    Qt.ItemDataRole.ToolTipRole)
                try:
                    # a header is a label, not a choice - Qt only knows
                    # that if the row itself says so
                    model.item(pos).setFlags(Qt.ItemFlag.NoItemFlags)
                except Exception:      # noqa: BLE001 - custom model
                    pass
            for item in rows:
                label = item["label"]
                if item["default"]:
                    label = f"\u25CF  {label}"
                if first and scanning:
                    label += " \u2013 scanning \u2026"
                first = False
                self.mic_combo.addItem(label, item["id"])
                tip = item.get("detail") or ""
                note = item.get("note") or ""
                if note:
                    tip = f"{tip}\n\n{note}" if tip else note
                if tip:
                    self.mic_combo.setItemData(
                        self.mic_combo.count() - 1, tip,
                        Qt.ItemDataRole.ToolTipRole)
        pos = self.mic_combo.findData(want)
        self.mic_combo.setCurrentIndex(pos if pos >= 0 else 0)
        self.mic_combo.blockSignals(False)
        # the Two-way source dropdown lists the very same entries
        if hasattr(self, "apply_twoway_devices"):
            self.apply_twoway_devices(entries)

    def _update_mic_raw_hint(self, entries):
        """Says what the hidden half of the list is, and whether the
        grouped list is available at all."""
        if not hasattr(self, "mic_raw_hint"):
            return
        if IS_WINDOWS:
            # Windows has no pactl, so the grouping there is a different
            # job: PortAudio reports every microphone once per host API
            # (MME, DirectSound, WASAPI, WDM-KS), and the toggle decides
            # whether those duplicates are shown.
            self.mic_raw_w.setVisible(True)
            self.mic_raw_hint.setText(
                "Windows offers every microphone through several audio "
                "APIs, so PortAudio lists each one three or four times. "
                "The list above keeps one entry per device (WASAPI where "
                "there is one, because MME cuts names off at 31 "
                "characters). Turn this on to see the other routes - "
                "worth trying if a device refuses to open.")
            return
        if not mic_pactl.available():
            self.mic_raw_w.setVisible(False)
            return
        self.mic_raw_w.setVisible(True)
        if entries is None:
            return          # visibility only - keep whatever it says
        grouped = sum(1 for e in entries
                      if str(e.get("id", "")).startswith("pulse:"))
        if grouped:
            self.mic_raw_hint.setText(
                "The list above comes from PipeWire, so it has your "
                "virtual sources in it (VR microphone, echo-cancel, "
                "routing apps) and only counts each real device once. "
                "Direct hardware means ALSA devices opened past the "
                "sound server \u2013 exclusive access, HDMI outputs "
                "listed as if they were inputs, and no VR microphone. "
                "Only needed when the list above does not work.")
        else:
            self.mic_raw_hint.setText(
                "PipeWire is there but returned no sources, so the plain "
                "device list is being shown. Turn this on if the "
                "microphone you want is missing.")

    def on_mic_show_raw(self, on):
        self.cfg["stt_mic_show_raw"] = bool(on)
        self.save_config()
        self._fill_mic_combo()

    def on_mic_refresh(self):
        """The \u27F3 button. Forces a fresh scan even after a previous
        timeout - the usual fix is on the user's side (plug the device
        back in, restart PipeWire) and the app cannot notice that."""
        clear_driver_stuck()
        self.stt_status_lbl.setText("Scanning for microphones \u2026")
        self.stt_status_lbl.setStyleSheet("")
        self._fill_mic_combo(force=True)

    def on_mic_changed(self, idx):
        data = self.mic_combo.itemData(idx)
        if data is None:
            return          # a group header; the model should prevent it
        self.cfg["stt_mic"] = data or ""
        self.save_config()
        self.log("Speech to Text: microphone = "
                 + (describe_entry(self.cfg["stt_mic"]) or "system default"))
        # a running test belongs to the device that WAS selected, so it
        # is restarted rather than left measuring the previous one
        if self.mic_test.running:
            self._start_mic_test()

    def on_mic_strict(self, on):
        self.cfg["stt_mic_strict"] = bool(on)
        self.save_config()

    # ------------------------------------------- microphone test + meter
    def _sensitivity(self):
        """The settings block handed to the microphone helper."""
        return {
            "energy_auto": bool(self.cfg.get("stt_energy_auto", True)),
            "energy_threshold": audiolevel.clamp_threshold(
                self.cfg.get("stt_energy_threshold",
                             audiolevel.THRESHOLD_DEFAULT)),
            "pause_sec": float(self.cfg.get("stt_pause_sec", 0.8) or 0.8),
            "min_phrase_sec": float(
                self.cfg.get("stt_min_phrase_sec", 0.3) or 0.3),
            "phrase_limit": int(self.cfg.get("stt_phrase_limit", 12) or 12),
        }

    def on_mic_tune_expanded(self, on):
        self.set_expanded(self.mic_tune_expander, self.mic_tune_box, on,
                          "Microphone test & sensitivity")
        if not on and self.mic_test.running:
            # closing the panel stops the test: an open microphone the
            # user cannot see is exactly the thing this feature exists
            # to prevent
            self.mic_test_btn.setChecked(False)

    def on_mic_test(self, on):
        if on:
            if not SpeechWorker.available():
                self.mic_test_btn.blockSignals(True)
                self.mic_test_btn.setChecked(False)
                self.mic_test_btn.blockSignals(False)
                self._set_meter_note(missing_dependency(), warn=True)
                return
            if self.stt_recording:
                # The recording already has the microphone open and is
                # already feeding the meter. A second stream on the same
                # device would at best duplicate it and at worst fight it
                # for a raw ALSA card.
                self.mic_test_btn.blockSignals(True)
                self.mic_test_btn.setChecked(False)
                self.mic_test_btn.blockSignals(False)
                self._set_meter_note(
                    "A recording is running \u2013 the bar is already "
                    "showing its input.")
                return
            self._start_mic_test()
        else:
            self.mic_test.stop()
            self.mic_test_btn.setText("\U0001F3A7  Test")
            self._measure_until = 0.0
            self._measure_peak = 0.0
            self.mic_meter.set_idle()
            self._set_meter_note("")
            self._sync_mic_meter()

    def _start_mic_test(self):
        """Resolve the selected entry, then open it in the helper."""
        eid = self.cfg.get("stt_mic", "")
        self.mic_test_btn.setText("\u23F9  Stop")
        self._set_meter_note("Opening the device \u2026")

        def work():
            return resolve_entry(eid, self.log)

        self.run_async(
            work, self._on_mic_test_resolved, interval=120,
            on_error=lambda e: self._on_mic_test_resolved(
                (None, "", f"The device could not be resolved ({e}).")))

    def _on_mic_test_resolved(self, result):
        index, node, note = result
        if not self.mic_test_btn.isChecked():
            return          # switched off while we were resolving
        if index is None:
            self._set_meter_note(note or "The device is not available.",
                                 warn=True)
            self.mic_test_btn.setChecked(False)
            return
        self.mic_test.start(
            mic_index=index, node=node,
            threshold=(0 if self.cfg.get("stt_energy_auto", True)
                       else audiolevel.clamp_threshold(
                           self.cfg.get("stt_energy_threshold"))),
            log=self.log)
        self._set_meter_note("Speak normally \u2013 the bar should clearly "
                             "pass the dashed line.")
        self._sync_mic_meter()

    def on_energy_measure(self):
        """Sample the room for a moment and put the threshold above it.

        Runs through the ordinary test session, so it needs no second
        way of opening a microphone; it just watches the levels for a
        couple of seconds and takes the loudest thing it saw.
        """
        self.cfg["stt_energy_auto"] = False
        self.toggle_energy_auto.blockSignals(True)
        self.toggle_energy_auto.setChecked(False)
        self.toggle_energy_auto.blockSignals(False)
        self._sync_sensitivity_ui()
        self._measure_peak = 0.0
        self._measure_until = time.monotonic() + 3.0
        if not self.mic_test.running:
            self.mic_test_btn.setChecked(True)
        self._set_meter_note("\U0001F4CF Measuring the room \u2013 stay "
                             "quiet for three seconds \u2026")
        self._sync_mic_meter()

    def _finish_measure(self):
        """Threshold = the loudest background moment, with headroom.

        The factor is deliberately generous. A threshold sitting exactly
        on the noise floor triggers on the noise floor - every fan spike
        becomes a phrase, and the recogniser sends an empty string or a
        hallucinated word into the chatbox. Speech is far louder than
        room noise, so there is plenty of room to be safe here.
        """
        self._measure_until = 0.0
        floor = self._measure_peak
        if floor <= 0:
            self._set_meter_note(
                "Nothing was measured \u2013 the device did not deliver "
                "any audio. That usually means the wrong source is "
                "selected.", warn=True)
            return
        value = audiolevel.clamp_threshold(max(floor * 1.8, floor + 120))
        self.cfg["stt_energy_threshold"] = value
        self.save_config()
        self._sync_sensitivity_ui()
        self.log(f"Speech to Text: sensitivity measured \u2013 background "
                 f"peak {floor:.0f}, threshold set to {value}")
        self._set_meter_note(
            f"Threshold set to {value} (background peaked at "
            f"{floor:.0f}). Now say something and check that the bar "
            f"passes the line.")

    def _set_meter_note(self, text, warn=False):
        if not hasattr(self, "mic_meter_lbl"):
            return
        self.mic_meter_lbl.setText(text or "")
        self.mic_meter_lbl.setStyleSheet("color: #d9884a;" if warn else "")

    def _sync_mic_meter(self):
        """Starts the meter timer while something is holding the
        microphone and stops it the rest of the time. A timer running
        against an idle queue is not expensive, but it is a poll on the
        GUI thread twelve times a second for no reason."""
        want = bool(self.stt_recording or self.mic_test.running)
        if want and not self.mic_meter_timer.isActive():
            self.mic_meter.apply_tokens(self.current_theme_tokens())
            self.mic_meter_timer.start(80)
        elif not want and self.mic_meter_timer.isActive():
            self.mic_meter_timer.stop()
            self.mic_meter.set_idle()

    def poll_mic_level(self):
        """One frame of the level bar, from whichever side is live."""
        for kind, payload in self._drain_mic_test():
            if kind == "level":
                rms, peak, threshold = payload
                self._feed_meter(rms, peak, threshold)
            elif kind == "ready":
                if payload:
                    self._set_meter_note(
                        f"\u2705 Recording from: "
                        f"{mic_pactl.describe_source(payload)}")
            elif kind == "error":
                self._set_meter_note(payload, warn=True)
                self.log(f"Speech to Text: microphone test - {payload}")
                self.mic_test_btn.setChecked(False)
            elif kind == "stopped":
                if self.mic_test_btn.isChecked():
                    self.mic_test_btn.setChecked(False)
        if self.stt_recording:
            level = self.stt.latest_level()
            if level is not None:
                self._feed_meter(*level)
        self._sync_mic_meter()

    def _drain_mic_test(self):
        out = []
        while not self.mic_test.messages.empty():
            try:
                out.append(self.mic_test.messages.get_nowait())
            except Exception:      # noqa: BLE001 - queue.Empty
                break
        return out

    def _feed_meter(self, rms, peak, threshold):
        if not self.cfg.get("stt_energy_auto", True):
            # in manual mode the marker is the user's own value, not
            # whatever the recogniser happens to be using
            threshold = audiolevel.clamp_threshold(
                self.cfg.get("stt_energy_threshold"))
        self.mic_meter.set_level(rms, peak, threshold)
        if self._measure_until and time.monotonic() < self._measure_until:
            self._measure_peak = max(self._measure_peak, float(rms))
        elif self._measure_until:
            self._finish_measure()

    # ------------------------------------------------------ sensitivity
    def on_energy_auto(self, on):
        self.cfg["stt_energy_auto"] = bool(on)
        self.save_config()
        self._sync_sensitivity_ui()
        if self.stt_recording:
            self._set_meter_note(
                "Sensitivity changes apply to the next recording \u2013 "
                "stop and start to use them now.")

    def on_energy_threshold(self, value):
        self.cfg["stt_energy_threshold"] = audiolevel.clamp_threshold(value)
        self.save_config_later()
        self.energy_value_lbl.setText(str(self.cfg["stt_energy_threshold"]))
        self.mic_meter.set_threshold(self.cfg["stt_energy_threshold"])

    def on_pause_sec(self, value):
        self.cfg["stt_pause_sec"] = round(float(value), 2)
        self.save_config_later()

    def on_min_phrase_sec(self, value):
        self.cfg["stt_min_phrase_sec"] = round(float(value), 2)
        self.save_config_later()

    def on_phrase_limit(self, value):
        self.cfg["stt_phrase_limit"] = int(value)
        self.save_config_later()

    def on_mic_tune_reset(self):
        self.cfg["stt_energy_auto"] = True
        self.cfg["stt_energy_threshold"] = audiolevel.THRESHOLD_DEFAULT
        self.cfg["stt_pause_sec"] = 0.8
        self.cfg["stt_min_phrase_sec"] = 0.3
        self.cfg["stt_phrase_limit"] = 12
        self.save_config()
        self._sync_sensitivity_ui()
        self._set_meter_note("Sensitivity back to the defaults.")

    def _sync_sensitivity_ui(self):
        """Pushes the config into the widgets without re-triggering their
        handlers. Called on load, after Measure and after Reset."""
        auto = bool(self.cfg.get("stt_energy_auto", True))
        threshold = audiolevel.clamp_threshold(
            self.cfg.get("stt_energy_threshold",
                         audiolevel.THRESHOLD_DEFAULT))
        for widget, value in ((self.toggle_energy_auto, auto),
                              (self.energy_slider, threshold),
                              (self.stt_pause_spin,
                               float(self.cfg.get("stt_pause_sec", 0.8))),
                              (self.stt_min_phrase_spin,
                               float(self.cfg.get("stt_min_phrase_sec",
                                                  0.3))),
                              (self.stt_phrase_limit_spin,
                               int(self.cfg.get("stt_phrase_limit", 12)))):
            widget.blockSignals(True)
            if isinstance(value, bool):
                widget.setChecked(value)
            else:
                widget.setValue(value)
            widget.blockSignals(False)
        self.energy_value_lbl.setText(str(threshold))
        # In automatic mode the slider is not the value in use, so it is
        # disabled rather than left there quietly doing nothing.
        self.energy_row_w.setEnabled(not auto)
        self.mic_meter.set_threshold(0 if auto else threshold)

    def on_tr_test(self):
        """Tests the service shown in the Translation card with a
        short phrase and shows the translation or the EXACT error in
        the hint line – no more guessing why the fallback kicked in."""
        method = self._tr_view_method()
        self.tr_test_btn.setEnabled(False)
        self.tr_method_hint.setText(
            f"\U0001F9EA Testing '{method}' \u2026")
        def work():
            tr = get_translator(
                method,
                deepl_key=self.cfg["stt_deepl_key"],
                libre_url=self.cfg["stt_libre_url"],
                google_key=self.cfg.get("stt_google_key", ""),
                libre_online_url=self.cfg.get("stt_libre_online_url", ""),
                libre_online_key=self.cfg.get("stt_libre_online_key", ""),
                custom_snippet=self.cfg.get("stt_custom_snippet", ""),
                custom_file=self.cfg.get("stt_custom_file", ""))
            out = tr.translate("wie geht es dir", "de", "en")
            return (tr.name, out, tr.last_error)
        self.run_async(work, self._poll_tr_test, interval=300)

    def _poll_tr_test(self, result):
        name, out, err = result
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
        to 'running' once it answers, reports errors if it dies.

        check_ready() does an HTTP request with a 1 s timeout, and this
        runs on a 750 ms timer - i.e. on the GUI thread. While the server
        boots it accepts connections without answering, so the window
        froze for about a second every 750 ms, for as long as the first
        run takes to download its language models. That is minutes.
        The probe therefore goes to a worker thread; the timer only
        schedules it.
        """
        if getattr(self, "_libre_probe_busy", False):
            return
        self._libre_probe_busy = True
        srv = self.libre_server
        self.run_async(
            srv.check_ready, self._on_libre_probe, interval=150,
            on_error=lambda _e: setattr(self, "_libre_probe_busy", False))

    def _on_libre_probe(self, ready):
        self._libre_probe_busy = False
        srv = self.libre_server
        if ready:
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

    def _sync_libre_online_ui(self):
        """Keeps the server dropdown, the custom URL row and the config
        in agreement. The configured value IS the source of truth: an
        empty string means the preset, anything matching a listed server
        selects it, and everything else is a custom URL."""
        url = (self.cfg.get("stt_libre_online_url") or "").strip()
        known = [v for _lbl, v in LIBRE_ONLINE_SERVERS
                 if v != LIBRE_ONLINE_CUSTOM]
        # "Custom" is its own state: an empty custom URL is NOT the
        # preset. Deriving it from the URL alone snapped the dropdown back
        # to the preset the moment Custom was picked (v1.5.1/1.5.2 bug).
        custom_mode = bool(self.cfg.get("stt_libre_online_custom", False))
        if custom_mode or url not in known:
            idx = self.libre_online_combo.findData(LIBRE_ONLINE_CUSTOM)
        else:
            idx = known.index(url)
        self.libre_online_combo.blockSignals(True)
        self.libre_online_combo.setCurrentIndex(idx)
        self.libre_online_combo.blockSignals(False)
        custom = self.libre_online_combo.itemData(idx) == LIBRE_ONLINE_CUSTOM
        self.libre_online_url_row.setVisible(custom)
        if self.libre_online_url_input.text().strip() != url and custom:
            self.libre_online_url_input.blockSignals(True)
            self.libre_online_url_input.setText(url)
            self.libre_online_url_input.blockSignals(False)

    def on_libre_online_server(self, idx):
        val = self.libre_online_combo.itemData(idx)
        if val == LIBRE_ONLINE_CUSTOM:
            # keep whatever is typed in the field; empty is fine, the
            # translator falls back to the preset until something is
            self.cfg["stt_libre_online_custom"] = True
            self.cfg["stt_libre_online_url"] = \
                self.libre_online_url_input.text().strip()
        else:
            self.cfg["stt_libre_online_custom"] = False
            self.cfg["stt_libre_online_url"] = val or ""
        self.save_config()
        self.stt.libre_online_url = self.cfg["stt_libre_online_url"]
        self._sync_libre_online_ui()
        self.log("LibreTranslate Online: server = "
                 + (self.cfg["stt_libre_online_url"]
                    or "community preset (mirrors, automatic)"))
        if val == LIBRE_ONLINE_CUSTOM:
            self.libre_online_url_input.setFocus()

    def on_libre_online_url(self, text):
        self.cfg["stt_libre_online_url"] = text.strip()
        self.save_config_later()
        self.stt.libre_online_url = text.strip()  # applies live

    def on_libre_online_key(self, text):
        self.cfg["stt_libre_online_key"] = text.strip()
        self.save_config_later()
        self.stt.libre_online_key = text.strip()  # applies live

    # ------------------------------------------------ custom translator
    def on_custom_snippet(self):
        text = self.custom_snippet_edit.toPlainText()
        self.cfg["stt_custom_snippet"] = text
        self.save_config_later()
        self.stt.custom_snippet = text   # applies live

    def on_custom_file(self, text):
        self.cfg["stt_custom_file"] = text.strip()
        self.save_config_later()
        self.stt.custom_file = text.strip()

    def on_custom_choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Custom translator: command or Python file", "",
            "Command or script (*.txt *.sh *.cmd *.bat *.py *.curl);;"
            "All files (*)")
        if path:
            self.custom_file_input.setText(path)

    def on_custom_example(self):
        from core.custom_translator import LIBRE_EXAMPLE
        if self.custom_snippet_edit.toPlainText().strip():
            ok = QMessageBox.question(
                self, "Custom translator",
                "Replace the current command with the LibreTranslate "
                "example?")
            if ok != QMessageBox.StandardButton.Yes:
                return
        self.custom_snippet_edit.setPlainText(LIBRE_EXAMPLE)

    def on_libre_url(self, text):
        self.cfg["stt_libre_url"] = text.strip()
        self.save_config_later()
        self.stt.libre_url = text.strip()  # applies live

    def on_google_key(self, text):
        self.cfg["stt_google_key"] = text.strip()
        self.save_config()
        self.stt.google_key = text.strip()  # applies live
        self._update_google_warning()

    def _update_google_warning(self):
        """Own key = official API. No key = shared unofficial endpoint,
        which Google may throttle or block at any time."""
        if self.cfg.get("stt_google_key", "").strip():
            self.google_warn_lbl.setText(
                "\u2705 Own API key \u2013 the official Google Cloud "
                "Translation API is used. Quota and billing are yours; "
                "get a key at console.cloud.google.com (enable the "
                "'Cloud Translation API' for your project).")
            self.google_warn_lbl.setStyleSheet("color:#8bd17c;")
        else:
            self.google_warn_lbl.setText(
                "\u26A0\uFE0F No key \u2013 USE AT YOUR OWN RISK. Without a "
                "key the app falls back to the unofficial endpoint that "
                "the Google Translate website uses. It is not a "
                "documented API and everybody shares it, so Google can "
                "rate-limit or block the requests at any time (HTTP "
                "429), and heavy use may get your IP temporarily "
                "blocked. For reliable use enter your own API key, or "
                "pick LibreTranslate.")
            self.google_warn_lbl.setStyleSheet("color:#e0a33e;")

    def on_deepl_key(self, text):
        self.cfg["stt_deepl_key"] = text
        self.save_config_later()
        self.stt.deepl_key = text  # applies live

    def _sync_stt_availability(self):
        """Enables or disables the whole Speech to Text card in one place,
        so the state cannot drift between the button, the dropdown and the
        status line."""
        ok = SpeechWorker.available()
        self.stt_button.setEnabled(ok)
        self.mic_combo.setEnabled(ok)
        for widget in ("mic_test_btn", "toggle_mic_raw",
                       "toggle_energy_auto", "stt_pause_spin",
                       "stt_min_phrase_spin", "stt_phrase_limit_spin",
                       "energy_measure_btn"):
            w = getattr(self, widget, None)
            if w is not None:
                w.setEnabled(ok)
        if not ok and getattr(self, "mic_test", None) is not None \
                and self.mic_test.running:
            self.mic_test_btn.setChecked(False)
        self.stt_button.setToolTip("" if ok else missing_dependency())
        self.mic_combo.setToolTip("" if ok else missing_dependency())
        # Two things can be missing, and the button now covers both:
        # SpeechRecognition (pure python) and the microphone driver.
        # On Linux the driver traditionally comes from the distribution
        # (python-pyaudio), so only offer to install one when there is
        # none at all - sounddevice is a plain wheel and works anywhere.
        if not has_sr():
            self._stt_install_target = "speech_recognition"
            self.stt_install_btn.setText("\u2B07  Install SpeechRecognition")
            self.stt_install_btn.setVisible(True)
        elif not has_microphone_driver():
            self._stt_install_target = "sounddevice"
            self.stt_install_btn.setText(
                "\u2B07  Install microphone driver (sounddevice)")
            self.stt_install_btn.setVisible(True)
        else:
            self.stt_install_btn.setVisible(False)
        if ok:
            self.stt_status_lbl.setText("")
            self.stt_status_lbl.setStyleSheet("")
        else:
            self.stt_status_lbl.setText(f"\u26A0 {missing_dependency()}")
            self.stt_status_lbl.setStyleSheet("color: #d9884a;")
        return ok

    def on_install_speech(self):
        """Runs pip on a worker thread - it downloads, so it must not
        freeze the window."""
        self.stt_install_btn.setEnabled(False)
        self.stt_install_btn.setText("Installing \u2026")
        target = getattr(self, "_stt_install_target", "speech_recognition")

        def work():
            return pyextras.install(target, self.log)

        self.run_async(work, self._on_speech_installed, interval=250)

    def _on_speech_installed(self, result):
        ok, message = result
        target = getattr(self, "_stt_install_target", "speech_recognition")
        pretty = ("SpeechRecognition" if target == "speech_recognition"
                  else "The microphone driver")
        self.stt_install_btn.setEnabled(True)
        if not ok:
            self.log(f"Speech to Text: install failed - {message}")
            QMessageBox.warning(
                self, "Installation failed",
                f"{pretty} could not be installed:\n\n{message}")
            self._sync_stt_availability()      # restores the button text
            return
        self.log(f"Speech to Text: {message}")
        if target == "speech_recognition":
            reload_sr()
        else:
            # the probe result is cached, so a freshly installed driver
            # would otherwise stay invisible until the next app start
            reload_mic_driver()
        self._fill_mic_combo()
        if self._sync_stt_availability():
            QMessageBox.information(
                self, "Speech to Text ready",
                "SpeechRecognition is installed and Speech to Text is "
                "ready to use.")
        else:
            QMessageBox.information(
                self, "One more step",
                f"{pretty} is installed, but Speech to Text still needs "
                f"something:\n\n{missing_dependency()}")

    def on_stt_toggled(self, on):
        if on:
            if not SpeechWorker.available():
                self._abort_stt_start()
                return
            if getattr(self, "_stt_preflight", 0):
                return          # a start is already being checked
            # Resolving the device touches PortAudio, so it happens on a
            # worker thread and the recording only begins once we know
            # the microphone is actually there. Starting blind is what
            # used to walk straight into a blocking open.
            self._stt_preflight = getattr(self, "_stt_preflight_seq", 0) + 1
            self._stt_preflight_seq = self._stt_preflight
            token = self._stt_preflight
            eid = self.cfg.get("stt_mic", "")
            strict = bool(self.cfg.get("stt_mic_strict", True))
            show_raw = bool(self.cfg.get("stt_mic_show_raw", False))
            self.stt_button.setText("\u23F3  Checking microphone \u2026")
            self.stt_status_lbl.setText(
                "Checking that the microphone is available \u2026")
            self.stt_status_lbl.setStyleSheet("")
            # a test holding the device would be a second stream on it
            if self.mic_test.running:
                self.mic_test_btn.setChecked(False)

            def work():
                # the user just asked for this explicitly, so a previous
                # timeout must not make the attempt fail on the spot
                clear_driver_stuck()
                entries, devices, sources = list_microphone_groups(
                    self.log, force=True, show_raw=show_raw, selected=eid)
                index, node, note = resolve_entry(
                    eid, self.log, devices=devices, sources=sources)
                if index is None and not strict:
                    # not strict: fall back to the system default rather
                    # than refuse - and say so, because a message that
                    # says which device is being used is the difference
                    # between "it works" and "it works, wrongly"
                    self.log(f"Speech to Text: {note} Falling back to the "
                             f"system default.")
                    note = ""
                    index, node = -1, ""
                if index == -1 and not node:
                    # "system default" is the one choice that can be
                    # broken without being missing, so it gets its own
                    # check inside the guard (see default_device_note)
                    note = note or default_device_note(self.log)
                return index, node, note, entries

            self.run_async(
                work,
                lambda res, t=token: self._on_stt_preflight(t, res),
                interval=150,
                on_error=lambda e, t=token: self._on_stt_preflight(
                    t, (None, "", f"Microphone check failed: {e}", None)))
        else:
            self._stt_preflight = 0
            self.stt.stop()
            self.stt_recording = False
            self.stt_timer.stop()
            self.stt_button.setText("\U0001F3A4  Start recording")
            self.log("Speech to Text: recording stopped \u2013 apps resume")
            self._sync_mic_meter()
            self.update_preview()

    def _abort_stt_start(self):
        """Puts the record button back without going through the whole
        stop path - nothing was started yet."""
        self._stt_preflight = 0
        self.stt_recording = False
        self.stt_button.blockSignals(True)
        self.stt_button.setChecked(False)
        self.stt_button.blockSignals(False)
        self.stt_button.setText("\U0001F3A4  Start recording")
        self._sync_mic_meter()

    def _on_stt_preflight(self, token, result):
        """Back on the GUI thread with a device index, or a reason why
        there is none."""
        if token != getattr(self, "_stt_preflight", 0):
            return          # the user already toggled again
        self._stt_preflight = 0
        index, node, note, entries = result
        if entries is not None:
            self._apply_mic_list(entries)
        if note:
            self.log(f"Speech to Text: {note}")
            self.stt_status_lbl.setText(f"\u26A0 {note}")
            self.stt_status_lbl.setStyleSheet("color: #d9884a;")
            self._abort_stt_start()
            return
        if not self.stt_button.isChecked():
            return          # toggled off while we were checking
        self.stt_recording = True
        self.stt_button.setText("\u23F9  Stop recording")
        self.stt_status_lbl.setText("Starting microphone \u2026")
        self.stt_status_lbl.setStyleSheet("")
        self.log(f"Speech to Text: recording started "
                 f"({self.cfg['stt_language']}) \u2013 apps are blocked")
        self.log(f"Speech to Text: microphone = "
                 f"{describe_entry(self.cfg.get('stt_mic', '')) or 'system default'}")
        # Which side of core/mic_host.py we are on. A crash report that
        # says "the app died" and one that says "the helper died" are two
        # completely different bugs, and this line is what tells them
        # apart afterwards.
        self.log(f"Speech to Text: microphone runs {microphone_mode()}")
        self.stt.custom_snippet = self.cfg.get("stt_custom_snippet", "")
        self.stt.custom_file = self.cfg.get("stt_custom_file", "")
        self.stt.start(
            self.cfg["stt_language"], self.cfg["stt_output"],
            self.cfg["stt_method"],
            self.cfg["stt_deepl_key"],
            self.cfg["stt_libre_url"],
            index if index is not None else -1,
            google_key=self.cfg.get("stt_google_key", ""),
            libre_online_url=self.cfg.get("stt_libre_online_url", ""),
            libre_online_key=self.cfg.get("stt_libre_online_key", ""),
            mic_node=node or "",
            sensitivity=self._sensitivity())
        self.stt_timer.start(200)
        self._sync_mic_meter()

    def poll_stt(self):
        while not self.stt.messages.empty():
            kind, payload = self.stt.messages.get_nowait()
            if kind == "text":
                # payload is (source_text, final_text); older single-string
                # payloads stay supported for safety
                if isinstance(payload, (tuple, list)) and len(payload) == 2:
                    source_text, final_text = payload
                else:
                    source_text = final_text = payload
                self.log(f"Speech to Text heard: \"{source_text}\"")
                self._deliver_translation(source_text, final_text, "Speech")
            elif kind == "translating":
                self.show_translating_notice("Speech")
            elif kind == "status":
                self.stt_status_lbl.setText(payload)
            elif kind == "source":
                # what the helper is REALLY attached to, read back out of
                # the audio graph - see mic_host.Session.attached_source()
                pretty = mic_pactl.describe_source(payload) or payload
                self.log(f"Speech to Text: recording from \"{pretty}\"")
                self._set_meter_note(f"\u2705 Recording from: {pretty}")
            elif kind == "error":
                self.stt_status_lbl.setText(payload)
                self.log(f"Speech to Text ERROR: {payload}")
                self.stt_button.setChecked(False)
            elif kind == "stopped":
                if self.stt_button.isChecked():
                    self.stt_button.setChecked(False)

    def on_stt_mode(self, on):
        """Main mode switch: OFF = Speech to Text, ON = Text to Text."""
        self.cfg["stt_mode"] = "ttt" if on else "stt"
        # leaving speech mode while recording -> stop cleanly
        if on and self.stt_button.isChecked():
            self.stt_button.setChecked(False)
        self.save_config()
        self._sync_mode_ui()

    def _sync_mode_ui(self):
        """Shows mic/record widgets in speech mode and the text field in
        text mode. Shared settings (languages, service) stay visible."""
        ttt = self.cfg.get("stt_mode", "stt") == "ttt"
        self.stt_mode_lbl.setText("Text to Text" if ttt else "Speech to Text")
        for w in (self.stt_speech_desc, self.mic_row_w, self.mic_raw_w,
                  self.mic_strict_w, self.mic_tune_w, self.rec_row_w):
            w.setVisible(not ttt)
        if ttt and self.mic_test.running:
            # Text to Text does not use the microphone at all; leaving a
            # test running behind a hidden panel would hold the device
            # open for a card the user cannot even see.
            self.mic_test_btn.setChecked(False)
        if not ttt:
            self._update_mic_raw_hint(None)
        self.stt_text_box.setVisible(ttt)

    def on_translate_notice(self, on):
        self.cfg["stt_translate_notice"] = bool(on)
        self.save_config()

    def on_translate_notice_text(self):
        value = (self.translate_notice_edit.text().strip()
                 or DEFAULT_TRANSLATE_NOTICE)
        if value == self.cfg.get("stt_translate_notice_text"):
            return
        self.cfg["stt_translate_notice_text"] = value
        self.translate_notice_edit.setText(value)
        self.save_config()

    def on_stt_show_both(self, on):
        self.cfg["stt_show_both"] = on
        self.save_config()

    def send_ttt(self):
        """Text-to-Text: run typed text through the same translation
        pipeline + OSC output as speech, without the microphone."""
        text = self.ttt_input.text().strip()
        if not text or self.osc_client is None:
            return
        self.ttt_history.push(text)
        self.ttt_input.clear()
        src = self.cfg.get("stt_language", "de-DE")
        tgt = self.cfg.get("stt_output", "")
        need = bool(tgt) and not src.lower().startswith(
            tgt.lower().split("-")[0])
        if not need:
            self._deliver_translation(text, text, "Text")
            return
        self.stt_status_lbl.setText("Translating \u2026")
        self.show_translating_notice("Text")

        def work():
            tr = translate_with_fallback(
                self.cfg["stt_method"], text, src, tgt,
                deepl_key=self.cfg["stt_deepl_key"],
                libre_url=self.cfg["stt_libre_url"],
                google_key=self.cfg.get("stt_google_key", ""),
                libre_online_url=self.cfg.get("stt_libre_online_url", ""),
                libre_online_key=self.cfg.get("stt_libre_online_key", ""),
                custom_snippet=self.cfg.get("stt_custom_snippet", ""),
                custom_file=self.cfg.get("stt_custom_file", ""))
            return (text, tr)
        self.run_async(work, self._poll_ttt, interval=200)

    def _poll_ttt(self, result):
        source_text, tr = result
        if tr:
            self._deliver_translation(source_text, tr, "Text")
        else:
            self.stt_status_lbl.setText(
                "Translation failed \u2013 sending original")
            self._deliver_translation(source_text, source_text, "Text")

    def show_translating_notice(self, origin):
        """Puts a placeholder in the chatbox while the translation is
        still on its way back.

        A translation is a network call, so between speaking and the
        text appearing there is a gap that the chatbox spends showing
        the previous message - which reads, to everyone else in the
        instance, as nothing happening. This fills the gap instead, and
        goes down the same path as the real message so {text_output} and
        the Line/Variables routes show it too.
        """
        if not self.cfg.get("stt_translate_notice", True):
            return
        notice = str(self.cfg.get("stt_translate_notice_text")
                     or DEFAULT_TRANSLATE_NOTICE)
        self._translating = True
        self.send_manual_text(
            notice, notice,
            ORIGIN_STT if origin == "Speech" else ORIGIN_TTT)

    def _deliver_translation(self, source_text, final_text, origin):
        self._translating = False
        """Sends the message to VRChat. With 'Show original + translation'
        on and an actual translation, both languages go into the chatbox."""
        if (self.cfg.get("stt_show_both")
                and final_text and final_text != source_text):
            out = f"{source_text} \u2192 {final_text}"
        else:
            out = final_text or source_text
        if final_text and final_text != source_text:
            self.notify_next_send()     # "Only on translations / AFK"
        self.log(f"{origin} to Text: sending \"{out}\"")
        self.stt_status_lbl.setText(f"Sent: {out}")
        # source_text is what was typed/spoken, out is what actually goes
        # out. The Variables mode exposes both, and the origin decides
        # whether they answer to {stt_*} or {ttt_*} - {text_*} answers
        # either way.
        self.send_manual_text(
            out, source_text=source_text,
            origin=ORIGIN_STT if origin == "Speech" else ORIGIN_TTT)

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
            self.textbox_history.push(text)
            self.textbox_input.clear()

    # ================================================================
    # chat send mode
    # ================================================================
    def on_stt_send_mode(self, idx):
        """How Speech to Text and Text to Text reach the chatbox."""
        if getattr(self, "_send_mode_syncing", False):
            return
        self.cfg["stt_send_mode"] = (self.stt_mode_combo.itemData(idx)
                                     or CHAT_MODE_DIRECT)
        self.save_config()
        # Leaving a mode that parks text in the payload has to take the
        # text with it, or a line from the old mode would sit in the
        # chatbox with no visible control left to remove it.
        if self.cfg["stt_send_mode"] == CHAT_MODE_DIRECT:
            self.clear_chat_text(quiet=True)
        self._update_chat_mode_ui()
        self.log(f"To Text send mode: {self.cfg['stt_send_mode']}")
        self.update_preview()

    def on_chat_anchor(self, idx):
        self.cfg["chat_anchor"] = (self.chat_anchor_combo.itemData(idx)
                                   or "aio")
        self.save_config()
        self.update_preview()

    def on_chat_hold(self, val):
        self.cfg["chat_hold_sec"] = int(val)
        self.save_config()
        # re-arm against the new duration rather than waiting for the old
        # one to run out first
        if self.chat_text_output:
            self.chat_text_until = (time.time() + val) if val else 0.0
        self.update_preview()

    def _send_opts_label(self):
        """Arrow text of the Send-as expander: shows the active route,
        so it can stay collapsed."""
        mode = self.cfg.get("stt_send_mode", CHAT_MODE_DIRECT)
        name = next((lbl for lbl, val in CHAT_SEND_MODES if val == mode),
                    CHAT_SEND_MODES[0][0])
        return f"Send as: {name}"

    def _update_chat_mode_ui(self):
        mode = self.cfg.get("stt_send_mode", CHAT_MODE_DIRECT)
        exp = getattr(self, "send_opts_expander", None)
        if exp is not None:
            self.set_expanded(exp, self.send_opts_box, exp.isChecked(),
                              self._send_opts_label())
        self.chat_anchor_w.setVisible(mode == CHAT_MODE_LINE)
        self.chat_hold_w.setVisible(mode != CHAT_MODE_DIRECT)
        self.chat_mode_hint.setText(CHAT_MODE_HINTS.get(mode, ""))
        # the Chat card is always Standard now, so its pause always applies
        self.chat_pause_w.setVisible(True)
        combo = getattr(self, "stt_mode_combo", None)
        if combo is not None:
            pos = combo.findData(mode)
            self._send_mode_syncing = True
            try:
                combo.setCurrentIndex(pos if pos >= 0 else 0)
            finally:
                self._send_mode_syncing = False
            self.stt_mode_hint.setText(STT_MODE_HINTS.get(mode, ""))

    def clear_chat_text(self, quiet=False):
        """Drops the parked message. Both modes that keep text around need
        this, and so does switching back to Standard."""
        had = bool(self.chat_text_output)
        self.chat_text_input = ""
        self.chat_text_output = ""
        self.chat_text_origin = ORIGIN_CHAT
        self.chat_text_until = 0.0
        if had and not quiet:
            self.log("Chat: parked message cleared")
        self.update_preview()

    def chat_text_expired(self):
        """True when a parked message has outlived its hold time. Checked
        from build_payload(), so it takes effect on the next frame without
        needing a timer of its own."""
        return bool(self.chat_text_until
                    and time.time() >= self.chat_text_until)

    def _park_chat_text(self, source_text, final_text, origin):
        """Store a message for the Line / Variables modes.

        `origin` is what makes {stt_output} different from {chat_output}:
        one message is parked, and it answers to the names of the source
        it came from plus the source-agnostic {text_*} pair. Keeping one
        slot rather than three is deliberate - the chatbox is 144
        characters, "the last thing I sent" is what people mean, and
        three slots would have to disagree about which one the Line mode
        renders.
        """
        hold = int(self.cfg.get("chat_hold_sec", 0) or 0)
        self.chat_text_input = source_text
        self.chat_text_output = final_text
        self.chat_text_origin = origin
        self.chat_text_until = (time.time() + hold) if hold else 0.0
        self.update_preview()

    def send_manual_text(self, text, source_text=None, origin=ORIGIN_CHAT):
        """The single way a typed or spoken message reaches VRChat.

        Every producer goes through here - the Chat field, the Presets,
        Speech to Text and Text to Text alike. Which route a message
        takes depends on where it came from: typed chat always takes
        over the chatbox, speech and text-to-text follow the "Send as"
        setting on the To Text card.
        """
        if self.osc_client is None:
            return
        # the Chat card always takes over the chatbox; only speech and
        # typed-to-text can be routed somewhere else
        mode = CHAT_MODE_DIRECT if origin == ORIGIN_CHAT else \
            self.cfg.get("stt_send_mode", CHAT_MODE_DIRECT)
        if origin == ORIGIN_TWOWAY:
            # own "Send as" and own slot - see ui/pages/twoway_page.py
            mode = self.cfg.get("stt_twoway_send_mode", CHAT_MODE_VARS)
            if mode != CHAT_MODE_DIRECT:
                self.park_twoway_text(
                    source_text if source_text is not None else text, text)
                self.log(f"Two-way ({mode}): \"{text}\"")
                return
        if mode != CHAT_MODE_DIRECT:
            # Line / Variables: the message joins the normal payload
            # instead of replacing it, so it goes through the ordinary
            # send path (rate limit, slim suffix, preview) rather than
            # firing its own message here.
            self._park_chat_text(source_text if source_text is not None
                                 else text, text, origin)
            self.log(f"{ORIGIN_LABELS.get(origin, 'Chat')} ({mode}): "
                     f"\"{text}\"")
            return
        if self.cfg["slim_chatbox"]:
            text = text[:CHATBOX_LIMIT - len(SLIM_SUFFIX)]
            payload = text + SLIM_SUFFIX
        else:
            payload = text[:CHATBOX_LIMIT]
        try:
            self.osc_client.send_message(
                CHATBOX_INPUT, [payload, True, self.chatbox_notify_flag()])
            self.chatbox_sent()
            pause = self.cfg["textbox_pause_sec"]
            self.manual_pause_until = time.time() + pause
            self.last_manual_text = text
            # what is on screen now is typed, not automatic - "Clear
            # chatbox when there is nothing to send" leaves it alone
            self._auto_text_on_screen = False
            self.log(f"-> MANUAL {CHATBOX_INPUT} \"{text}\" "
                     f"(apps paused for {pause}s)")
            self.update_preview()
            QTimer.singleShot(pause * 1000 + 100, self.update_preview)
        except Exception as e:
            self.log(f"ERROR while sending manual message: {e}")
