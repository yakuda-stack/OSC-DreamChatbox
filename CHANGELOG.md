# Changelog

All notable changes to OSC-DreamChatbox are documented here.

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

### OSC Routing
- UDP relay: catch other OSC programs and forward bundled to VRChat
- Live program list with per-source blocking
- Managed programs: launch AppImage/.sh/commands from inside the app,
  per-program debug console with live output capture

### Core
- Slim Chatbox mode (BlankEgg trick) – default ON, suffix survives the
  144-char limit
- Preview with character counter, debug console (capped at 500 lines)
- Update checker, Discord & donate links
- Performance: debounced config writes, cached D-Bus player, cached hwmon
  sensors, timers only run when actually needed
- All settings persisted to `~/.config/OSC-DreamChatbox/config.json`
