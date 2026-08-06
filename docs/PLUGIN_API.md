# OSC-DreamChatbox plugin API

**Current version: 2** (`core.plugins.PLUGIN_API_VERSION`)

A plugin is a folder under `~/.config/OSC-DreamChatbox/plugins/<id>/`
with a `plugin.json` and the python file it points at. Nothing else is
required.

```
oscleash/
    plugin.json      the manifest
    main.py          hooks
    logo.png         optional, shown in the store
    configs/         created by the app, never ship this
```

`configs/` is the plugin's own writable folder. It survives an update
from a newer .zip — which is exactly why a plugin must **not** ship one:
the installer keeps the existing folder only when the archive has none.

---

## Hooks

All optional. Implement what you need, ignore the rest.

| Hook | Purpose |
| --- | --- |
| `setup(api)` | after import; store the `api` object |
| `teardown()` | on disable and on exit; stop threads, close handles |
| `get_text()` | `str` → `{<id>}` |
| `get_lines()` | `list[str]` appended to the chatbox payload |
| `get_values()` | `dict` → `{<id>_<key>}` placeholders |
| `on_settings(opts)` | the user changed a setting |
| `on_text(text)` | last-chance filter on the final chatbox text |
| `on_tick()` | once per frame, before values are collected |
| `on_event(name, data)` | anything the app announces |
| `build_widget(parent)` | your own `QWidget`, embedded in the plugin card |

A hook that raises is caught, logged and shown in the plugin's info
popup. It can never take the chatbox down.

### `get_values()` and `None`

Return `None` for anything you do not know right now. `apply_template`
drops a `None` placeholder **together with its separators**, so
`"{x_name} | {x_count}"` never leaves a stray `|` behind. Returning `""`
does not do that.

### `on_tick()`

Runs at the top of every chatbox frame, before `get_values()`. For cheap
polling without a thread. Anything that can block — network, subprocess,
a file on a slow mount — belongs in a thread, not here.

### `build_widget(parent)`

For everything the settings schema cannot express: buttons that *do*
something, a live log, a list the user adds rows to.

```python
def build_widget(parent=None):
    from .panel import MyPanel          # import Qt lazily, not at module level
    return MyPanel(_api, parent)
```

Rules:

* Called from the GUI thread; build widgets only here.
* May be called **again** after the page rebuilds. The previous widget is
  deleted on the C++ side by then, so either build a fresh one or check
  the cached one is still alive:
  ```python
  if _panel is not None:
      try:
          _panel.isVisible()
      except RuntimeError:      # C++ object gone, python wrapper left
          _panel = None
  ```
* Never touch a widget from a worker thread. Poll from a `QTimer` in the
  GUI thread instead — a Qt widget touched from another thread is a
  segfault, not an exception.

### `on_event(name, data)`

The app announces things by name; you react to what you know and ignore
the rest. Never assume a name exists or that `data` has a key.

```python
def on_event(name, data):
    if name == "app.shutdown":
        _flush()
```

Names in this build: `app.shutdown`. More will be added; that is the
point of the hook.

---

## The `api` object

| Member | Since | What |
| --- | --- | --- |
| `api.log(msg)` | 1 | into the app's debug console, prefixed with the id |
| `api.get(key, default)` | 1 | one of your declared settings |
| `api.settings` | 1 | the live dict; the app mutates it in place |
| `api.plugin_dir` | 1 | your folder (read-only in spirit) |
| `api.data_dir` | 1 | `configs/`, writable, survives updates |
| `api.ensure_data_dir()` | 1 | same, created |
| `api.host` | 1 | the MainWindow, or `None` headless |
| `api.app_name` / `api.app_version` | 1 | |
| `api.api_version` | 2 | what the app speaks (`2` here) |
| `api.supports(feature)` | 2 | feature detection, see below |
| `api.needs(n)` | 2 | `True` when `api_version >= n` |
| `api.set(key, value)` | 2 | write one of *your* settings, persisted |
| `api.set_many(dict)` | 2 | |
| `api.refresh()` | 2 | ask for a fresh chatbox render |
| `api.data_path(*parts)` | 2 | a path inside `data_dir`, parents created |

`api.set()` is for values *you* discover — an autodetected binary, a
refreshed token, the size of your own window. It does **not** call your
`on_settings()` back (no loops), and it updates the widget the user is
looking at, even when you write from a worker thread.

---

## Writing one plugin for several app versions

Do not check `api.app_version`. Check the feature:

```python
def setup(api):
    if api.supports("api.set"):
        api.set("binary", found)
    else:
        _session_only = found          # older app: remember it for now
```

`api.supports()` also answers `"hook.<name>"` and `"settings.<type>"`.
Capabilities in this build: `settings.text` `settings.bool`
`settings.int` `settings.slider` `settings.choice` `settings.group`
`settings.secret` `settings.depends` `settings.depends_value`
`settings.unsupported_passthrough` `widget` `events` `tick` `api.set`
`api.refresh` `api.data_dir` `manifest.extra`.

### Declaring a minimum

```json
{ "api": 2, "min_app": "v1.3.2" }
```

Only declare `"api"` when the plugin genuinely **cannot** work without
it. An app that speaks less refuses to import the plugin and greys the
row out with the reason — which is correct for a hard requirement and
needlessly hostile for something you could have feature-detected.
No `"api"` key means 1, which is why every existing manifest keeps
working untouched.

---

## What happens to things the app does not understand

Nothing is silently dropped. That is the contract in both directions:

| Written by a newer app | What an older app does |
| --- | --- |
| a settings row of an unknown type | keeps the row and its default; `api.get()` returns the value as normal; the UI shows a disabled 🔒 line naming the missing version |
| extra keys on a settings row | kept in `item["extra"]` |
| extra keys in `plugin.json` | kept in `Plugin.extra` |
| extra keys in `configs/config.json` | kept and written back out untouched, so a downgrade does not delete settings made in the newer version |

So a plugin may ship options this app cannot edit yet, and still rely on
their values today.

---

## Settings schema

Types: `text` `bool` `int` `slider` `choice` `group`.

```json
{"key": "mode", "type": "choice", "label": "Data source",
 "default": "keyless",
 "choices": [{"value": "keyless", "label": "Keyless"},
             {"value": "api", "label": "Official API"}]}

{"key": "token", "type": "text", "label": "API key", "secret": true,
 "depends": "mode", "depends_value": "api"}

{"key": "twitch", "type": "group", "label": "Twitch", "expanded": false,
 "items": [ ...more settings... ]}
```

* `depends` hides a row while the named setting is falsy;
  `depends_value` (one value or a list) compares instead.
* `secret` masks the input. It is shoulder-surfing protection, not
  encryption — the value still sits in `config.json` as plain text, so
  say so in the `hint`.
* Keys are unique across the **whole** schema, groups included: option
  values live in one flat dict.
* Groups nest two levels deep. Deeper rows are kept as unsupported
  placeholders rather than dropped.

---

## Manifest

```json
{
  "name": "OSCLeash", "id": "oscleash", "version": "1.1.0",
  "author": "yakuda", "main": "main.py", "image": "logo.png",
  "description": "...", "summary": "one line for the store",
  "Github": "github.com/yakuda-stack",
  "enabled": false,
  "api": 2, "min_app": "v1.3.2",
  "is_linux": true, "is_windows": true,
  "template": "🐕 {oscleash_name}",
  "placeholders": {"name": "what it means"},
  "global_placeholders": ["leash"],
  "settings": [ ... ]
}
```

`id` must match the folder name and the `[a-z0-9_-]` rule — it is used as
a python module name. `global_placeholders` claims names without the id
prefix; a built-in value always wins, so a plugin cannot hijack one.

---

## Checklist before publishing

- [ ] `teardown()` stops every thread and child process you started
- [ ] no Qt import at module level, only inside `build_widget()`
- [ ] no widget touched from a worker thread
- [ ] `get_values()` returns `None`, not `""`, for unknown values
- [ ] no `configs/` folder in the .zip
- [ ] `"api"` declared only for hard requirements, `api.supports()` for
      the rest
- [ ] the plugin still loads with every setting at its default
