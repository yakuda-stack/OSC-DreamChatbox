"""
ui/card_popout.py – a Textbox card in its own window (v1.7.5)

The pop-out button in the header of To Text and Two-way translation moves
the whole card into this window. It is not modal: the app keeps working
while it is open. Closing it (or the button again) puts the card back into
the page - the moving itself is done in ui/pages/textbox_page.py
(pop_card / dock_card).
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QDialog, QFrame, QScrollArea, QVBoxLayout

#: drawn on a 24x24 grid, the pixmap is twice that for sharp HiDPI
ICON_GRID = 24


def popout_icon(color, inward=False):
    """The "open in a window" icon: a box open at the top right corner
    and an arrow - pointing out of it (pop out) or into it (inward=True,
    back into the app). Transparent background, lines in `color`."""
    pix = QPixmap(ICON_GRID * 2, ICON_GRID * 2)
    pix.setDevicePixelRatio(2.0)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    box = QPainterPath(QPointF(12, 5))
    for x, y in ((5, 5), (5, 19), (19, 19), (19, 12)):
        box.lineTo(x, y)
    p.drawPath(box)
    if inward:
        tip, tail = QPointF(11, 13), QPointF(19, 5)
        head = ((11, 8), (11, 13), (16, 13))
    else:
        tip, tail = QPointF(19, 5), QPointF(11, 13)
        head = ((14, 5), (19, 5), (19, 10))
    p.drawLine(tail, tip)
    arrow = QPainterPath(QPointF(*head[0]))
    for x, y in head[1:]:
        arrow.lineTo(x, y)
    p.drawPath(arrow)
    p.end()
    return QIcon(pix)


class CardPopout(QDialog):
    def __init__(self, win, title):
        super().__init__(win)
        # styled in ui/ui_main.py (QDialog#popoutwin), follows the theme
        self.setObjectName("popoutwin")
        self.setWindowTitle(f"{title} – OSC-DreamChatbox")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self.scroll)

    def take(self, card):
        self.scroll.setWidget(card)

    def give_back(self):
        """The card, without the window owning it any more."""
        return self.scroll.takeWidget()
