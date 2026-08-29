"""
ui/nowheel.py - the mouse wheel stops changing values it is scrolled over.

Qt's default is that a QComboBox, a QSpinBox and a QSlider all answer the
wheel. On a form that is one screen tall that is fine; on the Apps page,
which is several screens of cards inside a scroll area, it means every
scroll that happens to pass over the Personal Status template dropdown,
the Hardware sensor list or the rotation interval silently changes a
setting on the way past. The value that got changed is usually off the
screen by the time the scrolling stops, so the first sign of it is
VRChat showing the wrong thing.

So those three widget kinds no longer take the wheel at all: the event is
handed on to whatever they sit in, which is the scroll area, and the page
scrolls the way it was meant to. Everything else about them is unchanged
- click, arrow keys, typing into a spin box, dragging a slider, and the
wheel INSIDE an open dropdown list all work as before, because an open
list is a popup of its own and the event never reaches the combo box.

Installed once on the QApplication (see osc_dreamchatbox.py), so it also
covers widgets built later - dialogs, plugin panels, node blocks - with
nothing for them to remember to do.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from PyQt6.QtCore import QEvent, QObject, QPointF
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QSlider

#: the value widgets that sit in scrollable pages. QScrollBar is a
#: QAbstractSlider but NOT a QSlider, so scroll bars keep working.
GUARDED = (QComboBox, QAbstractSpinBox, QSlider)


def _scroll_target(widget):
    """The viewport of the nearest scrollable ancestor, or None."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent.viewport()
        parent = parent.parentWidget()
    return None


class WheelGuard(QObject):
    """Application-wide event filter: no wheel on GUARDED widgets."""

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.Wheel or not isinstance(obj, GUARDED):
            return False
        if isinstance(obj, QComboBox):
            # the popup is a window of its own, so this practically never
            # fires - but a style that routes the list's wheel back to
            # the combo would otherwise make the open list unscrollable
            view = obj.view()
            if view is not None and view.isVisible():
                return False
        target = _scroll_target(obj)
        if target is not None:
            # handed on by hand rather than left to Qt's parent walk: the
            # walk stops at the first widget that accepts the event, and
            # which widget that is depends on how the card was built.
            # Sending it straight at the viewport scrolls the page every
            # time, no matter how deeply the field is nested.
            QApplication.sendEvent(target, self._retarget(ev, target))
            return True
        # nothing to scroll (a dialog, say): swallow it and leave the
        # value alone
        ev.ignore()
        return True

    @staticmethod
    def _retarget(ev, target):
        """The same wheel event, positioned over the scroll area."""
        pos = QPointF(target.mapFromGlobal(ev.globalPosition().toPoint()))
        return QWheelEvent(pos, ev.globalPosition(),
                           ev.pixelDelta(), ev.angleDelta(),
                           ev.buttons(), ev.modifiers(),
                           ev.phase(), ev.inverted())


def install(app):
    """Puts the guard on the application. Returns it - the QApplication
    is its parent, so the caller does not have to keep it alive.

    The filter is taken off again on aboutToQuit, and that is not
    cosmetic: an application-wide filter that is still installed while
    Python and Qt tear each other down at exit segfaults reliably (any
    filter does, an empty one included - it is a shutdown ordering
    problem, not this class). Removing it one step earlier makes the
    quit clean.
    """
    guard = WheelGuard(app)
    app.installEventFilter(guard)
    app.aboutToQuit.connect(lambda: app.removeEventFilter(guard))
    return guard
