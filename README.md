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

### 📝 Personal Status
- Up to **10 rotating status texts** with an adjustable change interval
- Built-in **icon picker** (🔥 🎵 🎮 …) for every text field

### 🎵 MediaPlay
- Shows the song you are listening to – **Spotify, YT Music, browsers, VLC, any player** (via MPRIS/D-Bus, no extra setup)
- Toggle artist / title (max 24 chars) / time / progress songbar individually
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

### 🎛️ OSC Routing
- Tiny **UDP relay**: other OSC programs (OSC Leash, face tracking, …) send to the router, it forwards everything bundled through one connection to VRChat – no more port conflicts
- Live list of connected programs with per-program blocking
- **Managed programs**: add AppImages/.sh/commands, start & stop them from inside the app, per-program **debug console** with live output

### 🥚 Slim Chatbox (default ON)
- Appends the invisible characters `\u0003\u001f` so VRChat renders a **slim bar instead of the huge box** (the hidden "BlankEgg" trick from MagicChatbox – here it's just a normal setting)
- The suffix is guaranteed to survive even at the 144-char limit

### More
- Drag & drop card order = line order in VRChat
- Character counter with limit warning
- Debug console, update checker, dark UI, everything saved to `~/.config/OSC-DreamChatbox/config.json`

---

## 🚀 Installation

### One-line install
```bash
curl -sL https://raw.githubusercontent.com/yakuda-stack/OSC-DreamChatbox/main/install.sh | bash
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

## ⚠️ Important

**OSC must be enabled in VRChat**: Action Menu (radial) → **Options → OSC → Enabled**

Default target is `127.0.0.1:9000`. VRChat chatbox limit is 144 characters (the slim trick uses 2 of them).

---

## ❤️ Support

- 💬 [Discord](https://discord.gg/X5TaN4A47h)
- ☕ [Donate via PayPal](https://paypal.me/riesensika)

## 📄 License

MIT – see [LICENSE](LICENSE).
