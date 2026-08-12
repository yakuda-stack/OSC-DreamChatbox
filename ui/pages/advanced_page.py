"""
ui/pages/advanced_page.py – the "Advanced mode" page: one node canvas per
AIO string, built by dragging blocks around instead of typing a template.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.

The canvas itself (items, wiring, serialisation) lives in
ui/nodegraph.py and the evaluation in core/nodegraph_eval.py; this file
is the page around them.

Layout mirrors the All in one card on purpose: the same "Number of
strings" and "Rotate strings every N sec" at the top, and AIO 1-5 as
tabs instead of five text fields under each other. Same settings, same
config keys, same rotation - only the way a string is built differs
between the two modes.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget)

from core.constants import AIO_MAX
from core.hotkeys import IS_WINDOWS
from core.hotkeys import describe as describe_hotkey
from core.nodegraph_eval import node_count
from ui.nodegraph import (
    BlockTree, NodeCanvas, OscParamPalette, VariableTree)
from ui.pages.placeholder_picker import (
    BOX_ITEMS, CHAT_GROUPS, HARDWARE_GROUPS, MEDIA_ITEMS)

#: pulls the {name} back out of the picker tables, which spell their
#: entries with the braces on
_PLACEHOLDER_RE = re.compile(r"\{([a-z0-9_]+)\}", re.IGNORECASE)


class AdvancedPageMixin:
    # ------------------------------------------------------------------
    # page
    # ------------------------------------------------------------------
    def build_advanced_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("Advanced mode")
        title.setObjectName("pagetitle")
        layout.addWidget(title)

        intro = QLabel(
            "Build the All in one strings visually. Each AIO string has "
            "its own canvas \u2013 pick it with the tabs above the "
            "canvas, drag blocks and variables out of the palette on the "
            "left, then drag from an output dot "
            "to an input dot to connect them. Every canvas ends in a "
            "Chatbox Output block; a canvas without one is skipped by the "
            "rotation. Middle mouse button pans, the wheel zooms, Delete "
            "removes what is selected.")
        intro.setObjectName("dim")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        card = QFrame()
        card.setObjectName("card")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(16, 14, 16, 16)
        c_layout.setSpacing(12)

        c_layout.addWidget(self._build_graph_template_box())
        c_layout.addLayout(self._build_graph_rotation_row())
        c_layout.addLayout(self._build_graph_toolbar())

        # ---- palette | canvas | inspector -----------------------------
        split = QHBoxLayout()
        split.setSpacing(6)
        self.graph_palette_panel = self._build_node_palette()
        split.addWidget(self._collapsible(
            self.graph_palette_panel, "left", "Blocks & variables",
            self.graph_palette_hide))

        self.graph_canvas = NodeCanvas()
        self.graph_canvas.setObjectName("nodecanvas")
        self.graph_canvas.node_scene.graphChanged.connect(
            self.on_graph_changed)
        self.graph_canvas.selectionChanged.connect(self.on_graph_selection)
        split.addWidget(self.graph_canvas, 1)

        self.graph_inspector_panel = self._build_node_inspector()
        split.addWidget(self._collapsible(
            self.graph_inspector_panel, "right", "Block inspector",
            self.graph_inspector_hide))
        c_layout.addLayout(split, 1)

        layout.addWidget(card, 1)
        return page

    # ------------------------------------------------------------------
    def _build_graph_template_box(self):
        """The ten AIO templates, collapsed by default.

        The same ten sets the All in one card switches between, on the
        same config keys - a template holds its strings, its count, its
        dwell times and its canvases. Folded away because
        most sessions use one template and never touch this, and an
        always-open row of ten buttons would push the canvas down for
        everyone to serve the minority who switch.
        """
        box = QFrame()
        box.setObjectName("innerbox")
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(8)

        head_row = QHBoxLayout()
        self.graph_template_toggle = QPushButton("\u25b8  Template")
        self.graph_template_toggle.setObjectName("linkbtn")
        self.graph_template_toggle.setCheckable(True)
        self.graph_template_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.graph_template_toggle.toggled.connect(self._toggle_template_box)
        head_row.addWidget(self.graph_template_toggle)
        self.graph_template_lbl = QLabel("")
        self.graph_template_lbl.setObjectName("dim")
        head_row.addWidget(self.graph_template_lbl)
        head_row.addStretch()
        v.addLayout(head_row)

        self.graph_template_body = QWidget()
        body = QVBoxLayout(self.graph_template_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.graph_set_group = QButtonGroup(self)
        self.graph_set_group.setExclusive(True)
        self.graph_set_buttons = []
        for i in range(10):
            b = QPushButton(str(i + 1))
            b.setObjectName("slottab")
            b.setCheckable(True)
            b.setFixedWidth(34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(f"AIO template {i + 1} \u2013 its own strings, "
                         "canvases, count and dwell times")
            self.graph_set_group.addButton(b, i)
            btn_row.addWidget(b)
            self.graph_set_buttons.append(b)
        self.graph_set_group.idClicked.connect(self.on_graph_set)
        btn_row.addStretch()
        body.addLayout(btn_row)
        note = QLabel("The same ten templates as on the All in one card. "
                      "Each keeps its own strings, canvases, number of "
                      "strings and dwell times.")
        note.setObjectName("dim")
        note.setWordWrap(True)
        body.addWidget(note)
        v.addWidget(self.graph_template_body)
        self.graph_template_body.setVisible(False)
        return box

    def _toggle_template_box(self, open_):
        self.graph_template_body.setVisible(open_)
        self.graph_template_toggle.setText(
            ("\u25be  Template" if open_ else "\u25b8  Template"))

    def _sync_graph_set_buttons(self):
        idx = int(self.cfg.get("aio_set_active", 0))
        for i, b in enumerate(self.graph_set_buttons):
            b.setChecked(i == idx)
        self.graph_template_lbl.setText(f"{idx + 1} active")

    def on_graph_set(self, idx):
        if idx == int(self.cfg.get("aio_set_active", 0)):
            return
        self.on_aio_set(idx)
        # the card's own buttons are the other view of this setting
        if hasattr(self, "aio_set_buttons"):
            self.aio_set_buttons[idx].setChecked(True)

    def _build_graph_rotation_row(self):
        """The same two settings the All in one card has, on the same
        config keys. They belong to the strings, not to a mode, so
        changing one here changes it there."""
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Number of strings"))
        self.graph_count_spin = QSpinBox()
        self.graph_count_spin.setObjectName("smallspin")
        self.graph_count_spin.setRange(1, AIO_MAX)
        self.graph_count_spin.setFixedSize(64, 28)
        self.graph_count_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.graph_count_spin.valueChanged.connect(self.on_graph_count)
        row.addWidget(self.graph_count_spin)
        row.addSpacing(16)

        self.graph_rotate_chk = QCheckBox("Rotate strings every")
        self.graph_rotate_chk.toggled.connect(self.on_graph_rotate)
        row.addWidget(self.graph_rotate_chk)
        self.graph_rotate_spin = QSpinBox()
        self.graph_rotate_spin.setObjectName("smallspin")
        self.graph_rotate_spin.setRange(2, 3600)
        self.graph_rotate_spin.setFixedSize(72, 28)
        self.graph_rotate_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.graph_rotate_spin.valueChanged.connect(self.on_graph_rotate_sec)
        row.addWidget(self.graph_rotate_spin)
        row.addWidget(QLabel("sec"))
        row.addStretch()

        hint = QLabel("shared with the All in one card")
        hint.setObjectName("dim")
        row.addWidget(hint)
        return row

    def _build_graph_toolbar(self):
        """Slot tabs on the left, actions on the right.

        The tabs used to be a column down the side, which cost the canvas
        190 px of width to say five words. Up here they read like browser
        tabs - which is what they are - and the canvas gets the space
        back.
        """
        bar = QHBoxLayout()
        bar.setSpacing(3)

        aio_lbl = QLabel("AIO:")
        aio_lbl.setObjectName("dim")
        bar.addWidget(aio_lbl)

        # bare numbers, and only as many as "Number of strings" allows.
        # Ten tabs reading "AIO 7" would be most of the header width
        # spent repeating a word that is already written to their left,
        # and offering a canvas that the rotation will never reach is
        # offering somewhere to lose work.
        self.graph_slot_group = QButtonGroup(self)
        self.graph_slot_group.setExclusive(True)
        self.graph_slot_buttons = []
        for i in range(AIO_MAX):
            b = QPushButton(str(i + 1))
            b.setObjectName("slottab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedWidth(34)
            self.graph_slot_group.addButton(b, i)
            bar.addWidget(b)
            self.graph_slot_buttons.append(b)
        self.graph_slot_group.idClicked.connect(self.on_graph_slot)
        self.graph_slot_buttons[0].setChecked(True)

        bar.addSpacing(14)
        self.graph_status_lbl = QLabel("")
        self.graph_status_lbl.setObjectName("dim")
        bar.addWidget(self.graph_status_lbl)
        bar.addStretch()

        btn_fit = QPushButton("Reset view")
        btn_fit.setObjectName("linkbtn")
        btn_fit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_fit.clicked.connect(self.on_graph_reset_view)
        bar.addWidget(btn_fit)

        btn_clear = QPushButton("Clear canvas")
        btn_clear.setObjectName("linkbtn")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setToolTip("Removes every block and wire on THIS canvas.")
        btn_clear.clicked.connect(self.on_graph_clear)
        bar.addWidget(btn_clear)

        back = QPushButton("\u2039  Back to Apps")
        back.setObjectName("linkbtn")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(lambda: self.switch_page(self.PAGE_APPS))
        bar.addWidget(back)
        return bar

    def _collapsible(self, panel, side, name, hide_button):
        """Wraps a side panel so it can fold away.

        Two visible controls rather than one thin arrow at the edge: the
        button in the panel's own header row, which is where you are
        already looking when you decide the panel is in the way, and a
        full-size tab that stays behind at the top once it is gone. A
        14 px sliver at the canvas edge was findable only if you knew it
        was there.

        Because the canvas is the only stretching item in the row, the
        width freed by collapsing goes to it without any resizing.
        """
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # what is left when the panel is gone: a tab pinned to the top
        strip = QWidget()
        strip_col = QVBoxLayout(strip)
        strip_col.setContentsMargins(0, 0, 0, 0)
        strip_col.setSpacing(0)
        show_btn = QPushButton("\u203a\u2016" if side == "left"
                               else "\u2016\u2039")
        show_btn.setObjectName("panelshow")
        show_btn.setFixedSize(30, 30)
        show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        show_btn.setToolTip(f"Show {name}")
        strip_col.addWidget(show_btn)
        strip_col.addStretch()

        def apply(collapsed):
            panel.setVisible(not collapsed)
            strip.setVisible(collapsed)

        hide_button.setToolTip(f"Hide {name}")
        hide_button.clicked.connect(lambda: apply(True))
        show_btn.clicked.connect(lambda: apply(False))
        apply(False)

        if side == "left":
            row.addWidget(panel)
            row.addWidget(strip)
        else:
            row.addWidget(strip)
            row.addWidget(panel)
        return holder

    def _panel_hide_button(self, side):
        """The collapse button that sits in a panel's own header row."""
        b = QPushButton("\u2016\u2039" if side == "left"
                        else "\u203a\u2016")
        b.setObjectName("panelhide")
        b.setFixedSize(26, 22)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _build_node_palette(self):
        box = QFrame()
        box.setObjectName("innerbox")
        box.setFixedWidth(196)
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(6)

        head_row = QHBoxLayout()
        head = QLabel("Blocks")
        head.setObjectName("cardtitle")
        head_row.addWidget(head)
        head_row.addStretch()
        self.graph_palette_hide = self._panel_hide_button("left")
        head_row.addWidget(self.graph_palette_hide)
        v.addLayout(head_row)
        hint = QLabel("Drag onto the canvas")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self.graph_block_tree = BlockTree()
        v.addWidget(self.graph_block_tree, 1)

        # ---- avatar parameters ----------------------------------------
        osc_head = QLabel("Avatar parameters")
        osc_head.setObjectName("cardtitle")
        v.addWidget(osc_head)
        self.graph_osc_hint = QLabel("")
        self.graph_osc_hint.setObjectName("dim")
        self.graph_osc_hint.setWordWrap(True)
        v.addWidget(self.graph_osc_hint)
        self.graph_osc_list = OscParamPalette()
        v.addWidget(self.graph_osc_list)

        # ---- variables ------------------------------------------------
        var_head = QLabel("Variables")
        var_head.setObjectName("cardtitle")
        v.addWidget(var_head)
        var_hint = QLabel("Everything a typed AIO string can use, grouped "
                          "like the \u201c+\u201d menu \u2013 drag one "
                          "over and it arrives as a ready-made block.")
        var_hint.setObjectName("dim")
        var_hint.setWordWrap(True)
        v.addWidget(var_hint)

        self.graph_var_search = QLineEdit()
        self.graph_var_search.setPlaceholderText("Search \u2026")
        self.graph_var_search.setClearButtonEnabled(True)
        self.graph_var_search.textChanged.connect(
            lambda t: self.graph_var_list.apply_filter(t))
        v.addWidget(self.graph_var_search)

        self.graph_var_list = VariableTree()
        v.addWidget(self.graph_var_list, 1)
        return box

    def _build_node_inspector(self):
        box = QFrame()
        box.setObjectName("innerbox")
        box.setFixedWidth(232)
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)

        head_row = QHBoxLayout()
        self.graph_inspector_hide = self._panel_hide_button("right")
        head_row.addWidget(self.graph_inspector_hide)
        head = QLabel("Block")
        head.setObjectName("cardtitle")
        head_row.addWidget(head)
        head_row.addStretch()
        v.addLayout(head_row)

        self.graph_inspect_title = QLabel("Nothing selected")
        self.graph_inspect_title.setWordWrap(True)
        v.addWidget(self.graph_inspect_title)

        self.graph_inspect_note = QLabel(
            "Click a block on the canvas to edit its values.")
        self.graph_inspect_note.setObjectName("dim")
        self.graph_inspect_note.setWordWrap(True)
        v.addWidget(self.graph_inspect_note)

        # the fields of the selected node are rebuilt in here on every
        # selection change - a handful of widgets, so throwing them away
        # is cheaper than keeping one set per node type alive
        self.graph_fields_host = QWidget()
        self.graph_fields_layout = QVBoxLayout(self.graph_fields_host)
        self.graph_fields_layout.setContentsMargins(0, 4, 0, 0)
        self.graph_fields_layout.setSpacing(6)
        v.addWidget(self.graph_fields_host)

        v.addStretch()

        self.graph_delete_btn = QPushButton("Delete block")
        self.graph_delete_btn.setObjectName("linkbtn")
        self.graph_delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.graph_delete_btn.setEnabled(False)
        self.graph_delete_btn.clicked.connect(self.on_graph_delete_selected)
        v.addWidget(self.graph_delete_btn)
        return box

    # ------------------------------------------------------------------
    # variables
    # ------------------------------------------------------------------
    def graph_variable_groups(self):
        """[(group, [(name, note)])] in the same order and wording the
        \u201c+\u201d picker uses on a normal AIO field.

        Read straight from that module's tables plus the live status
        templates and installed plugins, so the canvas and the menu can
        never disagree about what exists.
        """
        def strip(items):
            out = []
            for name, note in items:
                match = _PLACEHOLDER_RE.fullmatch(name.strip())
                if match:
                    out.append((match.group(1), note))
            return out

        groups = [("Personal Status", [
            ("text", "the rotating status text"),
        ] + [(f"text_{i}", f"status slot {i}") for i in range(1, 21)]
            + [(f"text_t{t}", f"the rotating text of template {t}")
               for t in range(1, 11)])]
        for name, items in HARDWARE_GROUPS:
            groups.append((f"Hardware \u2013 {name}", strip(items)))
        groups.append(("Media", strip(MEDIA_ITEMS)))
        groups.append(("Custom Box", strip(BOX_ITEMS)))
        chat = []
        for name, items in CHAT_GROUPS:
            chat.extend((n, f"{name}: {note}") for n, note in strip(items))
        groups.append(("Chat / Speech to Text", chat))

        plugins = [p for p in self.plugins.ordered() if p.supported]
        for plugin in plugins:
            items = [(plugin.pid, "the plugin's own line")]
            for key, note in (plugin.placeholders or {}).items():
                items.append((f"{plugin.pid}_{key}", note or key))
            for key in sorted(plugin.global_keys or ()):
                items.append((key, "claimed by this plugin"))
            groups.append((f"Plugin: {plugin.name or plugin.pid}", items))
        return groups

    def refresh_graph_variables(self):
        if hasattr(self, "graph_var_list"):
            self.graph_var_list.set_groups(self.graph_variable_groups())
        self.refresh_graph_osc_params()

    def refresh_graph_osc_params(self):
        """Repaints the received-parameter list. Cheap, and called when
        the page is opened rather than on a timer - the list only has to
        be right at the moment somebody reaches for it."""
        if not hasattr(self, "graph_osc_list"):
            return
        listener = getattr(self, "osc_in", None)
        params = listener.snapshot() if listener is not None else {}
        self.graph_osc_list.set_parameters(params)
        if not self.cfg.get("osc_input_enabled"):
            self.graph_osc_hint.setText(
                "OSC input is off \u2013 switch it on under Options to "
                "see what your avatar is sending.")
        elif not params:
            self.graph_osc_hint.setText(
                "Listening, nothing received yet. Move a toggle in VRChat "
                "and it turns up here.")
        else:
            self.graph_osc_hint.setText(
                f"{len(params)} seen \u2013 drag one onto the canvas.")

    # ------------------------------------------------------------------
    # canvas <-> config
    # ------------------------------------------------------------------
    def load_graph_into_ui(self):
        """Called once from apply_config_to_ui()."""
        self.graph_slot = 0
        self.graph_canvas.apply_tokens(self.current_theme_tokens())
        self.graph_count_spin.setValue(self.cfg["aio_count"])
        self.graph_rotate_chk.setChecked(self.cfg["aio_rotate"])
        self.graph_rotate_spin.setValue(self.cfg["aio_rotate_sec"])
        self.refresh_graph_variables()
        self._sync_graph_set_buttons()
        self._show_graph_slot(0)

    def _show_graph_slot(self, idx):
        """Swaps the canvas over to another AIO string. The one leaving
        is written back first - the canvas is the live copy while it is
        on screen, the config is the record."""
        self.graph_slot = idx
        for i, b in enumerate(self.graph_slot_buttons):
            b.setChecked(i == idx)
        scene = self.graph_canvas.node_scene
        scene.blockSignals(True)
        try:
            scene.from_dict(self.aio_graph(idx))
        finally:
            scene.blockSignals(False)
        self.graph_canvas.reset_zoom()
        self.on_graph_selection(None)
        self._update_graph_status()
        self._update_graph_slot_labels()

    def _update_graph_slot_labels(self):
        """Marks the strings that are switched off (beyond "Number of
        strings") and the ones that have nothing on them yet, so the
        column says which canvas is worth opening."""
        count = self.cfg["aio_count"]
        for i, b in enumerate(self.graph_slot_buttons):
            if i == self.graph_slot:
                blocks = len(self.graph_canvas.node_scene.nodes())
            else:
                blocks = node_count(self.aio_graph(i))
            # hidden, not greyed out: a disabled tab is still width spent
            # on something you cannot use
            b.setVisible(i < count)
            # a filled canvas gets a dot, the way an unsaved tab does
            b.setText(f"{i + 1}\u2022" if blocks else str(i + 1))
            b.setToolTip(
                f"The canvas for AIO string {i + 1}  \u2013  "
                + (f"{blocks} blocks" if blocks else "empty"))
        # lowering the count must not leave the editor sitting on a
        # canvas that is no longer reachable
        if self.graph_slot >= count:
            self._store_current_graph()
            self._show_graph_slot(count - 1)

    def on_graph_slot(self, idx):
        # a slot beyond "Number of strings" has no tab to click, but it
        # can still be reached programmatically - and switching to one
        # would hand the canvas a graph the label pass then snaps away
        # from, leaving edits landing on the wrong slot
        if idx >= self.cfg["aio_count"] or idx == getattr(self, "graph_slot", 0):
            return
        self._store_current_graph()
        self._show_graph_slot(idx)

    def _store_current_graph(self):
        graphs = list(self.cfg.get("aio_graphs") or [])
        while len(graphs) < 5:
            graphs.append({"nodes": [], "edges": []})
        graphs[getattr(self, "graph_slot", 0)] = \
            self.graph_canvas.node_scene.to_dict()
        self.cfg["aio_graphs"] = graphs

    # ------------------------------------------------------------------
    # handlers
    # ------------------------------------------------------------------
    def on_graph_changed(self):
        if getattr(self, "_block_updating", False):
            return
        self._store_current_graph()
        # the active template owns the canvases the same way it owns the
        # strings; without this, switching template and back would come
        # home to an empty canvas
        self._sync_active_aio_set()
        self.save_config_later()
        self._update_graph_status()
        self._update_graph_slot_labels()
        # adding or removing the Chatbox Output block changes whether
        # this string is on rotation at all, so the timer has to be told
        if self.cfg.get("aio_mode") == "advanced":
            self.update_timers()
            self.update_preview()

    def _update_graph_status(self):
        scene = self.graph_canvas.node_scene
        n, e = len(scene.nodes()), len(scene.edges())
        outs = [x for x in scene.nodes() if x.type_id == "output"]
        if not outs:
            warn = "  \u2013  no Chatbox Output block yet"
        elif len(outs) > 1:
            # a canvas is one AIO string, so a second Output is not a
            # second message - it is a block whose whole subtree never
            # runs. Silently ignoring it looked exactly like a bug in
            # the wiring, so say it out loud.
            warn = (f"  \u2013  \u26a0 {len(outs)} Chatbox Output blocks, "
                    "only one canvas: chain the Info blocks into a single "
                    "Output, or move the second part to another AIO "
                    "string")
        else:
            warn = ""
        self.graph_status_lbl.setText(
            f"{n} block{'' if n == 1 else 's'}, "
            f"{e} connection{'' if e == 1 else 's'}{warn}")

    def on_graph_count(self, val):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_count"] = val
        self._sync_active_aio_set()
        self.save_config()
        # keep the All in one card in step - same setting, two places
        self.aio_count_spin.blockSignals(True)
        self.aio_count_spin.setValue(val)
        self.aio_count_spin.blockSignals(False)
        for i, row in enumerate(self.aio_rows):
            row.setVisible(i < val)
        self._update_graph_slot_labels()
        self.aio_index = 0
        self.update_timers()
        self.update_preview()

    def on_graph_rotate(self, on):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_rotate"] = on
        self.save_config()
        self.chk_aio_rotate.blockSignals(True)
        self.chk_aio_rotate.setChecked(on)
        self.chk_aio_rotate.blockSignals(False)
        self.aio_index = 0
        self.update_timers()
        self.update_preview()

    def on_graph_rotate_sec(self, val):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["aio_rotate_sec"] = val
        self.save_config()
        self.aio_rotate_spin.blockSignals(True)
        self.aio_rotate_spin.setValue(val)
        self.aio_rotate_spin.blockSignals(False)
        self.update_timers()

    def on_graph_reset_view(self):
        self.graph_canvas.reset_zoom()
        nodes = self.graph_canvas.node_scene.nodes()
        if nodes:
            self.graph_canvas.centerOn(nodes[0])

    def on_graph_clear(self):
        self.graph_canvas.node_scene.clear_graph()
        self.on_graph_selection(None)
        self.log(f"Advanced mode: canvas of AIO "
                 f"{getattr(self, 'graph_slot', 0) + 1} cleared")

    def on_graph_delete_selected(self):
        if self.graph_canvas.node_scene.delete_selected():
            self.on_graph_selection(None)

    def on_graph_selection(self, node):
        """Rebuilds the inspector for the selected block."""
        while self.graph_fields_layout.count():
            item = self.graph_fields_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        self.graph_delete_btn.setEnabled(node is not None)
        if node is None:
            self.graph_inspect_title.setText("Nothing selected")
            self.graph_inspect_note.setText(
                "Click a block on the canvas to edit its values.")
            return

        self.graph_inspect_title.setText(node.definition["title"])
        self.graph_inspect_note.setText(node.definition["note"])
        for key, kind, label, default, extra in node.definition["fields"]:
            if kind != "action":
                lbl = QLabel(label)
                lbl.setObjectName("dim")
                self.graph_fields_layout.addWidget(lbl)
            self.graph_fields_layout.addWidget(
                self._build_node_field(node, key, kind, default, extra))
        if any(f[1] == "hotkey" for f in node.definition["fields"]):
            # a combination that will not do anything should say so while
            # you are typing it, not the first time the graph fires
            self.graph_hotkey_note = QLabel("")
            self.graph_hotkey_note.setObjectName("dim")
            self.graph_hotkey_note.setWordWrap(True)
            self.graph_fields_layout.addWidget(self.graph_hotkey_note)
            self._update_hotkey_note(node)

    def _update_hotkey_note(self, node):
        note = getattr(self, "graph_hotkey_note", None)
        if note is None or note.parent() is None:
            return
        ok, text = describe_hotkey(node.values.get("keys", ""))
        sender = getattr(self, "hotkeys", None)
        if ok and sender is not None and not sender.available():
            text += f"  \u2013  but {sender.missing_hint()}"
        note.setText(("\u2713  " if ok else "\u26a0  ") + text)

    def _running_process_names(self):
        watcher = getattr(self, "procs", None)
        return watcher.names() if watcher is not None else set()

    def on_graph_button(self, node):
        """The Button block was pressed in the inspector.

        Arms the block and sends straight away rather than waiting for
        the next tick - the point of a manual trigger is seeing what it
        does now, and up to a full send interval of nothing would read
        as a broken button.
        """
        self._store_current_graph()          # makes sure the node has an id
        state = self._graph_state(self.graph_slot)
        key = ("button", node.node_id)
        if str(node.values.get("mode", "pulse")) == "toggle":
            state[key] = not state.get(key)
            self.log(f"Button: {'on' if state[key] else 'off'}")
        else:
            state[key] = True
            self.log("Button: triggered")
        # act now, on this canvas, without waiting for the send tick -
        # the point of a manual trigger is seeing what it does, and a
        # canvas that is pure automation never becomes "the current
        # slot" to be picked up by a normal send at all
        self.run_graph_automation(only=self.graph_slot)
        self.update_preview()
        if self.cfg.get("aio_active") and \
                self.graph_slot == self.current_aio_index():
            self.send_now()

    def _build_node_field(self, node, key, kind, default, extra):
        value = node.values.get(key, default)
        if kind == "action":
            w = QPushButton(str(default or "Trigger"))
            w.setObjectName("sendbtn")
            w.setMinimumHeight(30)
            w.setCursor(Qt.CursorShape.PointingHandCursor)
            w.clicked.connect(lambda _=False, n=node: self.on_graph_button(n))
            return w
        if kind == "multiline":
            w = QPlainTextEdit(str(value or ""))
            w.setObjectName("aioedit")
            w.setFixedHeight(72)
            w.textChanged.connect(
                lambda n=node, k=key, e=w:
                    self._set_node_value(n, k, e.toPlainText()))
            return w
        if kind == "int":
            low, high = extra or (0, 100)
            w = QSpinBox()
            w.setObjectName("smallspin")
            w.setRange(int(low), int(high))
            try:
                w.setValue(int(value))
            except (TypeError, ValueError):
                w.setValue(int(default))
            w.valueChanged.connect(
                lambda v, n=node, k=key: self._set_node_value(n, k, int(v)))
            return w
        if kind == "choice":
            w = QComboBox()
            for choice in (extra or []):
                w.addItem(str(choice))
            idx = w.findText(str(value))
            w.setCurrentIndex(idx if idx >= 0 else 0)
            w.currentTextChanged.connect(
                lambda t, n=node, k=key: self._set_node_value(n, k, t))
            return w
        if kind in ("file", "process"):
            w = PathPicker(str(value or ""), browse=(kind == "file"),
                           processes=self._running_process_names)
            w.valueChanged.connect(
                lambda t, n=node, k=key: self._set_node_value(n, k, t))
            return w
        if kind == "hotkey":
            w = HotkeyEdit(str(value or ""))
            w.valueChanged.connect(
                lambda t, n=node, k=key: self._set_node_value(n, k, t))
            w.valueChanged.connect(
                lambda _t, n=node: self._update_hotkey_note(n))
            return w
        w = QLineEdit(str(value or ""))
        w.textChanged.connect(
            lambda t, n=node, k=key: self._set_node_value(n, k, t))
        return w

    def _set_node_value(self, node, key, value):
        if node.values.get(key) == value:
            return
        node.values[key] = value
        dynamic = node.definition.get("dynamic_inputs")
        if dynamic and key == dynamic[0]:
            # the field decides how many sockets there are, so the block
            # has to be redrawn before anything reads it again
            node.rebuild_sockets()
        node.update()          # the block shows the first field inline
        self.on_graph_changed()


#: Qt key codes that are modifiers and never a combination on their own
_MODIFIER_KEYS = {
    Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
    Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_Super_L,
    Qt.Key.Key_Super_R,
}

#: Qt key -> the name core/hotkeys.py understands. Anything not in here
#: falls back to the character Qt reports, which is right for letters,
#: digits and punctuation.
_QT_KEY_NAMES = {
    Qt.Key.Key_Escape: "escape", Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter", Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Space: "space", Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete", Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup", Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
    Qt.Key.Key_Print: "printscreen", Qt.Key.Key_Pause: "pause",
    Qt.Key.Key_VolumeMute: "volumemute",
    Qt.Key.Key_VolumeDown: "volumedown",
    Qt.Key.Key_VolumeUp: "volumeup",
    Qt.Key.Key_MediaPlay: "mediaplay", Qt.Key.Key_MediaStop: "mediastop",
    Qt.Key.Key_MediaPrevious: "mediaprev",
    Qt.Key.Key_MediaNext: "medianext",
}
_QT_KEY_NAMES.update({getattr(Qt.Key, f"Key_F{i}"): f"f{i}"
                      for i in range(1, 36)
                      if hasattr(Qt.Key, f"Key_F{i}")})


class HotkeyEdit(QWidget):
    """A text field for a key combination that you can also just press.

    Typing "ctrl+shift+m" still works - the field is a normal QLineEdit
    the rest of the time. Press Record and it listens instead: hold the
    modifiers, press the key, done. Which matters because half the
    useful combinations are ones nobody knows the written name of, and
    "was that meta or super or win" is not a question worth asking the
    user.

    Recording stops on the first non-modifier key, so a combination is
    exactly one press and there is no "now click somewhere to finish".
    """

    valueChanged = pyqtSignal(str)

    def __init__(self, value="", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.edit = QLineEdit(str(value or ""))
        self.edit.setPlaceholderText("ctrl+shift+m  \u2013  or press Record")
        self.edit.textChanged.connect(self.valueChanged.emit)
        row.addWidget(self.edit, 1)

        self.record_btn = QPushButton("\u25cf")
        self.record_btn.setObjectName("recordbtn")
        self.record_btn.setCheckable(True)
        self.record_btn.setFixedSize(30, 26)
        self.record_btn.setToolTip("Record a key combination")
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.toggled.connect(self._set_recording)
        row.addWidget(self.record_btn)

        self._recording = False

    # ------------------------------------------------------------------
    def value(self):
        return self.edit.text()

    def _set_recording(self, on):
        self._recording = on
        self.record_btn.setText("\u25a0" if on else "\u25cf")
        if on:
            self.edit.setReadOnly(True)
            self.edit.setPlaceholderText("press the keys \u2026")
            self._previous = self.edit.text()
            self.edit.clear()
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.grabKeyboard()
        else:
            self.releaseKeyboard()
            self.edit.setReadOnly(False)
            self.edit.setPlaceholderText(
                "ctrl+shift+m  \u2013  or press Record")
            if not self.edit.text():
                # stopped without pressing anything: put back what was
                # there rather than silently clearing a working hotkey
                self.edit.setText(getattr(self, "_previous", ""))

    # ------------------------------------------------------------------
    def keyPressEvent(self, ev):
        if not self._recording:
            super().keyPressEvent(ev)
            return
        mods = []
        m = ev.modifiers()
        if m & Qt.KeyboardModifier.ControlModifier:
            mods.append("ctrl")
        if m & Qt.KeyboardModifier.AltModifier:
            mods.append("alt")
        if m & Qt.KeyboardModifier.ShiftModifier:
            mods.append("shift")
        if m & Qt.KeyboardModifier.MetaModifier:
            mods.append("super")

        key = Qt.Key(ev.key()) if ev.key() else None
        if key in _MODIFIER_KEYS or key is None:
            # Qt reports the modifier state as it was BEFORE this press,
            # so the first modifier down would otherwise show nothing at
            # all and the field would look dead
            held = {Qt.Key.Key_Control: "ctrl", Qt.Key.Key_Alt: "alt",
                    Qt.Key.Key_AltGr: "alt", Qt.Key.Key_Shift: "shift",
                    Qt.Key.Key_Meta: "super",
                    Qt.Key.Key_Super_L: "super",
                    Qt.Key.Key_Super_R: "super"}.get(key)
            if held and held not in mods:
                mods.append(held)
            self.edit.setText("+".join(mods) + ("+" if mods else ""))
            ev.accept()
            return

        name = _QT_KEY_NAMES.get(key)
        if name is None:
            text = ev.text().strip()
            name = text.lower() if text and text.isprintable() else ""
        if not name:
            ev.accept()
            return
        self.edit.setText("+".join(mods + [name]))
        self.record_btn.setChecked(False)
        ev.accept()

    def focusOutEvent(self, ev):
        if self._recording:
            self.record_btn.setChecked(False)
        super().focusOutEvent(ev)


#: process names that are the kernel talking to itself. Hundreds of them
#: on a normal Linux box, and never the thing anybody is looking for.
_KERNEL_PREFIXES = (
    "kworker", "ksoftirqd", "migration", "rcu_", "irq/", "idle_inject",
    "kdevtmpfs", "kthread", "kcompactd", "khugepaged", "kswapd",
    "watchdogd", "oom_reaper", "writeback", "cpuhp", "netns", "kintegrityd",
    "kblockd", "blkcg_punt", "ata_sff", "md", "edac-poller", "devfreq_wq",
    "scsi_", "kstrp", "charger_manager", "acpi_thermal", "zswap",
)


def _interesting(name):
    """Filters the process list down to things a person would recognise."""
    if not name or name.startswith("(") or "/" in name:
        return False
    return not any(name.startswith(p) for p in _KERNEL_PREFIXES)


class ProcessPickerDialog(QDialog):
    """Pick from what is running right now.

    A menu would have been less code and unusable: a normal desktop has
    several hundred processes, so this is a list with a filter on top.
    Double-click or Enter picks, because that is what a list like this
    is expected to do.
    """

    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Running programs")
        self.setMinimumSize(360, 420)
        self.chosen = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        hint = QLabel("Pick a program that is running now. Part of the "
                      "name is enough \u2013 it is matched as a substring.")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search \u2026")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._accept())
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton("Use this")
        ok.setObjectName("sendbtn")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        row.addWidget(ok)
        layout.addLayout(row)

        self._all = sorted({n for n in names if _interesting(n)},
                           key=str.lower)
        self._filter("")

    def _filter(self, text=""):
        text = (text or "").strip().lower()
        self.list.clear()
        self.list.addItems([n for n in self._all if not text or text in n])
        if self.list.count():
            self.list.setCurrentRow(0)

    def _accept(self):
        item = self.list.currentItem()
        if item is not None:
            self.chosen = item.text()
            self.accept()


class PathPicker(QWidget):
    """A text field with a folder button, and optionally a button that
    lists what is running.

    The typed field stays the real value - a command can have arguments
    and no file dialog will ever produce `mangohud --dlsym %command%`.
    The buttons are shortcuts into it, not replacements for it.
    """

    valueChanged = pyqtSignal(str)

    def __init__(self, value="", browse=True, processes=None, parent=None):
        super().__init__(parent)
        self._processes = processes          # callable -> set of names
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.edit = QLineEdit(str(value or ""))
        self.edit.textChanged.connect(self.valueChanged.emit)
        row.addWidget(self.edit, 1)

        if browse:
            self.browse_btn = QPushButton("\U0001f4c1")
            self.browse_btn.setObjectName("pickbtn")
            self.browse_btn.setFixedSize(30, 26)
            self.browse_btn.setToolTip("Choose a program or script")
            self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.browse_btn.clicked.connect(self._browse)
            row.addWidget(self.browse_btn)

        if processes is not None:
            self.proc_btn = QPushButton("\u25be")
            self.proc_btn.setObjectName("pickbtn")
            self.proc_btn.setFixedSize(26, 26)
            self.proc_btn.setToolTip("Pick from the programs running now")
            self.proc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.proc_btn.clicked.connect(self._pick_process)
            row.addWidget(self.proc_btn)

    def value(self):
        return self.edit.text()

    def _browse(self):
        if IS_WINDOWS:
            filters = ("Programs (*.exe *.bat *.cmd *.ps1);;"
                       "All files (*)")
        else:
            filters = ("Programs and scripts (*.sh *.AppImage *.appimage "
                       "*.run *.py *.bin);;All files (*)")
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a program", "", filters)
        if not path:
            return
        # the command is split shell-style later, so a path with spaces
        # has to arrive quoted or it would become two arguments
        self.edit.setText(f'"{path}"' if " " in path else path)

    def _pick_process(self):
        names = self._processes() if callable(self._processes) else set()
        dialog = ProcessPickerDialog(names, self)
        if dialog.exec() and dialog.chosen:
            self.edit.setText(dialog.chosen)
