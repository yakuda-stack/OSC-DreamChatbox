"""
core/notifysound.py - the app's own notification sound (v1.6.5)

VRChat's chatbox sound is heard by everyone nearby; this one plays only
on your PC. Either a WAV you pick or a short built-in two-tone chime,
generated once into the config folder (no sound file to ship).

Played by whatever is there, no extra dependency:
    Windows  winsound (standard library)
    Linux    pw-play (PipeWire) -> paplay (PulseAudio) -> aplay (ALSA)
    macOS    afplay
Always in the background - never blocks the send.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import math
import shutil
import struct
import subprocess
import threading
import wave
from pathlib import Path

from core.osinfo import IS_MACOS, IS_WINDOWS, subprocess_flags

RATE = 44100


def chime_path() -> Path:
    """The built-in chime, written on first use."""
    from core.constants import CONFIG_DIR
    path = Path(CONFIG_DIR) / "notify_chime.wav"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        frames = bytearray()
        # two short notes (A5, E6), each fading out
        for freq, dur in ((880.0, 0.11), (1318.5, 0.22)):
            n = int(RATE * dur)
            for i in range(n):
                env = math.exp(-5.0 * i / n) * min(1.0, i / 200)
                val = 0.35 * env * math.sin(2 * math.pi * freq * i / RATE)
                frames += struct.pack("<h", int(val * 32767))
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(bytes(frames))
    return path


def _player(path: str):
    if IS_WINDOWS:
        return None
    if IS_MACOS and shutil.which("afplay"):
        return ["afplay", path]
    for name in ("pw-play", "paplay", "aplay"):
        exe = shutil.which(name)
        if exe:
            return [exe, "-q", path] if name == "aplay" else [exe, path]
    return None


def play(file: str = "", log=lambda s: None):
    """Plays `file` (empty / missing = built-in chime). Never raises."""
    def work():
        try:
            path = Path(file).expanduser() if file else None
            if path is None or not path.is_file():
                path = chime_path()
            if IS_WINDOWS:
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME
                                   | winsound.SND_NODEFAULT)
                return
            argv = _player(str(path))
            if argv is None:
                log("Notification sound: no player found "
                    "(pw-play / paplay / aplay)")
                return
            subprocess.run(argv, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15,
                           **subprocess_flags())
        except Exception as e:      # noqa: BLE001
            log(f"Notification sound: {e}")
    threading.Thread(target=work, daemon=True).start()
