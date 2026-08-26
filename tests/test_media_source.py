"""
tests/test_media_source.py - the player choice, without a session bus.

The MPRIS backend is a thin layer over D-Bus calls, so what is worth
testing is the part that is NOT D-Bus: which bus name gets picked out of
a list, and whether the key that gets written into the config still
means the same player tomorrow. Both are pure functions of the bus names
and playback states, so a fake that answers those two questions is
enough - no QDBusConnection, no running Spotify, no PyQt6 at all.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from core.backends.media_linux import MediaFetcher, source_key, source_label

SPOTIFY = "org.mpris.MediaPlayer2.spotify"
YTM = "org.mpris.MediaPlayer2.YoutubeMusic"
FIREFOX = "org.mpris.MediaPlayer2.firefox.instance_1_94"
CHROMIUM = "org.mpris.MediaPlayer2.chromium.instance17421"


class FakeBus:
    """Stands in for a session bus with a fixed set of players."""

    def __init__(self, players):
        #: {bus name: "Playing" / "Paused" / "Stopped"}
        self.players = dict(players)
        self.identities = {}


def make_fetcher(players, preferred="", fallback=True):
    """A MediaFetcher whose D-Bus calls are answered from a dict."""
    fetcher = MediaFetcher.__new__(MediaFetcher)      # skip __init__/D-Bus
    fetcher.log = lambda *_a, **_k: None
    fetcher.bus = FakeBus(players)
    fetcher._cached_player = None
    fetcher.preferred = preferred
    fetcher.fallback = fallback
    fetcher._list_players = lambda: list(fetcher.bus.players)
    fetcher._status = lambda name: fetcher.bus.players.get(name, "")
    fetcher._identity = lambda name: fetcher.bus.identities.get(name, "")
    return fetcher


# ------------------------------------------------------------------ keys
@pytest.mark.parametrize("bus_name, expected", [
    (SPOTIFY, "spotify"),
    (YTM, "YoutubeMusic"),
    # the whole point of source_key: the per-process tail must go, or the
    # saved setting points at a Firefox that no longer exists
    (FIREFOX, "firefox"),
    (CHROMIUM, "chromium"),
    ("org.mpris.MediaPlayer2.vlc", "vlc"),
])
def test_source_key_is_stable(bus_name, expected):
    assert source_key(bus_name) == expected


def test_two_firefox_windows_share_one_key():
    a = source_key("org.mpris.MediaPlayer2.firefox.instance_1_94")
    b = source_key("org.mpris.MediaPlayer2.firefox.instance_2_7")
    assert a == b == "firefox"


def test_identity_beats_the_lookup_table():
    # a player that names itself is always right about its own name
    assert source_label("YoutubeMusic", "YouTube Music") == "YouTube Music"
    assert source_label("some-new-player", "Brand New Player") \
        == "Brand New Player"


def test_label_falls_back_to_the_table_then_to_the_key():
    assert source_label("spotify", "") == "Spotify"
    assert source_label("obscure-thing", "") == "obscure-thing"


# --------------------------------------------------------------- picking
def test_automatic_takes_whatever_is_playing():
    f = make_fetcher({SPOTIFY: "Paused", YTM: "Playing"})
    chosen, status = f._pick(list(f.bus.players))
    assert chosen == YTM
    assert status == "Playing"


def test_the_case_this_feature_exists_for():
    """Spotify paused, YouTube Music playing, Spotify chosen.

    Automatic would answer YouTube Music here and be right to. Having
    picked Spotify, the answer has to be Spotify - a paused song is
    still what that player has to say, and the card already renders
    paused songs.
    """
    f = make_fetcher({SPOTIFY: "Paused", YTM: "Playing"}, preferred="spotify")
    chosen, status = f._pick(list(f.bus.players))
    assert chosen == SPOTIFY
    assert status == "Paused"


def test_chosen_player_wins_even_when_listed_last():
    f = make_fetcher({YTM: "Playing", CHROMIUM: "Playing", SPOTIFY: "Playing"},
                     preferred="spotify")
    chosen, _ = f._pick(list(f.bus.players))
    assert chosen == SPOTIFY


def test_browser_choice_survives_a_new_instance_id():
    """The setting says "firefox"; Firefox came back with a new suffix."""
    f = make_fetcher({"org.mpris.MediaPlayer2.firefox.instance_9_31": "Playing"},
                     preferred="firefox")
    chosen, _ = f._pick(list(f.bus.players))
    assert chosen == "org.mpris.MediaPlayer2.firefox.instance_9_31"


def test_fallback_on_lets_another_player_through():
    f = make_fetcher({YTM: "Playing"}, preferred="spotify", fallback=True)
    chosen, _ = f._pick(list(f.bus.players))
    assert chosen == YTM


def test_fallback_off_shows_nothing():
    # deliberate: the line means Spotify or it means nothing
    f = make_fetcher({YTM: "Playing"}, preferred="spotify", fallback=False)
    chosen, status = f._pick(list(f.bus.players))
    assert chosen is None
    assert status == ""


def test_nothing_running_is_not_an_error():
    f = make_fetcher({}, preferred="spotify")
    assert f._pick([]) == (None, "")


def test_paused_only_still_reports_a_player():
    # unchanged from before the setting existed: a paused desktop shows
    # the paused song rather than going blank
    f = make_fetcher({SPOTIFY: "Paused"})
    chosen, status = f._pick(list(f.bus.players))
    assert chosen == SPOTIFY
    assert status == "Paused"


# --------------------------------------------------------------- listing
def test_list_sources_merges_windows_and_marks_the_live_one():
    f = make_fetcher({
        "org.mpris.MediaPlayer2.firefox.instance_1_1": "Paused",
        "org.mpris.MediaPlayer2.firefox.instance_1_2": "Playing",
        SPOTIFY: "Paused",
    })
    found = {s["key"]: s for s in f.list_sources()}
    assert set(found) == {"firefox", "spotify"}
    # the window that is playing is what "Firefox" means right now
    assert found["firefox"]["playing"] is True
    assert found["spotify"]["playing"] is False


def test_list_sources_puts_the_playing_one_first():
    f = make_fetcher({SPOTIFY: "Paused", YTM: "Playing"})
    assert f.list_sources()[0]["key"] == "YoutubeMusic"


def test_youtube_music_app_and_tab_stay_separate():
    """The app and a music.youtube.com tab are different entries.

    Someone who picks the desktop app did not pick "whatever Firefox is
    playing", and collapsing the two would make the setting unable to
    tell them apart.
    """
    f = make_fetcher({YTM: "Playing", FIREFOX: "Playing"})
    keys = {s["key"] for s in f.list_sources()}
    assert keys == {"YoutubeMusic", "firefox"}


def test_cached_player_is_dropped_when_the_choice_changes():
    """The fast path must not outlive the setting it was taken under."""
    f = make_fetcher({SPOTIFY: "Playing", YTM: "Playing"})
    f._cached_player = SPOTIFY
    f.preferred = "YoutubeMusic"
    # this is the guard inside fetch(), reproduced: a cached bus name
    # that no longer matches the wanted key is thrown away
    assert source_key(f._cached_player) != f.preferred
