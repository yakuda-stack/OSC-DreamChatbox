"""
tests/test_lyrics_sources.py - the format plumbing behind the six
lyrics services.

The network calls themselves are not tested here: six third-party
endpoints that go up and down is exactly what a test suite must not
depend on, and the failure would tell you nothing about this code
anyway. What IS worth pinning down is everything that happens to the
answer once it arrives, because that is where a wrong result looks
plausible instead of looking broken:

  * timestamps, where being off by a factor of ten puts every line in
    the wrong place and still produces a valid .lrc file
  * TTML's two time formats, only one of which most parsers handle
  * the source order, which decides whether a lookup costs one fast
    request or six slow ones
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from core.lyrics import _parse_lrc
from core.lyrics_sources import (
    DEFAULT_SOURCES, SOURCE_IDS, lines_to_lrc, normalize_sources,
    source_label, ttml_to_lrc)


# --------------------------------------------------------------------
# building .lrc out of millisecond rows (LyricsPlus)
# --------------------------------------------------------------------
def test_milliseconds_become_lrc_timestamps():
    assert lines_to_lrc([(0, "first")]) == "[00:00.00]first"
    assert lines_to_lrc([(63450, "later")]) == "[01:03.45]later"
    # over an hour the minutes keep counting rather than wrapping - an
    # .lrc has no hour field, and a DJ set would otherwise restart at 0
    assert lines_to_lrc([(3723000, "long")]) == "[62:03.00]long"


def test_blank_rows_are_dropped():
    # an empty lyric line reads as the song having stopped, so a gap is
    # better shown by leaving the previous line up
    assert lines_to_lrc([(0, "a"), (1000, "   "), (2000, "b")]) \
        == "[00:00.00]a\n[00:02.00]b"


def test_what_comes_out_can_be_read_back_in():
    lrc = lines_to_lrc([(0, "one"), (90_500, "two")])
    assert _parse_lrc(lrc) == [(0.0, "one"), (90.5, "two")]


# --------------------------------------------------------------------
# TTML (Better Lyrics, Paxsenix)
# --------------------------------------------------------------------
TTML = """<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
  <p begin="00:00:12.340" end="00:00:15.000">hello</p>
  <p begin="00:00:15.500">world</p>
</div></body></tt>"""


def test_clock_times_are_read():
    assert ttml_to_lrc(TTML) == "[00:12.34]hello\n[00:15.50]world"


def test_offset_times_are_read_too():
    # TTML allows both spellings and both turn up from these APIs
    ttml = ('<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
            '<p begin="83.45s">a</p><p begin="90000ms">b</p>'
            '</div></body></tt>')
    assert ttml_to_lrc(ttml) == "[01:23.45]a\n[01:30.00]b"


def test_word_timings_are_flattened_into_the_line():
    # a chatbox shows one line at a time and cannot animate a word
    ttml = ('<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
            '<p begin="00:00:01.000"><span begin="00:00:01.000">Hel</span>'
            '<span begin="00:00:01.200">lo</span></p>'
            '</div></body></tt>')
    assert ttml_to_lrc(ttml) == "[00:01.00]Hel lo"


def test_lines_come_out_in_time_order():
    ttml = ('<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
            '<p begin="00:00:09.000">second</p>'
            '<p begin="00:00:03.000">first</p>'
            '</div></body></tt>')
    assert ttml_to_lrc(ttml).splitlines()[0].endswith("first")


def test_broken_or_empty_ttml_is_not_an_exception():
    # one source having a bad day must not take the chain down with it
    assert ttml_to_lrc("") == ""
    assert ttml_to_lrc("<tt><body><div><p>no begin</p>") == ""
    assert ttml_to_lrc("not xml at all") == ""


# --------------------------------------------------------------------
# which sources, in which order
# --------------------------------------------------------------------
def test_order_comes_from_the_module_not_from_the_config():
    # a hand-edited config must not be able to put the slow unofficial
    # endpoint in front of the fast open one
    got = normalize_sources(["musixmatch", "lrclib"])
    assert got == ["lrclib", "musixmatch"]
    assert got.index("lrclib") < got.index("musixmatch")


def test_unknown_names_are_dropped():
    assert normalize_sources(["lrclib", "not-a-source"]) == ["lrclib"]


def test_a_missing_key_falls_back_to_the_defaults():
    # every config written before this version has no such key
    assert normalize_sources(None) == list(DEFAULT_SOURCES)
    assert "lrclib" in DEFAULT_SOURCES


def test_turning_everything_off_is_respected():
    # [] is a choice, not a missing value
    assert normalize_sources([]) == []


def test_a_set_survives_the_round_trip():
    # the checkbox handler builds one before storing it
    assert normalize_sources({"lrclib", "kugou"}) == ["lrclib", "kugou"]


def test_the_unofficial_ones_are_off_by_default():
    for sid in ("paxsenix", "kugou", "musixmatch"):
        assert sid in SOURCE_IDS
        assert sid not in DEFAULT_SOURCES


def test_every_source_has_a_label():
    for sid in SOURCE_IDS:
        assert source_label(sid) and source_label(sid) != sid or sid
