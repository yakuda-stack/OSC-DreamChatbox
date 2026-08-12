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
from core.constants import (
    PLUGIN_TEMPLATE_URL, PLUGINS_DIR, PLUGINS_REPO_URL)
from core.plugin_store import PluginStore, StoreError, compare_versions
from core.plugins import (
    ACTION_TYPE, ANCHOR_LABELS, PLUGIN_API_VERSION, UNSUPPORTED_TYPE,
    PluginError, PluginExistsError)
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
            f"<span style='font-family:Consolas, monospace'>"
            f"{self._esc(plugin.pid)}</span>")
        # which systems the manifest claims. Worth a line even when the
        # answer is "both", because that is the interesting case for
        # someone deciding whether to recommend a plugin to a friend on
        # the other OS - and the greyed out row only ever tells you about
        # the machine you are sitting at.
        systems = [name for name, ok in (("Linux", plugin.is_linux),
                                         ("Windows", plugin.is_windows)) if ok]
        colour = "#7a8290" if plugin.platform_ok else "#d9884a"
        # joined AFTER escaping: running "Linux & Windows" through _esc
        # would turn the entity back into "&amp;amp;"
        names = " &amp; ".join(self._esc(s) for s in systems) or "neither"
        rows.append(
            f"<span style='color:#7a8290'>OS</span> "
            f"<span style='color:{colour}'>{names}</span>")
        # only worth a line when it is not the default: every manifest
        # without an "api" key is API 1 and always will be
        if int(getattr(plugin, "api_needed", 1) or 1) > 1:
            rows.append(
                f"<span style='color:#7a8290'>Plugin API</span> "
                f"{self._esc(plugin.api_needed)} "
                f"<span style='color:#7a8290'>· this app speaks</span> "
                f"{PLUGIN_API_VERSION}")
        locked = getattr(plugin, "unsupported_options", [])
        if locked:
            names = ", ".join(self._esc(i["label"]) for i in locked[:6])
            rows.append(
                f"<span style='color:#d9884a'>Needs a newer app:</span> "
                f"{names}{' …' if len(locked) > 6 else ''}<br>"
                f"<span style='color:#7a8290;font-size:11px'>The plugin "
                f"still uses these values, they just cannot be edited "
                f"here.</span>")
        if plugin.error:
            rows.append(
                f"<span style='color:#d9884a'>Last error:</span><br>"
                f"<span style='font-family:Consolas, monospace;font-size:11px'>"
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
        self.plugin_option_widgets = {}
        self.plugin_update_btns = {}

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

        # ---- only appears when the catalogue knows of newer versions.
        # Same job as the button on the Store tab, but reachable from the
        # list it is actually about: somebody looking at three rows with
        # an update badge should not have to change tab to press one
        # button.
        self.installed_update_btn = QPushButton("\u2B07  Update all")
        self.installed_update_btn.setFixedHeight(34)
        self.installed_update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.installed_update_btn.setStyleSheet(
            "QPushButton { background: #2b3a4d; border: 1px solid #5b8dc9;"
            " border-radius: 8px; color: #cfe0f5; padding: 0 14px; }"
            "QPushButton:hover { background: #34495f; }"
            "QPushButton:disabled { border-color: #3a4152; color: #7a8290; }")
        self.installed_update_btn.setVisible(False)
        self.installed_update_btn.clicked.connect(self.on_store_update_all)
        btn_row.addWidget(self.installed_update_btn)

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
        repo_btn.setToolTip(
            "Ready-made plugins to download, plus example_template - a "
            "working plugin that shows every setting type next to every "
            "hook, to copy and rename as a starting point.\n\n"
            f"{PLUGINS_REPO_URL}\n{PLUGIN_TEMPLATE_URL}")
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
        # pid -> the "Update to vX" button in that row
        self.plugin_update_btns = {}
        # (pid, key) -> the widget showing that option, so a plugin
        # writing a value with api.set() is reflected on screen
        self.plugin_option_widgets = {}
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
        # the row buttons were set while they were built; the one above
        # the list counts them, so it is the list's job to update it
        self._sync_update_all_button()
        # the Apps page lists the same plugins under All in one ->
        # Parameters; rebuilding it here is what keeps the two in step
        # after a rescan, an install or an enable/disable
        if hasattr(self, "_param_layouts"):
            self.refresh_parameter_lists()

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
        tag.setStyleSheet("font-family: Consolas, monospace; color: #5b8dc9;")
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
        # ---- one-click update, hidden unless the store knows of a newer
        # version. Built for every row (not only the ones with an update
        # pending) so the catalogue arriving later can simply switch it
        # on - see sync_plugin_update_buttons().
        upd_btn = QPushButton("")
        upd_btn.setFixedHeight(24)
        upd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        upd_btn.setStyleSheet(
            "QPushButton { background: #2b3a4d; border: 1px solid #5b8dc9;"
            " border-radius: 6px; color: #cfe0f5; padding: 0 10px;"
            " font-size: 12px; }"
            "QPushButton:hover { background: #34495f; }"
            "QPushButton:disabled { border-color: #3a4152;"
            " color: #7a8290; }")
        upd_btn.setVisible(False)
        upd_btn.clicked.connect(
            lambda _, pid=plugin.pid: self.on_plugin_update(pid))
        head.addWidget(upd_btn)
        self.plugin_update_btns[plugin.pid] = upd_btn
        self._sync_plugin_update_button(plugin.pid)
        head.addStretch()
        texts.addLayout(head)

        # the list shows the SHORT description when the manifest has one,
        # so a row stays one line high no matter how much the author
        # wrote. The long text is still reachable: as the tooltip here,
        # and in full on the store page.
        sub = QLabel(plugin.summary or "\u2013")
        sub.setObjectName("dim")
        sub.setWordWrap(True)
        if plugin.description and plugin.description != plugin.summary:
            sub.setToolTip(plugin.description)
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

    # ------------------------------------------------- updates per row
    def _store_entry_for(self, pid):
        """The catalogue entry belonging to an installed plugin, or None.

        None is the normal state until the store has been loaded once -
        the Installed tab must work offline, so everything built on this
        is optional decoration, never a requirement.
        """
        store = getattr(self, "store", None)
        if store is None or not pid:
            return None
        for entry in store.entries:
            if entry.pid == pid:
                return entry
        return None

    @staticmethod
    def _update_pending(entry):
        """Is this catalogue entry an update worth offering?

        An entry that could not be read is skipped because the download
        would fail anyway, and one whose NEW version does not run here is
        skipped because installing it would only grey the plugin out -
        entry.supported describes the version on GitHub, not the one on
        disk.
        """
        return bool(entry is not None and entry.has_update
                    and entry.supported and not entry.error)

    def pending_updates(self):
        """Catalogue entries that are installed AND worth updating.

        One definition for all three places that ask (the row buttons,
        "Update all" on either tab, the counter on the Store tab), so
        they can never disagree about how many updates there are.
        """
        store = getattr(self, "store", None)
        if store is None:
            return []
        return [e for e in store.entries if self._update_pending(e)]

    def _sync_plugin_update_button(self, pid):
        """Shows or hides one row's update button against the catalogue."""
        btn = getattr(self, "plugin_update_btns", {}).get(pid)
        if btn is None:
            return
        entry = self._store_entry_for(pid)
        pending = self._update_pending(entry)
        btn.setVisible(pending)
        if not pending:
            return
        new = entry.version.lstrip("v")
        btn.setText(f"\u2B06  Update to v{new}")
        btn.setEnabled(not self._store_busy)
        btn.setToolTip(
            f"v{entry.installed_version.lstrip('v')} is installed, "
            f"v{new} is on GitHub.\nDownloads and installs it right away - "
            f"your settings for this plugin are kept.")

    def _sync_update_all_button(self):
        """The "Update all" button on the Installed tab."""
        btn = getattr(self, "installed_update_btn", None)
        if btn is None:
            return
        pending = self.pending_updates()
        btn.setVisible(bool(pending))
        if not pending:
            return
        btn.setText(f"\u2B07  Update all ({len(pending)})")
        btn.setEnabled(not self._store_busy)
        names = ", ".join(e.name for e in pending[:6])
        btn.setToolTip(
            f"Newer versions on GitHub: {names}"
            f"{' \u2026' if len(pending) > 6 else ''}\n"
            f"Downloads and installs all of them - your settings are kept.")

    def sync_plugin_update_buttons(self):
        """Re-checks every row after the catalogue changed.

        Deliberately not refresh_plugin_list(): the store refresh lands
        seconds after the page was opened, and rebuilding the rows then
        would collapse a Settings block somebody just opened.
        """
        for pid in list(getattr(self, "plugin_update_btns", {})):
            self._sync_plugin_update_button(pid)
        self._sync_update_all_button()

    def scan_plugin_updates(self):
        """One quiet catalogue load per session, triggered by opening the
        Plugins page. Without it the Installed tab could only ever show
        an update after a visit to the Store tab.

        Reuses on_store_refresh() so there is exactly one code path that
        talks to GitHub - including its error handling and its image
        cache, which is what keeps the Store tab instant afterwards.
        """
        if getattr(self, "_store_scanned", False) or self._store_busy:
            return
        if not self.plugins.plugins:
            return          # nothing installed - nothing to compare
        self._store_scanned = True
        self.on_store_refresh()

    def on_plugin_update(self, pid):
        """The row button: download and install the newer version."""
        entry = self._store_entry_for(pid)
        if entry is None or not entry.has_update or self._store_busy:
            return
        self._store_busy = True
        name = entry.name or pid
        btn = self.plugin_update_btns.get(pid)
        if btn is not None:
            btn.setEnabled(False)
            btn.setText("Updating \u2026")

        def work():
            try:
                self.store.install(entry, self.plugins)
                return (True, name, "")
            except (StoreError, PluginError) as e:
                return (False, name, str(e))
            except Exception as e:     # noqa: BLE001 - never kill the window
                return (False, name, f"{type(e).__name__}: {e}")

        self.run_async(
            work, self._on_plugin_updated, interval=250,
            # the busy flag is set above, so a failure that never reaches
            # work()'s own except has to clear it here or the Store tab
            # stays frozen for the rest of the session
            on_error=lambda e, n=name: self._on_plugin_updated(
                (False, n, f"{type(e).__name__}: {e}")))

    def _on_plugin_updated(self, result):
        ok, name, err = result
        self._store_busy = False
        if ok:
            self.log(f"Store: updated '{name}'")
        else:
            QMessageBox.warning(self, "Update failed",
                                f"'{name}' could not be updated:\n\n{err}")
            self.log(f"Store: update of '{name}' failed: {err}")
        # no network: the catalogue is unchanged, only our own folder is
        self.store.sync_installed(self._installed_versions())
        self.refresh_plugin_list()
        self._update_plugin_timer()
        self.refresh_store_grid()
        self.update_preview()

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

        plus = QPushButton("+")
        plus.setObjectName("iconbtn")
        plus.setFixedSize(30, 30)
        plus.setCursor(Qt.CursorShape.PointingHandCursor)
        plus.setToolTip(
            "Insert a placeholder or a formatting tag at the cursor.\n"
            "Only plugin values are offered: a plugin template is rendered "
            "against the plugin values alone, so a hardware or media name "
            "would come out empty here.")
        plus.clicked.connect(
            lambda _=False, e=edit, b=plus, pid=plugin.pid:
                self.open_placeholder_menu(e, b, scope="plugin", pid=pid))
        row.addWidget(plus)

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
            # parent key -> [(dependent widget, wanted values)], so a
            # sub-option can hide with its parent (Max world name length
            # under World name)
            deps = {}
            self._add_plugin_options(plugin, plugin.schema, c, opts, deps)
            self.plugin_dependents[plugin.pid] = deps
            self._sync_plugin_dependents(plugin.pid)

        # ----- the plugin's own UI, if it brings one. The settings
        # schema covers options; a Start button, a live log or a list the
        # user adds rows to cannot be expressed as an option, so a plugin
        # may hand us a finished widget instead.
        own = self.plugins.build_widget(plugin.pid, self)
        if isinstance(own, QWidget):
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setObjectName("hline")
            c.addWidget(sep)
            c.addWidget(own)
        return content

    def _add_plugin_options(self, plugin, schema, layout, opts, deps,
                            depth=0):
        """Fills one layout with the rows of a schema level. Called again
        for every group, which is what makes groups nestable."""
        for item in schema:
            if item["type"] == "group":
                w = self._build_plugin_group(plugin, item, opts, deps, depth)
            else:
                w = self._build_plugin_option(plugin, item, opts)
            if item.get("depends"):
                deps.setdefault(item["depends"], []).append(
                    (w, item.get("depends_value") or []))
                # indent it so it reads as belonging to the row above
                w.setContentsMargins(24, 0, 0, 0)
            layout.addWidget(w)

    def _build_plugin_group(self, plugin, item, opts, deps, depth):
        """A collapsible block of settings – the same expander gesture as
        the card's own Settings button, one level further in.

        Like that one it starts collapsed unless the manifest asks for
        "expanded": true. The open/closed state is a view detail, so it
        is deliberately not written to the plugin's config.
        """
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 2, 0, 2)
        box.setSpacing(6)

        body = QFrame()
        body.setObjectName("innerbox")
        inner = QVBoxLayout(body)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(8)
        self._add_plugin_options(plugin, item["items"], inner, opts, deps,
                                 depth + 1)

        btn = QPushButton()
        btn.setObjectName("expander")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if item["hint"]:
            btn.setToolTip(item["hint"])
        btn.toggled.connect(
            lambda on, b=btn, w=body, t=item["label"]:
            self._set_group_expanded(b, w, t, on))
        # set the label/visibility once by hand: toggled only fires when
        # the state actually changes, and False -> False does not
        btn.setChecked(bool(item.get("expanded")))
        self._set_group_expanded(btn, body, item["label"], btn.isChecked())

        box.addWidget(btn)
        box.addWidget(body)
        return holder

    @staticmethod
    def _set_group_expanded(btn, body, label, expanded):
        body.setVisible(expanded)
        btn.setText(("\u2304  " if expanded else "\u203A  ") + label)

    def _build_plugin_option(self, plugin, item, opts):
        """One widget for one entry of the plugin's "settings" schema.

        A type this build does not know arrives here as "unsupported"
        rather than not at all: the value exists and the plugin uses it,
        only the editor is missing, and that is worth saying out loud.
        """
        pid, key, kind = plugin.pid, item["key"], item["type"]
        # .get(): an action row is a button, not a value - it has no
        # default and never appears in the options dict
        value = opts.get(key, item.get("default", ""))

        if kind == UNSUPPORTED_TYPE:
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            lbl = QLabel(f"\U0001F512  {item['label']}")
            lbl.setObjectName("dim")
            row.addWidget(lbl)
            note = QLabel(item.get("reason") or "not supported here")
            note.setObjectName("dim")
            note.setStyleSheet("color: #d9884a;")
            note.setWordWrap(True)
            row.addWidget(note, 1)
            holder.setToolTip(
                (item["hint"] + "\n\n" if item["hint"] else "")
                + f"The plugin keeps using this value ({value!r}); this "
                  f"version of the app just cannot show an editor for it.")
            return holder

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
            self._remember_option(pid, key, chk)
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
            self._remember_option(pid, key, w)
            return holder

        if kind == "choice":
            # the stored value is the choice's "value", never its label,
            # so a plugin author can rename a label without invalidating
            # every config that already picked it
            w = QComboBox()
            for val, label in item["choices"]:
                w.addItem(label, val)
            idx = w.findData(str(value))
            w.setCurrentIndex(idx if idx >= 0 else 0)
            w.setMinimumWidth(170)
            if item["hint"]:
                w.setToolTip(item["hint"])
            w.currentIndexChanged.connect(
                lambda _i, p=pid, k=key, cb=w:
                self.on_plugin_option(p, k, cb.currentData()))
            row.addWidget(w)
            row.addStretch()
            self._remember_option(pid, key, w)
            return holder

        if kind == "path":
            # line edit plus a picker. Typing stays possible on purpose:
            # a path on a network share or one that does not exist yet
            # cannot be reached through the dialog, and pasting is often
            # faster than clicking through six folders.
            w = QLineEdit()
            w.setMaxLength(400)
            w.setText(str(value))
            if item.get("placeholder"):
                w.setPlaceholderText(item["placeholder"])
            if item["hint"]:
                w.setToolTip(item["hint"])
            w.textChanged.connect(
                lambda text, p=pid, k=key: self.on_plugin_option(p, k, text))
            row.addWidget(w, 1)

            browse = QPushButton("\U0001F4C1")
            browse.setObjectName("iconbtn")
            browse.setFixedSize(30, 28)
            browse.setCursor(Qt.CursorShape.PointingHandCursor)
            browse.setToolTip("Choose a folder" if item.get("mode") == "dir"
                              else "Choose a file")
            browse.clicked.connect(
                lambda _c, it=item, edit=w: self._pick_plugin_path(it, edit))
            row.addWidget(browse)
            self._remember_option(pid, key, w)
            return holder

        if kind == ACTION_TYPE:
            # a button, not a value. The label on the left says what it
            # is for, the button says what it does.
            colours = {
                "primary": ("#2b3a4d", "#5b8dc9", "#cfe0f5"),
                "danger": ("#3a2a2c", "#b5504a", "#f0d6d4"),
                "normal": ("#232733", "#333947", "#cfd6e2"),
            }
            bg, edge, fg = colours.get(item.get("style"), colours["normal"])
            btn = QPushButton(item.get("button") or item["label"])
            btn.setFixedHeight(28)
            btn.setMinimumWidth(120)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: {bg}; border: 1px solid {edge};"
                f" border-radius: 8px; color: {fg}; padding: 0 14px; }}"
                f"QPushButton:hover {{ background: {edge}; }}")
            if item["hint"]:
                btn.setToolTip(item["hint"])
            answer = QLabel("")
            answer.setObjectName("dim")
            answer.setWordWrap(True)
            btn.clicked.connect(
                lambda _c, p=pid, k=key, out=answer:
                self._run_plugin_action(p, k, out))
            row.addWidget(btn)
            row.addWidget(answer, 1)
            return holder

        if kind == "label":
            # read-only, and updated by api.set() like any other option -
            # which is how a plugin gets a live status line without
            # having to build a widget for it
            w = QLabel(str(value))
            w.setWordWrap(True)
            w.setStyleSheet("color: #c8d2e0;")
            if item["hint"]:
                w.setToolTip(item["hint"])
            row.addWidget(w, 1)
            self._remember_option(pid, key, w)
            return holder

        if kind == "emoji":
            # the same popup the Personal Status, MediaPlay and Hardware
            # custom strings use. A plugin icon is picked exactly the way
            # every other icon in the app is, instead of each plugin
            # inventing its own answer to "how do I type an emoji".
            w = QLineEdit()
            w.setMaxLength(24)
            w.setText(str(value))
            w.setMinimumWidth(90)
            if item.get("placeholder"):
                w.setPlaceholderText(item["placeholder"])
            if item["hint"]:
                w.setToolTip(item["hint"])
            w.textChanged.connect(
                lambda text, p=pid, k=key: self.on_plugin_option(p, k, text))
            row.addWidget(w, 1)

            ico = QPushButton("\U0001F600")
            ico.setObjectName("iconbtn")
            ico.setFixedSize(30, 28)
            ico.setCursor(Qt.CursorShape.PointingHandCursor)
            ico.setToolTip("Insert icon")
            ico.clicked.connect(
                lambda _c, e=w, b=ico: self.emoji_popup.open_for(e, b))
            row.addWidget(ico)
            self._remember_option(pid, key, w)
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
            if item.get("secret"):
                # tokens and API keys: shoulder-surfing protection, not
                # encryption - the value still sits in config.json
                w.setEchoMode(QLineEdit.EchoMode.Password)
            w.setText(str(value))
            w.textChanged.connect(
                lambda text, p=pid, k=key: self.on_plugin_option(p, k, text))
            row.addWidget(w, 1)
        self._remember_option(pid, key, w)
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
        repo_btn.setToolTip(
            "Every plugin in this catalogue, plus example_template to "
            "start your own.\n\n"
            f"{PLUGINS_REPO_URL}\n{PLUGIN_TEMPLATE_URL}")
        repo_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(PLUGINS_REPO_URL)))
        btns.addWidget(repo_btn)

        template_btn = QPushButton("\U0001F4C4  Write a plugin")
        template_btn.setObjectName("linkbtn")
        template_btn.setFixedHeight(34)
        template_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        template_btn.setToolTip(
            "example_template: every setting type next to every hook, in a "
            "plugin that actually runs. Copy the folder, rename it, delete "
            f"what you don't need.\n\n{PLUGIN_TEMPLATE_URL}")
        template_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(PLUGIN_TEMPLATE_URL)))
        btns.addWidget(template_btn)
        btns.addStretch()
        c.addLayout(btns)

        hint = QLabel(
            "Catalogue from <span style='font-family:Consolas, monospace'>plugins.json</span>"
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
        updates = len(self.pending_updates())
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

        # only shown for a plugin that is actually installed. Uninstalling
        # from here is the same operation as the bin on the Installed
        # page - people who found a plugin in the store look for the way
        # out in the store as well, not in a second list.
        self.detail_delete_btn = QPushButton("\U0001F5D1  Uninstall")
        self.detail_delete_btn.setObjectName("linkbtn")
        self.detail_delete_btn.setFixedHeight(34)
        self.detail_delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detail_delete_btn.setStyleSheet(
            "QPushButton { color: #d9884a; }"
            "QPushButton:hover { color: #f0b183; }")
        self.detail_delete_btn.clicked.connect(self.on_store_delete)
        self.detail_delete_btn.setVisible(False)
        row.addWidget(self.detail_delete_btn)
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
        self.detail_delete_btn.setVisible(bool(entry.installed and entry.pid))
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

    def on_store_delete(self):
        """Uninstall the plugin this store page is showing.

        Reuses on_plugin_delete() rather than repeating the confirmation
        and the folder handling: one delete path means the warning about
        losing the plugin's settings can never drift apart between the
        two places it is offered from.
        """
        entry = self._current_store_entry()
        if entry is None or not entry.pid:
            return
        if entry.pid not in self.plugins.plugins:
            # already gone - the list is just stale
            self.on_store_refresh_installed_state()
            return
        self.on_plugin_delete(entry.pid)
        self.on_store_refresh_installed_state()

    def on_store_refresh_installed_state(self):
        """Re-mark the catalogue against what is on disk. Deliberately
        NOT store.refresh(): that re-fetches every manifest over the
        network, and this runs on the GUI thread. Nothing upstream
        changed anyway - only our own folder did."""
        self.store.sync_installed(self._installed_versions())
        self.refresh_store_grid()
        self.show_store_detail()
        self.sync_plugin_update_buttons()

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

        # a StoreError (offline, GitHub 503, rate limit) used to leave
        # _store_busy True and the button disabled for good - one bad
        # moment cost the Store tab for the whole session
        self.run_async(work, self._on_store_refreshed, interval=250,
                       on_error=lambda e: self._store_release(
                           f"Catalogue could not be loaded: {e}"))

    def _store_release(self, message=""):
        """Single place that puts the Store back into a usable state.

        Every background job here sets _store_busy and disables a button;
        if the job blows up, something has to undo that, or the tab stays
        frozen with no way back short of restarting the app.
        """
        self._store_busy = False
        for name in ("store_refresh_btn", "store_update_btn"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(True)
        # the per-plugin buttons are disabled while a job runs, so they
        # belong to "put the page back into a usable state" as well
        self.sync_plugin_update_buttons()
        if message:
            self.log(f"Store: {message}")
            if getattr(self, "store_status", None) is not None:
                self.store_status.setText(f"\u26A0 {message}")

    def _on_store_refreshed(self, _entries):
        self._store_busy = False
        self.store_refresh_btn.setEnabled(True)
        self.refresh_store_grid()
        self.sync_catalogue_button()
        # the Installed rows carry the same information now
        self.sync_plugin_update_buttons()

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
        self.sync_plugin_update_buttons()
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
        """Re-download every installed plugin with a newer version.

        Reached from the Store tab and from the Installed tab; both
        buttons are the same operation, so both are disabled while it
        runs.
        """
        pending = self.pending_updates()
        if not pending or self._store_busy:
            return
        self._store_busy = True
        self.store_update_btn.setEnabled(False)
        if getattr(self, "installed_update_btn", None) is not None:
            self.installed_update_btn.setEnabled(False)
            self.installed_update_btn.setText(
                f"Updating {len(pending)} plugin(s) \u2026")
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

        self.run_async(work, self._on_store_updated_all, interval=250,
                       on_error=lambda e: self._store_release(
                           f"Update failed: {e}"))

    def _on_store_updated_all(self, result):
        done, failed = result
        self._store_busy = False
        self.store_update_btn.setEnabled(True)
        if done:
            self.log(f"Store: updated {', '.join(done)}")
        if failed:
            QMessageBox.warning(self, "Some updates failed",
                                "\n".join(failed))
        # mark what is on disk BEFORE the rows are rebuilt, or every row
        # that was just updated would come back with its update button
        # still on until the refresh below lands
        self.store.sync_installed(self._installed_versions())
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
        """Shows each dependent row only while its parent allows it - the
        same behaviour as the MediaPlay card's sub-options.

        Without "depends_value" the parent is tested for truthiness, which
        is the bool case every older plugin uses. With it, the parent's
        value has to be one of the listed ones, which is how a row hangs
        off a dropdown instead of a checkbox.
        """
        opts = self.plugins.options(pid)
        for parent, targets in self.plugin_dependents.get(pid, {}).items():
            value = opts.get(parent)
            for w, wanted in targets:
                w.setVisible(str(value) in wanted if wanted else bool(value))

    def _pick_plugin_path(self, item, edit):
        """The picker behind a "path" setting.

        Starts where the field already points, which is the difference
        between one click and hunting through the filesystem again. Qt's
        dialog is the native one on Windows and the platform one on
        Linux, so nothing here has to know which is which - only the
        name filters do, and those come from the plugin.
        """
        text = edit.text().strip()
        # an empty field must land in $HOME, not in the process working
        # directory - Path("") is Path("."), which is wherever the app
        # happened to be started from
        current = Path(text).expanduser() if text else Path.home()
        start = current if current.is_dir() else current.parent
        if not start.is_dir():
            start = Path.home()

        if item.get("mode") == "dir":
            picked = QFileDialog.getExistingDirectory(
                self, item["label"], str(start))
        else:
            filters = list(item.get("filters") or [])
            # always offer a way out of the filter: an AppImage renamed
            # by the browser, a wrapper script, a build with no suffix
            if not any(f.strip().endswith("(*)") for f in filters):
                filters.append("All files (*)")
            picked, _sel = QFileDialog.getOpenFileName(
                self, item["label"], str(start), ";;".join(filters))
        if picked:
            # setText fires textChanged, which stores the value - the one
            # path through on_plugin_option(), so nothing is written twice
            edit.setText(picked)

    def _run_plugin_action(self, pid, key, out_label):
        """Press an action button and show whatever the plugin answers.

        The hook runs on the GUI thread, so a plugin doing something slow
        in there freezes the window - that is the plugin's job to get
        right, and the docs say so. What is NOT its job is a crash: the
        call goes through the manager's _safe_call, so a raising button
        leaves an error line and nothing else.
        """
        answer = self.plugins.trigger_action(pid, key)
        out_label.setText(str(answer) if answer else "")
        self._sync_plugin_dependents(pid)
        self.update_preview()

    def _remember_option(self, pid, key, widget):
        """Note which widget shows which option, so sync_plugin_option()
        can find it again."""
        self.plugin_option_widgets[(pid, key)] = widget

    def sync_plugin_option(self, pid, key, value):
        """A plugin wrote one of its own settings (api.set) – put the new
        value into the widget the user is looking at.

        Called through PluginManager._ui_call(), which guarantees this
        runs in the GUI thread even when the plugin wrote from a worker.
        Signals are blocked while the widget is updated, otherwise the
        change would travel straight back into set_option() and the
        plugin would be answering its own write.
        """
        widget = self.plugin_option_widgets.get((pid, key))
        if widget is None:
            return
        try:
            blocked = widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                idx = widget.findData(str(value))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, (QSpinBox, QSlider)):
                widget.setValue(int(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))
            elif isinstance(widget, QLabel):
                # a "label" row: this is the whole point of it, a plugin
                # writing its own status text into the settings card
                widget.setText(str(value))
            widget.blockSignals(blocked)
        except (RuntimeError, TypeError, ValueError):
            # RuntimeError: the page was rebuilt and this widget is gone.
            # Nothing to do - the fresh one reads the stored value anyway.
            self.plugin_option_widgets.pop((pid, key), None)
            return
        self._sync_plugin_dependents(pid)

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
