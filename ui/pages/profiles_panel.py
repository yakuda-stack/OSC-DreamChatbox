"""
ui/pages/profiles_panel.py - the profile switcher at the bottom of the
sidebar (see core/profiles.py for what a profile is).

It sits in the sidebar rather than on the Options page because it is a
thing you use while playing - "switch to my translation setup" - not a
setting you configure once. One dropdown to switch, one ⋯ menu for
save / rename / delete.

Switching stores the live settings into the profile that is active right
now first, so nothing you changed is lost by switching away and back.

Mixin for MainWindow; all `self.*` refer to the MainWindow instance.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel,
                             QMenu, QMessageBox, QPushButton, QVBoxLayout,
                             QWidget)

from core import profiles

#: dropdown entry for "no profile active"
NO_PROFILE_LABEL = "\u2014 no profile \u2014"


class ProfilesMixin:
    # ------------------------------------------------------------ build
    def build_profiles_panel(self):
        """The sidebar block. Returns the widget to add."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        head = QLabel("Profile")
        head.setObjectName("dim")
        head.setToolTip(
            "Profiles are complete setups you can switch between with one "
            "click \u2013 e.g. \u201cGaming\u201d, \u201cMusic\u201d, "
            "\u201cTranslation\u201d.\n\nWhatever you change while a "
            "profile is active is kept in that profile. OSC target, theme "
            "and plugin settings are shared by all profiles.")
        lay.addWidget(head)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip(head.toolTip())
        # activated, not currentIndexChanged: only a choice the USER made
        # switches anything - refilling the list must never load a profile
        self.profile_combo.activated.connect(self.on_profile_chosen)
        row.addWidget(self.profile_combo, 1)
        self.profile_menu_btn = QPushButton("\u22EF")
        self.profile_menu_btn.setObjectName("linkbtn")
        self.profile_menu_btn.setFixedSize(30, 28)
        self.profile_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_menu_btn.setToolTip("Save, rename or delete profiles")
        self.profile_menu_btn.clicked.connect(
            lambda _=False: self.on_profile_menu())
        row.addWidget(self.profile_menu_btn)
        lay.addLayout(row)
        self.refresh_profile_combo()
        return box

    def active_profile(self):
        name = self.cfg.get(profiles.ACTIVE_KEY, "") or ""
        # a profile file deleted by hand is simply "none" again
        return name if name and profiles.exists(name) else ""

    def refresh_profile_combo(self):
        combo = self.profile_combo
        active = self.active_profile()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(NO_PROFILE_LABEL, "")
        for name in profiles.list_profiles():
            combo.addItem(name, name)
        pos = combo.findData(active)
        combo.setCurrentIndex(pos if pos >= 0 else 0)
        combo.blockSignals(False)

    # --------------------------------------------------------- menu
    def on_profile_menu(self):
        active = self.active_profile()
        menu = QMenu(self)
        menu.addAction("\U0001F4BE  Save current setup as new profile \u2026",
                       self.on_profile_save_new)
        if active:
            menu.addAction(f"\u2B07  Save into \u201c{active}\u201d now",
                           self.on_profile_save_active)
            menu.addAction(f"\u270F\uFE0F  Rename \u201c{active}\u201d \u2026",
                           self.on_profile_rename)
            menu.addAction(f"\U0001F5D1  Delete \u201c{active}\u201d \u2026",
                           self.on_profile_delete)
        menu.addSeparator()
        menu.addAction("\U0001F4C2  Open profiles folder",
                       self.on_profile_open_folder)
        menu.exec(self.profile_menu_btn.mapToGlobal(
            self.profile_menu_btn.rect().bottomLeft()))

    def _ask_profile_name(self, title, text, preset=""):
        name, ok = QInputDialog.getText(self, title, text, text=preset)
        if not ok:
            return ""
        name = profiles.clean_name(name)
        if not name:
            QMessageBox.warning(self, title, "Please enter a name.")
        return name

    def on_profile_save_new(self):
        name = self._ask_profile_name(
            "New profile",
            "Name for the current setup (e.g. Gaming, Translation):")
        if not name:
            return
        if profiles.exists(name) and QMessageBox.question(
                self, "New profile",
                f"A profile called \u201c{name}\u201d already exists. "
                "Replace it with the current setup?") \
                != QMessageBox.StandardButton.Yes:
            return
        self._store_live_config()
        try:
            name = profiles.save_profile(name, self.cfg)
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "New profile",
                                f"Could not save the profile:\n{e}")
            return
        self.cfg[profiles.ACTIVE_KEY] = name
        self.save_config()
        self.refresh_profile_combo()
        self.log(f"Profile \u201c{name}\u201d saved and active")

    def on_profile_save_active(self):
        active = self.active_profile()
        if active and self._save_active_profile():
            self.log(f"Profile \u201c{active}\u201d saved")

    def on_profile_rename(self):
        old = self.active_profile()
        if not old:
            return
        new = self._ask_profile_name("Rename profile", "New name:", old)
        if not new or new == old:
            return
        try:
            new = profiles.rename_profile(old, new)
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "Rename profile", str(e))
            return
        self.cfg[profiles.ACTIVE_KEY] = new
        self.save_config()
        self.refresh_profile_combo()
        self.log(f"Profile renamed: \u201c{old}\u201d \u2192 \u201c{new}\u201d")

    def on_profile_delete(self):
        name = self.active_profile()
        if not name:
            return
        if QMessageBox.question(
                self, "Delete profile",
                f"Delete the profile \u201c{name}\u201d?\n\nYour current "
                "settings stay as they are \u2013 only the saved profile "
                "is removed.") != QMessageBox.StandardButton.Yes:
            return
        profiles.delete_profile(name)
        self.cfg[profiles.ACTIVE_KEY] = ""
        self.save_config()
        self.refresh_profile_combo()
        self.log(f"Profile \u201c{name}\u201d deleted")

    def on_profile_open_folder(self):
        profiles.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(profiles.PROFILES_DIR)))

    # ------------------------------------------------------- switching
    def _store_live_config(self):
        """Flushes a pending debounced write so cfg and disk agree."""
        self._save_timer.stop()
        self._write_config()

    def _save_active_profile(self):
        """Writes the live settings into the active profile. False (and a
        warning) when that failed - the caller must then NOT switch, or
        the changes would be gone."""
        active = self.active_profile()
        if not active:
            return True
        self._store_live_config()
        try:
            profiles.save_profile(active, self.cfg)
            return True
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(
                self, "Profiles",
                f"Could not save the profile \u201c{active}\u201d:\n{e}")
            return False

    def on_profile_chosen(self, idx):
        name = self.profile_combo.itemData(idx) or ""
        if name == self.active_profile():
            return
        if not self.switch_profile(name):
            self.refresh_profile_combo()    # show what is really active

    def switch_profile(self, name):
        """Stores the active profile, then loads `name` ("" = detach: keep
        the current settings, just stop saving them into a profile).
        Returns True when the switch happened."""
        if not self._save_active_profile():
            return False
        if not name:
            self.cfg[profiles.ACTIVE_KEY] = ""
            self.save_config()
            self.refresh_profile_combo()
            self.log("Profile: none active")
            return True
        try:
            stored = profiles.read_profile(name)
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "Profiles",
                                f"Could not read the profile "
                                f"\u201c{name}\u201d:\n{e}")
            return False

        # a microphone or game-audio listener running on the OLD settings
        # would keep going with a device/language the new profile may not
        # even have - stop both, the user starts them again
        stopped = []
        if getattr(self, "stt_button", None) is not None \
                and self.stt_button.isChecked():
            self.stt_button.setChecked(False)
            stopped.append("Speech to Text")
        if getattr(self, "twoway_btn", None) is not None \
                and self.twoway_btn.isChecked():
            self.twoway_btn.setChecked(False)
            stopped.append("Two-way listening")

        raw = profiles.merge_for_load(self.cfg, stored)
        raw[profiles.ACTIVE_KEY] = name
        self.cfg = self.load_config(raw)
        # runtime state that indexes into the old setup
        self.status_index = 0
        self.pending_status_index = None
        self.aio_index = 0
        self.media.preferred = self.cfg.get("media_source", "")
        self.media.fallback = bool(self.cfg.get("media_source_fallback",
                                                True))
        self.apply_config_to_ui()
        self.refresh_media_sources()
        self.update_timers()
        self.update_preview()
        self.refresh_profile_combo()
        self.log(f"Profile \u201c{name}\u201d loaded"
                 + (f" \u2013 stopped: {', '.join(stopped)}"
                    if stopped else ""))
        return True
