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
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)
from core.constants import PLUGINS_DIR, PLUGINS_REPO_URL
from core.plugins import PluginError, PluginExistsError
from ui.ui_main import ToggleLabel, ToggleSwitch


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
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("Plugins")
        title.setObjectName("pagetitle")
        layout.addWidget(title)

        self.plugin_info_popup = PluginInfoPopup()
        # pid -> widget, rebuilt on every refresh_plugin_list()
        self.plugin_expanders = {}
        self.plugin_inputs = {}

        # ------------------------------------------------ actions card
        card = QFrame()
        card.setObjectName("card")
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 14, 16, 16)
        c.setSpacing(10)

        head = QHBoxLayout()
        ctitle = QLabel("Installed plugins")
        ctitle.setObjectName("cardtitle")
        head.addWidget(ctitle)
        head.addStretch()
        self.plugin_count_lbl = QLabel("")
        self.plugin_count_lbl.setObjectName("dim")
        head.addWidget(self.plugin_count_lbl)
        c.addLayout(head)

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

        hint = QLabel(
            f"Each plugin is one folder with a plugin.json and its python "
            f"file in <span style='font-family:monospace'>{PLUGINS_DIR}</span>."
            f" Turning a plugin off keeps the files – it is simply no longer "
            f"loaded, now and on the next start. Every plugin is usable as "
            f"<span style='font-family:monospace'>{{plugin_id}}</span> in "
            f"status texts, in the Apps custom strings and in All-in-one.")
        hint.setObjectName("dim")
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        c.addWidget(hint)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("hline")
        c.addWidget(line)

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

        layout.addWidget(card)
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
        plugins = list(self.plugins.plugins.values())
        for plugin in plugins:
            self.plugin_list.addWidget(self._build_plugin_row(plugin))

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

        toggle = ToggleSwitch()
        toggle.blockSignals(True)
        toggle.setChecked(plugin.enabled)
        toggle.blockSignals(False)
        toggle.toggled.connect(
            lambda on, pid=plugin.pid: self.on_plugin_toggled(pid, on))
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
        if plugin.error:
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

        del_btn = QPushButton("\U0001F5D1")
        del_btn.setObjectName("iconbtn")
        del_btn.setFixedSize(30, 30)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setToolTip("Delete this plugin from disk")
        del_btn.clicked.connect(
            lambda _, pid=plugin.pid: self.on_plugin_delete(pid))
        outer.addWidget(del_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(outer)

        # ---------------------------------------------------- settings
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
            for item in plugin.schema:
                c.addWidget(self._build_plugin_option(plugin, item, opts))
        return content

    def _build_plugin_option(self, plugin, item, opts):
        """One widget for one entry of the plugin's "settings" schema.
        Unknown types never reach here – _parse_schema drops them."""
        pid, key, kind = plugin.pid, item["key"], item["type"]
        value = opts.get(key, item["default"])

        if kind == "bool":
            w = QCheckBox(item["label"])
            w.setChecked(bool(value))
            w.toggled.connect(
                lambda on, p=pid, k=key: self.on_plugin_option(p, k, on))
            if item["hint"]:
                w.setToolTip(item["hint"])
            return w

        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel(item["label"])
        if item["hint"]:
            lbl.setToolTip(item["hint"])
        row.addWidget(lbl)

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

    def on_plugin_option(self, pid, key, value):
        """One of the plugin's own settings changed. The plugin is told
        via on_settings() and the value is saved with the config."""
        self.plugins.set_option(pid, key, value)
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
            f"The whole folder is removed:\n{plugin.folder}",
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
