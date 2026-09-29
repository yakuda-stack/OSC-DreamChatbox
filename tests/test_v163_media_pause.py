"""
tests/test_v163_media_pause.py - v1.6.3 community wishes.

* "Hide media while paused" in All in one: only the media parts go
  (default) or the whole All in one pauses.
* a line that is only about the song drops completely without a song -
  "🎵 {title} 🎵" no longer leaves "🎵 🎵" behind.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ui.pages.apps_page import AppsPageMixin


def page(**cfg):
    p = AppsPageMixin.__new__(AppsPageMixin)
    p.cfg = {"media_active": True, "media_only_playing": True,
             "media_pause_scope": "media"}
    p.cfg.update(cfg)
    p.media_info = None
    return p


@pytest.mark.parametrize("line, expected", [
    ("\U0001F3B5 {title} \U0001F3B5", True),
    ("{artist} : {title} | {time}", True),
    ("{icon_sound} {song}", True),          # alias + decoration
    ("Status: {text} | {title}", False),    # mixed - keep the status
    ("{cpu_usage}", False),
    ("just text", False),                   # no placeholder at all
    ("{icon_sound}", False),                # decoration only, no song value
])
def test_line_is_media_only(line, expected):
    assert page()._line_is_media_only(line) is expected


def test_whole_aio_pauses_only_when_chosen():
    assert page(media_pause_scope="aio").media_pauses_aio() is True
    assert page(media_pause_scope="media").media_pauses_aio() is False


def test_whole_aio_runs_while_playing():
    p = page(media_pause_scope="aio")
    p.media_info = {"title": "x", "playing": True}
    assert p.media_pauses_aio() is False


def test_whole_aio_needs_the_hide_option():
    assert page(media_pause_scope="aio",
                media_only_playing=False).media_pauses_aio() is False
