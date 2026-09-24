"""
core/profiles.py - named setups ("profiles") of the whole config

A profile is a copy of config.json under config/profiles/<name>.json.
Switching one in is: store the live settings into the profile that is
active right now, then load the other one. So a profile behaves like a
setup you are IN, not like a snapshot you have to remember to update -
whatever you change while "Japanese night" is active belongs to
"Japanese night" the next time you switch back.

A few keys are app-wide and never travel with a profile (APP_WIDE_KEYS):
where VRChat is, the look of the window, the debug console. Switching
from "Gaming" to "Translation" should not move the OSC port or recolour
the app.

Plugins keep their own state files (on/off, position, settings) and
are not part of a profile.

No Qt in here, so it can be tested on its own.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import re
from pathlib import Path

from core.atomicfile import write_text_atomic
from core.constants import CONFIG_DIR

PROFILES_DIR = CONFIG_DIR / "profiles"

#: the config key that remembers which profile is active ("" = none)
ACTIVE_KEY = "profile_active"

#: settings that belong to the app/machine, not to a setup
APP_WIDE_KEYS = frozenset((
    ACTIVE_KEY,
    # where VRChat is and how we talk to it
    "osc_ip", "osc_port", "oscquery_enabled", "send_to_vrchat",
    "osc_input_enabled", "osc_input_port", "hotkey_input_enabled",
    "osc_ext_ip", "osc_ext_port", "osc_instant_send", "interval_sec",
    # how the window looks
    "theme", "theme_colors", "theme_background", "theme_opacity",
    "debug",
))

#: longest name we accept - it ends up as a file name and in a dropdown
NAME_MAX = 40

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def clean_name(name):
    """The name as it will be stored, or "" when nothing usable is left.
    File-system characters are dropped rather than refused, so "Gaming /
    Music" simply becomes "Gaming  Music"."""
    name = _BAD_CHARS.sub("", str(name or "")).strip().strip(".")
    return name[:NAME_MAX].strip()


def _path(name, folder=None):
    return Path(folder or PROFILES_DIR) / f"{name}.json"


def list_profiles(folder=None):
    """Names of all saved profiles, sorted case-insensitively."""
    folder = Path(folder or PROFILES_DIR)
    if not folder.is_dir():
        return []
    return sorted((p.stem for p in folder.glob("*.json") if p.is_file()),
                  key=str.lower)


def exists(name, folder=None):
    name = clean_name(name)
    return bool(name) and _path(name, folder).is_file()


def profile_part(cfg):
    """The part of a config that a profile carries."""
    return {k: v for k, v in cfg.items() if k not in APP_WIDE_KEYS}


def save_profile(name, cfg, folder=None):
    """Writes the setup part of `cfg` as profile `name`. Returns the name
    it was stored under. Raises ValueError for an unusable name."""
    name = clean_name(name)
    if not name:
        raise ValueError("empty profile name")
    folder = Path(folder or PROFILES_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    write_text_atomic(_path(name, folder),
                      json.dumps(profile_part(cfg), indent=2))
    return name


def read_profile(name, folder=None):
    """The stored dict of profile `name`. Raises OSError / ValueError when
    it is missing or not a JSON object - the caller decides what to say."""
    data = json.loads(_path(clean_name(name), folder).read_text(
        encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("profile file is not a JSON object")
    return data


def merge_for_load(current_cfg, stored):
    """The raw config to load for a profile: everything from the profile,
    the app-wide keys from what is running now. The result still has to go
    through the normal config normalisation (ConfigMixin.load_config)."""
    merged = profile_part(stored)
    for key in APP_WIDE_KEYS:
        if key in current_cfg:
            merged[key] = current_cfg[key]
    return merged


def find_profile(name, folder=None):
    """The stored name of profile `name`, ignoring upper/lower case, so
    ``--profile=gaming`` finds "Gaming". "" when there is no such profile."""
    wanted = clean_name(name).lower()
    if not wanted:
        return ""
    for stored in list_profiles(folder):
        if stored.lower() == wanted:
            return stored
    return ""


#: command line option that starts the app with a profile
CLI_FLAG = "--profile"


def profile_from_argv(argv):
    """The profile asked for on the command line, or None when there is
    no --profile at all. Both spellings work:

        --profile="my profile"      --profile "my profile"

    A --profile without a name gives "" (the caller reports that)."""
    argv = list(argv)
    for i, arg in enumerate(argv):
        if arg.startswith(CLI_FLAG + "="):
            return arg.split("=", 1)[1].strip()
        if arg == CLI_FLAG:
            nxt = argv[i + 1] if i + 1 < len(argv) else ""
            return "" if nxt.startswith("--") else nxt.strip()
    return None


def delete_profile(name, folder=None):
    """Removes profile `name`. Missing is not an error."""
    try:
        _path(clean_name(name), folder).unlink()
    except FileNotFoundError:
        pass


def rename_profile(old, new, folder=None):
    """Renames a profile file. Returns the new (cleaned) name. Raises
    ValueError for an empty name or when `new` already exists."""
    new = clean_name(new)
    if not new:
        raise ValueError("empty profile name")
    src, dst = _path(clean_name(old), folder), _path(new, folder)
    if src == dst:
        return new
    if dst.exists() and dst.name.lower() != src.name.lower():
        raise ValueError(f"a profile called “{new}” already exists")
    src.rename(dst)
    return new
