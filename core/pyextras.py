"""
core/pyextras.py - a private site-packages folder for optional python
libraries the app can install for itself.

Background: SpeechRecognition is pure python and pip pulls in almost
nothing for it, but on Arch the only package is the AUR one, and that
declares SpeechRecognition's OPTIONAL backends (pocketsphinx,
google-cloud-speech, groq) as hard dependencies. When one of those fails
to build - google-cloud-speech's test suite currently does - the whole
chain dies and Speech to Text is unreachable through no fault of ours.

An AUR install of this app has no venv to fall back on, so instead we
keep our own folder:

    ~/.config/OSC-DreamChatbox/extras/

It is put on sys.path at startup, and one button installs into it with
`pip install --target`. Nothing outside that folder is touched: no
system packages, no --break-system-packages, nothing pacman owns.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib
import importlib.util
import shutil
import subprocess
import sys

from core.constants import EXTRAS_DIR
from core.osinfo import IS_FROZEN, IS_WINDOWS, subprocess_flags

# name -> pip requirement. Deliberately no extras: SpeechRecognition's
# backends are optional and we only use the plain HTTP recognizers.
KNOWN = {
    "speech_recognition": "SpeechRecognition",
    # The microphone driver. PyAudio would be the obvious choice, but it
    # is a compiled extension whose wheels stop at CPython 3.13 - on
    # newer pythons pip falls back to a source build that needs a C
    # compiler and PortAudio headers. sounddevice is a CFFI wrapper
    # around the same library and ships as a plain wheel (with the
    # PortAudio DLL included on Windows), so it installs anywhere.
    "sounddevice": "sounddevice",
}


def activate():
    """Puts the extras folder on sys.path. Call once, before anything
    tries to import an optional library."""
    path = str(EXTRAS_DIR)
    if EXTRAS_DIR.is_dir() and path not in sys.path:
        # after the stdlib but before site-packages, so a system package
        # that does work still wins over our copy
        sys.path.insert(1, path)
    return EXTRAS_DIR


def has(module):
    return importlib.util.find_spec(module) is not None


def installed_here(module):
    """True when the module comes from our extras folder rather than
    from the system - lets the UI say where it got it."""
    spec = importlib.util.find_spec(module)
    origin = getattr(spec, "origin", "") or ""
    return str(EXTRAS_DIR) in origin


def python_executable():
    """A real python interpreter we may run ``-m pip`` with, or None.

    THE TRAP: inside a PyInstaller build ``sys.executable`` is the app's
    own .exe, not python. ``[sys.executable, "-m", "pip", ...]`` would
    therefore start a SECOND copy of the chatbox instead of installing
    anything - and the extra arguments would be ignored, so it would look
    like a hang rather than an error. Frozen builds must go looking for
    an interpreter on the system instead.
    """
    if not IS_FROZEN:
        return sys.executable
    names = (["python.exe", "python3.exe", "py.exe"] if IS_WINDOWS
             else ["python3", "python"])
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def pip_available():
    exe = python_executable()
    if exe is None:
        return False
    try:
        subprocess.run([exe, "-m", "pip", "--version"],
                       capture_output=True, timeout=20, check=True,
                       **subprocess_flags())
        return True
    except Exception:
        return False


def install(module, log=None):
    """Installs one known extra into the extras folder.

    Returns (ok, message). Never raises - a failed install must leave the
    app exactly as it was.
    """
    requirement = KNOWN.get(module)
    if requirement is None:
        return False, f"'{module}' is not a known extra"
    exe = python_executable()
    if exe is None:
        return False, ("This is a packaged build with no python of its "
                       "own, and no python was found on the system. "
                       "Install Python from python.org (tick \"Add to "
                       "PATH\") and try again, or run the app from source.")
    if not pip_available():
        return False, ("pip is not available for this python. "
                       "Install python-pip and try again.")
    EXTRAS_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "-m", "pip", "install", "--upgrade",
           "--target", str(EXTRAS_DIR), requirement]
    if callable(log):
        log(f"Extras: {' '.join(cmd[-4:])}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=300, **subprocess_flags())
    except subprocess.TimeoutExpired:
        return False, "pip took too long (over 5 minutes) and was stopped."
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else f"pip exited with {proc.returncode}"
        return False, detail

    activate()
    # a failed import earlier leaves a negative entry in the finder cache
    importlib.invalidate_caches()
    if not has(module):
        return False, ("pip reported success but the module still cannot "
                       "be imported.")
    return True, f"{requirement} installed into {EXTRAS_DIR}"
