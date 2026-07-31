<div align="center">

# 🌙 OSC-DreamChatbox

**A simple, clean VRChat OSC chatbox companion for Linux.**
*The native Linux alternative to [MagicChatbox](https://github.com/BoiHanny/vrcosc-magicchatbox) (VRCOSC) – which is Windows-only.*

[![License: GPL--3.0--or--later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux-green.svg)]()
[![Python](https://img.shields.io/badge/Python-3.10%2B-yellow.svg)]()
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2.svg)](https://discord.gg/X5TaN4A47h)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-FF5E5B.svg)](https://ko-fi.com/yakuda_)

</div>

---

## ✨ What can it do?

Everything you know from MagicChatbox/VRCOSC on Windows – status rotation, now-playing, hardware stats, speech-to-text, the slim-chatbox trick – built natively for Linux (PyQt6, MPRIS/D-Bus, sysfs).

*(Personal Status, MediaPlay, Hardware and All-in-one live on the **Apps** page.)*

### 📝 Personal Status
- **10 switchable text templates**, each with its own set of up to **20 texts** – exclusive toggles, enabling one switches the others off
- Adjustable change interval; texts switch **randomly** (never the same one twice in a row)
- Text fields fold in/out so the card stays compact
- Built-in **icon picker** (🔥 🎵 🎮 …) for every text field

### 🎵 MediaPlay
- Shows the song you are listening to – **Spotify, YT Music, browsers, VLC, any player** (via MPRIS/D-Bus, no extra setup)
- Toggle artist / title (max 24 chars) / time / progress songbar individually
- Time is shown **without seconds** (hours:minutes, e.g. `0:03/0:04`)
- **Songbar size slider (30–100 %)** and **time position** – put the time before, after or around the bar so everything fits on **one line**:
  - `0:27/1:06 ▓▓▓▓░░░░` · `▓▓▓▓░░░░ 0:27/1:06` · `0:27▓▓▓▓░░░░1:06`
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

- Custom string with placeholders: `{artist} {title} {time} {time_status} {time_end} {bar} {icon_sound}`

### 🖥️ Hardware
- Live **GPU / VRAM / CPU / RAM** stats (AMD via kernel sysfs, NVIDIA via nvidia-smi)
- Auto-detected or custom GPU/CPU names, temps as `°C` or 🔥
- Custom string with placeholders: `{gpu_name} {gpu_usage} {gpu_temp} {temp_icon} {vram_usage} {cpu_name} {cpu_usage} {cpu_temp} {ram_usage} {ram_type}`

### 🧩 All in one (AIO)
- Combine **everything into one master string** – up to 5 rotating layouts
- All placeholders from every app work here, incl. `{text_1}…{text_20}`, `{time_status}`, `{time_end}`

### 💬 Textbox
- Free chat field → sends straight to VRChat (apps pause briefly so nothing overwrites your message)
- **Editable presets** (default 5, expandable to 20) with one-click send
- **Speech to Text** 🎤 – speak, it transcribes in realtime and sends to VRChat
  - **Microphone selection** dropdown (system default or any input device)
  - 15 input languages, **live translation** to 13 output languages
  - **Four selectable translation services**: Lingva Translate (default – anonymous proxy, no key, no Google tracking), Google Translate direct (fastest, no proxy hop), LibreTranslate (local instance, 100% offline – install once with `pip install libretranslate`, then a **Start/Stop server button** appears right in the UI; the server is shut down automatically when the app closes) or the official DeepL API (own key, typed error handling)
  - Automatic fallback chain if the chosen service fails: **Lingva first, then direct Google** (e.g. DeepL monthly limit reached or local instance down)
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

## 📸 Screenshots

<table>
  <tr>
    <td><b>Apps – Personal Status</b><br><img src="assets/p1.png" alt="Personal Status" width="600"/></td>
    <td><b>Hardware Monitor</b><br><img src="assets/p2.png" alt="MediaPlay" width="600"/></td>
    <td><b>MediaPlay & Songbar</b><br><img src="assets/p3.png" alt="Hardware" width="600"/></td>
  </tr>
  <tr>
    <td><b>All in one (AIO)</b><br><img src="assets/p4.png" alt="All in one" width="600"/></td>
    <td><b>Speech to Text </b><br><img src="assets/p5.png" alt="Textbox" width="600"/></td>
    <td><b>Textbox & Presets</b><br><img src="assets/p6.png" alt="Speech to Text" width="600"/></td>
  </tr>
  <tr>
    <td><b>Options – OSCQuery</b><br><img src="assets/p7.png" alt="Options" width="600"/></td>
    <td><b>plugins – Installed</b><br><img src="assets/p8.png" alt="Options" width="600"/></td>
    <td><b>plugins – Store</b><br><img src="assets/p9.png" alt="Options" width="600"/></td>
  </tr>
</table>

## 🚀 Installation

### Arch Linux / CachyOS (AUR) — recommended
Available on the **[AUR](https://aur.archlinux.org/packages/osc-dreamchatbox)** – install with any AUR helper:
```bash
yay -S osc-dreamchatbox      # or: paru -S osc-dreamchatbox
```
<details>
<summary>Without an AUR helper (plain <code>makepkg</code>)</summary>

```bash
git clone https://aur.archlinux.org/osc-dreamchatbox.git
cd osc-dreamchatbox
makepkg -si
```
</details>

### One-line install (any distro)
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

### Optional features
| Feature | Needs |
|---|---|
| Speech to Text | `SpeechRecognition` + `pyaudio` (Arch: `python-pyaudio`) |
| DeepL translation | `deepl` (official library, in requirements.txt) |
| Offline translation | local LibreTranslate: `pip install libretranslate`, then run `libretranslate` |
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
│   ├── translators.py    #   translation backends (Lingva/Google/Libre/DeepL)
│   ├── mediafetch.py     #   MPRIS/D-Bus media fetcher
│   ├── hardware.py       #   CPU/RAM/GPU monitoring
│   └── speechtotext.py   #   speech recognition + translation
├── ui/                   # UI widgets & stylesheet
│   ├── mainwindow.py     #   main window (Apps, Textbox, Options)
│   └── ui_main.py
├── assets/               # icons & images
│   └── icon.png          #   window/taskbar icon (loaded from here)
├── packaging/            # AUR PKGBUILD + .desktop file
├── scripts/              # install & build scripts
│   ├── install.sh
│   ├── build-appimage.sh   (PyInstaller one-file build)
│   └── build_appimage.sh   (bundled-source build)
├── start.sh              # run from a local venv
├── requirements.txt
├── LICENSE               # GPL-3.0
└── THIRD_PARTY_NOTICES.md   # dependency & service attribution
```

---

## ⚠️ Important

**OSC must be enabled in VRChat**: Action Menu (radial) → **Options → OSC → Enabled**

Default target is `127.0.0.1:9000`. VRChat chatbox limit is 144 characters (the slim trick uses 2 of them).

---

## ❤️ Support

- 💬 [Discord](https://discord.gg/X5TaN4A47h)
- ☕ [Support me on Ko-fi](https://ko-fi.com/yakuda_)


## Legal & Credits

* **Independence:** OSC Dream Chatbox is an independent open-source implementation and is not affiliated with, endorsed by, or using code from MagicChatbox.
* **Trademarks:** VRChat is a registered trademark of VRChat Inc. This project is an independent third-party tool and is not affiliated with or endorsed by VRChat Inc.
* **Lyrics:** Song lyrics displayed by the app are provided via LRCLIB and remain the intellectual property of their respective copyright holders.
* **Translation Endpoints:** Lingva is the default and needs no key. If you pick *Google Translate* you can enter your **own API key**, which routes the request through the official Google Cloud Translation API (your project, your quota). Without a key the app falls back to the unofficial, undocumented Google endpoint – shared by everyone and throttled or blocked by Google at any time, so **use at your own risk**. For heavy or reliable use, enter an API key or run LibreTranslate locally.
* **Third-party licenses:** A full list of every dependency, external service and system tool – with licenses, attribution and the GPL/LGPL source offer for the AppImage – is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).


## 📄 License

GPL-3.0-or-later – see [LICENSE](LICENSE).
Copyright (C) 2026 yakuda.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. It is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.

Third-party dependencies and services are documented in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

