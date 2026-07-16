"""
core/constants.py – shared constants & paths for OSC-DreamChatbox
"""

from pathlib import Path

APP_NAME = "OSC-DreamChatbox"
VERSION = "v1.0.7-alpha"
GITHUB_REPO = "yakuda-stack/OSC-DreamChatbox"
DISCORD_URL = "https://discord.gg/X5TaN4A47h"
DONATE_URL = "https://paypal.me/riesensika"

# ---------------------------------------------------------------- paths
# project root = folder that contains osc_dreamchatbox.py / core / ui
PROJECT_DIR = Path(__file__).resolve().parent.parent

CONFIG_DIR = Path.home() / ".config" / "OSC-DreamChatbox"
CONFIG_FILE = CONFIG_DIR / "config.json"
OLD_CONFIG_FILE = Path.home() / ".config" / "osc-dreamchatbox" / "settings.json"

# ------------------------------------------------------------- chatbox
# The "magic" suffix: turns the VRChat chatbox into a slim bar.
# (Same trick as the hidden BlankEgg/BoiHanny feature in MagicChatbox)
SLIM_SUFFIX = "\u0003\u001f"
CHATBOX_INPUT = "/chatbox/input"
CHATBOX_LIMIT = 144  # VRChat chatbox character limit

TITLE_MAX_LEN = 24   # max characters of the song title shown
SONGBAR_LEN = 13     # number of segments in the song progress bar
