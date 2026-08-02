"""
core/constants.py – shared constants & paths for OSC-DreamChatbox

Every path that differs per platform is resolved in core/osinfo.py; this
module only names things. On Linux the values are byte-for-byte what they
have always been.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path  # noqa: F401  (kept: tools import Path from here)

from core.osinfo import (  # noqa: F401  (IS_WINDOWS/OS_NAME re-exported)
    IS_WINDOWS, OS_NAME, config_dir, legacy_config_dir, resource_root)

APP_NAME = "OSC-DreamChatbox"
VERSION = "v1.3.0"
GITHUB_REPO = "yakuda-stack/OSC-DreamChatbox"
DISCORD_URL = "https://discord.gg/X5TaN4A47h"
DONATE_URL = "https://ko-fi.com/yakuda_"
VRCHAT_GROUP_URL = ("https://vrchat.com/home/group/"
                    "grp_829b7777-430d-48b2-8bf3-4e348d0dac9b")
# ready-made plugins + the template to start your own (see core/plugins.py)
PLUGINS_REPO_URL = "https://github.com/yakuda-stack/Dream-Chatbox-Plugins"

# ---------------------------------------------------------------- paths
# project root = folder that contains osc_dreamchatbox.py / core / ui.
# Inside a PyInstaller build this is the unpacked bundle instead, so
# assets/ and config/ keep resolving the same way.
PROJECT_DIR = resource_root()

# Linux:   ~/.config/OSC-DreamChatbox      (unchanged)
# Windows: %APPDATA%\OSC-DreamChatbox
CONFIG_DIR = config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
OLD_CONFIG_FILE = legacy_config_dir() / "settings.json"

# default folder for the user's own .lrc files (local lyrics)
LYRICS_DIR = CONFIG_DIR / "lyrics"

# ------------------------------------------------------------- plugins
# one subfolder per plugin (plugin.json + main.py), see core/plugins.py.
# Its state lives with it in plugins/<id>/configs/config.json, which also
# doubles as the plugin's own writable folder (api.data_dir).
# optional pure-python extras the app installs for itself with pip when the
# distribution's own package is unusable (see core/pyextras.py)
EXTRAS_DIR = CONFIG_DIR / "extras"
PLUGINS_DIR = CONFIG_DIR / "plugins"
# store catalogue: a list of GitHub links, shipped with the app so it can be
# extended with a pull request. APP_ROOT is where osc_dreamchatbox.py lives.
APP_ROOT = PROJECT_DIR
STORE_SOURCES_FILE = APP_ROOT / "config" / "plugins.json"

# ------------------------------------------------------------- chatbox
# The "magic" suffix: turns the VRChat chatbox into a slim bar.
# (Same trick as the hidden BlankEgg/BoiHanny feature in MagicChatbox)
SLIM_SUFFIX = "\u0003\u001f"
CHATBOX_INPUT = "/chatbox/input"
# a status text below this is unreadable in VRChat and burns a send each
# time it flips, so the UI and the config validator both enforce it
MIN_STATUS_CYCLE_SEC = 10
CHATBOX_LIMIT = 144  # VRChat chatbox character limit

TITLE_MAX_LEN = 24   # max characters of the song title shown
SONGBAR_LEN = 13     # number of segments in the song progress bar
