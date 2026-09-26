"""
tests/test_profile_plugins.py - plugins travelling with a profile (v1.5.7).

A profile lists its plugins as ``plugin_<id>: true/false`` at the end of
the file, and keeps their settings in profiles/plugins/<name>.json.
Loading it switches the listed plugins and puts their settings in place;
a plugin the profile does not mention is left alone, and a profile made
before v1.5.7 (no plugin_ keys at all) changes nothing.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json

from core import profiles
from core.plugins import PluginManager

PLUGIN_SRC = """
def get_text():
    return "x"
"""


def manager(tmp_path, *pids):
    base = tmp_path / "plugins"
    for pid in pids:
        folder = base / pid
        folder.mkdir(parents=True)
        (folder / "plugin.json").write_text(json.dumps({
            "id": pid, "name": pid.title(), "main": "main.py",
            "settings": [{"key": "speed", "type": "int", "default": 1}]}),
            encoding="utf-8")
        (folder / "main.py").write_text(PLUGIN_SRC, encoding="utf-8")
    mgr = PluginManager(log=lambda *a: None, plugins_dir=base)
    mgr.discover()
    return mgr


# ------------------------------------------------------ profile file
def test_plugin_keys_go_to_the_end(tmp_path):
    cfg = {"aio_active": True, "plugin_stale": True}
    profiles.save_profile("Gaming", cfg, tmp_path,
                          plugins={"oscleash": True, "afk": False})
    text = (tmp_path / "Gaming.json").read_text(encoding="utf-8")
    keys = list(json.loads(text))
    assert keys == ["aio_active", "plugin_afk", "plugin_oscleash"]


def test_plugin_flags_read_back(tmp_path):
    profiles.save_profile("G", {}, tmp_path,
                          plugins={"oscleash": True, "afk": False})
    stored = profiles.read_profile("G", tmp_path)
    assert profiles.plugin_flags(stored) == {"oscleash": True, "afk": False}


def test_plugin_keys_never_reach_the_config(tmp_path):
    stored = {"aio_active": True, "plugin_oscleash": True}
    assert "plugin_oscleash" not in profiles.merge_for_load({}, stored)


def test_old_profile_has_no_flags():
    assert profiles.plugin_flags({"aio_active": True}) == {}


def test_settings_file_is_not_a_profile(tmp_path):
    profiles.save_profile("G", {}, tmp_path)
    profiles.save_plugin_settings("G", {"afk": {"options": {}}}, tmp_path)
    assert (tmp_path / "plugins" / "G.json").is_file()
    assert profiles.list_profiles(tmp_path) == ["G"]
    assert profiles.read_plugin_settings("G", tmp_path) == {
        "afk": {"options": {}}}


def test_broken_settings_file_is_ignored(tmp_path):
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "G.json").write_text("{nope", encoding="utf-8")
    assert profiles.read_plugin_settings("G", tmp_path) == {}
    assert profiles.read_plugin_settings("missing", tmp_path) == {}


def test_rename_and_delete_take_the_settings_along(tmp_path):
    profiles.save_profile("A", {}, tmp_path)
    profiles.save_plugin_settings("A", {"x": {}}, tmp_path)
    profiles.rename_profile("A", "B", tmp_path)
    assert profiles.read_plugin_settings("B", tmp_path) == {"x": {}}
    assert not (tmp_path / "plugins" / "A.json").exists()
    profiles.delete_profile("B", tmp_path)
    assert not (tmp_path / "plugins" / "B.json").exists()


# --------------------------------------------------- plugin manager
def test_state_roundtrip_between_profiles(tmp_path):
    mgr = manager(tmp_path, "afk", "leash")
    mgr.set_enabled("afk", True)
    mgr.set_enabled("leash", False)
    mgr.set_option("afk", "speed", 5)
    flags, settings = mgr.profile_state()
    assert flags == {"afk": True, "leash": False}
    assert settings["afk"]["options"]["speed"] == 5
    assert "enabled" not in settings["afk"]
    assert "chat" not in settings["afk"]

    # another setup: afk off with other settings, leash on
    mgr.apply_profile({"afk": False, "leash": True},
                      {"afk": {"options": {"speed": 9}}})
    assert not mgr.is_enabled("afk") and mgr.is_enabled("leash")
    assert mgr.options("afk")["speed"] == 9

    # and back
    mgr.apply_profile(flags, settings)
    assert mgr.is_enabled("afk") and not mgr.is_enabled("leash")
    assert mgr.options("afk")["speed"] == 5
    # survives a restart: it is in the plugin's config.json
    again = PluginManager(log=lambda *a: None,
                          plugins_dir=tmp_path / "plugins")
    again.discover()
    assert again.options("afk")["speed"] == 5


def test_unmentioned_plugins_are_left_alone(tmp_path):
    mgr = manager(tmp_path, "afk", "leash")
    mgr.set_enabled("leash", True)
    mgr.apply_profile({"afk": False}, {})
    assert not mgr.is_enabled("afk")
    assert mgr.is_enabled("leash")


def test_missing_plugins_are_reported(tmp_path):
    mgr = manager(tmp_path, "afk")
    missing = mgr.apply_profile(
        {"afk": True, "oscleash": True, "gone": False}, {})
    assert missing == ["oscleash"]


def test_chat_answer_stays_on_this_machine(tmp_path):
    mgr = manager(tmp_path, "afk")
    mgr.entry("afk")["chat"] = False
    mgr.apply_profile({"afk": True}, {"afk": {"chat": True}})
    assert mgr.entry("afk")["chat"] is False


# ------------------------------------------- "save into profile?" popup
def test_ask_only_for_unknown_and_unasked():
    stored = {"plugin_afk": True}
    assert profiles.plugins_to_ask(
        stored, ["afk", "leash", "clock"], ["clock"]) == ["leash"]


def test_ask_nothing_when_all_known():
    stored = {"plugin_afk": True, "plugin_leash": False}
    assert profiles.plugins_to_ask(stored, ["afk", "leash"], []) == []


def test_asked_list_is_not_part_of_a_profile(tmp_path):
    cfg = {profiles.ASKED_KEY: {"G": ["afk"]}, "aio_active": True}
    profiles.save_profile("G", cfg, tmp_path)
    assert profiles.ASKED_KEY not in profiles.read_profile("G", tmp_path)


# ------------------------------------------------------ import / export
def test_export_import_roundtrip(tmp_path):
    src, dst = tmp_path / "a", tmp_path / "b"
    profiles.save_profile("Gaming", {"aio_active": True}, src,
                          plugins={"leash": True})
    profiles.save_plugin_settings("Gaming",
                                  {"leash": {"options": {"len": 3}}}, src)
    out = tmp_path / ("Gaming" + profiles.EXPORT_SUFFIX)
    profiles.export_profile("Gaming", out, src)

    name, stored, plugin_data = profiles.read_export(out)
    assert name == "Gaming"
    assert stored["plugin_leash"] is True
    profiles.import_profile(name, stored, plugin_data, dst)
    assert profiles.read_profile("Gaming", dst) == {
        "aio_active": True, "plugin_leash": True}
    assert profiles.read_plugin_settings("Gaming", dst) == {
        "leash": {"options": {"len": 3}}}


def test_import_plain_profile_file(tmp_path):
    f = tmp_path / "Music.json"
    f.write_text(json.dumps({"media_active": True}), encoding="utf-8")
    assert profiles.read_export(f) == ("Music", {"media_active": True}, {})


def test_import_refuses_other_formats(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
    try:
        profiles.read_export(f)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_import_never_moves_the_osc_port(tmp_path):
    profiles.import_profile("X", {"osc_port": 1234, "aio_active": True},
                            {}, tmp_path)
    assert profiles.read_profile("X", tmp_path) == {"aio_active": True}


def test_save_on_exit_is_app_wide():
    assert profiles.SAVE_ON_EXIT_KEY in profiles.APP_WIDE_KEYS


# ------------------------------------------------ manifest "headless"
def _headless_manager(tmp_path, flag):
    folder = tmp_path / "plugins" / "panel"
    folder.mkdir(parents=True)
    manifest = {"id": "panel", "name": "Panel", "main": "main.py"}
    if flag is not None:
        manifest["headless"] = flag
    (folder / "plugin.json").write_text(json.dumps(manifest),
                                        encoding="utf-8")
    (folder / "main.py").write_text(PLUGIN_SRC, encoding="utf-8")

    class Host:
        HEADLESS = True

    mgr = PluginManager(log=lambda *a: None, host=Host(),
                        plugins_dir=tmp_path / "plugins")
    mgr.discover()
    mgr.load_enabled()
    return mgr.plugins["panel"]


def test_headless_missing_means_true(tmp_path):
    assert _headless_manager(tmp_path, None).loaded


def test_headless_false_is_skipped_in_terminal_mode(tmp_path):
    plugin = _headless_manager(tmp_path, False)
    assert not plugin.loaded and plugin.enabled
    assert "terminal mode" in plugin.error


def test_headless_false_still_loads_in_the_window(tmp_path):
    folder = tmp_path / "plugins" / "panel"
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(json.dumps(
        {"id": "panel", "name": "Panel", "main": "main.py",
         "headless": False}), encoding="utf-8")
    (folder / "main.py").write_text(PLUGIN_SRC, encoding="utf-8")
    mgr = PluginManager(log=lambda *a: None, plugins_dir=tmp_path / "plugins")
    mgr.discover()
    mgr.load_enabled()
    assert mgr.plugins["panel"].loaded


def test_headless_string_false_counts(tmp_path):
    assert not _headless_manager(tmp_path, "false").loaded


# ------------------------------------- no profile active: pick a profile
def test_add_plugins_keeps_the_rest(tmp_path):
    profiles.save_profile("G", {"aio_active": True}, tmp_path,
                          plugins={"afk": True})
    profiles.save_plugin_settings("G", {"afk": {"options": {"a": 1}}},
                                  tmp_path)
    profiles.add_plugins("G", {"leash": False},
                         {"leash": {"options": {"b": 2}}}, tmp_path)
    assert profiles.read_profile("G", tmp_path) == {
        "aio_active": True, "plugin_afk": True, "plugin_leash": False}
    assert profiles.read_plugin_settings("G", tmp_path) == {
        "afk": {"options": {"a": 1}}, "leash": {"options": {"b": 2}}}


def test_plugins_in_no_profile(tmp_path):
    profiles.save_profile("A", {}, tmp_path, plugins={"afk": True})
    profiles.save_profile("B", {}, tmp_path, plugins={"clock": False})
    assert profiles.plugins_in_no_profile(
        ["afk", "clock", "leash", "gg"], tmp_path, asked=["gg"]) == ["leash"]
