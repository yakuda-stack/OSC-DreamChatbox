"""
core/osinfo.py – the ONE place that asks "what are we running on?"

Everything platform dependent in the app funnels through here:

    from core.osinfo import IS_WINDOWS, IS_LINUX, OS_NAME

Why a separate module and not core/constants.py? Because constants.py
already needs the answer itself (the config folder differs per OS), and
core/plugins.py used to compute the same three flags a second time. One
source of truth means a plugin, a backend and the store can never
disagree about which platform they are on.

Nothing here imports from the rest of the app, so this module can be
imported from anywhere without an import cycle.

Two things it also answers:

* ``resource_root()`` – where the read-only files that ship WITH the app
  live (assets/, config/plugins.json). Running from source that is the
  project folder; inside a PyInstaller .exe it is the unpacked bundle.
* ``config_dir()`` – where the user's own writable state lives:
      Linux    ~/.config/OSC-DreamChatbox
      Windows  %APPDATA%\\OSC-DreamChatbox
  plus a one-time migration for anyone who already ran the app from
  source on Windows, where it wrote to ~/.config like on Linux.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

# --------------------------------------------------------------- flags
# decided per start, never stored: a config carried to another machine
# would otherwise pick the wrong branch
SYSTEM = platform.system()          # "Linux" / "Windows" / "Darwin"

IS_WINDOWS = SYSTEM == "Windows"
# Deliberately "everything that is not Windows", exactly like the old
# core/plugins.py did. Plugin manifests only know is_linux / is_windows,
# so a BSD or macOS run has to land in one of the two buckets - and the
# POSIX code paths are the ones that have a chance of working there.
IS_LINUX = not IS_WINDOWS
IS_MACOS = SYSTEM == "Darwin"       # informational only (implies IS_LINUX)
OS_NAME = "Windows" if IS_WINDOWS else "Linux"

# True inside a PyInstaller build (.exe / one-dir bundle)
IS_FROZEN = bool(getattr(sys, "frozen", False))

# folder name used for the user's config on every platform
APP_DIRNAME = "OSC-DreamChatbox"
# the pre-v1.1 folder, kept for the settings.json migration
LEGACY_APP_DIRNAME = "osc-dreamchatbox"


# ----------------------------------------------------------- resources
def resource_root() -> Path:
    """Folder that contains assets/, config/, core/, ui/ ... - i.e. the
    read-only files shipped with the app.

    * from source: the project root (parent of core/)
    * frozen:      sys._MEIPASS (one-file: the temp unpack dir,
                   one-dir: the _internal folder)
    """
    if IS_FROZEN:
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource(*parts) -> Path:
    """resource('assets', 'icon.png') -> absolute path inside the app."""
    return resource_root().joinpath(*parts)


# -------------------------------------------------------------- config
def config_base() -> Path:
    """Parent folder the app's config folder is created in.

    Linux keeps the literal ~/.config it has always used - XDG_CONFIG_HOME
    is NOT honoured on purpose, otherwise an existing install would look
    at a different folder after this change.
    """
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata)
        return Path.home() / "AppData" / "Roaming"
    return Path.home() / ".config"


def config_dir() -> Path:
    """Where the user's config, plugins, extras and caches live."""
    return config_base() / APP_DIRNAME


def legacy_config_dir() -> Path:
    """Pre-v1.1 folder (lowercase), source of the settings.json import."""
    return config_base() / LEGACY_APP_DIRNAME


def _unix_style_config_dir() -> Path:
    """~/.config/OSC-DreamChatbox even on Windows - what a source
    checkout wrote there before this release existed."""
    return Path.home() / ".config" / APP_DIRNAME


def migrate_config_dir(log=None) -> tuple[bool, str]:
    """Windows only: copy an existing ~/.config/OSC-DreamChatbox over to
    %APPDATA%\\OSC-DreamChatbox once.

    Only runs when the new folder does not exist yet, and it COPIES
    instead of moving, so a half-finished migration can never destroy
    the only copy of someone's settings. Never raises.

    Returns (migrated, message).
    """
    if not IS_WINDOWS:
        return False, ""
    target = config_dir()
    source = _unix_style_config_dir()
    try:
        if target.exists() or not source.is_dir() or source == target:
            return False, ""
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True)
    except Exception as e:                       # noqa: BLE001
        msg = f"Config migration failed ({type(e).__name__}: {e})"
        if callable(log):
            log(msg)
        return False, msg
    msg = f"Config migrated: {source} -> {target} (the old folder was kept)"
    if callable(log):
        log(msg)
    return True, msg


# ------------------------------------------------------------- helpers
def describe() -> str:
    """One line for the debug console / bug reports."""
    return (f"{OS_NAME} ({SYSTEM} {platform.release()}), "
            f"python {platform.python_version()}, "
            f"{'frozen' if IS_FROZEN else 'source'}")
