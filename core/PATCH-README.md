# v1.3.2 drop-in

Based on v1.3.1 and containing the earlier v1.3.2 drop-in as well. Copy
over the tree, keeping the paths:

```
core/constants.py          (changed)  VERSION -> "v1.3.2"
core/boxstyle.py           (NEW)      Custom Box templates + line building
core/emojis.py             (NEW)      emoji palette, 10 categories
ui/ui_main.py              (changed)  category emoji picker, font fallback
core/textstyle.py          (NEW)      superscript / subscript
core/textutils.py          (changed)  {box_start} / {box_stop} aliases
core/plugins.py            (changed)  plugin settings: group / choice
ui/pages/custom_box.py     (NEW)      the Custom Box card
ui/pages/apps_page.py      (changed)  card added, value dict split out,
                                      Parameters list
ui/pages/plugins_page.py   (changed)  renders the new setting types,
                                      refreshes the Parameters list
ui/mainwindow.py           (changed)  mixin, clock timer, payload framing
ui/config_mixin.py         (changed)  defaults + validation + migration
README.md                  (changed)  Custom Box section, structure
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

### What a fresh install gets

```
╔═══ 🕐 09:05 🕐 ═══╗
talk to me
╚═ OSC-DreamChatbox ═╝
```

Double frame, top width 7 with `🕐{box_clock}🕐`, bottom width 3 with
`OSC-DreamChatbox`, alignment off (the two widths are deliberately
different), realtime clock on. The widths are short on purpose: a frame
line wide enough to wrap in the chatbox turns one line into two. A card with thirteen switches and an empty
preview teaches nobody what it does.

**An existing config does not grow a frame on update.** A config written
before v1.3.2 has no box keys, so it would inherit the new
`box_active: True` and change somebody's chatbox without being asked.
`load_config()` checks `stored` for the key: present, or no config file
at all, means the default applies; absent from an existing file means the
card comes up switched off - but filled in with everything above, so
turning it on is one click and looks like a new install.

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

### The preview wraps like the chatbox

The preview used to show the raw payload, so a line too wide for the
VRChat chatbox looked right in the app and arrived as two lines in the
headset - the one thing a preview exists to prevent.

`textutils.wrap_cells()` soft-wraps by character **cells** rather than
count, so a line of emoji breaks earlier than a line of letters. It
breaks between words where it can and inside a word only when a single
word is wider than the line - which is exactly what a frame line is, one
unbreakable run of box characters. The counter reports the result:

```
64/144  ·  ⤶ 1 line wrap
```

That deserves its own note because the character counter stays green
while it happens: wrapping costs no characters, it costs a line.

`constants.CHATBOX_WRAP_CELLS` is an **estimate** and documented as one.
The chatbox font is not monospaced, so nothing short of rendering it can
be exact; the value is there to show that a line *will* break, not to
predict where. One constant to tune if the preview and the headset
disagree.

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
