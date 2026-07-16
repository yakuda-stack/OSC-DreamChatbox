# Changelog

All notable changes to OSC-DreamChatbox are documented here.

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
