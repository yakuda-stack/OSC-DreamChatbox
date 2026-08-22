"""
core/mangohud.py - finds the MangoHud log folder by itself.

The FPS value on Linux comes from tailing MangoHud's CSV log (see
core/backends/hardware_linux.py). Until now that folder had to be typed
into a file dialog, which assumes the user knows where MangoHud writes -
and most people never chose that folder themselves: they set logging up
in GOverlay, which writes `output_folder` into a MangoHud config file
and never shows them the path again.

So this module looks in the two places the answer actually is:

1. **The config files.** MangoHud reads, in this order, whatever
   MANGOHUD_CONFIGFILE points at, then per-executable configs and
   MangoHud.conf under $XDG_CONFIG_HOME/MangoHud, then /etc/MangoHud.conf.
   GOverlay writes into exactly those, so "configured in GOverlay" and
   "found here" are the same thing. Every *.conf in the folder is read,
   not just MangoHud.conf, because a per-game config
   (`wine-VRChat.conf`) is how you log VRChat and nothing else.
2. **The usual folders.** If no config names one - someone passed
   output_folder inline in the Steam launch options, which leaves no file
   behind - the handful of paths people actually use are checked for
   MangoHud CSVs.

Everything found is ranked before it is returned: a folder holding a
VRChat log beats one holding somebody else's benchmark, and a fresh log
beats a stale one. That way the button picks the right folder on a
machine with three of them instead of the alphabetically first.

Qt-free on purpose - this is filesystem work and belongs in a place the
tests can call without a QApplication.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil
import time
from pathlib import Path

#: how long a CSV may sit untouched and still count as "from this
#: session". Deliberately generous: the detection runs while the user is
#: in the app, VRChat may have been closed ten minutes ago, and a log
#: from earlier today still proves the folder is the right one.
FRESH_SEC = 6 * 3600

#: MangoHud names its logs "<app>_<date>_<time>.csv"; this is what makes
#: one of them ours rather than any other CSV that happens to be there
VRCHAT_HINTS = ("vrchat", "vrchat.exe")

#: folders people end up with, in the order the MangoHud docs, GOverlay
#: and the copy-pasted launch options on Reddit suggest them
COMMON_FOLDERS = (
    "~/mangologs",
    "~/mangohud",
    "~/MangoHud",
    "~/.config/MangoHud/logs",
    "~/.local/share/MangoHud",
    "~/Documents/mangologs",
    "~/Dokumente/mangologs",
)


# --------------------------------------------------------------- helpers
def _home():
    return Path.home()


def _config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME") or (_home() / ".config"))


def expand(value):
    """A path out of a config file as an absolute Path, or None.

    MangoHud writes these by hand as often as not, so `~/mangologs`,
    `$HOME/mangologs` and a bare relative path all turn up.
    """
    text = str(value or "").strip().strip('"').strip("'")
    if not text:
        return None
    text = os.path.expandvars(text)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (_home() / path)
    return path


def config_files():
    """Every MangoHud config that could carry an output_folder, most
    specific first."""
    out = []
    explicit = os.environ.get("MANGOHUD_CONFIGFILE")
    if explicit:
        out.append(Path(explicit).expanduser())
    folder = _config_home() / "MangoHud"
    if folder.is_dir():
        try:
            confs = sorted(p for p in folder.iterdir()
                           if p.is_file() and p.suffix == ".conf")
        except OSError:
            confs = []
        # a per-game config wins over the global one: someone who set up
        # logging for VRChat specifically meant that folder
        out += [p for p in confs
                if any(h in p.name.lower() for h in VRCHAT_HINTS)]
        out += [p for p in confs if p.name == "MangoHud.conf"]
        out += [p for p in confs
                if p.name != "MangoHud.conf"
                and not any(h in p.name.lower() for h in VRCHAT_HINTS)]
    out.append(_config_home() / "MangoHud.conf")
    out.append(Path("/etc/MangoHud.conf"))
    seen, unique = set(), []
    for path in out:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def read_output_folder(path):
    """The output_folder line of one config file, or None.

    Comments count: GOverlay leaves the whole default config in place and
    only uncomments what is switched on, so a file full of
    `# output_folder=` lines means logging is OFF, not "logs to
    nowhere".
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip().lower() == "output_folder":
            return expand(value)
    return None


def env_output_folder():
    """output_folder out of MANGOHUD_CONFIG, if this process happens to
    have inherited one (rare, but free to check)."""
    raw = os.environ.get("MANGOHUD_CONFIG", "")
    for part in raw.split(","):
        key, _, value = part.partition("=")
        if key.strip().lower() == "output_folder":
            return expand(value)
    return None


def inspect(folder):
    """What a folder holds: how many MangoHud CSVs, how old the newest
    one is, and whether any of them is VRChat's."""
    info = {"exists": False, "csv": 0, "age": None, "vrchat": False,
            "newest": None}
    if folder is None:
        return info
    try:
        path = Path(folder)
        if not path.is_dir():
            return info
        info["exists"] = True
        newest_time = None
        for entry in path.iterdir():
            if not entry.is_file() or entry.suffix.lower() != ".csv":
                continue
            info["csv"] += 1
            if any(h in entry.name.lower() for h in VRCHAT_HINTS):
                info["vrchat"] = True
            stamp = entry.stat().st_mtime
            if newest_time is None or stamp > newest_time:
                newest_time, info["newest"] = stamp, entry
    except OSError:
        return info
    if newest_time is not None:
        info["age"] = max(0.0, time.time() - newest_time)
    return info


def _score(info):
    """Higher is a better guess. A VRChat log outweighs everything else,
    then recency, then simply having logs at all."""
    if not info["exists"]:
        return -1
    score = 0
    if info["csv"]:
        score += 10
    if info["vrchat"]:
        score += 100
    if info["age"] is not None and info["age"] <= FRESH_SEC:
        score += 50
    return score


def installed():
    """Is MangoHud actually on this system?

    The launcher script is the obvious check, but MANGOHUD=1 works
    through the Vulkan implicit layer alone, so a missing `mangohud`
    binary does not mean it is absent.
    """
    if shutil.which("mangohud"):
        return True
    layer_dirs = ("/usr/share/vulkan/implicit_layer.d",
                  "/usr/local/share/vulkan/implicit_layer.d",
                  str(_home() / ".local/share/vulkan/implicit_layer.d"))
    for folder in layer_dirs:
        try:
            for entry in Path(folder).iterdir():
                if "mangohud" in entry.name.lower():
                    return True
        except OSError:
            continue
    return False


def goverlay_installed():
    return bool(shutil.which("goverlay"))


# ------------------------------------------------------------------ main
def detect():
    """Finds the log folder. Returns a dict:

        folder     Path or None - what to put in the setting
        source     where it came from, for the message
        info       inspect() of the winner
        configured True when a config file names an output_folder at all
        mangohud   MangoHud is installed
        goverlay   GOverlay is installed
        checked    the config files that were read, for the message
    """
    candidates = []          # (score, order, folder, source)

    def offer(folder, source):
        if folder is None:
            return
        candidates.append((_score(inspect(folder)), len(candidates),
                           Path(folder), source))

    env_folder = env_output_folder()
    offer(env_folder, "MANGOHUD_CONFIG")

    checked, configured = [], env_folder is not None
    for conf in config_files():
        if not conf.is_file():
            continue
        checked.append(conf)
        folder = read_output_folder(conf)
        if folder is not None:
            configured = True
            offer(folder, str(conf))

    for name in COMMON_FOLDERS:
        offer(Path(name).expanduser(), "common folder")

    best = None
    for entry in candidates:
        # sort by score, then by the order they were offered in, so a
        # config file always beats a lucky guess at equal score
        if best is None or (entry[0], -entry[1]) > (best[0], -best[1]):
            best = entry

    result = {"folder": None, "source": None, "info": inspect(None),
              "configured": configured, "mangohud": installed(),
              "goverlay": goverlay_installed(), "checked": checked}
    if best is not None and best[0] >= 0:
        # score 0 = the folder exists but is empty. Still worth offering:
        # it is where the logs WILL appear once VRChat runs.
        result["folder"] = best[2]
        result["source"] = best[3]
        result["info"] = inspect(best[2])
    return result


#: the launch options that make MangoHud log at all - shown whenever the
#: detection comes up empty, because that is the missing step
LAUNCH_OPTIONS = ("MANGOHUD=1 MANGOHUD_CONFIG=output_folder=~/mangologs,"
                  "autostart_log=1,log_interval=1000 mangohud %command%")


def describe(result):
    """One short human sentence about what was found, for the log and
    the dialog."""
    folder, info = result["folder"], result["info"]
    if folder is None:
        if not result["mangohud"]:
            return "MangoHud does not seem to be installed."
        if not result["configured"]:
            return ("MangoHud is installed, but no config sets "
                    "output_folder - logging is off.")
        return "No MangoHud log folder could be found."
    where = ("from MANGOHUD_CONFIG" if result["source"] == "MANGOHUD_CONFIG"
             else "guessed" if result["source"] == "common folder"
             else f"from {result['source']}")
    if info["vrchat"]:
        what = "with VRChat logs in it"
    elif info["csv"]:
        what = f"with {info['csv']} MangoHud log(s)"
    else:
        what = "but no logs in it yet"
    return f"{folder} ({where}, {what})"
