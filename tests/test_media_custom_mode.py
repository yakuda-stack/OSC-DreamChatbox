"""
tests/test_media_custom_mode.py - the settings a custom string still uses.

The bug this guards against shipped in v1.4.4 and was fixed in v1.4.5.
Turning on the MediaPlay custom string greyed out the whole Content and
Playback section - artist, song title, max length, the time format, the
songbar style and size. The reasoning was that a custom string replaces
that layout, which is half true: it replaces where things GO, not which
values EXIST. Every one of those greyed controls still fed the custom
string, so the card locked people out of settings that were still doing
their job.

There is no way to check "can the user click this" without a running
app, so this tests the half that matters and is testable: that each of
those settings still changes what a custom string renders. If any of
them ever stops mattering in custom mode, greying it would become
correct and the corresponding test here should be the thing that says
so.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from core.textstyle import STYLE_NORMAL
from ui.mainwindow import MainWindow
from ui.pages.apps_page import AppsPageMixin

TRACK = {
    "artist": "Nightdrive",
    "title": "Midnight Signal (Extended Mix)",
    "position": 78.0,
    "length": 227.0,
    "playing": True,
    "player": "spotify",
}


class FakeLyrics:
    def current_line(self, *_a):
        return "and the city lights go by"


def make_page(**overrides):
    """A page with a config, in custom-string mode."""
    page = AppsPageMixin.__new__(AppsPageMixin)
    page.cfg = {
        "media_custom": True,
        "media_custom_template": "{artist} {title} {time} {bar} {lyrics}",
        "media_show_artist": True,
        "media_show_title": True,
        "media_show_time": True,
        "media_show_bar": True,
        "media_show_lyrics": False,
        "media_title_max": 24,
        "media_time_seconds": True,
        "media_time_style": STYLE_NORMAL,
        "media_bar_style": 0,
        "media_bar_size": 100,
        "media_bar_custom": None,
        "media_icon": False,
        "media_idle": False,
        "media_idle_text": "",
        "media_lyrics_prefix_on": True,
        "media_lyrics_prefix": "\u266a",
    }
    page.cfg.update(overrides)
    page.lyrics = FakeLyrics()
    page.media_info = dict(TRACK)
    # _fmt_media_time lives on MainWindow rather than the mixin, and it
    # is the whole of the "With seconds" and digit-style behaviour. Bound
    # off the real class rather than reimplemented here - a copy would
    # keep passing after the original changed, which is the one thing a
    # regression test must not do.
    page._fmt_media_time = MainWindow._fmt_media_time.__get__(page)
    return page


def values(page):
    return page._media_values(page.media_info)


# --------------------------------------------------------------------
# Content: the checkboxes still gate their placeholders
# --------------------------------------------------------------------
@pytest.mark.parametrize("key, placeholder", [
    ("media_show_artist", "artist"),
    ("media_show_title", "title"),
    ("media_show_time", "time"),
    ("media_show_bar", "bar"),
    ("media_show_lyrics", "lyrics"),
])
def test_checkbox_still_gates_its_placeholder(key, placeholder):
    """Ticked fills the placeholder, unticked empties it - in custom
    mode, which is exactly where the card used to be unclickable."""
    on = values(make_page(**{key: True}))[placeholder]
    off = values(make_page(**{key: False}))[placeholder]
    assert on, f"{placeholder} empty while {key} is on"
    assert off is None, f"{placeholder} survived {key} being off"


# --------------------------------------------------------------------
# Content: the Max length slider
# --------------------------------------------------------------------
def test_max_length_still_truncates():
    assert values(make_page(media_title_max=11))["title"] == "Midnight Si"
    assert values(make_page(media_title_max=8))["title"] == "Midnight"


def test_max_length_does_not_pad_a_short_title():
    page = make_page(media_title_max=64)
    assert page._media_values(page.media_info)["title"] == TRACK["title"]


# --------------------------------------------------------------------
# Playback: the time format
# --------------------------------------------------------------------
def test_seconds_toggle_still_picks_the_time_format():
    with_secs = values(make_page(media_time_seconds=True))["time"]
    without = values(make_page(media_time_seconds=False))["time"]
    assert with_secs == "1:18/3:47"
    assert without != with_secs


@pytest.mark.parametrize("field", ["position", "length",
                                   "time_status", "time_end"])
def test_the_bare_time_placeholders_ignore_the_time_checkbox(field):
    """{time} is gated by the Time checkbox; the four bare ones are not,
    which is what makes a custom string able to place the numbers
    separately."""
    assert values(make_page(media_show_time=False))[field]


# --------------------------------------------------------------------
# Playback: the songbar
# --------------------------------------------------------------------
def test_songbar_style_still_changes_the_bar():
    a = values(make_page(media_bar_style=0))["bar"]
    b = values(make_page(media_bar_style=2))["bar"]
    assert a and b and a != b


def test_songbar_size_still_changes_the_bar_length():
    long_bar = values(make_page(media_bar_size=100))["bar"]
    short_bar = values(make_page(media_bar_size=30))["bar"]
    assert len(short_bar) < len(long_bar)


def test_songbar_fills_proportionally():
    """A third of the way in is neither an empty bar nor a full one -
    the property the preview's demo track was chosen for."""
    start = make_page()
    start.media_info = dict(TRACK, position=0.0)
    end = make_page()
    end.media_info = dict(TRACK, position=227.0)
    assert values(start)["bar"] != values(end)["bar"]


# --------------------------------------------------------------------
# the whole line
# --------------------------------------------------------------------
def test_settings_reach_the_rendered_custom_line():
    """The end-to-end version: two settings changed, both visible in the
    text that would go to VRChat."""
    page = make_page(media_title_max=11, media_time_seconds=True,
                     media_custom_template="{title} | {time}")
    assert page.build_media_lines() == ["Midnight Si | 1:18/3:47"]


def test_an_unticked_part_collapses_its_separator():
    page = make_page(media_show_title=False,
                     media_custom_template="{title} | {time}")
    assert page.build_media_lines() == ["1:18/3:47"]
