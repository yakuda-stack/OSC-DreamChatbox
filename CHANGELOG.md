# Changelog

All notable changes to OSC-DreamChatbox are documented here.

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
