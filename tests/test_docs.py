"""
tests/test_docs.py - the two files behind Options -> General.

The **top blocks** must match core/constants.py -> VERSION. Otherwise
the Highlights button of a fresh release shows the previous one as
"what's new", and nobody notices until a user asks.

Every **Highlights version must exist in the changelog**. That is what
the "Full changelog" button promises - and it is also the check that
would have caught the v1.4.5 heading that got lost in CHANGELOG.md.

The **lookup** must find both files from source, which is the same
place (next to the app) the AppImage, AUR and Windows builds put them.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from pathlib import Path

from core.constants import VERSION

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
HIGHLIGHTS = ROOT / "HIGHLIGHTS.md"

CHANGELOG_HEAD = re.compile(r"^## \[v?([^\]]+)\]", re.M)
HIGHLIGHTS_HEAD = re.compile(r"^## v?(\S+)", re.M)


def _versions(path, pattern):
    return pattern.findall(path.read_text(encoding="utf-8"))


def test_changelog_top_block_is_current_version():
    assert _versions(CHANGELOG, CHANGELOG_HEAD)[0] == VERSION.lstrip("v")


def test_highlights_top_block_is_current_version():
    assert _versions(HIGHLIGHTS, HIGHLIGHTS_HEAD)[0] == VERSION.lstrip("v")


def test_every_highlight_has_a_changelog_entry():
    changelog = set(_versions(CHANGELOG, CHANGELOG_HEAD))
    missing = [v for v in _versions(HIGHLIGHTS, HIGHLIGHTS_HEAD)
               if v not in changelog]
    assert missing == []


def test_highlights_stay_short():
    # the whole point of the file: a few lines per release, not a
    # second changelog
    blocks = re.split(r"^## ", HIGHLIGHTS.read_text(encoding="utf-8"),
                      flags=re.M)[1:]
    for block in blocks:
        bullets = [ln for ln in block.splitlines() if ln.startswith("- ")]
        assert 1 <= len(bullets) <= 4, block.splitlines()[0]


def test_docviewer_finds_both_files():
    from ui.docviewer import CHANGELOG_FILE, HIGHLIGHTS_FILE, find_doc
    assert find_doc(CHANGELOG_FILE) == CHANGELOG
    assert find_doc(HIGHLIGHTS_FILE) == HIGHLIGHTS
