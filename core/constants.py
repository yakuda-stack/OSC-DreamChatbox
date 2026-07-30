"""
core/constants.py – shared constants & paths for OSC-DreamChatbox
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

APP_NAME = "OSC-DreamChatbox"
VERSION = "v1.2.1"
GITHUB_REPO = "yakuda-stack/OSC-DreamChatbox"
DISCORD_URL = "https://discord.gg/X5TaN4A47h"
DONATE_URL = "https://ko-fi.com/yakuda_"
VRCHAT_GROUP_URL = ("https://vrchat.com/home/group/"
                    "grp_829b7777-430d-48b2-8bf3-4e348d0dac9b")
# ready-made plugins + the template to start your own (see core/plugins.py)
PLUGINS_REPO_URL = "https://github.com/yakuda-stack/Dream-Chatbox-Plugins"

# ---------------------------------------------------------------- paths
# project root = folder that contains osc_dreamchatbox.py / core / ui
PROJECT_DIR = Path(__file__).resolve().parent.parent

CONFIG_DIR = Path.home() / ".config" / "OSC-DreamChatbox"
CONFIG_FILE = CONFIG_DIR / "config.json"
OLD_CONFIG_FILE = Path.home() / ".config" / "osc-dreamchatbox" / "settings.json"

# default folder for the user's own .lrc files (local lyrics)
LYRICS_DIR = CONFIG_DIR / "lyrics"

# ------------------------------------------------------------- plugins
# one subfolder per plugin (plugin.json + main.py), see core/plugins.py.
# Its state lives with it in plugins/<id>/configs/config.json, which also
# doubles as the plugin's own writable folder (api.data_dir).
PLUGINS_DIR = CONFIG_DIR / "plugins"
# store catalogue: a list of GitHub links, shipped with the app so it can be
# extended with a pull request. APP_ROOT is where osc_dreamchatbox.py lives.
APP_ROOT = Path(__file__).resolve().parent.parent
STORE_SOURCES_FILE = APP_ROOT / "config" / "plugins.json"

# ------------------------------------------------------------- chatbox
# The "magic" suffix: turns the VRChat chatbox into a slim bar.
# (Same trick as the hidden BlankEgg/BoiHanny feature in MagicChatbox)
SLIM_SUFFIX = "\u0003\u001f"
CHATBOX_INPUT = "/chatbox/input"
CHATBOX_LIMIT = 144  # VRChat chatbox character limit

TITLE_MAX_LEN = 24   # max characters of the song title shown
SONGBAR_LEN = 13     # number of segments in the song progress bar
