"""
ui/pages/textbox_page.py – Textbox page: STT, translation, LibreTranslate, presets, manual send.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.
"""

import time
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)
from core.constants import (
    CHATBOX_INPUT, CHATBOX_LIMIT, CHAT_MODE_DIRECT, CHAT_MODE_LINE,
    CHAT_MODE_VARS, DEFAULT_TRANSLATE_NOTICE, ORIGIN_CHAT, ORIGIN_LABELS, ORIGIN_STT, ORIGIN_TTT,
    SLIM_SUFFIX)
from core.speechtotext import (
    LANGUAGES, OUTPUT_LANGUAGES, SpeechWorker, cached_microphones,
    clear_driver_stuck, default_device_note, driver_stuck, has_sr,
    list_microphones, missing_dependency, reload_sr, resolve_device,
    has_microphone_driver, reload_mic_driver)
from core.plugins import ANCHOR_LABELS
from core import pyextras
from core.constants import EXTRAS_DIR
from core.translators import (
    DEFAULT_LIBRE_ONLINE_URL, DEFAULT_LIBRE_URL, LIBRE_ONLINE_CUSTOM, LIBRE_ONLINE_SERVERS, METHODS as TR_METHODS, METHOD_DEEPL, METHOD_GOOGLE, METHOD_LIBRE, METHOD_LIBRE_ONLINE, METHOD_LINGVA, get_translator, libretranslate_installed, translate_with_fallback)
from ui.ui_main import DragHandle, ToggleLabel, ToggleSwitch


#: where the two paid/keyed backends hand out their API keys. Kept next
#: to the UI that links them rather than in constants.py, because they are
#: third-party account pages, not app identity.
GOOGLE_KEYS_URL = "https://console.cloud.google.com/apis/credentials"
DEEPL_KEYS_URL = "https://www.deepl.com/your-account/keys"

#: The three ways a message can reach the chatbox. Applies to everything
#: that produces text here - the Chat field, the Presets, Speech to Text
#: and Text to Text - so the route is one decision instead of four.
CHAT_SEND_MODES = (
    ("Standard \u2013 message on its own, apps paused", CHAT_MODE_DIRECT),
    ("Line \u2013 as a line inside the normal output", CHAT_MODE_LINE),
    ("Variables \u2013 only {text_input} / {text_output}", CHAT_MODE_VARS),
)

#: The same three, phrased for the To Text card - "the message" there is
#: what you spoke or typed, and the pause/anchor controls live in the
#: Chat card, so the wording points at them instead of repeating them.
STT_MODE_HINTS = {
    CHAT_MODE_DIRECT: (
        "What you speak or type takes over the chatbox on its own and the "
        "apps pause, so nothing overwrites it."),
    CHAT_MODE_LINE: (
        "What you speak or type becomes a line inside the normal output, "
        "at the position set in the Chat card - the apps keep running "
        "around it."),
    CHAT_MODE_VARS: (
        "What you speak or type gets no line of its own; it only fills "
        "the variables below, so an All-in-one string decides where it "
        "goes."),
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
                           "ON = Text to Text (type & translate). Both share "
                           "the same languages, translation service and OSC "
                           "output.")
        mode_hint.setObjectName("dim")
        mode_hint.setWordWrap(True)
        sc.addWidget(mode_hint)
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
        sm_row.addWidget(self.stt_mode_combo, 1)
        sc.addLayout(sm_row)
        sc.addWidget(self.chat_anchor_w)
        sc.addWidget(self.chat_hold_w)
        sc.addWidget(self.chat_mode_hint)
        self.stt_mode_hint = QLabel("")
        self.stt_mode_hint.setObjectName("dim")
        self.stt_mode_hint.setWordWrap(True)
        sc.addWidget(self.stt_mode_hint)

        var_hint = QLabel(
            "Variables: {stt_input} / {stt_output} carry a SPOKEN message, "
            "{ttt_input} / {ttt_output} a typed one, {chat_input} / "
            "{chat_output} one from the Chat card above – and "
            "{text_input} / {text_output} carry whichever of them sent "
            "last. So an All-in-one string can put speech somewhere else "
            "than typing, or style only one of them.")
        var_hint.setObjectName("dim")
        var_hint.setWordWrap(True)
        sc.addWidget(var_hint)

        blk = QLabel("Block apps: while ON, NO app sends anything via OSC "
                     "(Personal Status, MediaPlay, Hardware, AIO) \u2013 "
                     "and, unless you switch them off below, no plugin "
                     "line and no Custom Box frame either. Everything "
                     "stays blocked until you turn it OFF again.")
        blk.setObjectName("dim")
        blk.setWordWrap(True)
        sc.addWidget(blk)

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
            "Block apps switches the four app cards off. These two "
            "extend it to the rest of the output \u2013 and the list "
            "below names what should keep running anyway.")
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
        self.stt_speech_desc = QLabel(
            "Speak into your microphone \u2013 your voice is transcribed "
            "in realtime and sent to the VRChat chatbox. While recording, "
            "all apps (Personal Status, MediaPlay, Hardware, AIO) are "
            "blocked so nothing overwrites your speech.")
        self.stt_speech_desc.setObjectName("dim")
        self.stt_speech_desc.setWordWrap(True)
        sc.addWidget(self.stt_speech_desc)

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
        tr_hint = QLabel("Example: input German, pick English as output \u2013 "
                         "your message gets translated before it is sent "
                         "to VRChat.")
        tr_hint.setObjectName("dim")
        tr_hint.setWordWrap(True)
        sc.addWidget(tr_hint)

        # show original + translation together in the chatbox
        both_row = QHBoxLayout()
        self.toggle_stt_both = ToggleSwitch()
        self.toggle_stt_both.toggled.connect(self.on_stt_show_both)
        both_row.addWidget(self.toggle_stt_both)
        both_row.addWidget(ToggleLabel("Show original + translation",
                                       self.toggle_stt_both))
        both_row.addStretch()
        sc.addLayout(both_row)
        both_hint = QLabel("When ON and a translation happens, the chatbox "
                           "shows both languages as \"source \u2192 translation\".")
        both_hint.setObjectName("dim")
        both_hint.setWordWrap(True)
        sc.addWidget(both_hint)

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
        sc.addLayout(notice_row)
        notice_hint = QLabel(
            "Translating is a network call, so between speaking and the "
            "text arriving the chatbox keeps showing the previous "
            "message \u2013 which reads, to everyone else in the "
            "instance, as nothing happening. With this ON that gap says "
            "so instead. It goes out the same way the message itself "
            "does, so {text_output} and the Line / Variables routes show "
            "it too.")
        notice_hint.setObjectName("dim")
        notice_hint.setWordWrap(True)
        sc.addWidget(notice_hint)

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
            "ON (recommended): if the selected device is gone, recording "
            "refuses to start and says so. OFF: it falls back to the system "
            "default \u2013 which on a machine that just lost an audio "
            "device (leaving VR) is often the device that hangs.")
        strict_hint.setObjectName("dim")
        strict_hint.setWordWrap(True)
        strict_row.addWidget(strict_hint)
        sc.addWidget(self.mic_strict_w)

        # ---- translation method (four-tier system) ----
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
        sc.addWidget(self.google_row)

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
            DEFAULT_LIBRE_ONLINE_URL)
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
        sc.addWidget(self.libre_online_row)

        self.tr_method_hint = QLabel("")
        self.tr_method_hint.setObjectName("dim")
        self.tr_method_hint.setWordWrap(True)
        sc.addWidget(self.tr_method_hint)

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
        ttt_desc = QLabel("Type a message and hit Enter (or Send) \u2013 it goes "
                          "through the same translation and OSC output as speech, "
                          "without using the microphone.")
        ttt_desc.setObjectName("dim")
        ttt_desc.setWordWrap(True)
        tb.addWidget(ttt_desc)
        ttt_row = QHBoxLayout()
        self.ttt_input = QLineEdit()
        self.ttt_input.setPlaceholderText("Type your message \u2026")
        self.ttt_input.setMaxLength(CHATBOX_LIMIT - len(SLIM_SUFFIX))
        self.ttt_input.returnPressed.connect(self.send_ttt)
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
        self._sync_stt_availability()
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
        self.google_row.setVisible(method == METHOD_GOOGLE)
        self.libre_row.setVisible(method == METHOD_LIBRE)
        self.libre_online_row.setVisible(method == METHOD_LIBRE_ONLINE)
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
                "Anonymous Lingva-Translate proxy (lingva.adminforge.de) "
                "\u2013 no API key, no direct Google tracking."),
            METHOD_LIBRE: (
                "Local LibreTranslate instance \u2013 100% offline on "
                "your own PC. Install it yourself once: "
                "pip install libretranslate \u2013 afterwards the "
                "Start/Stop button appears here (default "
                "http://127.0.0.1:5000). If it is not reachable, "
                "Lingva is used as fallback."),
            METHOD_LIBRE_ONLINE: (
                "LibreTranslate on somebody else's server \u2013 nothing "
                "to install, works on Windows and Linux alike. Preset is "
                f"{DEFAULT_LIBRE_ONLINE_URL}; pick \u201cCustom "
                "server\u201d to point it at any other instance. Public "
                "servers rate-limit keyless requests, so add an API key "
                "if you have one. If the server is unreachable, Lingva "
                "is used as fallback."),
            METHOD_DEEPL: (
                "Official DeepL API \u2013 free key at deepl.com (API "
                "Free plan, 500k chars/month); keys ending in ':fx' are "
                "detected as free-plan keys automatically. If DeepL "
                "fails (e.g. monthly limit reached), Lingva is used as "
                "fallback."),
        }
        self.tr_method_hint.setText(hints.get(method, ""))

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
        self._apply_mic_list(cached_microphones(), scanning=True)

        def work():
            return list_microphones(self.log, force=force)

        self.run_async(
            work, self._on_mic_list, interval=150,
            on_error=lambda _e: self._on_mic_list(cached_microphones()))

    def _on_mic_list(self, devices):
        self._mic_scan_busy = False
        self._apply_mic_list(devices or [])
        stuck = driver_stuck()
        if stuck:
            self.stt_status_lbl.setText(
                f"\u26A0 The audio driver is not responding ({stuck}). "
                f"Showing the last known device list \u2013 press \u27F3 "
                f"to try again.")
            self.stt_status_lbl.setStyleSheet("color: #d9884a;")

    def _apply_mic_list(self, devices, scanning=False):
        """Paints the dropdown. GUI thread only, and it never touches
        PortAudio - `devices` is already resolved."""
        want = self.cfg.get("stt_mic", "") if hasattr(self, "cfg") else ""
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        self.mic_combo.addItem(
            "System default" + (" \u2013 scanning \u2026" if scanning else ""),
            "")
        names = set()
        for name, _idx in devices:
            self.mic_combo.addItem(name, name)
            names.add(name)
        # A configured device that is not in the list right now still has
        # to be selectable, or a refresh while VR is off would silently
        # reset the choice to "System default" and the setting would be
        # lost by the time VR comes back.
        if want and want not in names:
            self.mic_combo.addItem(f"{want}  (not available)", want)
        pos = self.mic_combo.findData(want)
        self.mic_combo.setCurrentIndex(pos if pos >= 0 else 0)
        self.mic_combo.blockSignals(False)

    def on_mic_refresh(self):
        """The \u27F3 button. Forces a fresh scan even after a previous
        timeout - the usual fix is on the user's side (plug the device
        back in, restart PipeWire) and the app cannot notice that."""
        clear_driver_stuck()
        self.stt_status_lbl.setText("Scanning for microphones \u2026")
        self.stt_status_lbl.setStyleSheet("")
        self._fill_mic_combo(force=True)

    def on_mic_changed(self, idx):
        self.cfg["stt_mic"] = self.mic_combo.itemData(idx) or ""
        self.save_config()
        self.log("Speech to Text: microphone = "
                 + (self.cfg["stt_mic"] or "system default"))

    def on_mic_strict(self, on):
        self.cfg["stt_mic_strict"] = bool(on)
        self.save_config()

    def on_tr_test(self):
        """Tests the currently selected translation service with a
        short phrase and shows the translation or the EXACT error in
        the hint line – no more guessing why the fallback kicked in."""
        method = self.cfg.get("stt_method", METHOD_LINGVA)
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
                libre_online_key=self.cfg.get("stt_libre_online_key", ""))
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
        idx = (known.index(url) if url in known
               else self.libre_online_combo.count() - 1)
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
            self.cfg["stt_libre_online_url"] = \
                self.libre_online_url_input.text().strip()
        else:
            self.cfg["stt_libre_online_url"] = val or ""
        self.save_config()
        self.stt.libre_online_url = self.cfg["stt_libre_online_url"]
        self._sync_libre_online_ui()
        self.log("LibreTranslate Online: server = "
                 + (self.cfg["stt_libre_online_url"]
                    or f"{DEFAULT_LIBRE_ONLINE_URL} (preset)"))

    def on_libre_online_url(self, text):
        self.cfg["stt_libre_online_url"] = text.strip()
        self.save_config_later()
        self.stt.libre_online_url = text.strip()  # applies live

    def on_libre_online_key(self, text):
        self.cfg["stt_libre_online_key"] = text.strip()
        self.save_config_later()
        self.stt.libre_online_key = text.strip()  # applies live

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
                "pick Lingva / LibreTranslate.")
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
            name = self.cfg.get("stt_mic", "")
            strict = bool(self.cfg.get("stt_mic_strict", True))
            self.stt_button.setText("\u23F3  Checking microphone \u2026")
            self.stt_status_lbl.setText(
                "Checking that the microphone is available \u2026")
            self.stt_status_lbl.setStyleSheet("")

            def work():
                # the user just asked for this explicitly, so a previous
                # timeout must not make the attempt fail on the spot
                clear_driver_stuck()
                if name:
                    devices = list_microphones(self.log, force=True)
                    index, note = resolve_device(name, self.log,
                                                 devices=devices)
                    if index is None and not strict:
                        note = ""
                        index = -1
                    return index, note, devices
                return -1, default_device_note(self.log), None

            self.run_async(
                work,
                lambda res, t=token: self._on_stt_preflight(t, res),
                interval=150,
                on_error=lambda e, t=token: self._on_stt_preflight(
                    t, (None, f"Microphone check failed: {e}", None)))
        else:
            self._stt_preflight = 0
            self.stt.stop()
            self.stt_recording = False
            self.stt_timer.stop()
            self.stt_button.setText("\U0001F3A4  Start recording")
            self.log("Speech to Text: recording stopped \u2013 apps resume")
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

    def _on_stt_preflight(self, token, result):
        """Back on the GUI thread with a device index, or a reason why
        there is none."""
        if token != getattr(self, "_stt_preflight", 0):
            return          # the user already toggled again
        self._stt_preflight = 0
        index, note, devices = result
        if devices is not None:
            self._apply_mic_list(devices)
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
        self.stt.start(
            self.cfg["stt_language"], self.cfg["stt_output"],
            self.cfg["stt_method"],
            self.cfg["stt_deepl_key"],
            self.cfg["stt_libre_url"],
            index if index is not None else -1,
            google_key=self.cfg.get("stt_google_key", ""),
            libre_online_url=self.cfg.get("stt_libre_online_url", ""),
            libre_online_key=self.cfg.get("stt_libre_online_key", ""))
        self.stt_timer.start(200)

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
        for w in (self.stt_speech_desc, self.mic_row_w, self.mic_strict_w,
                  self.rec_row_w):
            w.setVisible(not ttt)
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
                libre_online_key=self.cfg.get("stt_libre_online_key", ""))
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

    def _update_chat_mode_ui(self):
        mode = self.cfg.get("stt_send_mode", CHAT_MODE_DIRECT)
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
