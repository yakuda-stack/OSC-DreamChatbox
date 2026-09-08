"""
tests/test_plugin_layout.py - the order of the blocks a plugin card is
made of, and the {"type": "widget"} row that places the panel.

Four things are worth pinning down.

**Filling in what was left out**, because that is the whole contract of
parse_layout(): ``["widget"]`` has to mean "panel first, the rest as
before", not "panel only". The same rule is what carries a stored order
across an app update that adds a fourth block - it lands at the end
instead of taking the card apart.

**The widget row not being a setting.** It has a key, like a button
does, and for the same reason: so it stays unique. It must never reach
config.json and api.get() must have nothing to return for it, or
options() would ask a row without a "default" for its default.

**The three sources of an order** - user, manifest, default - and
specifically that a stored order is ignored while the manifest has
reordering off, but not deleted. An author who turns the switch back on
in the next release should find the user's arrangement still there.

**Every manifest that predates all of this**, which must produce exactly
the order it always produced.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from pathlib import Path

from core.plugins import (
    DEFAULT_LAYOUT, LAYOUT_BLOCKS, PluginManager, iter_settings, parse_layout)

FOLDER = Path("/tmp/does-not-have-to-exist")


def make(**keys):
    data = {"id": "demo", "name": "Demo"}
    data.update(keys)
    return PluginManager._plugin_from_dict(data, FOLDER)


def manager(tmp_path, **manifest):
    """A manager over one real plugin folder, so config.json is written
    and read the way it is in the app."""
    folder = tmp_path / "demo"
    folder.mkdir()
    manifest.update({"id": "demo", "name": "Demo", "main": "main.py"})
    (folder / "plugin.json").write_text(json.dumps(manifest),
                                        encoding="utf-8")
    (folder / "main.py").write_text("", encoding="utf-8")
    mgr = PluginManager(log=lambda *a: None, plugins_dir=tmp_path)
    mgr.discover()
    return mgr


# ------------------------------------------------------ parse_layout
def test_nothing_given_is_the_old_order():
    assert parse_layout(None) == DEFAULT_LAYOUT
    assert parse_layout([]) == DEFAULT_LAYOUT


def test_missing_blocks_are_appended():
    """["widget"] means 'panel first', never 'panel only'."""
    assert parse_layout(["widget"]) == ["widget", "chatbox", "settings"]


def test_a_full_order_is_taken_as_written():
    assert parse_layout(["widget", "settings", "chatbox"]) == [
        "widget", "settings", "chatbox"]


def test_unknown_names_are_dropped_not_kept():
    """A typo, or a block name from a newer app. Either way the card
    still renders in full."""
    assert parse_layout(["knobs", "widget"]) == [
        "widget", "chatbox", "settings"]


def test_duplicates_keep_their_first_position():
    assert parse_layout(["widget", "widget", "chatbox"]) == [
        "widget", "chatbox", "settings"]


def test_junk_falls_back_to_the_default():
    for value in ("widget", 42, {"widget": True}, [None, {}]):
        assert parse_layout(value) == DEFAULT_LAYOUT


def test_the_result_is_always_complete():
    for value in (None, ["widget"], ["nope"], ["settings", "settings"]):
        assert sorted(parse_layout(value)) == sorted(LAYOUT_BLOCKS)


# --------------------------------------------------------- manifests
def test_manifest_without_layout_is_unchanged():
    plugin = make()
    assert plugin.layout == DEFAULT_LAYOUT
    assert plugin.user_reorderable is False


def test_manifest_layout_reaches_the_plugin():
    plugin = make(layout=["widget"], user_reorderable=True)
    assert plugin.layout == ["widget", "chatbox", "settings"]
    assert plugin.user_reorderable is True


# ------------------------------------------------------- widget rows
def test_a_widget_row_survives_the_schema_parser():
    plugin = make(settings=[{"key": "panel", "type": "widget"}])
    assert [i["type"] for i in plugin.schema] == ["widget"]


def test_a_widget_row_holds_no_value():
    """Otherwise options() would ask a row without a "default" for one."""
    plugin = make(settings=[{"key": "panel", "type": "widget"},
                            {"key": "a", "type": "bool", "default": True}])
    assert [i["key"] for i in iter_settings(plugin.schema)] == ["a"]


def test_a_widget_row_may_sit_inside_a_group():
    """This is the point of the whole feature: the panel above
    "Connection" rather than under everything."""
    plugin = make(settings=[
        {"key": "conn", "type": "group", "label": "Connection", "items": [
            {"key": "panel", "type": "widget"},
            {"key": "a", "type": "bool", "default": True}]}])
    inner = plugin.schema[0]["items"]
    assert [i["type"] for i in inner] == ["widget", "bool"]
    assert [i["key"] for i in iter_settings(plugin.schema)] == ["a"]


def test_a_widget_row_shares_the_key_namespace():
    """Keys are unique across the whole schema; a widget row is not an
    exception, or a later setting could silently vanish."""
    plugin = make(settings=[{"key": "panel", "type": "widget"},
                            {"key": "panel", "type": "bool",
                             "default": True}])
    assert len(plugin.schema) == 1


# ----------------------------------------------- order at runtime
def test_layout_for_falls_back_to_the_manifest(tmp_path):
    mgr = manager(tmp_path, layout=["widget"], user_reorderable=True)
    assert mgr.layout_for("demo") == ["widget", "chatbox", "settings"]


def test_the_user_order_wins_over_the_manifest(tmp_path):
    mgr = manager(tmp_path, layout=["widget"], user_reorderable=True)
    mgr.set_layout("demo", ["settings", "chatbox", "widget"])
    assert mgr.layout_for("demo") == ["settings", "chatbox", "widget"]


def test_the_user_order_survives_a_restart(tmp_path):
    mgr = manager(tmp_path, user_reorderable=True)
    mgr.set_layout("demo", ["widget", "settings", "chatbox"])
    again = PluginManager(log=lambda *a: None, plugins_dir=tmp_path)
    again.discover()
    assert again.layout_for("demo") == ["widget", "settings", "chatbox"]


def test_the_user_order_lands_in_config_json(tmp_path):
    mgr = manager(tmp_path, user_reorderable=True)
    mgr.set_layout("demo", ["widget", "chatbox", "settings"])
    written = json.loads(
        (tmp_path / "demo" / "configs" / "config.json").read_text())
    assert written["layout"] == ["widget", "chatbox", "settings"]


def test_a_stored_order_is_completed_not_refused(tmp_path):
    """A config written before a block existed must not lose the card."""
    mgr = manager(tmp_path, user_reorderable=True)
    mgr.entry("demo")["layout"] = ["settings"]
    assert mgr.layout_for("demo") == ["settings", "chatbox", "widget"]


def test_reordering_off_ignores_a_stored_order_but_keeps_it(tmp_path):
    mgr = manager(tmp_path, user_reorderable=True)
    mgr.set_layout("demo", ["widget", "chatbox", "settings"])

    (tmp_path / "demo" / "plugin.json").write_text(json.dumps(
        {"id": "demo", "name": "Demo", "main": "main.py",
         "layout": ["settings"], "user_reorderable": False}),
        encoding="utf-8")
    again = PluginManager(log=lambda *a: None, plugins_dir=tmp_path)
    again.discover()

    assert again.layout_for("demo") == ["settings", "chatbox", "widget"]
    # still on disk, waiting for the author to change their mind
    assert again.entry("demo")["layout"] == ["widget", "chatbox", "settings"]


def test_set_layout_is_refused_when_the_author_said_no(tmp_path):
    mgr = manager(tmp_path)
    assert mgr.set_layout("demo", ["widget"]) is False
    assert mgr.entry("demo")["layout"] == []


def test_reset_layout_goes_back_to_the_manifest(tmp_path):
    mgr = manager(tmp_path, layout=["widget"], user_reorderable=True)
    mgr.set_layout("demo", ["settings", "chatbox", "widget"])
    assert mgr.reset_layout("demo") == ["widget", "chatbox", "settings"]
    assert mgr.entry("demo")["layout"] == []
