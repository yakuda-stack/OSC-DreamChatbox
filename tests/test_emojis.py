"""
tests/test_emojis.py - the icon palette, its costs and its search.

core/emojis.py is pure data plus three small functions, so all of it is
testable without PyQt6 or a running app. What is worth pinning down is
the part that is easy to get quietly wrong:

- **the cost of an entry**, because the chatbox has 144 characters and
  the picker promises a number in a tooltip. A flag that claims to cost
  one and actually costs five is a promise broken at the point where it
  matters;
- **the flags themselves**, which are built from ISO codes rather than
  pasted, and where a wrong pair of invisible codepoints renders as a
  different country;
- **search ranking**, which regressed once already: it stopped at the
  first `limit` matches in palette order, so a query whose best answer
  lived in the last category never reached it.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from core.emojis import (ALIASES, CATEGORY_NOTES, COUNTRIES, EMOJI_CATEGORIES,
                         EMOJIS, FLAGS, PRIDE, _flag, cost, search, visual_len)

RAINBOW_FLAG = "\U0001F3F3\uFE0F\u200D\U0001F308"
TRANS_FLAG = "\U0001F3F3\uFE0F\u200D\u26A7\uFE0F"
TRANS_STRIPES = "\U0001F497\U0001F49C\U0001F499"


# --------------------------------------------------------------------
# the flag table
# --------------------------------------------------------------------
@pytest.mark.parametrize("code, expected", [
    ("DE", "\U0001F1E9\U0001F1EA"),
    ("US", "\U0001F1FA\U0001F1F8"),
    ("JP", "\U0001F1EF\U0001F1F5"),
    ("CH", "\U0001F1E8\U0001F1ED"),
])
def test_flag_builds_the_right_pair(code, expected):
    assert _flag(code) == expected


def test_country_codes_are_unique():
    """A repeated code is a flag that silently replaces another one in
    FLAG_NAMES, so the second country becomes unsearchable."""
    codes = [code for code, _en, _de in COUNTRIES]
    assert len(codes) == len(set(codes))


def test_every_country_has_both_names():
    for code, en, de in COUNTRIES:
        assert len(code) == 2, code
        assert en.strip() and de.strip(), code


def test_flags_are_unique():
    assert len(FLAGS) == len(set(FLAGS))


# --------------------------------------------------------------------
# what an entry costs, and what it draws
# --------------------------------------------------------------------
def test_cost_counts_characters_not_glyphs():
    assert cost("\U0001F525") == 1              # fire
    assert cost("\u2764\uFE0F") == 2            # heart + variation selector
    assert cost(_flag("DE")) == 2               # two regional indicators
    assert cost(RAINBOW_FLAG) == 4
    assert cost(TRANS_FLAG) == 5
    assert cost(TRANS_STRIPES) == 3


def test_visual_len_counts_glyphs_not_characters():
    """The picker sizes a cell by this, so a ZWJ sequence has to come
    out as one however many codepoints it is made of."""
    assert visual_len("\U0001F525") == 1
    assert visual_len("\u2764\uFE0F") == 1
    assert visual_len(_flag("DE")) == 1
    assert visual_len(RAINBOW_FLAG) == 1
    assert visual_len(TRANS_FLAG) == 1
    assert visual_len(TRANS_STRIPES) == 3


def test_pride_rows_fit_a_picker_cell():
    """Four is the ceiling the grid is laid out for - see the comment on
    PRIDE. A five-glyph row would be clipped rather than shrunk."""
    assert max(visual_len(e) for e in PRIDE) <= 4


def test_ordinary_categories_stay_single_glyph():
    """Everything outside Pride is one glyph per cell, which is what
    lets the picker use a square cell for those pages."""
    for name, _icon, block in EMOJI_CATEGORIES:
        if name == "Pride":
            continue
        widest = max(visual_len(e) for e in block)
        assert widest == 1, f"{name} has a {widest}-glyph entry"


# --------------------------------------------------------------------
# search
# --------------------------------------------------------------------
@pytest.mark.parametrize("query, expected", [
    ("germany", "\U0001F1E9\U0001F1EA"),
    ("deutschland", "\U0001F1E9\U0001F1EA"),
    ("japan", "\U0001F1EF\U0001F1F5"),
    ("schweiz", "\U0001F1E8\U0001F1ED"),
    ("trans", TRANS_FLAG),
    ("fire", "\U0001F525"),
])
def test_search_puts_the_obvious_answer_first(query, expected):
    hits = search(query)
    assert hits, f"{query!r} found nothing"
    assert hits[0] == expected


def test_search_reaches_the_last_category():
    """The regression this guards: search used to stop at `limit`
    matches in palette order. Flags are the last category, and "japan"
    matches JAPANESE OGRE and half a dozen other Smileys first, so the
    Japanese flag was never reached."""
    assert "\U0001F1EF\U0001F1F5" in search("japan")


def test_search_narrows_with_a_second_word():
    broad = search("flag")
    narrow = search("flag germany")
    assert len(narrow) < len(broad)
    assert narrow == ["\U0001F1E9\U0001F1EA"]


def test_search_respects_the_limit():
    assert len(search("a", limit=5)) == 5


def test_empty_search_returns_nothing():
    assert search("") == []
    assert search("   ") == []


def test_search_does_not_match_on_regional_indicator_names():
    """Every flag contains "REGIONAL INDICATOR SYMBOL LETTER x". Left in
    the index, "letter" matched 150 flags and buried the envelope."""
    assert _flag("DE") not in search("indicator")
    assert _flag("DE") not in search("letter")


def test_no_duplicate_alias_keys():
    """A repeated key in the ALIASES literal is legal Python and drops
    the earlier entry, which is how one of the two game-controller
    keyword sets went missing."""
    source = (__import__("pathlib").Path(__file__).parent.parent
              / "core" / "emojis.py").read_text()
    tree = __import__("ast").parse(source)
    for node in __import__("ast").walk(tree):
        if not isinstance(node, __import__("ast").Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, __import__("ast").Constant)
                and isinstance(k.value, str)]
        assert len(keys) == len(set(keys)), \
            f"duplicate keys: {[k for k in keys if keys.count(k) > 1]}"


# --------------------------------------------------------------------
# the palette as a whole
# --------------------------------------------------------------------
def test_flat_list_covers_every_category_without_repeats():
    for _name, _icon, block in EMOJI_CATEGORIES:
        for entry in block:
            assert entry in EMOJIS
    assert len(EMOJIS) == len(set(EMOJIS))


def test_flag_categories_carry_a_warning():
    """Both cost more than one character and both may not render, and
    the picker has nowhere else to say so."""
    for name in ("Pride", "Flags"):
        assert CATEGORY_NOTES.get(name, "").strip()


def test_every_alias_points_at_a_real_entry():
    """An alias for an emoji that is not in the palette is a search term
    that can never match anything."""
    missing = [e for e in ALIASES if e not in EMOJIS]
    assert not missing, missing
