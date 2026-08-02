"""
ui/pages/apps_page.py – Apps page (status / media / hardware / all-in-one) UI + handlers.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.
"""

import random
import re
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)
from core.constants import (
    CHATBOX_LIMIT, LYRICS_DIR, MIN_STATUS_CYCLE_SEC, SLIM_SUFFIX, SONGBAR_LEN, TITLE_MAX_LEN)
from core.osinfo import IS_WINDOWS
# download links for the two optional Windows helpers; harmless to
# import on Linux (the module is pure stdlib) but only used there
from core.backends.wintemp import LHM_DOWNLOAD_URL, RTSS_DOWNLOAD_URL
from core.mediafetch import (
    backend_note as media_backend_note, source_label as media_source_label)
from core.textutils import (
    CUSTOM_STYLE_INDEX, DEFAULT_CUSTOM_BAR, SONGBAR_STYLES, TIME_POSITIONS, TIME_POS_LINE, apply_template, bar_length, compose_bar_line, make_songbar)
from pathlib import Path
from ui.ui_main import DragHandle, ToggleLabel, ToggleSwitch


class AppsPageMixin:
    def build_apps_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("Apps")
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
        # ---- text templates 1-10 (exclusive toggles: enabling one
        #      switches all others off) ----
        tpl_row = QHBoxLayout()
        tpl_row.setSpacing(4)
        tpl_row.addWidget(QLabel("Template:"))
        self.tpl_group = QButtonGroup(self)
        self.tpl_group.setExclusive(True)
        self.tpl_buttons = []
        for i in range(10):
            b = QPushButton(str(i + 1))
            b.setCheckable(True)
            b.setFixedSize(30, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(f"Text template {i + 1} \u2013 own set of "
                         "up to 20 texts")
            b.setStyleSheet(
                "QPushButton { background: #232833; border: 1px solid"
                " #333947; border-radius: 6px; color: #aeb4bf; }"
                "QPushButton:hover { border-color: #5b8dc9; }"
                "QPushButton:checked { background: #5b8dc9;"
                " border-color: #5b8dc9; color: #ffffff; }")
            self.tpl_group.addButton(b, i)
            tpl_row.addWidget(b)
            self.tpl_buttons.append(b)
        tpl_row.addStretch()
        sc.addLayout(tpl_row)
        self.tpl_group.idClicked.connect(self.on_status_template)

        cnt_row = QHBoxLayout()
        cnt_row.addWidget(QLabel("Number of texts"))
        self.status_count_spin = QSpinBox()
        self.status_count_spin.setObjectName("smallspin")
        self.status_count_spin.setRange(1, 20)
        self.status_count_spin.setFixedSize(64, 28)
        self.status_count_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_count_spin.valueChanged.connect(self.on_status_count)
        cnt_row.addWidget(self.status_count_spin)
        cnt_row.addSpacing(16)
        cnt_row.addWidget(QLabel("Change text every"))
        self.status_cycle_spin = QSpinBox()
        self.status_cycle_spin.setObjectName("smallspin")
        # 10 s minimum: below that a line is gone before it can be read,
        # and every switch costs a chatbox send
        self.status_cycle_spin.setRange(MIN_STATUS_CYCLE_SEC, 3600)
        self.status_cycle_spin.setToolTip(
            f"How long each text stays up (at least "
            f"{MIN_STATUS_CYCLE_SEC} seconds)")
        self.status_cycle_spin.setFixedSize(72, 28)
        self.status_cycle_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_cycle_spin.valueChanged.connect(self.on_status_cycle)
        cnt_row.addWidget(self.status_cycle_spin)
        cnt_row.addWidget(QLabel("sec"))
        cnt_row.addStretch()
        sc.addLayout(cnt_row)

        # Live info ({player_in_world} {group_world} {realtime}) moved
        # into the "World Stats" plugin in v1.2.0 – the app no longer reads
        # VRChat's log itself. See the Plugins page.

        # texts fold in/out so the card stays compact
        self.texts_expander = QPushButton("\u25B8  Texts")
        self.texts_expander.setObjectName("expander")
        self.texts_expander.setCursor(Qt.CursorShape.PointingHandCursor)
        self.texts_expander.clicked.connect(self.on_texts_expand)
        sc.addWidget(self.texts_expander)
        self.texts_container = QWidget()
        tc = QVBoxLayout(self.texts_container)
        tc.setContentsMargins(0, 0, 0, 0)
        tc.setSpacing(8)
        self.texts_container.setVisible(False)

        # 20 text fields, visibility follows "Number of texts"
        self.status_rows = []
        self.status_edits = []
        for i in range(20):
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
            tc.addWidget(row_w)
            self.status_rows.append(row_w)
            self.status_edits.append(edit)
        sc.addWidget(self.texts_container)

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
                       "(Spotify, YT Music, browser, any media player – "
                       "via " + media_source_label() + ").")
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
        self.chk_title = QCheckBox("Song title")
        self.chk_time = QCheckBox("Time  (current / total)")
        self.chk_time_seconds = QCheckBox(
            "Time with seconds  (3:27 instead of 0:03)")
        self.chk_lyrics = QCheckBox(
            "Lyrics  (synced line via LRCLIB \u2013 needs internet, "
            "only fetched while checked)")
        self.chk_lyrics_local = QCheckBox(
            "Use my own .lrc files  (local, offline \u2013 matched by "
            "artist/title, takes priority over LRCLIB)")
        self.chk_bar = QCheckBox("Songbar  (progress bar)")
        for chk, key in ((self.chk_artist, "media_show_artist"),
                         (self.chk_title, "media_show_title"),
                         (self.chk_time, "media_show_time"),
                         (self.chk_time_seconds, "media_time_seconds"),
                         (self.chk_lyrics, "media_show_lyrics"),
                         (self.chk_lyrics_local, "media_lyrics_local"),
                         (self.chk_bar, "media_show_bar")):
            chk.toggled.connect(lambda on, k=key: self.on_media_option(k, on))
        # visually sub-options -> indent them
        self.chk_time_seconds.setStyleSheet("margin-left: 24px;")
        self.chk_lyrics_local.setStyleSheet("margin-left: 24px;")

        # title length slider (sub-option of Song title, 3-64 chars)
        self.title_max_row = QWidget()
        tmax = QHBoxLayout(self.title_max_row)
        tmax.setContentsMargins(24, 0, 0, 0)
        tmax.setSpacing(6)
        tmax.addWidget(QLabel("Max length:"))
        self.title_max_slider = QSlider(Qt.Orientation.Horizontal)
        self.title_max_slider.setRange(3, 64)
        self.title_max_slider.setSingleStep(1)
        self.title_max_slider.setPageStep(4)
        self.title_max_slider.setFixedWidth(160)
        self.title_max_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title_max_slider.valueChanged.connect(self.on_title_max)
        tmax.addWidget(self.title_max_slider)
        self.title_max_lbl = QLabel("24 characters")
        self.title_max_lbl.setObjectName("dim")
        self.title_max_lbl.setFixedWidth(96)
        tmax.addWidget(self.title_max_lbl)
        tmax.addStretch()

        # folder row for the local .lrc files (shown only in local mode)
        self.lrc_dir_row = QWidget()
        lrc_row = QHBoxLayout(self.lrc_dir_row)
        lrc_row.setContentsMargins(48, 0, 0, 0)
        lrc_row.setSpacing(6)
        lrc_row.addWidget(QLabel("Folder:"))
        self.lrc_dir_lbl = QLabel("")
        self.lrc_dir_lbl.setObjectName("dim")
        self.lrc_dir_lbl.setWordWrap(True)
        lrc_row.addWidget(self.lrc_dir_lbl, 1)
        lrc_btn = QPushButton("Choose \u2026")
        lrc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lrc_btn.clicked.connect(self.on_choose_lyrics_dir)
        lrc_row.addWidget(lrc_btn)
        open_btn = QPushButton("Open")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self.on_open_lyrics_dir)
        lrc_row.addWidget(open_btn)

        # add everything in the RIGHT order: each sub-option sits directly
        # under the checkbox it belongs to
        mc.addWidget(self.chk_artist)
        mc.addWidget(self.chk_title)
        mc.addWidget(self.title_max_row)
        mc.addWidget(self.chk_time)
        mc.addWidget(self.chk_time_seconds)
        mc.addWidget(self.chk_lyrics)
        mc.addWidget(self.chk_lyrics_local)
        mc.addWidget(self.lrc_dir_row)
        mc.addWidget(self.chk_bar)

        # all songbar options live in one container so they can be shown
        # or hidden together depending on the Songbar checkbox
        self.songbar_box = QWidget()
        sb = QVBoxLayout(self.songbar_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(8)

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
        sb.addLayout(style_row)

        # songbar size: shorter bar = room for the time on the same line
        size_row = QHBoxLayout()
        size_row.setContentsMargins(24, 0, 0, 0)
        size_row.addWidget(QLabel("Songbar size:"))
        self.bar_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.bar_size_slider.setRange(30, 100)
        self.bar_size_slider.setSingleStep(5)
        self.bar_size_slider.setPageStep(10)
        self.bar_size_slider.setFixedWidth(160)
        self.bar_size_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bar_size_slider.valueChanged.connect(self.on_bar_size)
        size_row.addWidget(self.bar_size_slider)
        self.bar_size_lbl = QLabel("100%")
        self.bar_size_lbl.setObjectName("dim")
        self.bar_size_lbl.setFixedWidth(42)
        size_row.addWidget(self.bar_size_lbl)
        size_row.addStretch()
        sb.addLayout(size_row)

        # where the time goes: merging it with the bar keeps the
        # chatbox at two lines instead of three
        tpos_row = QHBoxLayout()
        tpos_row.setContentsMargins(24, 0, 0, 0)
        tpos_row.addWidget(QLabel("Time position:"))
        self.time_pos_combo = QComboBox()
        for label, tid in TIME_POSITIONS:
            self.time_pos_combo.addItem(label, tid)
        self.time_pos_combo.currentIndexChanged.connect(self.on_time_pos)
        tpos_row.addWidget(self.time_pos_combo)
        tpos_row.addStretch()
        sb.addLayout(tpos_row)
        self.bar_line_preview = QLabel("")
        self.bar_line_preview.setObjectName("dim")
        self.bar_line_preview.setContentsMargins(24, 0, 0, 0)
        sb.addWidget(self.bar_line_preview)
        mc.addWidget(self.songbar_box)

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
        m_ph = QLabel("Placeholders: {artist} {title} {time} {time_status} "
                      "{time_end} {position} {length} "
                      "{bar} {lyrics} {player} {icon_sound}  \u2013  use \\n "
                      "for a line break. Values follow the checkboxes above "
                      "({lyrics} needs the Lyrics checkbox).")
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
        # FPS only exists inside the process drawing the frames, so both
        # platforms need a helper - MangoHud on Linux, RTSS on Windows.
        # The row below is the ONLY difference between them.
        self.chk_fps = hw_chk(
            "FPS  (needs RTSS, see below)" if IS_WINDOWS
            else "FPS  (needs MangoHud, see below)", "hw_fps")

        # The label is created on every platform because ui/mainwindow.py
        # writes to it at startup; on Windows it simply never joins a
        # layout, so nothing MangoHud-related is ever shown there.
        self.mangohud_dir_lbl = QLabel("(not set)")
        self.mangohud_dir_lbl.setObjectName("dim")

        if not IS_WINDOWS:
            fps_row = QHBoxLayout()
            fps_row.addSpacing(24)
            fps_row.addWidget(QLabel("MangoHud log folder"))
            fps_row.addWidget(self.mangohud_dir_lbl, 1)
            pick_mh = QPushButton("Choose\u2026")
            pick_mh.setObjectName("linkbtn")
            pick_mh.setFixedHeight(26)
            pick_mh.setCursor(Qt.CursorShape.PointingHandCursor)
            pick_mh.clicked.connect(self.on_choose_mangohud_dir)
            fps_row.addWidget(pick_mh)
            hc.addLayout(fps_row)
            # kept small on purpose: the toggle costs nothing at runtime,
            # the setup note is the only thing people need to see once
            fps_hint = QLabel("\u2139 read via MangoHud \u2013 hover for the "
                              "launch options")
            fps_hint.setToolTip(
                "Linux has no general way to read a game's FPS. MangoHud runs "
                "inside VRChat and can log it.\n\nSteam launch options:\n"
                "MANGOHUD=1 MANGOHUD_CONFIG=output_folder=~/mangohud,"
                "autostart_log=1,log_interval=1000 mangohud %command%\n\n"
                "Then pick that folder above. Polling only reads the last few "
                "lines of the log, so it costs nothing measurable.")
        else:
            # rich text so the word RTSS itself is the link - the button
            # below is for people who do not expect a label to be clickable
            fps_hint = QLabel(
                f'\u2139 read via <a href="{RTSS_DOWNLOAD_URL}" '
                f'style="color:#5b8dc9;">RTSS</a> \u2013 nothing to '
                f'configure, hover for details')
            fps_hint.setTextFormat(Qt.TextFormat.RichText)
            fps_hint.setOpenExternalLinks(True)
            fps_hint.setToolTip(
                "Windows has no general way to read a game's FPS either. "
                "RivaTuner Statistics Server (RTSS) sits inside the game and "
                "publishes the frame rate in shared memory - this app reads "
                "it from there.\n\nRTSS ships with MSI Afterburner and is "
                "what most Windows overlays already use. Install it, leave it "
                "running, and the value appears by itself.\n\nNo folder and "
                "no launch options are needed.")
        fps_hint.setStyleSheet("color: #7a8290; font-size: 11px;")
        fps_hint.setWordWrap(True)
        hint_row = QHBoxLayout()
        hint_row.addSpacing(24)
        hint_row.addWidget(fps_hint, 1)
        hc.addLayout(hint_row)
        if IS_WINDOWS:
            rtss_row = QHBoxLayout()
            rtss_row.addSpacing(24)
            rtss_btn = QPushButton("Download RTSS / MSI Afterburner")
            rtss_btn.setObjectName("linkbtn")
            rtss_btn.setFixedHeight(26)
            rtss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rtss_btn.setToolTip(RTSS_DOWNLOAD_URL)
            rtss_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(RTSS_DOWNLOAD_URL)))
            rtss_row.addWidget(rtss_btn)
            rtss_row.addStretch()
            hc.addLayout(rtss_row)

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
        if IS_WINDOWS:
            hc.addLayout(self._build_wintemp_row())
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

        # ---- AIO template sets 1-10 (exclusive, like Personal Status):
        #      each set keeps its own 5 strings + count, so you can flip
        #      between a gaming, a music and a minimal layout instantly ----
        aset_row = QHBoxLayout()
        aset_row.setSpacing(4)
        aset_row.addWidget(QLabel("Template:"))
        self.aio_set_group = QButtonGroup(self)
        self.aio_set_group.setExclusive(True)
        self.aio_set_buttons = []
        for i in range(10):
            b = QPushButton(str(i + 1))
            b.setCheckable(True)
            b.setFixedSize(30, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(f"AIO template {i + 1} \u2013 own set of up to "
                         "5 strings")
            b.setStyleSheet(
                "QPushButton { background: #232833; border: 1px solid"
                " #333947; border-radius: 6px; color: #aeb4bf; }"
                "QPushButton:hover { border-color: #5b8dc9; }"
                "QPushButton:checked { background: #5b8dc9;"
                " border-color: #5b8dc9; color: #ffffff; }")
            self.aio_set_group.addButton(b, i)
            aset_row.addWidget(b)
            self.aio_set_buttons.append(b)
        aset_row.addStretch()
        ac.addLayout(aset_row)
        self.aio_set_group.idClicked.connect(self.on_aio_set)

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

        a_hint = QLabel("Template 1-10: each button keeps its own set of "
                        "strings \u2013 switch layouts (gaming, music, "
                        "minimal \u2026) with one click, same as the "
                        "Personal Status templates.")
        a_hint.setObjectName("dim")
        a_hint.setWordWrap(True)
        ac.addWidget(a_hint)

        a_ph = QLabel("Placeholders: {text} (current rotating status text), "
                      "{text_1} \u2026 {text_20}, all Hardware placeholders "
                      "({gpu_name} {gpu_usage} {gpu_temp} {temp_icon} {vram_usage} "
                      "{cpu_name} {cpu_usage} {cpu_temp} {ram_usage} {ram_type} "
                      "{icon_flame}) and all MediaPlay placeholders ({artist} "
                      "{title} {time} {time_status} {time_end} {bar} "
                      "{lyrics} {icon_sound} \u2026), plus the live info "
                      "{player_in_world} {group_world} {realtime} "
                      "{instance_type}, plus every active plugin as "
                      "{plugin_id} (see the Plugins page). Use \\n for a "
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

    def on_texts_expand(self):
        """Folds the 20 text fields in/out (keeps the card compact)."""
        show = self.texts_container.isHidden()
        self.texts_container.setVisible(show)
        self._update_texts_expander_label(show)

    def _update_texts_expander_label(self, expanded=None):
        if expanded is None:
            expanded = not self.texts_container.isHidden()
        n = self.cfg["status_count"]
        self.texts_expander.setText(
            ("\u25BE  Hide texts" if expanded
             else f"\u25B8  Texts (1\u2013{n})"))

    def on_status_template(self, idx):
        """Exclusive template toggle: activates template idx (all
        others switch off) and loads its own texts/count."""
        idx = min(9, max(0, int(idx)))
        self.cfg["status_template_active"] = idx
        tpl = self.cfg["status_templates"][idx]
        self.cfg["status_texts"] = list(tpl["texts"])
        self.cfg["status_count"] = tpl["count"]
        self._block_updating = True
        for i, edit in enumerate(self.status_edits):
            edit.setText(self.cfg["status_texts"][i])
        self.status_count_spin.setValue(self.cfg["status_count"])
        self._block_updating = False
        for i, row in enumerate(self.status_rows):
            row.setVisible(i < self.cfg["status_count"])
        self._update_texts_expander_label()
        self.status_index = 0
        self.save_config()
        self.update_preview()
        self.log(f"Personal Status: template {idx + 1} active")

    def _sync_active_template(self):
        """Writes the current texts/count back into the active
        template so every template keeps its own set."""
        tpl = self.cfg["status_templates"][
            self.cfg["status_template_active"]]
        tpl["texts"] = list(self.cfg["status_texts"])
        tpl["count"] = self.cfg["status_count"]

    def on_status_text(self, idx, text):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["status_texts"][idx] = text
        self._sync_active_template()
        self.save_config_later()
        self.update_preview()

    def on_status_count(self, val):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["status_count"] = val
        self._sync_active_template()
        self.save_config()
        for i, row in enumerate(self.status_rows):
            row.setVisible(i < val)
        self._update_texts_expander_label()
        self.status_index = 0
        self.update_timers()
        self.update_preview()

    def on_status_cycle(self, val):
        self.cfg["status_cycle_sec"] = val
        self.save_config()
        self.update_timers()

    def _update_plugin_timer(self):
        """Keeps the preview refreshing while any plugin is active, so
        live values (clocks, world info) don't sit there stale between
        sends. Used to drive the VRChat log watcher too, before that moved
        into the World Stats plugin."""
        if self.plugins.any_active():
            if not self.plugin_timer.isActive():
                self.plugin_timer.start(2000)
        else:
            self.plugin_timer.stop()

    def _render_status(self, text):
        """Renders a status text: only runs the template engine when the
        text actually contains a {placeholder} – so plain texts (incl.
        ones starting with ':3' etc.) are never altered. The values come
        from the active plugins ({world_stats}, {realtime}, ...)."""
        if text and "{" in text:
            return apply_template(text, self.plugins.values())
        return text

    def advance_status(self):
        """Switches to a RANDOM other status text (never the same one
        twice in a row) instead of cycling sequentially."""
        texts = [t.strip() for t in
                 self.cfg["status_texts"][:self.cfg["status_count"]]]
        texts = [t for t in texts if t]
        if len(texts) <= 1:
            return
        current = self.status_index % len(texts)
        choices = [i for i in range(len(texts)) if i != current]
        nxt = random.choice(choices)

        # The new text is only PENDING at this point. The preview must not
        # show anything VRChat is not showing, so the switch is committed
        # by the send itself (see commit_status / send_now). Rotate and
        # send run on independent timers, and sending can also be blocked
        # entirely - by a manual textbox message, for instance - and in
        # that case the preview has to keep standing still too.
        self.pending_status_index = nxt
        if self.sending_live():
            self.send_after_change()
        elif not self.cfg.get("send_active"):
            # SendToVRChat is off, so nothing is going out at all and the
            # preview is a plain preview again - let it rotate
            self.commit_status()
            self.update_preview()
        # else: sending is only paused (manual message, speech to text).
        # The switch stays pending and the preview stands still, so it
        # keeps matching what VRChat is actually showing.

    def commit_status(self):
        """Applies a pending text switch. Called right before a payload is
        built for sending, so preview and VRChat always show the same
        text."""
        if self.pending_status_index is not None:
            self.status_index = self.pending_status_index
            self.pending_status_index = None

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
        self._sync_media_dependents()
        size = min(100, max(30, int(self.cfg.get("media_bar_size", 100))))
        self.cfg["media_bar_size"] = size
        self.bar_size_slider.blockSignals(True)
        self.bar_size_slider.setValue(size)
        self.bar_size_slider.blockSignals(False)
        self.bar_size_lbl.setText(f"{size}%")
        tpos = self.cfg.get("media_time_pos", TIME_POS_LINE)
        tidx = next((i for i in range(self.time_pos_combo.count())
                     if self.time_pos_combo.itemData(i) == tpos), 0)
        self.time_pos_combo.blockSignals(True)
        self.time_pos_combo.setCurrentIndex(tidx)
        self.time_pos_combo.blockSignals(False)
        self._update_bar_custom_preview()
        self._update_bar_line_preview()
        self._update_bar_line_preview()
        self.save_config()
        self.update_preview()

    def _bar_len(self):
        """Songbar length after applying the size slider."""
        return bar_length(self.cfg.get("media_bar_size", 100), SONGBAR_LEN)

    def on_bar_size(self, val):
        self.cfg["media_bar_size"] = int(val)
        self.bar_size_lbl.setText(f"{val}%")
        self._update_bar_custom_preview()
        self._update_bar_line_preview()
        self.save_config_later()
        self.update_preview()

    def on_time_pos(self, idx):
        self.cfg["media_time_pos"] = (self.time_pos_combo.itemData(idx)
                                      or TIME_POS_LINE)
        self._update_bar_line_preview()
        self.save_config()
        self.update_preview()

    def _update_bar_line_preview(self):
        """Shows how bar + time will look together (one line)."""
        try:
            bar = make_songbar(0.4, self.cfg["media_bar_style"],
                               self._bar_len(),
                               self.cfg.get("media_bar_custom"))
            line = compose_bar_line(bar, "0:27", "1:06",
                                    self.cfg.get("media_time_pos",
                                                 TIME_POS_LINE))
            if self.cfg.get("media_time_pos", TIME_POS_LINE) == TIME_POS_LINE:
                txt = (f"Bar line:  {line}   (time stays on the "
                       "artist/title line)")
            else:
                txt = f"Bar line:  {line}   ({len(line)} chars)"
        except Exception:
            txt = ""
        self.bar_line_preview.setText(txt)

    def on_bar_custom(self, key, text):
        custom = dict(DEFAULT_CUSTOM_BAR)
        custom.update(self.cfg.get("media_bar_custom", {}))
        custom[key] = text
        self.cfg["media_bar_custom"] = custom
        self._update_bar_custom_preview()
        self._update_bar_line_preview()
        self.save_config_later()
        self.update_preview()

    def _update_bar_custom_preview(self):
        try:
            bar = make_songbar(0.4, CUSTOM_STYLE_INDEX, self._bar_len(),
                               self.cfg.get("media_bar_custom"))
        except Exception:
            bar = ""
        self.bar_custom_preview.setText(f"Preview:  {bar}")

    def _sync_media_dependents(self):
        """Shows each sub-option only when its parent checkbox is on:
        - Max length  -> only with Song title
        - Time with seconds -> only with Time
        - Use my own .lrc files -> only with Lyrics
        - all Songbar options -> only with Songbar
        The custom songbar editor additionally needs the Custom style."""
        title_on = self.chk_title.isChecked()
        time_on = self.chk_time.isChecked()
        lyrics_on = self.chk_lyrics.isChecked()
        bar_on = self.chk_bar.isChecked()

        self.title_max_row.setVisible(title_on)
        self.chk_time_seconds.setVisible(time_on)
        self.chk_lyrics_local.setVisible(lyrics_on)
        self.songbar_box.setVisible(bar_on)
        is_custom = self.bar_style_combo.currentIndex() == CUSTOM_STYLE_INDEX
        self.bar_custom_box.setVisible(bar_on and is_custom)
        # folder row: only when Lyrics AND "use my own .lrc" are both on
        self._sync_lyrics_local()

    def on_media_option(self, key, on):
        self.cfg[key] = on
        self.save_config()
        if key == "media_lyrics_local":
            self._sync_lyrics_local()
        self._sync_media_dependents()
        self.update_preview()

    def _title_max(self):
        return min(64, max(3, int(self.cfg.get("media_title_max",
                                               TITLE_MAX_LEN))))

    def on_title_max(self, val):
        val = min(64, max(3, int(val)))
        self.cfg["media_title_max"] = val
        self.title_max_lbl.setText(f"{val} characters")
        self.save_config_later()
        self.update_preview()

    def _sync_lyrics_local(self):
        """Pushes the local-.lrc setting into the fetcher and toggles
        the folder row. Creating the default folder is best-effort."""
        on = bool(self.cfg.get("media_lyrics_local"))
        folder = self.cfg.get("media_lyrics_dir") or str(LYRICS_DIR)
        if on:
            try:
                Path(folder).expanduser().mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        self.lyrics.set_local(on, folder)
        if hasattr(self, "lrc_dir_row"):
            self.lrc_dir_row.setVisible(on and self.chk_lyrics.isChecked())
            self.lrc_dir_lbl.setText(folder)

    def on_choose_lyrics_dir(self):
        start = self.cfg.get("media_lyrics_dir") or str(LYRICS_DIR)
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the folder with your .lrc files", start)
        if not folder:
            return
        self.cfg["media_lyrics_dir"] = folder
        self.save_config()
        self._sync_lyrics_local()
        self.log(f"Lyrics: local .lrc folder set to {folder}")
        self.update_preview()

    def on_open_lyrics_dir(self):
        folder = self.cfg.get("media_lyrics_dir") or str(LYRICS_DIR)
        try:
            Path(folder).expanduser().mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

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
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_count"] = val
        self._sync_active_aio_set()
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
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_templates"][idx] = text
        self._sync_active_aio_set()
        self.save_config_later()
        self.update_preview()

    def _sync_active_aio_set(self):
        """Writes the current strings/count back into the active AIO
        template so every set keeps its own layout."""
        sets = self.cfg["aio_sets"]
        idx = min(len(sets) - 1, max(0, self.cfg["aio_set_active"]))
        sets[idx]["templates"] = list(self.cfg["aio_templates"])
        sets[idx]["count"] = self.cfg["aio_count"]

    def on_aio_set(self, idx):
        """Exclusive AIO template toggle: activates set idx and loads its
        own strings/count (all others switch off)."""
        idx = min(9, max(0, int(idx)))
        self.cfg["aio_set_active"] = idx
        tpl = self.cfg["aio_sets"][idx]
        self.cfg["aio_templates"] = list(tpl["templates"])
        self.cfg["aio_count"] = tpl["count"]
        self._block_updating = True
        for i, edit in enumerate(self.aio_edits):
            edit.setText(self.cfg["aio_templates"][i])
        self.aio_count_spin.setValue(self.cfg["aio_count"])
        self._block_updating = False
        for i, row in enumerate(self.aio_rows):
            row.setVisible(i < self.cfg["aio_count"])
        self.aio_index = 0
        self.save_config()
        self.update_timers()
        self.update_preview()
        self.log(f"All in one: template {idx + 1} active")

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
            vals["text"] = self._render_status(
                self.current_status_text()) or None
            for i in range(20):
                vals[f"text_{i + 1}"] = (
                    self._render_status(self.cfg["status_texts"][i].strip())
                    or None)
        else:
            vals["text"] = None
            for i in range(20):
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
        # {<plugin_id>} and {<plugin_id>_<key>} of every active plugin,
        # plus any unprefixed name a plugin claimed (never overwriting
        # a value one of the apps above already produced)
        self.plugins.merge_into(vals)
        text = apply_template(tpl, vals)
        return text.split("\n") if text else []

    def poll_media(self):
        # Linux: D-Bus round-trips can block for a while (many players /
        # slow players). Windows: fetch() only copies a snapshot the GSMTC
        # poller thread already produced, so it is instant there.
        # Either way this stays off the GUI thread via run_async, and a
        # fetch still in flight is skipped so worker threads cannot pile up.
        if getattr(self, "_media_busy", False):
            return
        self._media_busy = True
        self.run_async(self.media.fetch, self._on_media_result)

    def _on_media_result(self, info):
        self._media_busy = False
        changed = (info or {}).get("title") != (self.media_info or {}).get("title")
        self.media_info = info
        if info:
            self.media_status_lbl.setText(
                f"Detected player: {info['player']}"
                f"  ({'playing' if info['playing'] else 'paused'})")
            if changed:
                self.log(f"MediaPlay: now playing \"{info['artist']} – {info['title']}\" "
                         f"({info['player']})")
            # start the lyrics lookup as soon as a (new) song is seen –
            # only when the Lyrics checkbox is on (performance)
            if self.cfg.get("media_show_lyrics"):
                self.lyrics.prefetch(info["artist"], info["title"],
                                     info["length"])
        else:
            # A missing WinRT binding looks exactly like "nothing playing"
            # unless we say so - the backends expose the reason.
            note = getattr(self.media, "status_note", None)
            reason = ""
            try:
                reason = note() if callable(note) else ""
            except Exception:
                reason = ""
            reason = reason or media_backend_note()
            self.media_status_lbl.setText(
                f"No media player detected. {reason}".strip()
                if reason else "No media player detected.")
        self.update_preview()

    def _media_values(self, info):
        """Placeholder values for the custom string. They automatically
        follow the checkboxes above (unchecked -> empty)."""
        c = self.cfg
        t = info["title"]
        tmax = self._title_max()
        if len(t) > tmax:
            # hard cut – no "…" so no chatbox characters are wasted
            t = t[:tmax].rstrip()
        bar = ""
        if info["length"] > 0:
            frac = min(1.0, max(0.0, info["position"] / info["length"]))
            bar = make_songbar(frac, self.cfg["media_bar_style"],
                               self._bar_len(),
                               self.cfg.get("media_bar_custom"))
        # music timer – with seconds (3:27) or h:mm only (0:03),
        # depending on the "Time with seconds" toggle
        ft = self._fmt_media_time
        time_str = (f"{ft(info['position'])}/"
                    f"{ft(info['length'])}"
                    if info["length"] > 0
                    else ft(info["position"]))
        return {
            "artist": info["artist"] if c["media_show_artist"] else None,
            "title": t if c["media_show_title"] else None,
            "position": ft(info["position"]),
            "length": (ft(info["length"])
                       if info["length"] > 0 else None),
            # clearer aliases: where you are / when the song ends
            "time_status": ft(info["position"]),
            "time_end": (ft(info["length"])
                         if info["length"] > 0 else None),
            "time": time_str if c["media_show_time"] else None,
            # {lyrics} only works while the checkbox is checked –
            # unchecked means no LRCLIB requests at all (performance)
            "lyrics": (self.lyrics.current_line(
                           info["artist"], info["title"],
                           info["length"], info["position"])
                       if c.get("media_show_lyrics") else None),
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
            tmax = self._title_max()
            if len(t) > tmax:
                # hard cut – no "…" so no chatbox characters are wasted
                t = t[:tmax].rstrip()
            parts.append(t)
        text = " : ".join(parts)
        tpos = self.cfg.get("media_time_pos", TIME_POS_LINE)
        show_time = self.cfg["media_show_time"] and info["length"] > 0
        show_bar = self.cfg["media_show_bar"] and info["length"] > 0
        # time merged INTO the bar line? only possible if both are shown
        merge = show_time and show_bar and tpos != TIME_POS_LINE
        if show_time and not merge:
            time_str = (f"{self._fmt_media_time(info['position'])}/"
                        f"{self._fmt_media_time(info['length'])}")
            text = f"{text} | {time_str}" if text else time_str
        if text:
            lines.append(text)
        # synced lyrics line (between title/time and the songbar)
        if self.cfg.get("media_show_lyrics"):
            lyr = self.lyrics.current_line(info["artist"], info["title"],
                                           info["length"], info["position"])
            if lyr:
                lines.append(f"\u266a {lyr}")
        if show_bar:
            frac = min(1.0, max(0.0, info["position"] / info["length"]))
            bar = make_songbar(frac, self.cfg["media_bar_style"],
                               self._bar_len(),
                               self.cfg.get("media_bar_custom"))
            if merge:
                bar = compose_bar_line(bar,
                                       self._fmt_media_time(info["position"]),
                                       self._fmt_media_time(info["length"]),
                                       tpos)
            lines.append(bar)
        if lines and self.cfg["media_icon"]:
            lines[0] = f"\U0001F3B5 {lines[0]} \U0001F3B5"
        return lines

    def poll_hw(self):
        # snapshot() shells out to nvidia-smi on NVIDIA systems (a subprocess
        # with a timeout) and reads sysfs on AMD – both must stay off the GUI
        # thread. Skip if a previous snapshot is still running.
        if getattr(self, "_hw_busy", False):
            return
        self._hw_busy = True
        self.run_async(self.hw.snapshot, self._on_hw_result)

    def _on_hw_result(self, info):
        self._hw_busy = False
        self.hw_info = info
        # backends can name themselves; "AMD (sysfs)" is a Linux-only
        # phrase and would be wrong on a Windows machine with a Radeon
        label = getattr(self.hw, "gpu_backend_label", None)
        if not label:
            label = ("NVIDIA (nvidia-smi)" if self.hw.has_nvidia
                     else ("AMD (sysfs)" if self.hw.amd_card
                           else "none detected – GPU values unavailable"))
        self.hw_status_lbl.setText("GPU backend: " + label)
        if IS_WINDOWS:
            self.refresh_wintemp_status()
        self.update_preview()

    def _temp_str(self, t):
        if t is None:
            return None
        return f"{t:.0f}\U0001F525" if self.cfg["hw_flame"] else f"{t:.0f}\u00b0C"

    # ------------------------------------------------- Windows temps
    def _build_wintemp_row(self):
        """Windows only: CPU temperatures need a kernel driver, which no
        unelevated process has. See core/backends/wintemp.py for why."""
        outer = QVBoxLayout()
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.addSpacing(24)
        self.wintemp_btn = QPushButton(
            "Enable advanced temperature monitoring\u2026")
        self.wintemp_btn.setObjectName("linkbtn")
        self.wintemp_btn.setFixedHeight(26)
        self.wintemp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wintemp_btn.setToolTip(
            "Windows does not let any normal program read CPU core "
            "temperatures - they live in registers only kernel-mode code "
            "can touch, and administrator rights alone do not change "
            "that.\n\nThis button starts a small helper with administrator "
            "rights (you will see a UAC prompt) that reads every source "
            "reachable without installing a driver, and hands the values "
            "back to this app.\n\nOn most desktop boards you will also "
            "need LibreHardwareMonitor, which ships the signed driver "
            "Windows requires. The button starts it for you if it is "
            "installed.\n\nNothing is installed and no driver is added by "
            "this app. The helper exits by itself when the chatbox closes.")
        self.wintemp_btn.clicked.connect(self.on_enable_wintemp)
        row.addWidget(self.wintemp_btn)
        row.addStretch()
        outer.addLayout(row)

        hint_row = QHBoxLayout()
        hint_row.addSpacing(24)
        self.wintemp_lbl = QLabel("\u2139 checking\u2026")
        self.wintemp_lbl.setStyleSheet("color: #7a8290; font-size: 11px;")
        self.wintemp_lbl.setWordWrap(True)
        hint_row.addWidget(self.wintemp_lbl, 1)
        outer.addLayout(hint_row)

        # ----- recommended extra software -----
        rec_row = QHBoxLayout()
        rec_row.addSpacing(24)
        rec = QLabel(
            "Recommended extra software: LibreHardwareMonitor (LHM). "
            "Lightweight, open source and uses practically no system "
            "resources, so your performance stays untouched. Inside LHM, "
            "enable Options \u203a Remote Web Server once.")
        rec.setStyleSheet("color: #7a8290; font-size: 11px;")
        rec.setWordWrap(True)
        rec_row.addWidget(rec, 1)
        outer.addLayout(rec_row)

        dl_row = QHBoxLayout()
        dl_row.addSpacing(24)
        lhm_btn = QPushButton("Download LibreHardwareMonitor")
        lhm_btn.setObjectName("linkbtn")
        lhm_btn.setFixedHeight(26)
        lhm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lhm_btn.setToolTip(LHM_DOWNLOAD_URL)
        lhm_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(LHM_DOWNLOAD_URL)))
        dl_row.addWidget(lhm_btn)
        dl_row.addStretch()
        outer.addLayout(dl_row)
        return outer

    def _wintemp_helper(self):
        return getattr(self.hw, "temp_helper", None)

    def refresh_wintemp_status(self):
        """Called after every hardware poll, so the line reflects reality
        instead of whatever was true when the window opened."""
        helper = self._wintemp_helper()
        if helper is None or not hasattr(self, "wintemp_lbl"):
            return
        try:
            state, text = helper.status()
        except Exception as e:
            state, text = "none", f"Temperature helper unavailable ({e})"
        icon = {"active": "\u2714", "starting": "\u23F3"}.get(state, "\u2139")
        self.wintemp_lbl.setText(f"{icon} {text}")
        if hasattr(self, "wintemp_btn"):
            # "starting" keeps the button locked too, otherwise an
            # impatient second click means a second UAC prompt and a
            # second elevated helper process
            self.wintemp_btn.setEnabled(state not in ("active", "starting"))
            self.wintemp_btn.setText(
                {"active": "Temperature monitoring active",
                 "starting": "Starting\u2026"}.get(
                     state, "Enable advanced temperature monitoring\u2026"))

    def on_enable_wintemp(self):
        """Button handler. Pops UAC, so it must stay on the GUI thread."""
        helper = self._wintemp_helper()
        if helper is None:
            self.log("Temps: no helper on this platform.")
            return
        self.wintemp_btn.setEnabled(False)
        self.wintemp_lbl.setText("\u2139 waiting for the UAC prompt\u2026")
        try:
            ok, msg = helper.enable()
        except Exception as e:
            ok, msg = False, f"{type(e).__name__}: {e}"
        self.log(f"Temps: {msg}")
        self.wintemp_lbl.setText(("\u2714 " if ok else "\u26A0 ") + msg)
        # Do NOT simply re-enable here: on success the helper is in its
        # grace period and refresh_wintemp_status() keeps the button
        # locked until a reading arrives. Only a failure gets it back
        # right away, so a declined UAC prompt can be retried.
        self.refresh_wintemp_status()
        if not ok:
            self.wintemp_btn.setEnabled(True)

    def on_choose_mangohud_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "MangoHud log folder",
            self.cfg.get("hw_mangohud_dir") or str(Path.home()))
        if not folder:
            return
        self.cfg["hw_mangohud_dir"] = folder
        self.hw.mangohud_dir = Path(folder)
        self.mangohud_dir_lbl.setText(folder)
        self.save_config()
        self.update_preview()

    def _hw_values(self, info):
        """Placeholder values for the custom string. They automatically
        follow the checkboxes above (unchecked -> empty / generic name)."""
        c = self.cfg
        gpu = info.get("gpu") or {}
        ram = info.get("ram") or {}
        # {fps} stays empty unless the checkbox is on AND MangoHud is
        # actually writing - so a template never shows a stale number
        fps = info.get("fps") if c.get("hw_fps") else None
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
        vals_fps = f"{fps:.0f}" if fps else None
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
            "fps": vals_fps,
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
