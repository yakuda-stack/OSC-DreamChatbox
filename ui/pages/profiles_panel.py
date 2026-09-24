"""
ui/pages/profiles_panel.py - the profile switcher at the bottom of the
sidebar (see core/profiles.py for what a profile is).

It sits in the sidebar rather than on the Options page because it is a
thing you use while playing - "switch to my translation setup" - not a
setting you configure once. One dropdown does both: its first entry
saves the current setup as a new profile, the rest switch. Rename,
delete and the profiles folder are on Options -> General.

Switching stores the live settings into the profile that is active right
now first, so nothing you changed is lost by switching away and back.

Mixin for MainWindow; all `self.*` refer to the MainWindow instance.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from PyQt6.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel,
                             QMessageBox, QPushButton, QSizePolicy,
                             QStyledItemDelegate, QVBoxLayout, QWidget)

from core import profiles

#: dropdown entry for "no profile active"
NO_PROFILE_LABEL = "\u2014 no profile \u2014"

#: first dropdown entry - not a profile, an action
SAVE_NEW_LABEL = "\U0001F4BE  Save as new profile \u2026"
SAVE_NEW_DATA = "\x00save-new"

#: the bin drawn at the right end of every profile row in the dropdown
BIN = "\U0001F5D1"
BIN_WIDTH = 28


def _is_profile(data):
    """True for a row that is a real profile (not an action / "none")."""
    return bool(data) and data != SAVE_NEW_DATA


class _ProfileRowDelegate(QStyledItemDelegate):
    """Paints a small bin at the right end of each profile row."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not _is_profile(index.data(Qt.ItemDataRole.UserRole)):
            return
        rect = option.rect.adjusted(option.rect.width() - BIN_WIDTH, 0,
                                    -4, 0)
        painter.save()
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, BIN)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width() + BIN_WIDTH, max(size.height(), 26))


class _BinClickFilter(QObject):
    """Catches clicks on the bin inside the open dropdown. The click is
    swallowed (press AND release - the release is what would select the
    row) and handed to `on_delete(name)` once the popup is closed."""

    def __init__(self, combo, on_delete):
        super().__init__(combo)
        self.combo = combo
        self.on_delete = on_delete

    def _bin_hit(self, pos):
        view = self.combo.view()
        index = view.indexAt(pos)
        if not index.isValid():
            return None
        name = index.data(Qt.ItemDataRole.UserRole)
        if not _is_profile(name):
            return None
        rect = view.visualRect(index)
        return name if pos.x() >= rect.right() - BIN_WIDTH else None

    def eventFilter(self, obj, ev):
        kind = ev.type()
        if kind in (QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseButtonRelease,
                    QEvent.Type.MouseButtonDblClick):
            name = self._bin_hit(ev.position().toPoint())
            if name:
                if kind == QEvent.Type.MouseButtonRelease:
                    self.combo.hidePopup()
                    QTimer.singleShot(0, lambda n=name: self.on_delete(n))
                return True
        return False


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
            "and plugin settings are shared by all profiles.\n\n"
            "Rename, delete and the profiles folder: Options \u203a "
            "General \u203a Profiles.")
        lay.addWidget(head)

        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip(head.toolTip())
        self.profile_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        # activated, not currentIndexChanged: only a choice the USER made
        # switches anything - refilling the list must never load a profile
        self.profile_combo.activated.connect(self.on_profile_chosen)
        # 🗑 at the end of each profile row in the open list
        self.profile_combo.setItemDelegate(
            _ProfileRowDelegate(self.profile_combo))
        view = self.profile_combo.view()
        self._profile_bin_filter = _BinClickFilter(
            self.profile_combo, self.on_profile_delete)
        view.viewport().installEventFilter(self._profile_bin_filter)

        # 💾 next to the dropdown: saves the current setup into the active
        # profile right now (or asks for a name when none is active).
        # Switching profiles saves too - this is for "I'm done, keep it".
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding,
                                         QSizePolicy.Policy.Fixed)
        row.addWidget(self.profile_combo, 1)
        self.profile_save_btn = QPushButton("\U0001F4BE")
        self.profile_save_btn.setObjectName("iconbtn")   # padding 0
        self.profile_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_save_btn.setFixedSize(
            34, max(28, self.profile_combo.sizeHint().height()))
        self.profile_save_btn.setToolTip(
            "Save the current settings into the active profile.\n"
            "No profile active: save them as a new one.")
        self.profile_save_btn.clicked.connect(self.on_profile_save_button)
        row.addWidget(self.profile_save_btn)
        lay.addLayout(row)
        self.refresh_profile_combo()
        return box

    def on_profile_save_button(self):
        """The 💾 in the sidebar. Flashes a check mark when it worked -
        a save you cannot see happen gets clicked five times."""
        if not self.active_profile():
            self.on_profile_save_new()
            return
        active = self.active_profile()
        if not self._save_active_profile():
            return          # _save_active_profile already warned
        self.log(f"Profile \u201c{active}\u201d saved")
        btn = self.profile_save_btn
        btn.setText("\u2713")
        btn.setToolTip(f"Saved into \u201c{active}\u201d")
        def restore():
            try:
                btn.setText("\U0001F4BE")
                btn.setToolTip(
                    "Save the current settings into the active profile.\n"
                    "No profile active: save them as a new one.")
            except RuntimeError:
                pass        # window closed in the meantime
        QTimer.singleShot(1500, restore)

    def active_profile(self):
        name = self.cfg.get(profiles.ACTIVE_KEY, "") or ""
        # a profile file deleted by hand is simply "none" again
        return name if name and profiles.exists(name) else ""

    def refresh_profile_combo(self):
        combo = self.profile_combo
        active = self.active_profile()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(SAVE_NEW_LABEL, SAVE_NEW_DATA)
        combo.addItem(NO_PROFILE_LABEL, "")
        for name in profiles.list_profiles():
            combo.addItem(name, name)
        pos = combo.findData(active)
        combo.setCurrentIndex(pos if pos >= 1 else 1)
        combo.blockSignals(False)

    # ------------------------------------------------------ actions
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

    def _need_active_profile(self, title):
        name = self.active_profile()
        if not name:
            QMessageBox.information(
                self, title, "No profile is active. Pick one in the "
                "Profile dropdown at the bottom of the sidebar first.")
        return name

    def on_profile_rename(self):
        old = self._need_active_profile("Rename profile")
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

    def on_profile_delete(self, name=None):
        """Deletes `name`, or the active profile when none is given (the
        Options button). The bin in the dropdown passes its row's name."""
        if not isinstance(name, str) or not name:
            name = self._need_active_profile("Delete profile")
        if not name:
            return
        if QMessageBox.question(
                self, "Delete profile",
                f"Delete the profile \u201c{name}\u201d?\n\nYour current "
                "settings stay as they are \u2013 only the saved profile "
                "is removed.") != QMessageBox.StandardButton.Yes:
            return
        profiles.delete_profile(name)
        if name == self.cfg.get(profiles.ACTIVE_KEY):
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

    def apply_start_profile(self, wanted):
        """``--profile=NAME`` on the command line: switch to that profile
        before anything is sent. Without --profile nothing happens here -
        config.json already holds the profile that was active last time.
        Returns (ok, message); ok=False leaves the last profile active."""
        if not wanted:
            return False, ("--profile needs a name, e.g. "
                           "--profile=\"my profile\"")
        name = profiles.find_profile(wanted)
        if not name:
            names = profiles.list_profiles()
            current = self.active_profile() or "no profile"
            return False, (
                f"Profile “{wanted}” not found – starting "
                f"with “{current}”. Available: "
                + (", ".join(names) if names else "none yet"))
        if name == self.active_profile():
            return True, f"Profile “{name}” (--profile)"
        if not self.switch_profile(name):
            return False, (f"Could not load profile “{name}” "
                           "– starting with the last one.")
        return True, f"Profile “{name}” loaded (--profile)"

    def on_profile_chosen(self, idx):
        name = self.profile_combo.itemData(idx) or ""
        if name == SAVE_NEW_DATA:
            self.on_profile_save_new()
            self.refresh_profile_combo()    # never leave the action selected
            return
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
