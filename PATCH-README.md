# v1.3.2 drop-in

Based on v1.3.1 and containing the earlier v1.3.2 drop-in as well. Copy
over the tree, keeping the paths:

```
core/constants.py          (changed)  VERSION -> "v1.3.2",
                                      PLUGIN_TEMPLATE_URL
core/boxstyle.py           (NEW)      Custom Box templates + line building
core/emojis.py             (NEW)      emoji palette, 10 categories
ui/ui_main.py              (changed)  category emoji picker, font fallback
core/textstyle.py          (NEW)      superscript / subscript
core/textutils.py          (changed)  {box_start} / {box_stop} aliases
core/plugins.py            (changed)  plugin settings: group / choice,
                                      plugin API 2 (see Part 7)
core/plugin_store.py       (changed)  skips store entries this build
                                      cannot run
ui/pages/custom_box.py     (NEW)      the Custom Box card
ui/pages/apps_page.py      (changed)  card added, value dict split out,
                                      Parameters list
ui/pages/plugins_page.py   (changed)  renders the new setting types,
                                      refreshes the Parameters list,
                                      embeds a plugin's own widget,
                                      "Write a plugin" button
config/plugins.json        (changed)  store catalogue: OSCLeash, Social
                                      Media, Stream Stats in, hello_world
                                      out (it no longer exists in the
                                      plugin repository)
ui/mainwindow.py           (changed)  mixin, clock timer, payload framing
ui/config_mixin.py         (changed)  defaults + validation + migration
README.md                  (changed)  Custom Box section, structure,
                                      the new plugin template
CHANGELOG.md               (changed)  v1.3.2 block extended
```

`VERSION` is bumped in this drop-in - it was left out of the previous one
on purpose and is now set, so nothing is left to do by hand.

No new dependency (`core/boxstyle.py` is stdlib only), no config
migration that touches existing values, and every manifest that exists
today parses and renders exactly as before.

---

## Part 1 - Custom Box

A new card on the **Apps** page, below All in one. Switch it on and one
line is hung above everything the app sends and one below it:

```
┌──────┐            ┌─── 18:01 ───┐
now playing …  ->   now playing …
└──────┘            └─── 68 % ───┘
```

It sits below All in one because that is the order it works in: All in
one decides *what* is sent, the box only frames whatever came out of it.

### What the card ships with

```
╔═══ 🕐 09:05 🕐 ═══╗
talk to me
╚═ OSC-DreamChatbox ═╝
```

Double frame, top width 7 with `🕐{box_clock}🕐`, bottom width 3 with
`OSC-DreamChatbox`, alignment off (the two widths are deliberately
different), realtime clock on. A card with thirteen switches and an empty
preview teaches nobody what it does.

**`box_active` defaults to False.** How wide a frame line can get before
the VRChat chatbox breaks it depends on the font and on which characters
are on the line - box-drawing characters come out far wider than letters
- and nothing in the config can know that. It is set once, by eye,
against the game, and once set it stays set. Shipping it on would mean
shipping a frame that splits on somebody's setup and looks broken out of
the box. Everything else is filled in, so switching it on gives a working
frame to adjust from rather than a blank card.

### The card

| Control | What it does |
| --- | --- |
| **Template** | dropdown, 12 presets + the one you build yourself |
| **Align top & bottom** | pads the shorter line so both come out even |
| **Show top / bottom line** | each line switchable on its own |
| **Width** (per line) | fill characters for THAT line (0-40) |
| **Middle** (per line) | `None` / `Clock` / `Custom` |
| **Text** (per line) | the custom middle, with all AIO placeholders |
| **Realtime clock** | gives the clock its own tick (off by default) |
| **Format** | `18:01`, `18:01:47`, `6:01`, `6:01 PM` |

The twelve presets are Light, Heavy, Double, Rounded, Dashed, Blocks,
Rule, Corners, Stars, Hearts, Arrows and Sparkles. They live in a dropdown
that shows each frame next to its name - a row of numbered buttons would
have said "7" and nothing else, so picking one would have meant clicking
through all twelve to see what they look like. The **C** slot exposes
the six strings a template actually is - left cap, fill, right cap, for
each of the two lines - so any frame is a few characters away. A cap may
be empty (that is the *Rule* template); the fill may not, because the
width slider would then do nothing.

### The middle text

The fill is split evenly around it, which is what turns `┌──────┐` into
`┌─── 18:01 ───┐`. **Each line has its own width**, because the two
middle texts are rarely the same length - a short clock on top and a long
hardware line underneath need different amounts of fill to end up looking
like one box:

```
┌── 19:53 ──┐                        top width 4
now playing - some song
└────── cpu 68% | gpu 71C ──────┘    bottom width 12
```

The card carries the same **Parameters** list All in one has, because a
middle text is rendered against the identical value dict - plugins
included. `AppsPageMixin.register_parameter_list()` takes a layout and
keeps it filled, so the two cards share one builder instead of two
hand-kept lists that can drift apart.

**Align top & bottom** is for the other case: it pads the shorter of the
two *rendered* lines until they match. It only ever adds fill, never
trims, so the widths stay the starting point - and for two deliberately
different lines like the ones above, switch it off. **Custom** runs through the same template engine All
in one uses, so `{cpu_usage}`, `{title}`, `{gpu_temp}`, the live info and
every active plugin work in the frame. `{box_clock}` is the clock from
the format dropdown. A middle that renders to several lines is folded
back into one - a frame line is one line by definition.

### `{box_start}` / `{box_stop}`

The way back out of the card: put them into an **All in one** string and
the frame lines land where you wrote them instead of being wrapped around
the whole message.

```
{box_start} \n {text} \n {box_stop}
```

They resolve whether or not the card is Active, so All in one can use the
frame with the automatic wrapping switched off entirely. When the card
*is* active, a string that places a line itself does not get that line
added a second time (`box_placed_manually()` checks the AIO string that
is on screen right now, rotation included).

### The clock toggle

The tick is the only thing in this card that costs anything, so it is a
toggle rather than something that happens to you:

* **off** - the frame is rebuilt when something else changes, so a clock
  can sit up to one send interval behind
* **on** - its own tick, 2 s for a format without seconds and 1 s for one
  with them, and it compares the rendered string before refreshing. A
  clock that changes once a minute causes one refresh a minute, not sixty

The timer only runs while the card is Active **and** a line actually
shows a clock. That includes `{box_clock}` inside a **Custom** middle,
not just the Clock middle mode - the default top line is exactly that
shape, and checking only the mode left the switch on and doing nothing.
`_CLOCK_RE` also covers `{realtime}` and its aliases. Everything else
leaves the timer stopped.

On by default, because the default top line is a clock and a clock that
only moves when something else happens looks broken. Replace that line
with something static and switching the toggle off stops the tick.

### Implementation notes

* `core/boxstyle.py` - `BOX_TEMPLATES`, `CUSTOM_BOX_INDEX`,
  `build_line()`, `render_pair()` (incl. the aligner), `clock_text()`
  and `cells()`, a rough display width via `east_asian_width` so a frame
  of wide characters can be aligned against a narrow one. Stdlib only.
* `ui/pages/custom_box.py` - the card, the handlers, `box_lines()`,
  `_box_tick()` and `_apply_custom_box()`.
* `ui/pages/apps_page.py` - the All-in-one value dict moved out of
  `build_aio_lines()` into **`_template_values(probe)`**, because the box
  needs exactly the same placeholders. One builder means the frame can
  never know a placeholder All in one does not. `current_aio_template()`
  is new and used by both.
* `ui/mainwindow.py` - `CustomBoxMixin` in the MRO, the `box_timer`, and
  `_apply_custom_box()` as the last step of **both** branches of
  `build_payload()` - which is what makes the top line the first line of
  the message in AIO mode and in normal mode alike.
* `ui/config_mixin.py` now keeps the parsed file in `stored` next to
  `defaults`, because after the `update()` a default value is
  indistinguishable from a stored one - and a migration has to tell "the
  user never had this key" apart from "the user set it to the number the
  default happens to be". First user: the single `box_width` of the
  earlier build becoming `box_width_top` / `box_width_bottom`. The old
  key is dropped once carried over.
* An empty payload is not framed. With every app quiet there is nothing
  to put a box around, and an empty frame is not a smaller message.

### One caveat, on purpose

`apply_template()` strips leftover separators (`|`, `:`, `-`) from the
ends of a line, so a frame whose fill is a plain ASCII `-` survives the
direct wrapping but is stripped when routed through `{box_start}` in an
All-in-one string. The hint under the custom fields says so. Every preset
uses box-drawing characters and is unaffected.

---

## Part 2 - MediaPlay idle symbol

The MediaPlay line used to disappear entirely when nothing was playing.
On a two-line chatbox that reads as "the app stopped working", not as
"no song", so it now shows one character instead.

* `media_idle` (bool, default **on**) and `media_idle_text` (default
  `\u23F8`) in the config, with a checkbox and a text field plus emoji
  picker under the MediaPlay options.
* `_media_idle_line()` is the single answer, and `build_media_lines()`
  returns it from all three places that can end up with nothing: no
  player at all, a custom string that rendered empty, and a player where
  the checkboxes or an empty title left no parts. From the chatbox's side
  those are the same situation, so they give the same output.
* All in one never calls `build_media_lines()`, so it handles the case
  itself. `build_aio_lines()` renders the template **one line at a
  time** - the output is identical, because `apply_template()` cleans per
  line anyway, but it keeps the link between an output line and the
  template line it came from. A template line that `_line_is_media()`
  recognises (aliases resolved, `{super/...}` markers skipped) and that
  rendered to nothing means there is no song, so it is answered with the
  symbol instead of being cleaned away:

  ```
  {box_start}\n{text}\n {artist} : {title} |\n {bar}\n {box_stop}

  ┌──────┐        ┌──────┐
  talk to me      talk to me
  ⏸         ->    Artist : Song
  └──────┘        0:30 [███░░░] 3:00
                  └──────┘
  ```

  Only the first such line answers, or a title + bar + lyrics layout
  would stack three identical symbols.
* **`{media_idle}`** in `_template_values()` remains for placing it by
  hand - the symbol while nothing plays, `None` (= empty) otherwise, so
  `{media_idle}{artist} : {title}` puts it on the same line.
* Off gives exactly the old behaviour, so anyone who liked the vanishing
  line keeps it with one click.

---

## Part 3 - the emoji picker

30 icons became 1010, in ten categories (Smileys, People, Hearts,
Animals, Nature, Food, Activities, Travel, Objects, Symbols) with a tab
row to switch between them. The palette is plain data in
`core/emojis.py`; the picker in `ui/ui_main.py` renders it.

**What was left out, and why.** No ZWJ sequences, no flags, no skin tone
modifiers. A "family" emoji is five codepoints joined by zero-width
joiners and a flag is two regional indicators - VRChat's chatbox font
renders a good part of them as tofu, and where it does not, the sequence
still costs its full length against the 144 characters. Single codepoints
are used wherever one exists.

**What was kept, and why.** Variation selectors, where the character
needs one: `\u2764` and `\u2764\uFE0F` are different strings and many fonts draw
the older monochrome glyph for the first. That makes 57 of the 1010
entries two characters wide instead of one, so `emojis.cost()` exists and
every button carries it in its tooltip - with 144 characters to spend,
"this one costs double" is worth knowing before picking it.

**One category at a time, built on first open.** A thousand
QPushButtons constructed up front would be paid for on every start by
everyone, including the people who never open the picker. One category
exists at startup; the remaining nine cost 0.1 s in total and only if
visited.

**Search.** The terms are `unicodedata` names, built into an index on the
first search rather than at import. Every entry has an official name and
they are usually what someone would type (FIRE, ROCKET, DOG FACE), so a
hand-written keyword table would only be a second thing to keep in sync.
`ALIASES` covers what Unicode has no word for and what it has no German
for - `lol`, `pc`, `gpu`, `cpu`, `ram`, `fps`, `vrc`, `afk`, `herz`,
`feuer`, `musik`, `katze`, `wut` - short on purpose.

All query words must match, so a second word narrows. Whole-word matches
are returned before substring ones: `lol` is a substring of LOLLIPOP and
`pc` of CUPCAKE, and without the ranking the obvious answer sits under
the sweets. The results grid keeps one pool of buttons and relabels it,
because rebuilding a grid per keystroke is what makes a search box feel
broken - ten keystrokes cost 4 ms.

`EMOJIS` still exists as a flat list for anything that imported it, with
the handful of cross-category repeats (a heart is both a heart and a
symbol) dropped.

---

## Part 4 - "Parameters" under All in one

A second expander below the All-in-one Settings block, holding the whole
placeholder vocabulary. It exists because the paragraph above the string
had grown into a wall of grey text nobody reads, and because half the
vocabulary lived on the Plugins page - so writing an AIO string meant
switching pages to look up what a plugin was called.

**Software parameters** - everything the app itself produces, grouped the
way the UI is grouped: Personal Status, MediaPlay, Hardware, Live info,
Custom Box, formatting. Each group gets a one-line note where it is not
obvious, e.g. that `{temp_icon}` in the string makes the temperatures drop
their unit. The table lives in `AppsPageMixin.SOFTWARE_PARAMETERS` as
plain data - a new placeholder is one line there and nothing else.

**External parameters** - every installed plugin with its `{<id>}`, its
`{<id>_<key>}` values and any name the manifest claimed unprefixed via
`global_placeholders`. Inactive and unsupported plugins are listed too and
marked as such, because "why is this placeholder empty" is exactly the
question the list is there to answer.

The labels are selectable, so a placeholder can be copied straight out of
the list. `register_parameter_list(layout)` hands a layout over to be filled and
kept current; `refresh_parameter_lists()` rebuilds every registered one.
It is called from two places: when a block is opened (so a plugin
installed while the app is running appears without a restart) and at the
end of `refresh_plugin_list()` (so a rescan, install or enable/disable is
reflected immediately). Two cards register today - All in one and the
Custom Box - and `refresh_aio_parameters()` is kept as a thin alias.

`make_settings_expander()` and `set_expanded()` grew an optional `label`.
It was hard-wired to "Settings", which is right for every existing caller
and wrong for a reference list, so the default leaves all of them
untouched.

---

## Part 5 - plugin settings UI

Unchanged from the previous drop-in: `group`, `choice`, `depends_value`
and `secret` in `plugin.json`. See the v1.3.2 block in `CHANGELOG.md`.

## Part 6 - superscript / subscript (`core/textstyle.py`)

The three styles (`normal`, `super`, `sub`) per Personal Status text, on
the GPU/CPU name and on the music timer are unchanged from the previous
drop-in, `_"word"_` still keeps a word out of the conversion.

**New: the same thing inline, in any custom string.**

```
GPU {gpu_usage} {super/"vram"} {vram_usage}   ->   GPU 68% ⱽᴿᴬᴹ 9/16GB
```

A dropdown styles a whole field, which is the wrong unit for a string you
built yourself - the Hardware custom string is one field but five values.
The markers style one part of it instead.

* Implemented in `apply_template()`, not per card, so every custom string
  has it for the same reason and with the same syntax: Hardware, All in
  one, MediaPlay, the Personal Status texts, a Custom Box middle text and
  a plugin's own template.
* `rep()` recognises a marker via `textstyle.is_inline_marker()` and hands
  it through untouched - otherwise it would be looked up as a placeholder
  name, missed, and deleted. `textstyle.apply_inline()` then resolves it,
  *after* the substitution, so the content can be a placeholder:
  `{super/{cpu_temp}}` styles whatever the value turned out to be. The
  nesting works because `\{([^{}]+)\}` cannot match across the inner
  braces and so replaces the inner one first.
* Quotes are optional and stripped when present. They are the only way to
  write a word with a trailing space, since everything outside them is
  trimmed.
* Aliases: `{sup/}`, `{superscript/}`, `{subscript/}`, case-insensitive.
  `_"keep me"_` works inside a marker too.
* Unmappable characters pass through unchanged, as everywhere else -
  superscript has no `q`, subscript is missing about half the alphabet.
  Spelled out in the hint under the Hardware custom string and in the
  Parameters list.

## Part 7 - plugin API 2

The plugin system stops being a thing plugins have to match exactly and
becomes a contract that survives both sides being updated at different
times. `core/plugins.py`, `core/plugin_store.py`,
`ui/pages/plugins_page.py`. `ui/mainwindow.py` is **not** touched.

Nothing an installed plugin does changes: a manifest without the new
keys is plugin API 1 and behaves exactly as before.

### Why a number that is not the app version

`PLUGIN_API_VERSION = 2` lives in `core/plugins.py`. The app version is
a release, the API number is a promise: once v1.3.2 is published, API 2
means what it means today. New abilities arrive as additional capability
strings, which costs nothing because `api.supports()` answers `False`
for anything it has never heard of. The number only rises when a plugin
must be able to *rely* on something new.

### Version negotiation

```json
{ "api": 2, "min_app": "v1.3.2" }
```

A plugin asking for more than the build provides is listed, greyed out
and **not imported** - the check sits in `_load()`, before the import,
and the reason lands in the tooltip and the info popup. It used to
import fine and then raise on the first call into something that did not
exist yet, once per frame, into the debug console.

`min_app` is a hint for the user and is never parsed for a decision -
only the number is. The store does the same check in `StoreEntry`, so an
install that would end in a greyed out row is not offered in the first
place.

Only declare `"api"` when the plugin genuinely cannot work without it.
For everything else there is feature detection:

```python
if api.supports("api.set"):
    api.set("binary", found)
else:
    _session_only = found          # older app: remember it for now
```

`api.supports()` also answers `"hook.<name>"` and `"settings.<type>"`.
This build: `settings.text` `settings.bool` `settings.int`
`settings.slider` `settings.choice` `settings.path` `settings.emoji`
`settings.group` `settings.secret` `settings.depends` `settings.depends_value`
`settings.action` `settings.label`
`settings.unsupported_passthrough` `widget` `events` `tick` `api.set`
`api.refresh` `api.data_dir` `manifest.extra`.

### New setting type: `path`

A text row with a file picker next to it, because a path field without
one is unusable on Windows - nobody types
`C:\Users\…\AppData\Local\Programs\OSCLeash\OSCLeash.exe` by hand.

```json
{"key": "binary", "type": "path", "label": "OSCLeash path",
 "mode": "file", "placeholder": "auto - leave empty to search",
 "filters": ["OSCLeash (OSCLeash OSCLeash*.AppImage OSCLeash.exe)",
             "AppImage (*.AppImage *.appimage)"]}
```

* `mode`: `"file"` (default) or `"dir"`.
* `filters`: Qt name filters, files only. `All files (*)` is appended
  unless the plugin already offers a way past the filter - an AppImage
  renamed by the browser or a wrapper script has to stay reachable.
* `placeholder`: greyed hint text while the field is empty.

`QFileDialog` gives the native dialog on Windows and the platform one on
Linux, so nothing in the app has to know which is which. The dialog
opens where the field already points (the folder itself when the value
is one, its parent when it is a file, `$HOME` when the field is empty or
the path is gone) - the difference between one click and hunting through
the tree again.

Typing stays possible on purpose: a path on a share, a path that does
not exist yet, or a pasted one cannot be reached through a dialog. The
value is stored exactly as entered - never resolved, never checked for
existence, because a config carried to another machine must not be
silently "corrected".

### New setting types: `action` and `label`

```json
{"key": "reset", "type": "action", "label": "Cached data",
 "button": "Clear now", "style": "danger"}

{"key": "status", "type": "label", "label": "State", "default": "idle"}
```

`action` is a button. It holds no value and never reaches
`config.json` - `iter_settings()` skips it, so `options()` does not
invent a key for it. Pressing it calls the plugin's `on_action(key)`
through the usual `_safe_call()`, and a string returned by the hook is
shown next to the button. `style` is `normal | primary | danger`.

`label` is a read-only line whose text is an ordinary option value. That
sounds pointless until you combine it with `api.set()`: a plugin gets a
live status line inside its settings card without building a widget at
all, which is the common case that `build_widget()` was too big a hammer
for.

Between them these two close the gap that made `build_widget()` feel
mandatory: before, a plugin that just wanted one button had to ship a
whole Qt file.

### New setting type: `emoji`

```json
{"key": "icon", "type": "emoji", "label": "Icon", "default": "🐕",
 "placeholder": "none"}
```

A text row with `EmojiPopup` behind a 😀 button - the same picker the
Personal Status, MediaPlay, Hardware and Custom Box strings use, opened
through the existing `self.emoji_popup.open_for(edit, button)`. Nothing
new was built for it; the point is that a plugin icon is chosen the way
every other icon in the app is, instead of each plugin inventing its own
answer to "how do I type an emoji on this machine".

It stays a text field rather than a one-character one: an icon is often
two characters (a base emoji plus a variation selector, which the picker
tells you about in its tooltips), and a trailing space is sometimes
exactly what the author wanted.

### Nothing unknown is dropped any more

The part that actually makes this future-proof. A settings row of a type
this build does not know used to be a silent `continue` in
`_parse_schema()`; now it becomes `type: "unsupported"`, keeps its
default, and:

* the value is stored like any other, so `api.get()` returns it
* the row renders as a disabled 🔒 line naming what it needs
* the info popup lists the locked options

So a plugin may ship options this app cannot edit yet and still rely on
their values today. The same idea everywhere else:

```
extra manifest keys        -> Plugin.extra
extra keys on a row        -> item["extra"]
extra keys in config.json  -> entry["extra"], written back out untouched
```

That last one is the one that used to lose data: rewriting a config a
newer version had written silently deleted every setting made there.

`Plugin.supported` now means "runnable here" - platform **and** API -
with `platform_note` returning whichever reason applies. Both halves
stay available as `platform_ok` and `api_ok`, so the ten call sites in
`plugins_page.py` and the one in `apps_page.py` keep working unchanged.

### New hooks

```python
def on_tick():              # top of every chatbox frame, before get_values()
def on_event(name, data):   # anything the app announces
def build_widget(parent):   # -> QWidget, embedded under the plugin's settings
```

`on_tick()` rides on the existing `plugins.invalidate()` call at the top
of `build_payload()`, which is why `ui/mainwindow.py` needs no change. It
runs *before* the values are collected, so whatever it polled is in this
frame rather than the next. Anything that can block - network,
subprocess, a slow mount - still belongs in a thread.

`on_event()` is the extension point for everything that does not exist
yet. `self.plugins.emit("avatar.changed", {...})` reaches every active
plugin; one that does not know the name ignores it. No change in
`core/plugins.py` and none in any plugin. Only `app.shutdown` is emitted
so far, from `plugins.shutdown()` before teardown, so a plugin can flush
while the rest of the app is still standing. Adding more is a one-line
call each, at the place it belongs.

`build_widget()` covers what the settings schema cannot: a Start button,
a live log, a list the user adds rows to. The plugin returns a `QWidget`
and `_build_plugin_settings()` puts it under that plugin's options. It
goes through `_safe_call()` like every hook, and the page checks the
result really is a `QWidget`, so a plugin that returns nonsense loses its
panel and nothing else.

Two rules for the author, both learned the hard way in this codebase:

* the page rebuilds, and that deletes the embedded widget on the C++
  side while the python object survives. A cached widget has to be
  checked before it is handed back a second time:

  ```python
  if _panel is not None:
      try:
          _panel.isVisible()
      except RuntimeError:       # C++ object gone, wrapper left
          _panel = None
  ```

* import Qt inside `build_widget()`, not at module level, so a headless
  manager can still load the plugin.

### New on the api object

| Member | What |
| --- | --- |
| `api.api_version` | what the app speaks (2 here) |
| `api.supports(feature)` / `api.needs(n)` | feature detection |
| `api.set(key, value)` / `api.set_many(d)` | write your *own* settings, persisted |
| `api.refresh()` | ask for a fresh chatbox render |
| `api.data_path(*parts)` | a path inside `configs/`, parents created |

`api.set()` is for values the plugin discovers rather than the user
types - an autodetected path, a refreshed token, the size of its own
panel. It does **not** call `on_settings()` back, because a plugin
answering its own write is how you build an endless loop, and it pushes
the value into the widget on screen via `sync_plugin_option()`, with
signals blocked for the same reason.

**The thread part matters.** A plugin may call this from one of its
worker threads, and a Qt widget touched from a non-GUI thread is a
segfault, not an exception - the same class of bug as the `_log_signal`
fix in v1.0.8. `PluginManager._ui_call()` therefore hands every host
call to the window's event loop with the window itself as the context
object, which is what makes Qt run it in the GUI thread:

```python
QTimer.singleShot(0, self.host, run)
```

With no Qt at all (headless manager, tests) it runs inline.

### Writing a plugin - the short version

Hooks, all optional: `setup(api)`, `teardown()`, `get_text()`,
`get_lines()`, `get_values()`, `on_settings(opts)`, `on_text(text)`,
`on_tick()`, `on_event(name, data)`, `build_widget(parent)`. A hook that
raises is caught, logged and shown in the info popup.

Settings types: `text` `bool` `int` `slider` `choice` `path` `emoji`
`label` `action` `group`, with `depends` / `depends_value` for
conditional rows and `secret` for masked input.

`plugins/example_template/` is a working plugin that shows every one of
them next to every hook - the fastest way to start a new plugin is to
copy that folder and delete what is not needed. Keys are unique across the whole schema, groups included, because
option values live in one flat dict. Groups nest two levels.

Layout of a plugin:

```
oscleash/
    plugin.json      manifest
    main.py          hooks
    logo.png         optional, shown in the store
    configs/         created by the app - never ship this
```

`configs/` is the plugin's writable folder and survives an update from a
newer .zip, which is exactly why a plugin must not ship one: the
installer keeps the existing folder only when the archive has none.
Shipping it resets every setting the user made.

Checklist before publishing:

- [ ] `teardown()` stops every thread and child process
- [ ] no Qt import at module level, only inside `build_widget()`
- [ ] no widget touched from a worker thread
- [ ] `get_values()` returns `None`, not `""`, for unknown values -
      `apply_template()` drops a `None` together with its separators, so
      `"{x_name} | {x_count}"` leaves no stray `|`
- [ ] no `configs/` folder in the .zip
- [ ] `"api"` declared only for hard requirements, `api.supports()` for
      the rest
- [ ] the plugin still loads with every setting at its default

### Two fixes that came out of building a plugin against it

**Updating a plugin kept its old code.** `_unload()` popped only the
top-level module from `sys.modules`. A plugin of more than one file
imports its own parts as `<module>.panel`, `<module>.runner` and so on,
and those survived - so the next load built a fresh `main.py` around the
previous version's helpers. The plugin then showed its new manifest and
ran its old code, which is a confusing way to lose an afternoon. All
modules under the plugin's prefix are dropped now.

**The info popup says which systems a plugin supports**, `OS  Linux &
Windows` or just one of them, orange when it is not this machine. The
greyed out row answers only for the machine you are on, which does not
help when someone asks whether a plugin works on their side.

### The template and the store catalogue

`config/plugins.json` now lists **World Stats, OSCLeash, Social Media,
Stream Stats** and **example_template**. `hello_world` is out - it no
longer exists in the plugin repository, and a catalogue entry pointing
at a 404 shows up in the store as a broken card.

The catalogue is re-downloaded from `self_url` on every store refresh,
so AppImage and AUR users get the new entries without updating the app.
Checked against the live repository, all five resolve:

```
World Stats       v1.2.0  api=1     Social Media    v1.0.0  api=1
OSCLeash          v2.1.0  api=2     Stream Stats    v1.0.0  api=1
Example Template  v1.0.0  api=2
```

`PLUGIN_TEMPLATE_URL` in `core/constants.py` is the one place the
template address lives. The store page gained a **Write a plugin**
button that opens it directly, and both **Plugins & template** buttons
name it in their tooltip.

### What to check after applying

1. Every installed plugin still loads (`Plugins: loaded '<name>'` in the
   debug console) and its settings still show the values they had.
2. A manifest with `"api": 99` appears greyed out with a reason and is
   not imported.
3. A settings row with an invented type shows the 🔒 line, and the value
   is still in `configs/config.json`.
4. A plugin with `build_widget()` shows its panel inside its card.
5. A `path` row opens a file dialog on the folder button, on Windows and
   on Linux, and starts in the folder the field points at.
6. An `emoji` row opens the app's icon picker and inserts into that
   plugin's field, not into whatever was focused last.
7. Installing a newer .zip over a running plugin actually runs the new
   code - not just the new manifest.
