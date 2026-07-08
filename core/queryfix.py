"""
core/queryfix.py – OSCQuery fixer for OSC-DreamChatbox

One single, easily extensible list of supported programs. The
"Fix OSCQuery" button on the Options page writes the required
parameter directly into each program's own config file (all other
keys in the file are preserved).

To add a new program, just append another dict to PROGRAMS:
    name       display name shown in the UI
    path       path to the program's config file (~ is expanded)
    key        the JSON key to set
    value      the value to write (usually True)

Only EXISTING config files are modified – if the file is missing the
program is reported as "config not found" instead of creating a
broken partial config (some tools, e.g. OSCLeash, crash when keys
are missing from their config).
"""

import json
from pathlib import Path

# ---------------------------------------------------------------- programs
PROGRAMS = [
    {
        "name": "OSCLeash",
        "path": "~/.config/OSCLeash/Config.json",
        "key": "UseOSCQuery",
        "value": True,
    },
    {
        "name": "OscGoesBrrr",
        "path": "~/.config/OscGoesBrrr/config.json",
        "key": "useOscQuery",
        "value": True,
    },
    # Add more OSCQuery-capable programs here ...
]


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
                     f"      path:      {p['path']}\n"
                     f"      parameter: \"{p['key']}\": {val}")
    return "\n".join(lines)


def fix_program(prog):
    """Applies the OSCQuery fix to ONE program.
    Returns (ok: bool, message: str)."""
    cfg_path = Path(prog["path"]).expanduser()
    if not cfg_path.exists():
        return False, ("config not found – program not installed "
                       "or never started")
    try:
        data = json.loads(cfg_path.read_text())
    except Exception as e:
        return False, f"config unreadable ({e})"
    if data.get(prog["key"]) == prog["value"]:
        return True, (f"already set (\"{prog['key']}\": "
                      f"{json.dumps(prog['value'])})")
    data[prog["key"]] = prog["value"]
    try:
        cfg_path.write_text(json.dumps(data, indent=2))
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
