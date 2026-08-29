"""
tests/test_status_rotation.py - which text comes up next, and why.

advance_status() is the whole of the Personal Status rotation, and it is
a pure function of the config plus one random draw. Everything around it
- the send timer, the preview, the pending/commit dance - is stubbed
here, because none of that changes which index gets picked.

Two things are worth pinning down. The **order** itself, sequential
being new in v1.4.5 and random being what every existing config still
does. And the **empty slot**, which is the case that breaks a naive
sequential rotation: leaving Text 3 blank while editing is normal, and a
rotation that stopped there would look like the app had frozen.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ui.pages.apps_page import AppsPageMixin


def make_page(texts, random_order, count=None):
    """An AppsPageMixin with nothing but a config and the two methods
    advance_status() reaches into."""
    page = AppsPageMixin.__new__(AppsPageMixin)
    page.cfg = {
        "status_texts": list(texts) + [""] * (20 - len(texts)),
        "status_count": count if count is not None else len(texts),
        "status_random": random_order,
        "send_to_vrchat": False,
    }
    page.status_index = 0
    page.pending_status_index = None
    page.sending_live = lambda: False
    # advance_status() asks this before its instant send - see
    # MainWindow.afk_holds_the_chatbox(). "not away" is the case every
    # test below is about.
    page.afk_holds_the_chatbox = lambda: False
    page.update_preview = lambda: None
    page.log = lambda *_a, **_k: None
    return page


def rotate(page, steps):
    """The texts shown over `steps` switches, starting with the current
    one. commit_status() is what a real send would call."""
    seen = [page.current_status_text()]
    for _ in range(steps):
        page.advance_status()
        page.commit_status()
        seen.append(page.current_status_text())
    return seen


# --------------------------------------------------------------------
# in order
# --------------------------------------------------------------------
def test_sequential_runs_top_to_bottom_and_wraps():
    page = make_page(["A", "B", "C"], random_order=False)
    assert rotate(page, 6) == ["A", "B", "C", "A", "B", "C", "A"]


def test_sequential_skips_empty_slots():
    """The gap is the point: Text 3 is blank, so the order is A B D E."""
    page = make_page(["A", "B", "", "D", "E"], random_order=False)
    assert rotate(page, 7) == ["A", "B", "D", "E", "A", "B", "D", "E"]


def test_sequential_ignores_texts_past_the_count():
    """"Number of texts" is 2, so C exists in the config but is not in
    the rotation."""
    page = make_page(["A", "B", "C"], random_order=False, count=2)
    assert rotate(page, 3) == ["A", "B", "A", "B"]


# --------------------------------------------------------------------
# random
# --------------------------------------------------------------------
def test_random_never_repeats_back_to_back():
    page = make_page(["A", "B", "C", "D"], random_order=True)
    seen = rotate(page, 200)
    assert all(a != b for a, b in zip(seen, seen[1:]))


def test_random_reaches_every_text():
    page = make_page(["A", "B", "C", "D"], random_order=True)
    assert set(rotate(page, 200)) == {"A", "B", "C", "D"}


def test_random_is_the_default_for_a_config_without_the_key():
    """Configs written before v1.4.5 have no status_random at all, and
    the missing value has to keep meaning random."""
    page = make_page(["A", "B", "C"], random_order=True)
    del page.cfg["status_random"]
    seen = rotate(page, 60)
    # a sequential rotation of three is A B C A B C; random will not
    # produce that run for sixty steps
    assert seen != ["A", "B", "C"] * 20 + ["A"]
    assert set(seen) == {"A", "B", "C"}


# --------------------------------------------------------------------
# the degenerate cases
# --------------------------------------------------------------------
@pytest.mark.parametrize("random_order", [True, False])
def test_a_single_text_stands_still(random_order):
    page = make_page(["only"], random_order=random_order)
    assert rotate(page, 5) == ["only"] * 6


@pytest.mark.parametrize("random_order", [True, False])
def test_all_texts_empty_is_not_an_error(random_order):
    page = make_page(["", "", ""], random_order=random_order)
    assert rotate(page, 3) == [""] * 4


# --------------------------------------------------------------------
# AFK
# --------------------------------------------------------------------
def test_rotation_keeps_running_but_stays_quiet_while_afk():
    """Away, with the AFK line owning the chatbox.

    The rotation must not stop - coming back should continue where it
    left off, not restart at Text 1 - but it must not send either,
    because the text it switched to is invisible behind the AFK line and
    the identical payload would only cost part of VRChat's chatbox rate
    limit.
    """
    page = make_page(["A", "B", "C"], random_order=False)
    page.afk_holds_the_chatbox = lambda: True
    sent = []
    page.send_after_change = lambda: sent.append(page.current_status_text())

    assert rotate(page, 3) == ["A", "B", "C", "A"]
    assert sent == []
