"""
tests/test_gpu2.py - the second GPU (v1.5.1).

Three things are worth pinning down, and all three are testable without
a second graphics card in the machine:

1. nvidia-smi bookkeeping. The reader used to keep only the line that
   started with "0," and throw the rest away, so a second NVIDIA card was
   unreadable even though its values were already in the pipe. Now every
   index is kept, and _parse_nvsmi() refuses a line from another card -
   which is the part that stops GPU 2 from quietly showing GPU 1's load.

2. The placeholders. {gpu2_*} and {vram2_*} have to EXIST even with the
   feature switched off, because a string that carries them must collapse
   them like any other empty value instead of printing a card name.

3. The generated layout. "Own line" and "All in one line" are one
   setting, and the difference between them is exactly one line break.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import time

import pytest

from core.backends.hardware_linux import (
    _NvidiaSmiLoop, _nvsmi_index, _parse_nvsmi)
from core.constants import GPU2_MODE_INLINE, GPU2_MODE_LINE
from core.textstyle import STYLE_NORMAL
from core.textutils import canonical_placeholder
from ui.pages.apps_page import AppsPageMixin

CARD0 = "0, 42, 61, 4096, 16384, 180.0"
CARD1 = "1, 7, 44, 1024, 8192, 35.0"


# ====================================================================
# 1. nvidia-smi: one line per card
# ====================================================================
def test_index_is_read_from_the_line():
    assert _nvsmi_index(CARD1) == 1
    assert _nvsmi_index("") is None
    assert _nvsmi_index("no, numbers, here") is None


def test_parse_accepts_only_its_own_card():
    assert _parse_nvsmi(CARD1, 1)["usage"] == 7
    assert _parse_nvsmi(CARD1, 0) is None, "card 1's line answered for card 0"


def test_parse_reads_every_value():
    got = _parse_nvsmi(CARD0, 0)
    assert got["temp"] == 61
    assert got["power"] == 180.0
    assert got["vram_total"] == pytest.approx(16.0)
    assert got["vram_pct"] == pytest.approx(25.0)


def test_power_that_is_not_reported_costs_nothing_else():
    got = _parse_nvsmi("0, 42, 61, 4096, 16384, [N/A]", 0)
    assert got["power"] is None
    assert got["usage"] == 42


class _FakeProc:
    """Stands in for the nvidia-smi process: a fixed set of lines and
    then end of stream."""

    def __init__(self, lines):
        self.stdout = iter(f"{line}\n" for line in lines)

    def poll(self):
        return None


def test_the_reader_keeps_a_line_per_card():
    loop = _NvidiaSmiLoop(log_fn=lambda _m: None)
    proc = _FakeProc([CARD0, CARD1, "1, 9, 45, 1024, 8192, 36.0"])
    loop._proc = proc
    # without this the reader sees "nobody has asked for a value in 15
    # seconds", stops the process and drops what it read - the idle path
    # that keeps nvidia-smi from running while the Hardware card is off
    loop._last_ask = time.monotonic()
    loop._reader(proc)
    assert set(loop._lines) == {0, 1}
    assert loop._lines[0][0] == CARD0
    # the newest line of a card wins, the older one is not kept around
    assert loop._lines[1][0].startswith("1, 9,")


# ====================================================================
# 2. the placeholders
# ====================================================================
INFO = {
    "cpu_usage": 12.0, "cpu_temp": 55.0, "cpu_power": 40.0,
    "ram": {"used": 9.0, "total": 32.0, "pct": 28.0},
    "gpu": {"usage": 42.0, "temp": 61.0, "power": 180.0,
            "vram_used": 4.0, "vram_total": 16.0, "vram_pct": 25.0},
    "gpu2": {"usage": 7.0, "temp": 44.0, "power": 35.0,
             "vram_used": 1.0, "vram_total": 8.0, "vram_pct": 12.5},
}


class _FakeHw:
    gpu_name_auto = "RX 9070 XT"
    gpu2_name_auto = "RX 6600"
    cpu_name_auto = "Ryzen 7 9700X"


def make_page(**overrides):
    page = AppsPageMixin.__new__(AppsPageMixin)
    page.cfg = {
        "hw_flame": False,
        "hw_custom": False,
        "hw_custom_template": "",
        "hw_gpu_usage": True, "hw_gpu_temp": True, "hw_gpu_power": False,
        "hw_gpu_name": True, "hw_gpu_custom": False,
        "hw_gpu_custom_name": "", "hw_gpu_name_style": STYLE_NORMAL,
        "hw_vram_used": False, "hw_vram_pct": False,
        "hw_cpu_usage": False, "hw_cpu_temp": False, "hw_cpu_power": False,
        "hw_cpu_name": True, "hw_cpu_custom": False,
        "hw_cpu_custom_name": "", "hw_cpu_name_style": STYLE_NORMAL,
        "hw_ram_used": False, "hw_ram_pct": False, "hw_ram_type": "",
        "hw_gpu2": True, "hw_gpu2_mode": GPU2_MODE_LINE,
        "hw_gpu2_usage": True, "hw_gpu2_temp": True, "hw_gpu2_power": False,
        "hw_gpu2_name": True, "hw_gpu2_custom": False,
        "hw_gpu2_custom_name": "", "hw_gpu2_name_style": STYLE_NORMAL,
        "hw_gpu2_vram_used": False, "hw_gpu2_vram_pct": False,
    }
    page.cfg.update(overrides)
    page.hw = _FakeHw()
    page.hw_info = INFO
    return page


def values(page):
    return page._hw_values(page.hw_info)


GPU2_KEYS = ("gpu2_name", "gpu2_usage", "gpu2_temp", "gpu2_power",
             "vram2_usage", "vram2_pct")


def test_the_keys_exist_even_with_the_feature_off():
    vals = values(make_page(hw_gpu2=False))
    for key in GPU2_KEYS:
        assert key in vals, f"{key} missing - a string using it would print it"
        assert vals[key] is None, f"{key} filled while Second GPU is off"


def test_values_arrive_once_it_is_on():
    vals = values(make_page())
    assert vals["gpu2_name"] == "RX 6600"
    assert vals["gpu2_usage"] == "7%"
    assert vals["gpu2_temp"] == "44°C"


def test_the_first_card_is_untouched_by_the_second():
    vals = values(make_page())
    assert vals["gpu_usage"] == "42%"
    assert vals["gpu_name"] == "RX 9070 XT"


@pytest.mark.parametrize("key, placeholder", [
    ("hw_gpu2_usage", "gpu2_usage"),
    ("hw_gpu2_temp", "gpu2_temp"),
    ("hw_gpu2_power", "gpu2_power"),
    ("hw_gpu2_vram_pct", "vram2_pct"),
])
def test_every_checkbox_gates_its_own_placeholder(key, placeholder):
    on = values(make_page(**{key: True}))[placeholder]
    off = values(make_page(**{key: False}))[placeholder]
    assert on, f"{placeholder} empty while {key} is on"
    assert off is None, f"{placeholder} survived {key} being off"


def test_vram_numbers_need_their_own_tick():
    assert values(make_page(hw_gpu2_vram_used=True))["vram2_usage"] == "1/8GB"
    assert values(make_page())["vram2_usage"] is None


def test_a_custom_name_wins_over_the_detected_one():
    page = make_page(hw_gpu2_custom=True, hw_gpu2_custom_name="Zweitkarte")
    assert values(page)["gpu2_name"] == "Zweitkarte"


def test_name_off_says_gpu2():
    assert values(make_page(hw_gpu2_name=False))["gpu2_name"] == "GPU2"


def test_flame_applies_to_the_second_card_too():
    assert values(make_page(hw_flame=True))["gpu2_temp"] == "44\U0001F525"


def test_temp_icon_leaves_a_bare_number():
    page = make_page()
    vals = values(page)
    page._bare_temps(vals, INFO)
    assert vals["gpu2_temp"] == "44"
    assert vals["gpu_temp"] == "61"


@pytest.mark.parametrize("typed, canonical", [
    ("gpu_2_temp", "gpu2_temp"),
    ("gpu2_watt", "gpu2_power"),
    ("vram2", "vram2_usage"),
])
def test_the_spellings_people_type_fold_onto_one_name(typed, canonical):
    assert canonical_placeholder(typed) == canonical


# ====================================================================
# 3. the generated layout
# ====================================================================
def test_own_line_puts_the_second_card_under_the_first():
    lines = make_page().build_hw_lines()
    assert lines == ["RX 9070 XT: 42% 61°C", "RX 6600: 7% 44°C"]


def test_all_in_one_keeps_it_on_one_line():
    lines = make_page(hw_gpu2_mode=GPU2_MODE_INLINE).build_hw_lines()
    assert lines == ["RX 9070 XT: 42% 61°C | RX 6600: 7% 44°C"]


def test_no_second_line_while_the_feature_is_off():
    assert make_page(hw_gpu2=False).build_hw_lines() == \
        ["RX 9070 XT: 42% 61°C"]


def test_a_card_that_reports_nothing_adds_no_line():
    info = dict(INFO, gpu2=None)
    page = make_page()
    page.hw_info = info
    assert page.build_hw_lines() == ["RX 9070 XT: 42% 61°C"]


def test_every_value_of_the_second_card_unticked_adds_no_line():
    page = make_page(hw_gpu2_usage=False, hw_gpu2_temp=False,
                     hw_gpu2_power=False)
    assert page.build_hw_lines() == ["RX 9070 XT: 42% 61°C"]


def test_the_custom_string_places_the_second_card_itself():
    page = make_page(hw_custom=True,
                     hw_custom_template="{gpu_usage} / {gpu2_usage}")
    assert page.build_hw_lines() == ["42% / 7%"]
