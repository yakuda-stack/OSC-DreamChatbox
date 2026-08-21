"""
core/micgroups.py - one microphone list a person can actually read

THE PROBLEM THIS SOLVES
-----------------------
Two device lists exist and neither of them is the right one on its own:

    PortAudio  knows what can be OPENED, and calls a monitor output a
               microphone, lists the same headset four times and has no
               entry at all for a VR microphone.
    pactl      knows what the sound server actually has - including the
               virtual nodes - but cannot open anything.

So this module merges them. pactl supplies the entries and their
grouping (see core/backends/mic_pactl.py); PortAudio supplies the way in.
The raw PortAudio devices are still offered underneath, because a
machine without a sound server has nothing else, and because bypassing
PipeWire is occasionally the right answer.

THE ID
------
Every entry has a stable id string, and that is what lands in the config
under ``stt_mic``:

    ""                  the system default
    "pulse:<node>"      a sound-server source, opened via PULSE_SOURCE
    "pa:<device name>"  a PortAudio device, opened by index

A bare string without a prefix is read as ``pa:`` - that is what older
configs contain, so nothing has to be migrated and downgrading keeps
working.

Ids are names, never indices. PortAudio's indices are positions in a
list that changes whenever a device appears or disappears, so a stored
index silently points at a different device after a reboot; the app has
always stored names for that reason and this keeps it that way.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from core.backends import mic_pactl
from core.backends.mic_pactl import (G_MIC, G_MONITOR, G_VIRTUAL,
                                     GROUP_HINTS, GROUP_LABELS)
from core.osinfo import IS_WINDOWS

#: extra groups this module adds on top of pactl's three
G_SYSTEM = "system"
G_SERVER = "server"
G_RAW = "raw"
#: Windows only: the SAME device seen through another host API
G_ALT = "alt"

#: top to bottom in the dropdown. The order is the recommendation: the
#: default first, real microphones next, the things that need to be
#: chosen deliberately last.
GROUP_ORDER = (G_SYSTEM, G_MIC, G_VIRTUAL, G_MONITOR, G_SERVER, G_ALT,
               G_RAW)

LABELS = dict(GROUP_LABELS)
LABELS.update({
    G_SYSTEM: "Default",
    G_SERVER: "Sound server",
    G_ALT: "Other host APIs (advanced)",
    G_RAW: "Direct hardware (advanced)",
})

HINTS = dict(GROUP_HINTS)
HINTS.update({
    G_SYSTEM: ("Whatever the desktop currently has set as its default "
               "input. Follows the system, so it changes when you change "
               "it there."),
    G_SERVER: ("PortAudio's entry for the sound server as a whole. "
               "Records from the current default source, same as "
               "\u201cDefault\u201d, and is the entry the sources above "
               "are opened through."),
    G_ALT: ("The same physical microphones again, reached through a "
            "different Windows audio API (MME, DirectSound, WDM-KS). "
            "Same hardware, different route - MME also cuts names off "
            "at 31 characters. Only worth trying when the entry above "
            "does not open."),
    G_RAW: ("ALSA devices opened DIRECTLY, bypassing PipeWire. Exclusive "
            "access, so it can fail while something else is using the "
            "card, and the HDMI entries here are outputs, not "
            "microphones. Only needed when there is no sound server."),
})

#: Which Windows audio API to offer when the same device appears under
#: several. WASAPI is the modern one and the only one with a shot at low
#: latency; MME is last because it truncates device names, which is how
#: you end up with two entries called "Mikrofon (HyperX QuadCa".
_WIN_API_PREFERENCE = ("Windows WASAPI", "Windows DirectSound",
                       "Windows WDM-KS", "MME")

#: PortAudio names that mean "the sound server", not a device
_SERVER_NAMES = ("pipewire", "pulse", "default", "sysdefault")

#: which of them to prefer when a sound-server source has to be opened.
#: pipewire-alsa first: it takes PIPEWIRE_NODE, which addresses a node
#: directly. The pulse plugin's PULSE_SOURCE goes through the pulse
#: compatibility layer, which is one translation more.
_SERVER_PREFERENCE = ("pipewire", "pulse", "default", "sysdefault")


def _base_name(name):
    """'pulse' out of 'pulse [ALSA]' / 'default:CARD=x'."""
    low = str(name or "").strip().lower()
    for sep in (" [", ":", " ("):
        if sep in low:
            low = low.split(sep, 1)[0]
    return low.strip()


def classify_portaudio(name):
    """Which group a raw PortAudio device belongs in."""
    if IS_WINDOWS:
        # Windows has no ALSA and no monitor-as-input problem; every
        # entry PortAudio reports is a genuine capture device.
        return G_MIC
    if _base_name(name) in _SERVER_NAMES:
        return G_SERVER
    return G_RAW


def _raw_note(name):
    """A warning for the entries that are not microphones at all."""
    low = str(name or "").lower()
    if "hdmi" in low or "displayport" in low:
        return ("This is an HDMI/DisplayPort OUTPUT. It is in the list "
                "because ALSA lists every PCM of the card - it cannot "
                "record anything.")
    if "(hw:" in low:
        return ("Direct hardware access, bypassing PipeWire. Can fail "
                "while another program is using the card.")
    return ""


def split_host_api(name):
    """('Mikrofon (HyperX)', 'Windows WASAPI') out of a device name.

    core/backends/mic_sounddevice.py appends the host API in brackets
    because PortAudio reports one entry PER API - the same microphone
    four times over. That suffix is what makes the duplicates
    distinguishable, so here it is taken apart again.

    Returns ``(name, "")`` when there is no suffix, which is what the
    PyAudio path produces: identical names, no way to tell them apart.
    """
    name = str(name or "")
    if name.endswith("]") and " [" in name:
        base, _, api = name.rpartition(" [")
        return base.strip(), api[:-1].strip()
    return name.strip(), ""


#: MME cuts device names off at 31 characters. A truncated name is a
#: PREFIX of the real one, so it can be folded back onto it - but only
#: when it is long enough for the prefix to mean something. Two devices
#: whose names agree for twenty characters are the same device.
_WIN_TRUNCATION_MIN = 20


def _windows_groups(devices):
    """{device index -> group} for Windows.

    One entry per physical microphone in ``Microphones``, every further
    copy of it in ``Other host APIs``. Without this the Windows dropdown
    is the same wall of near-identical lines the Linux one used to be -
    a machine with two microphones shows eight entries, three of which
    are called almost the same thing.

    Keyed by INDEX, not by name. The PyAudio path reports no host-API
    suffix at all, so the four copies of one microphone arrive as four
    identical strings; deciding "is this the one we kept?" by name then
    answers yes for all of them and nothing gets folded away.
    """
    rows = []
    for idx, (name, dev_idx) in enumerate(devices):
        base, api = split_host_api(name)
        try:
            rank = _WIN_API_PREFERENCE.index(api)
        except ValueError:
            # an API we do not know about, or none at all. Ranked after
            # the known ones, and first-come wins among equals.
            rank = len(_WIN_API_PREFERENCE) + (0 if api else 1)
        rows.append({"pos": idx, "base": base, "key": base.casefold(),
                     "api": api, "rank": rank})

    # fold MME's truncated names onto the full ones before grouping
    full = sorted({r["key"] for r in rows}, key=len, reverse=True)
    for row in rows:
        key = row["key"]
        if len(key) < _WIN_TRUNCATION_MIN:
            continue
        for candidate in full:
            if len(candidate) > len(key) and candidate.startswith(key):
                row["key"] = candidate
                break

    best = {}
    for row in rows:
        current = best.get(row["key"])
        if current is None or row["rank"] < current["rank"]:
            best[row["key"]] = row
    primary = {row["pos"] for row in best.values()}
    return {row["pos"]: (G_MIC if row["pos"] in primary else G_ALT)
            for row in rows}


def entry(eid, label, group, detail="", note="", is_default=False,
          available=True):
    return {"id": eid, "label": label, "group": group, "detail": detail,
            "note": note, "default": bool(is_default),
            "available": bool(available)}


def build(devices, sources=None, default_source=None, show_raw=False,
          selected="", log=None):
    """The full grouped list for the dropdown.

    ``devices``  [(name, index)] from PortAudio (already enumerated - this
                 function never touches the audio stack itself).
    ``sources``  pactl sources, or None to fetch them here.
    ``show_raw`` include the entries that need to be chosen deliberately:
                 the direct-hardware group on Linux, the duplicate
                 host-API entries on Windows. Off by default - on a
                 PipeWire desktop those are noise at best and the HDMI
                 ones are outputs, and on Windows they are the same
                 microphone listed three more times.

    A ``selected`` id that is not in the list any more is appended as an
    unavailable entry, so a refresh while VR is off does not silently
    reset the choice to the system default.
    """
    if sources is None:
        sources = mic_pactl.list_sources(log)
    if default_source is None:
        default_source = mic_pactl.default_source()

    out = [entry("", "System default", G_SYSTEM,
                 detail=(mic_pactl.describe_source(default_source)
                         if default_source else ""))]

    server = pick_server(devices)
    if sources and server is not None:
        for src in sources:
            group = src.get("group") or G_VIRTUAL
            out.append(entry(
                "pulse:" + src["name"],
                src.get("description") or src["name"],
                group,
                detail=src["name"],
                is_default=bool(default_source
                                and src["name"] == default_source)))
    elif sources and server is None and callable(log):
        log("Speech to Text: the sound server has sources but PortAudio "
            "has no 'pipewire'/'pulse' device to open them through - "
            "showing the raw device list instead.")

    win_groups = _windows_groups(devices) if IS_WINDOWS else {}
    for pos, (name, _idx) in enumerate(devices):
        group = win_groups.get(pos) if IS_WINDOWS \
            else classify_portaudio(name)
        if group in (G_RAW, G_ALT) and not show_raw:
            continue
        # The G_SERVER entries stay in the list even when the grouped
        # source list is there and makes them a duplicate of "System
        # default": they are the one entry that keeps working when the
        # PULSE_SOURCE routing does not, so they belong in the list -
        # just at the bottom, where they no longer look like the choice.
        label = name
        if IS_WINDOWS:
            base, api = split_host_api(name)
            # In Microphones the API is noise - it is the preferred one
            # by construction. In the alternates group it is the ONLY
            # thing telling two identical lines apart, so it stays.
            label = base if group == G_MIC else name
        out.append(entry("pa:" + name, label, group,
                         detail=name, note=_raw_note(name)))

    if selected:
        known = {e["id"] for e in out}
        if selected not in known and normalize(selected) not in known:
            out.append(entry(normalize(selected),
                             f"{label_for_id(selected)}  (not available)",
                             group_for_id(selected), available=False))
    return out


def normalize(eid):
    """A stored value in its canonical form.

    Pre-1.4.2 configs hold a bare PortAudio device name; everything
    without a known prefix is therefore one of those.
    """
    eid = str(eid or "")
    if not eid:
        return ""
    if eid.startswith("pulse:") or eid.startswith("pa:"):
        return eid
    return "pa:" + eid


def label_for_id(eid):
    eid = normalize(eid)
    if not eid:
        return "System default"
    if eid.startswith("pulse:"):
        node = eid[6:]
        return mic_pactl.describe_source(node) or node
    return eid[3:]


def group_for_id(eid):
    eid = normalize(eid)
    if not eid:
        return G_SYSTEM
    if eid.startswith("pulse:"):
        return G_VIRTUAL
    return classify_portaudio(eid[3:])


def pick_server(devices):
    """(name, index) of the PortAudio device that IS the sound server.

    This is the door every pactl source is opened through, so when there
    is none, the grouped list cannot be offered at all.
    """
    by_base = {}
    for name, idx in devices:
        by_base.setdefault(_base_name(name), (name, idx))
    for wanted in _SERVER_PREFERENCE:
        if wanted in by_base:
            return by_base[wanted]
    return None


def resolve(eid, devices, sources=None, log=None):
    """Turn a stored id into something the helper can open.

    Returns ``(index, node, note)``:

        index   PortAudio device index, -1 for the system default
        node    sound-server source to point the helper at, or ""
        note    a sentence for the user when it cannot be resolved,
                and "" when everything is in order

    ``index`` is None together with a note when the device is gone. The
    caller decides whether to refuse (stt_mic_strict) or fall back - see
    ui/pages/textbox_page.py.
    """
    eid = normalize(eid)
    if not eid:
        return -1, "", ""

    if eid.startswith("pulse:"):
        node = eid[6:]
        if sources is None:
            sources = mic_pactl.list_sources(log)
        names = {s.get("name") for s in sources}
        if names and node not in names:
            return None, "", (
                f"The selected source \u201c{label_for_id(eid)}\u201d is "
                f"not in the audio graph any more. If you just left VR, "
                f"its virtual microphone went with it \u2013 pick another "
                f"source or press \u27F3 Refresh.")
        server = pick_server(devices)
        if server is None:
            return None, "", (
                "There is no \u201cpipewire\u201d or \u201cpulse\u201d "
                "device to open sound-server sources through. Pick a "
                "device from Direct hardware instead (switch the list to "
                "show it).")
        return server[1], node, ""

    name = eid[3:]
    for dev_name, idx in devices:
        if dev_name == name:
            return idx, "", ""
    return None, "", (
        f"The selected microphone \u201c{name}\u201d is not available "
        f"right now. If you just left VR, its virtual microphone is gone "
        f"\u2013 pick another device or press \u27F3 Refresh.")


def has_grouping(devices=None):
    """True when the grouped list can be offered at all."""
    if not mic_pactl.available():
        return False
    if devices is not None and pick_server(devices) is None:
        return False
    return True
