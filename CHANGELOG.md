# Changelog

All notable changes to OSC-DreamChatbox are documented here.

## [v1.0.3-alpha] – 2026-07-2026

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
