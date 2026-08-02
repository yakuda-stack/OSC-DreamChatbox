"""
ui/pages/textbox_page.py – Textbox page: STT, translation, LibreTranslate, presets, manual send.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.
"""

import time
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)
from core.constants import CHATBOX_INPUT, CHATBOX_LIMIT, SLIM_SUFFIX
from core.speechtotext import (
    LANGUAGES, OUTPUT_LANGUAGES, SpeechWorker, has_sr, list_microphones,
    missing_dependency, reload_sr,
    has_microphone_driver, reload_mic_driver)
from core import pyextras
from core.constants import EXTRAS_DIR
from core.translators import (
    DEFAULT_LIBRE_URL, METHODS as TR_METHODS, METHOD_DEEPL, METHOD_GOOGLE, METHOD_LIBRE, METHOD_LINGVA, get_translator, libretranslate_installed, translate_with_fallback)
from ui.ui_main import DragHandle, ToggleLabel, ToggleSwitch


#: where the two paid/keyed backends hand out their API keys. Kept next
#: to the UI that links them rather than in constants.py, because they are
#: third-party account pages, not app identity.
GOOGLE_KEYS_URL = "https://console.cloud.google.com/apis/credentials"
DEEPL_KEYS_URL = "https://www.deepl.com/your-account/keys"


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
        blk = QLabel("Block apps: while ON, NO app sends anything via OSC "
                     "(Personal Status, MediaPlay, Hardware, AIO) \u2013 "
                     "everything stays blocked until you turn it OFF again.")
        blk.setObjectName("dim")
        blk.setWordWrap(True)
        sc.addWidget(blk)
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
        mic_refresh.setToolTip("Refresh microphone list")
        mic_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        mic_refresh.clicked.connect(self._fill_mic_combo)
        mic_row.addWidget(mic_refresh)
        sc.addWidget(self.mic_row_w)

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
        self.google_row.setVisible(method == METHOD_GOOGLE)
        self.libre_row.setVisible(method == METHOD_LIBRE)
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
            METHOD_DEEPL: (
                "Official DeepL API \u2013 free key at deepl.com (API "
                "Free plan, 500k chars/month); keys ending in ':fx' are "
                "detected as free-plan keys automatically. If DeepL "
                "fails (e.g. monthly limit reached), Lingva is used as "
                "fallback."),
        }
        self.tr_method_hint.setText(hints.get(method, ""))

    def _fill_mic_combo(self):
        """(Re)populates the microphone dropdown; keeps the configured
        selection when the device is still present."""
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        self.mic_combo.addItem("System default", "")
        for name, idx in list_microphones(self.log):
            self.mic_combo.addItem(name, name)
        want = self.cfg.get("stt_mic", "") if hasattr(self, "cfg") else ""
        pos = self.mic_combo.findData(want)
        self.mic_combo.setCurrentIndex(pos if pos >= 0 else 0)
        self.mic_combo.blockSignals(False)

    def on_mic_changed(self, idx):
        self.cfg["stt_mic"] = self.mic_combo.itemData(idx) or ""
        self.save_config()
        self.log("Speech to Text: microphone = "
                 + (self.cfg["stt_mic"] or "system default"))

    def _mic_index(self):
        """Resolves the configured microphone NAME to its current
        device index (devices can shift between sessions);
        -1 = system default."""
        name = self.cfg.get("stt_mic", "")
        if not name:
            return -1
        for n, i in list_microphones(self.log):
            if n == name:
                return i
        self.log(f"Speech to Text: microphone '{name}' not found "
                 "\u2013 using system default")
        return -1

    def on_tr_test(self):
        """Tests the currently selected translation service with a
        short phrase and shows the translation or the EXACT error in
        the hint line – no more guessing why the fallback kicked in."""
        method = self.cfg.get("stt_method", METHOD_LINGVA)
        self.tr_test_btn.setEnabled(False)
        self.tr_method_hint.setText(
            f"\U0001F9EA Testing '{method}' \u2026")
        def work():
            tr = get_translator(method,
                                deepl_key=self.cfg["stt_deepl_key"],
                                libre_url=self.cfg["stt_libre_url"],
                                google_key=self.cfg.get("stt_google_key", ""))
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
                           self.cfg["stt_libre_url"],
                           self._mic_index(),
                           google_key=self.cfg.get("stt_google_key", ""))
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
                # payload is (source_text, final_text); older single-string
                # payloads stay supported for safety
                if isinstance(payload, (tuple, list)) and len(payload) == 2:
                    source_text, final_text = payload
                else:
                    source_text = final_text = payload
                self.log(f"Speech to Text heard: \"{source_text}\"")
                self._deliver_translation(source_text, final_text, "Speech")
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
        for w in (self.stt_speech_desc, self.mic_row_w, self.rec_row_w):
            w.setVisible(not ttt)
        self.stt_text_box.setVisible(ttt)

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

        def work():
            tr = translate_with_fallback(
                self.cfg["stt_method"], text, src, tgt,
                deepl_key=self.cfg["stt_deepl_key"],
                libre_url=self.cfg["stt_libre_url"],
                google_key=self.cfg.get("stt_google_key", ""))
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

    def _deliver_translation(self, source_text, final_text, origin):
        """Sends the message to VRChat. With 'Show original + translation'
        on and an actual translation, both languages go into the chatbox."""
        if (self.cfg.get("stt_show_both")
                and final_text and final_text != source_text):
            out = f"{source_text} \u2192 {final_text}"
        else:
            out = final_text or source_text
        self.log(f"{origin} to Text: sending \"{out}\"")
        self.stt_status_lbl.setText(f"Sent: {out}")
        self.send_manual_text(out)

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
