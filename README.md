<div align="center">

# 🌙 OSC-DreamChatbox

**A simple, clean VRChat OSC chatbox companion for Linux.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux-green.svg)]()
[![Python](https://img.shields.io/badge/Python-3.10%2B-yellow.svg)]()
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2.svg)](https://discord.gg/X5TaN4A47h)

</div>

---

## ✨ What can it do?

*(Personal Status, MediaPlay, Hardware and All-in-one live on the **Text Apps** page.)*

### 📝 Personal Status
- Up to **10 status texts** with an adjustable change interval
- Texts switch **randomly** (never the same one twice in a row)
- Built-in **icon picker** (🔥 🎵 🎮 …) for every text field

### 🎵 MediaPlay
- Shows the song you are listening to – **Spotify, YT Music, browsers, VLC, any player** (via MPRIS/D-Bus, no extra setup)
- Toggle artist / title (max 24 chars) / time / progress songbar individually
- Time is shown **without seconds** (hours:minutes, e.g. `0:03/0:04`)
- **7 songbar styles (6 presets + custom)**:

  | # | Style |
  |---|---|
  | 1 | `[───●────────────────]` |
  | 2 | `──■──` |
  | 3 | `[████████░░░░░░░░░░░░]` |
  | 4 | `▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱` |
  | 5 | `🎵🎵🎵🎵🎵🎵🎵─────────────` |
  | 6 | `▓▓▓▓▓▓▓▓░░░░░░░░░░░░` (classic) |
  | 7 | **Custom** – build your own (brackets, filled/empty chars, optional knob) with live preview |

- Custom string with placeholders: `{artist} {title} {time} {bar} {icon_sound}`

### 🖥️ Hardware
- Live **GPU / VRAM / CPU / RAM** stats (AMD via kernel sysfs, NVIDIA via nvidia-smi)
- Auto-detected or custom GPU/CPU names, temps as `°C` or 🔥
- Custom string with placeholders: `{gpu_name} {gpu_usage} {gpu_temp} {temp_icon} {vram_usage} {cpu_name} {cpu_usage} {cpu_temp} {ram_usage} {ram_type}`

### 🧩 All in one (AIO)
- Combine **everything into one master string** – up to 5 rotating layouts
- All placeholders from every app work here, incl. `{text_1}…{text_10}`

### 💬 Textbox
- Free chat field → sends straight to VRChat (apps pause briefly so nothing overwrites your message)
- **Editable presets** (default 5, expandable to 20) with one-click send
- **Speech to Text** 🎤 – speak, it transcribes in realtime and sends to VRChat
  - 15 input languages, **live translation** to 13 output languages
  - Optional **DeepL API** support (own key) for better quality, with Google fallback
  - "Block apps" toggle that pauses all automatic senders while you talk
- All cards freely **drag & drop reorderable**

### 🥚 Slim Chatbox (default ON)
- Appends the invisible characters `\u0003\u001f` so VRChat renders a **slim bar instead of the huge box** (the hidden "BlankEgg" trick from MagicChatbox – here it's just a normal setting)
- The suffix is guaranteed to survive even at the 144-char limit

### 📡 Native OSCQuery (Options page)
- No hard-coded ports anymore: the app picks a **free dynamic port**, registers itself via **mDNS/Zeroconf** (`_oscjson._tcp` + `_osc._udp`) and serves OSCQuery `HOST_INFO` over HTTP
- The running **VRChat instance is auto-discovered** and its real OSC input port is used automatically – the manual target is only a fallback
- Toggle + live status on the Options page; requires the `zeroconf` package

### 🔧 OSCQuery Fix (Options page)
- One button enables OSCQuery directly in the config of every supported program – other settings stay untouched
- Currently supported: **OSCLeash** (`~/.config/OSCLeash/Config.json` → `"UseOSCQuery": true`) and **OscGoesBrrr** (`~/.config/OscGoesBrrr/config.json` → `"useOscQuery": true`)
- Compact UI: collapsible "Show supported programs" expander with a scrollable list; click a program to fold its details (path + parameter) in/out
- Easily extensible: all programs live in a single file, `core/queryfix.py`

### More
- Drag & drop card order = line order in VRChat
- Character counter with limit warning
- Debug console, update checker, dark UI, everything saved to `~/.config/OSC-DreamChatbox/config.json`

> ℹ️ The former **OSC Routing** and **Addons/OSC Apps** features were removed – external tools (OSCLeash, face tracking, …) handle port discovery via **OSCQuery** nowadays, so the built-in relay and installer were unnecessary ballast.

---

## 🚀 Installation

### One-line install
```bash
curl -sL https://raw.githubusercontent.com/yakuda-stack/OSC-DreamChatbox/main/scripts/install.sh | bash
```
Then launch **OSC DreamChatbox** from your app menu or run `osc-dreamchatbox`.

### Manual (any distro)
```bash
git clone https://github.com/yakuda-stack/OSC-DreamChatbox.git
cd OSC-DreamChatbox
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python osc_dreamchatbox.py
```

### Arch Linux packages (alternative)
```bash
sudo pacman -S python-pyqt6 python-pyaudio mesa-utils xdotool
yay -S python-python-osc
```

### Optional features
| Feature | Needs |
|---|---|
| Speech to Text | `SpeechRecognition` + `pyaudio` (Arch: `python-pyaudio`) |
| Exact GPU name | `mesa-utils` (glxinfo) |
| NVIDIA stats | `nvidia-smi` (driver package) |

---

## 📁 Project structure

```
OSC-DreamChatbox/
├── osc_dreamchatbox.py   # entry point (GUI starter)
├── core/                 # backend logic
│   ├── constants.py      #   app name, version, paths
│   ├── textutils.py      #   time format, songbar styles, templates
│   ├── queryfix.py       #   OSCQuery fixer (supported programs list)
│   ├── oscquery.py       #   native OSCQuery (mDNS + dynamic ports)
│   ├── mediafetch.py     #   MPRIS/D-Bus media fetcher
│   ├── hardware.py       #   CPU/RAM/GPU monitoring
│   └── speechtotext.py   #   speech recognition + translation
├── ui/                   # UI widgets & stylesheet
│   ├── mainwindow.py     #   main window (Text Apps, Textbox, Options)
│   └── ui_main.py
├── assets/               # icons & images
│   └── icon.png          #   window/taskbar icon (loaded from here)
├── scripts/              # install & build scripts
│   ├── install.sh
│   ├── build-appimage.sh   (PyInstaller one-file build)
│   └── build_appimage.sh   (bundled-source build)
├── start.sh              # run from a local venv
└── requirements.txt
```

---

## ⚠️ Important

**OSC must be enabled in VRChat**: Action Menu (radial) → **Options → OSC → Enabled**

Default target is `127.0.0.1:9000`. VRChat chatbox limit is 144 characters (the slim trick uses 2 of them).

---

## ❤️ Support

- 💬 [Discord](https://discord.gg/X5TaN4A47h)
- ☕ [Donate via PayPal](https://paypal.me/riesensika)

## 📄 License

MIT – see [LICENSE](LICENSE).
