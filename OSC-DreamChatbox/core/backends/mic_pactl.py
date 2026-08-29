"""
core/backends/mic_pactl.py - the audio graph, as PipeWire actually sees it

WHY THIS EXISTS
---------------
PortAudio's device list on Linux is not a list of microphones. It is a
list of ALSA PCMs, and that is a very different thing:

    HDA ATI HDMI: LG ULTRAGEAR (hw:1,3)     <- a monitor. Not a microphone.
    HDA ATI HDMI: 1 (hw:1,7)                <- the same card, next HDMI pin
    USB Audio: - (hw:3,0)                   <- one physical headset ...
    USB Audio: #1 (hw:3,1)                  <- ... showing up four times
    pipewire / pulse / default              <- the three that actually work

Everything above "pipewire" in that list is either an output pretending
to be an input, or a raw hardware PCM that bypasses the sound server -
which on a PipeWire desktop means exclusive access, a fight with
whatever is already using the card, and no VR microphone at all, because
WiVRn's microphone is a PipeWire node with no ALSA device behind it.

So the dropdown asked people to pick from a list where most entries are
wrong, several are duplicates and the ones they actually want (the
virtual sources: WiVRn, PipeWeaver, echo-cancel, loopbacks) are not in
it at all.

WHAT THIS MODULE DOES
---------------------
It asks `pactl` for the real source list and sorts it into the three
groups a person can reason about:

    Microphones          hardware capture devices (ALSA, Bluetooth)
    Virtual sources      WiVRn, PipeWeaver, echo-cancel, null sinks, ...
    Monitors             "listen to what an output is playing"

`pactl` is not a dependency: it ships with pipewire-pulse and
pulseaudio alike, and when it is missing (or on Windows) every function
here returns empty and the caller falls back to the plain PortAudio
list. Nothing breaks, the list is just less pretty.

HOW A SOURCE IS THEN OPENED
---------------------------
Not through PortAudio's device index - PortAudio has one entry for the
whole sound server, not one per node. It is opened through the server
entry ("pipewire" / "pulse" / "default") with the environment pointing
at the node:

    PULSE_SOURCE=<node name>      honoured by the ALSA pulse plugin
    PIPEWIRE_NODE=<node name>     honoured by pipewire-alsa

Both are read at stream-open time, which is why the microphone helper is
a separate process (see core/mic_host.py): its environment can be set
per recording without touching the app's own.

Because an environment variable is a request and not a guarantee,
`active_source()` reads back which source the running helper is ACTUALLY
attached to, and the UI shows that. A silent "it recorded from the wrong
device" is exactly the failure this is supposed to prevent.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Runnable as a plain script (`python core/backends/mic_pactl.py`) for
# the self-test at the bottom - which is the first thing to reach for
# when somebody's dropdown looks wrong, so it should not require knowing
# to type `-m core.backends.mic_pactl`.
_ROOT = Path(__file__).resolve().parent.parent.parent
if __name__ == "__main__" and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.osinfo import IS_WINDOWS

#: pactl answers instantly on a healthy graph. It talks to the sound
#: server over a unix socket, so unlike PortAudio it cannot wedge in a
#: driver - but a server that is starting up can still stall, and this
#: runs while the user is waiting for a dropdown.
TIMEOUT = 3.0

#: group ids. The UI turns these into headers; keeping them as ids means
#: the wording can change without touching the sorting.
G_MIC = "mic"
G_VIRTUAL = "virtual"
G_MONITOR = "monitor"

GROUP_LABELS = {
    G_MIC: "Microphones",
    G_VIRTUAL: "Virtual sources",
    G_MONITOR: "Monitors (listen to an output)",
}

GROUP_ORDER = (G_MIC, G_VIRTUAL, G_MONITOR)

#: what each group is, for the tooltip on its header
GROUP_HINTS = {
    G_MIC: ("Real capture hardware - USB headsets, webcam microphones, "
            "the jack on your motherboard, Bluetooth."),
    G_VIRTUAL: ("Nodes without hardware behind them: WiVRn's VR "
                "microphone, echo-cancel and noise-suppression outputs, "
                "PipeWeaver/Helvum routing, loopbacks. This is where a VR "
                "microphone lives."),
    G_MONITOR: ("Not microphones - these record what an output is "
                "PLAYING. Useful to transcribe a video or a call, and "
                "the wrong choice for talking."),
}


def _pactl():
    """Path to pactl, or '' when there is none."""
    if IS_WINDOWS:
        return ""
    return shutil.which("pactl") or ""


def available():
    return bool(_pactl())


def _run(args):
    """pactl output as text, or '' on any failure. Never raises."""
    exe = _pactl()
    if not exe:
        return ""
    try:
        proc = subprocess.run(
            [exe] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=TIMEOUT)
    except Exception:      # noqa: BLE001 - a missing sound server is normal
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""


# ------------------------------------------------------------ parsing
def _is_monitor(entry, props):
    """Monitors are sources that record an OUTPUT.

    Three ways to tell, because pactl has moved the information around
    between versions and pipewire-pulse fills a different subset than
    PulseAudio did.
    """
    if str(props.get("device.class", "")).lower() == "monitor":
        return True
    mon = entry.get("monitor_of_sink") or entry.get("monitor_source") or ""
    if str(mon).strip() and str(mon).strip().lower() != "n/a":
        return True
    return str(entry.get("name", "")).endswith(".monitor")


def _is_hardware(props):
    """True for a node with a real device behind it.

    `device.api` is the honest answer when it is there: alsa, bluez5 and
    v4l2 are hardware, "null" and a missing key are not. The card keys
    are the fallback for servers that do not set it.
    """
    api = str(props.get("device.api", "")).lower()
    if api in ("alsa", "bluez5", "bluetooth"):
        return True
    if api:      # explicitly something else -> not hardware
        return False
    return any(k in props for k in
               ("alsa.card", "api.alsa.card", "alsa.card_name",
                "device.bus", "device.product.name"))


def _classify(entry, props):
    """Which of the three groups this source belongs in.

    A monitor of a VIRTUAL sink is filed with the virtual sources rather
    than under Monitors, because that is what it is to the user: the
    output side of an app-routing node like PipeWeaver's, not "listen to
    my speakers".
    """
    if _is_monitor(entry, props):
        return G_MONITOR if _is_hardware(props) else G_VIRTUAL
    return G_MIC if _is_hardware(props) else G_VIRTUAL


def _describe(entry, props):
    """The friendly name, with the same fallbacks pavucontrol uses."""
    for key in ("description",):
        val = str(entry.get(key) or "").strip()
        if val:
            return val
    for key in ("device.description", "node.description", "node.nick",
                "alsa.card_name"):
        val = str(props.get(key) or "").strip()
        if val:
            return val
    return str(entry.get("name") or "").strip()


def _from_json(text):
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    out = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        props = entry.get("properties")
        props = props if isinstance(props, dict) else {}
        # keys arrive as strings either way, values may not
        props = {str(k): ("" if v is None else str(v))
                 for k, v in props.items()}
        out.append({
            "name": name,
            "description": _describe(entry, props),
            "group": _classify(entry, props),
            "state": str(entry.get("state") or ""),
        })
    return out


def _from_text(text):
    """Fallback for a pactl too old for `-f json` (pre-15).

    Only the four fields that matter are picked out; anything unparsed
    simply lands in the virtual group, which is the harmless default.
    """
    sources = []
    current = None
    props = {}
    in_props = False
    for raw in text.splitlines():
        line = raw.strip()
        if raw[:1] not in (" ", "\t") and line.lower().startswith("source #"):
            if current:
                current["group"] = _classify(current, props)
                current["description"] = (current.get("description")
                                          or _describe(current, props))
                sources.append(current)
            current = {"name": "", "description": "", "state": ""}
            props = {}
            in_props = False
            continue
        if current is None:
            continue
        if line.lower().startswith("properties:"):
            in_props = True
            continue
        if in_props and "=" in line:
            key, _, val = line.partition("=")
            props[key.strip()] = val.strip().strip('"')
            continue
        in_props = False
        low = line.lower()
        if low.startswith("name:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif low.startswith("description:"):
            current["description"] = line.split(":", 1)[1].strip()
        elif low.startswith("state:"):
            current["state"] = line.split(":", 1)[1].strip()
        elif low.startswith("monitor of sink:"):
            current["monitor_of_sink"] = line.split(":", 1)[1].strip()
    if current:
        current["group"] = _classify(current, props)
        current["description"] = (current.get("description")
                                  or _describe(current, props))
        sources.append(current)
    return [s for s in sources if s.get("name")]


def list_sources(log=None):
    """[{name, description, group, state}] of every capture source.

    Empty list when pactl is unavailable or the server does not answer -
    the caller then shows the plain PortAudio list, which is what every
    version before this one did.
    """
    if not available():
        return []
    text = _run(["-f", "json", "list", "sources"])
    entries = _from_json(text) if text else None
    if entries is None:
        # -f json exists since pactl 15; older ones print the usage help
        entries = _from_text(_run(["list", "sources"]))
    if not entries and callable(log):
        log("Speech to Text: pactl returned no sources - falling back to "
            "the plain PortAudio device list.")
    return entries


def default_source():
    """node name of the server's default source, or ''."""
    if not available():
        return ""
    text = _run(["get-default-source"]).strip()
    if text and not text.lower().startswith("failure"):
        return text.splitlines()[0].strip()
    # older pactl has no get-default-source; `info` always had the line
    for line in _run(["info"]).splitlines():
        if line.lower().startswith("default source:"):
            return line.split(":", 1)[1].strip()
    return ""


# -------------------------------------------------- read-back of reality
def active_source(pid, log=None):
    """Which source the process `pid` is actually recording from.

    Returns the source's node name, or ''.

    The point of this is honesty. Selecting a node is done by exporting
    PULSE_SOURCE / PIPEWIRE_NODE into the helper's environment, and an
    environment variable is a request: a node that went away, a name
    with a typo in it or a server that ignores the hint all end the same
    way - a recording that works and listens to the wrong thing. Reading
    the routing back turns that into a line the user can see.
    """
    if not available() or not pid:
        return ""
    want = str(int(pid))
    text = _run(["-f", "json", "list", "source-outputs"])
    if text:
        try:
            data = json.loads(text)
        except Exception:
            data = None
        if isinstance(data, list):
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                props = entry.get("properties") or {}
                if str(props.get("application.process.id", "")) != want:
                    continue
                name = entry.get("source")
                if isinstance(name, str) and name:
                    return name
                # older pipewire-pulse reports the index here; resolve it
                return _source_name_by_index(name)
    return _active_source_text(want)


def _source_name_by_index(index):
    try:
        index = int(index)
    except Exception:
        return ""
    text = _run(["-f", "json", "list", "sources"])
    try:
        data = json.loads(text) if text else []
    except Exception:
        return ""
    for entry in data if isinstance(data, list) else ():
        if isinstance(entry, dict) and entry.get("index") == index:
            return str(entry.get("name") or "")
    return ""


def _active_source_text(want):
    """Same read-back through the plain text output."""
    source = ""
    pid = ""
    found = ""
    for raw in _run(["list", "source-outputs"]).splitlines():
        line = raw.strip()
        if raw[:1] not in (" ", "\t") and \
                line.lower().startswith("source output #"):
            if pid == want and source:
                found = source
            source = ""
            pid = ""
            continue
        low = line.lower()
        if low.startswith("source:"):
            # "Source: 52" - an index, resolved after the loop
            source = line.split(":", 1)[1].strip()
        elif "application.process.id" in low:
            pid = line.split("=", 1)[-1].strip().strip('"')
    if not found and pid == want and source:
        found = source
    if found and found.isdigit():
        return _source_name_by_index(found)
    return found


def describe_source(name):
    """The friendly description for a node name, or the name itself."""
    if not name:
        return ""
    for src in list_sources():
        if src.get("name") == name:
            return src.get("description") or name
    return name


def env_for(name):
    """The environment additions that point a new process at `name`.

    Both variables are set on purpose: PULSE_SOURCE is what the ALSA
    pulse plugin reads, PIPEWIRE_NODE is what pipewire-alsa reads, and
    which of the two is behind the "pipewire"/"pulse" PCM depends on the
    distribution rather than on anything the app can see.
    """
    if not name:
        return {}
    return {"PULSE_SOURCE": str(name), "PIPEWIRE_NODE": str(name)}


def clean_env(base=None):
    """`base` (default: os.environ) without the two routing variables.

    A user who exported PULSE_SOURCE in their shell would otherwise have
    it silently override "System default" for the helper.
    """
    env = dict(os.environ if base is None else base)
    env.pop("PULSE_SOURCE", None)
    env.pop("PIPEWIRE_NODE", None)
    return env


# ====================================================================
#  python -m core.backends.mic_pactl
# ====================================================================
def _selftest():
    print("=" * 62)
    print(" OSC-DreamChatbox - pactl source self-test")
    print("=" * 62)
    if not available():
        print("\npactl not found - the grouped list is unavailable and the "
              "plain PortAudio list is used instead.\n")
        return
    default = default_source()
    print(f"\ndefault source: {default or '(unknown)'}\n")
    sources = list_sources(print)
    for group in GROUP_ORDER:
        rows = [s for s in sources if s["group"] == group]
        if not rows:
            continue
        print(f"--- {GROUP_LABELS[group]} ({len(rows)}) ---")
        for src in rows:
            mark = "*" if src["name"] == default else " "
            print(f" {mark} {src['description']}")
            print(f"     {src['name']}  [{src.get('state', '')}]")
        print()


if __name__ == "__main__":
    _selftest()
