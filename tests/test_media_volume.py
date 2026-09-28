"""
tests/test_media_volume.py - player volume in the chatbox (v1.6.2).

{volume} / {volume_db} always exist when the player reports a volume;
the "Player volume" checkbox only decides whether the normal song line
gets "| 🔊 65%" appended. No volume reported (browser players, Windows)
means empty - never "0%".
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from core.mediafetch import fmt_volume, fmt_volume_db
from test_media_custom_mode import make_page


@pytest.mark.parametrize("vol, pct, db", [
    (0.65, "65%", "-3.7 dB"),
    (1.0, "100%", "0.0 dB"),
    (0.5, "50%", "-6.0 dB"),
    (1.25, "125%", "1.9 dB"),          # VLC goes above 100 %
    (0.0, "0%", "-∞ dB"),         # muted
    (None, None, None),                # not reported
])
def test_formatting(vol, pct, db):
    assert fmt_volume(vol) == pct
    assert fmt_volume_db(vol) == db


def test_placeholders_filled_regardless_of_checkbox():
    page = make_page(media_show_volume=False)
    page.media_info["volume"] = 0.65
    vals = page._media_values(page.media_info)
    assert vals["volume"] == "65%"
    assert vals["volume_db"] == "-3.7 dB"


def test_placeholders_empty_when_not_reported():
    page = make_page()
    page.media_info.pop("volume", None)
    vals = page._media_values(page.media_info)
    assert vals["volume"] is None and vals["volume_db"] is None


def _normal_line(**cfg):
    page = make_page(media_custom=False, media_show_bar=False,
                     media_show_time=False, media_time_pos=0, **cfg)
    page.media_info["volume"] = 0.65
    return page.build_media_lines()


def test_checkbox_appends_to_song_line():
    assert _normal_line(media_show_volume=True)[0].endswith(
        "| \U0001F50A 65%")


def test_checkbox_off_leaves_line_alone():
    assert "\U0001F50A" not in _normal_line(media_show_volume=False)[0]
