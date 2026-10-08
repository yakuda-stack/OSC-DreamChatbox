"""
core/aioscroll.py – "Star Wars" scroll between AIO strings (v1.6.6)

Normally the All in one rotation swaps one string for the next in a
single jump. With "Scroll" on, the old text moves up one line per step
and the new one comes in from below, like the opening crawl:

    on screen   step 1      done
    old 1       old 2       new 1
    old 2       new 1       new 2

Works on finished lines, so Normal mode and the node canvas (Advanced
mode) get it alike. Every step is one chatbox message, which is why
the step time cannot go below 2 s (VRChat's rate limit, see
OSC_MIN_SEND_GAP_SEC).

Pure Python, no Qt - the timer lives in the window.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

#: the VRChat chatbox shows at most this many lines
MAX_LINES = 9
#: seconds per line - the window's spin box uses the same range
MIN_STEP_SEC = 2
MAX_STEP_SEC = 30

#: tooltip of the option - shared by the All in one card and the node
#: canvas (Advanced page)
SCROLL_TIP = (
    "Instead of swapping the whole text at once, the old string moves "
    "up one line at a time and the next one comes in from below \u2013 "
    "like the Star Wars intro.\nNeeds \u201cRotate strings\u201d. Every "
    "line step is one chatbox message, so 2 s is the fastest VRChat "
    "allows.")


class ScrollTransition:
    """One running crawl from the lines that were on screen to whatever
    the new string renders to. The new lines are passed in on every
    frame, so live values (clock, song time) keep updating while it
    scrolls."""

    def __init__(self):
        self.src = None
        self.step = 0

    @property
    def active(self) -> bool:
        return bool(self.src)

    def start(self, shown_lines) -> bool:
        """Begin a crawl away from `shown_lines` (what is on screen
        now). Nothing on screen = nothing to scroll away, so no crawl.
        Returns whether a crawl is running."""
        lines = [ln for ln in (shown_lines or [])]
        self.src = lines or None
        self.step = 0
        return self.active

    def stop(self) -> None:
        self.src = None
        self.step = 0

    def tick(self) -> bool:
        """One line further. Returns False once the new string is
        fully on screen (the crawl is over)."""
        if not self.active:
            return False
        self.step += 1
        if self.step >= len(self.src):
            self.stop()
            return False
        return True

    def window(self, new_lines, max_lines: int = MAX_LINES) -> list:
        """The lines to show for this frame."""
        new_lines = list(new_lines or [])
        if not self.active:
            return new_lines
        if new_lines == self.src:
            # same text again (one string on rotation) - nothing to do
            self.stop()
            return new_lines
        # the window keeps the height of the old text while it moves;
        # the last step (tick() -> False) shows the new text in full
        height = max(1, min(max_lines, len(self.src)))
        combined = self.src + new_lines
        return combined[self.step:self.step + height]
