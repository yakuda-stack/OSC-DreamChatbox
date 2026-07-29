"""
core/plugins.py – plugin discovery, activation and dispatch.

Plugins live in ``CONFIG_DIR/plugins/<plugin_id>/`` and consist of at
least a ``plugin.json`` manifest and the python file it points to::

    ~/.config/OSC-DreamChatbox/plugins/
        hello_world/
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

Placeholders: every plugin is addressable as ``{<plugin_id>}`` (its
get_text(), falling back to its get_lines()), and every key of
get_values() as ``{<plugin_id>_<key>}``. That works in the plugin's own
custom string, in the Apps custom strings, in All-in-one and in the
Personal Status texts.

Beyond the required keys, plugin.json may declare:

    "template":     default custom string, e.g. "\U0001F44B {hello_world}"
    "placeholders": {"mood": "what it means"}   – shown as a UI hint
    "global_placeholders": ["realtime"]  – claim these names WITHOUT the
                            id prefix, so {realtime} works everywhere. An
                            app value that is already filled always wins,
                            so a plugin can never hijack a built-in one.
    "settings":     [{"key": "greeting", "type": "text",
                      "label": "Greeting", "default": "Hi"}]

``settings`` entries (type text | bool | int) are rendered as real
widgets under the plugin's Settings expander, so an author gets a
config UI without writing a single line of Qt. The current values reach
the plugin as ``api.settings`` (a live dict) plus the on_settings hook.

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
from core.textutils import apply_template

MANIFEST_NAME = "plugin.json"
# per-plugin state lives in <plugin>/configs/config.json
CONFIG_DIRNAME = "configs"
CONFIG_NAME = "config.json"
SETTING_TYPES = ("text", "bool", "int")
# plugin ids are used as folder AND module names -> keep them boring
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MODULE_PREFIX = "dreamchatbox_plugin_"
# zip bomb / typo protection (uncompressed size of the whole archive)
MAX_UNPACKED_BYTES = 64 * 1024 * 1024


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
    template: str = ""             # default custom string from the manifest
    placeholders: dict = field(default_factory=dict)   # name -> description
    global_keys: list = field(default_factory=list)    # unprefixed names
    schema: list = field(default_factory=list)         # user-editable options
    enabled: bool = False          # effective state (central state file)
    module: object = None          # imported module while loaded
    api: object = None
    error: str = ""                # last import/hook error, shown in the UI

    @property
    def loaded(self):
        return self.module is not None

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
    extend it here instead of letting plugins poke at internals."""

    def __init__(self, manager, plugin):
        self._manager = manager
        self._plugin = plugin
        self.app_name = APP_NAME
        self.app_version = VERSION
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

    def ensure_data_dir(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


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
        entry = {"enabled": False, "line": True, "custom": False,
                 "template": "{%s}" % pid, "options": {}}
        self.settings[pid] = entry
        return entry

    def options(self, pid):
        """Option values of one plugin, schema defaults filled in. Returns
        the live dict – api.settings points at this very object."""
        opts = self.entry(pid)["options"]
        plugin = self.plugins.get(pid)
        for item in (plugin.schema if plugin else []):
            if item["key"] not in opts:
                opts[item["key"]] = item["default"]
        return opts

    def _changed(self, pid):
        """Persist one plugin's config and drop the cached snapshot."""
        self._snap = None
        self._write_config(pid)

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

    def set_option(self, pid, key, value):
        """Stores one option value and notifies the plugin. The options
        dict is mutated in place, so api.settings sees it immediately."""
        opts = self.options(pid)
        opts[str(key)] = value
        plugin = self.plugins.get(pid)
        if plugin is not None and plugin.loaded:
            self._safe_call(plugin, "on_settings", opts)
        self._changed(pid)

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
        entry = {
            "enabled": bool(data.get("enabled", plugin.default_enabled)),
            "line": bool(data.get("line", True)),
            "custom": bool(data.get("custom", False)),
            "template": (str(data.get("template") or "").strip()
                         or plugin.template),
            "options": (dict(data["options"])
                        if isinstance(data.get("options"), dict) else {}),
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
            plugin.config_file.write_text(json.dumps(entry, indent=2,
                                                     ensure_ascii=False))
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
            template=template,
            placeholders={str(k): str(v) for k, v in placeholders.items()},
            global_keys=global_keys,
            schema=PluginManager._parse_schema(data.get("settings")),
        )

    @staticmethod
    def _parse_schema(raw):
        """Validates the optional "settings" list from plugin.json. Bad
        entries are dropped instead of raising – a typo in one option
        must not make the whole plugin uninstallable."""
        if not isinstance(raw, list):
            return []
        out = []
        seen = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            kind = str(item.get("type", "text")).strip().lower()
            if not key or key in seen or kind not in SETTING_TYPES:
                continue
            seen.add(key)
            entry = {
                "key": key,
                "type": kind,
                "label": str(item.get("label") or key),
                "hint": str(item.get("hint") or ""),
            }
            if kind == "bool":
                entry["default"] = bool(item.get("default", False))
            elif kind == "int":
                entry["default"] = int(item.get("default", 0) or 0)
                entry["min"] = int(item.get("min", 0) or 0)
                entry["max"] = int(item.get("max", 999) or 999)
                if entry["max"] < entry["min"]:
                    entry["min"], entry["max"] = entry["max"], entry["min"]
                entry["default"] = max(entry["min"],
                                       min(entry["max"], entry["default"]))
            else:
                entry["default"] = str(item.get("default", ""))
            out.append(entry)
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
        sys.modules.pop(MODULE_PREFIX + plugin.pid.replace("-", "_"), None)
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
        return [p for p in self.plugins.values() if p.enabled and p.loaded]

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
        frame no matter how many places ask for its values."""
        self._snap = None

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

    def values(self):
        """Flat placeholder dict for apply_template(): ``{<id>}`` for each
        plugin plus ``{<id>_<key>}`` for everything get_values() returned.
        Namespacing by id keeps two plugins from fighting over a key."""
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

    def render_lines(self):
        """The lines plugins contribute to the chatbox. With the custom
        string on, the plugin's own output is replaced by the user's
        template – exactly like the Apps cards work."""
        vals = self.values()
        lines = []
        for plugin in self._active():
            data = self.snapshot().get(plugin.pid, {})
            entry = self.entry(plugin.pid)
            if not entry["line"]:
                continue   # placeholder-only: values yes, own line no
            if entry["custom"] and entry["template"].strip():
                text = apply_template(entry["template"], vals)
                if text:
                    lines.extend(text.split("\n"))
            else:
                lines.extend(data.get("lines", []))
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

            with tempfile.TemporaryDirectory(dir=str(self._tmp_base())) as tmp:
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
                    shutil.move(str(keep), str(saved))
                if target.exists():
                    shutil.rmtree(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                if saved is not None and not (target / CONFIG_DIRNAME).exists():
                    shutil.move(str(saved), str(target / CONFIG_DIRNAME))

        self.discover()
        plugin = self.plugins.get(meta.pid)
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
                shutil.rmtree(plugin.folder)
        except Exception as e:
            self.log(f"Plugins: could not delete {plugin.folder}: {e}")
            return False
        # the settings lived inside the folder we just deleted
        self.settings.pop(pid, None)
        self.plugins.pop(pid, None)
        self._snap = None
        self.log(f"Plugins: removed '{plugin.name}'")
        return True
