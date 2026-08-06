## [v1.3.2] - 2026-08-03

### Added
- **MediaPlay: idle symbol between songs.** The line used to vanish when
  nothing was playing, which reads as "the app died" rather than "no
  song". Now a single character (`⏸` by default, editable, emoji picker
  next to it), switchable off for the old behaviour. Covers no player, a
  custom string that rendered to nothing, and a player with everything
  switched off. **All in one gets it automatically**: a template line
  that is about the song and rendered to nothing means there is no song,
  so it becomes the symbol instead of being cleaned away - only the
  first such line, so three song lines do not stack three symbols.
  `{media_idle}` still places it by hand.
- **Emoji picker: 30 icons -> just over a thousand**, in ten categories
  (Smileys, People, Hearts, Animals, Nature, Food, Activities, Travel,
  Objects, Symbols) with a tab row. Palette moved to `core/emojis.py`.
  No ZWJ sequences, flags or skin tones - VRChat's chatbox renders many
  of them as tofu and they cost their full length against the 144
  characters. Variation selectors are kept where a character needs one,
  so 57 entries cost 2 characters and every button says which in its
  tooltip. Categories build their buttons on first open, so startup is
  unaffected for anyone who never opens the picker.
- **Search box in the emoji picker.** Terms come from `unicodedata`, so
  they cannot drift from the palette, plus a short alias table for the
  shorthand Unicode has no word for and for German (`lol`, `gpu`, `ram`,
  `fps`, `vrc`, `herz`, `feuer`, `musik`, `katze`). Every query word must
  match, and whole-word hits rank above substring ones - otherwise `lol`
  buries the laughing face under LOLLIPOP.
- **Custom Box** - a new card on the Apps page, below All in one. Hangs
  one line above everything the app sends and one below it, so the
  chatbox reads as a closed box instead of a stack of loose lines.
  12 templates (Light, Heavy, Double, Rounded, Dashed, Blocks, Rule,
  Corners, Stars, Hearts, Arrows, Sparkles) plus a custom slot where you
  set the six characters a frame is made of, picked from a dropdown that
  shows each frame next to its name, and each line switchable on its own. **Width is set per line** - the two middle texts are rarely
  the same length, so a short clock on top and a long hardware line
  underneath can each get the fill they need. *Align top & bottom* pads
  the shorter line for when you do want them even, and only ever adds
  fill - so for two deliberately different lines, switch it off.
- **Middle text per line**: nothing, a clock (`┌─── 18:01 ───┐`, four
  formats), or your own string through the same template engine All in
  one uses - so `{cpu_usage}`, `{title}` and every active plugin work in
  the frame as well. The fill is split evenly around it.
- **"Parameters" under All in one** - a second arrow below Settings
  listing the whole placeholder vocabulary, so nobody has to walk to the
  Plugins page to find out what a plugin is called.
  **Software parameters** groups everything the app produces (Personal
  Status, MediaPlay, Hardware, Live info, Custom Box, `\n`);
  **External parameters** lists every installed plugin with its `{<id>}`
  and `{<id>_<key>}` values, inactive ones included and marked. Text is
  selectable, and the list rebuilds itself when the plugin list changes.
  The same list sits at the bottom of the Custom Box card - a box middle
  text takes the exact same placeholders, plugins included.
- **`{box_start}` / `{box_stop}`** place the two frame lines from inside
  an All-in-one string instead of having them wrapped around the whole
  message. They resolve whether or not the card is Active, and a string
  that places a line itself does not get that line added twice.
- **A fresh install arrives set up**: Double frame, live clock on top,
  `OSC-DreamChatbox` underneath, widths 7 / 3 - short on purpose, a
  frame line that wraps turns one line into two. An existing config does
  NOT grow a frame on update - it comes up switched off but filled in,
  so turning it on is one click.
- **Realtime clock toggle.** The clock tick is the only thing in the card
  that costs anything. Off, the frame follows the normal refresh; on, it
  gets its own tick - 2 s without seconds, 1 s with them - and only
  refreshes when the clock string actually changed. On by default
  because the default top line is a clock. The tick also recognises
  `{box_clock}` inside a Custom middle, not just the Clock mode.
- **Plugin settings: collapsible groups.** A manifest can wrap its
  settings in `{"type": "group", "items": [...]}`, which renders as a
  collapsible block inside the plugin's Settings expander. Groups may
  nest one level deep and start collapsed unless the manifest says
  `"expanded": true`.
- **Plugin settings: dropdowns.** The new `"type": "choice"` renders a
  combo box. The stored value is the choice's `value`, never its label,
  so a plugin author can rename a label without invalidating configs
  that already picked it. `"choices": ["a", "b"]` works as a short form.
- **Plugin settings: `depends_value`.** `depends` can now follow a
  dropdown instead of a checkbox: a row with
  `"depends": "mode", "depends_value": "official"` is visible while
  that choice is selected. A single value or a list of them.
- **Plugin settings: `"secret": true`** on a text row masks the input,
  for tokens and API keys.
- **Inline `{super/"word"}` / `{sub/"word"}` in every custom string.**
  `GPU {gpu_usage} {super/"vram"} {vram_usage}` comes out as
  `GPU 68% ⳽ᴿᴬᴹ 9/16GB`. Handled in `apply_template()`, so Hardware,
  All in one, MediaPlay, the status texts, a Custom Box middle and a
  plugin string all take it. Resolved after the placeholders, so the
  content can be one: `{super/{cpu_temp}}`. Quotes optional (and the only
  way to keep a trailing space); `{sup/}`, `{superscript/}` and
  `{subscript/}` work too.
- **Superscript / subscript** for the 20 Personal Status texts, the
  GPU/CPU name and the music timer (digits only). A word can be kept out
  of the conversion by wrapping it: `_"Quake"_`.

### Changed
- Option values are collected with the new `iter_settings()` walker, so
  defaults and stored values keep living in one flat dict no matter how
  the settings are grouped. Keys stay unique across the whole schema.
- The All-in-one value dict moved into `_template_values()` so the
  Custom Box renders against exactly the same placeholders.
- The stored config is kept alongside the defaults during load, so a
  migration can tell "the user never had this key" from "the user set it
  to the number the default happens to be". First user: the single
  `box_width` becoming `box_width_top` / `box_width_bottom`.
- An empty payload is not framed: with every app quiet, nothing is sent.

### Fixed
- **The preview wraps the way the chatbox wraps.** It showed the raw
  payload, so a line too wide for the VRChat chatbox looked fine in the
  app and arrived as two lines in the headset. Soft-wrapped by character
  cells, not count, and the counter reports it: `64/144 · ↶ 1 line
  wrap`. The character counter stays green during this - wrapping costs
  no characters, it costs a line. `CHATBOX_WRAP_CELLS` is an estimate
  and marked as one.
- **Windows: a plugin setting with an emoji in it was silently lost.**
  The plugin config was written with `ensure_ascii=False` and no
  explicit encoding, so Windows used cp1252 and raised on the first
  emoji - inside a `try` that logs and moves on, so nothing showed.
  Both config paths are pinned to UTF-8 now. Linux was never affected
  (UTF-8 locale).
- **Windows: `font-family: monospace` matched no font.** It is a
  fontconfig alias, so the Custom Box preview stopped lining up. Now
  the system fixed-width font, and `Consolas, monospace` in stylesheets.

### Notes
- Fully backwards compatible: manifests without groups or choices parse
  and render exactly as before, and a config written before v1.3.2 has
  no style and no box keys - so text comes up Normal, the frame comes up
  off, and nothing is migrated or reset.
- New files: `core/textstyle.py`, `core/boxstyle.py`,
  `ui/pages/custom_box.py`.
