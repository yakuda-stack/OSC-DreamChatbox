"""
tests/test_template_rotation.py - {text_tX} of a template that is NOT the
active one walks its OWN list.

The bug (v1.5.9 and earlier): all templates shared the active template's
index and the 20 cap. With 2 texts in template 1, {text_t2} only ever
showed the first two texts of template 2.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from ui.pages.apps_page import AppsPageMixin


def make_page(active_texts, other_texts, random_order=False):
    page = AppsPageMixin.__new__(AppsPageMixin)
    tpls = [{"name": "T1", "texts": list(active_texts),
             "count": len(active_texts), "styles": []},
            {"name": "T2", "texts": list(other_texts),
             "count": len(other_texts), "styles": []}]
    page.cfg = {"status_templates": tpls, "status_template_active": 0,
                "status_texts": list(active_texts),
                "status_count": len(active_texts),
                "status_random": random_order, "status_active": True,
                "send_to_vrchat": False}
    page.status_index = 0
    page.pending_status_index = None
    page.sending_live = lambda: False
    page.afk_holds_the_chatbox = lambda: False
    page.update_preview = lambda: None
    page._render_status = lambda text, style: text
    return page


def walk(page, key, steps):
    seen = []
    for _ in range(steps):
        seen.append(page.resolve_status_template(key))
        page.advance_status()
    return seen


def test_other_template_walks_its_whole_list():
    others = [f"Q{i}" for i in range(1, 6)]
    page = make_page(["A", "B"], others)
    assert walk(page, "text_t2", 5) == others


def test_active_template_with_one_text_still_moves_the_others():
    page = make_page(["only"], ["X", "Y", "Z"])
    assert walk(page, "text_t2", 3) == ["X", "Y", "Z"]
    assert page.current_status_text() == "only"


def test_beyond_twenty_in_another_template():
    others = [f"Q{i}" for i in range(1, 31)]
    page = make_page(["A", "B"], others)
    assert walk(page, "text_t2", 30) == others


def test_random_order_reaches_all_texts_of_the_other_template():
    others = [f"Q{i}" for i in range(1, 9)]
    page = make_page(["A", "B"], others, random_order=True)
    seen = walk(page, "text_t2", 400)
    assert set(seen) == set(others)
    assert all(a != b for a, b in zip(seen, seen[1:]))


def test_active_template_via_tx_is_the_normal_rotation():
    page = make_page(["A", "B", "C"], ["X"])
    for _ in range(4):
        assert page.resolve_status_template("text_t1") == \
            page.current_status_text()
        page.advance_status()


def test_timer_needed_for_other_templates():
    assert make_page(["only"], ["X", "Y"]).other_templates_rotate()
    assert not make_page(["A", "B"], ["X"]).other_templates_rotate()


def test_slot_100_of_another_template():
    others = [f"Q{i}" for i in range(1, 101)]
    page = make_page(["A"], others)
    assert page.resolve_status_template("text_t2_100") == "Q100"
