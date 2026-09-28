"""
tests/test_media_only_playing.py - "Hide media while paused" (v1.6.1).

Community wish: a paused song should not sit in the chatbox for hours.
With the option on, _on_media_result treats a paused/stopped player as
"nothing playing" - so the line disappears or the idle symbol shows.
Off (default) keeps the old behaviour: a paused song stays visible.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from ui.pages.apps_page import AppsPageMixin

TRACK = {"artist": "Nightdrive", "title": "Midnight Signal",
         "position": 78.0, "length": 227.0, "player": "spotify"}


class FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


def make_page(only_playing):
    page = AppsPageMixin.__new__(AppsPageMixin)
    page.cfg = {"media_only_playing": only_playing,
                "media_show_lyrics": False}
    page.media_info = None
    page.media_status_lbl = FakeLabel()
    page.log = lambda *_a, **_k: None
    page.update_preview = lambda: None
    page._warm_done = lambda *_a: None
    return page


def test_paused_song_hidden_when_on():
    page = make_page(True)
    page._on_media_result(dict(TRACK, playing=False))
    assert page.media_info is None
    assert "hidden" in page.media_status_lbl.text


def test_playing_song_still_shown_when_on():
    page = make_page(True)
    page._on_media_result(dict(TRACK, playing=True))
    assert page.media_info["title"] == "Midnight Signal"


def test_paused_song_kept_when_off():
    page = make_page(False)
    page._on_media_result(dict(TRACK, playing=False))
    assert page.media_info["title"] == "Midnight Signal"
    assert "paused" in page.media_status_lbl.text
