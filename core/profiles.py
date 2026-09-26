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

Plugins travel with a profile in two places:

  - ``plugin_<id>: true/false`` at the END of the profile file says which
    plugins this setup uses. Loading a profile switches them on/off, and
    a plugin that is missing but in the store can be installed from it.
    A profile without any ``plugin_`` key (older ones) leaves plugins
    exactly as they are.
  - ``profiles/plugins/<name>.json`` holds each plugin's settings for
    this profile (options, custom string, own line, position, block
    order). One small extra file instead of everything in the profile,
    so a converter or a human can read the setup part on its own.
    The "may write to the chatbox" answer stays per machine.

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

#: the profile a fresh install starts with (and anyone without one)
DEFAULT_NAME = "Default"

#: Options -> Profiles: store the live settings into the active profile
#: when the app closes. On by default.
SAVE_ON_EXIT_KEY = "profile_save_on_exit"

#: what an exported profile file says it is
EXPORT_FORMAT = "osc-dreamchatbox-profile"
EXPORT_VERSION = 1
EXPORT_SUFFIX = ".dcbprofile.json"

#: {profile name: [plugin ids]} - plugins we already asked about
#: ("save this plugin into your profile?"), so each one is asked once
ASKED_KEY = "profile_plugins_asked"

#: settings that belong to the app/machine, not to a setup
APP_WIDE_KEYS = frozenset((
    ACTIVE_KEY, ASKED_KEY, SAVE_ON_EXIT_KEY,
    # where VRChat is and how we talk to it
    "osc_ip", "osc_port", "oscquery_enabled", "send_to_vrchat",
    "osc_input_enabled", "osc_input_port", "hotkey_input_enabled",
    "osc_ext_ip", "osc_ext_port", "osc_instant_send", "interval_sec",
    # how the window looks
    "theme", "theme_colors", "theme_background", "theme_opacity",
    "debug",
))

#: profile keys that say which plugins the setup uses: plugin_<id>
PLUGIN_KEY_PREFIX = "plugin_"

#: sub folder with one plugin-settings file per profile
PLUGINS_SUBDIR = "plugins"

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


def _is_plugin_key(key):
    return isinstance(key, str) and key.startswith(PLUGIN_KEY_PREFIX)


def profile_part(cfg):
    """The part of a config that a profile carries. plugin_<id> keys are
    not config - save_profile() writes them fresh every time."""
    return {k: v for k, v in cfg.items()
            if k not in APP_WIDE_KEYS and not _is_plugin_key(k)}


def plugins_to_ask(stored, installed, asked):
    """Installed plugin ids that profile `stored` does not list yet and
    that were not asked about before - sorted, so one popup lists them
    in a stable order."""
    known = set(plugin_flags(stored))
    done = set(asked or ())
    return sorted(p for p in installed if p not in known and p not in done)


def add_plugins(name, flags, settings, folder=None):
    """Adds plugins to a stored profile WITHOUT touching its other
    settings - for a profile that is not the live one (no profile active,
    the user picks where the plugins go). Existing plugin_ keys stay."""
    stored = read_profile(name, folder)
    merged = plugin_flags(stored)
    merged.update({str(k).lower(): bool(v) for k, v in (flags or {}).items()})
    save_profile(name, stored, folder, plugins=merged)
    data = read_plugin_settings(name, folder)
    data.update({str(k).lower(): v for k, v in (settings or {}).items()
                 if isinstance(v, dict)})
    save_plugin_settings(name, data, folder)


def plugins_in_no_profile(installed, folder=None, asked=()):
    """Installed plugin ids that NO profile lists and that were not asked
    about before - used while no profile is active."""
    known = set()
    for name in list_profiles(folder):
        try:
            known |= set(plugin_flags(read_profile(name, folder)))
        except (OSError, ValueError):
            continue
    done = set(asked or ())
    return sorted(p for p in installed if p not in known and p not in done)


def plugin_flags(stored):
    """{plugin id: on/off} from a stored profile. Empty for a profile
    that predates the plugin_ keys - the caller then leaves plugins
    alone."""
    flags = {}
    for key, value in (stored or {}).items():
        if _is_plugin_key(key) and isinstance(value, bool):
            pid = key[len(PLUGIN_KEY_PREFIX):].strip().lower()
            if pid:
                flags[pid] = value
    return flags


def save_profile(name, cfg, folder=None, plugins=None):
    """Writes the setup part of `cfg` as profile `name`. Returns the name
    it was stored under. Raises ValueError for an unusable name.

    `plugins` ({id: on/off}) goes to the end of the file as
    ``plugin_<id>: true/false``, sorted, so it reads like a list."""
    name = clean_name(name)
    if not name:
        raise ValueError("empty profile name")
    folder = Path(folder or PROFILES_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    data = profile_part(cfg)
    for pid in sorted(plugins or {}):
        data[PLUGIN_KEY_PREFIX + pid] = bool(plugins[pid])
    write_text_atomic(_path(name, folder), json.dumps(data, indent=2))
    return name


def _plugins_path(name, folder=None):
    return (Path(folder or PROFILES_DIR) / PLUGINS_SUBDIR
            / f"{clean_name(name)}.json")


def save_plugin_settings(name, settings, folder=None):
    """Writes {plugin id: settings} for profile `name`."""
    path = _plugins_path(name, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(settings or {}, indent=2,
                                       ensure_ascii=False))


def read_plugin_settings(name, folder=None):
    """{plugin id: settings} of profile `name`, {} when there is no file
    or it is broken - plugin settings must never block a profile."""
    try:
        data = json.loads(_plugins_path(name, folder).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): v for k, v in data.items()
            if isinstance(v, dict)}


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
    merged = profile_part(stored)      # without the plugin_ keys
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
    for path in (_path(clean_name(name), folder),
                 _plugins_path(name, folder)):
        try:
            path.unlink()
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
    psrc, pdst = _plugins_path(old, folder), _plugins_path(new, folder)
    if psrc.is_file() and psrc != pdst:
        psrc.rename(pdst)
    return new


# ------------------------------------------------------ import / export
def export_profile(name, path, folder=None):
    """Writes profile `name` plus its plugin settings into ONE file:

        {"format": "osc-dreamchatbox-profile", "version": 1,
         "name": "Gaming", "profile": {...}, "plugins": {...}}

    "profile" is the profile file as it is (plugin_<id> keys included),
    "plugins" the profiles/plugins/<name>.json part."""
    name = clean_name(name)
    data = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "name": name,
        "profile": read_profile(name, folder),
        "plugins": read_plugin_settings(name, folder),
    }
    write_text_atomic(Path(path), json.dumps(data, indent=2,
                                             ensure_ascii=False))


def read_export(path):
    """(name, profile, plugins) from an exported file. A plain profile
    .json (just the settings, e.g. copied out of the profiles folder)
    works too - its name is the file name. Raises ValueError for
    anything that is not a profile."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not a profile file")
    stem = path.name
    for suffix in (EXPORT_SUFFIX, ".json"):
        if stem.lower().endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    if data.get("format") == EXPORT_FORMAT:
        profile = data.get("profile")
        plugins = data.get("plugins")
        if not isinstance(profile, dict):
            raise ValueError("the file has no profile in it")
        if not isinstance(plugins, dict):
            plugins = {}
        name = clean_name(data.get("name")) or clean_name(stem)
        return name, profile, plugins
    if "format" in data:
        raise ValueError(f"unknown file format \u201c{data['format']}\u201d")
    return clean_name(stem), data, {}


def import_profile(name, profile, plugins, folder=None):
    """Stores an imported profile under `name`. App-wide keys in it (OSC
    port, theme, ...) are dropped - an import never moves where VRChat
    is. Returns the stored name."""
    name = save_profile(name, profile, folder, plugins=plugin_flags(profile))
    save_plugin_settings(name, {str(k).lower(): v
                                for k, v in (plugins or {}).items()
                                if isinstance(v, dict)}, folder)
    return name
