"""tests/test_app_capture.py - Two-way app filter against a fake pactl."""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json

import pytest

from core.backends import app_capture as ac


class FakePactl:
    def __init__(self):
        self.default = "alsa_output.headset"
        self.modules = {}
        self.next_mod = 100
        self.streams = [
            {"index": 1, "sink": "alsa_output.headset", "owner_module": None,
             "properties": {"application.name": "VRChat",
                            "application.process.binary": "VRChat.exe"}},
            {"index": 2, "sink": "alsa_output.headset", "owner_module": None,
             "properties": {"application.name": "spotify"}},
            {"index": 3, "sink": "alsa_output.headset", "owner_module": None,
             "properties": {"application.name": "Firefox",
                            "media.name": "YouTube Music"}},
        ]

    def __call__(self, args):
        a = list(args)
        if a[:3] == ["-f", "json", "list"] and a[3] == "sink-inputs":
            return json.dumps(self.streams)
        if a[:3] == ["-f", "json", "list"] and a[3] == "sinks":
            return json.dumps([{"index": 77, "name": ac.SINK_NAME}])
        if a == ["get-default-sink"]:
            return self.default + "\n"
        if a[0] == "load-module":
            self.next_mod += 1
            self.modules[str(self.next_mod)] = " ".join(a[1:])
            if a[1] == "module-loopback":
                self.streams.append(
                    {"index": 9, "sink": self.default,
                     "owner_module": str(self.next_mod),
                     "properties": {"application.name": "Loopback"}})
            return f"{self.next_mod}\n"
        if a[0] == "unload-module":
            self.modules.pop(a[1], None)
            return ""
        if a[0] == "move-sink-input":
            for s in self.streams:
                if s["index"] == int(a[1]):
                    s["sink"] = a[2]
            return ""
        if a[:3] == ["list", "short", "modules"]:
            return "\n".join(f"{k}\tx\t{v}" for k, v in self.modules.items())
        return ""

    def sink_of(self, idx):
        return next(s["sink"] for s in self.streams if s["index"] == idx)


@pytest.fixture(autouse=True)
def _no_real_pipewire(monkeypatch):
    """Never touch the machine's real audio graph: without this, a PC
    that has pw-link (every PipeWire desktop) ran these tests in link
    mode against its live pw-dump."""
    monkeypatch.setattr(ac, "_pw", lambda args, timeout=4: "")
    monkeypatch.setattr(ac, "pipewire_available", lambda: False)
    monkeypatch.setattr(ac, "method", lambda: ac.METHOD_MOVE)


def _router(monkeypatch, mode, patterns):
    fake = FakePactl()
    monkeypatch.setattr(ac, "_run", fake)
    monkeypatch.setattr(ac, "available", lambda: True)
    r = ac.AppRouter()
    r.configure(mode, ac.parse_patterns(patterns))
    return r, fake


def test_only_vrchat(monkeypatch):
    r, fake = _router(monkeypatch, ac.MODE_ONLY, "vrchat")
    assert r.acquire("listen") == ""
    assert fake.sink_of(1) == ac.SINK_NAME
    assert fake.sink_of(2) == "alsa_output.headset"
    assert fake.sink_of(9) == "alsa_output.headset"   # our loopback
    r.release("listen")
    assert fake.sink_of(1) == "alsa_output.headset"
    assert fake.modules == {}


def test_except_music(monkeypatch):
    r, fake = _router(monkeypatch, ac.MODE_EXCEPT, "Spotify, YouTube Music")
    assert r.acquire("listen") == ""
    assert fake.sink_of(1) == ac.SINK_NAME
    assert fake.sink_of(2) == "alsa_output.headset"
    assert fake.sink_of(3) == "alsa_output.headset"
    r.shutdown()
    assert fake.modules == {}


def test_two_users_share_one_setup(monkeypatch):
    r, fake = _router(monkeypatch, ac.MODE_ONLY, "vrchat")
    r.acquire("test")
    r.acquire("listen")
    r.release("test")
    assert r.active and fake.sink_of(1) == ac.SINK_NAME
    r.release("listen")
    assert not r.active


def test_pattern_change_moves_back(monkeypatch):
    r, fake = _router(monkeypatch, ac.MODE_ONLY, "vrchat")
    r.acquire("listen")
    r.configure(ac.MODE_ONLY, ["spotify"])
    r.sync()
    assert fake.sink_of(1) == "alsa_output.headset"
    assert fake.sink_of(2) == ac.SINK_NAME
    r.shutdown()


def _pw_dump(vr_linked=False):
    objs = [
        {"id": 50, "type": "PipeWire:Interface:Node",
         "info": {"props": {"node.name": ac.SINK_NAME,
                            "media.class": "Audio/Sink"}}},
        {"id": 51, "type": "PipeWire:Interface:Port",
         "info": {"props": {"node.id": 50, "port.direction": "in",
                            "port.name": "playback_FL",
                            "audio.channel": "FL"}}},
        {"id": 52, "type": "PipeWire:Interface:Port",
         "info": {"props": {"node.id": 50, "port.direction": "in",
                            "port.name": "playback_FR",
                            "audio.channel": "FR"}}},
        {"id": 60, "type": "PipeWire:Interface:Node",
         "info": {"props": {"media.class": "Stream/Output/Audio",
                            "application.name": "VRChat"}}},
        {"id": 61, "type": "PipeWire:Interface:Port",
         "info": {"props": {"node.id": 60, "port.direction": "out",
                            "audio.channel": "FL"}}},
        {"id": 62, "type": "PipeWire:Interface:Port",
         "info": {"props": {"node.id": 60, "port.direction": "out",
                            "audio.channel": "FR"}}},
        {"id": 70, "type": "PipeWire:Interface:Node",
         "info": {"props": {"media.class": "Stream/Output/Audio",
                            "application.name": "spotify"}}},
        {"id": 71, "type": "PipeWire:Interface:Port",
         "info": {"props": {"node.id": 70, "port.direction": "out",
                            "audio.channel": "MONO"}}},
    ]
    return json.dumps(objs)


def test_pipewire_link_mode_never_moves(monkeypatch):
    fake = FakePactl()
    monkeypatch.setattr(ac, "_run", fake)
    monkeypatch.setattr(ac, "available", lambda: True)
    monkeypatch.setattr(ac, "method", lambda: ac.METHOD_LINK)
    calls = []

    def pw(args, timeout=4):
        calls.append(list(args))
        return _pw_dump() if args == ["pw-dump"] else ""

    monkeypatch.setattr(ac, "_pw", pw)
    r = ac.AppRouter()
    r.configure(ac.MODE_ONLY, ["vrchat"])
    assert r.acquire("listen") == ""
    links = [c for c in calls if c[0] == "pw-link"]
    assert ["pw-link", "61", "51"] in links and ["pw-link", "62", "52"] in links
    assert not any("71" in c for c in links)              # spotify untouched
    # nothing moved and no loopback loaded - headphones keep direct path
    assert fake.sink_of(1) == "alsa_output.headset"
    assert not any("loopback" in v for v in fake.modules.values())
    r.release("listen")
    assert fake.modules == {}


def test_plan_links_mono():
    pairs = ac.plan_links([(5, "MONO")], {"FL": 1, "FR": 2})
    assert pairs == [(5, 1), (5, 2)]
