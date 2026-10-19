# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later
"""A layout that wraps its items onto the next line (v1.6.9).

A QHBoxLayout full of buttons has a hard minimum width - the sum of all
buttons. Inside a page that scrolls, that minimum turned into a
horizontal scrollbar as soon as the window got a bit narrower. This
layout puts whatever no longer fits on the next line instead, so the
page only ever scrolls vertically.

Drop-in for the button rows: addWidget / addLayout / addSpacing /
addStretch / setSpacing work like on a QHBoxLayout. Stretches and
spacings are ignored - a row that wraps has no "end" to push against.
"""

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=8, v_spacing=None):
        super().__init__(parent)
        self._items = []
        self._h = spacing
        self._v = spacing if v_spacing is None else v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    # -- QHBoxLayout-style API -----------------------------------------
    def setSpacing(self, spacing):
        self._h = self._v = spacing
        self.invalidate()

    def spacing(self):
        return self._h

    def addStretch(self, *_args):
        """No-op, see the module docstring."""

    def addSpacing(self, *_args):
        """No-op, see the module docstring."""

    def addLayout(self, layout, *_args):
        """A sub-layout travels as one piece (a label with its spin box,
        for instance), so it is wrapped in a plain widget."""
        holder = QWidget()
        holder.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        self.addWidget(holder)

    def addWidget(self, widget, *_args, **_kw):
        # spelled out instead of super(): terminal mode swaps QLayout for
        # a stand-in (core/qtstub.py) that only answers class lookups
        QLayout.addWidget(self, widget)

    # -- QLayout -------------------------------------------------------
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        QLayout.setGeometry(self, rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        # one line, everything side by side - what the row asks for when
        # there is room
        w, h = 0, 0
        for item in self._visible():
            s = item.sizeHint()
            w += s.width() + (self._h if w else 0)
            h = max(h, s.height())
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def minimumSize(self):
        # the widest single item - anything else can go on its own line
        size = QSize()
        for item in self._visible():
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    # -- internals -----------------------------------------------------
    def _visible(self):
        out = []
        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            out.append(item)
        return out

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for item in self._visible():
            hint = item.sizeHint()
            # an item wider than the whole row (a long status label)
            # gets the row and grows downwards if it can
            w = min(hint.width(), max(item.minimumSize().width(),
                                      area.width()))
            h = hint.height()
            if item.hasHeightForWidth():
                h = max(h if w == hint.width() else 0,
                        item.heightForWidth(w))
            if x > area.x() and x + w > area.right() + 1:
                x = area.x()
                y += line_h + self._v
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x += w + self._h
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()

