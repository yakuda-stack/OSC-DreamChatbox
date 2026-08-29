"""
core/queryfix.py – OSCQuery fixer for OSC-DreamChatbox

One single, easily extensible list of supported programs. The
"Fix OSCQuery" button on the Options page writes the required
parameter directly into each program's own config file (all other
keys in the file are preserved).

To add a new program, just append another dict to PROGRAMS:
    name       display name shown in the UI
    paths      {"linux": [...], "windows": [...]} - candidate locations
               of the program's config file. "~" and %ENVVARS% are both
               expanded. The FIRST one that exists is used.
    key        the JSON key to set
    value      the value to write (usually True)

Only EXISTING config files are modified – if the file is missing the
program is reported as "config not found" instead of creating a
broken partial config (some tools, e.g. OSCLeash, crash when keys
are missing from their config).

That rule is also what makes several candidate paths per platform safe:
listing a location that turns out to be wrong costs nothing, because a
path that does not exist is simply skipped. Nothing is ever created.

WINDOWS NOTE: these tools have no single documented config location on
Windows the way the XDG spec gives us one on Linux, so the Windows
entries are the usual places (%APPDATA%, portable install next to the
.exe) rather than something verified on every install. If a program
reports "config not found" although it is installed, look up where it
keeps its config and add that path here - it is a one-line change.
"""

import json
import os
import platform
import re
from pathlib import Path

_WINVAR = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def _expand(text):
    """Expands %APPDATA% AND $HOME, on every platform.

    os.path.expandvars only knows the form its own platform uses -
    %VAR% is handled by ntpath, $VAR by posixpath. Doing %VAR%
    ourselves keeps the table above readable in one syntax and, more
    to the point, keeps it testable from a Linux machine.
    """
    text = _WINVAR.sub(
        lambda m: os.environ.get(m.group(1), m.group(0)), str(text))
    return os.path.expandvars(text)

IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------- programs
PROGRAMS = [
    {
        "name": "OSCLeash",
        "paths": {
            "linux": ["~/.config/OSCLeash/Config.json"],
            # forward slashes on purpose: pathlib turns them into
            # backslashes on Windows, and a table full of "\" invites
            # escaping mistakes nobody notices until a path silently misses
            "windows": [
                "%APPDATA%/OSCLeash/Config.json",
                "%LOCALAPPDATA%/OSCLeash/Config.json",
                # portable/unzipped builds keep the config next to the exe
                "%USERPROFILE%/Documents/OSCLeash/Config.json",
                "%USERPROFILE%/OSCLeash/Config.json",
            ],
        },
        "key": "UseOSCQuery",
        "value": True,
    },
    {
        "name": "OscGoesBrrr",
        "paths": {
            "linux": ["~/.config/OscGoesBrrr/config.json"],
            "windows": [
                # Electron's app.getPath("userData")
                "%APPDATA%/OscGoesBrrr/config.json",
                "%APPDATA%/oscgoesbrrr/config.json",
            ],
        },
        "key": "useOscQuery",
        "value": True,
    },
    # Add more OSCQuery-capable programs here ...
]


def _platform_key():
    return "windows" if IS_WINDOWS else "linux"


def candidate_paths(prog):
    """Config locations to try on THIS platform, as expanded Paths.

    Accepts the old single-"path" form too, so an out-of-tree edit of
    PROGRAMS keeps working.
    """
    raw = prog.get("paths")
    if raw is None:
        raw = {"linux": [prog.get("path", "")],
               "windows": [prog.get("path", "")]}
    entries = raw.get(_platform_key()) or []
    if isinstance(entries, str):
        entries = [entries]
    out = []
    for entry in entries:
        if not entry:
            continue
        expanded = _expand(entry)
        if _WINVAR.search(expanded):
            # an unset variable - the path cannot mean anything, and
            # keeping it would create a folder literally called %APPDATA%
            continue
        out.append(Path(expanded).expanduser())
    return out


def display_path(prog):
    """What the UI shows: the file we found, or the places we looked."""
    paths = candidate_paths(prog)
    for path in paths:
        if path.exists():
            return str(path)
    if not paths:
        return "(no known location on this platform)"
    if len(paths) == 1:
        return str(paths[0])
    return str(paths[0]) + f"  (+{len(paths) - 1} more checked)"


def supported_here(prog):
    """False when we know of no location at all on this platform."""
    return bool(candidate_paths(prog))


def describe():
    """Human-readable list of the supported programs (for the UI),
    e.g.:  OSCLeash
              path:      ~/.config/OSCLeash/Config.json
              parameter: "UseOSCQuery": true
    """
    lines = []
    for p in PROGRAMS:
        val = json.dumps(p["value"])
        lines.append(f"{p['name']}\n"
                     f"      path:      {display_path(p)}\n"
                     f"      parameter: \"{p['key']}\": {val}")
    return "\n".join(lines)


def fix_program(prog):
    """Applies the OSCQuery fix to ONE program.
    Returns (ok: bool, message: str)."""
    paths = candidate_paths(prog)
    cfg_path = next((p for p in paths if p.exists()), None)
    if cfg_path is None:
        if not paths:
            return False, "no known config location on this platform"
        where = ("" if len(paths) == 1
                 else f" ({len(paths)} locations checked)")
        return False, ("config not found – program not installed "
                       f"or never started{where}")
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"config unreadable ({e})"
    if data.get(prog["key"]) == prog["value"]:
        return True, (f"already set (\"{prog['key']}\": "
                      f"{json.dumps(prog['value'])})")
    data[prog["key"]] = prog["value"]
    try:
        cfg_path.write_text(json.dumps(data, indent=2),
                            encoding="utf-8")
    except Exception as e:
        return False, f"could not write config ({e})"
    return True, (f"fixed – \"{prog['key']}\": "
                  f"{json.dumps(prog['value'])} written")


def fix_all(log=print):
    """Applies the fix to every supported program.
    Returns a list of (name, ok, message)."""
    results = []
    for prog in PROGRAMS:
        ok, msg = fix_program(prog)
        results.append((prog["name"], ok, msg))
        log(f"OSCQuery Fix: {prog['name']}: {msg}")
    return results
