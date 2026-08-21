"""
ui/miclevel.py - the bar that answers "is it hearing me?"

WHY A HAND-PAINTED WIDGET
-------------------------
A QProgressBar can show a number. It cannot show the one thing that
makes this useful: WHERE THE THRESHOLD IS. The whole question a person
has in front of a microphone setting is

    "my voice makes the bar move - but does it move far enough to count
     as speech, or is it going to sit there and transcribe nothing?"

and that is a comparison between two values on one scale, not a value.
So the bar carries a marker at the sensitivity threshold, the fill turns
the accent colour once it passes it, and a peak line hangs behind for a
moment so a short word does not vanish before the eye catches it.

THE SCALE
---------
dBFS, not linear RMS - see core/audiolevel.py:to_bar(). Normal speech is
1-3% of full scale, so a linear bar is a twitch at the far left and
nothing else. Both the level and the threshold marker go through the
same mapping, which is the only reason the comparison on screen means
what it looks like it means.

The widget owns no timer and no audio. It is given numbers and paints
them; the polling lives with whoever has the microphone
(ui/pages/textbox_page.py).
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import time

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from core import audiolevel

#: how long a peak stays visible after the sound that caused it. Long
#: enough to see a single word, short enough not to look stuck.
PEAK_HOLD = 0.8

#: nothing arrived for this long -> the meter is not live any more and
#: says so instead of showing a frozen last frame as if it were current
STALE_AFTER = 1.5


class LevelMeter(QWidget):
    """A horizontal input level bar with a sensitivity marker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self._level = 0.0          # RMS, 0 .. 32768
        self._peak = 0.0
        self._peak_at = 0.0
        self._threshold = 0.0      # RMS the input has to beat
        self._active = False
        self._at = 0.0
        self._tokens = {}
        self.setToolTip(
            "Input level of the selected device.\n\n"
            "The vertical line is the sensitivity threshold: everything "
            "to the left of it is treated as background noise, "
            "everything past it starts a phrase. Speak normally - the "
            "bar should clearly pass the line, and your quiet room "
            "should clearly stay behind it.")

    # ------------------------------------------------------------ input
    def apply_tokens(self, tokens):
        """Theme colours. Painted widgets are outside the stylesheet's
        reach, so they get handed the palette - same as the node canvas
        (see ui/mainwindow.py apply_theme)."""
        self._tokens = dict(tokens or {})
        self.update()

    def set_level(self, rms, peak=None, threshold=None):
        self._level = max(0.0, float(rms or 0.0))
        now = time.monotonic()
        self._at = now
        self._active = True
        value = max(self._level, float(peak or 0.0))
        if value >= self._peak or now - self._peak_at > PEAK_HOLD:
            self._peak = value
            self._peak_at = now
        if threshold is not None:
            self._threshold = max(0.0, float(threshold))
        self.update()

    def set_threshold(self, threshold):
        """Moves the marker without a level update - the slider dragging
        has to show where it is going while nothing is recording."""
        self._threshold = max(0.0, float(threshold or 0.0))
        self.update()

    def set_idle(self, keep_threshold=True):
        """Nothing is listening. The bar empties instead of freezing on
        the last frame, which would read as "still live, gone quiet"."""
        self._level = 0.0
        self._peak = 0.0
        self._active = False
        if not keep_threshold:
            self._threshold = 0.0
        self.update()

    def live(self):
        return self._active and (time.monotonic() - self._at) < STALE_AFTER

    def over_threshold(self):
        return self._threshold > 0 and self._level >= self._threshold

    # ----------------------------------------------------------- paint
    def _color(self, token, fallback):
        return QColor(self._tokens.get(token) or fallback)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(6.0, rect.height() / 2.0)

        painter.setPen(QPen(self._color("border", "#333947"), 1))
        painter.setBrush(self._color("inner", "#232833"))
        painter.drawRoundedRect(rect, radius, radius)

        inner = rect.adjusted(2, 2, -2, -2)
        if inner.width() <= 0:
            return

        live = self.live()
        fill = audiolevel.to_bar(self._level) if live else 0.0
        mark = audiolevel.to_bar(self._threshold) if self._threshold else 0.0

        if fill > 0:
            # Below the threshold the fill is deliberately grey: it is
            # audio the recogniser is going to ignore, and colouring it
            # the same as speech would make a bar full of fan noise look
            # like it is working.
            passing = self._threshold <= 0 or self._level >= self._threshold
            color = (self._color("accent", "#5b8dc9") if passing
                     else self._color("dim", "#7a8290"))
            bar = QRectF(inner)
            bar.setWidth(max(2.0, inner.width() * fill))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(bar, radius - 1, radius - 1)

        if live and self._peak > 0 and \
                time.monotonic() - self._peak_at < PEAK_HOLD:
            x = inner.left() + inner.width() * audiolevel.to_bar(self._peak)
            x = min(x, inner.right() - 1)
            painter.setPen(QPen(self._color("accent_hi", "#6d9cd4"), 2))
            painter.drawLine(int(x), int(inner.top()),
                             int(x), int(inner.bottom()))

        if mark > 0:
            x = inner.left() + inner.width() * mark
            pen = QPen(self._color("text", "#e5e9ef"), 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(x), int(rect.top() + 1),
                             int(x), int(rect.bottom() - 1))
        painter.end()
