"""
core/boxstyle.py – the frame around the chatbox (Custom Box).

One line above everything and one line below everything, so the VRChat
chatbox reads as a closed box instead of a stack of loose lines::

    ┌──────┐            ┌─── 18:01 ───┐
    now playing …  ->   now playing …
    └──────┘            └─── 68 % ───┘

A template is nothing but six strings: the left cap, the repeated fill
and the right cap, twice – once for the top line and once for the bottom
line. That is deliberately the whole model. Anything fancier (per-side
templates, multi-row frames) would cost characters out of the 144 the
chatbox gives us, and the frame is the one part that must stay cheap.

Both lines can carry a middle text (a clock, or any custom string with
the same placeholders All-in-one accepts). The fill is then split evenly
around it, which is what turns ``┌──────┐`` into ``┌─── 18:01 ───┐``.

Character widths are estimated with east_asian_width so a frame built
from wide characters (✧, ♡, 〜) can still be aligned against a narrow
one. VRChat's chatbox font is not monospaced, so this is an
approximation on purpose – it gets the two lines close, it cannot get
them pixel perfect, and pretending otherwise would only add code.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import unicodedata
from datetime import datetime

# --------------------------------------------------------------- sides
SIDE_TOP = "top"
SIDE_BOTTOM = "bottom"

# ----------------------------------------------------------- templates
# Each entry: name + the six parts. "" as a cap is allowed and gives a
# plain rule with no corners.
#   tl / tf / tr = top    left cap / fill / right cap
#   bl / bf / br = bottom left cap / fill / right cap
BOX_TEMPLATES = [
    {"name": "Light",
     "tl": "\u250C", "tf": "\u2500", "tr": "\u2510",
     "bl": "\u2514", "bf": "\u2500", "br": "\u2518"},
    {"name": "Heavy",
     "tl": "\u250F", "tf": "\u2501", "tr": "\u2513",
     "bl": "\u2517", "bf": "\u2501", "br": "\u251B"},
    {"name": "Double",
     "tl": "\u2554", "tf": "\u2550", "tr": "\u2557",
     "bl": "\u255A", "bf": "\u2550", "br": "\u255D"},
    {"name": "Rounded",
     "tl": "\u256D", "tf": "\u2500", "tr": "\u256E",
     "bl": "\u2570", "bf": "\u2500", "br": "\u256F"},
    {"name": "Dashed",
     "tl": "\u250C", "tf": "\u254C", "tr": "\u2510",
     "bl": "\u2514", "bf": "\u254C", "br": "\u2518"},
    {"name": "Blocks",
     "tl": "\u259B", "tf": "\u2580", "tr": "\u259C",
     "bl": "\u2599", "bf": "\u2584", "br": "\u259F"},
    {"name": "Rule",
     "tl": "", "tf": "\u2594", "tr": "",
     "bl": "", "bf": "\u2581", "br": ""},
    {"name": "Corners",
     "tl": "\u25E4", "tf": "\u2501", "tr": "\u25E5",
     "bl": "\u25E3", "bf": "\u2501", "br": "\u25E2"},
    {"name": "Stars",
     "tl": "\u2726", "tf": "\u2500", "tr": "\u2726",
     "bl": "\u2726", "bf": "\u2500", "br": "\u2726"},
    {"name": "Hearts",
     "tl": "\u2661", "tf": "\u2500", "tr": "\u2661",
     "bl": "\u2661", "bf": "\u2500", "br": "\u2661"},
    {"name": "Arrows",
     "tl": "\u226A", "tf": "\u2501", "tr": "\u226B",
     "bl": "\u226A", "bf": "\u2501", "br": "\u226B"},
    {"name": "Sparkles",
     "tl": "\u2727", "tf": "\uFF65", "tr": "\u2727",
     "bl": "\u2727", "bf": "\uFF65", "br": "\u2727"},
]

# index of the user-defined template (= right after the presets)
CUSTOM_BOX_INDEX = len(BOX_TEMPLATES)

DEFAULT_CUSTOM_BOX = {
    "tl": "\u2039", "tf": "\u00B7", "tr": "\u203A",
    "bl": "\u2039", "bf": "\u00B7", "br": "\u203A",
}

# ------------------------------------------------------- middle modes
MODE_NONE = "none"
MODE_CLOCK = "clock"
MODE_CUSTOM = "custom"

MIDDLE_MODES = (
    ("None  \u2013  \u250C\u2500\u2500\u2500\u2500\u2500\u2500\u2510", MODE_NONE),
    ("Clock  \u2013  \u250C\u2500\u2500\u2500 18:01 \u2500\u2500\u2500\u2510",
     MODE_CLOCK),
    ("Custom  \u2013  own text + placeholders", MODE_CUSTOM),
)

# ------------------------------------------------------ clock formats
CLOCK_24_HM = "hm24"
CLOCK_24_HMS = "hms24"
CLOCK_12_HM = "hm12"
CLOCK_12_HM_SUFFIX = "hm12ap"

CLOCK_FORMATS = (
    ("18:01", CLOCK_24_HM),
    ("18:01:47", CLOCK_24_HMS),
    ("6:01", CLOCK_12_HM),
    ("6:01 PM", CLOCK_12_HM_SUFFIX),
)

#: formats that change every second – the only ones that need a fast tick
SECOND_FORMATS = (CLOCK_24_HMS,)

WIDTH_MIN = 0
WIDTH_MAX = 40


def normalize_template(idx) -> int:
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return 0
    return idx if 0 <= idx <= CUSTOM_BOX_INDEX else 0


def normalize_mode(value) -> str:
    value = str(value or "").strip().lower()
    return value if value in (MODE_NONE, MODE_CLOCK, MODE_CUSTOM) else MODE_NONE


def normalize_clock_format(value) -> str:
    value = str(value or "").strip()
    known = [v for _, v in CLOCK_FORMATS]
    return value if value in known else CLOCK_24_HM


def normalize_width(value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 6
    return max(WIDTH_MIN, min(WIDTH_MAX, value))


def normalize_custom(parts) -> dict:
    """A custom template with every part forced to a short string. The
    caps may be empty (that is a valid rule-style frame); an empty fill
    is not, because it would collapse the whole line to two caps."""
    out = dict(DEFAULT_CUSTOM_BOX)
    if isinstance(parts, dict):
        for key in out:
            val = parts.get(key)
            if isinstance(val, str):
                # 4 characters is plenty for a cap and keeps a paste
                # accident from eating the character budget
                out[key] = val[:4]
    if not out["tf"]:
        out["tf"] = DEFAULT_CUSTOM_BOX["tf"]
    if not out["bf"]:
        out["bf"] = DEFAULT_CUSTOM_BOX["bf"]
    return out


def template(idx, custom=None) -> dict:
    """The six parts of template ``idx``; ``custom`` is only consulted
    for the user-defined slot."""
    idx = normalize_template(idx)
    if idx == CUSTOM_BOX_INDEX:
        return normalize_custom(custom)
    return dict(BOX_TEMPLATES[idx])


def template_name(idx) -> str:
    idx = normalize_template(idx)
    if idx == CUSTOM_BOX_INDEX:
        return "Custom"
    return BOX_TEMPLATES[idx]["name"]


def parts(tpl: dict, side: str):
    """(left cap, fill, right cap) of one side of a template."""
    if side == SIDE_BOTTOM:
        return tpl.get("bl", ""), tpl.get("bf", ""), tpl.get("br", "")
    return tpl.get("tl", ""), tpl.get("tf", ""), tpl.get("tr", "")


def cells(text: str) -> int:
    """Rough display width of ``text`` in character cells.

    Wide/fullwidth characters count as two, combining marks as zero,
    everything else as one. Good enough to line the two frame lines up
    against each other; it is not a font metric and cannot be one.
    """
    total = 0
    for ch in text or "":
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def build_line(tpl: dict, side: str, width: int, middle: str = "",
               extra_left: int = 0, extra_right: int = 0) -> str:
    """One frame line.

    Without a middle text the fill is repeated ``width`` times. With one,
    the fill is split evenly around it – ``width`` 6 gives three fill
    units per side, which is exactly the ``┌─── 18:01 ───┐`` shape.
    ``extra_left`` / ``extra_right`` are what the aligner adds on top;
    nothing else should pass them.
    """
    left, fill, right = parts(tpl, side)
    width = max(0, int(width))
    if not fill:
        # a fill-less template would repeat nothing, so the width slider
        # would do nothing either – fall back to a space so the caps at
        # least keep their distance
        fill = " "
    middle = (middle or "").strip()
    if not middle:
        return left + fill * (width + max(0, extra_left)
                              + max(0, extra_right)) + right
    half = width // 2
    return (left + fill * (half + max(0, extra_left))
            + " " + middle + " "
            + fill * (half + max(0, extra_right)) + right)


def _grow_to(tpl, side, width, middle, target, guard=120) -> str:
    """Adds fill units (alternating left/right) until the line is at
    least ``target`` cells wide. Stops at the first line that reaches or
    passes the target, so a wide fill character overshoots by at most one
    unit instead of looping forever."""
    left = right = 0
    line = build_line(tpl, side, width, middle)
    steps = 0
    while cells(line) < target and steps < guard:
        if left <= right:
            left += 1
        else:
            right += 1
        line = build_line(tpl, side, width, middle, left, right)
        steps += 1
    return line


def render_pair(tpl: dict, width_top: int, width_bottom: int = None,
                top_middle: str = "", bottom_middle: str = "",
                top_on: bool = True, bottom_on: bool = True,
                align: bool = True):
    """(top line, bottom line) – either may be "" when that side is off.

    The two sides have their own width because their middle texts rarely
    have the same length: a clock on top and a hardware line underneath
    want different amounts of fill to end up looking like one box.
    ``width_bottom`` defaults to ``width_top`` so a caller that only
    cares about a symmetric frame can pass one number.

    With ``align`` the shorter of the two *rendered* lines is then padded
    with extra fill until both are about the same width. The widths stay
    the starting point – align only ever adds, it never trims – so for
    two deliberately different lines, switch it off.
    """
    if width_bottom is None:
        width_bottom = width_top
    top = build_line(tpl, SIDE_TOP, width_top, top_middle) if top_on else ""
    bottom = (build_line(tpl, SIDE_BOTTOM, width_bottom, bottom_middle)
              if bottom_on else "")
    if align and top and bottom:
        target = max(cells(top), cells(bottom))
        if cells(top) < target:
            top = _grow_to(tpl, SIDE_TOP, width_top, top_middle, target)
        if cells(bottom) < target:
            bottom = _grow_to(tpl, SIDE_BOTTOM, width_bottom,
                              bottom_middle, target)
    return top, bottom


def clock_text(fmt: str, now: datetime | None = None) -> str:
    """The clock string for one of the CLOCK_FORMATS. Built by hand
    rather than with strftime so it reads the same on every platform –
    Windows has no %-I and would print a leading zero."""
    now = now or datetime.now()
    fmt = normalize_clock_format(fmt)
    if fmt == CLOCK_24_HMS:
        return f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
    if fmt in (CLOCK_12_HM, CLOCK_12_HM_SUFFIX):
        hour = now.hour % 12 or 12
        text = f"{hour}:{now.minute:02d}"
        if fmt == CLOCK_12_HM_SUFFIX:
            text += " AM" if now.hour < 12 else " PM"
        return text
    return f"{now.hour:02d}:{now.minute:02d}"


def clock_needs_seconds(fmt: str) -> bool:
    """True when the chosen format changes every second, so the live
    clock timer knows whether a 1 s tick is worth its wakeups."""
    return normalize_clock_format(fmt) in SECOND_FORMATS


def preview(tpl_idx, width_top, width_bottom=None, top_middle="",
            bottom_middle="", custom=None, top_on=True, bottom_on=True,
            align=True) -> str:
    """Both lines in one string – used for the little preview label."""
    top, bottom = render_pair(template(tpl_idx, custom), width_top,
                              width_bottom, top_middle, bottom_middle,
                              top_on, bottom_on, align)
    return "\n".join(x for x in (top, bottom) if x)
