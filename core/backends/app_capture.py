"""
core/backends/app_capture.py - record only some programs (Linux)

Two-way translation listens to what the PC plays. With Spotify or
YouTube Music running next to VRChat, "what the PC plays" is mostly
music - and the recogniser tries to translate lyrics.

Every program's audio is a stream of its own, so the app can pick:

PipeWire (the normal case, METHOD_LINK) - zero latency for you
    1. a virtual output is created              (module-null-sink)
    2. the ports of the streams that SHOULD be translated are linked
       to it IN ADDITION to their normal route  (pw-link)
       - PipeWire fans an output port out to any number of inputs, so
         your headphones keep the untouched, direct path: no loopback,
         no added delay, nothing moved
    3. Two-way records that output's monitor - and nothing else

Plain PulseAudio (fallback, METHOD_MOVE) - cannot fan out, so the
streams are MOVED onto the virtual output and it is looped back to your
real output with module-loopback. That costs ~30 ms on what you hear;
the UI says so.

"Only these apps" takes the matching streams (VRChat), "Everything
except" all others (not Spotify). A background thread re-checks every
two seconds, because programs open new streams all the time (VRChat
does on every world change).

On stop the virtual output is unloaded - in link mode that drops the
extra links and nothing else changes; in move mode every stream goes
back where it came from first. Leftovers of a crash are removed on the
next start.

Works with PulseAudio and PipeWire (pipewire-pulse) - anything pactl
talks to. Windows has no equivalent that works without a driver; there
the hint points to routing VRChat to a virtual cable instead.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading

from core.backends import mic_pactl

#: the virtual output. Fixed name, so leftovers can be found again.
SINK_NAME = "dreamchatbox_2way"
SINK_DESC = "DreamChatbox-Two-way"
MONITOR = f"{SINK_NAME}.monitor"
#: the stored id Two-way records from while a filter is on
SOURCE_ID = f"pulse:{MONITOR}"

MODE_OFF = "off"
MODE_ONLY = "only"
MODE_EXCEPT = "except"

RESYNC_SEC = 2.0

METHOD_LINK = "link"     # PipeWire: extra links, headphones untouched
METHOD_MOVE = "move"     # PulseAudio: move + loopback (~30 ms)

#: our own loopback stream and other audio plumbing - never moved
_PLUMBING = ("loopback", "dreamchatbox", "speech-dispatcher", "pavucontrol",
             "osc-dreamchatbox", "peak detect")


def available() -> bool:
    return mic_pactl.available()


def pipewire_available() -> bool:
    """pw-link + pw-dump present AND the server really is PipeWire."""
    if not (shutil.which("pw-link") and shutil.which("pw-dump")):
        return False
    info = _run(["info"])
    return "pipewire" in info.lower() if info else True


def method() -> str:
    return METHOD_LINK if pipewire_available() else METHOD_MOVE


def _pw(args, timeout=4):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True,
                           timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except Exception:      # noqa: BLE001
        return ""


def pw_graph():
    """(stream nodes, our sink's input ports, existing links) from
    pw-dump. Stream node: {id, app, binary, media, label, ports:
    [(port id, channel)]}."""
    try:
        data = json.loads(_pw(["pw-dump"]) or "[]")
    except ValueError:
        data = []
    nodes, ports, links = {}, [], set()
    sink_id = None
    for o in data:
        t = o.get("type", "")
        info = o.get("info") or {}
        props = info.get("props") or {}
        if t.endswith("Node"):
            if props.get("node.name") == SINK_NAME:
                sink_id = o.get("id")
            if props.get("media.class") == "Stream/Output/Audio":
                st = _stream(o.get("id"), None, None, props)
                st["ports"] = []
                nodes[o.get("id")] = st
        elif t.endswith("Port"):
            ports.append((o.get("id"), props))
        elif t.endswith("Link"):
            links.add((info.get("output-port-id"), info.get("input-port-id")))
    sink_ports = {}
    for pid, props in ports:
        nid = props.get("node.id")
        direction = props.get("port.direction")
        ch = str(props.get("audio.channel") or props.get("port.name") or "")
        if nid in nodes and direction == "out":
            nodes[nid]["ports"].append((pid, ch.upper()))
        elif nid == sink_id and direction == "in" \
                and "monitor" not in str(props.get("port.name", "")):
            sink_ports[ch.upper().replace("PLAYBACK_", "")] = pid
    return list(nodes.values()), sink_ports, links


def plan_links(stream_ports, sink_ports):
    """Which (out port, in port) pairs to link one stream to our stereo
    sink. FL->FL, FR->FR, MONO->both, anything else by position."""
    left = sink_ports.get("FL") or sink_ports.get("MONO")
    right = sink_ports.get("FR") or left
    pairs = []
    for i, (pid, ch) in enumerate(stream_ports):
        ch = ch.split("_")[-1]
        if ch in ("FL", "SL", "RL"):
            targets = [left]
        elif ch in ("FR", "SR", "RR"):
            targets = [right]
        elif ch in ("MONO", "FC", "LFE"):
            targets = [left, right]
        else:
            targets = [left if i % 2 == 0 else right]
        pairs += [(pid, t) for t in targets if t is not None]
    return pairs


def _run(args):
    return mic_pactl._run(args)


def parse_patterns(text: str):
    """'Spotify, YouTube Music' -> ['spotify', 'youtube music']"""
    return [p.strip().lower() for p in re.split(r"[,;\n]", text or "")
            if p.strip()]


# ------------------------------------------------------------ streams
def list_streams():
    """Every program currently playing: [{index, sink, owner_module,
    app, binary, media, label}]."""
    out = []
    text = _run(["-f", "json", "list", "sink-inputs"])
    data = None
    if text:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    if isinstance(data, list):
        for e in data:
            if not isinstance(e, dict):
                continue
            p = e.get("properties") or {}
            out.append(_stream(e.get("index"), e.get("sink"),
                               e.get("owner_module"), p))
        return [s for s in out if s["index"] is not None]
    # older pactl without -f json
    cur = None
    props = {}
    for line in _run(["list", "sink-inputs"]).splitlines():
        m = re.match(r"^Sink Input #(\d+)", line)
        if m:
            if cur is not None:
                out.append(_stream(cur.get("index"), cur.get("sink"),
                                   cur.get("owner"), props))
            cur, props = {"index": int(m.group(1))}, {}
            continue
        if cur is None:
            continue
        st = line.strip()
        if st.startswith("Sink:"):
            cur["sink"] = st.split(":", 1)[1].strip()
        elif st.startswith("Owner Module:"):
            cur["owner"] = st.split(":", 1)[1].strip()
        else:
            pm = re.match(r'^([\w.\-]+) = "(.*)"$', st)
            if pm:
                props[pm.group(1)] = pm.group(2)
    if cur is not None:
        out.append(_stream(cur.get("index"), cur.get("sink"),
                           cur.get("owner"), props))
    return out


def _stream(index, sink, owner, props):
    app = str(props.get("application.name") or "")
    binary = str(props.get("application.process.binary") or "")
    media = str(props.get("media.name") or "")
    label = app or binary or media or f"stream {index}"
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = None
    return {"index": index, "sink": sink, "owner_module": owner,
            "app": app, "binary": binary, "media": media, "label": label}


def running_apps():
    """Distinct program names playing right now, for the "Add" menu."""
    seen = []
    for s in list_streams():
        if _is_plumbing(s):
            continue
        name = s["app"] or s["binary"]
        if name and name not in seen:
            seen.append(name)
    return seen


def _is_plumbing(stream):
    hay = f"{stream['app']} {stream['binary']} {stream['media']}".lower()
    return any(p in hay for p in _PLUMBING)


def matches(stream, patterns) -> bool:
    """Case-insensitive substring match against app name, binary and
    media name - "vrchat" hits "VRChat", "VRChat.exe" and a Proton
    stream called "VRChat.exe"."""
    hay = f"{stream['app']} {stream['binary']} {stream['media']}".lower()
    return any(p in hay for p in patterns)


def wanted(stream, mode, patterns) -> bool:
    if mode == MODE_ONLY:
        return matches(stream, patterns)
    if mode == MODE_EXCEPT:
        return not matches(stream, patterns)
    return False


# ------------------------------------------------------------- router
class AppRouter:
    """Owns the virtual output and keeps the right streams on it."""

    def __init__(self, log=lambda s: None):
        self.log = log
        self.mode = MODE_OFF
        self.patterns = []
        self._sink_module = None
        self._loop_module = None
        self._sink_index = None
        self._origin = {}          # stream index -> sink it came from
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._users = set()
        self.method = METHOD_MOVE
        self._linked = {}          # stream node id -> [(out, in)]

    @property
    def active(self):
        return self._sink_module is not None

    def configure(self, mode, patterns):
        self.mode = mode or MODE_OFF
        self.patterns = list(patterns or [])

    # -- lifecycle -----------------------------------------------------
    def acquire(self, who):
        """Start (if needed) on behalf of `who` ("listen" / "test").
        Returns '' on success or a sentence why not."""
        with self._lock:
            self._users.add(who)
            if self.active:
                return ""
            err = self._setup()
            if err:
                self._users.discard(who)
                return err
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="twoway-router")
        self._thread.start()
        return ""

    def release(self, who):
        with self._lock:
            self._users.discard(who)
            if self._users or not self.active:
                return
            self._stop.set()
            self._teardown()

    def shutdown(self):
        with self._lock:
            self._users.clear()
            self._stop.set()
            if self.active:
                self._teardown()

    def _setup(self):
        if not available():
            return "pactl is not available (PulseAudio / PipeWire needed)."
        cleanup_leftovers(self.log)
        self.method = method()
        default = _run(["get-default-sink"]).strip()
        mod = _run(["load-module", "module-null-sink",
                    f"sink_name={SINK_NAME}",
                    f"sink_properties=device.description={SINK_DESC}"]
                   ).strip()
        if not mod.isdigit():
            return "could not create the virtual output (module-null-sink)."
        self._sink_module = mod
        if default and _run(["get-default-sink"]).strip() != default:
            _run(["set-default-sink", default])
        if self.method == METHOD_LINK:
            # nothing is moved and nothing looped: your headphones keep
            # the direct path, the sink only gets an extra copy
            self.log(f"Two-way filter: PipeWire link mode, no added "
                     f"latency ({self.mode}: "
                     f"{', '.join(self.patterns) or '-'})")
            self.sync()
            return ""
        # PulseAudio: you keep hearing what gets moved onto it
        loop = _run(["load-module", "module-loopback",
                     f"source={MONITOR}"]
                    + ([f"sink={default}"] if default else [])
                    + ["latency_msec=30",
                       "source_dont_move=true", "sink_dont_move=true"]
                    ).strip()
        self._loop_module = loop if loop.isdigit() else None
        if self._loop_module is None:
            self.log("Two-way filter: loopback failed - moved apps would "
                     "be silent, so filtering is not started.")
            self._teardown()
            return "could not loop the virtual output back to your speakers."
        # a new sink must never become the default output
        if default and _run(["get-default-sink"]).strip() != default:
            _run(["set-default-sink", default])
        self._sink_index = _sink_index(SINK_NAME)
        self.log(f"Two-way filter: virtual output ready "
                 f"({self.mode}: {', '.join(self.patterns) or '-'})")
        self.sync()
        return ""

    def _teardown(self):
        # link mode: unloading the sink drops every extra link with it
        self._linked.clear()
        # move mode: everything we moved goes back where it came from
        for s in list_streams():
            if s["index"] in self._origin and self._on_ours(s):
                _run(["move-sink-input", str(s["index"]),
                      str(self._origin[s["index"]])])
        self._origin.clear()
        for mod in (self._loop_module, self._sink_module):
            if mod:
                _run(["unload-module", str(mod)])
        self._loop_module = self._sink_module = None
        self._sink_index = None
        self.log("Two-way filter: stopped, apps are back on their output")

    def _on_ours(self, stream):
        sink = str(stream.get("sink"))
        return sink in (SINK_NAME, str(self._sink_index))

    # -- the actual work -----------------------------------------------
    def sync(self):
        if not self.active:
            return
        if self.method == METHOD_LINK:
            self._sync_links()
            return
        default = _run(["get-default-sink"]).strip() or "@DEFAULT_SINK@"
        for s in list_streams():
            if s["index"] is None or _is_plumbing(s):
                continue
            if str(s.get("owner_module")) == str(self._loop_module):
                continue
            want = wanted(s, self.mode, self.patterns)
            ours = self._on_ours(s)
            if want and not ours:
                self._origin[s["index"]] = s.get("sink") or default
                _run(["move-sink-input", str(s["index"]), SINK_NAME])
                self.log(f"Two-way filter: recording “{s['label']}”")
            elif not want and ours:
                back = self._origin.pop(s["index"], default)
                _run(["move-sink-input", str(s["index"]), str(back)])
                self.log(f"Two-way filter: ignoring “{s['label']}”")

    def _sync_links(self):
        nodes, sink_ports, links = pw_graph()
        if not sink_ports:
            return          # sink not in the graph yet
        alive = set()
        for st in nodes:
            if _is_plumbing(st):
                continue
            nid = st["index"]
            want = wanted(st, self.mode, self.patterns)
            have = self._linked.get(nid)
            if want:
                alive.add(nid)
                pairs = plan_links(st["ports"], sink_ports)
                missing = [pr for pr in pairs if pr not in links]
                for out_p, in_p in missing:
                    _pw(["pw-link", str(out_p), str(in_p)])
                if pairs and not have:
                    self.log(f"Two-way filter: recording "
                             f"\u201c{st['label']}\u201d")
                self._linked[nid] = pairs
            elif have:
                for out_p, in_p in have:
                    _pw(["pw-link", "-d", str(out_p), str(in_p)])
                self._linked.pop(nid, None)
                self.log(f"Two-way filter: ignoring \u201c{st['label']}\u201d")
        for nid in list(self._linked):
            if nid not in alive and nid not in {n["index"] for n in nodes}:
                self._linked.pop(nid, None)   # stream closed

    def _loop(self):
        while not self._stop.wait(RESYNC_SEC):
            try:
                with self._lock:
                    self.sync()
            except Exception as e:      # noqa: BLE001
                self.log(f"Two-way filter: {e}")


def _sink_index(name):
    text = _run(["-f", "json", "list", "sinks"])
    try:
        for e in json.loads(text or "[]"):
            if e.get("name") == name:
                return e.get("index")
    except (ValueError, AttributeError):
        pass
    for line in _run(["list", "short", "sinks"]).splitlines():
        parts = line.split("\t")
        if len(parts) > 1 and parts[1] == name:
            return parts[0]
    return None


def cleanup_leftovers(log=lambda s: None):
    """Unloads our modules from a previous run that did not stop cleanly.
    The sound server moves their streams to the default output itself."""
    n = 0
    for line in _run(["list", "short", "modules"]).splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and (SINK_NAME in parts[2]):
            _run(["unload-module", parts[0]])
            n += 1
    if n:
        log(f"Two-way filter: removed {n} leftover module(s) of a "
            f"previous run")
