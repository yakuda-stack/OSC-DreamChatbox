"""tests/test_profiles.py - core/profiles.py (named setups)."""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json

import pytest

from core import profiles


def test_clean_name_drops_path_characters():
    assert profiles.clean_name("  Gaming / Music ") == "Gaming  Music"
    assert profiles.clean_name("../..") == ""
    assert profiles.clean_name("a" * 100) == "a" * profiles.NAME_MAX
    assert profiles.clean_name(None) == ""


def test_save_list_read_roundtrip(tmp_path):
    cfg = {"aio_active": True, "osc_port": 9123, "theme": "dark",
           profiles.ACTIVE_KEY: "x"}
    name = profiles.save_profile("Translation", cfg, tmp_path)
    assert name == "Translation"
    assert profiles.list_profiles(tmp_path) == ["Translation"]
    stored = profiles.read_profile("Translation", tmp_path)
    # the setup travels, the app-wide keys do not
    assert stored == {"aio_active": True}


def test_list_is_sorted_case_insensitive(tmp_path):
    for n in ("b", "A", "c"):
        profiles.save_profile(n, {}, tmp_path)
    assert profiles.list_profiles(tmp_path) == ["A", "b", "c"]


def test_list_missing_folder(tmp_path):
    assert profiles.list_profiles(tmp_path / "nope") == []


def test_merge_keeps_app_wide_keys_of_running_config():
    current = {"osc_port": 9000, "theme": "neon", "aio_active": False,
               "debug": True}
    stored = {"aio_active": True, "osc_port": 1111}
    merged = profiles.merge_for_load(current, stored)
    assert merged["aio_active"] is True
    assert merged["osc_port"] == 9000
    assert merged["theme"] == "neon"
    assert merged["debug"] is True


def test_empty_name_refused(tmp_path):
    with pytest.raises(ValueError):
        profiles.save_profile("  ", {}, tmp_path)


def test_rename_and_delete(tmp_path):
    profiles.save_profile("Old", {"a": 1}, tmp_path)
    assert profiles.rename_profile("Old", "New", tmp_path) == "New"
    assert profiles.list_profiles(tmp_path) == ["New"]
    profiles.save_profile("Other", {}, tmp_path)
    with pytest.raises(ValueError):
        profiles.rename_profile("New", "Other", tmp_path)
    profiles.delete_profile("New", tmp_path)
    profiles.delete_profile("New", tmp_path)       # missing is fine
    assert profiles.list_profiles(tmp_path) == ["Other"]


def test_read_rejects_non_object(tmp_path):
    (tmp_path / "Bad.json").write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(ValueError):
        profiles.read_profile("Bad", tmp_path)


def test_conversation_template_renders():
    from core.textutils import apply_template
    from ui.pages.twoway_page import (CONVERSATION_SEPARATOR,
                                      CONVERSATION_TEMPLATE)
    out = apply_template(CONVERSATION_TEMPLATE, {
        "stt_output": "Hola amigo", "twoway_input": "¿Qué tal?",
        "twoway_output": "How are you?"})
    assert out.split("\n") == ["Hola amigo", CONVERSATION_SEPARATOR,
                               "¿Qué tal?", "How are you?"]


def test_find_profile_ignores_case(tmp_path):
    profiles.save_profile("Gaming", {}, tmp_path)
    assert profiles.find_profile("gaming", tmp_path) == "Gaming"
    assert profiles.find_profile(" GAMING ", tmp_path) == "Gaming"
    assert profiles.find_profile("Music", tmp_path) == ""
    assert profiles.find_profile("", tmp_path) == ""


@pytest.mark.parametrize("argv, expected", [
    ([], None),
    (["--headless"], None),
    (["--profile=my profile"], "my profile"),
    (["--headless", "--profile", "my profile"], "my profile"),
    (["--profile"], ""),
    (["--profile", "--headless"], ""),
    (["--profile="], ""),
])
def test_profile_from_argv(argv, expected):
    assert profiles.profile_from_argv(argv) == expected
