"""tests/test_plugin_tags.py - "tags" in plugin.json and the store search
(v1.5.8)."""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from core.plugin_store import StoreEntry, Source, all_tags, matches
from core.plugins import PluginManager, parse_tags


def entry(name, tags=(), summary="", pid=""):
    e = StoreEntry(source=Source.__new__(Source))
    e.name, e.pid, e.author = name, pid or name.lower(), "yakuda"
    e.summary = e.description = summary
    e.tags = list(tags)
    return e


def test_parse_tags_cleans_up():
    assert parse_tags(["#VRChat", "vrchat", "  Hardware  Stats "]) == [
        "vrchat", "hardware stats"]
    assert parse_tags("stream, twitch ,") == ["stream", "twitch"]
    assert parse_tags(None) == [] and parse_tags(42) == []
    assert len(parse_tags([f"t{i}" for i in range(20)])) == 8
    assert parse_tags(["x" * 40]) == ["x" * 24]


def test_manifest_tags_and_missing_tags():
    folder = Path("/tmp/nowhere")
    p = PluginManager._plugin_from_dict(
        {"id": "a", "name": "A", "tags": ["VR", "#Clock"]}, folder)
    assert p.tags == ["vr", "clock"]
    assert "tags" not in p.extra
    assert PluginManager._plugin_from_dict(
        {"id": "b", "name": "B"}, folder).tags == []


def test_search_words_and_tags():
    world = entry("World Stats", ["vrchat", "battery"], "players and FPS")
    life = entry("Life Stats", ["weather", "clock"], "weather, heart rate")
    assert matches(world, "") and matches(world, "fps")
    assert matches(life, "heart rate")          # every word must match
    assert not matches(life, "heart fps")
    assert matches(world, "#vrch")               # tag prefix
    assert not matches(world, "#weather")
    assert matches(life, "WEATHER")              # case does not matter
    assert matches(world, tag="battery") and not matches(life, tag="battery")


def test_all_tags_most_used_first():
    es = [entry("a", ["vrchat", "fps"]), entry("b", ["vrchat"]),
          entry("c", ["clock"])]
    assert all_tags(es) == ["vrchat", "clock", "fps"]
