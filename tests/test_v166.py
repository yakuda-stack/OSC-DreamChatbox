"""
tests/test_v166.py - the new pieces of v1.6.6 that work without a window:
message history, AIO scroll, Custom Box animation, in-app update asset
pick, parameter log diff and the AI setup check.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from core import ai_translator as ai
from core import selfupdate
from core.aioscroll import ScrollTransition
from core.boxanim import (ANIM_BLINK, ANIM_LOAD, ANIM_OFF, ANIM_ROTATE,
                          LOAD_EMPTY, LOAD_FULL, ROTATE_MARK, normalize_anim)
from core.boxstyle import BOX_TEMPLATES, cells, render_pair
from core.inputhistory import InputHistory


# ---- message history ----------------------------------------------------
def test_history_up_down_restores_draft():
    h = InputHistory()
    for t in ("one", "two", "two", "  "):
        h.push(t)
    assert h.items == ["one", "two"]          # repeat + empty skipped
    assert h.up("draft") == "two"
    assert h.up() == "one"
    assert h.up() is None                     # oldest reached
    assert h.down() == "two"
    assert h.down() == "draft"
    assert h.down() is None                   # not browsing any more


def test_history_limit_and_reset():
    h = InputHistory(limit=3)
    for i in range(5):
        h.push(str(i))
    assert h.items == ["2", "3", "4"]
    h.up()
    h.reset()
    assert h.up() == "4"


def test_history_empty():
    assert InputHistory().up("x") is None


# ---- AIO scroll -----------------------------------------------------------
def test_scroll_crawls_line_by_line():
    s = ScrollTransition()
    assert s.start(["A1", "A2", "A3"])
    new = ["B1", "B2"]
    frames = [s.window(new)]
    while s.tick():
        frames.append(s.window(new))
    frames.append(s.window(new))
    assert frames == [["A1", "A2", "A3"], ["A2", "A3", "B1"],
                      ["A3", "B1", "B2"], ["B1", "B2"]]
    assert not s.active


def test_scroll_nothing_on_screen_no_crawl():
    s = ScrollTransition()
    assert not s.start([])
    assert s.window(["x"]) == ["x"]


def test_scroll_same_text_stops():
    s = ScrollTransition()
    s.start(["a", "b"])
    assert s.window(["a", "b"]) == ["a", "b"]
    assert not s.active


def test_scroll_max_lines():
    s = ScrollTransition()
    s.start([str(i) for i in range(12)])
    assert len(s.window(["n"])) == 9


# ---- Custom Box animation -----------------------------------------------
TPL = BOX_TEMPLATES[0]


def test_anim_off_is_plain():
    assert render_pair(TPL, 6, 4, "12:00", "", anim=ANIM_OFF, frame=3) == \
        render_pair(TPL, 6, 4, "12:00", "")


@pytest.mark.parametrize("mode", [ANIM_BLINK, ANIM_LOAD, ANIM_ROTATE])
def test_anim_keeps_width(mode):
    plain = render_pair(TPL, 6, 4, "12:00", "68 %")
    for frame in range(10):
        top, bottom = render_pair(TPL, 6, 4, "12:00", "68 %",
                                  anim=mode, frame=frame)
        assert cells(top) == cells(plain[0])
        assert cells(bottom) == cells(plain[1])
        assert "12:00" in top and "68 %" in bottom


def test_anim_blink_alternates():
    a = render_pair(TPL, 4, 4, anim=ANIM_BLINK, frame=0)
    b = render_pair(TPL, 4, 4, anim=ANIM_BLINK, frame=1)
    assert a != b and "─" not in b[0]


def test_anim_load_fills_up():
    first = render_pair(TPL, 6, 6, anim=ANIM_LOAD, frame=0)[0]
    full = render_pair(TPL, 6, 6, anim=ANIM_LOAD, frame=6)[0]
    assert LOAD_FULL not in first and LOAD_EMPTY not in full


def test_anim_rotate_one_mark_per_line():
    top, bottom = render_pair(TPL, 6, 6, anim=ANIM_ROTATE, frame=2)
    assert top.count(ROTATE_MARK) == 1 and bottom.count(ROTATE_MARK) == 1


def test_normalize_anim():
    assert normalize_anim("rotate") == ANIM_ROTATE
    assert normalize_anim("nope") == ANIM_OFF


# ---- in-app update (Windows) -----------------------------------------------
def test_find_setup_asset():
    rel = {"assets": [
        {"name": "OSC-DreamChatbox-1.6.6.AppImage",
         "browser_download_url": "https://x/a.AppImage", "size": 1},
        {"name": "OSC-DreamChatbox-1.6.6-portable.exe",
         "browser_download_url": "https://x/p.exe", "size": 2},
        {"name": "OSC-DreamChatbox-1.6.6-setup.exe",
         "browser_download_url": "https://x/s.exe", "size": 3},
    ]}
    assert selfupdate.find_setup_asset(rel) == (
        "OSC-DreamChatbox-1.6.6-setup.exe", "https://x/s.exe", 3)
    assert selfupdate.find_setup_asset({"assets": []}) is None
    assert selfupdate.find_setup_asset({}) is None


def test_setup_asset_needs_https():
    rel = {"assets": [{"name": "OSC-DreamChatbox-1-setup.exe",
                       "browser_download_url": "http://x/s.exe"}]}
    assert selfupdate.find_setup_asset(rel) is None


def test_download_refuses_other_files():
    with pytest.raises(ValueError):
        selfupdate.download("https://x/evil.exe", "evil.exe")


def test_not_frozen_no_install_button():
    assert selfupdate.is_installed_windows_build() is False


# ---- parameter log ----------------------------------------------------------
def test_param_diff():
    pytest.importorskip("PyQt6")
    from ui.osc_param_log import diff_snapshots
    old = {"a": 1, "b": True}
    new = {"a": 1, "b": False, "c": 0.5}
    assert diff_snapshots(old, new) == [("b", False), ("c", 0.5)]


# ---- AI setup check ---------------------------------------------------------
def test_ai_custom_configured(monkeypatch):
    ai.use_config({"stt_ai_custom_cmd": ""})
    assert not ai.configured(ai.METHOD_AI_CUSTOM)
    ai.use_config({"stt_ai_custom_cmd": "ollama run {model} {prompt}"})
    assert ai.configured(ai.METHOD_AI_CUSTOM)
    ai.use_config({})


def test_ai_install_steps_npm(monkeypatch):
    monkeypatch.setattr(ai.shutil, "which",
                        lambda n: "/usr/bin/npm" if n == "npm" else None)
    steps = ai.install_steps(ai.METHOD_GEMINI)
    assert len(steps) == 1
    argv = steps[0]()
    assert argv[:3] == ["/usr/bin/npm", "install", "-g"]
    assert "@google/gemini-cli" in argv and "--prefix" in argv


def test_ai_install_steps_npm_missing(monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda n: None)
    steps = ai.install_steps(ai.METHOD_CHATGPT)
    assert len(steps) == 2           # npm first, then the package


def test_pkexec_argv(monkeypatch):
    monkeypatch.setattr(ai, "IS_WINDOWS", False)
    monkeypatch.setattr(ai.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(ai.Path, "exists", lambda self: False)
    assert ai.pkexec_install_argv("npm", ids=["cachyos", "arch"]) == [
        "pkexec", "/usr/bin/pacman", "-S", "--needed", "--noconfirm", "npm"]
    assert ai.pkexec_install_argv("npm", ids=["fedora"])[-1] == "nodejs-npm"
