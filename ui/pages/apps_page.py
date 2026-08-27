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
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox,
    QVBoxLayout, QWidget)
from core.constants import (
    AIO_MAX, ORIGINS, ORIGIN_CHAT,
    CHATBOX_LIMIT, LYRICS_DIR, MIN_STATUS_CYCLE_SEC, SLIM_SUFFIX, SONGBAR_LEN, TITLE_MAX_LEN)
from core.osinfo import IS_WINDOWS
from core.boxstyle import SIDE_BOTTOM, SIDE_TOP
from core.hotkeys import HotkeySender
from core.proclaunch import launch as launch_program

try:
    from pythonosc.udp_client import SimpleUDPClient
except ImportError:      # pragma: no cover - python-osc is a hard dep
    SimpleUDPClient = None
# download links for the two optional Windows helpers; harmless to
# import on Linux (the module is pure stdlib) but only used there
from core.backends.wintemp import LHM_DOWNLOAD_URL
from core.mediafetch import (
    backend_note as media_backend_note, source_label as media_source_label,
    player_label)
from core.textstyle import (
    COMPACT_STYLE_CHOICES, DIGIT_STYLE_CHOICES, KEEP_HINT, STYLE_CHOICES, STYLE_NORMAL, apply_style, is_inline_marker, normalize as normalize_style, unsupported as unsupported_chars)
from core.textutils import (
    CUSTOM_STYLE_INDEX, DEFAULT_CUSTOM_BAR, PLACEHOLDER_ALIASES, SONGBAR_STYLES, TIME_POSITIONS, TIME_POS_LINE, apply_template, bar_length, compose_bar_line, finish_template, make_songbar)
from core.nodegraph_eval import (
    evaluate as graph_evaluate, has_output as graph_has_output,
    has_side_effects as graph_has_side_effects, literals as graph_literals,
    run_side_effects as graph_run_side_effects)
from pathlib import Path
from ui.aio_edit import AioTextEdit
from ui.ui_main import DragHandle, ToggleLabel, ToggleSwitch


#: {text_t<X>} and {text_t<X>_<N>} in their canonical spelling - see
#: core.textutils.canonical_placeholder(), which folds {text_template3},
#: {text_tpl3_5} and {text_t03} onto exactly this shape first.
_TEXT_T_RE = re.compile(r"^text_t(\d{1,2})(?:_(\d{1,2}))?$")


class LazyStatusValues(dict):
    """The placeholder dict, with the cross-template names resolved on
    demand instead of materialised.

    Ten templates times twenty slots is 210 extra placeholders. Building
    those into the dict on every single frame - and running the template
    engine over each non-empty one - would be real work done for a
    feature most strings use none of. So the ordinary values stay a plain
    dict and only a lookup that actually asks for {text_t...} costs
    anything.

    Only ``get()`` is extended, which is the single way apply_template
    reads a value. Everything else (``in``, ``[]``, ``update``,
    ``setdefault``) behaves like the plain dict it is, so the plugin
    merge and the rest of the pipeline are untouched.
    """

    resolver = None      # set by _template_values(); a bound method

    def get(self, key, default=None):
        if key in self:
            # a key that IS present wins, even when its value is None -
            # "Personal Status is off" has to stay distinguishable from
            # "nobody has ever heard of this name"
            return dict.get(self, key, default)
        if self.resolver is not None and key.startswith("text_t"):
            value = self.resolver(key)
            if value is not None:
                return value
        return default


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

        # Sits between the count and the interval because that is the
        # order the three settings are read in: how many texts, in what
        # order, how long each one stays. On its own line underneath it
        # read like a setting about the text fields below it instead.
        self.chk_status_random = QCheckBox("Random order")
        self.chk_status_random.setToolTip(
            "On: the next text is picked at random, never the same one "
            "twice in a row.\n\n"
            "Off: the texts run top to bottom and start over - Text 1, "
            "Text 2, Text 3, Text 1 ... Empty fields are skipped either "
            "way, so a gap in the middle does not stall the rotation.")
        self.chk_status_random.toggled.connect(self.on_status_random)
        cnt_row.addWidget(self.chk_status_random)
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

        # ---- how the small-letter styles behave. Sits above the fields
        # because it explains something you have to know BEFORE typing:
        # Unicode has no superscript q and no subscript for half the
        # alphabet, so those letters come through unchanged.
        style_info = QLabel(
            "\u2139 The dropdown behind each text renders it small: "
            "Normal \u00B7 Superscript \u1D34\u1D2C\u1D38\u1D38\u1D3C \u00B7 "
            "Subscript \u2095\u2090\u2097\u2097\u2092 \u2013 same character "
            "count, less height in the chatbox. Not every letter exists in "
            "Unicode (no superscript q, no subscript b c d f g q w y z); "
            "those stay normal. To keep a whole word out of the "
            f"conversion, wrap it: {KEEP_HINT} \u2013 the markers "
            "themselves never reach VRChat.")
        style_info.setStyleSheet("color: #7a8290; font-size: 11px;")
        style_info.setWordWrap(True)
        tc.addWidget(style_info)

        # 20 text fields, visibility follows "Number of texts"
        self.status_rows = []
        self.status_edits = []
        self.status_style_combos = []
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
            combo = self._make_style_combo(
                f"How text {i + 1} is rendered in the chatbox")
            combo.currentIndexChanged.connect(
                lambda _idx, slot=i, cb=combo:
                self.on_status_style(slot, cb.currentData()))
            row.addWidget(combo)
            tc.addWidget(row_w)
            self.status_rows.append(row_w)
            self.status_edits.append(edit)
            self.status_style_combos.append(combo)
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
        mc.setSpacing(4)

        # =============================================================
        #  Live preview
        # =============================================================
        # Sits at the top because it answers the question every setting
        # below it raises: "what will that actually look like?" The old
        # card had checkboxes for artist, title, time, bar, lyrics, an
        # icon and a custom string, and the only way to see the result
        # was the chatbox preview at the bottom of the window - which
        # also carries Status and Hardware, so the media line was never
        # on its own.
        #
        # It renders through build_media_lines(), the same function that
        # produces the real thing, against a stand-in track. Writing a
        # second formatter for the preview would have meant two things
        # that drift apart, and a preview that lies is worse than none.
        mc.addWidget(self._section_header("Preview"))
        self.media_preview_lbl = QLabel("")
        self.media_preview_lbl.setObjectName("minipreview")
        self.media_preview_lbl.setWordWrap(True)
        self.media_preview_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.media_preview_lbl.setToolTip(
            "How the MediaPlay line will look. While something is "
            "actually playing this is your song; otherwise it is a "
            "stand-in track, so the settings can be judged without "
            "starting music first.")
        mc.addWidget(self.media_preview_lbl)
        self.media_preview_note = QLabel("")
        self.media_preview_note.setObjectName("dim")
        mc.addWidget(self.media_preview_note)
        mc.addSpacing(6)

        # =============================================================
        #  Player  -  always open, directly under the preview
        # =============================================================
        # Not foldable, and first, because it is the one thing on this
        # card that decides whether anything appears at all. Everything
        # below is about how the line looks; this is about whether there
        # is a line. Somebody whose chatbox stayed empty should hit this
        # without opening a single section.
        mc.addWidget(self._section_header("Player"))

        pgrid = QGridLayout()
        pgrid.setContentsMargins(0, 0, 0, 0)
        pgrid.setHorizontalSpacing(14)
        pgrid.setVerticalSpacing(4)

        lbl_player = QLabel("Read from")
        lbl_player.setObjectName("dim")
        pgrid.addWidget(lbl_player, 0, 0, 1, 2)
        # The case this is for: Spotify paused in the background and
        # YouTube Music playing in a tab. "First one that says Playing"
        # used to answer that, and the answer moved around between
        # restarts because it depended on bus ordering.
        self.media_source_combo = QComboBox()
        self.media_source_combo.setMinimumWidth(200)
        self.media_source_combo.setToolTip(
            "Which player the song line comes from.\n\nAutomatic picks "
            "whatever is playing - right when only one thing is, "
            "arbitrary when two are.\n\nPick a player and it stays that "
            "player, paused songs included. A player that is closed can "
            "still be selected; it simply has nothing to report until it "
            "is running again.")
        self.media_source_combo.currentIndexChanged.connect(
            self.on_media_source_changed)
        pgrid.addWidget(self.media_source_combo, 1, 0)
        rescan = QPushButton("Rescan")
        rescan.setObjectName("linkbtn")
        rescan.setFixedHeight(28)
        rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan.setToolTip("Look for players that started since this list "
                          "was built.")
        rescan.clicked.connect(lambda: self.refresh_media_sources(force=True))
        pgrid.addWidget(rescan, 1, 1)

        lbl_poll = QLabel("Query every")
        lbl_poll.setObjectName("dim")
        pgrid.addWidget(lbl_poll, 0, 2)
        poll_wrap = QHBoxLayout()
        poll_wrap.setContentsMargins(0, 0, 0, 0)
        poll_wrap.setSpacing(6)
        self.poll_spin = QSpinBox()
        self.poll_spin.setObjectName("smallspin")
        self.poll_spin.setRange(1, 30)
        self.poll_spin.setFixedSize(64, 28)
        self.poll_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poll_spin.valueChanged.connect(self.on_poll_changed)
        poll_wrap.addWidget(self.poll_spin)
        poll_wrap.addWidget(QLabel("sec"))
        poll_holder = QWidget()
        poll_holder.setLayout(poll_wrap)
        pgrid.addWidget(poll_holder, 1, 2)
        pgrid.setColumnStretch(3, 1)
        mc.addLayout(pgrid)

        self.chk_media_fallback = QCheckBox(
            "Fall back to any other player when the chosen one is closed")
        self.chk_media_fallback.setToolTip(
            "On: closing Spotify lets the next player through, so the "
            "line keeps working.\n\nOff: the line means the player you "
            "picked and nothing else - it stays empty while that player "
            "is closed. Only useful with Automatic switched off.")
        self.chk_media_fallback.toggled.connect(
            lambda on: self.on_media_option("media_source_fallback", on))
        mc.addWidget(self.chk_media_fallback)

        self.media_status_lbl = QLabel("")
        self.media_status_lbl.setObjectName("dim")
        self.media_status_lbl.setWordWrap(True)
        mc.addWidget(self.media_status_lbl)

        mc.addSpacing(4)

        # =============================================================
        #  Content   (foldable)
        # =============================================================
        cnt = self._collapsible_section("Content", mc)
        self.content_custom_note = self._mode_note(
            "Custom string is on. These still decide which values exist \u2013 an unticked box leaves its placeholder empty \u2013 they just no longer decide where things go.", cnt)

        self.chk_artist = QCheckBox("Artist")
        self.chk_title = QCheckBox("Song title")
        self.chk_time = QCheckBox("Time  (current / total)")
        self.chk_time_seconds = QCheckBox(
            "With seconds  (3:27 instead of 0:03)")
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

        cnt.addWidget(self.chk_artist)
        cnt.addWidget(self.chk_title)

        # ---- sub-option of Song title -------------------------------
        self.title_max_row, tmax = self._sub_group()
        tmax.addWidget(QLabel("Max length"))
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
        cnt.addWidget(self.title_max_row)

        cnt.addWidget(self.chk_lyrics)

        # ---- sub-options of Lyrics ----------------------------------
        # Three rows that only make sense together, so they share one
        # container and one rule down the left edge.
        self.lyrics_box, lyr = self._sub_group(vertical=True)

        lp_row = QHBoxLayout()
        lp_row.setSpacing(6)
        self.chk_lyrics_prefix = QCheckBox("Symbol before the lyrics line:")
        self.chk_lyrics_prefix.toggled.connect(self.on_lyrics_prefix_on)
        lp_row.addWidget(self.chk_lyrics_prefix)
        self.lyrics_prefix_input = QLineEdit()
        self.lyrics_prefix_input.setMaxLength(4)
        self.lyrics_prefix_input.setFixedWidth(56)
        self.lyrics_prefix_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lyrics_prefix_input.setPlaceholderText("\u266a")
        self.lyrics_prefix_input.setToolTip(
            "Any character or emoji, e.g. \u266a \U0001F3B5 > | - "
            "Leave it empty for no symbol at all.")
        self.lyrics_prefix_input.textChanged.connect(self.on_lyrics_prefix)
        lp_row.addWidget(self.lyrics_prefix_input)
        lp_hint = QLabel("(off = the line starts with the text itself)")
        lp_hint.setObjectName("dim")
        lp_row.addWidget(lp_hint)
        lp_row.addStretch()
        self.lyrics_prefix_row = QWidget()
        self.lyrics_prefix_row.setLayout(lp_row)
        lyr.addWidget(self.lyrics_prefix_row)

        lyr.addWidget(self.chk_lyrics_local)

        self.lrc_dir_row = QWidget()
        lrc_row = QHBoxLayout(self.lrc_dir_row)
        lrc_row.setContentsMargins(20, 0, 0, 0)
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
        lyr.addWidget(self.lrc_dir_row)
        cnt.addWidget(self.lyrics_box)

        # =============================================================
        #  Playback time & progress   (foldable)
        # =============================================================
        pb = self._collapsible_section("Playback time & progress", mc)
        self.playback_custom_note = self._mode_note(
            "Custom string is on. These still decide which values exist \u2013 an unticked box leaves its placeholder empty \u2013 they just no longer decide where things go.", pb)
        pb.addWidget(self.chk_time)

        # ---- sub-options of Time, side by side ----------------------
        # Two settings about the same six characters, so they belong on
        # one line rather than stacked.
        self.time_opts_box, topts = self._sub_group()
        topts.addWidget(self.chk_time_seconds)
        topts.addSpacing(16)
        topts.addWidget(QLabel("Digits"))
        self.time_style_combo = self._make_style_combo(
            "Renders the music timer small to save a line in the chatbox. "
            "Only the digits are converted, so ':' and '/' keep their "
            "normal shape.", DIGIT_STYLE_CHOICES)
        self.time_style_combo.currentIndexChanged.connect(
            lambda _i: self.on_media_time_style(
                self.time_style_combo.currentData()))
        topts.addWidget(self.time_style_combo)
        topts.addStretch()
        pb.addWidget(self.time_opts_box)
        # kept as an alias: _sync_media_dependents() and any other code
        # that grew up around the old name still means this row
        self.time_style_row = self.time_opts_box

        pb.addWidget(self.chk_bar)

        # ---- all songbar options ------------------------------------
        self.songbar_box, sb = self._sub_group(vertical=True)

        # Style, size and time position are three answers to one
        # question - what the bar line looks like - so they share a grid
        # instead of eating three rows each with its own stretch.
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)

        lbl_style = QLabel("Style")
        lbl_style.setObjectName("dim")
        grid.addWidget(lbl_style, 0, 0)
        self.bar_style_combo = QComboBox()
        for preview in SONGBAR_STYLES:
            self.bar_style_combo.addItem(preview)
        self.bar_style_combo.addItem("Custom \u2026")   # own style
        self.bar_style_combo.currentIndexChanged.connect(self.on_bar_style)
        grid.addWidget(self.bar_style_combo, 1, 0)

        lbl_size = QLabel("Size")
        lbl_size.setObjectName("dim")
        grid.addWidget(lbl_size, 0, 1)
        size_wrap = QHBoxLayout()
        size_wrap.setContentsMargins(0, 0, 0, 0)
        size_wrap.setSpacing(6)
        self.bar_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.bar_size_slider.setRange(30, 100)
        self.bar_size_slider.setSingleStep(5)
        self.bar_size_slider.setPageStep(10)
        self.bar_size_slider.setFixedWidth(130)
        self.bar_size_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bar_size_slider.valueChanged.connect(self.on_bar_size)
        size_wrap.addWidget(self.bar_size_slider)
        self.bar_size_lbl = QLabel("100%")
        self.bar_size_lbl.setObjectName("dim")
        self.bar_size_lbl.setFixedWidth(42)
        size_wrap.addWidget(self.bar_size_lbl)
        size_holder = QWidget()
        size_holder.setLayout(size_wrap)
        grid.addWidget(size_holder, 1, 1)

        lbl_tpos = QLabel("Time position")
        lbl_tpos.setObjectName("dim")
        grid.addWidget(lbl_tpos, 0, 2)
        self.time_pos_lbl = lbl_tpos
        self.time_pos_combo = QComboBox()
        for label, tid in TIME_POSITIONS:
            self.time_pos_combo.addItem(label, tid)
        self.time_pos_combo.setToolTip(
            "Merging the time into the bar keeps the chatbox at two "
            "lines instead of three.")
        self.time_pos_combo.currentIndexChanged.connect(self.on_time_pos)
        grid.addWidget(self.time_pos_combo, 1, 2)
        grid.setColumnStretch(3, 1)
        sb.addLayout(grid)

        self.bar_line_preview = QLabel("")
        self.bar_line_preview.setObjectName("dim")
        sb.addWidget(self.bar_line_preview)

        # ---- custom style editor (only with "Custom" selected) ------
        self.bar_custom_box = QWidget()
        cb = QVBoxLayout(self.bar_custom_box)
        cb.setContentsMargins(0, 4, 0, 0)
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
        sb.addWidget(self.bar_custom_box)
        pb.addWidget(self.songbar_box)

        # =============================================================
        #  Styling & custom layout   (foldable)
        # =============================================================
        sty = self._collapsible_section("Styling & custom layout", mc)

        self.chk_media_icon = QCheckBox(
            "Media icon  (\U0001F3B5 before & after the song line)")
        self.chk_media_icon.toggled.connect(
            lambda on: self.on_media_option("media_icon", on))
        sty.addWidget(self.chk_media_icon)

        self.chk_media_idle = QCheckBox(
            "Idle symbol  (show this when nothing is playing)")
        self.chk_media_idle.setToolTip(
            "Without it the MediaPlay line simply disappears between songs, "
            "which on a two-line chatbox looks like the app stopped working. "
            "A single character says \u201cstill here, nothing playing\u201d and "
            "costs one of the 144.")
        self.chk_media_idle.toggled.connect(
            lambda on: self.on_media_option("media_idle", on))
        sty.addWidget(self.chk_media_idle)

        self.media_idle_box, idle = self._sub_group()
        self.media_idle_input = QLineEdit()
        self.media_idle_input.setMaxLength(20)
        self.media_idle_input.setFixedWidth(120)
        self.media_idle_input.setPlaceholderText("\u23F8")
        self.media_idle_input.textChanged.connect(self.on_media_idle_text)
        idle.addWidget(self.media_idle_input)
        m_idle_ico = QPushButton("\U0001F600")
        m_idle_ico.setObjectName("iconbtn")
        m_idle_ico.setFixedSize(30, 30)
        m_idle_ico.setCursor(Qt.CursorShape.PointingHandCursor)
        m_idle_ico.clicked.connect(
            lambda _, e=self.media_idle_input, b=m_idle_ico:
            self.emoji_popup.open_for(e, b))
        idle.addWidget(m_idle_ico)
        idle.addStretch()
        sty.addWidget(self.media_idle_box)

        self.chk_media_custom = QCheckBox(
            "Custom string  (build your own layout)")
        self.chk_media_custom.setToolTip(
            "Replaces everything under Content and Playback time with "
            "your own arrangement. The checkboxes still decide which "
            "values exist - {lyrics} stays empty while Lyrics is off.")
        self.chk_media_custom.toggled.connect(
            lambda on: self.on_media_option("media_custom", on))
        sty.addWidget(self.chk_media_custom)

        # ---- the editor and its legend, together --------------------
        self.media_custom_box, cust = self._sub_group(vertical=True)
        m_custom_row = QHBoxLayout()
        m_custom_row.setContentsMargins(0, 0, 0, 0)
        self.media_custom_input = QLineEdit()
        self.media_custom_input.setMaxLength(200)
        self.media_custom_input.textChanged.connect(self.on_media_template)
        m_custom_row.addWidget(self.media_custom_input, 1)
        m_plus = QPushButton("+")
        m_plus.setObjectName("iconbtn")
        m_plus.setFixedSize(30, 30)
        m_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        m_plus.setToolTip(
            "Insert a MediaPlay placeholder or a formatting tag at the "
            "cursor.\nSelect text first and the formatting entries wrap it.\n"
            "Typing { and a letter or two suggests names directly in the "
            "field.")
        m_plus.clicked.connect(
            lambda _=False, e=self.media_custom_input, b=m_plus:
                self.open_placeholder_menu(e, b, scope="media"))
        m_custom_row.addWidget(m_plus)
        self.attach_placeholder_completer(self.media_custom_input,
                                          scope="media")
        m_ico = QPushButton("\U0001F600")
        m_ico.setObjectName("iconbtn")
        m_ico.setFixedSize(30, 30)
        m_ico.setToolTip("Insert icon")
        m_ico.setCursor(Qt.CursorShape.PointingHandCursor)
        m_ico.clicked.connect(
            lambda _, e=self.media_custom_input, b=m_ico:
            self.emoji_popup.open_for(e, b))
        m_custom_row.addWidget(m_ico)
        cust.addLayout(m_custom_row)

        # The legend used to be a wall of dim text directly on the card,
        # where it competed with the settings around it. In its own box
        # it reads as reference material - there when you look for it,
        # quiet when you are not.
        legend = QFrame()
        legend.setObjectName("infobox")
        lg = QVBoxLayout(legend)
        lg.setContentsMargins(10, 8, 10, 8)
        lg.setSpacing(3)
        lg_title = QLabel("Placeholders")
        lg_title.setObjectName("dim")
        lg_title.setStyleSheet("font-weight: 600;")
        lg.addWidget(lg_title)
        lg_body = QLabel(
            "{artist} {title} {time} {time_status} {time_end} {position} "
            "{length} {bar} {lyrics} {lyrics_prefix} {player} "
            "{icon_sound}")
        lg_body.setObjectName("dim")
        lg_body.setWordWrap(True)
        lg.addWidget(lg_body)
        lg_note = QLabel(
            "\\n makes a line break. Values follow the checkboxes above "
            "\u2013 {lyrics} needs the Lyrics checkbox.")
        lg_note.setObjectName("dim")
        lg_note.setWordWrap(True)
        lg.addWidget(lg_note)
        cust.addWidget(legend)
        sty.addWidget(self.media_custom_box)

        # The player list is rebuilt when the settings are opened rather
        # than on a timer: listing D-Bus once a second for a dropdown
        # nobody is looking at is work for nothing, and a player that
        # started while the panel was open is what Rescan is for.
        self.media_expander = self.make_settings_expander(
            lambda on: (self.set_expanded(self.media_expander,
                                          self.media_content, on),
                        self.refresh_media_sources() if on else None))
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
        hc.setSpacing(8)

        # =============================================================
        #  Components   (2x2 grid of boxes)
        # =============================================================
        # FPS used to live here. It moved into the World Stats plugin in
        # v1.4.4: reading a frame rate means loading something into the
        # game - a Vulkan layer on Linux, RTSS on Windows - and none of
        # that belongs in the same place as /proc and /sys. The plugin
        # owns the layer, its build step and its settings; uninstall the
        # plugin and all of it goes with it.
        hc.addWidget(self._section_header("Components"))

        comp = QGridLayout()
        comp.setContentsMargins(0, 0, 0, 0)
        comp.setHorizontalSpacing(10)
        comp.setVerticalSpacing(10)
        comp.setColumnStretch(0, 1)
        comp.setColumnStretch(1, 1)
        # Boxes in a row share a height, so the grid reads as a grid.
        # VRAM and RAM have less in them than GPU and CPU, which is why
        # they end with a stretch: their content sits at the top of the
        # box rather than floating in the middle of it.

        # ----- GPU -----
        gpu_box, gpu = self._hw_component("GPU")
        (self.chk_gpu_usage, self.chk_gpu_temp,
         self.chk_gpu_power, self.chk_gpu_name) = self._hw_check_grid(gpu, (
             ("Usage", "hw_gpu_usage",
              "The load on the card, e.g. GPU: 27%."),
             ("Temp", "hw_gpu_temp",
              "The card's temperature. Shown as \u00b0C or as a flame - "
              "see Config & formatting below."),
             ("Power draw", "hw_gpu_power",
              "Adds the card's power draw to the GPU line, and fills "
              "{gpu_power} / {gpu_watt} for custom strings.\n\n"
              "NVIDIA always reports it. AMD needs amdgpu's hwmon node, "
              "and on Windows both come from LibreHardwareMonitor. Where "
              "nothing reports a value the line simply stays as it was."),
             ("Name", "hw_gpu_name",
              "The detected card name. Off means the line says GPU."),
         ))
        (self.chk_gpu_custom, self.gpu_custom_input,
         self.gpu_style_combo) = self._hw_name_row(
            gpu, "gpu", "RX 9060 XT / RTX 5060 Ti / \u2026")
        comp.addWidget(gpu_box, 0, 0)

        # ----- VRAM -----
        vram_box, vram = self._hw_component("VRAM")
        (self.chk_vram_used, self.chk_vram_pct) = self._hw_check_grid(vram, (
            ("Numbers", "hw_vram_used", "e.g. 12/16GB"),
            ("Percent", "hw_vram_pct", "e.g. 75%"),
        ))
        vram.addStretch()
        comp.addWidget(vram_box, 0, 1)

        # ----- CPU -----
        cpu_box, cpu = self._hw_component("CPU")
        (self.chk_cpu_usage, self.chk_cpu_temp,
         self.chk_cpu_power, self.chk_cpu_name) = self._hw_check_grid(cpu, (
             ("Usage", "hw_cpu_usage",
              "The load across all cores, e.g. CPU: 27%."),
             ("Temp", "hw_cpu_temp",
              "The package temperature. Shown as \u00b0C or as a flame - "
              "see Config & formatting below."),
             ("Power draw", "hw_cpu_power",
              "Adds the package power to the CPU line, and fills "
              "{cpu_power} / {cpu_watt} for custom strings.\n\n"
              "Needs zenpower or readable RAPL counters on Linux, and "
              "LibreHardwareMonitor on Windows. Where nothing reports a "
              "value the line simply stays as it was."),
             ("Name", "hw_cpu_name",
              "The detected processor name. Off means the line says CPU."),
         ))
        (self.chk_cpu_custom, self.cpu_custom_input,
         self.cpu_style_combo) = self._hw_name_row(
            cpu, "cpu", "Ryzen 7 9700X / i7 12700K / \u2026")
        comp.addWidget(cpu_box, 1, 0)

        # ----- RAM -----
        ram_box, ram = self._hw_component("RAM")
        (self.chk_ram_used, self.chk_ram_pct) = self._hw_check_grid(ram, (
            ("Numbers", "hw_ram_used", "e.g. 12/32GB"),
            ("Percent", "hw_ram_pct", "e.g. 38%"),
        ))
        ramtype_box, ramtype = self._sub_group()
        rt_lbl = QLabel("Type")
        rt_lbl.setObjectName("dim")
        ramtype.addWidget(rt_lbl)
        self.ram_type_input = QLineEdit()
        self.ram_type_input.setPlaceholderText("DDR5")
        self.ram_type_input.setMaxLength(10)
        self.ram_type_input.setFixedWidth(88)
        self.ram_type_input.setToolTip(
            "Optional. Nothing can detect the memory generation without "
            "reading SPD as root, so it is yours to type or leave empty. "
            "Fills {ram_type}.")
        self.ram_type_input.textChanged.connect(
            lambda t: self.on_hw_text("hw_ram_type", t))
        ramtype.addWidget(self.ram_type_input)
        ramtype.addStretch()
        ram.addWidget(ramtype_box)
        comp.addWidget(ram_box, 1, 1)

        # Equal stretch alone does not give equal columns: it splits the
        # *spare* room evenly on top of each column's own minimum, and
        # GPU's minimum (a text field plus a dropdown on one row) is far
        # larger than VRAM's two checkboxes. Giving both columns the
        # larger minimum makes the spare room the only difference, which
        # is none. Below that width the page scrolls, like every other
        # card here.
        # minimumSizeHint, not sizeHint: the preferred width of a box
        # containing a text field is "as wide as you like", and using it
        # as a floor puts a horizontal scrollbar under a 1024px window.
        for box in (gpu_box, vram_box, cpu_box, ram_box):
            # minimumSizeHint is computed from the child widgets' fonts,
            # and those are not resolved until the widget is polished.
            # Asking first gives an answer that is a dozen pixels short,
            # which is exactly enough to un-equalise the columns again.
            box.ensurePolished()
        floor = max(box.minimumSizeHint().width()
                    for box in (gpu_box, vram_box, cpu_box, ram_box))
        for box in (gpu_box, vram_box, cpu_box, ram_box):
            box.setMinimumWidth(floor)
        comp.setColumnMinimumWidth(0, floor)
        comp.setColumnMinimumWidth(1, floor)

        hc.addLayout(comp)

        # The Windows temperature helper is about the CPU but is three
        # paragraphs of explanation, a button and a status line. In a
        # half-width box it would be a column of two-word lines, so it
        # gets the full width underneath the grid instead.
        if IS_WINDOWS:
            hc.addLayout(self._build_wintemp_row(indent=0))

        # =============================================================
        #  Custom string   (foldable help)
        # =============================================================
        hc.addWidget(self._section_header("Custom string"))

        self.chk_hw_custom = QCheckBox("Build my own layout")
        self.chk_hw_custom.setToolTip(
            "Replaces the generated hardware line with your own "
            "arrangement. The checkboxes above still decide which values "
            "exist - {gpu_temp} stays empty while Temperature is off.")
        self.chk_hw_custom.toggled.connect(
            lambda on: self.on_hw_option("hw_custom", on))
        hc.addWidget(self.chk_hw_custom)

        self.hw_custom_box, hwc = self._sub_group(vertical=True)
        hw_custom_row = QHBoxLayout()
        hw_custom_row.setContentsMargins(0, 0, 0, 0)
        self.hw_custom_input = QLineEdit()
        self.hw_custom_input.setMaxLength(200)
        self.hw_custom_input.textChanged.connect(
            lambda t: self.on_hw_text("hw_custom_template", t))
        hw_custom_row.addWidget(self.hw_custom_input, 1)
        hw_plus = QPushButton("+")
        hw_plus.setObjectName("iconbtn")
        hw_plus.setFixedSize(30, 30)
        hw_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        hw_plus.setToolTip(
            "Insert a hardware placeholder or a formatting tag at the "
            "cursor.\nSelect text first and the formatting entries wrap it.\n"
            "Typing { and a letter or two suggests names directly in the "
            "field.")
        hw_plus.clicked.connect(
            lambda _=False, e=self.hw_custom_input, b=hw_plus:
                self.open_placeholder_menu(e, b, scope="hardware"))
        hw_custom_row.addWidget(hw_plus)
        self.attach_placeholder_completer(self.hw_custom_input,
                                          scope="hardware")
        hw_ico = QPushButton("\U0001F600")
        hw_ico.setObjectName("iconbtn")
        hw_ico.setFixedSize(30, 30)
        hw_ico.setToolTip("Insert icon")
        hw_ico.setCursor(Qt.CursorShape.PointingHandCursor)
        hw_ico.clicked.connect(
            lambda _, e=self.hw_custom_input, b=hw_ico:
                self.emoji_popup.open_for(e, b))
        hw_custom_row.addWidget(hw_ico)
        hwc.addLayout(hw_custom_row)

        # Two paragraphs of reference text used to sit here in dim grey,
        # permanently, competing with the settings around them. Folded
        # away they are reference material: there when you go looking,
        # quiet when you are not.
        help_body = self._collapsible_section(
            "Placeholders & text styles", hwc)
        legend = QFrame()
        legend.setObjectName("infobox")
        lg = QVBoxLayout(legend)
        lg.setContentsMargins(10, 8, 10, 8)
        lg.setSpacing(6)
        for heading, body in (
            ("Placeholders",
             "{gpu_name} {gpu_usage} {gpu_temp} {gpu_power} {vram_usage} "
             "{cpu_name} {cpu_usage} {cpu_temp} {cpu_power} {ram_usage} "
             "{ram_type} {icon_flame} {temp_icon}"),
            ("Line breaks",
             "\\n starts a new line. Values follow the checkboxes above: "
             "unchecked is empty, and a name left unchecked comes out as "
             "GPU or CPU."),
            ("Small text",
             "Wrap any part in {super/\"word\"} or {sub/\"word\"} to shrink "
             "it. GPU {gpu_usage} {super/\"vram\"} {vram_usage} comes out "
             "as GPU 68% \u2CFD\u1D3F\u1D2C\u1D39 9.1G. A placeholder works "
             "inside one too: {super/{cpu_temp}}."),
            ("What will not shrink",
             "Unicode has no small form for every letter - superscript is "
             "missing q, subscript about half the alphabet. Those "
             "characters pass through at full size."),
        ):
            h = QLabel(heading)
            h.setObjectName("dim")
            h.setStyleSheet("font-weight: 600;")
            lg.addWidget(h)
            b = QLabel(body)
            b.setObjectName("dim")
            b.setWordWrap(True)
            lg.addWidget(b)
        help_body.addWidget(legend)
        hc.addWidget(self.hw_custom_box)

        # =============================================================
        #  Config & formatting
        # =============================================================
        hc.addWidget(self._section_header("Config & formatting"))

        self.chk_hw_flame = QCheckBox(
            "Flame icon for temps  (62\U0001F525 instead of 62\u00b0C)")
        self.chk_hw_flame.setToolTip(
            "Applies to both temperatures, and to {temp_icon} in a custom "
            "string. Saves one character per temperature.")
        self.chk_hw_flame.toggled.connect(
            lambda on: self.on_hw_option("hw_flame", on))
        hc.addWidget(self.chk_hw_flame)

        hpoll_row = QHBoxLayout()
        hpoll_row.addWidget(QLabel("Query hardware every"))
        self.hw_poll_spin = QSpinBox()
        self.hw_poll_spin.setObjectName("smallspin")
        self.hw_poll_spin.setRange(1, 60)
        self.hw_poll_spin.setFixedSize(64, 28)
        self.hw_poll_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hw_poll_spin.setToolTip(
            "How often /proc, /sys and the GPU are read. The chatbox "
            "sends on its own schedule; this only decides how fresh the "
            "numbers are when it does.")
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

        # ---- mode switch: the five template strings, or the node canvas
        #      on the Advanced page. Two buttons rather than a combo box
        #      because this is the first thing in the card and it decides
        #      what the rest of it looks like - that should be readable
        #      at a glance, not one click deep.
        amode_row = QHBoxLayout()
        amode_row.setSpacing(6)
        amode_row.addWidget(QLabel("Mode:"))
        self.aio_mode_group = QButtonGroup(self)
        self.aio_mode_group.setExclusive(True)
        self.aio_mode_buttons = {}
        for key, label, tip in (
                ("normal", "Normal mode",
                 "Write the AIO strings by hand, with placeholders."),
                ("advanced", "Advanced mode",
                 "Build the string visually on the node canvas "
                 "(\u201cAdvanced\u201d in the sidebar).")):
            b = QPushButton(label)
            b.setObjectName("modebtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            self.aio_mode_group.addButton(b)
            amode_row.addWidget(b)
            self.aio_mode_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.on_aio_mode(k))
        amode_row.addStretch()
        a_layout.addLayout(amode_row)

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
                         f"{AIO_MAX} strings")
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
        self.aio_count_spin.setRange(1, AIO_MAX)
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
        self.aio_time_checks = []
        self.aio_time_spins = []
        top = Qt.AlignmentFlag.AlignTop
        for i in range(AIO_MAX):
            row_w = QWidget()
            row_v = QVBoxLayout(row_w)
            row_v.setContentsMargins(0, 0, 0, 0)
            row_v.setSpacing(4)

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            lbl = QLabel(f"AIO {i + 1}:")
            lbl.setFixedWidth(48)
            row.addWidget(lbl, 0, top)
            # multi-line since v1.3.3: three rows to start with, grows
            # with the text, and Shift+Enter writes the \n the template
            # language wants. See ui/aio_edit.py.
            edit = AioTextEdit()
            edit.setPlaceholderText(
                "{text}\nShift+Enter = new line \u2026")
            edit.setMaxLength(300)
            edit.setToolTip(
                "Shift+Enter (or Ctrl+Enter) starts a new chatbox line \u2013 "
                "stored as \\n.\nDrag the bottom edge to set the height, "
                "double-click it to grow with the text again.\n"
                "Type { and a letter or two for a suggestion list; the \"+\" "
                "opens the full menu with a search line.")
            edit.valueChanged.connect(
                lambda t, idx=i: self.on_aio_text(idx, t))
            edit.heightChanged.connect(
                lambda px, idx=i: self.on_aio_height(idx, px))
            row.addWidget(edit, 1)
            a_plus = QPushButton("+")
            a_plus.setObjectName("iconbtn")
            a_plus.setFixedSize(30, 30)
            a_plus.setCursor(Qt.CursorShape.PointingHandCursor)
            a_plus.setToolTip(
                "Insert a placeholder or a formatting tag at the cursor.\n"
                "Select text first and the formatting entries wrap it.")
            a_plus.clicked.connect(
                lambda _=False, e=edit, b=a_plus:
                    self.open_placeholder_menu(e, b))
            row.addWidget(a_plus, 0, top)
            # the same vocabulary without opening the menu: "{gpu" and
            # the list is under the cursor
            self.attach_placeholder_completer(edit)
            a_ico = QPushButton("\U0001F600")
            a_ico.setObjectName("iconbtn")
            a_ico.setFixedSize(30, 30)
            a_ico.setCursor(Qt.CursorShape.PointingHandCursor)
            a_ico.clicked.connect(
                lambda _, e=edit, b=a_ico: self.emoji_popup.open_for(e, b))
            row.addWidget(a_ico, 0, top)
            row_v.addLayout(row)

            # ---- per-string dwell time: this one string overrides the
            #      shared "Rotate strings every N sec" while it is on
            #      screen; the next one is back to the shared value
            #      unless it carries its own.
            trow = QHBoxLayout()
            trow.setContentsMargins(48 + 6, 0, 0, 0)
            trow.setSpacing(6)
            chk_time = QCheckBox("Custom time")
            chk_time.setToolTip(
                "Give this string its own time on screen instead of the "
                "shared rotation interval.\nOnly this string is "
                "affected \u2013 the others keep the shared value.")
            chk_time.toggled.connect(
                lambda on, idx=i: self.on_aio_custom_time(idx, on))
            trow.addWidget(chk_time)
            spin_time = QSpinBox()
            spin_time.setObjectName("smallspin")
            spin_time.setRange(2, 3600)
            spin_time.setFixedSize(72, 26)
            spin_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin_time.valueChanged.connect(
                lambda val, idx=i: self.on_aio_custom_sec(idx, val))
            trow.addWidget(spin_time)
            sec_lbl = QLabel("sec")
            sec_lbl.setObjectName("dim")
            trow.addWidget(sec_lbl)
            trow.addStretch()
            row_v.addLayout(trow)

            ac.addWidget(row_w)
            self.aio_rows.append(row_w)
            self.aio_edits.append(edit)
            self.aio_time_checks.append(chk_time)
            self.aio_time_spins.append(spin_time)

        a_hint = QLabel("Template 1-10: each button keeps its own set of "
                        "strings \u2013 switch layouts (gaming, music, "
                        "minimal \u2026) with one click, same as the "
                        "Personal Status templates.")
        a_hint.setObjectName("dim")
        a_hint.setWordWrap(True)
        ac.addWidget(a_hint)

        a_ph = QLabel("Everything the apps, the live info, the Custom Box "
                      "and your plugins produce can be used here as a "
                      "placeholder \u2013 the full list is under "
                      "\u201cParameters\u201d below. Shift+Enter starts a "
                      "new chatbox line (written as \\n), and dragging the "
                      "bottom edge of a field sets its height. "
                      "\u201cCustom time\u201d gives that one string its "
                      "own time on screen instead of the shared rotation "
                      "interval. The apps must be Active for their values "
                      "to fill in.")
        a_ph.setObjectName("dim")
        a_ph.setWordWrap(True)
        ac.addWidget(a_ph)

        self.aio_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.aio_expander, self.aio_content, on))
        ab_layout.addWidget(self.aio_expander)
        ab_layout.addWidget(self.aio_content)
        self.aio_content.setVisible(False)

        # ---- Parameters: the whole placeholder vocabulary, on demand ---
        # Its own expander below Settings, because it is a reference list
        # and not a setting - and because nobody should have to walk over
        # to the Plugins page to find out what a plugin is called.
        self.aio_param_content = QWidget()
        self.aio_param_layout = QVBoxLayout(self.aio_param_content)
        self.aio_param_layout.setContentsMargins(14, 4, 14, 12)
        self.aio_param_layout.setSpacing(10)
        self.aio_param_expander = self.make_settings_expander(
            self._on_aio_params_toggled, "Parameters")
        ab_layout.addWidget(self.aio_param_expander)
        ab_layout.addWidget(self.aio_param_content)
        self.aio_param_content.setVisible(False)
        self.register_parameter_list(self.aio_param_layout)

        a_layout.addWidget(abox)
        # everything above lives in here so Advanced mode can hide the
        # whole normal UI in one go - the strings stay in the config
        # untouched, this only takes them off screen
        self.aio_normal_box = abox

        # ---- what Advanced mode shows instead --------------------------
        self.aio_advanced_box = QFrame()
        self.aio_advanced_box.setObjectName("innerbox")
        adv_layout = QVBoxLayout(self.aio_advanced_box)
        adv_layout.setContentsMargins(14, 14, 14, 14)
        adv_layout.setSpacing(10)
        adv_hint = QLabel(
            "Advanced mode is on \u2013 the AIO string is built on the "
            "node canvas instead of in the fields here. Your typed "
            "strings are kept and come back when you switch to Normal "
            "mode.")
        adv_hint.setObjectName("dim")
        adv_hint.setWordWrap(True)
        adv_layout.addWidget(adv_hint)
        goto_row = QHBoxLayout()
        self.aio_goto_btn = QPushButton("Go to Advanced mode  \u203A")
        self.aio_goto_btn.setObjectName("sendbtn")
        self.aio_goto_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.aio_goto_btn.setMinimumHeight(34)
        self.aio_goto_btn.clicked.connect(
            lambda: self.switch_page(self.PAGE_ADVANCED))
        goto_row.addWidget(self.aio_goto_btn)
        goto_row.addStretch()
        adv_layout.addLayout(goto_row)
        a_layout.addWidget(self.aio_advanced_box)
        self.aio_advanced_box.setVisible(False)

        # add the cards in the saved order (drag the 3x3 dots to reorder;
        # the order also defines the line order in the VRChat chatbox)
        self.app_cards = {"status": card, "media": mcard, "hardware": hcard}
        self.apps_layout = layout
        for key in self.cfg["app_order"]:
            layout.addWidget(self.app_cards[key])
        layout.addWidget(acard)
        # Custom Box sits below All in one because that is the order it
        # works in: All in one decides WHAT is sent, the box only frames
        # whatever came out of it (see ui/pages/custom_box.py)
        layout.addWidget(self.build_box_card())
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

    # ================================================================
    # small-letter styles (superscript / subscript)
    # ================================================================
    def _make_style_combo(self, tooltip, choices=STYLE_CHOICES, width=196):
        """One dropdown for one styled field. The label carries its own
        preview, so the effect is visible before anything is picked.

        `width` exists for the Hardware component cards, which are half
        a card wide and share their row with a text field. Pair a
        narrower box with COMPACT_STYLE_CHOICES rather than clipping the
        long labels.
        """
        combo = QComboBox()
        for label, value in choices:
            combo.addItem(label, value)
        combo.setToolTip(tooltip)
        combo.setFixedWidth(width)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        return combo

    @staticmethod
    def set_style_combo(combo, value):
        """Selects a stored value without firing the change handler."""
        idx = combo.findData(normalize_style(value))
        combo.blockSignals(True)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _status_style(self, idx):
        styles = self.cfg.get("status_styles") or []
        if 0 <= idx < len(styles):
            return normalize_style(styles[idx])
        return STYLE_NORMAL

    def on_status_style(self, idx, value):
        if getattr(self, "_block_updating", False):
            return
        styles = self.cfg.setdefault("status_styles", [STYLE_NORMAL] * 20)
        while len(styles) < 20:
            styles.append(STYLE_NORMAL)
        styles[idx] = normalize_style(value)
        self._sync_active_template()
        self.save_config()
        # letters Unicode simply does not have would silently stay big,
        # so say so once instead of leaving people to spot it themselves
        missing = unsupported_chars(self.cfg["status_texts"][idx],
                                    styles[idx])
        if missing:
            self.log(f"Personal Status: text {idx + 1} keeps "
                     f"{' '.join(missing)} normal - no such character in "
                     f"this style. Wrap a whole word in {KEEP_HINT} to "
                     f"leave it out on purpose.")
        self.update_preview()

    def on_hw_style(self, key, value):
        if getattr(self, "_block_updating", False):
            return
        self.cfg[key] = normalize_style(value)
        self.save_config()
        self.update_preview()

    def on_media_time_style(self, value):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["media_time_style"] = normalize_style(value)
        self.save_config()
        self.update_preview()

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
        self.cfg["status_styles"] = [normalize_style(x) for x in
                                     (tpl.get("styles") or
                                      [STYLE_NORMAL] * 20)][:20]
        while len(self.cfg["status_styles"]) < 20:
            self.cfg["status_styles"].append(STYLE_NORMAL)
        self._block_updating = True
        for i, edit in enumerate(self.status_edits):
            edit.setText(self.cfg["status_texts"][i])
            self.set_style_combo(self.status_style_combos[i],
                                 self.cfg["status_styles"][i])
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
        tpl["styles"] = list(self.cfg.get("status_styles")
                             or [STYLE_NORMAL] * 20)

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

    def on_status_random(self, on):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["status_random"] = on
        self.save_config()
        self.log("Personal Status: texts switch "
                 + ("randomly" if on else "in order, top to bottom"))

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

    def _render_status(self, text, style=STYLE_NORMAL):
        """Renders a status text: only runs the template engine when the
        text actually contains a {placeholder} – so plain texts (incl.
        ones starting with \':3\' etc.) are never altered. The values come
        from the active plugins ({world_stats}, {realtime}, ...).

        The small-letter style is applied LAST, so whatever a placeholder
        filled in is rendered the same way as the text around it. It also
        strips the _"keep me"_ markers in normal mode, so they never leak
        into the chatbox.
        """
        if text and "{" in text:
            text = apply_template(text, self.plugins.values())
        return apply_style(text, style)

    def advance_status(self):
        """Moves to the next status text.

        Two orders, chosen by the Random order checkbox:

        - **random**, which is what this always did: any text except the
          one currently up, so nothing repeats back to back;
        - **in order**, straight down the list and around again.

        Both walk the *non-empty* texts only. Leaving a gap in the
        middle of the list is a normal thing to do while editing, and a
        sequential rotation that stopped on Text 4 because it is blank
        would look like the app had frozen.
        """
        texts = [t.strip() for t in
                 self.cfg["status_texts"][:self.cfg["status_count"]]]
        texts = [t for t in texts if t]
        if len(texts) <= 1:
            return
        current = self.status_index % len(texts)
        if self.cfg.get("status_random", True):
            choices = [i for i in range(len(texts)) if i != current]
            nxt = random.choice(choices)
        else:
            nxt = (current + 1) % len(texts)

        # The new text is only PENDING at this point. The preview must not
        # show anything VRChat is not showing, so the switch is committed
        # by the send itself (see commit_status / send_now). Rotate and
        # send run on independent timers, and sending can also be blocked
        # entirely - by a manual textbox message, for instance - and in
        # that case the preview has to keep standing still too.
        self.pending_status_index = nxt
        if self.sending_live():
            self.send_after_change()
        elif not self.cfg.get("send_to_vrchat"):
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

    def _status_slots(self):
        """[(slot, text)] of the non-empty texts of the active template.

        The slot number is kept because the style dropdowns are indexed
        by text field, not by position in the filtered list - an empty
        text 2 must not shift the style of text 3 onto text 4.
        """
        return [(i, t.strip()) for i, t in
                enumerate(self.cfg["status_texts"][:self.cfg["status_count"]])
                if t.strip()]

    def current_status_text(self):
        """Returns the currently shown status text (switches between the
        non-empty texts every status_cycle_sec seconds - randomly or in
        order, see advance_status)."""
        slots = self._status_slots()
        if not slots:
            return ""
        return slots[self.status_index % len(slots)][1]

    def current_status_style(self):
        """The style dropdown belonging to the currently shown text."""
        slots = self._status_slots()
        if not slots:
            return STYLE_NORMAL
        return self._status_style(slots[self.status_index % len(slots)][0])

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

    # ================================================================
    #  section scaffolding
    # ================================================================
    def _section_header(self, text):
        """A quiet heading inside a settings card.

        Deliberately not a QGroupBox: a real group box draws a frame per
        section, and four framed boxes stacked inside an already-framed
        card is more borders than content. A small caption plus the
        spacing around it is enough to say "these belong together"
        without adding another rectangle.
        """
        lbl = QLabel(text.upper())
        lbl.setObjectName("section")
        return lbl

    def _sub_group(self, vertical=False):
        """An indented container for options that belong to the
        checkbox above them.

        Returns (frame, layout) - the caller fills the layout and adds
        the frame wherever it belongs.

        The indent is a rule down the left edge rather than empty
        margin. With margin alone, "Max length" under "Song title" and
        "Songbar" two rows further down look like the same level of
        nesting once the card is long enough; the line makes the
        parent-child relationship visible without reading the labels.

        QFrame and not QWidget on purpose: a plain QWidget ignores a
        stylesheet border unless it is told to paint its own background,
        which is a footgun nobody needs twice.
        """
        frame = QFrame()
        frame.setObjectName("substack")
        layout = QVBoxLayout(frame) if vertical else QHBoxLayout(frame)
        layout.setContentsMargins(14, 2, 0, 2)
        layout.setSpacing(6 if vertical else 8)
        return frame, layout

    # ================================================================
    #  Hardware card scaffolding
    # ================================================================
    def _hw_component(self, title, subtitle=""):
        """One bordered box for one component. Returns (frame, layout).

        The Hardware card used to be one column of eighteen checkboxes
        with four bold labels somewhere in it, and finding the CPU half
        meant scrolling past the GPU half. Four boxes in a 2x2 grid fit
        the same options in a third of the height, and "which component
        is this" stops being something you work out from the label above
        the checkbox you happen to be looking at.
        """
        frame = QFrame()
        frame.setObjectName("hwcard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)
        head = QLabel(title)
        head.setObjectName("hwcardtitle")
        layout.addWidget(head)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("dim")
            sub.setWordWrap(True)
            layout.addWidget(sub)
        return frame, layout

    def _hw_check_grid(self, parent_layout, specs, columns=2):
        """The component's checkboxes, two per row.

        `specs` is (label, config key, tooltip or None). The labels are
        short because the box above them already says GPU or CPU - the
        examples that used to be in the label ("GPU usage  (e.g. GPU:
        27%)") moved into the tooltips, which is where a thing you read
        once belongs.
        """
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        made = []
        for i, (label, key, tip) in enumerate(specs):
            chk = QCheckBox(label)
            if tip:
                chk.setToolTip(tip)
            chk.toggled.connect(lambda on, k=key: self.on_hw_option(k, on))
            grid.addWidget(chk, i // columns, i % columns)
            made.append(chk)
        for col in range(columns):
            grid.setColumnStretch(col, 1)
        parent_layout.addLayout(grid)
        return made

    def _hw_name_row(self, parent_layout, which, placeholder):
        """The "Custom name" checkbox and, indented under it, the name
        field and its style dropdown on one shared row.

        Returns (checkbox, line edit, combo).

        Only the text field follows the checkbox. The dropdown does not,
        because the style applies to the *detected* name as well - see
        _hw_display_name() - so greying it out with the custom name off
        would take away a setting that is still doing something.
        """
        chk = QCheckBox("Custom name")
        chk.setToolTip(
            f"Use your own text instead of the detected {which.upper()} "
            "name. Detection returns marketing names that are long and "
            "sometimes wrong; 30 characters of the 144 is a lot to spend "
            "on one.")
        chk.toggled.connect(
            lambda on, k=f"hw_{which}_custom": self.on_hw_option(k, on))
        parent_layout.addWidget(chk)

        box, row = self._sub_group()
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setMaxLength(30)
        # no minimum: the card is half a settings card wide, and a field
        # that refuses to shrink pushes the dropdown off the edge on a
        # 1024px window instead of just getting narrow
        edit.setMinimumWidth(0)
        edit.textChanged.connect(
            lambda t, k=f"hw_{which}_custom_name": self.on_hw_text(k, t))
        row.addWidget(edit, 1)

        combo = self._make_style_combo(
            f"Renders the {which.upper()} name small to save room on the "
            "line. Applies to the detected name and to your custom one.",
            choices=COMPACT_STYLE_CHOICES, width=126)
        combo.currentIndexChanged.connect(
            lambda _i, k=f"hw_{which}_name_style", c=combo:
                self.on_hw_style(k, c.currentData()))
        row.addWidget(combo)
        parent_layout.addWidget(box)
        return chk, edit, combo

    def _mode_note(self, text, parent_layout):
        """A line at the top of a section, shown only when a setting
        somewhere else changed what that section does.

        This exists because the alternative - greying the section out -
        was a lie. Greyed means "this does nothing"; these controls do
        plenty in custom-string mode, they just stopped deciding the
        layout. Saying so costs one line and leaves everything clickable.
        """
        frame = QFrame()
        frame.setObjectName("infobox")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 6, 10, 6)
        lbl = QLabel(text)
        lbl.setObjectName("dim")
        lbl.setWordWrap(True)
        lay.addWidget(lbl, 1)
        frame.setVisible(False)
        parent_layout.addWidget(frame)
        return frame

    def _collapsible_section(self, title, parent_layout):
        """A section header that is also the arrow to fold it away.

        Returns the layout to fill. The card had grown past a screenful
        even after being grouped, and most of it is set once and never
        touched again - the songbar characters, the lyrics folder, the
        idle symbol. Folding lets somebody who only came to change the
        player see the player.

        Collapsed on start, like every other expander in the app. The
        state is deliberately not remembered: the outer Settings arrow
        forgets too, and one of the two remembering would be stranger
        than neither.
        """
        btn = QPushButton(f"\u203a  {title}")
        btn.setObjectName("sectionexpander")
        btn.setCheckable(True)
        btn.setChecked(False)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 2, 0, 8)
        layout.setSpacing(4)
        content.setVisible(False)

        btn.toggled.connect(
            lambda on, b=btn, c=content, t=title:
            self.set_expanded(b, c, on, t))
        parent_layout.addWidget(btn)
        parent_layout.addWidget(content)
        return layout

    # ================================================================
    #  live preview
    # ================================================================
    #: A stand-in track for the preview. Long enough that the Max length
    #: slider visibly does something, and roughly a third of the way in
    #: so the songbar is neither empty nor full.
    DEMO_TRACK = {
        "artist": "Nightdrive",
        "title": "Midnight Signal (Extended Mix)",
        "position": 78.0,
        "length": 227.0,
        "playing": True,
        "player": "spotify",
        "player_key": "spotify",
        "player_label": "Spotify",
    }
    DEMO_LYRICS = "and the city lights go by"

    def update_media_preview(self):
        """Render the MediaPlay line the way it will actually appear.

        Goes through build_media_lines() rather than formatting anything
        itself. That function already handles the custom string, the
        icon, the merged bar line, the idle fallback and the order of
        everything - reimplementing a readable subset of it here would
        produce a preview that is right today and wrong after the next
        change to the real one.

        Real data wins when there is any: while music is playing this
        shows the actual song, which is more useful than a stand-in and
        also proves the player setting is picking the right source.
        """
        lbl = getattr(self, "media_preview_lbl", None)
        if lbl is None:
            return

        live = bool(self.media_info)
        if not live:
            # Swap in the demo track for the duration of one render. The
            # attribute is restored in the finally block, so a failure
            # in here cannot leave the app believing a song is playing.
            self.media_info = dict(self.DEMO_TRACK)
            # Lyrics would otherwise send the stand-in artist and title
            # to LRCLIB - a network request for a track that does not
            # exist, repeated on every keystroke in the custom string.
            self._demo_lyrics = self.DEMO_LYRICS
        try:
            lines = self.build_media_lines()
        except Exception as e:                              # noqa: BLE001
            lines = []
            self.log(f"MediaPlay: preview failed ({type(e).__name__}: {e})")
        finally:
            if not live:
                self.media_info = None
                self._demo_lyrics = None

        text = "\n".join(lines) if lines else ""
        lbl.setText(text or "(nothing – every part is switched off)")

        note = getattr(self, "media_preview_note", None)
        if note is None:
            return
        if live:
            note.setText("Your song, right now.")
        elif not self.cfg.get("media_active"):
            note.setText("Example – MediaPlay is switched off.")
        else:
            note.setText("Example – nothing is playing at the moment.")

    def _sync_media_dependents(self):
        """Shows each sub-option only when its parent checkbox is on:
        - Max length  -> only with Song title
        - Time with seconds -> only with Time
        - Use my own .lrc files -> only with Lyrics
        - all Songbar options -> only with Songbar
        The custom songbar editor additionally needs the Custom style.

        Custom-string mode adds a note to Content and Playback rather
        than disabling them - see the comment further down for why.
        """
        title_on = self.chk_title.isChecked()
        time_on = self.chk_time.isChecked()
        lyrics_on = self.chk_lyrics.isChecked()
        bar_on = self.chk_bar.isChecked()

        idle_on = self.chk_media_idle.isChecked()
        custom_on = self.chk_media_custom.isChecked()

        self.media_idle_input.setEnabled(idle_on)
        self.media_idle_box.setVisible(idle_on)
        self.title_max_row.setVisible(title_on)
        # the two Time sub-options now share one row
        self.time_opts_box.setVisible(time_on)
        self.lyrics_box.setVisible(lyrics_on)
        self.lyrics_prefix_row.setVisible(lyrics_on)
        self.chk_lyrics_local.setVisible(lyrics_on)
        self.songbar_box.setVisible(bar_on)
        is_custom = self.bar_style_combo.currentIndex() == CUSTOM_STYLE_INDEX
        self.bar_custom_box.setVisible(bar_on and is_custom)
        self.media_custom_box.setVisible(custom_on)
        # A custom string replaces the LAYOUT above it, not the settings.
        # Everything in Content and Playback still feeds it: an unticked
        # Song title leaves {title} empty, Max length still truncates,
        # "With seconds" still picks the time format, and the songbar
        # style and size still build {bar}. Greying them out - which is
        # what v1.4.4 did - locked people out of settings that were
        # still doing their job, so the sections say what changed
        # instead and stay usable.
        self.content_custom_note.setVisible(custom_on)
        self.playback_custom_note.setVisible(custom_on)
        # The one genuine exception. "Time position" merges the clock
        # into the bar line, and that merge only happens while the
        # standard layout is building the lines - a custom string places
        # {bar} and {time} itself. This one really does nothing, so it
        # really is greyed.
        for widget in (self.time_pos_combo, self.time_pos_lbl):
            widget.setEnabled(not custom_on)
        self.time_pos_combo.setToolTip(
            "Not used while a custom string is on - your string decides "
            "where {time} goes."
            if custom_on else
            "Merging the time into the bar keeps the chatbox at two "
            "lines instead of three.")
        # folder row: only when Lyrics AND "use my own .lrc" are both on
        self._sync_lyrics_local()
        self.update_media_preview()

    def on_media_option(self, key, on):
        self.cfg[key] = on
        self.save_config()
        if key == "media_lyrics_local":
            self._sync_lyrics_local()
        if key == "media_source_fallback":
            # the backend reads this on every fetch, so it takes effect
            # on the next poll without rebuilding anything
            self.media.fallback = on
        self._sync_media_dependents()
        self.update_preview()

    # --------------------------------------------------- player choice
    def refresh_media_sources(self, force=False):
        """Rebuild the player dropdown from what is running right now.

        The saved choice always survives this, even when that player is
        closed: dropping it would mean someone who quits Spotify comes
        back to a card silently set to Automatic. It is listed as "not
        running" instead, which is the truth and is recoverable.
        """
        combo = getattr(self, "media_source_combo", None)
        if combo is None:
            return
        try:
            found = self.media.list_sources()
        except Exception as e:
            self.log(f"MediaPlay: could not list players ({e})")
            found = []

        want = self.cfg.get("media_source", "")
        # Repopulating fires currentIndexChanged, which would write the
        # config back with whatever lands at index 0 mid-rebuild.
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Automatic  (whatever is playing)", "")
        for item in found:
            mark = "  \u2013 playing" if item["playing"] else ""
            combo.addItem(f"{item['label']}{mark}", item["key"])
        if want and not any(item["key"] == want for item in found):
            label = self.cfg.get("media_source_label") or player_label(want)
            combo.addItem(f"{label}  \u2013 not running", want)
        index = combo.findData(want)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

        if force:
            names = ", ".join(item["label"] for item in found)
            self.log(f"MediaPlay: players found: {names or 'none'}")

    def on_media_source_changed(self, _index):
        combo = self.media_source_combo
        key = combo.currentData() or ""
        self.cfg["media_source"] = key
        # Remember the pretty name too. Without it the dropdown has
        # nothing to call the choice once that player is closed, and
        # "Spotify.exe – not running" is a worse thing to read than
        # "Spotify – not running".
        label = ""
        if key:
            for item in self.media.list_sources():
                if item["key"] == key:
                    label = item["label"]
                    break
            if not label:
                label = self.cfg.get("media_source_label") or player_label(key)
        self.cfg["media_source_label"] = label
        self.media.preferred = key
        # the cached bus name belongs to the old choice
        self.media._cached_player = None
        self.save_config()
        self.log(f"MediaPlay: player set to {label or 'Automatic'}")
        self.update_preview()

    def on_media_idle_text(self, text):
        self.cfg["media_idle_text"] = text
        self.save_config_later()
        self.update_preview()

    def _lyrics_prefix(self):
        """The symbol that goes in front of the lyrics line, or "" when
        it is switched off / cleared. One place decides it, so the
        standard output, the {lyrics_prefix} placeholder and the preview
        can never disagree."""
        if not self.cfg.get("media_lyrics_prefix_on", True):
            return ""
        return str(self.cfg.get("media_lyrics_prefix", "\u266a"))[:4].strip()

    def on_lyrics_prefix_on(self, on):
        self.cfg["media_lyrics_prefix_on"] = bool(on)
        self.lyrics_prefix_input.setEnabled(bool(on))
        self.save_config()
        self.update_preview()

    def on_lyrics_prefix(self, text):
        self.cfg["media_lyrics_prefix"] = text[:4]
        self.save_config_later()
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

    def _sync_hw_dependents(self):
        """Greys out the fields whose parent checkbox is off.

        Three separate rules, because the three things depend on
        different checkboxes:

        - the custom GPU/CPU name field follows its own "Custom name";
        - the style dropdown does NOT, because _hw_display_name() styles
          the detected name too - it only goes dead when neither a
          detected nor a custom name is going out, and the line would
          say a bare GPU or CPU;
        - the custom string editor follows "Build my own layout".

        Greyed rather than hidden, on purpose: a row that vanishes takes
        its own explanation with it, and someone who ticks "Custom name"
        should find the field where they last saw it.
        """
        for which in ("gpu", "cpu"):
            custom_on = getattr(self, f"chk_{which}_custom").isChecked()
            name_on = getattr(self, f"chk_{which}_name").isChecked()
            getattr(self, f"{which}_custom_input").setEnabled(custom_on)
            getattr(self, f"{which}_style_combo").setEnabled(
                custom_on or name_on)
        self.hw_custom_box.setEnabled(self.chk_hw_custom.isChecked())

    def on_hw_option(self, key, on):
        self.cfg[key] = on
        self.save_config()
        self._sync_hw_dependents()
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

    def on_aio_mode(self, key):
        """Normal / Advanced. Only the UI changes here - nothing is
        rewritten or thrown away, so this is always reversible."""
        key = key if key in ("normal", "advanced") else "normal"
        self.cfg["aio_mode"] = key
        self.save_config()
        self._apply_aio_mode()
        # the two modes rarely have the same number of strings on
        # rotation, so the index has to start over or it would point past
        # the end of the new one
        self.aio_index = 0
        self.update_timers()
        self.update_preview()
        self.log(f"All in one: {key} mode")

    def _apply_aio_mode(self):
        """Shows the fields or the pointer to the node canvas, depending
        on cfg['aio_mode']. Called on start and on every switch."""
        advanced = self.cfg.get("aio_mode") == "advanced"
        for k, b in self.aio_mode_buttons.items():
            b.setChecked(k == ("advanced" if advanced else "normal"))
        self.aio_normal_box.setVisible(not advanced)
        self.aio_advanced_box.setVisible(advanced)

    def on_aio_count(self, val):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_count"] = val
        self._sync_active_aio_set()
        self.save_config()
        for i, row in enumerate(self.aio_rows):
            row.setVisible(i < val)
        # the Advanced page carries the same setting - mirror it there
        # rather than letting the two drift apart
        self._mirror_graph_rotation()
        self.aio_index = 0
        self.update_timers()
        self.update_preview()

    def on_aio_rotate(self, on):
        self.cfg["aio_rotate"] = on
        self.save_config()
        self._mirror_graph_rotation()
        self.aio_index = 0
        self.update_timers()
        self.update_preview()

    def on_aio_rotate_sec(self, val):
        self.cfg["aio_rotate_sec"] = val
        self.save_config()
        self._mirror_graph_rotation()
        self.update_timers()

    def _mirror_graph_rotation(self):
        """Repaints the copies of "Number of strings" / "Rotate every"
        that live on the Advanced page. One setting, two places to see
        it - the config is the single source, these are just views."""
        if not hasattr(self, "graph_count_spin"):
            return
        for widget, value in ((self.graph_count_spin, self.cfg["aio_count"]),
                              (self.graph_rotate_chk, self.cfg["aio_rotate"]),
                              (self.graph_rotate_spin,
                               self.cfg["aio_rotate_sec"])):
            widget.blockSignals(True)
            if widget is self.graph_rotate_chk:
                widget.setChecked(bool(value))
            else:
                widget.setValue(int(value))
            widget.blockSignals(False)
        self._update_graph_slot_labels()

    def on_aio_text(self, idx, text):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_templates"][idx] = text
        self._sync_active_aio_set()
        self.save_config_later()
        # a string going empty (or filling up) changes which strings are
        # on rotation at all, and with it whose dwell time is next
        self.update_timers()
        self.update_preview()

    def on_aio_height(self, idx, px):
        """Remembers the height the user dragged a field to. Purely
        cosmetic, so it lives outside the template sets - switching
        layouts should not make the fields jump around."""
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_heights"][idx] = int(px)
        self.save_config_later()

    def on_aio_custom_time(self, idx, on):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_custom_time"][idx] = bool(on)
        self._sync_active_aio_set()
        self.save_config()
        self.log(f"All in one: AIO {idx + 1} "
                 + (f"stays on screen for {self.cfg['aio_custom_sec'][idx]} "
                    "seconds" if on else "follows the shared rotation "
                    "interval again"))
        self.update_timers()

    def on_aio_custom_sec(self, idx, val):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_custom_sec"][idx] = int(val)
        self._sync_active_aio_set()
        self.save_config_later()
        self.update_timers()

    def _sync_active_aio_set(self):
        """Writes the current strings/count back into the active AIO
        template so every set keeps its own layout."""
        sets = self.cfg["aio_sets"]
        idx = min(len(sets) - 1, max(0, self.cfg["aio_set_active"]))
        sets[idx]["templates"] = list(self.cfg["aio_templates"])
        sets[idx]["count"] = self.cfg["aio_count"]
        sets[idx]["custom_time"] = list(self.cfg["aio_custom_time"])
        sets[idx]["custom_sec"] = list(self.cfg["aio_custom_sec"])
        # the canvases belong to the template as much as the strings do -
        # switching template and keeping the old graphs would leave the
        # two halves of one AIO string describing different things
        if hasattr(self, "graph_canvas"):
            self._store_current_graph()
        sets[idx]["graphs"] = [dict(g) for g in (self.cfg.get("aio_graphs")
                                                 or [])]

    def on_aio_set(self, idx):
        """Exclusive AIO template toggle: activates set idx and loads its
        own strings/count (all others switch off)."""
        idx = min(9, max(0, int(idx)))
        self.cfg["aio_set_active"] = idx
        tpl = self.cfg["aio_sets"][idx]
        self.cfg["aio_templates"] = list(tpl["templates"])
        self.cfg["aio_count"] = tpl["count"]
        self.cfg["aio_custom_time"] = list(tpl["custom_time"])
        self.cfg["aio_custom_sec"] = list(tpl["custom_sec"])
        graphs = tpl.get("graphs") or []
        graphs = [dict(g) if isinstance(g, dict) else {"nodes": [],
                                                       "edges": []}
                  for g in graphs][:AIO_MAX]
        graphs += [{"nodes": [], "edges": []}
                   for _ in range(AIO_MAX - len(graphs))]
        self.cfg["aio_graphs"] = graphs
        self._block_updating = True
        for i, edit in enumerate(self.aio_edits):
            edit.setValue(self.cfg["aio_templates"][i])
        for i, chk in enumerate(self.aio_time_checks):
            chk.setChecked(self.cfg["aio_custom_time"][i])
        for i, spin in enumerate(self.aio_time_spins):
            spin.setValue(self.cfg["aio_custom_sec"][i])
        self.aio_count_spin.setValue(self.cfg["aio_count"])
        self._block_updating = False
        for i, row in enumerate(self.aio_rows):
            row.setVisible(i < self.cfg["aio_count"])
        self.aio_index = 0
        if hasattr(self, "graph_canvas"):
            # the canvas is showing a graph that just stopped being the
            # current one, so it has to be reloaded rather than saved
            self._graph_runtime_state = {}
            self._show_graph_slot(min(self.graph_slot,
                                      self.cfg["aio_count"] - 1))
            self._mirror_graph_rotation()
            self._sync_graph_set_buttons()
        self.save_config()
        self.update_timers()
        self.update_preview()
        self.log(f"All in one: template {idx + 1} active")

    def advance_aio(self):
        self.aio_index += 1
        self.update_preview()
        # The string that just came up decides how long it stays, so the
        # interval is set per step rather than once. Restarting a running
        # QTimer with a new interval is exactly what start() does.
        self.aio_timer.start(self.aio_interval_ms())
        if not self.aio_is_advanced():
            # Rotation and sending run on independent timers, so without
            # this the new string waits for the next send interval - a
            # string with a 2 second Custom time could be gone again
            # before VRChat ever saw it. Rate limited and coalesced by
            # request_send(); Advanced mode is left alone because
            # tick_graph() already notices the changed slot and would
            # send the same text a second time.
            self.request_send()

    def aio_is_advanced(self):
        return self.cfg.get("aio_mode") == "advanced"

    def aio_graph(self, idx):
        """The canvas of AIO string ``idx`` (0-based), or an empty one."""
        graphs = self.cfg.get("aio_graphs") or []
        if 0 <= idx < len(graphs) and isinstance(graphs[idx], dict):
            return graphs[idx]
        return {"nodes": [], "edges": []}

    def _aio_active_indices(self):
        """Slot numbers of the strings actually on rotation.

        The slot number has to travel with the string: AIO 2 being empty
        must not shift AIO 3's dwell time onto AIO 4."""
        if self.aio_is_advanced():
            # structural: a slot exists when the canvas has a Chatbox
            # Output block for it. Deliberately NOT "the graph currently
            # renders to something" - a slot that shows the song title
            # would otherwise leave and rejoin the rotation every time
            # the music is paused, and take the dwell times of the
            # others with it.
            return [i for i in range(self.cfg["aio_count"])
                    if graph_has_output(self.aio_graph(i))]
        return [i for i in range(self.cfg["aio_count"])
                if self.cfg["aio_templates"][i].strip()]

    def _aio_active_templates(self):
        if self.aio_is_advanced():
            return [graph_literals(self.aio_graph(i))
                    for i in self._aio_active_indices()]
        return [self.cfg["aio_templates"][i]
                for i in self._aio_active_indices()]

    def current_aio_index(self):
        """Slot number of the AIO string on screen right now, or -1."""
        slots = self._aio_active_indices()
        if not slots:
            return -1
        return slots[self.aio_index % len(slots)]

    def aio_interval_ms(self):
        """How long the string currently on screen stays there.

        Its own "Custom time" when it has one, the shared rotation
        interval otherwise - which is what makes the setting local to
        one string instead of a second global switch."""
        idx = self.current_aio_index()
        if idx >= 0 and self.cfg["aio_custom_time"][idx]:
            return max(2, int(self.cfg["aio_custom_sec"][idx])) * 1000
        return max(2, int(self.cfg["aio_rotate_sec"])) * 1000

    # ================================================================
    # Parameters list (the expander under All in one)
    # ================================================================
    #: the built-in vocabulary, grouped the way the UI is grouped so the
    #: list reads like the app rather than like a dump of the value dict.
    #: Kept as data because it is a reference, not logic - a new
    #: placeholder is one line here and nothing else.
    SOFTWARE_PARAMETERS = (
        ("Personal Status", "{text}  {text_1} \u2026 {text_20}",
         "{text} is the status text currently on rotation; the numbered "
         "ones address a specific slot."),
        ("Personal Status \u2013 other templates",
         "{text_t1} \u2026 {text_t10}   {text_t1_1} \u2026 {text_t10_20}",
         "Reach into a template that is NOT the one selected above: "
         "{text_t3} is the rotating text of template 3, {text_t3_5} is "
         "its slot 5. {text_template3} and {text_tpl3} spell the same "
         "thing. They work whether or not Personal Status is switched "
         "on - naming a template is asking for that text, not for the "
         "Status card - so the ten templates double as a text library "
         "for All in one. An empty slot renders empty; a template that "
         "is empty or has no such number falls back to the active one."),
        ("MediaPlay", "{artist}  {title}  {time}  {time_status}  "
                      "{time_end}  {bar}  {lyrics}  {lyrics_prefix}  "
                      "{icon_sound}  {media_idle}",
         "{bar} is the progress bar, {time_status} follows the time "
         "format you picked in MediaPlay. {media_idle} is the idle "
         "symbol while nothing plays and empty otherwise."),
        ("Hardware", "{gpu_name}  {gpu_usage}  {gpu_temp}  {gpu_power}  "
                     "{vram_usage}  {cpu_name}  {cpu_usage}  {cpu_temp}  "
                     "{cpu_power}  {ram_usage}  {ram_type}  {temp_icon}  "
                     "{icon_flame}",
         "{gpu_power} / {cpu_power} are the power draw in watts "
         "({gpu_watt} spells the same thing) and follow the "
         "\u201cpower draw in watts\u201d checkboxes on the Hardware card, "
         "which are off by default. NVIDIA always reports it; "
         "AMD GPUs need amdgpu's hwmon node, and CPU watts need zenpower "
         "or readable RAPL counters - on Windows both come from "
         "LibreHardwareMonitor. Empty when nothing reports it, like every "
         "other sensor here. "
         "With {temp_icon} in the string the temperatures drop their unit, "
         "because the icon already carries it."),
        ("Formatting", "{sup}text{/sup}   {sub}text{/sub}   "
                       "{super/\"word\"}   {sub/\"word\"}",
         "Superscript and subscript. The tag pair styles a whole stretch "
         "including the placeholders inside it; the slash form styles one "
         "word (the older form, kept so existing strings work - the tag "
         "pair does everything it does). Unicode has no complete "
         "alphabet for either (superscript "
         "lacks q, subscript lacks b c d f g q w y z) - those letters "
         "pass through unchanged. Wrap a word in _\"quotes\"_ to keep it "
         "out of the conversion. A tag left unclosed styles the rest of "
         "the string."),
        ("Chat / Speech to Text",
         "{text_input}  {text_output}   {stt_*}  {ttt_*}  {chat_*}",
         "The last message from the Chat card, Speech to Text or Text to "
         "Text. {text_input} is what was typed or said, {text_output} "
         "what actually goes out - the translation, when there is one. "
         "{stt_input}/{stt_output}, {ttt_input}/{ttt_output} and "
         "{chat_input}/{chat_output} are the same pair narrowed to one "
         "source, so speech can go somewhere else than typing; exactly "
         "one of the three is ever filled. They fill in every send mode; "
         "set \u201cSend as\u201d to Variables on the Textbox page if "
         "the message should show up ONLY where you place it here."),
        ("Live info", "{player_in_world}  {group_world}  {realtime}  "
                      "{instance_type}",
         "Read from the VRChat log by the bundled world_stats plugin."),
        ("Custom Box", "{box_start}  {box_stop}  {box_text}",
         "The two frame lines and the middle text on its own. With All "
         "in one active these are the ONLY way the frame appears - the "
         "card no longer wraps the whole message, because a wrap can "
         "only ever be right for one of your strings and would sit "
         "around the plugin lines as well."),
        ("Text styles", '{super/"word"}   {sub/"word"}',
         "Makes one part of the string small. The content may be a "
         "placeholder: {super/{cpu_usage}}. Superscript has no q and "
         "subscript is missing about half the alphabet - those letters "
         "pass through unchanged, and _\"word\"_ keeps a word out of the "
         "conversion entirely."),
        ("Formatting", "\\n",
         "A line break. Everything else is your own text."),
    )

    def _on_aio_params_toggled(self, on):
        # rebuilt on open, so a plugin installed or renamed since the app
        # started shows up without a restart
        if on:
            self.refresh_parameter_lists()
        self.set_expanded(self.aio_param_expander, self.aio_param_content,
                          on, "Parameters")

    def _param_heading(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: 700;")
        return lbl

    def _param_row(self, name, placeholders, note=""):
        """One group: its name, the placeholders (selectable, so they can
        be copied straight out) and an optional note."""
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        head = QLabel(name)
        head.setObjectName("dim")
        box.addWidget(head)
        ph = QLabel(placeholders)
        ph.setWordWrap(True)
        ph.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(ph)
        if note:
            n = QLabel(note)
            n.setObjectName("dim")
            n.setWordWrap(True)
            box.addWidget(n)
        return box

    def register_parameter_list(self, layout):
        """Hands a layout over to be filled with the Parameters list and
        kept up to date. More than one card shows the same vocabulary -
        All in one and the Custom Box both render strings against the
        exact same value dict - so they share one builder rather than
        two lists that can drift apart."""
        if not hasattr(self, "_param_layouts"):
            self._param_layouts = []
        if layout not in self._param_layouts:
            self._param_layouts.append(layout)
        self._fill_parameters(layout)

    def refresh_parameter_lists(self):
        """(Re)builds every registered Parameters list. Called when a
        block is opened and whenever the plugin list changes, so the
        external half can never drift from what is actually installed."""
        for layout in getattr(self, "_param_layouts", []):
            self._clear_layout(layout)
            self._fill_parameters(layout)
        # the canvas offers the same vocabulary, so it is rebuilt from
        # the same trigger instead of having its own refresh path
        self.refresh_graph_variables()

    def refresh_aio_parameters(self):
        """Kept for callers that only mean the All-in-one list."""
        self.refresh_parameter_lists()

    def _fill_parameters(self, layout):
        # ---------------------------------------------- built in
        layout.addWidget(self._param_heading("Software parameters"))
        intro = QLabel("Everything the app itself produces. Works in the "
                       "All-in-one string and in a Custom Box middle text "
                       "alike \u2013 both are rendered against the same "
                       "values. An app has to be Active for its values to "
                       "fill in; a placeholder from an inactive app renders "
                       "as nothing and its leftover separators are cleaned "
                       "up.")
        intro.setObjectName("dim")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for name, placeholders, note in self.SOFTWARE_PARAMETERS:
            layout.addLayout(self._param_row(name, placeholders, note))

        # ---------------------------------------------- plugins
        layout.addWidget(self._param_heading("External parameters"))
        plugins = self.plugins.ordered()
        if not plugins:
            empty = QLabel("No plugins installed. The Plugins page has an "
                           "\u201cOpen plugins folder\u201d button and a "
                           "link to the plugin repository.")
            empty.setObjectName("dim")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            return
        intro = QLabel("Everything your installed plugins provide. "
                       "{<id>} is the plugin's own output; a plugin can "
                       "also expose extra values under {<id>_<key>}. "
                       "Inactive plugins are listed too \u2013 they render "
                       "as nothing until you switch them on.")
        intro.setObjectName("dim")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for plugin in plugins:
            names = [f"{{{plugin.pid}}}"]
            for key in plugin.placeholders:
                names.append(f"{{{plugin.pid}_{key}}}")
            # names the manifest claimed without the id prefix
            for key in plugin.global_keys:
                names.append(f"{{{key}}}")
            state = "active" if plugin.enabled else "inactive"
            if not plugin.supported:
                state = plugin.platform_note
            layout.addLayout(self._param_row(
                f"{plugin.name}  \u2013  {state}", "  ".join(names),
                plugin.description or ""))

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                AppsPageMixin._clear_layout(item.layout())

    def current_aio_template(self):
        """The AIO string that is on screen right now (rotation included),
        or "" when All in one has nothing to show. The Custom Box needs
        this to see whether that string places the frame itself.

        In Advanced mode there is no template string, so this hands back
        the literals of the blocks feeding that slot instead - which is
        exactly what the two callers search: they look for placeholder
        names like {box_start}, not for rendered text.
        """
        idx = self.current_aio_index()
        if idx < 0:
            return ""
        if self.aio_is_advanced():
            return graph_literals(self.aio_graph(idx))
        return self.cfg["aio_templates"][idx]

    # ================================================================
    # cross-template placeholders: {text_tX} / {text_tX_N}
    # ================================================================
    def _template_slots(self, tpl):
        """[(slot, text)] of the non-empty texts of ANY template dict.

        The same rule _status_slots() uses for the active one: the slot
        number travels with the text, because the styles are indexed by
        text field and an empty slot 2 must not shift slot 3's style onto
        slot 4.
        """
        texts = tpl.get("texts") or []
        count = min(20, max(1, int(tpl.get("count", 1) or 1)))
        return [(i, str(t).strip()) for i, t in enumerate(texts[:count])
                if str(t).strip()]

    @staticmethod
    def _template_style(tpl, slot):
        styles = tpl.get("styles") or []
        if 0 <= slot < len(styles):
            return normalize_style(styles[slot])
        return STYLE_NORMAL

    def resolve_status_template(self, key):
        """{text_tX} and {text_tX_N} - reach into a template that is not
        the one selected at the top of Personal Status.

        {text_tX}     the rotating text of template X
        {text_tX_N}   slot N of template X, whatever the rotation is doing

        Two deliberate decisions in here:

        * These resolve whether or not Personal Status is switched on,
          unlike {text} and {text_N}. Naming a template explicitly is
          asking for that text, not for the Status card's output - which
          is what makes the ten templates usable as a text library from
          All in one. {text} and {text_N} keep their old behaviour, so
          nothing about an existing string changes.
        * {text_tX} rotates on the SAME clock as the active template.
          Only one rotation timer exists, and giving every template its
          own would mean ten independent switches racing for one 144
          character chatbox.

        Returns None when the name is not one of ours, so the caller can
        fall through to its normal miss handling.
        """
        m = _TEXT_T_RE.match(key)
        if not m:
            return None
        tpls = self.cfg.get("status_templates") or []
        if not tpls:
            return ""
        active = min(len(tpls) - 1,
                     max(0, int(self.cfg.get("status_template_active", 0))))
        idx = int(m.group(1)) - 1
        if not 0 <= idx < len(tpls):
            # a template number that does not exist falls back to the
            # active one rather than to nothing - the same answer the
            # user would get without the tX part at all
            idx = active
        tpl = tpls[idx]

        if m.group(2) is not None:
            # ---- a specific slot -------------------------------------
            slot = int(m.group(2)) - 1
            texts = tpl.get("texts") or []
            if not 0 <= slot < len(texts):
                return ""          # no such slot -> empty, never a guess
            text = str(texts[slot]).strip()
            if not text:
                return ""          # an empty slot IS the answer
            return self._render_status(
                text, self._template_style(tpl, slot)) or None

        # ---- the rotating text of that template ----------------------
        slots = self._template_slots(tpl)
        if not slots and idx != active:
            # an empty template falls back to the active one, so a
            # template you have not filled in yet does not silently blank
            # the line it sits on
            tpl = tpls[active]
            slots = self._template_slots(tpl)
        if not slots:
            return ""
        slot, text = slots[self.status_index % len(slots)]
        return self._render_status(
            text, self._template_style(tpl, slot)) or None

    def _template_values(self, probe=""):
        """The placeholder dict every custom string is rendered against:
        All in one, and the middle text of the Custom Box.

        ``probe`` is the template the values are going into. It is only
        read to decide how the temperatures are formatted - a string
        containing {temp_icon} supplies its own unit, so the raw number
        goes in instead of the one with the unit baked on.
        """
        vals = LazyStatusValues()
        # {text_tX} / {text_tX_N} are answered on demand from here
        vals.resolver = self.resolve_status_template
        # Personal Status texts
        if self.cfg["status_active"]:
            vals["text"] = self._render_status(
                self.current_status_text(),
                self.current_status_style()) or None
            for i in range(20):
                vals[f"text_{i + 1}"] = (
                    self._render_status(self.cfg["status_texts"][i].strip(),
                                        self._status_style(i))
                    or None)
        else:
            vals["text"] = None
            for i in range(20):
                vals[f"text_{i + 1}"] = None
        # MediaPlay values
        if self.cfg["media_active"] and self.media_info:
            vals.update(self._media_values(self.media_info))
        vals.setdefault("icon_sound", "\U0001F3B5")
        # {media_idle}: the idle symbol while nothing plays, empty
        # otherwise. All in one never calls build_media_lines(), so
        # without this an AIO string has no way to say "nothing playing"
        vals["media_idle"] = (
            None if (self.cfg["media_active"] and self.media_info)
            else ((self.cfg.get("media_idle_text") or "").strip() or None))
        # Hardware values (incl. temp_icon behaviour)
        if self.cfg["hw_active"] and self.hw_info:
            hw = self._hw_values(self.hw_info)
            if re.search(r"\{\s*temp_icon\s*\}", probe or "", re.IGNORECASE):
                gpu = self.hw_info.get("gpu") or {}
                if self.cfg["hw_gpu_temp"] and gpu.get("temp") is not None:
                    hw["gpu_temp"] = f"{gpu['temp']:.0f}"
                if self.cfg["hw_cpu_temp"] and self.hw_info.get("cpu_temp") is not None:
                    hw["cpu_temp"] = f"{self.hw_info['cpu_temp']:.0f}"
            vals.update(hw)
        vals["temp_icon"] = "\U0001F525" if self.cfg["hw_flame"] else "\u00b0C"
        vals.setdefault("icon_flame", "\U0001F525")
        # The Chat card's parked message. Present in every send mode, so
        # a template using {text_output} keeps working if you switch the
        # dropdown - it is only the Line mode that ALSO adds a line of
        # its own. None rather than "" so an empty one collapses the
        # separators around it like every other placeholder.
        msg_in = (self.chat_text_input or "").strip() or None
        msg_out = (self.chat_text_output or "").strip() or None
        vals["text_input"] = msg_in
        vals["text_output"] = msg_out
        # The same pair narrowed to the source it came from. Exactly one
        # of the three origins is ever filled, so a string can carry
        # {stt_output} and {chat_output} side by side and only the one
        # that applies shows up - the empty ones collapse with their
        # separators like any other placeholder.
        for origin in ORIGINS:
            hit = origin == getattr(self, "chat_text_origin", ORIGIN_CHAT)
            vals[f"{origin}_input"] = msg_in if hit else None
            vals[f"{origin}_output"] = msg_out if hit else None
        # {<plugin_id>} and {<plugin_id>_<key>} of every active plugin,
        # plus any unprefixed name a plugin claimed (never overwriting
        # a value one of the apps above already produced)
        self.plugins.merge_into(vals)
        return vals

    #: the MediaPlay half of the vocabulary, by canonical name. Used to
    #: recognise a template line that is about the song and nothing else.
    MEDIA_KEYS = frozenset((
        "artist", "title", "time", "time_status", "time_end", "bar",
        "lyrics", "lyrics_prefix", "position", "length"))

    def _line_is_media(self, tpl_line):
        """True when this template line asks for at least one MediaPlay
        value. Aliases are resolved the same way apply_template resolves
        them, so {song} counts as {title}; style markers are skipped
        because {super/...} is not a placeholder name."""
        for match in re.finditer(r"\{([^{}]+)\}", tpl_line):
            inner = match.group(1)
            if is_inline_marker(inner):
                continue
            key = inner.strip().lower().replace(" ", "_")
            if PLACEHOLDER_ALIASES.get(key, key) in self.MEDIA_KEYS:
                return True
        return False

    def _aio_idle_text(self):
        """The idle symbol, or "" when it does not apply right now."""
        if not (self.cfg["media_active"] and self.cfg.get("media_idle")):
            return ""
        if self.media_info:
            return ""
        return (self.cfg.get("media_idle_text") or "").strip()

    def _build_graph_lines(self, vals, idle):
        """Advanced mode: the lines come out of the node canvas.

        The canvas of the slot that is on screen right now is evaluated,
        which keeps the rotation, the dwell times and the Custom Box
        working exactly as they do for a typed string - from here down
        the pipeline only ever sees text.

        Text only - the blocks with side effects are handled by
        run_graph_automation(), which walks every canvas rather than
        just this one.
        """
        idx = self.current_aio_index()
        if idx < 0:
            return []
        try:
            raw = graph_evaluate(
                self.aio_graph(idx), vals,
                osc=getattr(self, "osc_in", None),
                keys=getattr(self, "hotkey_in", None),
                procs=self.procs, shown=True,
                state=self._graph_state(idx))
        except Exception as e:      # noqa: BLE001
            # a broken graph must not take the send loop down with it -
            # the message is worth more than the block that failed
            self.log(f"Advanced mode: graph could not be evaluated ({e})")
            return []
        text = finish_template(raw)
        if text:
            return text.split("\n")
        # empty result: same courtesy the typed strings get - a slot that
        # is about the song answers with the idle symbol rather than
        # disappearing
        if idle and self._line_is_media(graph_literals(self.aio_graph(idx))):
            return [idle]
        return []

    def run_graph_automation(self, vals=None, only=None):
        """Runs the side-effect blocks of EVERY canvas.

        Automation must not depend on which string happens to be on
        rotation. A canvas holding nothing but Button -> Send Hotkey has
        no Chatbox Output block at all, so it is never "the current
        slot" - tying side effects to the visible canvas meant those
        graphs silently did nothing, which is exactly what they looked
        like they were doing.

        Text is still the current canvas's job; this only walks the
        blocks that act.
        """
        if self.cfg.get("aio_mode") != "advanced":
            return
        if vals is None:
            vals = self._template_values("")
            top, bottom = self.box_lines()
            vals["box_start"] = top or None
            vals["box_stop"] = bottom or None
        slots = [only] if only is not None else range(AIO_MAX)
        current = self.current_aio_index()
        for idx in slots:
            graph = self.aio_graph(idx)
            # every canvas with anything on it, not just the ones with a
            # side-effect block. Blocks that keep state (a pulse Timer, a
            # Step) only move on during a commit, and skipping a canvas
            # because it merely displays things left its Step sitting on
            # page 1 forever.
            if not graph.get("nodes"):
                continue
            try:
                actions = graph_run_side_effects(
                    graph, vals, osc=getattr(self, "osc_in", None),
                    keys=getattr(self, "hotkey_in", None),
                    procs=self.procs, shown=(idx == current),
                    state=self._graph_state(idx))
            except Exception as e:      # noqa: BLE001
                self.log(f"Advanced mode: AIO {idx + 1} automation "
                         f"failed ({e})")
                continue
            if actions:
                self.run_graph_actions(actions)

    def _graph_state(self, idx=None):
        """Where the graph keeps what has to outlive one frame: when a
        pulse timer last fired, what a Set parameter block last sent,
        which Button is armed.

        One namespace per canvas, because node ids are only unique
        within a canvas - "n1" on AIO 1 and "n1" on AIO 2 are two
        different blocks and must not share a timer.
        """
        if not hasattr(self, "_graph_runtime_state"):
            self._graph_runtime_state = {}
        if idx is None:
            idx = getattr(self, "graph_slot", 0)
        return self._graph_runtime_state.setdefault(int(idx), {})

    def run_graph_actions(self, actions):
        """Carries out what the commit pass asked for."""
        for action in actions:
            try:
                if action[0] == "osc_set":
                    self.send_avatar_parameter(action[1], action[2])
                elif action[0] == "osc_raw":
                    self.send_external_osc(action[1], action[2],
                                           action[3], action[4])
                elif action[0] == "hotkey":
                    self.send_hotkey(action[1])
                elif action[0] == "run_program":
                    self.start_program(action[1], action[2])
                elif action[0] == "aio_change":
                    self._graph_change_aio(action[1])
            except Exception as e:      # noqa: BLE001
                self.log(f"Advanced mode: {action[0]} failed ({e})")

    def _graph_change_aio(self, target):
        """The Change AIO block. Jumps the rotation, and restarts the
        dwell timer so the new string gets its full time on screen
        instead of the remainder of the old one's."""
        slots = self._aio_active_indices()
        if not slots:
            return
        if target == "next":
            self.aio_index += 1
        elif target == "previous":
            self.aio_index -= 1
        else:
            try:
                wanted = int(target) - 1
            except (TypeError, ValueError):
                return
            if wanted not in slots:
                self.log(f"Change AIO: AIO {target} has no Chatbox Output "
                         "block, staying where we are")
                return
            self.aio_index = slots.index(wanted)
        self.aio_index %= max(1, len(slots))
        if self.aio_timer.isActive():
            self.aio_timer.start(self.aio_interval_ms())
        self.log(f"Change AIO: now on AIO {self.current_aio_index() + 1}")

    def send_external_osc(self, ip, port, address, value):
        """One message to an arbitrary OSC target.

        Clients are cached per (ip, port): a UDP socket per send would
        work, but a graph that fires every few seconds would churn
        through file descriptors for no reason.
        """
        ip = (ip or "").strip() or str(self.cfg.get("osc_ext_ip",
                                                    "127.0.0.1"))
        port = int(port) or int(self.cfg.get("osc_ext_port", 9002))
        if not hasattr(self, "_ext_osc_clients"):
            self._ext_osc_clients = {}
        client = self._ext_osc_clients.get((ip, port))
        if client is None:
            if SimpleUDPClient is None:
                self.log("External OSC: python-osc is not installed")
                return
            client = SimpleUDPClient(ip, port)
            self._ext_osc_clients[(ip, port)] = client
        client.send_message(address, value)
        self.log(f"External OSC: {ip}:{port} {address} = {value!r}")

    def reset_ext_osc_clients(self):
        """Drops the cached clients so a changed default target is
        picked up on the next send."""
        self._ext_osc_clients = {}

    def send_hotkey(self, combo):
        """The Send Hotkey block. Failures are logged, not raised - a
        missing key tool must not take the message down with it."""
        if not hasattr(self, "hotkeys"):
            self.hotkeys = HotkeySender(self.log)
        ok, message = self.hotkeys.send(combo)
        if ok:
            self.log(f"Hotkey: {combo}")
        else:
            self.log(f"Hotkey {combo} failed: {message}")

    def start_program(self, command, debug=False):
        """The Start program block."""
        ok, message = launch_program(command, debug)
        if ok:
            self.log(f"Started: {command}"
                     + ("  (debug terminal)" if debug else ""))
        else:
            self.log(f"Could not start {command!r}: {message}")

    def send_avatar_parameter(self, name, value):
        """One /avatar/parameters/<name> write."""
        if self.osc_client is None or not name:
            return
        self.osc_client.send_message(f"/avatar/parameters/{name}", value)
        self.log(f"OSC out: /avatar/parameters/{name} = {value}")

    def build_aio_lines(self, commit=False):
        """Builds the AIO output: one combined custom string with values
        from all active apps.

        Rendered one template line at a time rather than in one go. The
        result is identical - apply_template cleans per line anyway - but
        it keeps the link between an output line and the template line it
        came from, which is what lets a song line that rendered to
        nothing be answered with the idle symbol instead of vanishing.
        """
        tpl = self.current_aio_template()
        advanced = self.aio_is_advanced()
        if not tpl and not advanced:
            return []
        if advanced and self.current_aio_index() < 0:
            # In Advanced mode "no literals" is not "nothing to show": a
            # canvas whose only source is a Clock, a Timer or an Avatar
            # parameter carries no written placeholder at all, and bailing
            # on the empty string here made those graphs silently produce
            # nothing. Whether the slot exists is the Output block's job
            # to answer, and current_aio_index() already asks it.
            return []
        vals = self._template_values(tpl)
        # {box_start} / {box_stop}: place the Custom Box frame yourself
        # instead of having it wrapped around the whole message. They
        # resolve whether or not the card is Active, so All in one can
        # use the frame without the automatic wrapping being on at all.
        top, bottom = self.box_lines()
        vals["box_start"] = top or None
        vals["box_stop"] = bottom or None
        # the middle text on its own, without the frame characters - for
        # layouts that want the clock or the custom text but not the bar
        # it usually sits in
        vals["box_text"] = self._box_middle(SIDE_TOP) or \
            self._box_middle(SIDE_BOTTOM) or None

        idle = self._aio_idle_text()
        if self.aio_is_advanced():
            return self._build_graph_lines(vals, idle)
        lines = []
        idle_used = False
        for tpl_line in tpl.split("\\n"):
            rendered = apply_template(tpl_line, vals)
            if rendered:
                lines.extend(rendered.split("\n"))
            elif idle and not idle_used and self._line_is_media(tpl_line):
                # a line that is about the song and came out empty means
                # there is no song. Only the first one answers, or a
                # layout with a title line AND a bar line AND a lyrics
                # line would stack three identical symbols.
                lines.append(idle)
                idle_used = True
        return lines

    def poll_media(self):
        # Linux: D-Bus round-trips can block for a while (many players /
        # slow players). Windows: fetch() only copies a snapshot the GSMTC
        # poller thread already produced, so it is instant there.
        # Either way this stays off the GUI thread via run_async, and a
        # fetch still in flight is skipped so worker threads cannot pile up.
        if getattr(self, "_media_busy", False):
            return
        self._media_busy = True
        # on_error is not optional here: without it a failing poll
        # would leave _media_busy True forever and this card would
        # silently stop updating for the rest of the session
        self.run_async(
            self.media.fetch, self._on_media_result,
            on_error=lambda _e: setattr(self, "_media_busy", False))

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
            # so a custom / AIO template can follow the same setting
            # instead of hard-coding the symbol into the string
            "lyrics_prefix": self._lyrics_prefix() or None,
        }

    def _media_idle_line(self):
        """What MediaPlay shows when there is no song. [] switches the
        whole thing off, which is what it did before this existed."""
        if not self.cfg.get("media_idle"):
            return []
        text = (self.cfg.get("media_idle_text") or "").strip()
        return [text] if text else []

    def build_media_lines(self):
        """Builds the media text lines based on the checkboxes."""
        info = self.media_info
        if not info:
            # no player at all, or nothing playing in the one there is
            return self._media_idle_line()
        # custom string mode
        if self.cfg["media_custom"] and self.cfg["media_custom_template"].strip():
            text = apply_template(self.cfg["media_custom_template"],
                                  self._media_values(info))
            lines = text.split("\n") if text else []
            if not lines:
                # a custom string that rendered to nothing is the same
                # situation as no player: every value it asked for was
                # empty, so there is no song
                return self._media_idle_line()
            if self.cfg["media_icon"]:
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
            # The preview sets this so a stand-in artist/title never
            # reaches LRCLIB. Nothing else ever touches it, so the live
            # path is byte-for-byte what it always was.
            demo = getattr(self, "_demo_lyrics", None)
            lyr = demo if demo is not None else self.lyrics.current_line(
                info["artist"], info["title"],
                info["length"], info["position"])
            if lyr:
                pre = self._lyrics_prefix()
                lines.append(f"{pre} {lyr}" if pre else lyr)
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
        if not lines:
            # a player is there but nothing survived the checkboxes -
            # an empty title, or every part switched off
            return self._media_idle_line()
        if self.cfg["media_icon"]:
            lines[0] = f"\U0001F3B5 {lines[0]} \U0001F3B5"
        return lines

    def poll_hw(self):
        # snapshot() shells out to nvidia-smi on NVIDIA systems (a subprocess
        # with a timeout) and reads sysfs on AMD – both must stay off the GUI
        # thread. Skip if a previous snapshot is still running.
        if getattr(self, "_hw_busy", False):
            return
        self._hw_busy = True
        # on_error is not optional here: without it a failing poll
        # would leave _hw_busy True forever and this card would
        # silently stop updating for the rest of the session
        self.run_async(
            self.hw.snapshot, self._on_hw_result,
            on_error=lambda _e: setattr(self, "_hw_busy", False))

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
    def _build_wintemp_row(self, indent=24):
        """Windows only: CPU temperatures need a kernel driver, which no
        unelevated process has. See core/backends/wintemp.py for why.

        `indent` was the 24px that tied this block to the CPU checkbox
        above it. Since v1.4.5 it is its own full-width block under the
        component grid, where there is no checkbox to hang off and the
        indent is just a margin - so the caller passes 0.
        """
        outer = QVBoxLayout()
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.addSpacing(indent)
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
        hint_row.addSpacing(indent)
        self.wintemp_lbl = QLabel("\u2139 checking\u2026")
        self.wintemp_lbl.setStyleSheet("color: #7a8290; font-size: 11px;")
        self.wintemp_lbl.setWordWrap(True)
        hint_row.addWidget(self.wintemp_lbl, 1)
        outer.addLayout(hint_row)

        # ----- recommended extra software -----
        rec_row = QHBoxLayout()
        rec_row.addSpacing(indent)
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
        dl_row.addSpacing(indent)
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

    def _hw_display_name(self, which):
        """GPU/CPU name as it goes out: custom > detected > generic, with
        the small-letter style applied. One place for both the plain
        lines and the custom string, so they can never drift apart."""
        c = self.cfg
        if c[f"hw_{which}_custom"] and c[f"hw_{which}_custom_name"].strip():
            name = c[f"hw_{which}_custom_name"].strip()
        elif c[f"hw_{which}_name"]:
            name = (self.hw.gpu_name_auto if which == "gpu"
                    else self.hw.cpu_name_auto)
        else:
            name = which.upper()
        return apply_style(name, c.get(f"hw_{which}_name_style",
                                       STYLE_NORMAL))

    @staticmethod
    def _watt_str(watts):
        """Watts for a chatbox: no decimals above ten, one below.

        A GPU at 213 W does not need a tenth of a watt, and an idle chip
        at 4.2 W reads as a flat "4" without one.
        """
        try:
            watts = float(watts)
        except (TypeError, ValueError):
            return None
        return f"{watts:.0f}W" if watts >= 10 else f"{watts:.1f}W"

    def _hw_values(self, info):
        """Placeholder values for the custom string. They automatically
        follow the checkboxes above (unchecked -> empty / generic name)."""
        c = self.cfg
        gpu = info.get("gpu") or {}
        ram = info.get("ram") or {}
        # names: custom > auto-detected (if "name" is checked) > generic
        gpu_name = self._hw_display_name("gpu")
        cpu_name = self._hw_display_name("cpu")
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
        # Watts, behind their own checkboxes like every other sensor on
        # the card. Both off by default - see ui/config_mixin.py. Empty
        # whenever nothing reports a value: NVIDIA always does, AMD needs
        # amdgpu's hwmon, and CPU watts need zenpower or readable RAPL
        # counters (LibreHardwareMonitor on Windows).
        gpu_power = gpu.get("power") if c["hw_gpu_power"] else None
        cpu_power = info.get("cpu_power") if c["hw_cpu_power"] else None
        return {
            "gpu_power": (self._watt_str(gpu_power)
                          if gpu_power is not None else None),
            "cpu_power": (self._watt_str(cpu_power)
                          if cpu_power is not None else None),
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
        parts.append(self._hw_display_name("gpu"))
        vals = []
        if self.cfg["hw_gpu_usage"] and gpu.get("usage") is not None:
            vals.append(f"{gpu['usage']:.0f}%")
        if self.cfg["hw_gpu_temp"] and gpu.get("temp") is not None:
            vals.append(self._temp_str(gpu["temp"]))
        if self.cfg["hw_gpu_power"] and gpu.get("power") is not None:
            vals.append(self._watt_str(gpu["power"]))
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
        cname = self._hw_display_name("cpu")
        cvals = []
        if self.cfg["hw_cpu_usage"] and info.get("cpu_usage") is not None:
            cvals.append(f"{info['cpu_usage']:.0f}%")
        if self.cfg["hw_cpu_temp"] and info.get("cpu_temp") is not None:
            cvals.append(self._temp_str(info["cpu_temp"]))
        if self.cfg["hw_cpu_power"] and info.get("cpu_power") is not None:
            cvals.append(self._watt_str(info["cpu_power"]))
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
