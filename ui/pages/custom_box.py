"""
ui/pages/custom_box.py – the "Custom Box" card (Apps page, below All in one).

Draws one frame line above everything the app sends and one below it, so
the chatbox reads as a closed box::

    ┌─── 18:01 ───┐
    now playing – …
    └──────┘

Mixin for MainWindow; see ui/mainwindow.py. All `self.*` refer to the
MainWindow instance.

Two things are worth knowing before reading on:

* The frame is built ONCE per payload, in `_apply_custom_box()`, which is
  the last thing `build_payload()` does. So the top line really is the
  first line of the message and the bottom line really is the last one,
  no matter which apps or plugins produced what in between.
* A middle text runs through the same template engine as All-in-one, so
  `{cpu_usage}`, `{title}` or any plugin placeholder works in the frame
  as well. `{box_start}` / `{box_stop}` are the way back: an All-in-one
  string can place the two lines itself instead of having them wrapped
  around the whole message.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)
from core.boxstyle import (
    BOX_TEMPLATES, CLOCK_FORMATS, CUSTOM_BOX_INDEX, DEFAULT_CUSTOM_BOX, MIDDLE_MODES, MODE_CLOCK, MODE_CUSTOM, MODE_NONE, SIDE_BOTTOM, SIDE_TOP, WIDTH_MAX, WIDTH_MIN, clock_needs_seconds, clock_text, normalize_mode, render_pair, template)
from core.textutils import apply_template

#: which placeholder names let an All-in-one string place a frame line
#: itself. Matching here (and not only in the alias table) is what stops
#: the automatic wrapping from adding the same line a second time.
_MANUAL_RE = {
    SIDE_TOP: re.compile(r"\{\s*(box_start|box_top|box_open)\s*\}",
                         re.IGNORECASE),
    SIDE_BOTTOM: re.compile(r"\{\s*(box_stop|box_end|box_bottom|box_close)\s*\}",
                            re.IGNORECASE),
}

class CustomBoxMixin:
    # ================================================================
    # UI
    # ================================================================
    def build_box_card(self):
        """The whole card. Returns the frame so the Apps page can drop it
        in below All in one."""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)

        from ui.ui_main import ToggleLabel, ToggleSwitch

        head = QHBoxLayout()
        title = QLabel("Custom Box")
        title.setObjectName("cardtitle")
        head.addWidget(title)
        head.addStretch()
        self.toggle_box = ToggleSwitch()
        self.toggle_box.toggled.connect(self.on_box_toggled)
        head.addWidget(self.toggle_box)
        head.addWidget(ToggleLabel("Active", self.toggle_box))
        layout.addLayout(head)

        desc = QLabel("Hangs one line above everything and one line below "
                      "everything, so the chatbox looks like a closed box. "
                      "The top line is always the first line of the "
                      "message, the bottom line always the last. Two lines "
                      "and their characters come out of the same 144 as "
                      "everything else, so keep an eye on the counter under "
                      "the preview. With every app quiet nothing is sent at "
                      "all \u2013 an empty frame is not worth a message.\n"
                      "With All in one active the frame is NOT wrapped "
                      "around the message: there you place it yourself "
                      "with {box_start}, {box_stop} and {box_text}, which "
                      "is the only way it can sit where you want it "
                      "relative to your strings and your plugin lines.")
        desc.setObjectName("dim")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        box = QFrame()
        box.setObjectName("innerbox")
        b_layout = QVBoxLayout(box)
        b_layout.setContentsMargins(14, 10, 14, 14)
        b_layout.setSpacing(8)

        self.box_content = QWidget()
        bc = QVBoxLayout(self.box_content)
        bc.setContentsMargins(0, 0, 0, 0)
        bc.setSpacing(8)

        # ---- template picker: 12 presets + the user-defined one -------
        trow = QHBoxLayout()
        trow.setSpacing(6)
        trow.addWidget(QLabel("Template:"))
        self.box_tpl_combo = QComboBox()
        for i in range(CUSTOM_BOX_INDEX + 1):
            if i == CUSTOM_BOX_INDEX:
                label = "C  \u2013  Custom (build it yourself)"
            else:
                tpl = BOX_TEMPLATES[i]
                # the sample in the label is the point of the dropdown:
                # the old buttons only said "7", so picking a frame meant
                # clicking through all twelve to see what they looked like
                sample = (f"{tpl['tl']}{tpl['tf'] * 4}{tpl['tr']}  "
                          f"{tpl['bl']}{tpl['bf'] * 4}{tpl['br']}")
                label = f"{i + 1}  \u2013  {tpl['name']}   {sample}"
            self.box_tpl_combo.addItem(label, i)
        self.box_tpl_combo.setFixedWidth(320)
        self.box_tpl_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.box_tpl_combo.currentIndexChanged.connect(self.on_box_template)
        trow.addWidget(self.box_tpl_combo)
        trow.addStretch()
        bc.addLayout(trow)

        # ---- live preview of both lines -------------------------------
        self.box_preview_lbl = QLabel("")
        self.box_preview_lbl.setObjectName("dim")
        # "monospace" is a fontconfig alias - it resolves on Linux and
        # is simply not a family on Windows, where Qt would fall back to
        # whatever it likes and the frame preview would stop lining up.
        # Ask the system for its fixed-width font instead.
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(11)
        self.box_preview_lbl.setFont(mono)
        self.box_preview_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        bc.addWidget(self.box_preview_lbl)

        # ---- alignment (the widths live with their own line below) ----
        wrow = QHBoxLayout()
        self.chk_box_align = QCheckBox("Align top & bottom")
        self.chk_box_align.setToolTip(
            "Pads the shorter of the two lines until both come out about "
            "the same width. It only ever adds fill, never trims \u2013 so "
            "switch it off when the two widths below are meant to differ.")
        self.chk_box_align.toggled.connect(self.on_box_align)
        wrow.addWidget(self.chk_box_align)
        wrow.addStretch()
        bc.addLayout(wrow)

        # ---- the two sides --------------------------------------------
        bc.addWidget(self._box_separator("Top line"))
        self.chk_box_top, self.box_top_width_spin, self.box_top_combo, \
            self.box_top_edit, self.box_top_custom_row = \
            self._build_side_row(bc, SIDE_TOP)

        bc.addWidget(self._box_separator("Bottom line"))
        self.chk_box_bottom, self.box_bottom_width_spin, \
            self.box_bottom_combo, self.box_bottom_edit, \
            self.box_bottom_custom_row = self._build_side_row(bc, SIDE_BOTTOM)

        # ---- clock ------------------------------------------------------
        bc.addWidget(self._box_separator("Clock"))
        crow = QHBoxLayout()
        self.toggle_box_clock = ToggleSwitch()
        self.toggle_box_clock.toggled.connect(self.on_box_clock_live)
        crow.addWidget(self.toggle_box_clock)
        crow.addWidget(ToggleLabel("Realtime clock", self.toggle_box_clock))
        crow.addSpacing(16)
        crow.addWidget(QLabel("Format"))
        self.box_clock_combo = QComboBox()
        for label, value in CLOCK_FORMATS:
            self.box_clock_combo.addItem(label, value)
        self.box_clock_combo.setFixedWidth(120)
        self.box_clock_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.box_clock_combo.currentIndexChanged.connect(self.on_box_clock_fmt)
        crow.addWidget(self.box_clock_combo)
        crow.addStretch()
        bc.addLayout(crow)

        clock_hint = QLabel(
            "Without it the frame is only rebuilt when something else "
            "changes, so a clock can sit up to one send interval behind. "
            "With it the clock gets its own tick and updates the moment it "
            "changes. On by default because the default top line is a "
            "clock; switch it off if you replace that line with something "
            "that does not move, and the tick stops. It only ever runs "
            "while a line actually shows a clock \u2013 including "
            "{box_clock} inside a custom text \u2013 so it costs nothing "
            "the rest of the time.")
        clock_hint.setObjectName("dim")
        clock_hint.setWordWrap(True)
        bc.addWidget(clock_hint)

        # ---- custom template parts (only for the C slot) ---------------
        self.box_custom_row = QWidget()
        cust = QVBoxLayout(self.box_custom_row)
        cust.setContentsMargins(0, 0, 0, 0)
        cust.setSpacing(6)
        self.box_part_edits = {}
        for side, label, keys in (
                (SIDE_TOP, "Top", ("tl", "tf", "tr")),
                (SIDE_BOTTOM, "Bottom", ("bl", "bf", "br"))):
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(f"{label}:")
            lbl.setFixedWidth(56)
            row.addWidget(lbl)
            for key, ph in zip(keys, ("left", "fill", "right")):
                edit = QLineEdit()
                edit.setMaxLength(4)
                edit.setFixedWidth(58)
                edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
                edit.setPlaceholderText(ph)
                edit.setToolTip(f"{label} {ph} character")
                edit.textChanged.connect(
                    lambda t, k=key: self.on_box_part(k, t))
                row.addWidget(edit)
                self.box_part_edits[key] = edit
            row.addStretch()
            cust.addLayout(row)
        cpart_hint = QLabel(
            "The middle field is the fill and is repeated Width times; the "
            "two outer fields are the caps and may be left empty for a "
            "plain rule. Avoid plain \"-\" as the fill: a line made only of "
            "dashes is stripped as a leftover separator before it is sent.")
        cpart_hint.setObjectName("dim")
        cpart_hint.setWordWrap(True)
        cust.addWidget(cpart_hint)
        bc.addWidget(self.box_custom_row)

        # ---- placeholders ----------------------------------------------
        ph = QLabel(
            "Custom middle: every placeholder All in one accepts works "
            "here too, plugins included \u2013 the full list is under "
            "\u201cParameters\u201d at the bottom of this card. "
            "{box_clock} is the clock from the format above.\n"
            "With All in one active this card stops wrapping the message "
            "on its own \u2013 put {box_start}, {box_stop} or {box_text} "
            "into an AIO string (or onto the Advanced canvas) and the "
            "lines land exactly where you wrote them. Everything set up "
            "here still decides what they look like.")
        ph.setObjectName("dim")
        ph.setWordWrap(True)
        bc.addWidget(ph)

        self.box_expander = self.make_settings_expander(
            lambda on: self.set_expanded(self.box_expander,
                                         self.box_content, on))
        b_layout.addWidget(self.box_expander)
        b_layout.addWidget(self.box_content)
        self.box_content.setVisible(False)

        # ---- the same Parameters list All in one has ------------------
        # A middle text is rendered against the identical value dict, so
        # the vocabulary is identical too - including every plugin. One
        # shared builder, two cards (see AppsPageMixin).
        self.box_param_content = QWidget()
        self.box_param_layout = QVBoxLayout(self.box_param_content)
        self.box_param_layout.setContentsMargins(14, 4, 14, 12)
        self.box_param_layout.setSpacing(10)
        self.box_param_expander = self.make_settings_expander(
            self._on_box_params_toggled, "Parameters")
        b_layout.addWidget(self.box_param_expander)
        b_layout.addWidget(self.box_param_content)
        self.box_param_content.setVisible(False)
        self.register_parameter_list(self.box_param_layout)

        layout.addWidget(box)
        return card

    def _on_box_params_toggled(self, on):
        if on:
            self.refresh_parameter_lists()
        self.set_expanded(self.box_param_expander, self.box_param_content,
                          on, "Parameters")

    def _box_separator(self, text):
        lbl = QLabel(f"\u2500\u2500  {text}")
        lbl.setObjectName("dim")
        return lbl

    def _build_side_row(self, parent_layout, side):
        """The three widgets one side needs: the on/off box, the mode
        dropdown and the custom text field. Both sides are identical, so
        they are built by the same code instead of twice by hand."""
        top = side == SIDE_TOP
        row = QHBoxLayout()
        chk = QCheckBox(f"Show {'top' if top else 'bottom'} line")
        chk.toggled.connect(lambda on, s=side: self.on_box_side(s, on))
        row.addWidget(chk)
        row.addSpacing(16)
        row.addWidget(QLabel("Width"))
        width = QSpinBox()
        width.setObjectName("smallspin")
        width.setRange(WIDTH_MIN, WIDTH_MAX)
        width.setFixedSize(64, 28)
        width.setAlignment(Qt.AlignmentFlag.AlignCenter)
        width.setToolTip(
            "How many fill characters THIS line is made of. With a middle "
            "text they are split evenly around it, so 6 gives "
            "\u250C\u2500\u2500\u2500 18:01 \u2500\u2500\u2500\u2510.\n"
            "Each line has its own width because the two middle texts are "
            "rarely the same length \u2013 a short clock on top and a long "
            "hardware line underneath need different amounts of fill to "
            "end up looking like one box.")
        width.valueChanged.connect(lambda v, s=side: self.on_box_width(s, v))
        row.addWidget(width)
        row.addSpacing(16)
        row.addWidget(QLabel("Middle"))
        combo = QComboBox()
        for label, value in MIDDLE_MODES:
            combo.addItem(label, value)
        combo.setFixedWidth(230)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.currentIndexChanged.connect(
            lambda _i, s=side, c=None: self.on_box_mode(s))
        row.addWidget(combo)
        row.addStretch()
        parent_layout.addLayout(row)

        crow_w = QWidget()
        crow = QHBoxLayout(crow_w)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.setSpacing(6)
        lbl = QLabel("Text:")
        lbl.setFixedWidth(48)
        crow.addWidget(lbl)
        edit = QLineEdit()
        edit.setMaxLength(120)
        edit.setPlaceholderText("{cpu_usage} \u2013 own text and placeholders")
        edit.textChanged.connect(lambda t, s=side: self.on_box_custom(s, t))
        crow.addWidget(edit, 1)
        ico = QPushButton("\U0001F600")
        ico.setObjectName("iconbtn")
        ico.setFixedSize(30, 30)
        ico.setCursor(Qt.CursorShape.PointingHandCursor)
        ico.clicked.connect(
            lambda _, e=edit, b=ico: self.emoji_popup.open_for(e, b))
        crow.addWidget(ico)
        parent_layout.addWidget(crow_w)
        return chk, width, combo, edit, crow_w

    # ================================================================
    # config -> UI
    # ================================================================
    def apply_box_config_to_ui(self):
        c = self.cfg
        self.toggle_box.setChecked(c["box_active"])
        tidx = self.box_tpl_combo.findData(c["box_template"])
        self.box_tpl_combo.blockSignals(True)
        self.box_tpl_combo.setCurrentIndex(tidx if tidx >= 0 else 0)
        self.box_tpl_combo.blockSignals(False)
        self.box_top_width_spin.setValue(c["box_width_top"])
        self.box_bottom_width_spin.setValue(c["box_width_bottom"])
        self.chk_box_align.setChecked(c["box_align"])
        self.chk_box_top.setChecked(c["box_top_on"])
        self.chk_box_bottom.setChecked(c["box_bottom_on"])
        self.box_top_edit.setText(c["box_top_custom"])
        self.box_bottom_edit.setText(c["box_bottom_custom"])
        for combo, key in ((self.box_top_combo, "box_top_mode"),
                           (self.box_bottom_combo, "box_bottom_mode")):
            idx = combo.findData(normalize_mode(c[key]))
            combo.blockSignals(True)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)
        self.toggle_box_clock.setChecked(c["box_clock_live"])
        cidx = self.box_clock_combo.findData(c["box_clock_format"])
        self.box_clock_combo.blockSignals(True)
        self.box_clock_combo.setCurrentIndex(cidx if cidx >= 0 else 0)
        self.box_clock_combo.blockSignals(False)
        parts = c["box_custom_style"]
        for key, edit in self.box_part_edits.items():
            edit.blockSignals(True)
            edit.setText(parts.get(key, DEFAULT_CUSTOM_BOX[key]))
            edit.blockSignals(False)
        self._sync_box_ui()

    def _sync_box_ui(self):
        """Shows only the rows the current settings actually use."""
        c = self.cfg
        self.box_custom_row.setVisible(c["box_template"] == CUSTOM_BOX_INDEX)
        self.box_top_custom_row.setVisible(
            c["box_top_on"] and normalize_mode(c["box_top_mode"]) == MODE_CUSTOM)
        self.box_bottom_custom_row.setVisible(
            c["box_bottom_on"]
            and normalize_mode(c["box_bottom_mode"]) == MODE_CUSTOM)
        self.box_top_combo.setEnabled(c["box_top_on"])
        self.box_bottom_combo.setEnabled(c["box_bottom_on"])
        self.box_top_width_spin.setEnabled(c["box_top_on"])
        self.box_bottom_width_spin.setEnabled(c["box_bottom_on"])
        self.update_box_preview()

    def update_box_preview(self):
        """The little two-line preview inside the card. Rendered with the
        same code the payload uses, so what is shown here is what gets
        sent \u2013 including whatever the placeholders currently hold."""
        if not hasattr(self, "box_preview_lbl"):
            return
        top, bottom = self.box_lines()
        text = "\n".join(x for x in (top, bottom) if x)
        self.box_preview_lbl.setText(text or "(both lines are switched off)")

    # ================================================================
    # handlers
    # ================================================================
    def on_box_toggled(self, on):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["box_active"] = on
        self.save_config()
        self._update_box_timer()
        self.update_preview()
        self.log(f"Custom Box: {'on' if on else 'off'}")

    def on_box_template(self, _idx=None):
        if getattr(self, "_block_updating", False):
            return
        data = self.box_tpl_combo.currentData()
        self.cfg["box_template"] = max(0, min(CUSTOM_BOX_INDEX,
                                              int(data or 0)))
        self.save_config()
        self._sync_box_ui()
        self.update_preview()

    def on_box_width(self, side, val):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["box_width_top" if side == SIDE_TOP
                 else "box_width_bottom"] = int(val)
        self.save_config()
        self.update_box_preview()
        self.update_preview()

    def on_box_align(self, on):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["box_align"] = bool(on)
        self.save_config()
        self.update_box_preview()
        self.update_preview()

    def on_box_side(self, side, on):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["box_top_on" if side == SIDE_TOP else "box_bottom_on"] = \
            bool(on)
        self.save_config()
        self._sync_box_ui()
        self._update_box_timer()
        self.update_preview()

    def on_box_mode(self, side):
        if getattr(self, "_block_updating", False):
            return
        combo = (self.box_top_combo if side == SIDE_TOP
                 else self.box_bottom_combo)
        mode = normalize_mode(combo.currentData())
        self.cfg["box_top_mode" if side == SIDE_TOP
                 else "box_bottom_mode"] = mode
        self.save_config()
        self._sync_box_ui()
        self._update_box_timer()
        self.update_preview()
        if mode == MODE_CLOCK and not self.cfg["box_clock_live"]:
            self.log("Custom Box: clock selected \u2013 switch on "
                     "\"Realtime clock\" for a clock that updates on its "
                     "own instead of only when something else changes.")

    def on_box_custom(self, side, text):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["box_top_custom" if side == SIDE_TOP
                 else "box_bottom_custom"] = text
        self.save_config_later()
        self.update_box_preview()
        self.update_preview()

    def on_box_clock_live(self, on):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["box_clock_live"] = bool(on)
        self.save_config()
        self._update_box_timer()
        self.update_preview()

    def on_box_clock_fmt(self, _idx=None):
        if getattr(self, "_block_updating", False):
            return
        self.cfg["box_clock_format"] = self.box_clock_combo.currentData()
        self.save_config()
        self._update_box_timer()
        self.update_box_preview()
        self.update_preview()

    def on_box_part(self, key, text):
        if getattr(self, "_block_updating", False):
            return
        parts = dict(self.cfg.get("box_custom_style") or DEFAULT_CUSTOM_BOX)
        parts[key] = text[:4]
        self.cfg["box_custom_style"] = parts
        self.save_config_later()
        self.update_box_preview()
        self.update_preview()

    # ================================================================
    # the live clock tick
    # ================================================================
    #: placeholders that make a custom middle text time-dependent. A
    #: middle set to Custom can still be a clock - "{box_clock}" is the
    #: obvious way to put a clock next to something else - and without
    #: this the tick would never start for it, leaving the Realtime
    #: switch on and doing nothing.
    _CLOCK_RE = re.compile(r"\{\s*(box_clock|realtime|clock|time_now|pctime)"
                           r"\s*\}", re.IGNORECASE)

    def _box_clock_in_use(self):
        c = self.cfg
        for on, mode, custom in (
                (c["box_top_on"], c["box_top_mode"], c["box_top_custom"]),
                (c["box_bottom_on"], c["box_bottom_mode"],
                 c["box_bottom_custom"])):
            if not on:
                continue
            mode = normalize_mode(mode)
            if mode == MODE_CLOCK:
                return True
            if mode == MODE_CUSTOM and self._CLOCK_RE.search(custom or ""):
                return True
        return False

    def _update_box_timer(self):
        """Runs the clock tick only while it can actually change
        something: the card active, the realtime toggle on, and at least
        one side set to Clock. Everything else leaves the timer stopped,
        which is the whole point of the toggle."""
        if not (self.cfg["box_active"] and self.cfg["box_clock_live"]
                and self._box_clock_in_use()):
            self.box_timer.stop()
            return
        # a format without seconds only changes once a minute, but the
        # tick has to be finer than that or the clock flips up to a
        # minute late. 1 s of a string compare is nothing; the send that
        # follows is guarded by _box_clock_last.
        interval = 1000 if clock_needs_seconds(
            self.cfg["box_clock_format"]) else 2000
        if (not self.box_timer.isActive()
                or self.box_timer.interval() != interval):
            self.box_timer.start(interval)

    def _box_tick(self):
        """Refreshes only when the clock string actually changed. Without
        this the preview (and with it a send request) would be rebuilt
        every single second for a clock that changes once a minute."""
        now = clock_text(self.cfg["box_clock_format"])
        if now == getattr(self, "_box_clock_last", None):
            return
        self._box_clock_last = now
        self.update_box_preview()
        self.update_preview()

    # ================================================================
    # rendering
    # ================================================================
    def _box_middle(self, side):
        """The text that goes into the middle of one frame line \u2013 "" for
        a plain line."""
        c = self.cfg
        if side == SIDE_TOP:
            if not c["box_top_on"]:
                return ""
            mode, custom = normalize_mode(c["box_top_mode"]), c["box_top_custom"]
        else:
            if not c["box_bottom_on"]:
                return ""
            mode, custom = (normalize_mode(c["box_bottom_mode"]),
                            c["box_bottom_custom"])
        if mode == MODE_CLOCK:
            return clock_text(c["box_clock_format"])
        if mode == MODE_CUSTOM and custom.strip():
            vals = self._template_values(custom)
            vals["box_clock"] = clock_text(c["box_clock_format"])
            text = apply_template(custom, vals)
            # a frame line is one line by definition; a template that
            # produced several (via \n) is folded back into one instead
            # of quietly breaking the box open
            return " ".join(x.strip() for x in text.split("\n") if x.strip())
        return ""

    def box_lines(self):
        """(top, bottom) as they would be sent right now. Either may be
        "" when that side is switched off."""
        c = self.cfg
        tpl = template(c["box_template"], c.get("box_custom_style"))
        return render_pair(tpl, c["box_width_top"], c["box_width_bottom"],
                           self._box_middle(SIDE_TOP),
                           self._box_middle(SIDE_BOTTOM),
                           top_on=c["box_top_on"],
                           bottom_on=c["box_bottom_on"],
                           align=c["box_align"])

    def box_placed_manually(self, side):
        """True when the All-in-one string that is on screen right now
        places this line itself with {box_start} / {box_stop}.

        Kept for plugins and for the card's own hints. The automatic
        wrapping no longer consults it: with All in one active there IS
        no automatic wrapping any more (see _apply_custom_box), which is
        the whole point - a per-string check could only ever be right for
        the one string that happened to be showing.
        """
        if not self.cfg.get("aio_active"):
            return False
        return bool(_MANUAL_RE[side].search(self.current_aio_template()))

    def _apply_custom_box(self, lines):
        """Wraps the finished payload. Called as the very last step of
        build_payload(), so the top line is the first line of the message
        and the bottom line the last one.
        """
        if not self.cfg.get("box_active"):
            return lines
        if self.cfg.get("aio_active"):
            # All in one decides WHAT is sent, and that includes where
            # the frame goes: {box_start} / {box_stop} / {box_text} place
            # it, nothing else does.
            #
            # Wrapping automatically here was wrong in both directions.
            # A layout that placed the frame itself only got left alone
            # while the ONE string carrying {box_start} happened to be on
            # rotation, so the box reappeared around the other strings;
            # and the wrap sat outside the plugin lines too, framing
            # output that has nothing to do with the box. Neither is
            # something the user asked for by switching the card on.
            return lines
        if self.box_blocked():
            # "Block apps" extends to the frame: a box drawn around a
            # message the block left empty is two wasted lines and a
            # send, and around a speech-to-text message it is a frame
            # the user did not ask for.
            return lines
        if not any((ln or "").strip() for ln in lines):
            # nothing to frame. An empty box is not a smaller message,
            # it is a message that says nothing and still burns two
            # lines and a send - so with every app quiet, stay quiet.
            return lines
        top, bottom = self.box_lines()
        if bottom:
            lines = list(lines) + [bottom]
        if top:
            lines = [top] + list(lines)
        return lines
