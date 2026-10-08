"""
core/boxanim.py – animated Custom Box frame (v1.6.6)

Makes the frame move to catch the eye. Only the FILL of the two frame
lines changes - caps and middle text stay put - so the box keeps its
width and nothing jumps around:

    blink    ┌──── 18:01 ────┐   ->   ┌     18:01     ┐
    load     ┌▓▓░░ 18:01 ░░░░┐   ->   ┌▓▓▓▓ 18:01 ░░░░┐
    rotate   ┌─◆── 18:01 ────┐   ->   ┌──◆─ 18:01 ────┐
             (top runs right, bottom runs left - round the box)

Every animation step is one chatbox message, so the step time is 2 s at
the fastest (VRChat's rate limit). Pure Python, no Qt.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

ANIM_OFF = "off"
ANIM_BLINK = "blink"
ANIM_LOAD = "load"
ANIM_ROTATE = "rotate"

ANIMATIONS = [
    ("Off", ANIM_OFF),
    ("Blink", ANIM_BLINK),
    ("Loading  ▓▓▓░░░", ANIM_LOAD),
    ("Rotate  ─◆──", ANIM_ROTATE),
]
_IDS = {v for _l, v in ANIMATIONS}

LOAD_FULL = "▓"     # ▓
LOAD_EMPTY = "░"    # ░
ROTATE_MARK = "◆"   # ◆
#: steps from empty to full bar (then it starts over)
LOAD_STEPS = 6

MIN_STEP_SEC = 2
MAX_STEP_SEC = 30


def normalize_anim(value) -> str:
    return value if value in _IDS else ANIM_OFF


def fill_function(mode: str, frame: int, fill: str, bottom: bool = False):
    """A callable(n, offset, total) -> str that replaces the plain
    `fill * n` of one frame line, or None for "no animation".

    n       units of this fill segment (left or right of the middle)
    offset  index of the segment's first unit within the whole line
    total   all fill units of the line (both segments)
    """
    mode = normalize_anim(mode)
    if mode == ANIM_OFF:
        return None
    fill = fill or " "
    frame = max(0, int(frame))

    if mode == ANIM_BLINK:
        def blink(n, _offset, _total):
            return (" " if frame % 2 else fill) * n
        return blink

    if mode == ANIM_LOAD:
        # both lines fill in the same LOAD_STEPS steps, whatever their
        # length, so top and bottom are full at the same moment
        k = frame % (LOAD_STEPS + 1)

        def load(n, offset, total):
            done = round(total * k / LOAD_STEPS) if total else 0
            return "".join(LOAD_FULL if offset + i < done else LOAD_EMPTY
                           for i in range(n))
        return load

    def rotate(n, offset, total):
        if not total:
            return fill * n
        pos = frame % total
        if bottom:
            pos = total - 1 - pos
        return "".join(ROTATE_MARK if offset + i == pos else fill
                       for i in range(n))
    return rotate
