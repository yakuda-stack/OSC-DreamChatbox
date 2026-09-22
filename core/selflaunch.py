"""
core/selflaunch.py - starting this app again, and terminal windows.

Used by terminal mode (DCB-UI opens the window, DCB-log opens a log
window) and by the Options button that switches the window over to
terminal mode.

"Start this app again" depends on how it was installed, and getting it
wrong fails in confusing ways:

* AppImage: the running code lives in a temporary mount
  (/tmp/.mount_XXXX) that disappears the moment this process ends. A
  new process has to be started from the .AppImage FILE itself, whose
  path the AppImage runtime puts in $APPIMAGE.
* Windows .exe (PyInstaller): sys.executable IS the app.
* From source (venv, start.sh) and AUR (/usr/lib/osc-dreamchatbox run
  by the system python): the same interpreter with the entry script.

The AppImage also exports PYTHONPATH (and its own usr/bin on PATH) for
the bundled packages. Those must not leak into a terminal emulator or
into the new copy - AppRun sets them again for the new copy anyway.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core import proclaunch
from core.osinfo import IS_FROZEN, IS_WINDOWS

#: the entry script, next to core/
ENTRY = Path(__file__).resolve().parent.parent / "osc_dreamchatbox.py"


def in_appimage():
    return bool(os.environ.get("APPIMAGE"))


def self_command(args=()):
    """The command line that starts this app (the same install) again."""
    args = list(args)
    if in_appimage():
        return [os.environ["APPIMAGE"]] + args
    if IS_FROZEN:
        return [sys.executable] + args
    return [sys.executable, str(ENTRY)] + args


def clean_env():
    """os.environ without what the AppImage runtime injected for its own
    bundled python packages (see module doc)."""
    env = dict(os.environ)
    if in_appimage():
        for key in ("PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH",
                    "DREAMCHATBOX_PYTHON", "QT_PLUGIN_PATH"):
            env.pop(key, None)
        appdir = env.get("APPDIR", "")
        if appdir and "PATH" in env:
            env["PATH"] = os.pathsep.join(
                p for p in env["PATH"].split(os.pathsep)
                if not p.startswith(appdir))
    return env


def start_detached(cmd):
    """Starts ``cmd`` so it outlives this process. (ok, message)"""
    kwargs = {"env": clean_env(), "stdin": subprocess.DEVNULL,
              "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)
    except OSError as e:
        return False, str(e)
    return True, ""


def open_in_terminal(cmd, keep_open_on_error=True):
    """Runs ``cmd`` in a NEW terminal window. (ok, message)

    Linux: the first installed terminal emulator ($TERMINAL first, see
    core/proclaunch.py). With ``keep_open_on_error`` the window stays
    open when the command fails, so its last words can be read instead
    of the window just vanishing.
    Windows: a new console window."""
    if IS_WINDOWS:
        try:
            subprocess.Popen(
                cmd, env=clean_env(),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        except OSError as e:
            return False, str(e)
        return True, ""

    prefix = proclaunch.find_terminal()
    if prefix is None:
        return False, ("no terminal emulator found - install konsole, "
                       "gnome-terminal, kitty, alacritty or xterm")
    if keep_open_on_error:
        # "$@" runs the command with its arguments untouched by the shell
        script = ('"$@" || { echo; echo "[stopped with an error - press '
                  'Enter to close]"; read _; }')
        cmd = ["sh", "-c", script, "sh"] + list(cmd)
    ok, msg = start_detached(prefix + list(cmd))
    if not ok:
        return False, f"{prefix[0]}: {msg}"
    return True, ""


def log_viewer_command(path):
    """A command that shows ``path`` and follows new lines (tail -f)."""
    if IS_WINDOWS:
        quoted = str(path).replace("'", "''")
        script = ("$Host.UI.RawUI.WindowTitle = 'OSC-DreamChatbox log'; "
                  "Get-Content -Wait -Tail 200 -Encoding UTF8 "
                  f"-LiteralPath '{quoted}'")
        return ["powershell", "-NoExit", "-Command", script]
    return ["tail", "-n", "200", "-F", str(path)]
