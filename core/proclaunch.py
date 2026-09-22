"""
core/proclaunch.py – starting a program from the canvas.

The other half of core/procwatch.py: that one notices VRChat came up,
this one starts the three things that should come up with it.

Two things it is careful about:

* **Detached.** A launched program is not a child that dies with the
  chatbox. Closing the app after it started your overlay should leave
  the overlay running.
* **Debug.** Ticked, the program runs in a terminal window instead of
  silently in the background, and the window stays open after it exits.
  Without that, "it did not start" and "it started and immediately said
  why it stopped" look exactly the same from here.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shlex
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform.startswith("win")

#: terminal emulators tried in order for a debug launch, with the
#: argument that means "and now run this"
TERMINALS = [
    ("konsole", ["konsole", "-e"]),
    ("gnome-terminal", ["gnome-terminal", "--"]),
    # -x, not -e: xfce4-terminal's -e takes ONE string, so a command
    # with arguments after it was cut off at the first one
    ("xfce4-terminal", ["xfce4-terminal", "-x"]),
    ("ptyxis", ["ptyxis", "--"]),
    ("tilix", ["tilix", "-e"]),
    ("terminator", ["terminator", "-x"]),
    ("alacritty", ["alacritty", "-e"]),
    ("kitty", ["kitty"]),
    ("foot", ["foot"]),
    ("wezterm", ["wezterm", "start", "--"]),
    ("xterm", ["xterm", "-e"]),
]


def _preferred():
    """The user's own choice from $TERMINAL, as (binary, prefix) - with
    the known "run this" argument when it is one of ours, "-e" (the
    xterm convention most others follow) otherwise."""
    name = os.environ.get("TERMINAL", "").strip()
    if not name or not shutil.which(name):
        return None
    base = os.path.basename(name)
    for binary, prefix in TERMINALS:
        if binary == base:
            return base, [name] + prefix[1:]
    return base, [name, "-e"]


def find_terminal():
    """The terminal to use ($TERMINAL first, then the first installed
    one), as the prefix to put a command behind, or None."""
    pref = _preferred()
    if pref is not None:
        return pref[1]
    for binary, prefix in TERMINALS:
        if shutil.which(binary):
            return prefix
    return None


def terminal_name():
    pref = _preferred()
    if pref is not None:
        return pref[0]
    for binary, _prefix in TERMINALS:
        if shutil.which(binary):
            return binary
    return ""


def launch(command, debug=False):
    """Starts ``command``. Returns (ok, message).

    The command is split the way a shell would, so arguments and quotes
    work, but it is NOT run through a shell - a canvas field is not a
    place where `; rm -rf` should mean anything.
    """
    command = str(command or "").strip()
    if not command:
        return False, "no command set"
    try:
        parts = shlex.split(command, posix=not IS_WINDOWS)
    except ValueError as e:
        return False, f"could not read the command ({e})"
    if not parts:
        return False, "no command set"

    if debug:
        if IS_WINDOWS:
            # /k keeps the window after the program ends
            parts = ["cmd", "/c", "start", "", "cmd", "/k"] + parts
        else:
            prefix = find_terminal()
            if prefix is None:
                return False, ("no terminal emulator found \u2013 install "
                               "konsole or xterm, or untick Debug")
            inner = " ".join(shlex.quote(p) for p in parts)
            parts = prefix + [
                "sh", "-c",
                f"{inner}; echo; echo '[finished, press Enter]'; read _"]

    try:
        kwargs = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        else:
            # its own session, so it survives this process
            kwargs["start_new_session"] = True
        subprocess.Popen(parts, **kwargs)
    except FileNotFoundError:
        return False, f"{parts[0]!r} was not found"
    except OSError as e:
        return False, str(e)
    return True, ""
