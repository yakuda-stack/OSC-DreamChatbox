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
VERSION = "v1.4.4"

#: how many All-in-one strings there can be. Raised from 5 in v1.4.0;
#: every list that is "one entry per AIO string" is sized from here.
AIO_MAX = 10
GITHUB_REPO = "yakuda-stack/OSC-DreamChatbox"
DISCORD_URL = "https://discord.gg/X5TaN4A47h"
DONATE_URL = "https://ko-fi.com/yakuda_"
VRCHAT_GROUP_URL = ("https://vrchat.com/home/group/"
                    "grp_829b7777-430d-48b2-8bf3-4e348d0dac9b")
# ready-made plugins + the template to start your own (see core/plugins.py)
PLUGINS_REPO_URL = "https://github.com/yakuda-stack/Dream-Chatbox-Plugins"
# the example plugin: every setting type next to every hook, all of it
# live. One constant instead of the URL sitting in four tooltips, because
# a link that moved is only worth fixing once.
PLUGIN_TEMPLATE_URL = (PLUGINS_REPO_URL
                       + "/tree/main/template/example_template")

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



# ------------------------------------------------------- OSC rate limit
# VRChat throttles the chatbox: roughly 5 messages inside a 5 second
# window, and going over that earns a ~30 second cooldown in which
# NOTHING is shown at all. Both numbers are enforced in
# ui/mainwindow.py (_osc_send_delay) as a rolling window, so an
# instant send after a text change can never spend the whole budget.
OSC_RATE_WINDOW_SEC = 5.0
OSC_RATE_MAX_SENDS = 5
# on top of the window: never fire two sends back to back. 1.5 s is the
# interval VRChat itself uses for chatbox updates, so it is the safe
# floor everybody else (VRCOSC etc.) settled on as well.
OSC_MIN_SEND_GAP_SEC = 1.5

TITLE_MAX_LEN = 24   # max characters of the song title shown
SONGBAR_LEN = 13     # number of segments in the song progress bar

# ---------------------------------------------------------- chat routing
# How a typed / spoken message reaches the chatbox. See
# ui/pages/textbox_page.py (the UI) and ui/mainwindow.py (build_payload).
#
#   direct  the message IS the chatbox for a few seconds - it goes out on
#           its own and every app is paused meanwhile. The original
#           behaviour, and still the default.
#   line    the message becomes one more line of the normal payload, at a
#           position you pick the same way a plugin picks one. Apps keep
#           running around it.
#   vars    the message produces no line of its own at all; it only fills
#           {text_input} / {text_output}, so an All-in-one template
#           decides where - and whether - it shows up.
CHAT_MODE_DIRECT = "direct"
CHAT_MODE_LINE = "line"
CHAT_MODE_VARS = "vars"
CHAT_MODES = (CHAT_MODE_DIRECT, CHAT_MODE_LINE, CHAT_MODE_VARS)

# Where a message came from. The send mode is one setting for all three,
# but the placeholders are not: {stt_output} fills only for something
# spoken, {ttt_output} only for something typed into the Text to Text
# field, {chat_output} only for the Chat card - while {text_output}
# answers for whichever of them sent last. That is what lets one
# All-in-one string treat a spoken sentence differently from a typed one.
#: shown in the chatbox while a translation is still being fetched
DEFAULT_TRANSLATE_NOTICE = "Translate \u2026"

ORIGIN_CHAT = "chat"
ORIGIN_STT = "stt"
ORIGIN_TTT = "ttt"
ORIGINS = (ORIGIN_CHAT, ORIGIN_STT, ORIGIN_TTT)
ORIGIN_LABELS = {ORIGIN_CHAT: "Chat", ORIGIN_STT: "Speech to Text",
                 ORIGIN_TTT: "Text to Text"}
