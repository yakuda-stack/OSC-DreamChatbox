"""
core/afk.py – "is the player away right now?", and what the box says.

Two switches sit under the Preview and both end up here:

  * **Detect AFK** watches VRChat's own ``AFK`` avatar parameter and
    flips the chatbox over by itself. VRChat sets that parameter when
    you take the headset off or leave the window alone, so nothing has
    to be guessed from idle timers - the game has already decided.
  * **I'm AFK** is the manual version: no detection, the chatbox says
    you are away for exactly as long as the toggle is on.

Manual wins. It is an explicit statement, and somebody who flips it on
while VRChat still thinks they are present means it.

The parameter arrives over the OSC input (core/oscin.py), which is
opt-in because it binds udp/9001. Detection therefore needs that switch
on; the UI says so rather than leaving a dead toggle.

The other half of this module is the **text**. Three switchable
presets, the way Personal Status switches its templates, each keeping
its own line so trying one out never clobbers another - plus an
optional timer line saying how long you have been gone.

No frame is drawn. VRChat's chatbox font is proportional, so
box-drawing characters do not line up there: a ``╔═══╗`` / ``║ … ║``
frame renders as loose, unconnected segments floating around the text
rather than as a box. Framing belongs to the Custom Box card, which
already puts a top line above and a bottom line below the finished
payload - and only when the user has switched it on.

Everything in here is a pure function of values that were handed in, so
the rules can be tested without a window, a socket or VRChat.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from core.constants import (
    AFK_PRESET_COUNT, DEFAULT_AFK_PARAM, DEFAULT_AFK_TEXTS,
    DEFAULT_AFK_TIMER_TEXT)

#: what counts as "away" when the parameter is sent as text. VRChat
#: sends a bool, but avatars carrying their own AFK toggle through a
#: bridge have been seen sending all of these.
_TRUE_WORDS = ("1", "true", "on", "yes", "afk", "away")
_FALSE_WORDS = ("", "0", "false", "off", "no", "none")

#: what the timer line is looked up by, both in the appended line and
#: anywhere the user typed it into the text themselves
TIME_PLACEHOLDER = "{afk_time}"


# --------------------------------------------------------------- state
def is_afk_value(value):
    """Does this parameter value mean "away"?

    ``None`` is not False, it is *nothing heard yet* - but for a
    yes/no question the honest answer is still "do not claim they are
    away", so it maps to False here and the UI reports the difference
    separately (see AppsPageMixin.update_afk_status).

    A float is compared against 0.5 rather than 0, because a parameter
    that arrives as a float is an animator value and those never land
    exactly on 1.0.
    """
    if value is None:
        return False
    if isinstance(value, (tuple, list)):
        # a message with several arguments - the first one is the value,
        # the rest is whatever the sender bundled with it
        return is_afk_value(value[0]) if value else False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) > 0.5
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _FALSE_WORDS:
            return False
        if text in _TRUE_WORDS:
            return True
        # a number in a string still counts as one
        try:
            return float(text.replace(",", ".")) > 0.5
        except ValueError:
            return True     # some other non-empty word: present, so on
    return bool(value)


def afk_param_name(cfg):
    """Which parameter Detect AFK listens to.

    Configurable because not every setup goes through VRChat's built-in
    one - an avatar with its own away toggle, or a bridge renaming it,
    should not need a fork. Empty falls back to the built-in name
    instead of listening to nothing at all.
    """
    name = str(cfg.get("afk_param", DEFAULT_AFK_PARAM) or "").strip()
    return name or DEFAULT_AFK_PARAM


# --------------------------------------------------------------- timer
def format_afk_time(seconds):
    """How long you have been gone, in the calmest wording available.

    Minute granularity on purpose. The chatbox re-sends whenever the
    text changes, so a seconds counter would put a message on the wire
    every few seconds for as long as you are away - and VRChat answers
    a burst of those with a blackout. A number that moves once a minute
    says the same thing and costs one send an hour more than a static
    line does.
    """
    seconds = max(0, int(seconds or 0))
    minutes = seconds // 60
    if minutes < 1:
        return "<1 min"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


# ---------------------------------------------------------------- text
def afk_preset(cfg):
    """Which of the three texts is selected."""
    try:
        idx = int(cfg.get("afk_preset", 0))
    except (TypeError, ValueError):
        return 0
    return idx if 0 <= idx < AFK_PRESET_COUNT else 0


def afk_text(cfg, index=None):
    """The raw text of one preset.

    Each preset keeps its own, the way each Personal Status template
    keeps its own texts: switching over to preset 2 to see what it says
    must not overwrite preset 1. An empty one falls back to its built-in
    line - being AFK with a *blank* chatbox is never what the switch was
    turned on for.
    """
    index = afk_preset(cfg) if index is None else index
    index = index if 0 <= index < AFK_PRESET_COUNT else 0
    stored = cfg.get("afk_texts")
    stored = stored if isinstance(stored, list) else []
    text = str(stored[index]).strip() if index < len(stored) else ""
    return text or DEFAULT_AFK_TEXTS[index]


def afk_body(cfg, time_text=""):
    """The finished lines, ready to go into the payload.

    ``\\n`` in the text is a line break, the same two-character spelling
    All in one uses - it has to survive a single-line QLineEdit and a
    JSON round trip.

    The timer line is *appended* rather than woven into the text, so
    turning it on and off never touches what you typed. It is skipped
    when the text already contains ``{afk_time}``: somebody who placed
    the counter by hand has said where they want it, and adding a second
    copy underneath would be the app arguing.
    """
    text = afk_text(cfg).replace("\\n", "\n")
    lines = text.split("\n")
    if cfg.get("afk_timer") and TIME_PLACEHOLDER not in text:
        lines.append(str(cfg.get("afk_timer_text")
                         or DEFAULT_AFK_TIMER_TEXT))
    if time_text:
        lines = [line.replace(TIME_PLACEHOLDER, time_text) for line in lines]
    return [line.strip() for line in lines if line.strip()]
