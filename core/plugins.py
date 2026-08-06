"""
core/plugins.py – plugin discovery, activation and dispatch.

Plugins live in ``CONFIG_DIR/plugins/<plugin_id>/`` and consist of at
least a ``plugin.json`` manifest and the python file it points to::

    ~/.config/OSC-DreamChatbox/plugins/
        example_template/
            plugin.json
            main.py

Every hook is optional; a plugin only implements what it needs:

    def setup(api):          called right after the module was imported
    def teardown():          called when the plugin is disabled / on exit
    def get_text():          -> str, the plugin's main output -> {<id>}
    def get_lines():         -> list[str], appended to the chatbox payload
    def get_values():        -> dict, extra {<id>_<key>} placeholders
    def on_settings(opts):   called when the user changed a setting
    def on_text(text):       -> str, last-chance filter for the final text
    def on_tick():           once per chatbox frame, before the values are
                             collected – for a plugin that has to poll
    def on_event(name, data) anything the app announces; see "Events"
    def build_widget(parent) -> QWidget, the plugin's own UI, embedded
                             under its settings on the Plugins page

Hooks are looked up by name, never required and never awaited: a plugin
written for a newer app may implement hooks this build has never heard
of, and an older plugin simply misses the new ones. Neither is an error.

Forward compatibility
---------------------
The whole point of the rules below is that a plugin and the app are
updated by different people at different times, and neither direction
may end in a traceback or in silently lost settings:

    "api": 3            a manifest may state which plugin API it needs.
                        A plugin asking for more than PLUGIN_API_VERSION
                        is listed, greyed out and NOT imported, with the
                        reason in its tooltip – instead of failing
                        halfway through setup() with an AttributeError.

    api.supports(...)   runtime feature detection, so one plugin release
                        can serve several app versions:
                        `if api.supports("api.set"): api.set(...)`

    unknown settings    a "settings" entry of a type this build does not
                        know is kept, not dropped: its default is stored
                        like any other value, the plugin reads it through
                        api.get() as usual, and the UI shows a disabled
                        row saying which app version it needs. An option
                        the user cannot see is still an option the plugin
                        can rely on.

    unknown keys        anything else the app does not understand – extra
                        manifest fields, extra keys on a settings row,
                        extra keys in config.json – is carried along
                        untouched (Plugin.extra, item["extra"],
                        entry["extra"]) instead of being thrown away on
                        the next write.

Events
------
    manager.emit("avatar.changed", {"id": "avtr_..."})

reaches every active plugin as ``on_event("avatar.changed", {...})``.
This is the extension point for everything that does not exist yet: a
new kind of notification needs no change in here and no change in any
plugin that does not care about it. Names are dotted and lower case;
a plugin must ignore what it does not recognise.

Placeholders: every plugin is addressable as ``{<plugin_id>}`` (its
get_text(), falling back to its get_lines()), and every key of
get_values() as ``{<plugin_id>_<key>}``. That works in the plugin's own
custom string, in the Apps custom strings, in All-in-one and in the
Personal Status texts.

Beyond the required keys, plugin.json may declare:

    "is_linux":     false to mark the plugin as Linux-incompatible
    "is_windows":   false to mark it as Windows-incompatible
                    Both default to true: most plugins are plain python and
                    run anywhere, so only a plugin that really touches
                    pactl, /sys, WMI or similar has to say so.
    "template":     default custom string, e.g. "\u2728 {example_template}"
    "placeholders": {"mood": "what it means"}   – shown as a UI hint
    "global_placeholders": ["realtime"]  – claim these names WITHOUT the
                            id prefix, so {realtime} works everywhere. An
                            app value that is already filled always wins,
                            so a plugin can never hijack a built-in one.
    "settings":     [{"key": "greeting", "type": "text",
                      "label": "Greeting", "default": "Hi"},
                     {"key": "len", "type": "slider", "label": "Length",
                      "default": 24, "min": 6, "max": 64,
                      "suffix": " chars", "depends": "shout"}]

``settings`` entries (type text | bool | int | slider | choice | path
| emoji | label | action | group)
are rendered as real widgets under the plugin's Settings expander, so an
author gets a config UI without writing a single line of Qt. The current
values reach the plugin as ``api.settings`` (a live dict) plus the
on_settings hook.

Three of those types need a word beyond their name:

    {"key": "mode", "type": "choice", "label": "Data source",
     "default": "keyless",
     "choices": [{"value": "keyless", "label": "Keyless"},
                 {"value": "api", "label": "Official API"}]}

        A dropdown. The stored value is always one of the "value"
        strings; a plain list of strings works too, then value == label.

    {"key": "binary", "type": "path", "label": "OSCLeash path",
     "mode": "file", "placeholder": "auto",
     "filters": ["OSCLeash (OSCLeash* *.AppImage *.exe)"]}

        A text row with a file picker next to it. "mode" is "file" or
        "dir", "filters" are Qt name filters and only apply to files.
        The value is stored exactly as typed or picked and is never
        resolved or checked here: a plugin may want a path that does not
        exist yet, and a config carried to another machine must not be
        silently "corrected".

    {"key": "reset", "type": "action", "label": "Cached data",
     "button": "Clear now", "style": "danger"}

        A button. It holds no value and never reaches config.json - the
        key only tells the plugin which button was pressed, through
        ``on_action(key)``. "style" is normal | primary | danger, and a
        string returned by the hook is shown next to the button.

    {"key": "status", "type": "label", "label": "State", "default": "idle"}

        A read-only line. The text is an option value like any other, so
        ``api.set("status", "connected")`` turns it into a live status
        line - no widget needed for the common case of "the plugin wants
        to say one thing".

    {"key": "icon", "type": "emoji", "label": "Icon", "default": "\U0001F415"}

        A text row with the app's own icon picker next to it - the same
        popup the Personal Status and Hardware custom strings use, so a
        plugin icon is chosen the way every other icon in the app is. It
        stays a text field: an icon is often two characters (emoji plus
        variation selector), and a trailing space is sometimes the point.

    {"key": "twitch", "type": "group", "label": "Twitch",
     "expanded": false, "items": [ ...more settings... ]}

        A collapsible block. A group holds no value of its own, it only
        groups the settings in its "items" list - which may contain
        every type including one more level of groups. Like the Settings
        expander itself, a group starts collapsed unless the manifest
        says "expanded": true; the open/closed state is a view detail and
        is deliberately not persisted.

``depends`` hides a row while another setting is switched off. With
``depends_value`` it can follow a choice instead of a bool::

    {"key": "api_key", "type": "text", "label": "API key",
     "secret": true, "depends": "mode", "depends_value": "api"}

``depends_value`` accepts a single value or a list of them; without it
the parent is simply tested for truthiness, which is what every existing
plugin relies on. ``"secret": true`` on a text row masks the input, for
tokens and API keys.

``api`` is a PluginAPI instance (log, paths, host window). Every call
into plugin code goes through _safe_call(), so a broken plugin can log
a traceback but can never take the chatbox down with it.

Everything the user changed about a plugin – the on/off toggle, the
custom string and the values of its own settings – is stored next to the
plugin itself::

    plugins/<id>/configs/config.json

One file per plugin, so a plugin carries its own state: copy the folder
and the settings come along, delete it and nothing is left behind. The
``configs/`` folder is preserved when a plugin is re-installed from a
newer .zip, so an update never resets what the user configured. The
``"enabled"`` key inside plugin.json is only the initial default for a
fresh install; after that the config file decides.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import traceback
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from core.constants import APP_NAME, PLUGINS_DIR, VERSION
# re-exported below so plugins and core/plugin_store.py can keep
# doing `from core.plugins import IS_WINDOWS, OS_NAME`
from core.osinfo import IS_LINUX, IS_WINDOWS, OS_NAME  # noqa: F401
from core.textutils import apply_template

MANIFEST_NAME = "plugin.json"

# --------------------------------------------------------------------
# plugin API version
# --------------------------------------------------------------------
# Bumped whenever plugins gain something they may rely on. A manifest can
# declare the minimum it needs as "api": <n>; anything higher than this
# number is refused with a readable reason instead of being imported and
# blowing up on the first missing attribute.
#
#   1  the original contract: setup/teardown/get_*/on_settings/on_text,
#      settings of type text | bool | int | slider
#   2  choice + group settings, secret, depends_value, build_widget(),
#      on_tick(), on_event(), api.set()/api.refresh()/api.supports(),
#      and unknown settings/keys surviving instead of being dropped
PLUGIN_API_VERSION = 2

# What THIS build can actually do, for api.supports("..."). Feature
# strings are additive and never removed - a plugin testing for one that
# was retired simply gets False and takes its fallback path.
CAPABILITIES = frozenset({
    "settings.text", "settings.bool", "settings.int", "settings.slider",
    "settings.choice", "settings.group", "settings.secret",
    "settings.path", "settings.emoji", "settings.action", "settings.label",
    "settings.depends", "settings.depends_value",
    "settings.unsupported_passthrough",
    "widget",              # build_widget() is embedded in the plugin card
    "events",              # on_event(name, data)
    "tick",                # on_tick() once per chatbox frame
    "api.set",             # writing a setting back from the plugin
    "api.refresh",         # asking for a fresh chatbox render
    "api.data_dir",        # a writable folder that survives updates
    "manifest.extra",      # unknown manifest keys reach Plugin.extra
})

# Every hook the app knows. Only used for introspection (the info popup,
# api.supports("hook.<name>")): dispatch itself is by name, so a plugin
# may carry hooks from a newer app without anything here complaining.
HOOKS = ("setup", "teardown", "get_text", "get_lines", "get_values",
         "on_settings", "on_text", "on_tick", "on_event", "on_action",
         "build_widget")

# per-plugin state lives in <plugin>/configs/config.json
CONFIG_DIRNAME = "configs"
# where a plugin's lines land relative to the standard apps. The value is
# the app key it sits ABOVE; "aio" means "below everything else", because
# All in one is always the last block.
ANCHORS = ("status", "media", "hardware", "aio")
ANCHOR_LABELS = (("status", "Above Personal Status"),
                 ("media", "Above Media Player"),
                 ("hardware", "Above Hardware"),
                 ("aio", "Above All in one"))
DEFAULT_ANCHOR = "aio"
CONFIG_NAME = "config.json"
# types that carry a value the user can change
LEAF_SETTING_TYPES = ("text", "bool", "int", "slider", "choice", "path",
                      "emoji", "label")
# a button is not a value: it has a key so the plugin knows which one was
# pressed, but nothing about it is ever stored
ACTION_TYPE = "action"
# purely structural: a collapsible block around other settings
GROUP_TYPE = "group"
SETTING_TYPES = LEAF_SETTING_TYPES + (GROUP_TYPE, ACTION_TYPE)
# not a type an author writes: what a row of an unknown type BECOMES, so
# its value still exists for the plugin and the UI can say why the row is
# greyed out. See _parse_schema().
UNSUPPORTED_TYPE = "unsupported"
# keys the schema parser consumes itself – everything else on a settings
# row is handed through in item["extra"] for a future UI to pick up
KNOWN_ITEM_KEYS = frozenset({
    "key", "type", "label", "hint", "depends", "depends_value", "default",
    "min", "max", "suffix", "secret", "choices", "options", "items",
    "expanded", "mode", "filters", "placeholder", "button", "style"})
# same idea for the manifest and for config.json
KNOWN_MANIFEST_KEYS = frozenset({
    "id", "name", "version", "author", "description", "summary", "Github",
    "github", "main", "image", "enabled", "is_linux", "is_windows",
    "template", "placeholders", "global_placeholders", "settings", "api",
    "min_app"})
KNOWN_CONFIG_KEYS = frozenset({
    "enabled", "anchor", "order", "line", "custom", "template", "options"})
# how deep groups may nest. Two levels are plenty for a settings block
# and the limit keeps a hand-written (or generated) manifest from
# recursing the parser into the ground.
MAX_GROUP_DEPTH = 2
# plugin ids are used as folder AND module names -> keep them boring
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MODULE_PREFIX = "dreamchatbox_plugin_"
# what we are running on right now - decided per start in
# core/osinfo.py, never stored: a config carried to another machine
# would otherwise pick the wrong branch. IS_WINDOWS / IS_LINUX /
# OS_NAME are imported above and stay importable from here, so
# every existing plugin and every plugin.json keeps working.
# zip bomb / typo protection (uncompressed size of the whole archive)
MAX_UNPACKED_BYTES = 64 * 1024 * 1024


def iter_settings(schema):
    """Yields every setting that holds a VALUE, walking into groups.

    Groups are containers, so everything that deals with option values -
    filling in defaults, reading them back - iterates with this instead
    of looping over the schema directly. A schema without groups walks
    exactly like the flat list it always was.
    """
    for item in schema or []:
        kind = item.get("type")
        if kind == GROUP_TYPE:
            yield from iter_settings(item.get("items"))
        elif kind != ACTION_TYPE:
            # a button has a key but no value - it must not end up in
            # config.json, and api.get() has nothing to return for it
            yield item


# --------------------------------------------------------------------
# filesystem helpers
# --------------------------------------------------------------------
# Windows fails at deleting and moving folders in two ways POSIX never
# does, and both hit exactly here - right after a zip was unpacked:
#
#   WinError 5  (access denied) - a file extracted from an archive can
#                carry the read-only attribute, and rmtree refuses it
#   WinError 32 (file in use)   - the indexer or an antivirus scanner
#                still holds a handle on a freshly written file, or the
#                plugin itself left one open
#
# The first needs the attribute cleared, the second just needs a moment.
# So: clear read-only, then retry a few times over about a second. On
# Linux both loops are a no-op on the first pass.
_FS_RETRIES = 6
_FS_DELAY = 0.2


def _clear_readonly(path):
    try:
        import os
        import stat
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass


def _rmtree(path):
    """shutil.rmtree that survives Windows. Raises the last error if it
    really cannot delete."""
    import time
    path = Path(path)
    last = None
    for attempt in range(_FS_RETRIES):
        try:
            def _on_error(func, failed, exc):
                _clear_readonly(failed)
                func(failed)
            # onexc replaced onerror in 3.12; both exist in 3.12/3.13, so
            # pick by signature rather than by version number
            try:
                shutil.rmtree(str(path), onexc=lambda f, p_, e: _on_error(f, p_, e))
            except TypeError:
                shutil.rmtree(str(path), onerror=lambda f, p_, e: _on_error(f, p_, e))
            return
        except FileNotFoundError:
            return
        except OSError as e:
            last = e
            if attempt < _FS_RETRIES - 1:
                time.sleep(_FS_DELAY)
    if last is not None:
        raise last


def _move(src, dst):
    """shutil.move with the same retry treatment."""
    import time
    last = None
    for attempt in range(_FS_RETRIES):
        try:
            shutil.move(str(src), str(dst))
            return
        except OSError as e:
            last = e
            _clear_readonly(src)
            if attempt < _FS_RETRIES - 1:
                time.sleep(_FS_DELAY)
    if last is not None:
        raise last


class PluginError(Exception):
    """Anything that went wrong while installing/reading a plugin."""


class PluginExistsError(PluginError):
    """Raised by install_plugin_zip() when the id is already installed
    and overwrite=False – the UI turns this into an 'update?' prompt."""

    def __init__(self, pid, name=""):
        super().__init__(f"Plugin '{pid}' is already installed.")
        self.pid = pid
        self.name = name or pid


# --------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------
@dataclass
class Plugin:
    folder: Path
    pid: str
    name: str
    version: str = "?"
    author: str = ""
    description: str = ""
    github: str = ""
    main: str = "main.py"
    default_enabled: bool = True
    is_linux: bool = True          # manifest flags, both default to true
    is_windows: bool = True
    template: str = ""             # default custom string from the manifest
    placeholders: dict = field(default_factory=dict)   # name -> description
    global_keys: list = field(default_factory=list)    # unprefixed names
    schema: list = field(default_factory=list)         # user-editable options
    api_needed: int = 1            # manifest "api": the API it relies on
    min_app: str = ""              # optional "min_app": "v1.4.0" – a hint
                               # for the user, never parsed for a decision
    extra: dict = field(default_factory=dict)   # manifest keys we don't know
    enabled: bool = False          # effective state (central state file)
    module: object = None          # imported module while loaded
    api: object = None
    error: str = ""                # last import/hook error, shown in the UI

    @property
    def loaded(self):
        return self.module is not None

    @property
    def platform_ok(self):
        """False when the manifest rules this operating system out."""
        return self.is_windows if IS_WINDOWS else self.is_linux

    @property
    def api_ok(self):
        """False when the plugin needs a newer plugin API than this build
        provides. Checked BEFORE the import, so a plugin from the future
        is greyed out with a reason instead of raising somewhere inside
        setup()."""
        return int(self.api_needed or 1) <= PLUGIN_API_VERSION

    @property
    def supported(self):
        """Everything that has to be true before this build may run the
        plugin at all. Kept as one property because the whole UI asks
        this one question - the reason lives in platform_note."""
        return self.platform_ok and self.api_ok

    @property
    def platform_note(self):
        """Why the plugin is unusable here, empty when it is usable. The
        name is historical: it used to only ever be the OS."""
        if not self.platform_ok:
            return f"not for {OS_NAME}"
        if not self.api_ok:
            need = self.min_app.strip()
            return (f"needs a newer {APP_NAME}"
                    + (f" ({need})" if need else "")
                    + f" – plugin API {self.api_needed}, this build "
                      f"speaks {PLUGIN_API_VERSION}")
        return ""

    @property
    def unsupported_options(self):
        """Settings this build cannot render. Their values still exist,
        the plugin can still read them - only the row is disabled."""
        return [i for i in iter_settings(self.schema)
                if i.get("type") == UNSUPPORTED_TYPE]

    @property
    def main_path(self):
        return self.folder / self.main

    @property
    def config_dir(self):
        """plugins/<id>/configs/ – the plugin's own state + data folder."""
        return self.folder / CONFIG_DIRNAME

    @property
    def config_file(self):
        return self.config_dir / CONFIG_NAME

    @property
    def github_url(self):
        """Manifests usually contain 'github.com/user' without a scheme –
        QDesktopServices needs a real URL, so normalise it here."""
        url = (self.github or "").strip()
        if not url:
            return ""
        if url.startswith(("http://", "https://")):
            return url
        return "https://" + url.lstrip("/")


class PluginAPI:
    """Everything a plugin is handed in setup(). Deliberately small –
    extend it here instead of letting plugins poke at internals.

    Anything added here has to be added to CAPABILITIES as well, because
    that is what a plugin is meant to test against. The pattern that
    keeps one plugin release working across app versions is::

        if api.supports("api.set"):
            api.set("binary", found)
        else:
            self._binary = found      # remember it for this session only
    """

    def __init__(self, manager, plugin):
        self._manager = manager
        self._plugin = plugin
        self.app_name = APP_NAME
        self.app_version = VERSION
        # what the app can do, for feature detection
        self.api_version = PLUGIN_API_VERSION
        self.capabilities = CAPABILITIES
        self.plugin_id = plugin.pid
        self.plugin_dir = plugin.folder
        # the plugin's own writable folder – same place its config.json
        # lives, and it survives an update from a newer .zip
        self.data_dir = plugin.config_dir
        # the MainWindow, or None when the manager runs headless
        self.host = manager.host
        # live dict of the user's option values (the "settings" schema in
        # plugin.json). The manager mutates THIS object in place, so a
        # plugin can just read api.settings whenever it needs a value.
        self.settings = manager.options(plugin.pid)

    def log(self, msg):
        self._manager.log(f"[{self.plugin_id}] {msg}")

    def get(self, key, default=None):
        """Convenience reader for a declared setting."""
        return self.settings.get(key, default)

    # ------------------------------------------------ feature detection
    def supports(self, feature):
        """True when this build offers a named capability.

        Also answers "hook.<name>" and "settings.<type>", so a plugin can
        ask the two questions it actually has: 'may I call this?' and
        'will my settings row show up?'
        """
        feature = str(feature or "").strip()
        if not feature:
            return False
        if feature in self.capabilities:
            return True
        if feature.startswith("hook."):
            return feature[5:] in HOOKS
        return False

    def needs(self, version):
        """True when the app speaks at least this plugin API version."""
        try:
            return PLUGIN_API_VERSION >= int(version)
        except (TypeError, ValueError):
            return False

    # ----------------------------------------------------- writing back
    def set(self, key, value):
        """Store one of the plugin's own settings and persist it.

        For values the plugin discovers rather than the user types – an
        autodetected path, a token it just refreshed, the window size of
        its own panel. The visible widget follows along, and on_settings
        is NOT called back, so a plugin cannot loop through its own
        write.
        """
        return self._manager.set_option(self.plugin_id, key, value,
                                        notify=False, from_plugin=True)

    def set_many(self, values):
        if not isinstance(values, dict):
            return False
        ok = True
        for key, value in values.items():
            ok = self.set(key, value) and ok
        return ok

    def refresh(self):
        """Ask the app for a fresh chatbox render, e.g. after data
        arrived that would otherwise wait for the next tick."""
        return self._manager.request_refresh()

    # -------------------------------------------------------- the disk
    def ensure_data_dir(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    def data_path(self, *parts):
        """A path inside the plugin's own folder, parents created. Keeps
        plugins from inventing their own place under $HOME."""
        path = self.ensure_data_dir().joinpath(*[str(p) for p in parts])
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


# --------------------------------------------------------------------
# manager
# --------------------------------------------------------------------
class PluginManager:
    def __init__(self, log=print, host=None, plugins_dir=PLUGINS_DIR):
        self.log = log
        self.host = host
        self.dir = Path(plugins_dir)
        self.plugins = {}          # pid -> Plugin, insertion = display order
        self.settings = {}         # pid -> config dict (mirrors config.json)
        self._snap = None          # cached snapshot for the current frame

    # ------------------------------------------------- per-plugin config
    def entry(self, pid):
        """The settings block of one plugin (mirror of its config.json).

        Keys: enabled, line, custom, template, options. "line" decides
        whether the plugin prints its own chatbox line – off means it still
        runs and still fills {<id>}, it just doesn't print itself, which is
        what you want once you placed it inside another template.
        """
        entry = self.settings.get(pid)
        if isinstance(entry, dict):
            return entry
        plugin = self.plugins.get(pid)
        if plugin is not None:
            return self._read_config(plugin)
        entry = {"enabled": False, "anchor": DEFAULT_ANCHOR, "order": 1000,
                 "line": True, "custom": False,
                 "template": "{%s}" % pid, "options": {}}
        self.settings[pid] = entry
        return entry

    def options(self, pid):
        """Option values of one plugin, schema defaults filled in. Returns
        the live dict – api.settings points at this very object."""
        opts = self.entry(pid)["options"]
        plugin = self.plugins.get(pid)
        for item in iter_settings(plugin.schema if plugin else []):
            if item["key"] not in opts:
                opts[item["key"]] = item["default"]
        return opts

    def _changed(self, pid):
        """Persist one plugin's config and drop the cached snapshot."""
        self._snap = None
        self._write_config(pid)

    def set_anchor(self, pid, anchor):
        """Where this plugin's lines go relative to the standard apps."""
        self.entry(pid)["anchor"] = (anchor if anchor in ANCHORS
                                     else DEFAULT_ANCHOR)
        self._changed(pid)

    def ordered(self):
        """All known plugins in the user's order. Ties fall back to the id,
        so the list can never jump around between starts."""
        return sorted(self.plugins.values(),
                      key=lambda p: (self.entry(p.pid)["order"], p.pid))

    def move_to(self, pid, index):
        """Puts a plugin at a given position among the plugins.

        Orders are rewritten as a dense 0..n-1 sequence afterwards, so
        repeated moves cannot drift apart or collide - otherwise two
        plugins sharing an order would silently sort by id instead.
        Only the configs that actually changed are written, because a
        drag fires this on every mouse move.
        """
        ids = [p.pid for p in self.ordered()]
        if pid not in ids:
            return False
        index = max(0, min(len(ids) - 1, int(index)))
        if ids.index(pid) == index:
            return False
        ids.remove(pid)
        ids.insert(index, pid)
        for pos, key in enumerate(ids):
            entry = self.entry(key)
            if entry["order"] != pos:
                entry["order"] = pos
                self._write_config(key)
        self._snap = None
        return True

    def move(self, pid, delta):
        """Convenience wrapper: one step up (-1) or down (+1)."""
        ids = [p.pid for p in self.ordered()]
        if pid not in ids:
            return False
        return self.move_to(pid, ids.index(pid) + delta)

    def normalize_order(self):
        """Gives every plugin a distinct order. Called after discovery so
        freshly installed plugins land at the end instead of all sharing
        the default 1000."""
        for pos, plugin in enumerate(self.ordered()):
            entry = self.entry(plugin.pid)
            if entry["order"] != pos:
                entry["order"] = pos
                self._write_config(plugin.pid)

    def set_line(self, pid, on):
        self.entry(pid)["line"] = bool(on)
        self._changed(pid)

    def set_custom(self, pid, on):
        self.entry(pid)["custom"] = bool(on)
        self._changed(pid)

    def set_template(self, pid, text):
        self.entry(pid)["template"] = str(text)
        self._changed(pid)

    def reset_template(self, pid):
        """Back to the default string the plugin author shipped."""
        plugin = self.plugins.get(pid)
        default = plugin.template if plugin else "{%s}" % pid
        self.entry(pid)["template"] = default
        self._changed(pid)
        return default

    def set_option(self, pid, key, value, notify=True, from_plugin=False):
        """Stores one option value. The options dict is mutated in place,
        so api.settings sees it immediately.

        ``notify`` runs the plugin's on_settings hook – off when the
        plugin itself is the writer (api.set), because a plugin reacting
        to its own write is how you build an endless loop.
        ``from_plugin`` additionally pushes the new value into the widget
        the user is looking at, if the Plugins page is built.
        """
        opts = self.options(pid)
        opts[str(key)] = value
        plugin = self.plugins.get(pid)
        if notify and plugin is not None and plugin.loaded:
            self._safe_call(plugin, "on_settings", opts)
        self._changed(pid)
        if from_plugin:
            self._ui_call("sync_plugin_option", pid, str(key), value)
        return True

    def _ui_call(self, method, *args):
        """Optional call into the host window. The manager also runs
        headless (tests, a future CLI), and an older window simply does
        not have the method – neither is an error.

        A plugin may call this from one of its own worker threads, and a
        Qt widget touched from a non-GUI thread is a segfault, not an
        exception. So the call is handed to the window's event loop with
        the window itself as the context object, which is what makes Qt
        run it in the GUI thread. Only if there is no Qt at all (headless
        manager) does it run inline.
        """
        fn = getattr(self.host, method, None)
        if not callable(fn):
            return False

        def run():
            try:
                fn(*args)
            except Exception as e:
                self.log(f"Plugins: host.{method}() raised: {e}")

        try:
            from PyQt6.QtCore import QObject, QTimer
            if isinstance(self.host, QObject):
                # singleShot with a context object queues into THAT
                # object's thread – the one guarantee we need here
                QTimer.singleShot(0, self.host, run)
                return True
        except Exception:
            pass
        run()
        return True

    def request_refresh(self):
        """A plugin asking for a fresh render. Drops the cached snapshot
        in any case, so the next frame is up to date even when the window
        cannot re-render on demand."""
        self._snap = None
        return self._ui_call("update_preview")

    # ---------------------------------------------------------- state
    def _read_config(self, plugin):
        """Loads plugins/<id>/configs/config.json. A missing or broken file
        is not an error – we fall back to the manifest defaults so a plugin
        always stays usable."""
        path = plugin.config_file
        data = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
                else:
                    raise ValueError("config.json must contain an object")
            except Exception as e:
                self.log(f"Plugins: '{plugin.pid}' config unreadable ({e}) – "
                         f"using the defaults from {MANIFEST_NAME}.")
        anchor = str(data.get("anchor", DEFAULT_ANCHOR))
        try:
            order = int(data.get("order", 1000))
        except (TypeError, ValueError):
            order = 1000
        entry = {
            "enabled": bool(data.get("enabled", plugin.default_enabled)),
            "anchor": anchor if anchor in ANCHORS else DEFAULT_ANCHOR,
            "order": order,
            "line": bool(data.get("line", True)),
            "custom": bool(data.get("custom", False)),
            "template": (str(data.get("template") or "").strip()
                         or plugin.template),
            "options": (dict(data["options"])
                        if isinstance(data.get("options"), dict) else {}),
            # keys a newer app wrote here. This build cannot use them,
            # but rewriting the file without them would quietly delete
            # settings the user made in that newer version - so they ride
            # along and go back out in _write_config().
            "extra": {k: v for k, v in data.items()
                      if k not in KNOWN_CONFIG_KEYS},
        }
        self.settings[plugin.pid] = entry
        return entry

    def _write_config(self, pid):
        """Writes one plugin's config.json. Failures are logged, never
        raised – losing a setting must not take the chatbox down."""
        plugin = self.plugins.get(pid)
        entry = self.settings.get(pid)
        if plugin is None or entry is None:
            return
        try:
            plugin.config_dir.mkdir(parents=True, exist_ok=True)
            # encoding pinned: ensure_ascii=False means real emoji and
            # box characters land in the file, and Windows would
            # otherwise write it in the locale codepage (cp1252) and
            # raise on the first one - silently losing the setting,
            # because the failure below is logged and swallowed
            data = {k: v for k, v in entry.items() if k != "extra"}
            # unknown keys go back where they came from: at the top
            # level, and never on top of a key we do own
            for key, value in (entry.get("extra") or {}).items():
                data.setdefault(key, value)
            plugin.config_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception as e:
            self.log(f"Plugins: could not save the settings of "
                     f"'{pid}': {e}")

    # ------------------------------------------------------- discovery
    def discover(self):
        """(Re)scans the plugins folder. Already loaded modules stay
        loaded – this only refreshes the metadata list."""
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log(f"Plugins: folder {self.dir} not usable: {e}")
            return []

        found = {}
        for folder in sorted(p for p in self.dir.iterdir() if p.is_dir()):
            if folder.name.startswith((".", "_")):
                continue
            try:
                plugin = self._read_manifest(folder)
            except PluginError as e:
                self.log(f"Plugins: skipping '{folder.name}': {e}")
                continue
            # keep the live module/error of a plugin we already know
            old = self.plugins.get(plugin.pid)
            if old is not None and old.folder == plugin.folder:
                plugin.module = old.module
                plugin.api = old.api
                plugin.error = old.error
            found[plugin.pid] = plugin

        # plugins that vanished from disk: unload them before dropping
        for pid, old in self.plugins.items():
            if pid not in found and old.loaded:
                self._unload(old)
        self.plugins = found
        # settings of plugins that are gone would only go stale
        for pid in [k for k in self.settings if k not in found]:
            self.settings.pop(pid, None)
        # config.json can only be read once the plugin is in self.plugins
        for plugin in found.values():
            plugin.enabled = self._read_config(plugin)["enabled"]
        self.normalize_order()
        self._snap = None
        return list(self.plugins.values())

    def _read_manifest(self, folder):
        path = folder / MANIFEST_NAME
        if not path.exists():
            raise PluginError(f"no {MANIFEST_NAME}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise PluginError(f"{MANIFEST_NAME} is not valid JSON ({e})")
        return self._plugin_from_dict(data, folder)

    @staticmethod
    def _plugin_from_dict(data, folder):
        if not isinstance(data, dict):
            raise PluginError(f"{MANIFEST_NAME} must contain an object")
        pid = str(data.get("id", "")).strip().lower()
        if not ID_RE.match(pid):
            raise PluginError(
                "invalid or missing 'id' (allowed: a-z, 0-9, '_', '-')")
        main = str(data.get("main", "main.py")).strip() or "main.py"
        # 'main' must stay inside the plugin folder
        if Path(main).is_absolute() or ".." in Path(main).parts:
            raise PluginError("'main' must be a path inside the plugin folder")
        # the manifest key is capitalised in the spec, accept both spellings
        github = data.get("Github") or data.get("github") or ""
        # optional extras – a plugin that ships none still works, it just
        # gets the auto-generated "{<id>}" template and no options UI
        placeholders = data.get("placeholders")
        if not isinstance(placeholders, dict):
            placeholders = {}
        template = str(data.get("template") or "").strip() or "{%s}" % pid
        raw_globals = data.get("global_placeholders")
        global_keys = []
        if isinstance(raw_globals, list):
            for k in raw_globals:
                key = str(k).strip().lower().replace(" ", "_")
                if key and key != pid and key not in global_keys:
                    global_keys.append(key)
        # which plugin API the author wrote against. Missing means 1:
        # every manifest that exists today predates the key and works
        # exactly as before.
        try:
            api_needed = int(data.get("api", 1) or 1)
        except (TypeError, ValueError):
            api_needed = 1
        return Plugin(
            folder=Path(folder),
            pid=pid,
            name=str(data.get("name") or pid),
            version=str(data.get("version") or "?"),
            author=str(data.get("author") or "unknown"),
            description=str(data.get("description") or ""),
            github=str(github),
            main=main,
            default_enabled=bool(data.get("enabled", True)),
            is_linux=bool(data.get("is_linux", True)),
            is_windows=bool(data.get("is_windows", True)),
            template=template,
            placeholders={str(k): str(v) for k, v in placeholders.items()},
            global_keys=global_keys,
            schema=PluginManager._parse_schema(data.get("settings")),
            api_needed=max(1, api_needed),
            min_app=str(data.get("min_app") or "").strip(),
            # anything this build has no idea about. Kept so a manifest
            # written for a newer app is not silently truncated, and so a
            # future feature can be read straight off Plugin.extra
            extra={k: PluginManager._json_safe(v) for k, v in data.items()
                   if k not in KNOWN_MANIFEST_KEYS},
        )

    @staticmethod
    def _parse_schema(raw, _depth=0, _seen=None):
        """Validates the optional "settings" list from plugin.json. Bad
        entries are dropped instead of raising – a typo in one option
        must not make the whole plugin uninstallable.

        Groups recurse with the SAME ``seen`` set, so a key stays unique
        across the whole schema no matter how deeply it sits: option
        values live in one flat dict, and two rows sharing a key would
        silently overwrite each other.
        """
        if not isinstance(raw, list):
            return []
        out = []
        seen = _seen if _seen is not None else set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            kind = str(item.get("type", "text")).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            entry = {
                "key": key,
                "type": kind,
                "label": str(item.get("label") or key),
                "hint": str(item.get("hint") or ""),
                # optional: only show this row while the named setting is
                # on, the way "Max length" hides under "Song title"
                "depends": str(item.get("depends") or "").strip(),
                # ... or while it has one of these values, for choices
                "depends_value": PluginManager._parse_depends_value(item),
                # everything this build does not know about the row. Not
                # used here, deliberately kept: a newer UI can read it
                # without every older app having to be taught the key
                "extra": {k: v for k, v in item.items()
                          if k not in KNOWN_ITEM_KEYS},
            }

            # ---- a type from a newer app, or a group nested too deep.
            # The row is kept as a disabled placeholder rather than
            # dropped: its value stays in config.json, api.get() keeps
            # returning it, and the page can tell the user what is
            # missing instead of showing a hole in the settings.
            too_deep = kind == GROUP_TYPE and _depth >= MAX_GROUP_DEPTH
            if kind not in SETTING_TYPES or too_deep:
                entry["type"] = UNSUPPORTED_TYPE
                entry["raw_type"] = kind
                entry["default"] = PluginManager._json_safe(
                    item.get("default"))
                entry["reason"] = (
                    "nested too deeply for this version"
                    if too_deep else
                    f"setting type '{kind}' needs a newer {APP_NAME}")
                out.append(entry)
                continue

            if kind == GROUP_TYPE:
                entry["expanded"] = bool(item.get("expanded", False))
                entry["items"] = PluginManager._parse_schema(
                    item.get("items"), _depth + 1, seen)
                entry["default"] = None
                if not entry["items"]:
                    continue        # an empty block has nothing to show
                out.append(entry)
                continue

            if kind == "choice":
                choices = PluginManager._parse_choices(item)
                if not choices:
                    continue        # a dropdown without entries is a typo
                entry["choices"] = choices
                values = [v for v, _lbl in choices]
                default = str(item.get("default", values[0]))
                entry["default"] = default if default in values else values[0]
                out.append(entry)
                continue

            if kind == "path":
                # a text row with a file picker next to it. The value is
                # whatever the user typed or picked - never resolved,
                # never checked for existence here: a plugin may well
                # want a path that does not exist yet, and a config
                # carried to another machine must not be "corrected".
                entry["default"] = str(item.get("default", ""))
                mode = str(item.get("mode", "file")).strip().lower()
                entry["mode"] = mode if mode in ("file", "dir") else "file"
                filters = item.get("filters")
                entry["filters"] = [str(f) for f in filters
                                    if str(f).strip()] \
                    if isinstance(filters, (list, tuple)) else []
                entry["placeholder"] = str(item.get("placeholder") or "")
                out.append(entry)
                continue

            if kind == ACTION_TYPE:
                # a button. "button" is the caption, the label to its
                # left is the question it answers. Pressing it calls the
                # plugin's on_action(key).
                entry["button"] = str(item.get("button") or item["label"])
                entry["style"] = str(item.get("style") or "normal").lower()
                out.append(entry)
                continue

            if kind == "label":
                # a read-only line. The value comes from the options like
                # any other setting, so api.set(key, text) turns it into
                # a live status line without the plugin needing a widget.
                entry["default"] = str(item.get("default", ""))
                out.append(entry)
                continue

            if kind == "emoji":
                # a text row with the app's own icon picker next to it.
                # Deliberately a full text field and not a single
                # character: a plugin icon is often two of them (a base
                # emoji plus a variation selector), and people paste
                # things like "♡ " with a trailing space on purpose.
                entry["default"] = str(item.get("default", ""))
                entry["placeholder"] = str(item.get("placeholder") or "")
                out.append(entry)
                continue

            if kind == "bool":
                entry["default"] = bool(item.get("default", False))
            elif kind in ("int", "slider"):
                entry["default"] = int(item.get("default", 0) or 0)
                entry["min"] = int(item.get("min", 0) or 0)
                entry["max"] = int(item.get("max", 999) or 999)
                if entry["max"] < entry["min"]:
                    entry["min"], entry["max"] = entry["max"], entry["min"]
                entry["default"] = max(entry["min"],
                                       min(entry["max"], entry["default"]))
                entry["suffix"] = str(item.get("suffix") or "")
            else:
                entry["default"] = str(item.get("default", ""))
                # masked input for tokens and API keys
                entry["secret"] = bool(item.get("secret", False))
            out.append(entry)
        return out

    @staticmethod
    def _json_safe(value, _depth=0):
        """Whatever survives a round trip through config.json.

        Used for the default of a setting type this build does not know:
        the value has to be storable without understanding it, and it
        must not be able to smuggle in something json cannot write.
        """
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if _depth >= 4:
            return None
        if isinstance(value, (list, tuple)):
            return [PluginManager._json_safe(v, _depth + 1) for v in value]
        if isinstance(value, dict):
            return {str(k): PluginManager._json_safe(v, _depth + 1)
                    for k, v in value.items()}
        return str(value)

    @staticmethod
    def _parse_depends_value(item):
        """The values a parent setting must have for this row to show.

        Empty list = the old behaviour: the parent is tested for
        truthiness. Everything is compared as a string, because that is
        what a choice stores.
        """
        raw = item.get("depends_value")
        if raw is None:
            return []
        if isinstance(raw, (list, tuple, set)):
            return [str(v) for v in raw if str(v) != ""]
        return [str(raw)] if str(raw) != "" else []

    @staticmethod
    def _parse_choices(item):
        """[(value, label), ...] for a choice row.

        Accepts the long form [{"value": "a", "label": "A"}] and the
        short one ["a", "b"], where the value doubles as the label.
        Duplicates are dropped so the stored value always maps back to
        exactly one entry.
        """
        raw = item.get("choices")
        if not isinstance(raw, (list, tuple)):
            raw = item.get("options")
        if not isinstance(raw, (list, tuple)):
            return []
        out = []
        seen = set()
        for opt in raw:
            if isinstance(opt, dict):
                value = str(opt.get("value", opt.get("key", ""))).strip()
                label = str(opt.get("label") or value)
            else:
                value = str(opt).strip()
                label = value
            if not value or value in seen:
                continue
            seen.add(value)
            out.append((value, label))
        return out

    # ------------------------------------------------------ (un)loading
    def load_enabled(self):
        """Imports every enabled plugin. Called once at startup after
        discover()."""
        for plugin in self.plugins.values():
            if plugin.enabled and not plugin.loaded:
                self._load(plugin)

    def _load(self, plugin):
        """Imports the plugin module and runs setup(api). Returns True on
        success; failures are stored in plugin.error and logged."""
        if plugin.loaded:
            return True
        if not plugin.platform_ok:
            # a zip install bypasses the store, so the guard belongs here:
            # loading anyway would end in a traceback from some missing
            # system tool rather than a clear message
            plugin.error = (f"This plugin is marked as not compatible with "
                            f"{OS_NAME} ({MANIFEST_NAME}).")
            self.log(f"Plugins: '{plugin.pid}' skipped - {plugin.platform_note}")
            return False
        if not plugin.api_ok:
            # the same idea one step earlier: a plugin built against a
            # newer API would import fine and then call something that
            # does not exist yet. Refusing here costs the user a greyed
            # out row; importing it costs them a traceback per frame.
            plugin.error = (
                f"This plugin needs plugin API {plugin.api_needed}; "
                f"{APP_NAME} {VERSION} provides {PLUGIN_API_VERSION}. "
                f"Update the app" + (f" to {plugin.min_app}"
                                     if plugin.min_app else "") + ".")
            self.log(f"Plugins: '{plugin.pid}' skipped - {plugin.platform_note}")
            return False
        if not plugin.main_path.exists():
            plugin.error = f"{plugin.main} not found"
            self.log(f"Plugins: '{plugin.pid}' – {plugin.error}")
            return False
        mod_name = MODULE_PREFIX + plugin.pid.replace("-", "_")
        try:
            spec = importlib.util.spec_from_file_location(
                mod_name, plugin.main_path,
                # makes the plugin folder a package root, so a plugin can
                # ship helper modules and use relative imports
                submodule_search_locations=[str(plugin.folder)])
            if spec is None or spec.loader is None:
                raise ImportError("could not create an import spec")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(mod_name, None)
            plugin.error = traceback.format_exc(limit=4).strip()
            self.log(f"Plugins: '{plugin.pid}' failed to load:\n"
                     f"{plugin.error}")
            return False

        plugin.module = module
        plugin.api = PluginAPI(self, plugin)
        plugin.error = ""
        self._snap = None
        # setup() is optional: only an exception counts as a failure
        if hasattr(module, "setup"):
            ok, _res = self._safe_call(plugin, "setup", plugin.api)
            if not ok:
                self._unload(plugin, call_teardown=False)
                return False
        self.log(f"Plugins: loaded '{plugin.name}' {plugin.version}")
        return True

    def _unload(self, plugin, call_teardown=True):
        """Drops the module reference (python can't truly unload code, but
        this stops all dispatch and lets the next enable re-import a fresh
        copy of the file)."""
        if plugin.module is None:
            return
        if call_teardown:
            self._safe_call(plugin, "teardown")
        # the plugin's OWN submodules go too. A plugin of more than one
        # file imports them as "<mod_name>.panel" and friends, and those
        # stay in sys.modules after the top module is dropped - so
        # re-importing after an update would build a fresh main.py that
        # pulls the previous version's helpers straight out of the cache.
        # The symptom is a plugin showing its new manifest and running
        # its old code, which is a genuinely confusing afternoon.
        mod_name = MODULE_PREFIX + plugin.pid.replace("-", "_")
        for name in [n for n in sys.modules
                     if n == mod_name or n.startswith(mod_name + ".")]:
            sys.modules.pop(name, None)
        plugin.module = None
        plugin.api = None
        self._snap = None
        self.log(f"Plugins: unloaded '{plugin.name}'")

    def reload(self, pid):
        """Disable + enable in one go – useful while developing a plugin."""
        plugin = self.plugins.get(pid)
        if plugin is None:
            return False
        self._unload(plugin)
        return self._load(plugin) if plugin.enabled else True

    # -------------------------------------------------------- toggling
    def set_enabled(self, pid, on):
        """Central toggle: persists the state and loads/unloads live, so
        the change takes effect immediately AND survives a restart. The
        plugin files are never touched."""
        plugin = self.plugins.get(pid)
        if plugin is None:
            return False
        plugin.enabled = bool(on)
        self.entry(pid)["enabled"] = bool(on)
        self._changed(pid)
        if on:
            return self._load(plugin)
        self._unload(plugin)
        return True

    def is_enabled(self, pid):
        plugin = self.plugins.get(pid)
        return bool(plugin and plugin.enabled)

    # -------------------------------------------------------- dispatch
    def _safe_call(self, plugin, hook, *args, **kwargs):
        """Calls a hook on ONE plugin. Never raises: on error the plugin is
        marked and the traceback goes to the debug console.

        Returns ``(ok, result)`` – ok is False when the hook doesn't exist
        or blew up. Note the tuple: a hook that legitimately returns None
        (setup(), teardown()) must not be mistaken for a failure.
        """
        fn = getattr(plugin.module, hook, None)
        if not callable(fn):
            return False, None
        try:
            return True, fn(*args, **kwargs)
        except Exception:
            plugin.error = traceback.format_exc(limit=4).strip()
            self.log(f"Plugins: '{plugin.pid}'.{hook}() raised:\n"
                     f"{plugin.error}")
            return False, None

    def _active(self):
        return [p for p in self.ordered()
                if p.enabled and p.loaded and p.supported]

    def dispatch(self, hook, *args, **kwargs):
        """Fire-and-forget hook on every active plugin. Returns the list of
        (pid, result) pairs for the plugins that implement it and survived
        the call – plugins that raised are simply skipped."""
        out = []
        for plugin in self._active():
            ok, res = self._safe_call(plugin, hook, *args, **kwargs)
            if ok:
                out.append((plugin.pid, res))
        return out

    def invalidate(self):
        """Drops the cached snapshot. MainWindow calls this once at the top
        of build_payload(), so every plugin hook runs exactly once per
        frame no matter how many places ask for its values.

        This is also the frame boundary, so it is where on_tick() fires:
        a plugin that has to poll something cheap gets a heartbeat
        without starting a thread, and it runs BEFORE get_values(), so
        whatever it collected is in this frame rather than the next.
        """
        self._snap = None
        self.dispatch("on_tick")

    def emit(self, name, data=None):
        """Announce a host event to every active plugin.

        The one extension point that needs no new code on either side: a
        future notification is a new name, and every plugin that does not
        know it ignores it. Names are dotted and lower case, e.g.
        "app.shutdown", "avatar.changed", "chatbox.sent".

        Returns the list of (pid, result) pairs, so an event can also be
        used to ask plugins something.
        """
        name = str(name or "").strip().lower()
        if not name:
            return []
        payload = data if isinstance(data, dict) else {"value": data}
        return self.dispatch("on_event", name, payload)

    def build_widget(self, pid, parent=None):
        """The plugin's own UI, or None.

        Goes through _safe_call like every other hook, so a plugin whose
        widget code is broken loses its panel and nothing else. The host
        decides where to put the result; it may call this again after a
        rebuild, and a plugin is expected to survive that (either by
        building a fresh widget or by noticing its cached one was
        deleted).
        """
        plugin = self.plugins.get(pid)
        if plugin is None or not plugin.loaded or not plugin.supported:
            return None
        ok, widget = self._safe_call(plugin, "build_widget", parent)
        return widget if ok else None

    def trigger_action(self, pid, key):
        """One of the plugin's action buttons was pressed.

        Nothing is stored - the button has a key so the plugin can tell
        which one it was, not because it holds a value. The return value
        of on_action() is handed back, so a plugin can answer with a
        string for the UI to show.
        """
        plugin = self.plugins.get(pid)
        if plugin is None or not plugin.loaded:
            return None
        ok, result = self._safe_call(plugin, "on_action", str(key))
        return result if ok else None

    def has_hook(self, pid, hook):
        """Whether one plugin implements a given hook – lets the UI show
        a panel button only for plugins that have a panel."""
        plugin = self.plugins.get(pid)
        return bool(plugin and plugin.loaded
                    and callable(getattr(plugin.module, hook, None)))

    def snapshot(self):
        """One pass over all active plugins: main text, extra values and
        raw lines. Cached until invalidate()."""
        if self._snap is not None:
            return self._snap
        snap = {}
        for plugin in self._active():
            lines = []
            ok, res = self._safe_call(plugin, "get_lines")
            if ok:
                if isinstance(res, str):
                    res = [res]
                if isinstance(res, (list, tuple)):
                    lines = [str(x) for x in res if str(x).strip()]
            # {<id>} is get_text() if the plugin has one, else its lines
            ok, res = self._safe_call(plugin, "get_text")
            if ok and isinstance(res, str):
                text = res
            else:
                text = "\n".join(lines)
            values = {}
            ok, res = self._safe_call(plugin, "get_values")
            if ok and isinstance(res, dict):
                for k, v in res.items():
                    key = str(k).strip().lower().replace(" ", "_")
                    if key:
                        values[key] = None if v is None else str(v)
            snap[plugin.pid] = {"lines": lines, "text": text,
                                "values": values}
        self._snap = snap
        return snap

    def raw_values(self):
        """The unfiltered values: ``{<id>}`` is whatever the plugin itself
        produced, ignoring any custom string. This is what a custom string
        is rendered against."""
        out = {}
        for pid, data in self.snapshot().items():
            plugin = self.plugins.get(pid)
            out[pid] = data["text"] or None
            for key, val in data["values"].items():
                out[f"{pid}_{key}"] = val
                # names the plugin claimed unprefixed, e.g. {realtime}
                if plugin is not None and key in plugin.global_keys:
                    out.setdefault(key, val)
        return out

    def values(self):
        """Flat placeholder dict for apply_template(): ``{<id>}`` for each
        plugin plus ``{<id>_<key>}`` for everything get_values() returned.
        Namespacing by id keeps two plugins from fighting over a key.

        With the custom string switched on, ``{<id>}`` is that string, not
        the plugin's raw output – so putting {world_stats} into All-in-one
        gives the same layout you configured on the Plugins page instead of
        quietly ignoring it.

        Custom strings are rendered against raw_values(), never against
        each other. That is what keeps the default template "{<id>}" from
        recursing into itself, and it means two plugins referencing each
        other produce a defined result rather than depending on order.
        """
        raw = self.raw_values()
        out = dict(raw)
        for pid in self.snapshot():
            entry = self.entry(pid)
            if not (entry["custom"] and entry["template"].strip()):
                continue
            rendered = apply_template(entry["template"], raw)
            out[pid] = rendered or None
        return out

    def merge_into(self, vals):
        """Adds the plugin placeholders to an existing value dict without
        stomping on anything the app already filled in. Used by the Apps
        page so a built-in {player_in_world} keeps priority over a plugin
        claiming the same name."""
        for key, val in self.values().items():
            if val is not None and vals.get(key) is None:
                vals[key] = val
        return vals

    def any_active(self):
        """True when at least one plugin is enabled and loaded – lets the
        window know it should keep the preview refresh timer running."""
        return bool(self._active())

    def _plugin_lines(self, plugin, vals):
        entry = self.entry(plugin.pid)
        if not entry["line"]:
            return []      # placeholder-only: values yes, own line no
        if entry["custom"] and entry["template"].strip():
            text = vals.get(plugin.pid)
            return text.split("\n") if text else []
        return list(self.snapshot().get(plugin.pid, {}).get("lines", []))

    def lines_by_anchor(self):
        """{anchor: [lines]} for every active plugin, each group already in
        the user's plugin order. MainWindow walks the app order and drops
        each group in front of the app it is anchored to, so anchors decide
        the section and the plugin order decides the rest."""
        out = {a: [] for a in ANCHORS}
        vals = self.values()
        active = {p.pid for p in self._active()}
        for plugin in self.ordered():
            if plugin.pid not in active:
                continue
            entry = self.entry(plugin.pid)
            anchor = entry["anchor"] if entry["anchor"] in ANCHORS \
                else DEFAULT_ANCHOR
            out[anchor].extend(self._plugin_lines(plugin, vals))
        return out

    def render_lines(self):
        """Every plugin line in order, ignoring the anchors. Used when
        there is no app order to slot them into."""
        grouped = self.lines_by_anchor()
        lines = []
        for anchor in ANCHORS:
            lines.extend(grouped[anchor])
        return lines

    def filter_text(self, text):
        """Runs the final chatbox text through every on_text() hook. A
        plugin returning something that isn't a string is ignored, so a
        sloppy plugin can't wipe the chatbox."""
        for plugin in self._active():
            ok, res = self._safe_call(plugin, "on_text", text)
            if ok and isinstance(res, str):
                text = res
        return text

    def shutdown(self):
        """teardown() everything – call this from MainWindow.closeEvent."""
        # announced first: a plugin may want to flush state while the
        # rest of the app is still standing
        self.emit("app.shutdown")
        for plugin in list(self.plugins.values()):
            self._unload(plugin)

    # ---------------------------------------------------- zip install
    def install_plugin_zip(self, zip_path, overwrite=False):
        """Validates and installs a .zip into the plugins folder.

        Accepts both layouts: manifest at the archive root, or inside a
        single top-level folder (what GitHub's 'Download ZIP' produces).
        Raises PluginError / PluginExistsError on problems, otherwise
        returns the freshly discovered Plugin.
        """
        zip_path = Path(zip_path).expanduser()
        if not zip_path.is_file() or not zipfile.is_zipfile(zip_path):
            raise PluginError("That file is not a valid .zip archive.")

        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            # --- zip-slip / zip-bomb guards -------------------------
            for info in infos:
                name = info.filename.replace("\\", "/")
                parts = Path(name).parts
                if name.startswith("/") or Path(name).is_absolute() \
                        or ".." in parts:
                    raise PluginError(
                        f"Archive contains an unsafe path: {info.filename}")
            total = sum(i.file_size for i in infos)
            if total > MAX_UNPACKED_BYTES:
                raise PluginError(
                    f"Archive is too large when unpacked "
                    f"({total // (1024 * 1024)} MB, limit "
                    f"{MAX_UNPACKED_BYTES // (1024 * 1024)} MB).")

            # --- locate the manifest (root or one folder deep) -------
            manifests = [
                i.filename for i in infos
                if Path(i.filename).name == MANIFEST_NAME
                and len(Path(i.filename).parts) <= 2]
            if not manifests:
                raise PluginError(
                    f"No {MANIFEST_NAME} found in the archive "
                    f"(it must sit at the top level or in a single folder).")
            manifest = sorted(manifests, key=lambda n: len(Path(n).parts))[0]
            try:
                data = json.loads(zf.read(manifest).decode("utf-8"))
            except Exception as e:
                raise PluginError(f"{MANIFEST_NAME} is not valid JSON ({e})")

            root = Path(manifest).parent           # "." when at zip root
            meta = self._plugin_from_dict(data, self.dir / "unused")
            target = self.dir / meta.pid
            existing = self.plugins.get(meta.pid)
            if target.exists() and not overwrite:
                raise PluginExistsError(meta.pid,
                                        existing.name if existing else
                                        meta.name)

            # "_" prefix: discover() skips folders starting with "." or
            # "_", so a leftover from a crashed install is never mistaken
            # for a plugin. ignore_cleanup_errors: on Windows a scanner
            # holding one file open would otherwise raise AFTER the
            # install already succeeded.
            with tempfile.TemporaryDirectory(
                    dir=str(self._tmp_base()), prefix="_install_",
                    ignore_cleanup_errors=True) as tmp:
                zf.extractall(tmp)
                source = Path(tmp) / root if str(root) != "." else Path(tmp)
                if not (source / meta.main).exists():
                    raise PluginError(
                        f"'{meta.main}' is listed in {MANIFEST_NAME} but "
                        f"missing from the archive.")
                # unload the old copy before replacing files on disk
                if existing is not None:
                    self._unload(existing)
                # an update must not reset what the user configured, so the
                # old configs/ folder is carried over to the new install
                # (unless the archive ships one of its own)
                keep = target / CONFIG_DIRNAME
                saved = None
                if keep.is_dir():
                    saved = Path(tmp) / "__configs_backup__"
                    _move(keep, saved)
                if target.exists():
                    _rmtree(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                _move(source, target)
                if saved is not None and not (target / CONFIG_DIRNAME).exists():
                    _move(saved, target / CONFIG_DIRNAME)

        self.discover()
        plugin = self.plugins.get(meta.pid)
        if plugin is not None and not plugin.supported:
            # installed, but it will sit there greyed out. Saying so once
            # is friendlier than letting the user hunt for the tooltip.
            self.log(f"Plugins: '{meta.name}' installed but not usable here "
                     f"– {plugin.platform_note}")
        if plugin is not None and plugin.enabled and not plugin.loaded:
            self._load(plugin)
        self.log(f"Plugins: installed '{meta.name}' {meta.version} "
                 f"-> {target}")
        return plugin

    def _tmp_base(self):
        """Unpack next to the target so shutil.move() stays a rename and
        never has to copy across filesystems."""
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            return self.dir
        except Exception:
            return Path(tempfile.gettempdir())

    # -------------------------------------------------------- removal
    def uninstall(self, pid):
        """Unloads the plugin and deletes its folder for good."""
        plugin = self.plugins.get(pid)
        if plugin is None:
            return False
        self._unload(plugin)
        try:
            if plugin.folder.exists():
                _rmtree(plugin.folder)
        except Exception as e:
            self.log(f"Plugins: could not delete {plugin.folder}: {e}")
            return False
        # the settings lived inside the folder we just deleted
        self.settings.pop(pid, None)
        self.plugins.pop(pid, None)
        self._snap = None
        self.log(f"Plugins: removed '{plugin.name}'")
        return True
