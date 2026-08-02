"""
ui/pages/plugins_page.py – Plugins page: install, enable/disable, remove.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.

The heavy lifting (scanning, importing, zip validation) lives in
core/plugins.py – this file is pure UI plus the handlers wired to it.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsColorizeEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QSpinBox, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)
from core.constants import PLUGINS_DIR, PLUGINS_REPO_URL
from core.plugin_store import PluginStore, StoreError, compare_versions
from core.plugins import ANCHOR_LABELS, PluginError, PluginExistsError
from ui.ui_main import DragHandle, ToggleLabel, ToggleSwitch


class PluginInfoPopup(QFrame):
    """Small popup shown by the (i) button next to a plugin: name,
    version, author and a clickable GitHub link."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.Popup)
        self.setStyleSheet(
            "QFrame { background: #191c24; border: 1px solid #333947;"
            " border-radius: 10px; }"
            "QLabel { border: none; }")
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(4)
        self.lbl = QLabel("")
        self.lbl.setTextFormat(Qt.TextFormat.RichText)
        self.lbl.setOpenExternalLinks(True)
        self.lbl.setWordWrap(True)
        self.lbl.setMaximumWidth(380)
        self.lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        box.addWidget(self.lbl)

    @staticmethod
    def _esc(text):
        return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    def open_for(self, plugin, anchor):
        rows = [
            f"<b style='font-size:15px'>{self._esc(plugin.name)}</b>",
            f"<span style='color:#7a8290'>Version</span> "
            f"{self._esc(plugin.version)}",
            f"<span style='color:#7a8290'>Author</span> "
            f"{self._esc(plugin.author)}",
        ]
        if plugin.github_url:
            rows.append(
                f"<span style='color:#7a8290'>GitHub</span> "
                f"<a href='{self._esc(plugin.github_url)}' "
                f"style='color:#5b8dc9'>"
                f"{self._esc(plugin.github)}</a>")
        rows.append(
            f"<span style='color:#7a8290'>ID</span> "
            f"<span style='font-family:monospace'>"
            f"{self._esc(plugin.pid)}</span>")
        if plugin.error:
            rows.append(
                f"<span style='color:#d9884a'>Last error:</span><br>"
                f"<span style='font-family:monospace;font-size:11px'>"
                f"{self._esc(plugin.error)}</span>")
        self.lbl.setText("<br>".join(rows))
        self.adjustSize()
        # anchor the popup under the (i) button, right-aligned
        self.move(anchor.mapToGlobal(anchor.rect().bottomRight())
                  - self.rect().topRight())
        self.show()


class PluginsPageMixin:
    def build_plugins_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 14, 24, 20)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Plugins")
        title.setObjectName("pagetitle")
        head.addWidget(title)
        head.addStretch()

        # ---- catalogue update: only appears when GitHub has a newer
        # plugins.json, and only downloads when the user clicks it
        self.catalogue_btn = QPushButton("\u2B06  Plugin list update")
        self.catalogue_btn.setFixedHeight(30)
        self.catalogue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.catalogue_btn.setStyleSheet(
            "QPushButton { background: #2b3a4d; border: 1px solid #5b8dc9;"
            " border-radius: 8px; color: #cfe0f5; padding: 0 12px; }"
            "QPushButton:hover { background: #34495f; }")
        self.catalogue_btn.setVisible(False)
        self.catalogue_btn.clicked.connect(self.on_catalogue_update)
        head.addWidget(self.catalogue_btn)
        layout.addLayout(head)

        # ---- Installed / Store switch (exclusive, like the AIO templates)
        # Own row UNDER the title and left aligned, not on the right of the
        # title row: right-aligned controls are the first thing a narrow
        # window cuts off, and these two decide what the whole page shows.
        # Left of a left-growing layout, they survive any window width.
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(8)
        self.plugin_tab_group = QButtonGroup(self)
        self.plugin_tab_group.setExclusive(True)
        for i, label in enumerate(("\U0001F4E6  Installed", "\U0001F6CD  Store")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedHeight(30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton { background: #232833; border: 1px solid #333947;"
                " border-radius: 8px; color: #aeb4bf; padding: 0 14px; }"
                "QPushButton:hover { border-color: #5b8dc9; }"
                "QPushButton:checked { background: #5b8dc9;"
                " border-color: #5b8dc9; color: #ffffff; }")
            self.plugin_tab_group.addButton(b, i)
            tabs_row.addWidget(b)
        # the stretch goes AFTER the buttons, so they stay packed left
        tabs_row.addStretch()
        self.plugin_tab_group.button(0).setChecked(True)
        self.plugin_tab_group.idClicked.connect(self.on_plugin_tab)
        layout.addLayout(tabs_row)

        self.plugin_info_popup = PluginInfoPopup()
        self.store = PluginStore(self.log)
        self.store_tiles_per_row = 4
        self._store_busy = False
        # pid -> widget, rebuilt on every refresh_plugin_list()
        self.plugin_expanders = {}
        self.plugin_inputs = {}

        # ------------------------------------------------ actions card
        card = QFrame()
        card.setObjectName("card")
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 10, 16, 12)
        c.setSpacing(6)

        head = QHBoxLayout()
        ctitle = QLabel("Installed plugins")
        ctitle.setObjectName("cardtitle")
        head.addWidget(ctitle)
        head.addStretch()
        self.plugin_count_lbl = QLabel("")
        self.plugin_count_lbl.setObjectName("dim")
        head.addWidget(self.plugin_count_lbl)
        c.addLayout(head)

        note = QLabel(
            "Note: In the Apps (All-in-One) tab, you can use plugin variables "
            "(e.g. {world_stats}) to include your plugin data directly.")
        note.setStyleSheet("color: #7a8290; font-size: 11px;")
        note.setWordWrap(True)
        c.addWidget(note)

        btn_row = QHBoxLayout()
        install_btn = QPushButton("\u2795  Install plugin from .zip")
        install_btn.setObjectName("sendbtn")
        install_btn.setFixedHeight(34)
        install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        install_btn.clicked.connect(self.on_install_plugin_zip)
        btn_row.addWidget(install_btn)

        open_btn = QPushButton("\U0001F4C2  Open plugins folder")
        open_btn.setObjectName("linkbtn")
        open_btn.setFixedHeight(34)
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setToolTip(str(PLUGINS_DIR))
        open_btn.clicked.connect(self.on_open_plugins_dir)
        btn_row.addWidget(open_btn)

        repo_btn = QPushButton("\U0001F9E9  Plugins & template")
        repo_btn.setObjectName("linkbtn")
        repo_btn.setFixedHeight(34)
        repo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        repo_btn.setToolTip("Ready-made plugins to download plus the "
                            "template to build your own \u2013 opens "
                            f"{PLUGINS_REPO_URL}")
        repo_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(PLUGINS_REPO_URL)))
        btn_row.addWidget(repo_btn)

        rescan_btn = QPushButton("\U0001F504  Rescan")
        rescan_btn.setObjectName("linkbtn")
        rescan_btn.setFixedHeight(34)
        rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan_btn.setToolTip("Re-read the plugins folder (after you dropped "
                              "a plugin in there by hand)")
        rescan_btn.clicked.connect(self.on_rescan_plugins)
        btn_row.addWidget(rescan_btn)
        btn_row.addStretch()
        c.addLayout(btn_row)

        # -------------------------------------------------- plugin list
        self.plugin_list = QVBoxLayout()
        self.plugin_list.setSpacing(8)
        c.addLayout(self.plugin_list)

        self.plugin_empty_lbl = QLabel(
            "No plugins installed yet. Grab a .zip and hit "
            "\u201cInstall plugin from .zip\u201d.")
        self.plugin_empty_lbl.setObjectName("dim")
        self.plugin_empty_lbl.setWordWrap(True)
        c.addWidget(self.plugin_empty_lbl)
        # keeps every row at its natural height and pins the whole block to
        # the top - without it the leftover space is shared out between the
        # heading, the buttons and each plugin row
        c.addStretch(1)

        self.plugin_stack = QStackedWidget()
        self.plugin_stack.addWidget(card)                    # 0 installed
        self.plugin_stack.addWidget(self._build_store_view())  # 1 store
        self.plugin_stack.addWidget(self._build_store_detail())  # 2 detail
        layout.addWidget(self.plugin_stack)
        layout.addStretch()
        self.refresh_plugin_list()
        return page

    # ------------------------------------------------------- list build
    def refresh_plugin_list(self):
        """Rebuilds the rows from the manager's current plugin list."""
        while self.plugin_list.count():
            item = self.plugin_list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        self.plugin_expanders = {}
        self.plugin_inputs = {}
        self.plugin_dependents = {}
        # user order, not folder order (Plugins page ▲▼)
        plugins = self.plugins.ordered()
        self.plugin_rows = {}
        for plugin in plugins:
            row = self._build_plugin_row(plugin)
            self.plugin_rows[plugin.pid] = row
            self.plugin_list.addWidget(row)

        self.plugin_empty_lbl.setVisible(not plugins)
        active = sum(1 for p in plugins if p.enabled)
        self.plugin_count_lbl.setText(
            f"{active} of {len(plugins)} active" if plugins else "")

    def _build_plugin_row(self, plugin):
        """One plugin = one card: header line + a collapsible Settings
        block holding the custom string and the plugin's own options
        (same expander pattern as the Apps cards)."""
        row = QFrame()
        row.setObjectName("innerbox")
        box = QVBoxLayout(row)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(8)

        # ------------------------------------------------------ header
        outer = QHBoxLayout()
        outer.setSpacing(12)

        if plugin.supported:
            # same grip as the app cards - dragging is the one reorder
            # gesture in this app, so plugins should not invent a second
            outer.addWidget(
                DragHandle(lambda pos, pid=plugin.pid:
                           self.plugin_drag(pid, pos),
                           lambda pid=plugin.pid: self.plugin_drag_end(pid)),
                0, Qt.AlignmentFlag.AlignVCenter)
        else:
            spacer = QWidget()
            spacer.setFixedSize(22, 22)
            outer.addWidget(spacer, 0, Qt.AlignmentFlag.AlignVCenter)

        toggle = ToggleSwitch()
        toggle.blockSignals(True)
        toggle.setChecked(plugin.enabled and plugin.supported)
        toggle.blockSignals(False)
        if plugin.supported:
            toggle.toggled.connect(
                lambda on, pid=plugin.pid: self.on_plugin_toggled(pid, on))
        else:
            # greyed out rather than hidden: hiding it would look like the
            # plugin vanished after installing it
            toggle.setEnabled(False)
            toggle.setToolTip(plugin.error or plugin.platform_note)
            row.setStyleSheet("QFrame#innerbox { opacity: 0.5; }")
        outer.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(ToggleLabel(plugin.name, toggle))
        ver = QLabel(f"v{plugin.version.lstrip('v')}")
        ver.setObjectName("dim")
        head.addWidget(ver)
        # the placeholder is the whole point – show it right in the header
        tag = QLabel(f"{{{plugin.pid}}}")
        tag.setObjectName("dim")
        tag.setStyleSheet("font-family: monospace; color: #5b8dc9;")
        tag.setToolTip("Use this placeholder in any custom string, in "
                       "All-in-one or in a Personal Status text")
        tag.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(tag)
        if not plugin.supported:
            note = QLabel(f"\u26D4 {plugin.platform_note}")
            note.setStyleSheet("color: #8a8f99; font-size: 12px;")
            note.setToolTip(plugin.error or plugin.platform_note)
            head.addWidget(note)
        elif plugin.error:
            warn = QLabel("\u26A0 error")
            warn.setStyleSheet("color: #d9884a; font-size: 12px;")
            warn.setToolTip(plugin.error)
            head.addWidget(warn)
        head.addStretch()
        texts.addLayout(head)

        sub = QLabel(plugin.description or "\u2013")
        sub.setObjectName("dim")
        sub.setWordWrap(True)
        texts.addWidget(sub)
        if not plugin.supported:
            for lbl in (sub,):
                lbl.setStyleSheet("color: #5c626c;")
        by = QLabel(f"by {plugin.author}")
        by.setObjectName("dim")
        texts.addWidget(by)
        outer.addLayout(texts, 1)

        info_btn = QPushButton("\u2139")
        info_btn.setObjectName("iconbtn")
        info_btn.setFixedSize(30, 30)
        info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        info_btn.setToolTip("Name, version, author, GitHub")
        info_btn.clicked.connect(
            lambda _, pid=plugin.pid, b=info_btn: self.on_plugin_info(pid, b))
        outer.addWidget(info_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # ---- where this plugin's lines go relative to the Apps cards
        anchor_box = QComboBox()
        anchor_box.setFixedWidth(168)
        anchor_box.setToolTip(
            "Where this plugin's line goes in the chatbox. All in one is "
            "always the last block, so \u201cAbove All in one\u201d means "
            "below every app.")
        for key, label in ANCHOR_LABELS:
            anchor_box.addItem(label, key)
        current = self.plugins.entry(plugin.pid)["anchor"]
        pos = anchor_box.findData(current)
        anchor_box.setCurrentIndex(pos if pos >= 0 else
                                   anchor_box.count() - 1)
        if plugin.supported:
            anchor_box.currentIndexChanged.connect(
                lambda _i, pid=plugin.pid, b=anchor_box:
                self.on_plugin_anchor(pid, b.currentData()))
        else:
            anchor_box.setEnabled(False)
        outer.addWidget(anchor_box, 0, Qt.AlignmentFlag.AlignVCenter)

        # ---- uninstall, last in the row
        # Deliberately reachable for UNSUPPORTED plugins too: a plugin that
        # cannot run here is exactly the one you want to get rid of, and
        # everything else in its row is disabled.
        del_btn = QPushButton("\U0001F5D1")
        del_btn.setObjectName("iconbtn")
        del_btn.setFixedSize(30, 30)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setToolTip(f"Uninstall '{plugin.name}' and delete its "
                           f"folder\n{plugin.folder}")
        del_btn.setStyleSheet(
            "QPushButton:hover { background: #4a2b2b; border-color: #c96b6b;"
            " color: #ffb4b4; }")
        del_btn.clicked.connect(
            lambda _, pid=plugin.pid: self.on_plugin_delete(pid))
        outer.addWidget(del_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        box.addLayout(outer)

        # ---------------------------------------------------- settings
        if not plugin.supported:
            # no settings for something that cannot run here
            return row
        content = self._build_plugin_settings(plugin)
        # the expander needs to reference itself in its own callback, so
        # look it back up in the dict instead of chasing a forward name
        pid = plugin.pid
        expander = self.make_settings_expander(
            lambda on, c=content, k=pid: self.set_expanded(
                self.plugin_expanders[k], c, on))
        self.plugin_expanders[pid] = expander
        box.addWidget(expander)
        box.addWidget(content)
        content.setVisible(False)
        return row

    def _build_plugin_settings(self, plugin):
        """The collapsible body: custom string + whatever the plugin
        declared under "settings" in its plugin.json."""
        entry = self.plugins.entry(plugin.pid)
        content = QWidget()
        c = QVBoxLayout(content)
        c.setContentsMargins(12, 4, 0, 4)
        c.setSpacing(8)

        # ----- own line vs. placeholder-only
        chk_line = QCheckBox(
            "Own line in the chatbox  (off = only usable as a placeholder)")
        chk_line.setChecked(bool(entry["line"]))
        chk_line.setToolTip(
            "Turn this off once you placed {%s} inside a status text, an "
            "Apps custom string or All-in-one \u2013 otherwise the plugin "
            "prints its output a second time." % plugin.pid)
        chk_line.toggled.connect(
            lambda on, pid=plugin.pid: self.on_plugin_line(pid, on))
        c.addWidget(chk_line)

        # ----- custom string (mirrors the MediaPlay / Hardware cards)
        chk = QCheckBox("Custom string  (build your own layout)")
        chk.setChecked(bool(entry["custom"]))
        chk.toggled.connect(
            lambda on, pid=plugin.pid: self.on_plugin_custom(pid, on))
        c.addWidget(chk)

        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setMaxLength(200)
        edit.setText(entry["template"])
        edit.setEnabled(bool(entry["custom"]))
        edit.textChanged.connect(
            lambda text, pid=plugin.pid: self.plugins.set_template(pid, text))
        row.addWidget(edit, 1)

        reset = QPushButton("\u21BA")
        reset.setObjectName("iconbtn")
        reset.setFixedSize(30, 30)
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.setToolTip("Back to the default string of this plugin")
        reset.clicked.connect(
            lambda _, pid=plugin.pid, e=edit: self.on_plugin_reset(pid, e))
        row.addWidget(reset)

        ico = QPushButton("\U0001F600")
        ico.setObjectName("iconbtn")
        ico.setFixedSize(30, 30)
        ico.setCursor(Qt.CursorShape.PointingHandCursor)
        ico.setToolTip("Insert icon")
        ico.clicked.connect(
            lambda _, e=edit, b=ico: self.emoji_popup.open_for(e, b))
        row.addWidget(ico)
        c.addLayout(row)
        # keep the input greyed out while the checkbox is off
        self.plugin_inputs[plugin.pid] = edit

        parts = [f"Placeholders: {{{plugin.pid}}} (this plugin's output)"]
        for key, desc in plugin.placeholders.items():
            parts.append(f"{{{plugin.pid}_{key}}}"
                         + (f" ({desc})" if desc else ""))
        ph = QLabel(", ".join(parts) + ".  All Apps placeholders ({artist} "
                    "{title} {bar} {gpu_usage} {text} \u2026) and other "
                    "plugins work here too \u2013 use \\n for a line break.")
        ph.setObjectName("dim")
        ph.setWordWrap(True)
        c.addWidget(ph)

        # ----- options declared by the plugin author
        if plugin.schema:
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setObjectName("hline")
            c.addWidget(line)
            opts = self.plugins.options(plugin.pid)
            # parent key -> [dependent widgets], so a sub-option can hide
            # with its parent (Max world name length under World name)
            deps = {}
            for item in plugin.schema:
                w = self._build_plugin_option(plugin, item, opts)
                if item.get("depends"):
                    deps.setdefault(item["depends"], []).append(w)
                    # indent it so it reads as belonging to the row above
                    w.setContentsMargins(24, 0, 0, 0)
                c.addWidget(w)
            self.plugin_dependents[plugin.pid] = deps
            self._sync_plugin_dependents(plugin.pid)
        return content

    def _build_plugin_option(self, plugin, item, opts):
        """One widget for one entry of the plugin's "settings" schema.
        Unknown types never reach here – _parse_schema drops them."""
        pid, key, kind = plugin.pid, item["key"], item["type"]
        value = opts.get(key, item["default"])

        if kind == "bool":
            holder = QWidget()
            box = QHBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox(item["label"])
            chk.setChecked(bool(value))
            chk.toggled.connect(
                lambda on, p=pid, k=key: self.on_plugin_option(p, k, on))
            if item["hint"]:
                chk.setToolTip(item["hint"])
            box.addWidget(chk)
            box.addStretch()
            return holder

        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel(item["label"])
        if item["hint"]:
            lbl.setToolTip(item["hint"])
        row.addWidget(lbl)

        if kind == "slider":
            # live value label next to the handle, so dragging shows the
            # number instead of leaving people guessing
            try:
                start = int(value)
            except (TypeError, ValueError):
                start = item["default"]
            start = max(item["min"], min(item["max"], start))
            w = QSlider(Qt.Orientation.Horizontal)
            w.setRange(item["min"], item["max"])
            w.setValue(start)
            w.setMinimumWidth(160)
            val_lbl = QLabel(f"{start}{item.get('suffix', '')}")
            val_lbl.setObjectName("dim")
            val_lbl.setMinimumWidth(72)
            w.valueChanged.connect(
                lambda v, p=pid, k=key, lb=val_lbl, sfx=item.get("suffix", ""):
                (lb.setText(f"{v}{sfx}"), self.on_plugin_option(p, k, v)))
            row.addWidget(w, 1)
            row.addWidget(val_lbl)
            return holder

        if kind == "int":
            w = QSpinBox()
            w.setObjectName("smallspin")
            w.setRange(item["min"], item["max"])
            w.setFixedSize(72, 28)
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            try:
                w.setValue(int(value))
            except (TypeError, ValueError):
                w.setValue(item["default"])
            w.valueChanged.connect(
                lambda val, p=pid, k=key: self.on_plugin_option(p, k, val))
            row.addWidget(w)
            row.addStretch()
        else:   # text
            w = QLineEdit()
            w.setMaxLength(200)
            w.setText(str(value))
            w.textChanged.connect(
                lambda text, p=pid, k=key: self.on_plugin_option(p, k, text))
            row.addWidget(w, 1)
        return holder


    # ================================================================
    # store
    # ================================================================
    def _build_store_view(self):
        card = QFrame()
        card.setObjectName("card")
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 14, 16, 16)
        c.setSpacing(10)

        head = QHBoxLayout()
        t = QLabel("Plugin store")
        t.setObjectName("cardtitle")
        head.addWidget(t)
        head.addStretch()
        self.store_status = QLabel("")
        self.store_status.setObjectName("dim")
        head.addWidget(self.store_status)
        c.addLayout(head)

        btns = QHBoxLayout()
        self.store_refresh_btn = QPushButton("\U0001F504  Refresh")
        self.store_refresh_btn.setObjectName("sendbtn")
        self.store_refresh_btn.setFixedHeight(34)
        self.store_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.store_refresh_btn.setToolTip(
            "Downloads the current plugin list from GitHub and re-reads "
            "every plugin's details")
        self.store_refresh_btn.clicked.connect(self.on_store_refresh)
        btns.addWidget(self.store_refresh_btn)

        self.store_update_btn = QPushButton("\u2B07  Update all")
        self.store_update_btn.setObjectName("linkbtn")
        self.store_update_btn.setFixedHeight(34)
        self.store_update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.store_update_btn.setToolTip("Re-download every installed plugin "
                                         "that has a newer version")
        self.store_update_btn.setVisible(False)
        self.store_update_btn.clicked.connect(self.on_store_update_all)
        btns.addWidget(self.store_update_btn)

        repo_btn = QPushButton("\U0001F9E9  Plugins & template")
        repo_btn.setObjectName("linkbtn")
        repo_btn.setFixedHeight(34)
        repo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        repo_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(PLUGINS_REPO_URL)))
        btns.addWidget(repo_btn)
        btns.addStretch()
        c.addLayout(btns)

        hint = QLabel(
            "Catalogue from <span style='font-family:monospace'>plugins.json</span>"
            " next to the app \u2013 paste a GitHub link to a plugin folder and it "
            "shows up here. Name, version and preview image come from the "
            "plugin's own plugin.json.")
        hint.setObjectName("dim")
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        c.addWidget(hint)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("hline")
        c.addWidget(line)

        self.store_grid = QGridLayout()
        self.store_grid.setSpacing(10)
        c.addLayout(self.store_grid)
        c.addStretch()
        return card

    def _store_placeholder_pixmap(self, entry):
        """A plugin without a preview image still needs something in the
        tile, so draw its initials on a flat tile instead of leaving a
        hole in the grid."""
        pm = QPixmap(200, 112)
        pm.fill(QColor("#232833"))
        painter = QPainter(pm)
        painter.setPen(QColor("#5b8dc9"))
        f = painter.font()
        f.setPointSize(26)
        f.setBold(True)
        painter.setFont(f)
        initials = "".join(w[0] for w in (entry.name or "?").split()[:2]).upper()
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, initials)
        painter.end()
        return pm

    @staticmethod
    def _grey_effect():
        """Desaturates a preview so an incompatible plugin reads as
        unavailable at a glance, without hiding what it looks like."""
        eff = QGraphicsColorizeEffect()
        eff.setColor(QColor("#6b7180"))
        eff.setStrength(0.85)
        return eff

    def _build_store_tile(self, entry):
        tile = QFrame()
        tile.setObjectName("innerbox")
        tile.setCursor(Qt.CursorShape.PointingHandCursor)
        tile.setFixedWidth(212)
        v = QVBoxLayout(tile)
        v.setContentsMargins(6, 6, 6, 8)
        v.setSpacing(6)

        img = QLabel()
        img.setFixedSize(200, 112)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setScaledContents(True)
        pm = None
        if entry.image_path:
            loaded = QPixmap(str(entry.image_path))
            if not loaded.isNull():
                pm = loaded
        img.setPixmap(pm or self._store_placeholder_pixmap(entry))
        v.addWidget(img)

        name = QLabel(entry.name)
        name.setStyleSheet("font-weight: 600;")
        name.setWordWrap(True)
        v.addWidget(name)

        meta = QLabel(f"v{entry.version.lstrip('v')} \u00b7 {entry.author}")
        meta.setObjectName("dim")
        v.addWidget(meta)

        if not entry.supported:
            state = QLabel(f"\u26D4 {entry.platform_note}")
            state.setStyleSheet("color: #8a8f99; font-size: 12px;")
            tile.setStyleSheet(
                "QFrame#innerbox { background: #1a1d24; border-color:"
                " #262a33; }")
            img.setGraphicsEffect(self._grey_effect())
            name.setStyleSheet("font-weight: 600; color: #6b7180;")
            meta.setStyleSheet("color: #565c66;")
        elif entry.error:
            state = QLabel("\u26A0 unreachable")
            state.setStyleSheet("color: #d9884a; font-size: 12px;")
            state.setToolTip(entry.error)
        elif entry.has_update:
            state = QLabel(f"Update \u2192 v{entry.version.lstrip('v')}")
            state.setStyleSheet("color: #5b8dc9; font-size: 12px;")
        elif entry.installed:
            state = QLabel("\u2713 installed")
            state.setStyleSheet("color: #6f9f6f; font-size: 12px;")
        else:
            state = QLabel("not installed")
            state.setObjectName("dim")
        v.addWidget(state)

        # the whole tile is clickable, not just a small button
        tile.mousePressEvent = (
            lambda ev, k=entry.source.key: self.on_store_open(k))
        return tile

    def refresh_store_grid(self):
        while self.store_grid.count():
            item = self.store_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        entries = self.store.entries
        per_row = self.store_tiles_per_row
        for i, entry in enumerate(entries):
            self.store_grid.addWidget(self._build_store_tile(entry),
                                      i // per_row, i % per_row)
        # keep the tiles left-aligned instead of stretched apart
        self.store_grid.setColumnStretch(per_row, 1)
        updates = sum(1 for e in entries if e.has_update)
        self.store_update_btn.setVisible(updates > 0)
        self.store_update_btn.setText(f"\u2B07  Update all ({updates})")
        if self.store.last_error:
            self.store_status.setText(self.store.last_error)
        else:
            bits = [f"{len(entries)} plugin(s)"]
            if updates:
                bits.append(f"{updates} update(s)")
            if self.store.catalogue_version not in ("", "0"):
                bits.append(f"list v{self.store.catalogue_version}")
            self.store_status.setText(", ".join(bits))

    # ------------------------------------------------------- detail view
    def _build_store_detail(self):
        card = QFrame()
        card.setObjectName("card")
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 14, 16, 16)
        c.setSpacing(10)

        top = QHBoxLayout()
        back = QPushButton("\u2190  Back to store")
        back.setObjectName("linkbtn")
        back.setFixedHeight(30)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(lambda: self.on_plugin_tab(1))
        top.addWidget(back)
        top.addStretch()
        c.addLayout(top)

        self.detail_img = QLabel()
        self.detail_img.setFixedHeight(200)
        self.detail_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.addWidget(self.detail_img)

        self.detail_title = QLabel("")
        self.detail_title.setObjectName("cardtitle")
        c.addWidget(self.detail_title)
        self.detail_meta = QLabel("")
        self.detail_meta.setObjectName("dim")
        c.addWidget(self.detail_meta)

        self.detail_text = QTextBrowser()
        self.detail_text.setOpenExternalLinks(True)
        self.detail_text.setMinimumHeight(120)
        self.detail_text.setStyleSheet(
            "QTextBrowser { background: #191c24; border: 1px solid #333947;"
            " border-radius: 8px; padding: 8px; }")
        c.addWidget(self.detail_text)

        row = QHBoxLayout()
        self.detail_install_btn = QPushButton("Install")
        self.detail_install_btn.setObjectName("sendbtn")
        self.detail_install_btn.setFixedHeight(34)
        self.detail_install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detail_install_btn.clicked.connect(self.on_store_install)
        row.addWidget(self.detail_install_btn)

        self.detail_github_btn = QPushButton("\U0001F310  Open on GitHub")
        self.detail_github_btn.setObjectName("linkbtn")
        self.detail_github_btn.setFixedHeight(34)
        self.detail_github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detail_github_btn.clicked.connect(self.on_store_open_github)
        row.addWidget(self.detail_github_btn)
        row.addStretch()
        c.addLayout(row)
        c.addStretch()
        return card

    def _current_store_entry(self):
        key = getattr(self, "_store_selected", "")
        for e in self.store.entries:
            if e.source.key == key:
                return e
        return None

    def show_store_detail(self):
        entry = self._current_store_entry()
        if entry is None:
            return
        pm = QPixmap(str(entry.image_path)) if entry.image_path else QPixmap()
        if pm.isNull():
            pm = self._store_placeholder_pixmap(entry)
        self.detail_img.setPixmap(
            pm.scaledToHeight(200, Qt.TransformationMode.SmoothTransformation))
        self.detail_title.setText(entry.name)
        bits = [f"v{entry.version.lstrip('v')}", f"by {entry.author}"]
        if entry.installed:
            bits.append(f"installed: v{entry.installed_version.lstrip('v')}")
        self.detail_meta.setText("  \u00b7  ".join(bits))
        body = entry.description or "(no description)"
        if entry.error:
            body += f"\n\nCould not be read: {entry.error}"
        self.detail_text.setPlainText(body)
        if not entry.supported:
            self.detail_install_btn.setText(entry.platform_note.capitalize())
            self.detail_install_btn.setEnabled(False)
        elif entry.error:
            self.detail_install_btn.setText("Unavailable")
            self.detail_install_btn.setEnabled(False)
        elif entry.has_update:
            self.detail_install_btn.setText(
                f"Update to v{entry.version.lstrip('v')}")
            self.detail_install_btn.setEnabled(True)
        elif entry.installed:
            self.detail_install_btn.setText("Reinstall")
            self.detail_install_btn.setEnabled(True)
        else:
            self.detail_install_btn.setText("Install")
            self.detail_install_btn.setEnabled(True)

    # --------------------------------------------------------- handlers
    def on_plugin_tab(self, idx):
        idx = 1 if idx == 1 else (2 if idx == 2 else 0)
        self.plugin_stack.setCurrentIndex(idx)
        # the detail view is reached from a tile, so keep "Store" lit for it
        btn = self.plugin_tab_group.button(1 if idx else 0)
        if btn is not None:
            btn.setChecked(True)
        if idx == 1 and not self.store.entries and not self._store_busy:
            self.on_store_refresh()

    def on_store_open(self, key):
        self._store_selected = key
        self.show_store_detail()
        self.plugin_stack.setCurrentIndex(2)

    def on_store_open_github(self):
        entry = self._current_store_entry()
        if entry is not None:
            QDesktopServices.openUrl(QUrl(entry.source.web_url))

    def _installed_versions(self):
        return {pid: p.version for pid, p in self.plugins.plugins.items()}

    def on_store_refresh(self):
        """Fetches the catalogue on a worker thread - the store must never
        freeze the window while GitHub is slow."""
        if self._store_busy:
            return
        self._store_busy = True
        self.store_refresh_btn.setEnabled(False)
        self.store_status.setText("Loading from GitHub \u2026")
        installed = self._installed_versions()

        def work():
            entries = self.store.refresh(installed)
            for e in entries:          # previews, best effort
                self.store.fetch_image(e)
            return entries

        self.run_async(work, self._on_store_refreshed, interval=250)

    def _on_store_refreshed(self, _entries):
        self._store_busy = False
        self.store_refresh_btn.setEnabled(True)
        self.refresh_store_grid()
        self.sync_catalogue_button()

    def sync_catalogue_button(self):
        """Shows the up-arrow only while an update is actually pending."""
        pending = bool(self.store.catalogue_update)
        self.catalogue_btn.setVisible(pending)
        if pending:
            self.catalogue_btn.setText(
                f"\u2B06  Plugin list v{self.store.remote_version}")
            self.catalogue_btn.setToolTip(
                f"A newer plugin list is on GitHub "
                f"(v{self.store.remote_version}, you have "
                f"v{self.store.catalogue_version}). Click to download it - "
                f"new plugins show up in the store without updating the app.")

    def on_catalogue_update(self):
        """Downloads the newer catalogue, then reloads the store from it."""
        version = self.store.apply_catalogue_update()
        if not version:
            QMessageBox.warning(
                self, "Plugin list not updated",
                "The new plugin list could not be saved. See the debug "
                "console for details.")
            self.sync_catalogue_button()
            return
        self.log(f"Store: plugin list updated to v{version}")
        self.catalogue_btn.setVisible(False)
        self.on_plugin_tab(1)
        self.on_store_refresh()

    def on_store_install(self):
        entry = self._current_store_entry()
        if entry is None or self._store_busy:
            return
        self._store_busy = True
        self.detail_install_btn.setEnabled(False)
        self.detail_install_btn.setText("Downloading \u2026")
        key = entry.source.key

        def work():
            try:
                self.store.install(entry, self.plugins)
                return (True, entry.name, "")
            except (StoreError, PluginError) as e:
                return (False, entry.name, str(e))
            except Exception as e:     # noqa: BLE001 - never kill the window
                return (False, entry.name, f"{type(e).__name__}: {e}")

        self.run_async(work,
                       lambda r, k=key: self._on_store_installed(r, k),
                       interval=250)

    def _on_store_installed(self, result, key):
        ok, name, err = result
        self._store_busy = False
        self._store_selected = key
        if ok:
            self.log(f"Store: installed '{name}'")
        else:
            QMessageBox.warning(self, "Installation failed",
                                f"'{name}' could not be installed:\n\n{err}")
            self.log(f"Store: install of '{name}' failed: {err}")
        for e in self.store.entries:
            e.installed_version = self._installed_versions().get(e.pid, "")
            e.has_update = bool(
                e.installed_version and e.version != "?"
                and compare_versions(e.version, e.installed_version) > 0)
        self.refresh_plugin_list()
        self._update_plugin_timer()
        self.refresh_store_grid()
        self.show_store_detail()
        self.update_preview()

    def check_plugin_updates(self):
        """Called by the "Check for updates" button on the Options page.
        Looks for newer plugin versions on GitHub and offers to pull them
        in with one click."""
        if self._store_busy:
            return
        self._store_busy = True
        installed = self._installed_versions()
        if not installed:
            self._store_busy = False
            return

        def work():
            try:
                return (self.store.check_updates(installed), "")
            except Exception as e:    # noqa: BLE001
                return ([], f"{type(e).__name__}: {e}")

        self.run_async(work, self._on_plugin_updates_checked, interval=250)

    def _on_plugin_updates_checked(self, result):
        pending, err = result
        self._store_busy = False
        if err:
            self.log(f"Store: plugin update check failed: {err}")
            return
        self.sync_catalogue_button()
        if not pending:
            self.log("Store: all plugins are up to date")
            return
        lines = "\n".join(
            f"  \u2022 {e.name}: v{e.installed_version.lstrip('v')} "
            f"\u2192 v{e.version.lstrip('v')}" for e in pending)
        answer = QMessageBox.question(
            self, "Plugin updates available",
            f"{len(pending)} plugin(s) can be updated:\n\n{lines}\n\n"
            f"Download and install them now? Your settings are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer == QMessageBox.StandardButton.Yes:
            self.refresh_store_grid()
            self.on_store_update_all()

    def on_store_update_all(self):
        pending = [e for e in self.store.entries if e.has_update]
        if not pending or self._store_busy:
            return
        self._store_busy = True
        self.store_update_btn.setEnabled(False)
        self.store_status.setText(f"Updating {len(pending)} plugin(s) \u2026")

        def work():
            done, failed = [], []
            for e in pending:
                try:
                    self.store.install(e, self.plugins)
                    done.append(e.name)
                except Exception as ex:   # noqa: BLE001
                    failed.append(f"{e.name}: {ex}")
            return (done, failed)

        self.run_async(work, self._on_store_updated_all, interval=250)

    def _on_store_updated_all(self, result):
        done, failed = result
        self._store_busy = False
        self.store_update_btn.setEnabled(True)
        if done:
            self.log(f"Store: updated {', '.join(done)}")
        if failed:
            QMessageBox.warning(self, "Some updates failed",
                                "\n".join(failed))
        self.refresh_plugin_list()
        self._update_plugin_timer()
        self.on_store_refresh()
        self.update_preview()

    # ---------------------------------------------------------- handlers
    def on_plugin_toggled(self, pid, on):
        plugin = self.plugins.plugins.get(pid)
        if plugin is None:
            return
        ok = self.plugins.set_enabled(pid, on)
        self.log(f"Plugin '{plugin.name}': "
                 f"{'enabled' if on else 'disabled'}")
        if on and not ok:
            QMessageBox.warning(
                self, "Plugin could not be loaded",
                f"'{plugin.name}' was enabled but failed to load.\n\n"
                f"{plugin.error or 'See the debug console for details.'}")
        self.refresh_plugin_list()
        # the set of active plugins changed – the live preview timer only
        # runs while at least one of them is loaded
        self._update_plugin_timer()
        self.update_preview()

    def on_plugin_anchor(self, pid, anchor):
        """Anchor changed - only the render order moves, nothing reloads."""
        self.plugins.set_anchor(pid, anchor)
        self.update_preview()

    def plugin_drag(self, pid, global_pos):
        """Live reorder while dragging - the row follows the cursor instead
        of only jumping on release. Mirrors card_drag() on the Apps page:
        count how many other rows the cursor has passed and move there."""
        order = [p.pid for p in self.plugins.ordered()]
        if pid not in order:
            return
        cur = order.index(pid)
        y = global_pos.y()
        others = [k for k in order if k != pid and k in self.plugin_rows]
        new_idx = sum(
            1 for k in others
            if y > self.plugin_rows[k].mapToGlobal(
                self.plugin_rows[k].rect().center()).y())
        if new_idx == cur:
            return
        self.plugins.move_to(pid, new_idx)
        row = self.plugin_rows[pid]
        self.plugin_list.removeWidget(row)
        self.plugin_list.insertWidget(new_idx, row)
        self.update_preview()

    def plugin_drag_end(self, pid):
        self.log("Plugin order: "
                 + " > ".join(p.pid for p in self.plugins.ordered()))

    def on_plugin_line(self, pid, on):
        """Own line on/off. The plugin keeps running either way – this only
        decides whether it prints itself or is placeholder-only."""
        self.plugins.set_line(pid, on)
        self.update_preview()

    def on_plugin_custom(self, pid, on):
        """Custom string on/off – the template field follows along, the
        same way the MediaPlay card greys out its input."""
        self.plugins.set_custom(pid, on)
        edit = self.plugin_inputs.get(pid)
        if edit is not None:
            edit.setEnabled(on)
        self.update_preview()

    def on_plugin_reset(self, pid, edit):
        """Restores the default string from the plugin's plugin.json."""
        default = self.plugins.reset_template(pid)
        edit.setText(default)   # textChanged writes it back through
        self.update_preview()

    def _sync_plugin_dependents(self, pid):
        """Shows each dependent row only while its parent bool is on - the
        same behaviour as the MediaPlay card's sub-options."""
        opts = self.plugins.options(pid)
        for parent, widgets in self.plugin_dependents.get(pid, {}).items():
            on = bool(opts.get(parent))
            for w in widgets:
                w.setVisible(on)

    def on_plugin_option(self, pid, key, value):
        """One of the plugin's own settings changed. The plugin is told
        via on_settings() and the value is saved with the config."""
        self.plugins.set_option(pid, key, value)
        self._sync_plugin_dependents(pid)
        self.update_preview()

    def on_plugin_info(self, pid, anchor):
        plugin = self.plugins.plugins.get(pid)
        if plugin is not None:
            self.plugin_info_popup.open_for(plugin, anchor)

    def on_plugin_delete(self, pid):
        plugin = self.plugins.plugins.get(pid)
        if plugin is None:
            return
        answer = QMessageBox.question(
            self, "Delete plugin?",
            f"Delete '{plugin.name}' for good?\n\n"
            f"The whole folder is removed, including the settings you "
            f"made for this plugin:\n{plugin.folder}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.plugins.uninstall(pid):
            QMessageBox.warning(
                self, "Could not delete",
                f"'{plugin.name}' could not be removed – check the "
                f"permissions on {plugin.folder}.")
        self.refresh_plugin_list()
        # the set of active plugins changed – the live preview timer only
        # runs while at least one of them is loaded
        self._update_plugin_timer()
        self.update_preview()

    def on_install_plugin_zip(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a plugin .zip", str(Path.home()),
            "Plugin archive (*.zip)")
        if not path:
            return
        self._install_plugin_zip(path, overwrite=False)

    def _install_plugin_zip(self, path, overwrite):
        try:
            plugin = self.plugins.install_plugin_zip(path,
                                                     overwrite=overwrite)
        except PluginExistsError as e:
            answer = QMessageBox.question(
                self, "Plugin already installed",
                f"'{e.name}' is already installed.\n\n"
                f"Replace it with the version from the archive? "
                f"Its on/off state is kept.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if answer == QMessageBox.StandardButton.Yes:
                self._install_plugin_zip(path, overwrite=True)
            return
        except PluginError as e:
            QMessageBox.warning(self, "Installation failed", str(e))
            self.log(f"Plugin install failed: {e}")
            return
        except Exception as e:   # noqa: BLE001 – never kill the window
            QMessageBox.warning(self, "Installation failed",
                                f"Unexpected error: {e}")
            self.log(f"Plugin install failed: {e}")
            return

        self.refresh_plugin_list()
        # the set of active plugins changed – the live preview timer only
        # runs while at least one of them is loaded
        self._update_plugin_timer()
        self.update_preview()
        if plugin is not None:
            state = "active" if plugin.enabled else "installed, but off"
            QMessageBox.information(
                self, "Plugin installed",
                f"'{plugin.name}' {plugin.version} installed – {state}.")

    def on_open_plugins_dir(self):
        try:
            PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log(f"Plugins: could not create {PLUGINS_DIR}: {e}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(PLUGINS_DIR)))

    def on_rescan_plugins(self):
        self.plugins.discover()
        self.plugins.load_enabled()
        self.refresh_plugin_list()
        self._update_plugin_timer()
        self.log(f"Plugins: rescanned – {len(self.plugins.plugins)} found")
