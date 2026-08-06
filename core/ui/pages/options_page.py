"""
ui/pages/options_page.py – Options page: OSC target, OSCQuery, updates, fixes, sending, debug.

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
    QColorDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)
from core import desktop_integration, queryfix, vrc_pictures
from core.theming import (
    TOKEN_LABELS, import_background, list_backgrounds, remove_background,
    resolve_tokens, theme_ids, theme_name)
from core.constants import (
    CHATBOX_INPUT, DISCORD_URL, DONATE_URL, GITHUB_REPO, OSC_MIN_SEND_GAP_SEC, OSC_RATE_MAX_SENDS, OSC_RATE_WINDOW_SEC, VERSION, VRCHAT_GROUP_URL)
from core.oscquery import HAS_ZEROCONF
from core.osinfo import IS_WINDOWS, OS_NAME
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

        layout.addWidget(card)
        layout.addWidget(self.build_customization_card())

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
        don_btn = QPushButton("\u2615  Support on Ko-fi")
        don_btn.setObjectName("linkbtn")
        don_btn.setFixedHeight(34)
        don_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        don_btn.setToolTip("Support development on Ko-fi")
        don_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        btn_row.addWidget(don_btn)

        vrc_btn = QPushButton("\U0001F465  VRChat Group")
        vrc_btn.setObjectName("linkbtn")
        vrc_btn.setFixedHeight(34)
        vrc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        vrc_btn.setToolTip("Join the OSC-DreamChatbox VRChat group")
        vrc_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(VRCHAT_GROUP_URL)))
        btn_row.addWidget(vrc_btn)

        btn_row.addStretch()
        uc.addLayout(btn_row)

        # App Tray Fix sits on its own row directly under "Check for updates"
        #
        # Both buttons below fix problems that only exist on Linux:
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
        # So on Windows the whole row is skipped rather than shown greyed
        # out: a disabled button invites the question "what am I missing?",
        # and the honest answer is "nothing".
        fix_row = QHBoxLayout()
        self.tray_fix_btn = QPushButton("\U0001F527  App Tray Fix")
        self.tray_fix_btn.setObjectName("linkbtn")
        self.tray_fix_btn.setFixedHeight(34)
        self.tray_fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tray_fix_btn.setToolTip(
            "Registers a desktop entry so the correct taskbar/tray icon shows "
            "and the app appears in your application menu. For install-script "
            "users – does nothing if an entry already exists.")
        self.tray_fix_btn.clicked.connect(self.run_app_tray_fix)
        fix_row.addWidget(self.tray_fix_btn)

        self.vrc_pic_btn = QPushButton("\U0001F5BC\uFE0F  VRC Picture Folder Fix")
        self.vrc_pic_btn.setObjectName("linkbtn")
        self.vrc_pic_btn.setFixedHeight(34)
        self.vrc_pic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vrc_pic_btn.setToolTip(
            "Creates a symlink so VRChat's camera photos – normally saved "
            "inside the Proton prefix – land directly in your Linux Pictures "
            "folder (~/Pictures/VRChat). Existing photos in the prefix are "
            "moved over. Does nothing if it's already set up.")
        self.vrc_pic_btn.clicked.connect(self.run_vrc_picture_fix)
        fix_row.addWidget(self.vrc_pic_btn)

        fix_row.addStretch()
        if IS_WINDOWS:
            # created but never shown: other code (and any future preset)
            # may still reference the attributes
            self.tray_fix_btn.setVisible(False)
            self.vrc_pic_btn.setVisible(False)
        else:
            uc.addLayout(fix_row)

        self.update_lbl = QLabel(f"Current version: {VERSION}")
        self.update_lbl.setObjectName("dim")
        self.update_lbl.setWordWrap(True)
        self.update_lbl.setOpenExternalLinks(True)
        uc.addWidget(self.update_lbl)
        # Community & Updates goes to the TOP of the page (index 0 is the
        # "Options" title, so this card lands right underneath it)
        layout.insertWidget(1, ucard)

        layout.addStretch()
        return page


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
        elif tag and tag != VERSION:
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
