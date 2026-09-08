"""
tests/test_plugin_chatbox.py - the "chatbox" manifest block.

The one thing worth pinning down here is how far the switch reaches. It
stops exactly two hooks - get_text() and get_lines(). get_values() keeps
running, because a plugin can have nothing to say in the chatbox and
still offer {its_name} to somebody else's line. That distinction is the
whole design decision, and it is the kind of thing a later refactor
quietly widens into "the plugin contributes nothing".

The rest is the same shape as the block layout in
tests/test_plugin_layout.py: the author decides whether the user gets a
say, a stored answer waits rather than being lost when they turn the
switch off again, and a manifest that predates the key behaves exactly
as it did before.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from pathlib import Path

from core.plugins import PluginManager, parse_flag_block

FOLDER = Path("/tmp/does-not-have-to-exist")

PLUGIN_SRC = """
def get_text():
    return "line"
def get_lines():
    return ["extra"]
def get_values():
    return {"mood": "fine"}
"""


def make(**keys):
    data = {"id": "demo", "name": "Demo"}
    data.update(keys)
    return PluginManager._plugin_from_dict(data, FOLDER)


def manager(tmp_path, **manifest):
    folder = tmp_path / "demo"
    folder.mkdir()
    manifest.update({"id": "demo", "name": "Demo", "main": "main.py"})
    (folder / "plugin.json").write_text(json.dumps(manifest),
                                        encoding="utf-8")
    (folder / "main.py").write_text(PLUGIN_SRC, encoding="utf-8")
    mgr = PluginManager(log=lambda *a: None, plugins_dir=tmp_path)
    mgr.discover()
    return mgr


# ------------------------------------------------------------ parsing
def test_no_block_means_on():
    assert make().chatbox == {"enabled": True, "user_editable": False}


def test_the_author_can_switch_it_off():
    assert make(chatbox={"enabled": False}).chatbox["enabled"] is False


def test_quoted_booleans_are_accepted():
    """Manifests are hand-written and "true" in quotes is the single
    most common thing an author gets wrong."""
    plugin = make(chatbox={"enabled": "false", "user_editable": "yes"})
    assert plugin.chatbox == {"enabled": False, "user_editable": True}


def test_junk_falls_back_to_on():
    for value in ("yes", 1, [], None):
        assert parse_flag_block(value)["enabled"] is True


# -------------------------------------------------------- the effect
def test_a_silent_plugin_still_fills_its_placeholders(tmp_path):
    """The whole point: a plugin can have nothing to say in the chatbox
    and still offer {its_name} to somebody else's line."""
    mgr = manager(tmp_path, chatbox={"enabled": False})
    mgr.set_enabled("demo", True)
    snap = mgr.snapshot()["demo"]
    assert snap["text"] == ""
    assert snap["lines"] == []
    assert snap["values"] == {"mood": "fine"}


def test_a_normal_plugin_is_unaffected(tmp_path):
    mgr = manager(tmp_path)
    mgr.set_enabled("demo", True)
    snap = mgr.snapshot()["demo"]
    assert snap["text"] == "line"
    assert snap["lines"] == ["extra"]


def test_the_user_switch_overrides_the_manifest(tmp_path):
    mgr = manager(tmp_path,
                  chatbox={"enabled": False, "user_editable": True})
    mgr.set_enabled("demo", True)
    assert mgr.chat_enabled("demo") is False
    mgr.set_chat_enabled("demo", True)
    assert mgr.chat_enabled("demo") is True
    assert mgr.snapshot()["demo"]["text"] == "line"


def test_switching_it_off_invalidates_the_snapshot(tmp_path):
    """Without that, the line stays on screen until something else
    happens to invalidate the cache - which looks like the switch not
    working."""
    mgr = manager(tmp_path,
                  chatbox={"enabled": True, "user_editable": True})
    mgr.set_enabled("demo", True)
    assert mgr.snapshot()["demo"]["text"] == "line"
    mgr.set_chat_enabled("demo", False)
    assert mgr.snapshot()["demo"]["text"] == ""


def test_the_user_switch_survives_a_restart(tmp_path):
    mgr = manager(tmp_path,
                  chatbox={"enabled": True, "user_editable": True})
    mgr.set_chat_enabled("demo", False)
    again = PluginManager(log=lambda *a: None, plugins_dir=tmp_path)
    again.discover()
    assert again.chat_enabled("demo") is False


def test_a_stored_switch_is_ignored_without_the_opt_in(tmp_path):
    """Same rule as the block layout: the author decides whether the
    user gets a say, and an old answer waits rather than being lost."""
    mgr = manager(tmp_path, chatbox={"enabled": True})
    mgr.entry("demo")["chat"] = False
    assert mgr.chat_enabled("demo") is True
    assert mgr.entry("demo")["chat"] is False


def test_an_unknown_plugin_is_treated_as_chatty(tmp_path):
    mgr = manager(tmp_path)
    assert mgr.chat_enabled("not-installed") is True
