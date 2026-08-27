# Changelog

All notable changes to OSC-DreamChatbox are documented here.

🟢 Windows Support: Complete & Stable (v.1.3.0)

🟢 Linux Support: Complete & Stable (v1.2.6)

## [v1.4.5] – 2026-08-26

**Flags in the icon picker, a status rotation that can run in order,
Hardware settings that stop being one long column, and a MediaPlay card
that is clickable again.**

### Added

**Personal Status can run its texts in order**

- A **Random order** checkbox on the Personal Status card, **on by
  default** — which is what the rotation always did, so no existing
  config changes behaviour. It sits between *Number of texts* and
  *Change text every*, which is the order the three are read in: how
  many texts, in what order, how long each one stays.
- Turn it off and the texts run **top to bottom** and start over: Text 1,
  Text 2, Text 3, Text 1 … Useful for anything where the order carries
  meaning and a shuffle does not, like a greeting followed by what you
  are doing followed by where to find you.
- **Empty fields are skipped either way.** Leaving a gap in the middle
  of the list while editing is normal, and a rotation that stopped on a
  blank Text 3 would look like the app had frozen.

**Pride and country flags**

- Two new categories in the icon picker: **Pride** and **Flags**. The
  rainbow and transgender flags, 149 country flags, plus the plain ones
  (🏁 🚩 🏳️ 🏴 🏴‍☠️).
- The picker is reachable from every text field that already had the 😀
  button, so this covers Personal Status, MediaPlay, Hardware, the Chat
  box, All-in-one and plugin settings.
- **Flags were deliberately left out until now**, and the reason has not
  gone away: a country flag is two characters of the chatbox's 144, the
  rainbow flag four and the transgender flag five, and whether they draw
  at all is up to VRChat's font. So the cost is shown rather than hidden
  — every button says what it costs, and both flag categories carry a
  line under the grid saying they may come out as letters.
- **Identities Unicode has no flag for** get their stripes as coloured
  hearts instead: bi, pan, lesbian, ace, non-binary, agender and
  aromantic. Those are ordinary hearts, so they render where a flag
  might not, and they cost one character per stripe.
- **Search works in German and English.** Unicode calls the German flag
  "REGIONAL INDICATOR SYMBOL LETTER D", which is not what anyone types,
  so the names come from a table: *deutschland*, *schweiz*, *türkei*,
  *trans*, *queer* and *pride* all find something now.

### Changed

**The Hardware settings are a grid**

- GPU, VRAM, CPU and RAM each get their own box, laid out **two by
  two**. The card was 883 pixels tall and is now 580 — a third shorter
  with nothing removed.
- Checkboxes sit **two per row** inside each box. The examples that used
  to be in the labels ("GPU usage  (e.g. GPU: 27%)") moved into
  tooltips, which is where something you read once belongs.
- **Custom name and its style share one row** under the component they
  belong to, indented under their checkbox.
- **Custom string got its own section**, and its two paragraphs of
  reference text are now a *Placeholders & text styles* panel that folds
  away. It used to sit on the card permanently in dim grey, competing
  with the settings around it.
- **Config & formatting** is a section at the bottom: the flame icon,
  the poll interval and the GPU backend line.
- On Windows, the advanced-temperature block moved out of the CPU box
  and under the grid. Three paragraphs of explanation in a half-width
  column would have been a stack of two-word lines.

**Greying that follows the setting it belongs to**

- The custom name field follows its own checkbox.
- The style dropdown does **not**, because it also styles the *detected*
  name — it only goes dead when neither a detected nor a custom name is
  going out.
- The custom string editor follows *Build my own layout*.

### Fixed

**MediaPlay: the Content and Playback settings were unusable with a
custom string on**

- Turning on the MediaPlay custom string greyed out the entire **Content**
  and **Playback time & progress** sections — Artist, Song title, Max
  length, the time format, the digit style, the songbar style and its
  size slider. None of them could be clicked, dragged or opened.
- That was wrong, because **every one of those settings still fed the
  custom string**. An unticked *Song title* leaves `{title}` empty, Max
  length still truncates, *With seconds* still picks between `1:18/3:47`
  and `0:01/0:03`, and the songbar style and size still build `{bar}`.
  Greying a control means it does nothing; these were doing their job
  and simply could not be reached.
- Both sections are **fully usable again**. When the custom string is on
  they show a line saying what changed: they still decide which values
  exist, they just no longer decide where things go.
- **Time position** stays greyed, because it is the one setting that
  genuinely does nothing in custom mode — merging the clock into the bar
  only happens while the standard layout builds the lines, and a custom
  string places `{bar}` and `{time}` itself. Its tooltip now says so.
- Lyrics was inconsistently left clickable while everything around it
  was not; the sections now behave the same way throughout.

- **Icon search gave up before reaching the last categories.** It
  stopped at the first 120 matches in palette order, so "japan" filled
  its results with 👹 and 🏣 and never reached the Japanese flag. The
  whole palette is searched now.
- **A duplicate entry in the search alias table** meant one of the two
  🎮 keyword sets was silently discarded.
- Variation selectors and regional indicators no longer contribute their
  Unicode names to the search index, where they put the words "letter"
  and "symbol" on a fifth of the palette and matched queries meant for
  something else.

## [v1.4.4] – 2026-08-26

**FPS moved into the World Stats plugin, the song line can be pinned to
one player, and the MediaPlay settings got a structure.**

### Added

**Choosing which player the song line comes from**

- A **Player** dropdown in the MediaPlay settings. The old rule was
  "first player that says Playing wins", which is right when one thing
  is playing and arbitrary when two are: leave Spotify paused mid-song
  and start YouTube Music, and which one showed up depended on the order
  the system happened to list players in — and changed between restarts.
- *Automatic* keeps the old behaviour and stays the default. Pick a
  player and it stays that player, paused songs included, since the card
  already shows those.
- A **Fall back to any other player** checkbox, on by default: closing
  Spotify lets the next player through, so the line keeps working. Turn
  it off and the line means the player you picked or it means nothing.
- The **YouTube Music desktop app and a music.youtube.com tab are
  separate entries**, because they behave differently and someone who
  picks one did not mean the other.
- Works on both platforms: MPRIS on Linux, the Windows media session on
  Windows.

**A live preview in the MediaPlay card**

- Shows the song line the way it will actually appear, updating as you
  tick things. While music is playing it is your song; otherwise a
  stand-in track, so the settings can be judged without starting music
  first.
- It renders through the same function that produces the real line. A
  second formatter written just for the preview would be right today and
  quietly wrong after the next change to the real one.
- The stand-in track never reaches LRCLIB. A made-up artist and title
  would otherwise be looked up on every keystroke in the custom string
  field.

### Changed

**Frame rate is a plugin now**

- Every FPS setting has left the Hardware card: the checkbox, the
  MangoHud folder, Auto-detect and the Check RTSS button. They live in
  **World Stats v1.5.0** under a *Frame rate* block.
- The reason is not tidiness. Everything else on that card reads
  `/proc`, `/sys` or a Windows counter — the operating system already
  knows those numbers. A frame rate only exists inside the process
  drawing it, so getting one means loading something **into the game**:
  a Vulkan layer on Linux, RTSS on Windows. That is a different kind of
  job, with different failure modes, and it was making the Hardware card
  carry a second personality.
- **Nothing was lost, and Linux gained something.** The plugin ships its
  own Vulkan layer that counts frames inside the game — no MangoHud, no
  CSV logging, no folder to find. MangoHud stays as an alternative
  source for anyone who already has it working. Windows reads RTSS as
  before, plus a few things the app never did, like noticing when RTSS
  is still reporting a game that has already closed.
- If you had FPS switched on, the app says so once in the log on the
  next start, along with your old MangoHud folder so it can be pasted
  straight into the plugin. `hw_fps` and `hw_mangohud_dir` are dropped
  from the config rather than left behind as settings nothing reads.
- `{fps}` is still a global placeholder, so **templates, AIO lines and
  Advanced Mode canvases keep working unchanged** once World Stats is
  installed and its Frame rate box is on. The `FPS` output on the
  *RAM & System* block stays wired up; only its description changed.

**The MediaPlay settings, rearranged**

- **Sections instead of one list**: *Preview*, *Player*, then *Content*,
  *Playback time & progress* and *Styling & custom layout*. The card had
  grown to around twenty controls in a single column under one "Show:"
  heading, and finding the songbar size meant scrolling past the lyrics
  folder picker.
- **The last three fold away behind an arrow**, collapsed on start like
  every other expander in the app. Most of what is in them is set once
  and never touched again — the songbar characters, the lyrics folder,
  the idle symbol.
- **Player sits directly under the preview and does not fold.** It is
  the one thing on this card that decides whether anything appears at
  all; everything below is about how the line looks. Somebody whose
  chatbox stayed empty should reach it without opening a section.
- **Sub-options are visibly attached to their parent.** Max length under
  Song title, the two Time options under Time, the whole songbar block
  under Songbar — each behind a rule down the left edge rather than a
  bare indent. With margin alone, two things at different depths look
  the same once the card is long enough.
- **Related fields sit side by side.** Songbar style, size and time
  position share a three-column grid; player and query interval share a
  row; "With seconds" and the digit style are on one line.
- **Ticking Custom string now greys out Content and Playback time.** A
  custom layout replaces those parts rather than adding to them, and the
  card used to leave them looking live while they no longer decided
  anything. They stay visible — the checkboxes still control which
  values exist — but no longer pretend to control the arrangement.
- **The placeholder legend moved into an info box.** As dim text
  directly on the card it competed with the settings around it.
- Section headers, the sub-option rule and the info box are new
  stylesheet rules built from colours `core/theming.py` already knows,
  so every theme recolours them along with the rest.

### Fixed

- **A browser choice would have broken on restart.** Firefox and
  Chromium append a per-process suffix to their MPRIS bus name
  (`…firefox.instance_1_94`); storing that would have pointed the
  setting at a Firefox that no longer exists. The suffix is stripped and
  the stored value keeps meaning Firefox. Two windows of the same
  browser also collapse to one dropdown entry, and the one that is
  playing decides whether it shows as active.
- **YouTube Music had no name in the Windows player dropdown.** Its
  Electron AUMID has no ".exe" to strip and no "!" to split on, so it
  fell through every rule and was listed as
  `com.squirrel.youtubemusicdesktopapp.youtube music desktop app`. It
  now says "YouTube Music" — for the Squirrel build, the th-ch fork and
  YTMDesktop alike, whose AUMIDs differ only in whether they spell it
  with a hyphen, an underscore or a space.
- **The Windows dropdown lower-cased every unknown player.** The label
  was built from the storage key, which is lower-cased on purpose so the
  saved setting survives a capitalisation change — but that meant the
  dropdown read "youtube music" while the chatbox's `{player}` said
  "YouTube Music". Labels now come from the AUMID as Windows reported
  it. Also affects TIDAL, Deezer, SoundCloud and anything else not in
  the lookup table.

### Removed

- `core/mangohud.py`, and the RTSS reader in
  `core/backends/hardware_windows.py`.
- `HardwareMonitor(log, mangohud_dir)` is `HardwareMonitor(log)` — the
  second argument is gone on all three backends, and `snapshot()` no
  longer returns an `fps` key.

## [v1.4.3] – 2026-08-22

**FPS setup no longer means hunting for a folder, a colon you typed
stays a colon, and the mouse wheel scrolls the page instead of quietly
changing the dropdown it rolls over.**

### Added

**FPS setup that finds itself**

- Linux: an **Auto-detect** button next to the MangoHud log folder. It
  reads `output_folder` out of your MangoHud configs — including the
  per-game ones and the ones **GOverlay** writes, which is how most
  people set logging up without ever seeing the path — and falls back to
  the usual folders (`~/mangologs`, `~/mangohud`, …). A folder holding
  VRChat logs wins over one holding somebody else's benchmark, and a
  fresh log wins over a stale one.
- When it finds nothing it says which step is missing rather than just
  "not found": MangoHud not installed, installed but no config enables
  logging (with the GOverlay route and the launch options), or configured
  but the folder does not exist yet.
- Windows: a **Check RTSS** button beside the download button. An empty
  FPS field means either "RTSS is not installed" or "RTSS is installed
  but not running", and those need different next steps — the button
  tells them apart, offers to start RTSS when it is only idle, and opens
  the download page when it is genuinely missing.

### Fixed

**Punctuation you typed is no longer eaten**

- A line like `fps:` in an All in one string, a Custom Box or a plugin
  template lost its colon — and `-----` lost its dashes, and a leading
  `|` disappeared. The clean-up pass that removes what an empty
  placeholder leaves behind (`GPU: {gpu_usage}` with the Hardware card
  off) decided by punctuation alone, so it could not tell a leftover
  from a character somebody wrote on purpose.
- Empty placeholders now leave an invisible mark behind during
  rendering, and the clean-up only works on those marks. Everything
  still standing afterwards is text you typed and is left alone.
- A missing value takes its label with it: `GPU: {gpu} | CPU: {cpu}`
  with no GPU now reads `CPU: 27%` instead of leaving a stray `GPU |`.
  `{position}/{length}` without a length is `0:27`, not `0:27/`.
- Advanced mode gets the same treatment: Text, Placeholder, Hardware and
  Media blocks mark their empty values too, so a Format block of
  `GPU: {a}` sends nothing rather than a bare `GPU:` — while OSC out
  blocks never see the marks.

**The mouse wheel no longer edits settings in passing**

- Scrolling over a dropdown (Personal Status template, Hardware sensors,
  microphone, translator …), a spin box or a slider changed its value.
  On a page that is several screens tall, the setting that got changed
  was usually off-screen before you noticed — the first sign of it was
  VRChat showing the wrong thing.
- Those widgets now hand the wheel to the page they sit in. Click,
  arrow keys, typing and the wheel inside an *open* dropdown list work
  exactly as before, and scroll bars are untouched.
- The filter is taken off again on quit — an application-wide event
  filter that is still installed while Qt and Python tear each other
  down segfaults on exit.

## [v1.4.2] – 2026-08-21

**The microphone dropdown finally lists microphones instead of ALSA
PCMs, and there is a level bar that tells you whether the one you picked
can actually hear you.**

### Added

**A microphone list you can read**

- The dropdown is **grouped**: *Microphones*, *Virtual sources*,
  *Monitors*, and — folded away at the bottom — *Direct hardware*. Each
  group header explains what it is, so "a monitor records what your
  speakers are playing, not your voice" is said once instead of never.
- The entries come from **PipeWire/PulseAudio** (`pactl`) rather than
  from PortAudio. That is the whole difference: PortAudio's list is a
  list of ALSA PCMs, which is why it showed four copies of one headset,
  half a dozen HDMI **outputs** as if they were inputs, and **no VR
  microphone at all** — a WiVRn or PipeWeaver source is a PipeWire node
  with no ALSA device behind it, so it could not appear.
- Those sources are opened by pointing the microphone helper's
  environment at the node (`PULSE_SOURCE` / `PIPEWIRE_NODE`), which only
  works because the microphone has lived in its own process since 1.4.1.
- The **default source is marked** with ●, the node name is in the
  tooltip, and the raw `hw:` devices are one toggle away for the cases
  where bypassing the sound server is genuinely the answer.
- No `pactl`: everything falls back to the previous plain device list.
  It is an optional dependency, not a requirement.

**Windows gets its own version of the same problem solved**

- There is no `pactl` on Windows, but PortAudio has the duplication
  problem there too: every microphone is reported once per audio API
  (MME, DirectSound, WASAPI, WDM-KS), so two microphones become eight
  entries. The list now keeps **one entry per device** – WASAPI where
  there is one, because MME truncates names at 31 characters and turns
  a microphone into `Mikrofon (HyperX QuadCa`.
- Those truncated MME names are **folded back onto the full ones**
  rather than left sitting there as a near-identical extra line.
- The other routes are behind the same toggle the direct-hardware group
  uses on Linux, worded for Windows – worth a try when a device
  refuses to open on WASAPI.
- The level meter, the microphone test and all sensitivity settings work
  the same on Windows. Only the *“Recording from”* read-back is
  Linux-only, since it asks the sound server a question Windows has no
  equivalent for.

**Proof that the right thing is being recorded**

- After a recording starts, the app **reads back out of the audio graph**
  which source the helper actually ended up attached to and shows it:
  *✅ Recording from: PipeWeaver VR-Mic*.
- Pointing an environment variable at a node is a request, not a
  guarantee. A node that disappeared between the dropdown and the click
  produces a recording that works perfectly and listens to the wrong
  thing — and you would find that out from the people in the instance.
  Now you find it out from the status line.

**Microphone test and a level meter**

- A new **Microphone test & sensitivity** panel under the device
  dropdown, with a **🎧 Test** button that opens the selected device and
  shows its input level without recording or transcribing anything.
- The bar keeps running **while a recording is going**, fed from inside
  the helper's own read path — so it shows the audio the recogniser is
  actually working with, not a second stream that might be attached
  somewhere else entirely.
- The scale is dBFS, because speech sits at 1-3 % of full scale and a
  linear bar is a twitch at the left edge and nothing else.

**Sensitivity settings**

- **Automatic sensitivity** (on by default, the previous behaviour) can
  be switched off. Automatic re-learns the room continuously, which is
  right in a quiet one and drifts upward next to a fan, in a game with
  sound, or with a headset whose own audio bleeds into the microphone —
  until nothing counts as speech any more.
- **Speech starts above** — the threshold, drawn as a dashed line in the
  level bar so the setting and the meter are the same scale. Below it
  the bar fills grey (audio that will be ignored), above it accent
  coloured.
- **📏 Measure** listens to your room for three seconds while you stay
  quiet and puts the threshold above what it heard.
- **Silence ends a phrase after** — too short cuts sentences in half at
  every breath, too long delays every message.
- **Ignore sounds shorter than** — what keeps a keyboard click, a mouse
  or a door from becoming a transcription request.
- **Longest single phrase** — a hard cap, so an open mic in a loud
  instance still sends something instead of recording forever.
- All of it has a **Reset to defaults**, and none of it exists in older
  configs — those load on the defaults, i.e. exactly the behaviour they
  had before.

### Changed

- `stt_mic` now stores an id (`pulse:<node>`, `pa:<device>`, or empty
  for the system default). **Existing configs need no migration**: a
  bare device name is read as `pa:` and keeps working, and so does
  downgrading.
- The saved device is still kept in the list when it is temporarily
  gone, marked *(not available)* — a refresh while VR is off does not
  quietly reset the choice.
- Calibration is **skipped in manual mode**. `adjust_for_ambient_noise()`
  writes what it measured into the threshold, so running it would have
  discarded the value you just set and left you adjusting a slider that
  did nothing.
- The AUR package gained `libpulse` as an **optional** dependency
  (that is where `pactl` lives).

### Fixed

- **Two settings quietly destroying each other.** The new "silence ends
  a phrase" field was built as `self.pause_spin` — a name the Presets
  card already used for the chatbox pause. Loading the config pushed the
  10-second chatbox pause into a field whose maximum is 3 seconds, which
  clamped it and wrote 3.0 back into the speech setting on **every
  start**, while the chatbox pause never applied at all. Caught before
  release; the speech fields are now `stt_*` throughout.
- **An empty microphone dropdown after loading the config.** The config
  step still repainted the list the old way, with raw PortAudio pairs
  instead of grouped entries, wiping the entry the build step had just
  put there.
- The level meter, the test and any running recording are stopped when
  the panel is collapsed, when Text to Text is selected, and when the
  window closes — an open microphone behind a hidden panel is exactly
  what this release is about noticing.

## [v1.4.1] – 2026-08-17

**Speech to Text no longer crashes the app, Send to VRChat really means
off in Advanced mode, and the placeholder names can be typed instead of
hunted for.**

### Added

**Advanced mode: a search line over the blocks**

- The **Blocks palette** got the same search box the Variables list
  below it has always had. Thirty-four blocks in six collapsed
  categories means knowing that *Send Hotkey* lives under System is
  something you learn rather than something you can see.
- It matches the title, the description and the category, so "key"
  brings up both hotkey blocks and "avatar" everything that talks to
  VRChat. Categories and subgroups open themselves while a search is
  running and fold back the moment the box is empty.

**Type-ahead for placeholders**

- Type `{` and a letter or two in an All-in-one string, the Hardware or
  MediaPlay custom string or a plugin's own string, and a **suggestion
  list drops under the cursor**. Enter or a click completes the whole
  name, closing brace included; typing on narrows it; Escape drops it
  for that word.
- The list is ranked: names that *start* with what you typed first, then
  names that contain it, then descriptions — so `{bat` reaches
  `{hmd_battery}` without knowing which plugin named it, while `{time`
  still puts `{time}` above `{time_status}`.
- It is fed by the same index the picker menu uses, so a field only ever
  suggests what it can actually resolve — no hardware names inside a
  plugin string — and a plugin installed while the field is open shows
  up on the next keystroke.

**The "+" menu got a search line**

- A **search box and a scope selector** sit at the top of the picker.
  Typing filters everything down to a flat list of hits, each one
  carrying the group it came from, so the answer to "where did
  `{hmd_battery}` come from" is in the result rather than three folders
  away.
- The scope selector narrows the search: *Everywhere*, *This app*, one
  of the **built-in sections** (Personal Status, Hardware, Media, Custom
  Box, Chat / Speech to Text, Formatting) or **one specific plugin**.
  Picking a plugin with the box empty simply lists everything that
  plugin offers.
- A plugin's short names — the ones it claimed without its own prefix —
  moved into a **"Short names (n)"** submenu instead of sitting inline.
  They are the same values under a second name, and fifteen lines of
  "claimed by this plugin" was something to scroll past every time.

### Fixed

- **Speech to Text could take the whole app down with it.** Reported
  from CachyOS with PipeWire 1.6 and PyAudio 0.2.14, on the AUR build,
  the AppImage and a source checkout alike: pressing record ended the
  process within a second, with `malloc(): mismatching next->prev_size`
  or `free(): corrupted unsorted chunks` and a core dump. That is glibc
  finding a corrupted heap — not a Python exception, so no amount of
  error handling inside the app could have caught it. Two things on our
  side made it happen, and both are gone:

  - **Every PortAudio call ran on a throwaway thread.** The timeout
    guard opened the stream on one thread, calibrated it on a second and
    read it on a third — with each earlier one already exited by then.
    PipeWire keeps per-thread client state, so the reader was working on
    a stream whose creator no longer existed. That is why the faulting
    thread in the reported core dumps is called `mic-probe:*`.
  - **Filling the microphone dropdown could abort a running recording.**
    Enumerating devices builds a PyAudio object and tears it down again,
    and `Pa_Terminate()` closes *every* open stream in its process.

- **The microphone now runs in a process of its own**
  (`core/mic_host.py`, `core/stt_child.py`). It opens, calibrates, reads
  and closes on one single thread, and nothing else in that process
  touches audio. If the audio stack aborts anyway, it aborts a helper:
  the recording stops, the app says so and stays open. Device lists and
  the default-device check are separate short-lived helpers for the same
  reason — which also means a wedged PortAudio can finally be
  **killed** instead of leaking a thread that is parked forever.

  The debug console logs which path is in use on every recording start,
  so the next report says whether the app or the helper died. Setting
  `OSC_DREAMCHATBOX_STT_INPROCESS=1` forces the old in-process path for
  debugging; that path got the same-thread fix as well, plus a watchdog
  that reports a hang instead of moving the call away from its stream.

- Closing the window while recording now **ends the helper before the
  app exits**. Stopping only set a flag, and the daemon thread that acts
  on it dies with the process — which could leave a helper holding the
  microphone for a window that was already gone.

- **Advanced mode ignored the Send to VRChat switch.** With All in one
  in *Advanced* mode and anything moving on a canvas — a clock, a
  hardware value, a Timer — turning the sidebar switch off cleared the
  chatbox as intended and then put the text straight back one to two
  seconds later, over and over.

  The one second Advanced tick (and the **Button** block) called the
  send routine directly, while the switch was only consulted on the
  paths the interval timer and the instant sends take. The check now
  sits in the send routine itself, so every automatic chatbox message
  passes it no matter which timer or block asked for it.

- The canvas keeps running with the switch off — a graph whose job is a
  hotkey, a program start or an avatar parameter is not about the
  chatbox and should not stop — it just no longer reaches the chatbox.
  Typed messages from the Chat card and Speech to Text are unaffected
  as well; those are manual actions with their own path.

## [v1.4.0] – 2026-08-10

**A visual way to build the All-in-one string, a link to the avatar in
both directions, and the app can now reach outside itself.** Everything
since v1.3.2 in one release.

### Added

**Advanced mode — a node canvas for the All-in-one string**

- A **Mode switch** at the top of the All in one card: *Normal* is the
  text fields exactly as before, *Advanced* points at the new canvas.
  Nothing is converted when you switch, so it is reversible at any time.
- A new **Advanced tab** in the sidebar: blocks palette on the left, the
  canvas in the middle, the selected block's values on the right. Both
  side panels fold away. Drag a block out of the palette, drag from an
  output dot to an input dot to wire it; middle mouse pans, the wheel
  zooms, Delete removes the selection.
- **One canvas per AIO string**, picked with tabs above the canvas, and
  each of the ten AIO templates keeps its own set of canvases alongside
  its strings and dwell times. Up to **10 strings** now, not 5.
- **34 blocks.** Sources (Text, Placeholder, Personal Status, Status
  text, GPU, CPU, RAM & System, MediaPlay, Chat/STT, Clock, Custom Box),
  Text (Join with 2–10 inputs, Format, Info, Style, Truncate, Line
  break), Logic (If/Else, Compare, Has value), Flow (Timer, Step,
  Button, Change AIO), OSC, Output, System and Hotkeys.
- **Info + Step** let several pages take turns in one Chatbox Output and
  start over by themselves; **Chatbox Output → Shown?** into a **Timer**
  times something from the moment a string appears.
- Every placeholder a typed string can use is **draggable out of a
  grouped Variables list**, plugins included.

**Talking to VRChat and to everything else**

- **OSC input**: a listener that keeps the last value of every avatar
  parameter, with a picker so names are chosen rather than typed, plus
  blocks to read them and to write bool/int/float back.
- **External OSC in/out** for any address, so other tools on the machine
  can drive the chatbox and be driven by it.
- **Send Hotkey / Get Hotkey**: press a key combination at the operating
  system, or react to one pressed anywhere. SendInput on Windows;
  xdotool, wtype or ydotool on Linux, with python-evdev for watching.
- **Program running / Start program**: notice that VRChat came up and
  launch things with it, optionally in a terminal window for debugging.
- Blocks with side effects run **only on a real send, never on the
  preview**, and Advanced mode ticks once a second so a Timer keeps its
  own time rather than the send interval's.

**Elsewhere**

- **`short_description` in plugin.json** — an optional one-liner for the
  Installed list, so a plugin with a long `description` no longer makes
  its row three lines tall. Missing means the list keeps showing
  `description`, exactly as before, and the full text is still the
  tooltip on the row and the body of the store page. `summary`, the key
  the store already read, counts as the same thing.
- **One-click update in the Installed list**: a plugin with a newer
  version on GitHub gets an **Update to vX** button right in its row,
  next to the version. It downloads and installs on the spot and keeps
  the plugin's settings — no trip to the Store tab and no "Update all"
  for a single plugin. Opening the Plugins page loads the catalogue once
  per session in the background so the button can appear at all; if
  GitHub is unreachable the page simply stays as it is.
- **"Update all (n)" above the Installed list** when more than one
  plugin has an update waiting — the same operation as the button on the
  Store tab, reachable from the list it is about. Both buttons are
  disabled while it runs and the tooltip names what is going to be
  pulled in.
- Which plugins count as "has an update" is now decided in **one place**
  for the row buttons, both "Update all" buttons and the counter on the
  Store tab, so they can no longer disagree. An entry that could not be
  read is left out — the download would fail anyway — and so is one
  whose new version does not run on this system, which previously meant
  "Update all" could install a plugin straight into a greyed out row.
- **`{box_text}`** — the Custom Box middle text on its own.
- **Say when a translation is running** (on by default): the gap between
  speaking and the translation arriving says `Translate …` instead of
  leaving the previous message up. Shows in `{text_output}` too.
- The **"+" placeholder picker** on the Hardware, MediaPlay and plugin
  custom fields; **CPU and GPU watts**; multi-line All-in-one fields with
  Shift+Enter; **per-string dwell times**; message placeholders split by
  source (`{stt_input}`, `{chat_output}`, …); reaching into a Personal
  Status template that is not the active one.

### Changed

- **With All in one active, the Custom Box no longer wraps the message.**
  The frame appears exactly where `{box_start}`, `{box_stop}` or
  `{box_text}` are, and nowhere else. Previously the wrap came back
  around every string that did not carry the placeholders, and sat
  outside the plugin lines as well. With All in one off, unchanged.
- **The Chat card has no "Send as" dropdown any more — it is always
  Standard.** Typing a message and pressing Send means "put this in the
  chatbox now". The dropdown, *Position* and *Keep for* moved to the To
  Text card, which is where the other two routes were ever useful. An
  existing setting carries over on first load.
- `apply_template()` is now `finish_template(substitute_placeholders(…))`
  — same behaviour, split so the node evaluator can resolve placeholders
  without running the line clean-up on a half-built string.
- **`core/` had a second copy of the whole project committed inside it**
  (`core/ui/`, `core/core/`, the README, the launcher, the requirements
  files, and more). All of it stale, none of it imported. Removed.

### Fixed

- **Speech to Text could freeze the whole app, and on Wayland the
  desktop**, when leaving VR. Device enumeration moved off the GUI
  thread with timeout guards.
- **CPU and GPU watts**: a GPU read could suppress the "no CPU power
  sensor" warning; the hwmon lookup re-globbed sysfs on every poll; Zen
  4/5 machines reported nothing where the counter exists; AMD sensors
  could come from the integrated card instead of the discrete one; an
  empty value now explains itself.
- **A microphone that is gone is reported** instead of silently falling
  back to the system default, and one that dies mid-recording is
  noticed.
- **stderr could vanish for the rest of the session** after the
  ALSA-noise suppression.
- **Hotkeys with named keys were sent in the wrong spelling** — X keysyms
  are case sensitive where the people typing them are not, so F13–F24,
  Escape, Return, the arrows, Delete and the media keys did nothing. On
  Windows the keystroke carried no scan code and no extended-key flag,
  which games ignore and which turned Delete into a numpad decimal
  point.
- **The process list was full of kernel threads**, and which backend
  produced it depended on whether psutil happened to be installed.
- A **canvas whose sources carry no written placeholder** (a Clock, a
  Timer, an Avatar parameter) produced nothing at all.
- A **canvas that only automates** — Button into Send Hotkey, with no
  Chatbox Output — never ran.
- A **second Chatbox Output block on the same canvas** was ignored
  without saying so; the status line now says how many there are.
- **All in one never rotated in Normal mode** — it stayed on AIO 1 no
  matter what "Rotate strings every" said. The timer was started for the
  rotation and then stopped again by the branch that starts the Advanced
  mode tick, so only Advanced mode ever rotated. Rotation and the tick
  are now decided separately, and switching All in one off is the only
  thing that sends the rotation back to the first string.
- **A rotated All-in-one string only reached VRChat at the next send
  interval** in Normal mode, so a string with a short "Custom time"
  could be over before it was ever shown. It now goes out as soon as the
  rate limit allows, the way a rotated Personal Status text does.

### Notes

No existing config is touched. Every new key is absent from configs
written before this release and falls back to the old behaviour, and the
one shared "Send as" setting is carried over to the To Text card on first
load. Node graphs are stored as ordinary JSON in the config file; an
unknown block from a newer version costs that block, not the file.

## [v1.3.2] – 2026-08-03

**Plugin settings got a real layout, and the chatbox got smaller letters.**
Two things that both come down to the same problem: 144 characters and a
handful of pixels, and everything has to fit in there. Everything in here
works identically on Windows and Linux, and no existing config is touched.

### Added

- **Plugin settings: collapsible groups.** A `plugin.json` can now wrap its
  settings in a block instead of dumping twenty rows in a flat list:

  ```json
  {"key": "g_twitch", "type": "group", "label": "Twitch",
   "expanded": false, "items": [ ... ]}
  ```

  A group holds no value of its own, it only groups the settings in its
  `items` list – which may contain every type, including one more level of
  groups (`MAX_GROUP_DEPTH = 2`; anything deeper is dropped rather than
  parsed, the same way a broken setting is dropped today). It renders with
  the same expander gesture as the card's own **Settings** button and, like
  that one, starts collapsed unless the manifest says `"expanded": true`.
  The open/closed state is a view detail and is deliberately **not** written
  to the plugin's `config.json` – a plugin that reopens five blocks on every
  start would be worse than one that opens none.

- **Plugin settings: dropdowns.** The new `"type": "choice"` renders a combo
  box:

  ```json
  {"key": "mode", "type": "choice", "label": "Data source",
   "default": "keyless",
   "choices": [{"value": "keyless", "label": "Keyless"},
               {"value": "api", "label": "Official API"}]}
  ```

  The **stored value is always the `value` string, never the label**, so a
  plugin author can rename a label in a later version without invalidating
  every config that already picked it. `"choices": ["a", "b"]` works as a
  short form where the value doubles as the label. Duplicates are dropped so
  a stored value always maps back to exactly one entry, and a choice without
  usable entries is dropped like any other broken row.

- **Plugin settings: `depends_value`.** `depends` used to mean "show this row
  while that checkbox is on". It can now follow a dropdown as well:

  ```json
  {"key": "api_key", "type": "text", "label": "API key", "secret": true,
   "depends": "mode", "depends_value": "official"}
  ```

  Accepts a single value or a list of them. **Without** `depends_value`
  nothing changes: the parent is tested for truthiness, exactly as every
  existing plugin relies on.

- **Plugin settings: `"secret": true`** on a `text` row switches the input to
  password echo, for tokens and API keys. Shoulder-surfing protection only –
  the value still sits in plain text in the plugin's `config.json`, and a
  plugin asking for credentials should say so in its `hint`.

- **Superscript and subscript for chatbox text** – the same character count,
  a fraction of the height. Unicode has modifier letters and sub/superscript
  digits, so a hardware name or a music timer can be tucked under the line it
  belongs to instead of eating a whole line of the 144:

  ```
  normal        hallo        012345689
  superscript   ᴴᴬᴸᴸᴼ        ⁰¹²³⁴⁵⁶⁷⁸⁹
  subscript     ₕₐₗₗₒ        ₀₁₂₃₄₅₆₇₈₉
  ```

  A dropdown sits behind **every one of the 20 Personal Status texts**, so
  one line can be small while the next stays normal. The style belongs to the
  text field, not to the position in the rotation, and it travels with the
  **text template** it was set in – all ten templates keep their own styles
  the way they keep their own texts.

  The same dropdown sits behind the **GPU name** and the **CPU name** in the
  Hardware card (a card name is the longest thing on a hardware line, so that
  is where the room is) and behind the **music timer** in MediaPlay. The timer
  converts **digits only**, so `:` and `/` keep their normal shape and
  `³:²⁷/⁴:¹⁵` still reads as a time.

  Unicode does **not** have a complete alphabet for either variant – that is
  the catch, and it is the reason for the info line above the status texts.
  There is no superscript `q`, and subscript is missing `b c d f g q w y z`.
  A character without a mapping is passed through unchanged, so a word comes
  out mixed rather than mangled. For those cases a word can be kept out of
  the conversion entirely by wrapping it:

  ```
  Playing _"Quake"_ right now   ->   ᴾᴸᴬʸᴵᴺᴳ Quake ᴿᴵᴳᴴᵀ ᴺᴼᵂ
  ```

  The markers are a formatting instruction, not content, so they are stripped
  in **every** mode – including Normal – and never reach VRChat. Picking a
  style that cannot render a letter also logs which characters stayed big,
  because that is much easier than squinting at the preview wondering why one
  letter looks wrong.

- **Inline `{super/"word"}` and `{sub/"word"}` in every custom string.** The
  dropdowns style a whole field, which is the wrong unit for a string you
  built yourself – the Hardware custom string is one field but five values,
  and styling the lot of it was never the point. The markers style one part
  instead:

  ```
  GPU {gpu_usage} {super/"vram"} {vram_usage}   ->   GPU 68% ⳽ᴿᴬᴹ 9/16GB
  ```

  Handled inside `apply_template()`, so every custom string has it for the
  same reason and with the same syntax: Hardware, All in one, MediaPlay, the
  Personal Status texts, a Custom Box middle text and a plugin's own string.
  Resolved *after* the placeholders, so the content can be one –
  `{super/{cpu_temp}}` styles whatever the value turned out to be. The quotes
  are optional and stripped when present, which is the only way to write a
  word with a trailing space. Aliases `{sup/…}`, `{superscript/…}` and
  `{subscript/…}` all work, and the `_"keep me"_ ` markers work inside a
  marker as well.

  The same caveat as everywhere else applies and is spelled out under the
  field: Unicode has no superscript `q` and no subscript for about half the
  alphabet, so those letters pass through unchanged rather than being mangled.

- **MediaPlay: an idle symbol between songs.** Until now the MediaPlay line
  simply vanished when nothing was playing, which on a two-line chatbox reads
  as "the app stopped working" rather than "no song". It now shows a single
  character instead – `⏸` by default, editable, with the emoji picker next to
  it – and can be switched off to get the old behaviour back.

  It covers all three ways of ending up with nothing: no player at all, a
  player whose custom string rendered to nothing, and a player where every
  part was switched off or the title was empty. All three are the same
  situation from the chatbox's side, so they give the same answer.

  **All in one gets it without asking for it.** A template line that is about
  the song and rendered to nothing means there is no song, so it is answered
  with the idle symbol instead of being cleaned away:

  ```
  {box_start}\n{text}\n {artist} : {title} |\n {time_status} {bar} {time_end}\n {box_stop}
  ```

  ```
  ┌──────┐          ┌──────┐
  talk to me        talk to me
  ⏸           ->    Artist : Song
  └──────┘          0:30 [██░░░░░░░░░░░] 3:00
                    └──────┘
  ```

  Only the *first* such line answers – a layout with a title line, a bar line
  and a lyrics line would otherwise stack three identical symbols. A line that
  mixes song values with anything else is untouched as long as the rest of it
  renders, and a line with no song values in it is cleaned away exactly as
  before. Aliases count: `{song}` is `{title}`.

  This is why `build_aio_lines()` now renders the template one line at a time.
  The output is identical – `apply_template()` cleans per line anyway – but it
  keeps the link between an output line and the template line it came from,
  which is the whole thing that makes the above possible.

  **`{media_idle}`** is still there for placing the symbol by hand: the symbol
  while nothing plays, empty otherwise, so `{media_idle}{artist} : {title}`
  puts it on the same line rather than on its own.

- **The emoji picker grew from 30 icons to just over a thousand**, in ten
  categories – Smileys, People, Hearts, Animals, Nature, Food, Activities,
  Travel, Objects, Symbols – with a tab row to switch between them. The
  palette moved into `core/emojis.py`, where it is plain data.

  Two things shaped what got in, and both come from the chatbox rather than
  from taste. **No ZWJ sequences, no flags, no skin tone modifiers**: a
  "family" emoji is five codepoints glued together with zero-width joiners
  and a flag is two regional indicators, VRChat's chatbox font renders a good
  part of them as tofu, and where it does not they still cost their full
  length against the 144 characters. Single codepoints are used wherever one
  exists. **Variation selectors are kept where the character needs one**,
  because `❤` and `❤️` are different strings and many fonts draw the
  monochrome glyph for the first – so 57 of the 1010 entries cost two
  characters instead of one, and each button says which in its tooltip.

  **A search box sits above the tabs.** Its terms come from `unicodedata`
  rather than a hand-written table: every entry in the palette has an official
  Unicode name and they are usually the words someone would type – FIRE,
  ROCKET, DOG FACE – so a thousand hand-maintained keyword lists would be a
  thousand chances to drift from the palette for no gain. The index is built
  on the first search, not at import. On top of that sits a short `ALIASES`
  table for the shorthand Unicode has no word for and for German, both
  deliberately not exhaustive: `lol`, `pc`, `gpu`, `cpu`, `ram`, `fps`, `vrc`,
  `afk`, `herz`, `feuer`, `musik`, `katze`, `wut`. All query words must match,
  so a second word narrows. Whole-word matches rank above substring ones,
  because `lol` is a substring of LOLLIPOP and `pc` of CUPCAKE – without the
  ranking the obvious answer sits under the sweets. The result grid reuses one
  pool of buttons instead of rebuilding on every keystroke.

  The picker shows one category at a time and builds a category's buttons the
  first time it is opened. A thousand QPushButtons built up front would be
  paid for on every start by everyone, including the people who never open
  the picker; this way one category exists at startup and the other nine
  cost 0.1 s in total, only if visited.

- **Custom Box – a frame around the whole chatbox.** A new card on the Apps
  page, below All in one. Switch it on and one line is hung above everything
  the app sends and one below it, so the chatbox reads as a closed box
  instead of a stack of loose lines:

  ```
  ┌──────┐            ┌─── 18:01 ───┐
  now playing …  ->   now playing …
  └──────┘            └─── 68 % ───┘
  ```

  It sits below All in one because that is the order it works in: All in one
  decides *what* is sent, the box only frames whatever came out. The top line
  is the first line of the message and the bottom line the last one, no
  matter which apps or plugins produced what in between.

  **Twelve templates plus one you build yourself** – Light, Heavy, Double,
  Rounded, Dashed, Blocks, Rule, Corners, Stars, Hearts, Arrows, Sparkles,
  in a dropdown that shows each frame next to its name. A row of numbered
  buttons would have said "7" and nothing else, so picking a frame would have
  meant clicking through all twelve to find out what they look like. The
  **C** slot exposes the six strings a template actually is (left cap, fill
  and right cap, for each of the two lines), so any frame is a few characters
  away. Each line can be switched off on its own – a top rule with no bottom
  is a valid frame.

  **Width is set per line**, not once for both. The two middle texts are
  rarely the same length – a short clock on top and a long hardware line
  underneath need different amounts of fill to end up looking like one box,
  and a single number could only ever suit one of them. **Align top & bottom**
  is still there for when you *do* want them even: it pads the shorter of the
  two rendered lines. It only ever adds fill, never trims, so for two
  deliberately different lines, switch it off.

  **Each line can carry a middle text**, chosen per line in a dropdown:

  - **None** – a plain line: `┌──────┐`
  - **Clock** – `┌─── 18:01 ───┐`, in one of four formats (24 h with or
    without seconds, 12 h with or without AM/PM)
  - **Custom** – your own text through the **same template engine All in one
    uses**, so `{cpu_usage}`, `{title}`, `{gpu_temp}`, the live info and
    every active plugin all work in the frame. `{box_clock}` is the clock
    from the format above.

  The fill is split evenly around a middle text, which is what turns
  `┌──────┐` into `┌─── 18:01 ───┐`. The alignment is an estimate by design –
  the chatbox font is not monospaced, so it gets the two lines close and
  cannot get them pixel perfect.

- **A "Parameters" list under All in one.** A second arrow below Settings,
  because the placeholder vocabulary had grown into a wall of grey text that
  nobody reads and half of it lived on the Plugins page anyway. It opens into
  two halves:

  - **Software parameters** – everything the app itself produces, grouped the
    way the UI is grouped: Personal Status, MediaPlay, Hardware, Live info,
    Custom Box, and `\n`. Each group with a one-line note on the parts that
    are not obvious, e.g. that `{temp_icon}` makes the temperatures drop
    their unit.
  - **External parameters** – every installed plugin with its `{<id>}`, its
    `{<id>_<key>}` values and any name it claimed unprefixed. Inactive and
    unsupported plugins are listed too, marked as such, because "why is this
    placeholder empty" is the question the list exists to answer.

  The same list sits at the bottom of the **Custom Box** card, because a box
  middle text is rendered against the identical value dict – plugins included
  – and one shared builder cannot drift the way two hand-kept lists would.
  The text is selectable, so a placeholder can be copied straight out of the
  list into the string. It is rebuilt when the block is opened and whenever
  the plugin list changes, so a plugin installed while the app is running
  shows up without a restart. The old paragraph above the All-in-one string
  shrank to one sentence pointing at it.

- **`{box_start}` and `{box_stop}`** – the way back out of the card. Put them
  into an All-in-one string and the two frame lines land exactly where you
  wrote them instead of being wrapped around the whole message. They resolve
  whether or not the card is Active, so All in one can use the frame without
  the automatic wrapping at all, and a string that places a line itself does
  **not** get that line added a second time.

- **The card ships switched off but fully filled in.** Turning it on gives:

  ```
  ╔═══ 🕐 09:05 🕐 ═══╗
  talk to me
  ╚═ OSC-DreamChatbox ═╝
  ```

  Double frame, a live clock on top, the app name underneath, widths 7 and 3,
  alignment off because those two widths are deliberately different. A card
  with thirteen switches and an empty preview teaches nobody what it does, so
  the settings are there – but the frame itself is not sent until asked for.

  Off rather than on, because how wide a frame line can get before the chatbox
  breaks it depends on the font and on which characters are on the line, and
  nothing in the config can know that. It is set once, by eye, against the
  game – and once set it stays set. Shipping it on would mean shipping a frame
  that splits on somebody's setup and looks broken out of the box.

- **Realtime clock.** The clock tick is the only thing in the Custom Box that
  costs anything, so it is a toggle. Off, the frame is rebuilt when something
  else changes, which means a clock can sit up to one send interval behind.
  On, it gets its own tick and updates the moment it changes. It is on by
  default because the default top line is a clock – a clock that only moves
  when something else happens looks broken.

  The tick only runs while the card is Active **and** a line actually shows a
  clock. That includes `{box_clock}` inside a Custom middle, not just the
  Clock middle mode: the default top line is exactly that shape, and checking
  only the mode would have left the switch on and doing nothing. It is 2 s for
  a format without seconds and 1 s for one with them, and it compares the
  rendered clock string before doing anything – so a clock that changes once
  a minute causes one refresh a minute, not sixty.

- **Plugin API 2: a plugin may now say which one it needs.** `plugin.json`
  takes `"api": 2` (and an optional `"min_app"`). A plugin asking for more
  than the app provides is listed, greyed out and **not imported**, with the
  reason in its tooltip and its info popup. Before, such a plugin imported
  fine and then raised on the first call into something that did not exist
  yet – once per frame, into the debug console. The store checks the same
  thing before the download, so an install that would end in a greyed out row
  is not offered at all. No `"api"` key means 1, which is every manifest that
  exists today, so nothing published so far changes.
- **`api.supports("feature")` and `api.needs(n)`** – runtime feature
  detection, so one plugin release can serve several app versions instead of
  pinning a minimum for something it could have worked around. Also answers
  `"hook.<name>"` and `"settings.<type>"`, which are the two questions an
  author actually has: may I call this, and will my settings row show up.
- **`api.set(key, value)` / `api.set_many()`.** A plugin can write its *own*
  settings – an autodetected path, a refreshed token, the size of its own
  panel – and have them persisted like any user edit. The visible widget
  follows along, `on_settings()` is deliberately **not** called back, because
  a plugin answering its own write is how you build an endless loop, and the
  update is queued onto the GUI thread, so a plugin may write from one of its
  worker threads without that being a segfault.
- **`api.refresh()`** asks for a fresh render for data that arrived between
  frames, and **`api.data_path(*parts)`** hands out a path inside the
  plugin's own folder with the parents created – so plugins stop inventing
  places under `$HOME`.
- **`build_widget(parent)`: a plugin may bring its own UI.** It returns a
  `QWidget` and the Plugins page embeds it under that plugin's settings. The
  settings schema covers *options*; a Start button, a live log or a list the
  user adds rows to cannot be expressed as an option, and the alternative was
  every such plugin opening its own window. Runs through the same
  `_safe_call()` as every hook, so broken widget code costs that plugin its
  panel and nothing else.
- **`on_event(name, data)` plus `PluginManager.emit()`.** One generic channel
  for everything that does not exist yet: a new kind of notification is a new
  name, and every plugin that does not know it ignores it – no change in
  `core/plugins.py` and none in any installed plugin. First name in use is
  `app.shutdown`, announced before teardown so a plugin can flush while the
  rest of the app is still standing.
- **`on_tick()`** fires at the top of every chatbox frame, before the values
  are collected: a heartbeat for cheap polling without starting a thread.
- **New plugin setting type `path`** – a text row with a file picker next to
  it. A path field without one is unusable on Windows, where nobody types
  `C:\Users\…\AppData\Local\Programs\OSCLeash\OSCLeash.exe` by hand, and
  awkward enough on Linux. `"mode": "file" | "dir"`, optional Qt name
  `"filters"` and a `"placeholder"`; `QFileDialog` gives the native dialog on
  Windows and the platform one on Linux, so the app never has to know which
  it is. The dialog opens where the field already points – the folder itself
  when the value is one, its parent when it is a file, `$HOME` when the field
  is empty. Typing stays possible, because a path on a share or one that does
  not exist yet cannot be picked, and the value is stored exactly as entered:
  never resolved, never checked, so a config carried to another machine is
  not silently "corrected".
- **The plugin info popup names the systems a plugin runs on** – `OS  Linux &
  Windows`, or just the one, in orange when it is not this machine. The greyed
  out row only ever answers for the computer you are sitting at, which is no
  help when you are deciding whether to recommend a plugin to someone on the
  other OS.
- **New plugin setting types `action` and `label`.** `action` is a button: it
  holds no value, never reaches `config.json`, and calls the plugin's
  `on_action(key)` when pressed, showing whatever the hook returns next to it
  (`style` is `normal`, `primary` or `danger`). `label` is a read-only line
  whose text is an ordinary option value - combined with `api.set()` that
  gives a plugin a live status line inside its own settings card. Between
  them they close the gap that made `build_widget()` feel mandatory: a plugin
  that only wanted one button used to need a whole Qt file for it.
- **An Uninstall button in the store**, on the detail page of a plugin that is
  installed. It runs the same delete path as the bin on the Installed page, so
  the warning about losing that plugin's settings cannot drift apart between
  the two places it is offered from – somebody who found a plugin in the store
  looks for the way out there too, not in a second list. Afterwards the
  catalogue is re-marked against the folder on disk with the new
  `PluginStore.sync_installed()`, which touches no network: nothing upstream
  changed, only our own side did, and `refresh()` would have frozen the window
  while it fetched every manifest again.
- **The store catalogue lists the new plugins**: OSCLeash, Social Media and
  Stream Stats next to World Stats, and `example_template` replaces the old
  Hello World, which is gone from the repository. `config/plugins.json` is
  fetched from GitHub on every refresh, so AppImage and AUR users see them
  without updating the app.
- **A “Write a plugin” button** in the store, and `PLUGIN_TEMPLATE_URL` in
  `core/constants.py` so the address lives in one place instead of in four
  tooltips.
- **An example plugin ships with the app**, `example_template`: every setting
  type next to every hook, all of it live, with the reasoning in the comments.
  Copy the folder, rename it, delete what you don't need - including the
  deliberate row of an invented type, which is there to show that an unknown
  setting is kept rather than dropped.
- **New plugin setting type `emoji`** – a text row with the app's own icon
  picker behind a 😀 button, the same popup the Personal Status, MediaPlay,
  Hardware and Custom Box strings already use. Nothing new was built for it;
  the point is that a plugin icon is chosen the way every other icon in the
  app is, rather than each plugin inventing its own answer to "how do I type
  an emoji on this machine". It stays a text field on purpose: an icon is
  often two characters (a base emoji plus a variation selector) and a
  trailing space is sometimes exactly what the author wanted.
- **The plugin contract is documented** in `PATCH-README.md`, including the
  parts that are easy to get wrong – `None` versus `""` in `get_values()`,
  importing Qt lazily, never touching a widget from a worker thread, and
  never shipping a `configs/` folder inside a plugin zip.

### Changed

- Plugin option values are collected through the new `iter_settings()` walker,
  so defaults and stored values keep living in one flat dict no matter how the
  settings are grouped. Keys stay unique across the whole schema – groups
  recurse sharing one `seen` set, because two rows sharing a key would
  silently overwrite each other in that dict.
- The GPU/CPU name is built in one place (`_hw_display_name()`) for both the
  plain hardware lines and the custom string, which is what keeps the style
  from applying to one and not the other.
- The music timer is styled inside `_fmt_media_time()`, the single point every
  time string already went through – so the time line, the merged songbar
  line and the `{time}` `{position}` `{length}` `{time_status}` `{time_end}`
  placeholders all follow the setting without five separate code paths.
- The All-in-one value dict moved out of `build_aio_lines()` into
  `_template_values()`, because the Custom Box needs exactly the same
  placeholders. One builder means the frame can never know a placeholder All
  in one does not, or fill one differently.
- A config from the first Custom Box build carried one `box_width` for both
  lines; it is migrated into `box_width_top` / `box_width_bottom` and the old
  key dropped. The stored file is now kept alongside the defaults during load,
  because after the merge a default is indistinguishable from a stored value –
  and a migration has to be able to tell "never had this key" from "set it to
  the number the default happens to be".
- `make_settings_expander()` / `set_expanded()` take an optional label. It
  was hard-wired to "Settings", which is right for every existing caller and
  wrong for a block that is a reference list, so the default keeps all of
  them unchanged.
- An empty payload is no longer framed. With every app quiet there is nothing
  to put a box around, and an empty frame is not a smaller message – it is a
  message that says nothing and still costs two lines and a send.

- **Nothing the plugin system does not understand is dropped any more.** A
  settings row of a type this build does not know is kept instead of silently
  vanishing: its default is stored like any other value, `api.get()` keeps
  returning it, and the row shows up as a disabled 🔒 line naming what it
  needs. The same for unknown keys everywhere else – extra manifest fields in
  `Plugin.extra`, extra keys on a settings row in `item["extra"]`, extra keys
  in `configs/config.json` written back out untouched. That last one matters
  most: rewriting a config that a newer version wrote used to quietly delete
  every setting made there.
- **`Plugin.supported` now means "runnable here"** – the platform check and
  the plugin API check together, with `platform_note` returning whichever
  reason applies. Both halves stay available as `platform_ok` and `api_ok`,
  and every place in the UI that asked the old question keeps working
  unchanged.
- Groups nested deeper than the two supported levels become that same
  disabled placeholder instead of disappearing.

### Fixed

- **Windows: a plugin setting containing an emoji was silently lost.**
  `PluginManager._write_config()` wrote the file with `ensure_ascii=False` but
  without an explicit encoding, so Windows used the locale codepage (cp1252)
  and raised `UnicodeEncodeError` on the first non-Latin-1 character. The
  write is wrapped in a `try` that logs and moves on – losing a setting must
  not take the chatbox down – so the failure was invisible and the setting
  simply never arrived. Reachable through the emoji picker sitting right next
  to every plugin custom string, and now also through `{super/…}` output.
  Linux never saw it because its locale is UTF-8. Both config paths (plugin
  and main) are now pinned to UTF-8 on read and write.
- **Windows: `font-family: monospace` is a fontconfig alias, not a family.**
  It resolves on Linux and matches nothing on Windows, where Qt then picked
  whatever it liked – which for the Custom Box preview meant the frame stopped
  lining up. The preview now asks the system for its actual fixed-width font,
  and the stylesheet rules ask for `Consolas, monospace` so each platform gets
  the one it has.

- **Updating a plugin left its old code running.** `_unload()` dropped only
  the plugin's top-level module from `sys.modules`, never the submodules a
  multi-file plugin imports as `<module>.panel` and friends. Re-importing
  after an update therefore built a fresh `main.py` around the *previous*
  version's helpers, and the plugin showed its new manifest while running its
  old code – visible as a card that says v2 next to an error message only v1
  could produce. Every module belonging to the plugin is dropped now, so the
  next load is genuinely fresh.
- **A plugin writing to the UI from a background thread could take the whole
  app down.** Host calls out of the plugin manager are now queued into the
  window's event loop with the window as the context object, which is what
  makes Qt run them in the GUI thread – the same class of bug as the
  `_log_signal` fix in v1.0.8, one layer further out.

### Notes

- Fully backwards compatible in all three parts. Manifests without groups or
  choices parse and render exactly as before; configs written before v1.3.2
  have no styles, so every text, name and timer defaults to **Normal**, and
  they have no Custom Box keys either, so the frame comes up switched off and
  nothing about an existing setup changes on update. Every Custom Box value
  is clamped on load rather than rejected – an out-of-range template index
  would otherwise leave the card with no template selected at all.
- The frame costs characters out of the same 144 as everything else. Two
  `┌──────┐` lines are about 16 of them; the counter under the preview warns
  before VRChat cuts anything.
- New files: `core/textstyle.py` (the maps, the `_"keep me"_` handling and the
  dropdown labels), `core/boxstyle.py` (the frame templates, line building and
  the width estimate) and `ui/pages/custom_box.py` (the card). Changed:
  `core/plugins.py`, `core/plugin_store.py`, `core/textutils.py`,
  `ui/pages/plugins_page.py`, `ui/pages/apps_page.py`, `ui/mainwindow.py`,
  `ui/config_mixin.py`.
- **Plugin API 2 is additive.** Every hook, every manifest key and the config
  format are unchanged; an installed plugin keeps loading without being
  touched, and a plugin built against API 2 stays installable on an older app
  as long as it feature-detects instead of declaring `"api": 2`. The number
  lives in `core/plugins.py` as `PLUGIN_API_VERSION` and is deliberately not
  the app version: the app version is a release, the API number is a promise.
  Once v1.3.2 is out, API 2 means what it means today – new abilities arrive
  as additional capability strings, which cost nothing because
  `api.supports()` answers `False` for anything it has never heard of.

## [v1.3.1] – 2026-08-03

**Community release.** Two feature requests from the Discord, the hosted
LibreTranslate backend, and the reason VRChat was always a few seconds behind
the app. Everything in here works identically on Windows and Linux.

### Added

- **First-start default prompts.** A fresh install now comes with four filled
  rotation slots instead of an empty Personal Status card, so the app does
  something visible the moment you switch SendToVRChat on: a thank-you line,
  a "what am I running" line, the Ko-fi link and the GitHub link. They are
  seeded **only** when no config exists yet - they are ordinary texts from
  then on, so clearing or rewriting one sticks, and no existing install is
  touched. Plain text on purpose: VRChat's chatbox does not render markdown,
  so `[label](url)` would show the brackets and waste characters.

- **LibreTranslate Online - a hosted instance, nothing to install.** The
  fifth entry in the translation-service dropdown. It speaks the same API as
  the existing local option, just on somebody else's server, so it needs no
  `pip install libretranslate` and no local process. Pick the preset
  (`https://de.libretranslate.com`), the official `libretranslate.com`, or
  **Custom server** and paste any URL; a bare hostname gets `https://`
  prefixed automatically. There is an optional **API key** field, because
  public instances rate-limit keyless requests. Available in both **Speech to
  Text and Text to Text** - they share one translation pipeline, so the
  setting applies to both at once, and the 🧪 Test button works with it like
  with every other service. If the server is unreachable, the existing
  fallback chain (Lingva → Google) still catches it.

- **Lyrics symbol is now switchable** *(requested by Rachelle Bellwether on
  Discord)*. The `♪` in front of the synced lyrics line used to be
  hard-coded. Under **Apps → MediaPlay → Lyrics** there is now a checkbox
  plus a small field: turn it off entirely, or put any character or emoji
  there instead. An empty field behaves like switching it off. Custom and
  AIO templates get a matching `{lyrics_prefix}` placeholder so they can
  follow the same setting instead of hard-coding the symbol.

- **Instant send** (Options → Send to OSC). A changed text now reaches VRChat
  right away instead of waiting for the next interval tick. It is on by
  default and can be switched off.

### Fixed

- **VRChat lagged behind the app by up to a whole send interval**
  *(reported by Rachelle Bellwether on Discord: "vr chat doesn't get the
  updates as fast as the app does")*. `sending_live()` checked a config key
  called `send_active`, which stopped existing when the toggle was renamed to
  `send_to_vrchat` - so it was `False` for everybody, always. Every
  instant-send path behind it did nothing at all, and a rotated status text
  or a switched template only showed up on the next scheduled tick, up to
  `interval_sec` later. The preview updated immediately, which is exactly why
  it looked like VRChat was the slow one.

- **Chatbox sends are now rate-limit aware.** VRChat allows roughly 5 chatbox
  messages per 5 seconds and answers a burst with a ~30 second cooldown in
  which *nothing* is displayed - so naively sending on every change would
  have turned the first bug into a worse one. Sends now go through a rolling
  window (5 per 5 s, minimum 1.5 s apart - the interval VRChat itself uses).
  A send that arrives too early is **postponed, never dropped**, and repeated
  changes inside the waiting period **coalesce into one message**: typing in
  a status field costs a single send carrying the final text, not one per
  keystroke. Identical payloads are not re-sent, and clearing the chatbox is
  counted against the budget like any other message.

- **Dead `NameError` in the Windows branch of "VRC Picture Folder Fix."** The
  guard called a local variable that is only bound at the end of the method.
  Nobody ever hit it: on Windows that button is hidden and its row is never
  added to the layout, and the method has no other caller - so the branch was
  unreachable and no release ever crashed on it. It was still a loaded gun
  pointed at the next person who unhides the button, because PyQt6 routes an
  exception out of a slot to `sys.excepthook`, whose default terminates the
  process. It now shows the intended "not needed on Windows" dialog.

- **Status slots 11-20 could be lost.** The 20 rotation texts were normalised
  through a 10-wide window on load, so the upper ten only survived because
  the active template happened to restore them afterwards - and did not
  survive when that template was empty.

## [v1.3.0] – 2026-08-02

**Windows support.** The app runs natively on Windows 10/11 - same codebase,
same features, no Wine. Everything platform-dependent now sits behind one
switch and has a real backend on both sides. Linux behaviour is unchanged
throughout: the existing code was moved, not rewritten.

### Added

- **`core/osinfo.py` - the single platform switch.** The one place that calls
  `platform.system()`. It hands out `IS_WINDOWS` / `IS_LINUX` / `OS_NAME`,
  resolves the config directory (`~/.config` vs `%APPDATA%`) and knows where
  the read-only app files are, whether that is the project folder or the
  inside of a PyInstaller bundle. `core/plugins.py` re-exports the flags from
  here, so every existing plugin and every `plugin.json` keeps working
  untouched.

- **`core/backends/` - one implementation per platform, one interface.** Same
  pattern `core/translators.py` already used: several classes behind one
  contract, and a factory picks at startup. `core/hardware.py` and
  `core/mediafetch.py` became those factories, so `from core.hardware import
  HardwareMonitor` in the UI resolves to whichever backend fits. The Linux
  code moved into `hardware_linux.py` / `media_linux.py` byte for byte.

- **Media player on Windows** via GSMTC, the system media session Windows
  uses for its own media keys - Spotify, Apple Music, VLC, foobar2000,
  MusicBee, and any browser tab playing audio or video.

  The part that usually gets this wrong: GSMTC does *not* update the playback
  position continuously. Spotify writes it on play, pause, seek and track
  change and nothing in between, so a naively read song bar freezes for
  minutes and then jumps. The position is therefore extrapolated from the
  timeline's own timestamp, clamped to the track length, and guarded against
  every way that can go wrong - paused, past the end, a player that never
  sets the timestamp (it stays at the 1601 epoch, which would report a
  position of several centuries), a browser tab that reports no duration at
  all.

  WinRT objects have COM apartment affinity, so the backend owns one daemon
  thread that holds the apartment and refreshes a snapshot once a second;
  `fetch()` only copies it and never blocks.

- **Hardware on Windows**, stacked from "always works" to "only if you
  installed something", each source isolated so a missing one costs its own
  values and nothing else:
  - CPU load via `GetSystemTimes()`, RAM via `GlobalMemoryStatusEx()`, CPU and
    GPU names from the registry - no dependencies, always available
  - GPU load and VRAM from `nvidia-smi`, or otherwise from the same
    `\GPU Engine` / `\GPU Process Memory` performance counters the Task
    Manager reads. Utilisation is summed per engine type and the busiest type
    wins; adding up every instance would double-count, because 3D, Copy and
    VideoDecode run in parallel on the same chip.
  - FPS from RTSS shared memory - the Windows counterpart to tailing a
    MangoHud log, auto-detected, nothing to configure

- **Temperature helper for Windows.** CPU die temperatures live in registers
  only kernel-mode code can read; administrator rights do not change that,
  which is why every tool that shows them ships a signed kernel driver.

  This app deliberately ships **no** such driver. The usual candidate,
  WinRing0, has published privilege-escalation CVEs (CVE-2020-14979 /
  CVE-2020-14980 - arbitrary MSR and physical memory access for any local
  user), is on Microsoft's vulnerable-driver blocklist, and gets flagged by
  antivirus. A VRChat chatbox has no business installing a ring-0 attack
  surface on its users' machines.

  Instead the Hardware card has a button that starts a small elevated
  PowerShell helper reading everything reachable *without* a driver: ACPI
  thermal zones, which work on most laptops, plus LibreHardwareMonitor's WMI
  namespace if you have it running. The button also starts LHM elevated when
  it is installed, and enables its web server first. The helper writes to a
  small JSON file the unelevated app reads - no sockets, no pipes, no
  privileged code in the app itself - and exits by itself when the chatbox
  closes, so a stray elevated process can never outlive it.

- **Microphone on Windows via `sounddevice`.** PyAudio is a compiled
  extension whose wheels stop at CPython 3.13; on 3.14 `pip install pyaudio`
  falls back to a source build needing Visual Studio and a PortAudio
  checkout. `sounddevice` wraps the same PortAudio through CFFI, ships as
  `py3-none-win_amd64` (no CPython ABI, installs on every 3.x) and carries
  the PortAudio DLL in its wheel.

  Nothing about the recognition changed. `sr.Recognizer.listen()` only asks
  its source for four things, so the new module supplies exactly those as an
  `sr.AudioSource` - the energy threshold, silence detection,
  `adjust_for_ambient_noise()` and the Google recognizer all run untouched.
  PyAudio still wins when it is installed, so existing Linux setups stay on
  their usual path.

- **Windows packaging.** `packaging/windows/` holds a PyInstaller spec
  (one-folder or one-file, console on or off), a PowerShell build script that
  sets up its own venv and converts the icon, a double-click `.bat` wrapper,
  an Inno Setup installer script and a full build guide.

  The spec explicitly collects the MSVC runtime (`VCRUNTIME140.dll`,
  `MSVCP140.dll` and friends). PyInstaller follows binary dependencies but
  does not collect DLLs it considers part of the operating system - which is
  exactly where `MSVCP140.dll`, the C++ runtime Qt6 needs, normally lives. On
  the build machine everything works; on a fresh Windows box the app died at
  startup with a missing-DLL dialog. The build log now names every runtime
  DLL it ships and warns loudly if one is missing.

- **Plugin uninstall button.** Every row in the Plugins list has a 🗑 button.
  The handler existed already - it had simply never been wired to anything.

- **Clickable links for the API keys** under the Google and DeepL fields, and
  download links for LibreHardwareMonitor and RTSS on the Hardware card.

### Changed

- **Config location on Windows** is `%APPDATA%\OSC-DreamChatbox`, with a
  one-time copy from `~/.config/OSC-DreamChatbox` for anyone who ran the app
  from source before this release. It copies rather than moves, so a
  half-finished migration cannot destroy the only copy of anyone's settings.

- **"Installed" and "Store" moved** to their own row under the *Plugins*
  heading, left aligned. They were top-right, which is the first thing a
  narrow window cuts off - and they decide what the whole page shows.

- **Linux-only fixes are hidden on Windows**, not greyed out. *App Tray Fix*
  writes a freedesktop `.desktop` entry; Windows takes the icon from the
  executable. *VRChat Picture Folder Fix* symlinks screenshots out of the
  Proton prefix; on Windows there is no prefix. A disabled button invites the
  question "what am I missing?", and the answer is nothing.

- **"Fix OSCQuery" knows per-platform config locations.** Each supported
  program carries candidate paths for Linux and Windows, and the first one
  that *exists* is used. The module's rule is unchanged and is what makes
  guessing safe: only files that already exist are ever written, never
  created.

- **The FPS row adapts.** MangoHud folder picker and Steam launch options on
  Linux; on Windows an RTSS hint with a download link and nothing to
  configure.

- **`core/plugins.py`** no longer computes the platform flags itself - three
  lines, so there is one source of truth instead of two that can disagree.

- **`config/` is now bundled into the AppImage.** The plugin store catalogue
  lives there and was missing from the build. *(The AUR `PKGBUILD` has the
  same gap and is left alone deliberately - fixing it needs a republish.)*

### Fixed

- **A single network error killed the plugin store for the whole session.**
  `run_async(work, on_done)` only called `on_done` on success, so every
  caller that sets a "busy" flag beforehand got stuck: one `StoreError`
  (offline, GitHub rate limit) left `_store_busy` True and the button
  disabled until the app restarted. The hardware and media pollers had the
  same shape - one failed poll and that card never updated again. There is
  now an `on_error` path, and the store resets its state in one place.

- **An exception inside a result callback could take the app down.** PyQt6
  hands an exception raised in a slot to `sys.excepthook`, whose default
  aborts the process - so a display bug could have killed a running
  recording. Callbacks are now isolated.

- **Starting LibreTranslate froze the window for minutes.** The readiness
  probe ran on a 750 ms timer on the GUI thread and did an HTTP request with
  a one second timeout. While the server downloads its language models it
  accepts connections without answering, so the window locked up for about a
  second every 750 ms for the entire download. The probe now runs on a worker
  thread.

- **Speech to Text froze the window for up to six seconds** on restart -
  changing the language or toggling it off and on joined the previous
  recording thread on the GUI thread, and `r.listen()` only checks its stop
  flag between phrases. The wait now happens on the new worker thread.

  The same change fixes a race that killed recordings silently: the old
  session emitted its "stopped" message *after* the new one had started, and
  the UI read that as "recording ended" and unchecked the button. Sessions
  are numbered now and a stale one's messages are dropped.

- **Settings could be lost on exit.** `closeEvent` wrote the config last -
  after a teardown step that waits several seconds for a process to die.
  Anyone killing the seemingly frozen window lost the whole session's
  settings. The config is written first now, and each teardown step is
  isolated so one failure cannot skip the rest.

- **File handle leak** in the LibreTranslate launcher: the log file was
  opened and the parent's copy never closed - one handle per start, and on
  Windows an open handle keeps the file locked so it could never be replaced.

- **Plugin install and uninstall are hardened against Windows.** Files
  extracted from an archive can carry the read-only attribute (`rmtree`
  refuses them), and Defender or the search indexer can still hold a handle
  moments after a write. Both now clear the attribute and retry over about a
  second - a no-op on Linux. An update that failed here could previously have
  cost the plugin's settings, since the old `configs/` folder had already
  been moved aside.

- **The GPU backend label** no longer says "AMD (sysfs)" on a Windows machine
  with a Radeon card. Backends name themselves now.

- **`_silence_stderr()` is a no-op on Windows.** It exists to swallow ALSA
  spam, which Windows does not produce - and in a windowed `.exe` file
  descriptor 2 may not be a real handle, so redirecting it would have hidden
  genuine errors for no gain.

- **PyInstaller build log told the truth about optional packages.**
  `collect_all()` returns empty lists rather than raising for a package that
  is not installed, so the spec reported success for everything. It asks the
  import system first now.

## [v1.2.6] – 2026-08-01

### Fixed
- **Personal Status preview and VRChat now always show the same text.** The
  rotate timer and the send timer ran independently, so a new text appeared in
  the preview immediately while VRChat kept displaying the previous one until
  the next send tick - up to a full send interval later.

  A text switch is now only *pending* until it is actually sent: the send
  commits it and refreshes the preview, so the preview can never show
  something that has not gone out. On top of that a switch triggers a send
  right away and restarts the send timer from that moment, so the text changes
  without waiting and a scheduled tick cannot re-send the identical payload a
  fraction of a second later.

  This also covers the cases where sending is blocked: while a manual textbox
  message is up or Speech to Text is recording, the preview holds still
  together with VRChat and catches up on the next real send. Only with
  SendToVRChat switched off does the preview rotate on its own again - nothing
  is going out then, so it is a plain preview.

### Changed
- **"Change text every" has a 10 second minimum** (was 2). Anything shorter is
  gone before it can be read, and every switch now costs a chatbox send.
  Existing configs below 10 are lifted on load.

## [v1.2.5] – 2026-07-31

### Added
- **Anchor per plugin.** A dropdown next to each plugin's info button decides
  where its line lands: *Above Personal Status*, *Above Media Player*, *Above
  Hardware* or *Above All in one*. All in one stays the last block, so the
  fourth option means "below every app". The payload builder walks the app
  order and drops each anchor group in front of the app it belongs to, so
  dragging the Apps cards keeps working and plugins follow along.
- **Manual plugin order by drag & drop**, using the same grip handle as the
  app cards - dragging is the one reorder gesture in this app, so the Plugins
  page should not invent a second one. Within an anchor group the order set
  here is exactly the output order, which is what you want when you run only
  plugins and no All in one at all. Orders are rewritten as a dense sequence
  after every move, so two plugins can never end up sharing a position and
  silently sorting by id, and only the configs that actually changed are
  written - a drag fires on every mouse move.

### Changed
- With All in one active, plugin lines now render **above** the AIO block
  instead of being dropped. Previously the AIO branch returned early, so a
  plugin's own line vanished the moment you switched All in one on.

### Fixed
- **Speech to Text is installable on Arch again.** `python-speechrecognition`
  exists only in the AUR, and that package declares SpeechRecognition's
  *optional* backends - pocketsphinx, google-cloud-speech, groq - as hard
  dependencies. `google-cloud-speech` currently fails its own test suite, so
  the whole chain dies and Speech to Text becomes unreachable, even though we
  use none of those backends. The app now installs the pure-python library for
  itself with one button, into `~/.config/OSC-DreamChatbox/extras`, which is
  added to `sys.path` at startup. pip pulls in only SpeechRecognition and
  typing-extensions there, nothing is owned by pacman, and no
  `--break-system-packages` is involved. The AUR package no longer references
  `python-speechrecognition` at all.
- **Background image now fills the whole window.** It was applied to the root
  widget, but four surfaces from the base stylesheet were still painted
  opaquely on top of it - the window, the page stack in the middle, `#sidebar`
  and `#rightpanel` - so the picture only showed in the gaps and looked like
  three separate backgrounds instead of one. All four are transparent now; the
  two side columns keep a light 30% tint for legibility and the cards follow
  the opacity slider, so the image runs behind the entire UI as a single layer.

## [v1.2.4] – 2026-07-31

### Fixed
- PKGBUILD fix
- README updated

## [v1.2.3] – 2026-07-31

### Fixed
- **Speech to Text: microphone stuck on "System default" and the record button
  did nothing.** `available()` only checked for SpeechRecognition, which
  imports fine *without* pyaudio - pyaudio is needed the moment `sr.Microphone`
  is touched. So the UI reported everything as fine while `list_microphones()`
  silently swallowed `AttributeError: Could not find PyAudio` and returned an
  empty list, which is indistinguishable from a PC with one microphone.
  pyaudio is now detected separately, the reason is logged instead of
  swallowed, and the card says plainly what to install rather than leaving a
  dead button. On AUR this hit everyone: `python-pyaudio` was only an
  `optdepends`, so a normal install never pulled it in. It is a hard
  `depends` now - it lives in `[extra]` and brings `portaudio` with it.
  `python-speechrecognition` stays optional on purpose: it exists only in the
  AUR, so as a hard dependency it would break plain `makepkg -si` and drag
  every user into that package's known file conflicts. (With a source install
  the usual cause is `install.sh` failing to build pyaudio, which only prints
  a warning that is easy to miss.)

### Changed
- **Both bundled plugins updated to 1.2.0 and marked Linux + Windows.**
  *World Stats* now finds VRChat's log on Windows too
  (`AppData\LocalLow\VRChat\VRChat`) alongside the Steam/Proton prefix on
  Linux, skips the Steam library scan where it makes no sense, and words its
  "log not found" message per platform. *Hello World* is pure python and runs
  anywhere as-is. World Stats also ships its `logo.png` for the store tile.

### Added
- **Customization on the Options page.** Eight UI themes shown as colour
  swatches, every colour of the active theme overridable with a colour picker,
  and a background image behind the whole window – import your own, switch
  between them, adjust how solid the cards sit on top. Overrides are stored per
  theme, so switching away and back keeps them. Theming works by substituting
  colour tokens in the app stylesheet, so it covers every widget without any of
  them knowing that themes exist.
- **`is_linux` / `is_windows` in `plugin.json`.** Both default to true, so a
  plain-python plugin needs no extra keys. A plugin ruled out for the current
  platform is greyed out in the store with its install button disabled, greyed
  out in the installed list with its toggle locked, and refused by the plugin
  manager – that last one matters because a .zip install bypasses the store
  entirely, and loading anyway would end in a traceback instead of a message.
  The platform is detected per start, never stored, so a config copied to
  another machine cannot select the wrong branch.
- **FPS in the Hardware card**, usable as `{fps}` in the custom string, in
  All-in-one and in status texts. Linux exposes GPU load through `/sys` but
  frames per second only exist inside the process drawing them, so this reads
  MangoHud's log: it already runs inside VRChat and appends a row per interval.
  Set the log folder in the Hardware card and add the launch options shown
  there. A log older than 15 seconds counts as stale, so the chatbox never
  shows the frame rate of a session that ended hours ago.

## [v1.2.2] – 2026-07-30

### Changed
- **A plugin's custom string now drives its placeholder too.** With *Custom
  string* switched on for a plugin, `{world_stats}` in an All-in-one template,
  in a Personal Status text or in an Apps custom string returns that string
  instead of the plugin's raw output. Before, the custom layout only applied
  to the plugin's own chatbox line and was silently ignored everywhere else.
- Custom strings are rendered against the plugins' raw values, never against
  one another. That keeps the default template `{<id>}` from recursing into
  itself, and two plugins referencing each other now produce a defined result
  instead of depending on evaluation order.
- The plugin line and the `{<id>}` placeholder are rendered once and share the
  result, so they can no longer drift apart.

## [v1.2.1] – 2026-07-30

Plugin store, one-click plugin updates, and the fixes for the v1.2.0 AppImage and installer.

### Added
- **Plugin store.** The Plugins page now has two tabs: **Installed** and
  **Store**. The store shows a 4-per-row grid of tiles with the plugin's
  preview image, name, version and author; clicking a tile opens a detail view
  with the full description, an *Open on GitHub* link and one Install button.
  Plugins that are already installed are marked as such, and a newer version
  upstream shows as *Update →*.
- **`config/plugins.json` as the catalogue.** Adding a plugin to the store
  means pasting one GitHub link into `config/plugins.json` next to the app. Name, version,
  author, description and the preview image are read from the plugin's own
  `plugin.json`, so nothing has to be kept in sync by hand. Links to the repo
  root, to `/tree/<branch>/<folder>` and even straight to a `plugin.json` are
  all understood. Entries in
  `~/.config/OSC-DreamChatbox/plugins_sources.json` are merged on top, so your
  own additions survive an app update.
- **Two new `plugin.json` keys for store listings:** `image` (file in the
  plugin folder or a full URL) and `summary`. A plugin without an image gets a
  generated tile with its initials rather than a hole in the grid.
- **Install and update straight from GitHub.** Downloading, unpacking and
  installing runs on a worker thread, so a slow GitHub never freezes the
  window. Updates keep `configs/`, so settings survive.
- **Plugin updates in "Check for updates".** The Options button now checks the
  app *and* every installed plugin. If something is newer, a dialog lists the
  version jumps and updates them all with one click. The Store tab has its own
  *Update all* button for the same thing.
- **Self-updating plugin list.** Hitting **Refresh** in the store downloads
  the current `plugins.json` from GitHub and caches it in
  `~/.config/OSC-DreamChatbox/plugins.json`, so new plugins appear without
  updating the app at all. No version number has to be bumped for that.
  Writing to the config folder instead of back into the project folder is what
  makes this work for **AppImage** users (read-only squashfs), AUR installs
  (root-owned under `/usr`) and git checkouts (a modified file would break the
  next `git pull --ff-only`) alike. A network error never destroys the working
  list – the previous one keeps being used. The optional `version` key only
  decides one thing: a later app release shipping a strictly newer catalogue
  wins over the cache, which is then discarded. An ⬆ button at the top of the
  Plugins page still offers the update when the check runs outside the store.
- **New `slider` setting type** for plugins, rendered as a real slider with a
  live value label next to it (optional `suffix` for the label).
- **Nested plugin settings** via an optional `depends` key: a row is indented
  under its parent switch and hidden while that switch is off, the same way
  *Max length* sits under *Song title* on the MediaPlay card.

### Changed
- **World Stats 1.1.0:** the maximum world-name length is a slider now instead
  of a number field, and it sits indented under *World name*, appearing only
  while that is switched on. Preview image (`logo.png`) shown in the store.
- **Sidebar order:** Plugins now sits above Options.
- Store previews fall back to conventional file names (`logo.png`,
  `preview.png`, `icon.png`, ...) when a manifest's `image` key is missing or
  points at a file that is not there.
- The plugin store deliberately avoids the GitHub API. That endpoint allows 60
  unauthenticated requests per hour per IP, which one store refresh would eat
  into; manifests come from `raw.githubusercontent.com` and downloads from
  `codeload.github.com`, both plain file fetches with no such limit.

### Fixed
- **AppImage now runs on Linux Mint / Ubuntu 22.04+ (FUSE 2 *and* FUSE 3).**
  The build used the AppImageKit runtime, which loads `libfuse.so.2` via
  `dlopen()`. Distributions that ship only fuse3 – Mint 21+ among them –
  failed with `dlopen(): error loading libfuse.so.2` before a single line of
  Python ran. The build script now embeds the statically linked
  [type2-runtime](https://github.com/AppImage/type2-runtime), which carries its
  own FUSE and picks whatever `fusermount*` the system provides, and verifies
  after the build that no `libfuse.so.2` reference is left.
- **Readable errors instead of Qt tracebacks.** `AppRun` checks for the Qt6
  system libraries that Mint/Ubuntu do not install by default (notably
  `libxcb-cursor0`) and names the package to install.
- **`install.sh` now actually installs the Qt libraries it lists.** The
  dependency step was guarded by `[ -t 0 ]`, which is never true for
  `curl -sL ... | bash` – the very install path the README recommends. So the
  step printed "Running non-interactively" and skipped itself, and the first
  launch died with "xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb
  platform plugin". The prompt now goes through `/dev/tty`, which still works
  inside a pipe, and with no terminal at all the libraries are installed by
  default (`DREAMCHATBOX_SKIP_SYSDEPS=1` opts out, `DREAMCHATBOX_ASSUME_YES=1`
  skips the question). Same bug silently skipped `python3-venv`, which then
  broke the venv step on Debian-based systems.
- **`install.sh` verifies the GUI before claiming success.** After building the
  venv it runs `ldd` against Qt's `libqxcb.so`, maps any missing soname to the
  right package name for apt/pacman/dnf/zypper and prints the exact command.
  Works without a display, so it is also useful over SSH.
- **Complete xcb dependency list.** `libxcb-cursor0` alone is not enough;
  `libxcb-icccm4`, `libxcb-image0`, `libxcb-keysyms1`, `libxcb-render-util0`,
  `libxcb-shape0`, `libxcb-xkb1` and `libxkbcommon-x11-0` are now installed too,
  and the AUR package gained the matching `xcb-util-*` and `libxkbcommon-x11`
  dependencies.
- **Python version mismatch is caught up front.** The bundled C extensions
  (`PyQt6.sip`, `zeroconf`) are built for the Python minor version of the build
  machine. The AppImage now records that version, looks for a matching
  `pythonX.Y` on the target system, and otherwise says plainly what is wrong
  instead of dying with an `ImportError`.

## [v1.2.0] – 2026-07-29

First non-alpha release. The big change is a **plugin system**: features that
only some people need no longer have to live in the app itself.

### Added
- **Plugin system.** A new **Plugins** page in the sidebar. Plugins live in
  `~/.config/OSC-DreamChatbox/plugins/<id>/` as a folder with a `plugin.json`
  and a python file, are loaded dynamically via `importlib`, and can be
  installed from a `.zip`, switched on/off and deleted from the UI. Every call
  into plugin code is wrapped, so a broken plugin logs a traceback to the debug
  console and is skipped – it can never take the chatbox down.
- **Every plugin is a placeholder.** An active plugin is addressable as
  `{plugin_id}` in Personal Status texts, in the MediaPlay/Hardware custom
  strings and in All in one; anything it exports additionally shows up as
  `{plugin_id_key}`. A plugin may also claim unprefixed names via
  `global_placeholders` – a value the app itself produced always wins, so a
  plugin can never hijack a built-in placeholder.
- **Per-plugin Settings block.** Same expander as the Apps cards, with an
  *Own line in the chatbox* toggle (off = the plugin only feeds placeholders
  and stops printing itself), a *Custom string* with reset and emoji buttons,
  and the plugin's own options. Those options are declared in `plugin.json`
  (`text`, `bool`, `int`) and rendered automatically, so a plugin author gets a
  settings UI without writing a single line of Qt.
- **World Stats plugin.** Ships the live VRChat info that used to sit in the
  Personal Status card: `{player_in_world}`, `{group_world}`, `{instance_type}`
  and `{realtime}`, plus a combined `{world_stats}` line. Player icon, clock
  format, maximum world-name length and the log folder are configurable, and
  each of the three values can be switched off on its own.
- **Hello World example plugin** demonstrating settings, `get_text()`,
  `get_values()` and the `on_settings()` hook.
- **"Plugins & template" button** on the Plugins page, linking to
  [Dream-Chatbox-Plugins](https://github.com/yakuda-stack/Dream-Chatbox-Plugins)
  – ready-made plugins to download plus the template to start your own.
- **10 switchable All in one templates**, exactly like the Personal Status
  templates: each button keeps its own set of up to 5 strings and its own
  count, so you can flip between a gaming, a music and a minimal layout with
  one click. Existing configs are migrated – your current string lands in
  template 1.

### Changed
- **Plugin settings are stored with the plugin**, in
  `plugins/<id>/configs/config.json` – one file per plugin holding its on/off
  state, custom string and option values. Copy the folder and the settings come
  along; delete it and nothing is left behind. The `configs/` folder is
  preserved when a plugin is re-installed from a newer `.zip`, so an update
  never resets what you configured.
- The app no longer reads VRChat's `output_log` itself. `core/vrchatlog.py` is
  down to the Steam/Proton path discovery that the VRC Picture Folder Fix
  needs; the log watcher and its background thread now ship inside the World
  Stats plugin. Without that plugin installed, the chatbox tails no log file at
  all.
- The preview refresh timer is now driven by active plugins instead of the log
  watcher, so live values like clocks stay current between sends.

### Removed
- **Live info from the Personal Status card.** The *Player in world*, *Group
  world* and *Realtime* checkboxes and the VRChat log folder picker are gone –
  install the **World Stats** plugin instead. The placeholder names are
  unchanged, so existing status texts and All in one strings keep working once
  the plugin is enabled.
- The config keys `status_player_in_world`, `status_group_world`,
  `status_realtime` and `vrchat_log_dir` are no longer used.

### Notes
- Dropping `-alpha` reflects that the feature set is settled, not that every
  edge case is proven. Please keep reporting what breaks.

## [v1.1.5-alpha] – 2026-07-29

### Added
- **Own Google API key for translation.** Selecting *Google Translate* now
  shows an optional **Google API key** field. With a key the app uses the
  official **Google Cloud Translation API v2** – your own project, your own
  quota, covered by Google's Terms of Service. Get one at
  console.cloud.google.com and enable the *Cloud Translation API* for the
  project. The key is stored as `stt_google_key`, masked in the UI, and applies
  live to the translation test, Speech-to-Text and the manual Textbox
  translation.
- **Clear "use at your own risk" warning for the key-less mode.** Leaving the
  field empty keeps the previous behaviour, but the UI now says plainly what
  that means: the request goes to the **unofficial, undocumented** endpoint that
  the Google Translate website uses. It is not an API agreement, everybody
  shares the same anonymous endpoint, and Google can throttle or block it at any
  time – heavy use can get your IP temporarily blocked. The warning switches to
  a green confirmation as soon as a key is entered.
- **`THIRD_PARTY_NOTICES.md`** – full attribution for every dependency, external
  service and system tool, including their licences, the GPL/LGPL source offer
  for the AppImage, and the trademark and independence statements. Linked from
  the README.

### Changed
- **Better error messages for Google translation.** HTTP 429/403 from the
  key-less endpoint is now reported as "blocked/rate-limited – the unofficial
  endpoint is shared by everyone", and a rejected key as "key rejected – check
  the key and make sure the Cloud Translation API is enabled", instead of a raw
  exception. The failing backend still falls back to Lingva as before.
- The Google entry in the translation-service dropdown now reads
  *"Google Translate (direct / fastest, key optional)"*.
- An entered API key is also used when Google is reached as a **fallback**, not
  only when it is the selected service.
- **README:** new *Third-party licenses* pointer in the Legal & Credits section,
  and `THIRD_PARTY_NOTICES.md` added to the project structure listing.
- **Donations now go through Ko-fi.** The in-app *Support on Ko-fi* button on
  the Options page, plus the README support link and badge, all point to
  [ko-fi.com/yakuda_](https://ko-fi.com/yakuda_) instead of PayPal.

### Fixed
- Responses from the official Google API are now HTML-unescaped, so translations
  containing apostrophes or quotes no longer show up as `&#39;` / `&quot;`.

### Fixed
- **AppImage now runs on Linux Mint / Ubuntu 22.04+ (FUSE 2 *and* FUSE 3).**
  The build used the AppImageKit runtime, which loads `libfuse.so.2` via
  `dlopen()`. Distributions that ship only fuse3 – Mint 21+ among them –
  failed with `dlopen(): error loading libfuse.so.2` before a single line of
  Python ran. The build script now embeds the statically linked
  [type2-runtime](https://github.com/AppImage/type2-runtime), which carries its
  own FUSE and picks whatever `fusermount*` the system provides, and verifies
  after the build that no `libfuse.so.2` reference is left.
- **Readable errors instead of Qt tracebacks.** `AppRun` checks for the Qt6
  system libraries that Mint/Ubuntu do not install by default (notably
  `libxcb-cursor0`) and names the package to install.
- **`install.sh` now actually installs the Qt libraries it lists.** The
  dependency step was guarded by `[ -t 0 ]`, which is never true for
  `curl -sL ... | bash` – the very install path the README recommends. So the
  step printed "Running non-interactively" and skipped itself, and the first
  launch died with "xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb
  platform plugin". The prompt now goes through `/dev/tty`, which still works
  inside a pipe, and with no terminal at all the libraries are installed by
  default (`DREAMCHATBOX_SKIP_SYSDEPS=1` opts out, `DREAMCHATBOX_ASSUME_YES=1`
  skips the question). Same bug silently skipped `python3-venv`, which then
  broke the venv step on Debian-based systems.
- **`install.sh` verifies the GUI before claiming success.** After building the
  venv it runs `ldd` against Qt's `libqxcb.so`, maps any missing soname to the
  right package name for apt/pacman/dnf/zypper and prints the exact command.
  Works without a display, so it is also useful over SSH.
- **Complete xcb dependency list.** `libxcb-cursor0` alone is not enough;
  `libxcb-icccm4`, `libxcb-image0`, `libxcb-keysyms1`, `libxcb-render-util0`,
  `libxcb-shape0`, `libxcb-xkb1` and `libxkbcommon-x11-0` are now installed too,
  and the AUR package gained the matching `xcb-util-*` and `libxkbcommon-x11`
  dependencies.
- **Python version mismatch is caught up front.** The bundled C extensions
  (`PyQt6.sip`, `zeroconf`) are built for the Python minor version of the build
  machine. The AppImage now records that version, looks for a matching
  `pythonX.Y` on the target system, and otherwise says plainly what is wrong
  instead of dying with an `ImportError`.

### Notes
- Lingva Translate remains the **default** translation backend – anonymous,
  key-less and without direct Google tracking. Nothing changes for existing
  configs.
- Housekeeping outside the code: the leftover third-party program logos in
  `assets/icons/` and the dead `scripts/dreammanager.py` (it imported a
  `core.addons` module that no longer exists) were removed, `LICENSE` was
  replaced with the verbatim GPL-3.0 text from gnu.org, and the duplicated
  `install.sh` / `build_appimage.sh` copies in the repository root were dropped
  in favour of the ones in `scripts/`. The `scripts/DreamManager` launcher (a
  wrapper around the already-deleted `dreammanager.py`) and the two empty
  `.SRCINFO` placeholders were removed as well – `.SRCINFO` is generated in the
  AUR clone with `makepkg --printsrcinfo`, not kept here.

## [v1.1.4-alpha] – 2026-07-28

### Changed
- **Smoother UI: media and hardware polling moved off the GUI thread.**
  Reading the media player (via D-Bus/MPRIS) and the hardware stats now runs
  in the background. On NVIDIA systems the periodic `nvidia-smi` call, and –
  with several media players open – the D-Bus round-trips, previously ran on
  the interface thread and could make the window stutter every 1–2 seconds.
  They no longer do. A guard skips a new poll while the previous one is still
  in flight, so slow queries can't pile up.
- **Leaner internals (foundation for a plugin system).** The main window
  (~3,600 lines) was split into focused modules – config handling and one
  module per page (Apps, Textbox, Options) – composed via mixins. This is a
  pure restructure with no change in behaviour; it makes the code far easier
  to navigate and prepares a clean place for future per-feature plugins.
- **Less duplicated code.** The repeated background-worker/queue/timer plumbing
  (translation test, text-to-text, update check) now lives in one shared
  helper, and its short-lived timers are disposed of after use instead of
  accumulating on the window.

### Fixed
- **A broken config no longer wipes your settings silently.** If
  `config.json` can't be read (corrupt/invalid JSON), the file is now copied
  to `config.json.bak` and a clear warning is logged *before* the app falls
  back to defaults, so your old settings can be recovered.
- Removed several unused imports and a leftover dead variable.
- The version number shown at startup and in *About* is now consistent with
  the actual release version.

## [v1.1.3-alpha] – 2026-07-27

### Added
- **VRChat Group button** in *Community & Updates*, next to Donate – opens
  the OSC-DreamChatbox VRChat group page.
- **Update check knows how you installed.** *Check for updates* still just
  reports the newest release (it never downloads or overwrites files); now the
  message is tailored: AppImage users get a link to grab the new AppImage from
  the release page, AUR users are told to update via whichever helper they
  actually have installed (auto-detects `yay` or `paru`), and script/source
  users get the `git pull` / `install.sh` hint.
- **Distro-aware system libraries in the installer.** Non-Arch users (e.g.
  Linux Mint) previously had to add libraries by hand. The install script now
  reads `/etc/os-release`, picks the right package manager (apt / dnf /
  zypper / pacman) and offers to install the libraries the app needs —
  PortAudio for the microphone and the Qt `xcb-cursor` library (without which
  Qt6 fails with "Could not load the Qt platform plugin xcb" on X11/non-KDE).
  Interactive runs ask first; piped `curl | bash` runs print the exact
  command instead (so `sudo` never blocks on a password).

### Fixed
- **Installer now pulls the full dependency set.** The one-line `install.sh`
  was missing `zeroconf`, `deepl` and `setproctitle`, which could leave
  OSCQuery, a translation backend and the process name broken. It now
  installs the same packages as the build script.
- **App Tray Fix – smarter replace.** If an old osc-dreamchatbox entry from a
  previous fix is found (a real .desktop file, a symlink pointing elsewhere,
  an absolute Icon= path, or a missing themed icon), the fix deletes it and
  writes a fresh one. An AUR entry (which ships its own icon) is left
  untouched. When running as an AppImage the entry now uses the stable
  `$APPIMAGE` path for `Exec=` instead of the ephemeral mount path.

## [v1.1.2-alpha] – 2026-07-27

### Added
- **Text to Text translation** (community request). The *Speech to Text* card
  is now **To Text** with a main **Speech or Text** mode switch at the top:
  - **Speech to Text** (OFF) – microphone + record button, as before.
  - **Text to Text** (ON) – a text field with Enter/Send instead of the mic.
    Typed messages run through the exact same translation pipeline and OSC
    output as speech, so no duplicated code and no microphone use.
  - thanks on @Algia- on my discord
  The UI adapts to the mode: mic/record widgets show in speech mode, the text
  field in text mode; languages and translation service are shared by both.
- **Show original + translation** toggle: when on and a translation happens,
  the chatbox shows both languages as `source → translation`. Works in both
  Speech-to-Text and Text-to-Text modes.

### Fixed
- **App Tray Fix now actually shows the icon.** The generated `.desktop`
  referenced the icon by absolute path, which KDE/Wayland taskbars usually
  ignore. It now installs the icon into the hicolor theme
  (`~/.local/share/icons/hicolor/256x256/apps/osc-dreamchatbox.png`) and
  references it by name (`Icon=osc-dreamchatbox`), exactly like the AUR
  package. Both install scripts do the same. If an old osc-dreamchatbox
  entry is found (a real .desktop file, a symlink pointing elsewhere, an
  absolute Icon= path, or a missing themed icon), the fix now deletes it and
  writes a fresh one. A full app restart (and one KDE/Wayland re-login) is
  still needed for the taskbar to refresh.
  Thanks on @royalrex25 on my discord

## [v1.1.1-alpha] – 2026-07-27

### Added
- **Desktop integration / App Tray Fix** – install-script users (curl | bash)
  previously got the generic Wayland icon and no application-menu entry
  because they don't receive the AUR `.desktop` file. Fixed two ways:
  - The **install script** now detects the desktop environment and writes a
    canonical `.desktop` into `~/.config/OSC-DreamChatbox/desktop/`, symlinked
    into `~/.local/share/applications/`. Skipped automatically when a system
    package (AUR) already provides the entry.
  - New **App Tray Fix** button on its own row under *Check for updates* in
    the *Community & Updates* card. It first checks whether an entry already
    exists (symlink **or** real file, in the user applications dir **or** a
    system dir) and does nothing if so; otherwise it creates the same
    canonical entry + symlink on demand.
  - Thanks on @royalrex25 in my discord server
- **VRC Picture Folder Fix** – button next to *App Tray Fix* in the
  *Community & Updates* card. Under Proton, VRChat saves camera photos deep
  inside the Steam prefix
  (`…/compatdata/438100/pfx/…/steamuser/Pictures/VRChat`); this replaces that
  folder with a symlink to the real Linux Pictures directory
  (`~/Pictures/VRChat`, honouring `XDG_PICTURES_DIR`), so new photos land
  there directly. Existing photos in the prefix are migrated first. Detects
  Steam via native, Flatpak and `libraryfolders.vdf` locations, repoints a
  wrong symlink, and is a no-op once set up.

### Changed
- **MediaPlay – tidier sub-options.** Sub-options now appear only when their
  parent is enabled, instead of always being visible: *Max length* shows only
  with *Song title*, *Time with seconds* only with *Time*, *Use my own .lrc
  files* only with *Lyrics* (folder row only when both are on), and the whole
  Songbar block (style, size, time position, custom editor) only when
  *Songbar* is enabled.

## [v1.1.0-alpha] – 2026-07-23

### Added
- **Song title length** – new slider under *Song title* in the MediaPlay
  card (`media_title_max`, default 24): set how many characters of the
  title are shown, anywhere from 3 to 64. Applies to the normal media
  line and the `{title}` placeholder

- **Local .lrc files** – new sub-toggle under *Lyrics* in the MediaPlay
  card (`media_lyrics_local`, default OFF): drop your own `.lrc` files
  into a folder and they are used offline, matched by artist/title on
  the filename (`Artist - Title.lrc`, `Title.lrc`, …). A local hit takes
  priority over LRCLIB; LRCLIB stays as the online fallback. Default
  folder is `~/.config/OSC-DreamChatbox/lyrics/`, changeable via a
  *Choose…* / *Open* row that only appears while the toggle is on
- **Personal Status live info** – three new checkboxes, each usable as a
  placeholder inside any status text (e.g. Text 1) AND in All in one:
  - **Player in world** → `{player_in_world}` – number of players in your
    current VRChat instance (incl. yourself)
  - **Group world** → `{group_world}` – the current world name (bonus:
    `{instance_type}` = Public / Friends / Group / Group+ / Invite …)
  - **Realtime** → `{realtime}` – your PC clock (HH:MM)

  World name, instance type and player count are read live from VRChat's
  Proton `output_log` – no VRChat login, no API calls, no rate limits.
  The log folder is auto-detected across the usual Steam locations
  (native, extra library folders, Flatpak) and can be overridden
  manually. The watcher only runs while *Player in world* or *Group
  world* is enabled. Placeholder aliases: `{playerin_word}` `{players}`
  `{player_count}` → `{player_in_world}`; `{world}` `{world_name}` →
  `{group_world}`; `{clock}` `{time_now}` → `{realtime}`. Status texts
  are only run through the template engine when they actually contain a
  `{…}`, so plain texts (e.g. `:3`) are never altered

### Changed
- **Long song titles are cut without a trailing `…`** – the ellipsis
  wasted one of the precious 144 chatbox characters on every long title,
  so the title is now hard-cut at the chosen length (a trailing space is
  trimmed too)
- **Options page order** – *Community & Updates* moved to the top, above
  OSCQuery and the OSC settings

## [v1.0.9-alpha] – 2026-07-17

### Added
- **Time with seconds** – new sub-toggle under Time in the MediaPlay
  card (`media_time_seconds`, default ON): the music timer now shows
  real seconds (`3:27/4:12`, long songs as `h:mm:ss`). Turn it off to
  get the previous hours:minutes style (`0:03/0:04`) back. The toggle
  applies everywhere the time appears: the time line, the time merged
  into the songbar line AND the placeholders `{time}` `{time_status}`
  `{time_end}` `{position}` `{length}`

### Fixed
- **Chatbox is cleared when SendToVRChat is switched OFF**: one empty
  OSC message is sent so the last text disappears from VRChat
  immediately instead of hanging there for minutes. The same clear
  also runs when the app is closed

## [v1.0.8-alpha] – 2026-07-16

### Fixed
- **Crash (SIGSEGV) with the debug console open**: background
  threads (lyrics fetcher, OSCQuery/mDNS listeners) wrote their log
  messages directly into the Qt debug console – GUI calls from a
  non-GUI thread crash Qt. `log()` is now thread-safe: messages are
  delivered to the console via a queued Qt signal, so they always
  arrive in the GUI thread no matter which thread logs. Thanks for
  the report!

## [v1.0.7-alpha] – 2026-07-16

### Added
- **Lyrics in MediaPlay** 🎶 – shows the current line of the song you
  are listening to, perfectly synced to the playback position:
  - New **"Lyrics" checkbox** in the MediaPlay card (between Time and
    Songbar). The line appears with a ♪ prefix between title/time and
    the songbar
  - Lyrics come from **[LRCLIB](https://lrclib.net)** – an open,
    key-less database of `.lrc` files with exact timestamps. Works
    with EVERY MPRIS player (Spotify, YT Music, browsers, VLC, …)
  - New placeholder **`{lyrics}`** for the MediaPlay custom string
    and All-in-one (aliases: `{lyric}`, `{songtext}`, `{liedtext}`).
    `{lyrics}` only fills in while the checkbox is checked
  - **Performance-first**: unchecked = ZERO network requests. Checked
    = one lookup per song in a background thread, cached (including
    negative results, so unknown songs are never re-queried)
  - **Fuzzy matching** so platform title variations still hit:
    noise like `(Official Video)`, `[4K Remastered]`, `feat. XY`,
    `- Topic` is stripped, then a 4-step chain from exact lookup to
    scored search runs. Search hits must match the title START
    (prefix) and stay within ±10 s of the song duration – so
    third-party uploads match, but wrong songs/remixes never do
    (`core/lyrics.py`, no new dependencies)

Huge thanks to **ewephoric (stupid lamb thing)** on Discord for the
idea! 🐑💙

## [v1.0.6-alpha] – 2026-07-15

### Added
- **Songbar size slider (30–100 %)** in the MediaPlay card – a shorter
  bar leaves room for the time on the same line (`media_bar_size`)
- **Time position** dropdown (`media_time_pos`) – the time can now be
  merged INTO the songbar line so the chatbox stays at two lines
  instead of three:
  - `Own line` (default, previous behaviour): time sits on the
    artist/title line, bar gets its own line
  - `Before bar`: `0:27/1:06 ▓▓▓▓░░░░`
  - `After bar`: `▓▓▓▓░░░░ 0:27/1:06`
  - `Around bar`: `0:27▓▓▓▓░░░░1:06`
  A live preview under the dropdown shows the resulting line + its
  character count
- **New placeholders `{time_status}` (current position) and
  `{time_end}` (when the song ends)** for the MediaPlay custom string
  and All-in-one – clearer aliases of `{position}` / `{length}`

## [v1.0.5-alpha] – 2026-07-12

### Changed
- **License changed from MIT to GPL-3.0-or-later** (LICENSE, README
  badge, PKGBUILD). Releases up to and including v1.0.4-alpha remain
  MIT; this release and everything after is GPL-3.0-or-later

## [v1.0.4-alpha] – 2026-07-12

### Added
- **AUR packaging**: `packaging/aur/PKGBUILD` + `.desktop` file for
  publishing as `osc-dreamchatbox` in the Arch User Repository
  (installs to /usr/share, launcher in /usr/bin, hicolor icon)
- **README screenshots** (assets/p1–p7)
- **Process name**: the app now shows up as `OSC-DreamChatbox`
  instead of `python` in htop/btop/KDE system monitor
  (setproctitle for the command line + prctl PR_SET_NAME for the
  kernel comm name)
- **Personal Status text templates (1–10)**: exclusive toggle row at
  the top of the card – enabling one template switches all others
  off. Every template stores its OWN set of up to 20 texts + count,
  so you can flip between predefined text sets you define yourself.
  Old configs are migrated into template 1 automatically
- **Personal Status: up to 20 texts** (was 10); AIO placeholders now
  go up to `{text_20}`. The text fields fold in/out ("Texts (1–20)"
  expander) so the card stays compact
- **Speech to Text: microphone selection** dropdown (system default +
  every input device, with refresh button). The device is stored by
  NAME and re-resolved on every recording start, so shifting device
  indexes between sessions can't pick the wrong mic

### Changed
- "Text Apps" page renamed back to **Apps**
- **Native OSCQuery smoother**: stays ON by default; the mDNS
  discovery is event-driven (no active re-scanning), the status
  poll only repaints on changes and relaxes from 2 s to 10 s once
  VRChat is found – near-zero idle cost

### Fixed
- **LibreTranslate integration hardened** (local server worked in the
  browser but the app fell back): default URL is now
  `http://127.0.0.1:5000` (avoids localhost/IPv6 mismatches), URLs
  typed without a scheme get `http://` prepended, the REAL server
  error message (`{"error": …}` body) is surfaced instead of a
  generic HTTP code, and a 400 for an explicit source language
  triggers one automatic retry with auto-detect (like the web UI)
- New **🧪 Test button** next to the translation-service dropdown:
  sends a test phrase through the selected service and shows the
  translation or the exact error in the hint line

### Changed
- **Translation reworked into a four-tier system** (dropdown
  "Translation service" replaces the old DeepL checkbox; modular
  backends in `core/translators.py` with one unified
  `translate(text, source, target)` interface):
  1. **Lingva Translate** (new default) – anonymous proxy
     (lingva.adminforge.de), no API key, no direct Google tracking
  2. **Google Translate (direct)** – the un-anonymised gtx web
     endpoint for minimal latency (fast live chat; user's choice)
  3. **LibreTranslate** (optional/local) – local instance for 100%
     offline translation (URL field, default http://localhost:5000)
     with a **Start/Stop server button**: once LibreTranslate is
     installed (manually: `pip install libretranslate`) the button
     "🚀 Start LibreTranslate" appears (spawns the server
     detached, status line shows "⏳ Starting …" and then
     "✅ Server running on port X"), while running it turns into a
     red "🛑 Stop LibreTranslate" (clean process-group terminate).
     A watchdog reports if the server dies; on app close a running
     server is always shut down – no orphaned processes.
     The automatic pip installation from within the app was removed
  4. **DeepL API** (optional/power user) – official `deepl` library
     with typed error handling (quota exceeded, invalid key, rate
     limit); raw-HTTP fallback when the library is missing
  If the chosen method fails for any reason, the chain automatically
  falls back to **Lingva first, then direct Google** – speech-to-text
  never crashes on a dead API.
  Old configs with the DeepL checkbox enabled are migrated to the
  DeepL method automatically. The direct free Google endpoint was
  removed.

## [v1.0.2-alpha] – 2026-07-08

### Added
- **Native OSCQuery** (`core/oscquery.py`): the app no longer binds
  hard-coded ports. On startup it picks a free dynamic UDP port,
  serves OSCQuery HOST_INFO over HTTP and registers both via
  mDNS/Zeroconf; the running VRChat instance is auto-discovered and
  its REAL OSC input port is used as send target (manual target stays
  as fallback). Toggle + live status on the Options page. Needs the
  `zeroconf` package (bundled by install/build scripts).
- **OSCQuery Fix UI reworked**: collapsible "Show supported programs"
  expander with a compact, scrollable list (fixed max height) –
  clicking a program folds its details (path + parameter) in and out
- **Custom songbar style**: new "Custom …" entry in the songbar style
  dropdown with its own editor (start/end brackets, filled/empty
  characters, optional travelling knob) and live preview – build your
  own bar, stored as `media_bar_custom`
- **OSCQuery Fix** on the Options page: one button writes the OSCQuery
  parameter directly into the config of every supported program
  (other settings in the file stay untouched). Supported programs
  live in a single, easily extensible `core/queryfix.py`:
  - OSCLeash    – `~/.config/OSCLeash/Config.json` → `"UseOSCQuery": true`
  - OscGoesBrrr – `~/.config/OscGoesBrrr/config.json` → `"useOscQuery": true`

## [v1.0.1-alpha] – 2026-07-07

### Removed
- **OSC Routing** removed completely (UDP relay, source list, managed
  programs, `core/oscrouter.py`, all `route_*` config keys – old keys
  in existing configs are ignored on load)
- **Addons / OSC Apps** removed completely (catalog, installer,
  update checks, Start Programs, `.desktop`/taskbar integration)
- **DreamManager CLI** removed completely (`scripts/dreammanager.py`,
  `start-programs`, `start-all`, …) – `osc_dreamchatbox.py` is a pure
  GUI starter again
- Reason: external OSC tools handle port discovery via **OSCQuery**
  nowadays, so the built-in relay/installer were unnecessary ballast.
  Leftovers of earlier addon installs under
  `~/.config/OSC-DreamChatbox/tool` + `taskbar` and symlinks in
  `~/.local/share/applications` can be deleted manually.

### Changed
- "Apps" page renamed to **Text Apps**
- Project restructured into `core/`, `ui/`, `assets/`, `scripts/`
- **Personal Status**: with multiple texts the rotation now switches
  **randomly** instead of sequentially (never the same text twice in
  a row)
- **MediaPlay time without seconds**: the music timer shows hours and
  minutes only (`h:mm`, e.g. `0:03/0:04`) – applies to the time line
  and the `{position}` / `{length}` / `{time}` placeholders
- Window/taskbar icon is now loaded from `assets/icon.png`
  (falls back to the project root for old checkouts)

### Added
- **6 selectable songbar styles** (dropdown "Songbar style" in the
  MediaPlay card, stored as `media_bar_style` 0–5), also used by the
  `{bar}` placeholder in custom strings / AIO:
  1. `[───●────────────────]`
  2. `──■──` (compact slider)
  3. `[████████░░░░░░░░░░░░]` (default)
  4. `▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱`
  5. `🎵🎵🎵🎵🎵🎵🎵─────────────`
  6. `▓▓▓▓▓▓▓▓░░░░░░░░░░░░` (classic look of earlier versions)

## [v1.0.0-alpha] – 2026-07-05

First public release. 🎉

### Apps
- **Personal Status**: 1–10 rotating texts, adjustable interval, icon picker
- **MediaPlay**: current song via MPRIS (Spotify, YT Music, browsers, VLC, …),
  artist/title/time/songbar toggles, 🎵 media icon, custom string
- **Hardware**: GPU/VRAM/CPU/RAM stats (AMD sysfs + NVIDIA nvidia-smi),
  auto/custom names, °C or 🔥 temps, custom string with `{temp_icon}`
- **All in one**: combine every app into one master string, up to 5 rotating
  layouts with all placeholders (`{text_1}…{text_10}`, media, hardware)
- Drag & drop card order = line order in VRChat

### Textbox
- Free chat field with instant send + app pausing
- Editable presets (5 default, up to 20)
- **Speech to Text**: realtime transcription (15 languages), live translation
  (13 output languages), optional DeepL API with Google fallback,
  "Block apps" master switch
- Drag & drop card order

### Core
- Slim Chatbox mode (BlankEgg trick) – default ON, suffix survives the
  144-char limit
- Preview with character counter, debug console (capped at 500 lines)
- Update checker, Discord & donate links
- Performance: debounced config writes, cached D-Bus player, cached hwmon
  sensors, timers only run when actually needed
- All settings persisted to `~/.config/OSC-DreamChatbox/config.json`
