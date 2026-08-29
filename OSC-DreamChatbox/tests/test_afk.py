"""
tests/test_afk.py - who decides that you are away, and what goes out.

Three things are worth pinning down here.

The **parameter reading**, because VRChat sends a bool but an avatar
carrying its own away toggle through a bridge can send a float, an int
or a word - and "no parameter has arrived" must never be mistaken for
"the player is here", since the two need completely different help text.

The **precedence**, because the manual switch is an explicit statement:
somebody who flips "I'm AFK" while VRChat still thinks they are present
meant it, and detection must not argue.

The **payload takeover**, which is the whole point of the feature: while
you are away the chatbox says one thing, not one thing plus a song plus
your GPU temperature. The off-by-default half matters just as much -
every existing config has none of these keys, and must behave exactly as
it did before.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from core.afk import (
    afk_body, afk_param_name, afk_text, format_afk_time, is_afk_value)
from core.constants import (
    AFK_PRESET_COUNT, DEFAULT_AFK_PARAM, DEFAULT_AFK_TEXTS,
    DEFAULT_AFK_TIMER_TEXT)
from core.textstyle import STYLE_NORMAL


class FakeListener:
    """core/oscin.py's listener, reduced to the two things afk cares
    about: is it up, and what was the last value seen."""

    def __init__(self, params=None, running=True):
        self._params = dict(params or {})
        self.running = running
        self.port = 9001

    def get(self, name):
        return self._params.get(name)


def make_host(cfg=None, listener=None):
    """A MainWindow with nothing but the AFK methods on it.

    Built by hand rather than by starting the real window, because none
    of the rules under test need a screen - and a test that needs Qt is
    a test that stops running on the machine that packages the AppImage.
    """
    from ui.mainwindow import MainWindow

    host = MainWindow.__new__(MainWindow)
    host.cfg = {
        "afk_detect": False,
        "afk_manual": False,
        "afk_param": DEFAULT_AFK_PARAM,
        "afk_preset": 0,
        "afk_texts": list(DEFAULT_AFK_TEXTS),
        "afk_timer": False,
        "afk_timer_text": DEFAULT_AFK_TIMER_TEXT,
        "afk_style": STYLE_NORMAL,
        "afk_solo": True,
    }
    host.cfg.update(cfg or {})
    host.osc_in = listener if listener is not None else FakeListener({})
    # the away stopwatch, normally started in MainWindow.__init__
    host._afk_since = None
    # _render_status() lives on the Apps page mixin and only runs the
    # template engine when there is a {placeholder} in the text, so a
    # plain AFK line never touches the plugin manager at all
    host.plugins = None
    return host


# --------------------------------------------------------------------
# reading the parameter
# --------------------------------------------------------------------
def test_bools_are_taken_at_face_value():
    assert is_afk_value(True) is True
    assert is_afk_value(False) is False


def test_nothing_heard_is_not_away():
    assert is_afk_value(None) is False


def test_floats_use_a_midpoint_not_a_zero_test():
    # an animator value never lands exactly on 1.0
    assert is_afk_value(0.98) is True
    assert is_afk_value(0.02) is False
    assert is_afk_value(1) is True
    assert is_afk_value(0) is False


def test_words_a_bridge_might_send():
    for word in ("1", "true", "True", "on", "yes", "AFK", " away "):
        assert is_afk_value(word) is True, word
    for word in ("", "0", "false", "off", "no", "  "):
        assert is_afk_value(word) is False, word


def test_a_bundled_message_reads_its_first_argument():
    assert is_afk_value((True, "headset off")) is True
    assert is_afk_value((False,)) is False
    assert is_afk_value(()) is False


# --------------------------------------------------------------------
# which parameter, and which text
# --------------------------------------------------------------------
def test_empty_parameter_name_falls_back_to_the_builtin():
    assert afk_param_name({"afk_param": "   "}) == DEFAULT_AFK_PARAM
    assert afk_param_name({}) == DEFAULT_AFK_PARAM
    assert afk_param_name({"afk_param": "MyAway"}) == "MyAway"


def test_each_slot_keeps_its_own_text():
    # trying text 2 out must not overwrite what text 1 said
    cfg = {"afk_preset": 0, "afk_texts": ["one", "two", "three"]}
    assert afk_text(cfg) == "one"
    cfg["afk_preset"] = 1
    assert afk_text(cfg) == "two"


def test_an_empty_slot_never_blanks_the_chatbox():
    # being AFK with nothing on screen is not what the switch was for
    cfg = {"afk_preset": 0, "afk_texts": ["   ", "", ""]}
    assert afk_text(cfg) == DEFAULT_AFK_TEXTS[0]


def test_an_out_of_range_slot_falls_back_to_the_first():
    assert afk_text({"afk_preset": 99, "afk_texts": ["a", "b", "c"]}) == "a"
    assert afk_text({"afk_preset": "nonsense"}) == DEFAULT_AFK_TEXTS[0]
    assert len(DEFAULT_AFK_TEXTS) == AFK_PRESET_COUNT


# --------------------------------------------------------------------
# precedence
# --------------------------------------------------------------------
def test_manual_wins_over_a_disagreeing_vrchat():
    host = make_host({"afk_manual": True, "afk_detect": True},
                     FakeListener({"AFK": False}))
    assert host.afk_active() is True


def test_manual_works_with_the_osc_input_down():
    host = make_host({"afk_manual": True}, FakeListener({}, running=False))
    assert host.afk_active() is True


def test_detection_needs_its_switch():
    listener = FakeListener({"AFK": True})
    assert make_host({"afk_detect": False}, listener).afk_active() is False
    assert make_host({"afk_detect": True}, listener).afk_active() is True


def test_detection_reads_nothing_while_the_listener_is_down():
    host = make_host({"afk_detect": True},
                     FakeListener({"AFK": True}, running=False))
    assert host.afk_param_value() is None
    assert host.afk_active() is False


def test_a_renamed_parameter_is_followed():
    host = make_host({"afk_detect": True, "afk_param": "MyAway"},
                     FakeListener({"AFK": True, "MyAway": False}))
    assert host.afk_active() is False
    host.osc_in._params["MyAway"] = True
    assert host.afk_active() is True


# --------------------------------------------------------------------
# what actually goes out
# --------------------------------------------------------------------
def test_no_line_while_present():
    assert make_host().afk_line() == ""


def test_the_line_is_the_first_default_text_and_nothing_else():
    # no frame: box characters do not line up in VRChat's proportional
    # chatbox font, so drawing one there produced loose segments
    host = make_host({"afk_manual": True})
    assert host.afk_line() == DEFAULT_AFK_TEXTS[0]


def test_the_rotations_stand_down_only_while_afk_owns_the_box():
    # nothing to protect while present
    assert make_host().afk_holds_the_chatbox() is False
    # away and alone on screen: a text rotating behind it is invisible
    assert make_host({"afk_manual": True}).afk_holds_the_chatbox() is True
    # away but sharing the box: the lines below still have to update
    assert make_host({"afk_manual": True, "afk_solo": False}) \
        .afk_holds_the_chatbox() is False


def test_the_line_follows_the_style_dropdown():
    from core.textstyle import STYLE_SUPER, apply_style

    host = make_host({"afk_manual": True, "afk_style": STYLE_SUPER,
                      "afk_texts": ["afk", "", ""]})
    assert host.afk_line() == apply_style("afk", STYLE_SUPER)


# --------------------------------------------------------------------
# the timer
# --------------------------------------------------------------------
def test_the_timer_counts_in_whole_minutes():
    # seconds would put a message on the wire every few seconds for as
    # long as you are gone, which VRChat answers with a blackout
    assert format_afk_time(0) == "<1 min"
    assert format_afk_time(59) == "<1 min"
    assert format_afk_time(60) == "1 min"
    assert format_afk_time(12 * 60) == "12 min"
    assert format_afk_time(3600) == "1 h 00 min"
    assert format_afk_time(3900) == "1 h 05 min"


def test_the_timer_line_is_appended_not_woven_in():
    cfg = {"afk_preset": 0, "afk_texts": ["away", "", ""],
           "afk_timer": True, "afk_timer_text": "seit {afk_time}"}
    assert afk_body(cfg, "7 min") == ["away", "seit 7 min"]
    # switching it off leaves the text exactly as it was
    cfg["afk_timer"] = False
    assert afk_body(cfg, "7 min") == ["away"]


def test_a_hand_placed_counter_is_not_doubled():
    # the user said where they want it; adding a second copy underneath
    # would be the app arguing
    cfg = {"afk_preset": 0, "afk_texts": ["brb {afk_time}", "", ""],
           "afk_timer": True, "afk_timer_text": "for {afk_time}"}
    assert afk_body(cfg, "3 min") == ["brb 3 min"]


def test_a_backslash_n_is_a_line_break():
    cfg = {"afk_preset": 0, "afk_texts": ["one \\n two", "", ""]}
    assert afk_body(cfg) == ["one", "two"]
