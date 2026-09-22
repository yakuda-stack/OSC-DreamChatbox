"""
core/qtstub.py - stand-ins for QtWidgets and QtGui in terminal mode.

Why this exists
---------------
Terminal mode (``--headless``, see core/headless.py) runs the very same
MainWindow code as the normal app - the same send loop, the same payload
builder, the same pollers and plugins. Writing a second copy of all that
without Qt would mean two implementations that drift apart with every
release.

What costs memory is not QtCore (timers, signals, D-Bus) but QtWidgets
and QtGui: the widget tree, fonts, the GPU/raster backend, the style.
So terminal mode keeps the REAL QtCore and QtDBus and swaps only these
two modules for the stand-ins below before anything imports them.

How the stand-ins behave
------------------------
Every name looked up in the fake modules (QLabel, QPushButton, QFont,
QIcon, ...) is a class derived from ``Null``. A ``Null``:

* accepts any constructor arguments,
* answers every attribute and method call with another ``Null``,
* is falsy, empty, zero and "" in every context.

That makes ``build_ui()`` run through without drawing anything, and a
widget read that slipped into the logic reads as "off / empty" instead
of crashing. Widget classes are real QObjects, because MainWindow needs
a QObject base for its signals and QTimer(self) needs a QObject parent.

Only install() these in a process that never shows a window.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import sys
import types

from PyQt6.QtCore import QObject

#: the modules replaced by install(); everything else stays real
STUBBED = ("PyQt6.QtWidgets", "PyQt6.QtGui", "PyQt6.QtSvg",
           "PyQt6.QtSvgWidgets")


class _NullMeta(type(QObject)):
    """Class-level lookups (enums like QSizePolicy.Policy.Expanding,
    static calls like QApplication.instance()) land here."""

    def __getattr__(cls, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _NULL


class Null(QObject, metaclass=_NullMeta):
    """A widget/value that absorbs everything and does nothing."""

    def __init__(self, *args, **kwargs):
        # never hand the arguments to QObject: a "parent" here is just
        # another Null, and ownership does not matter for fakes
        QObject.__init__(self)

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _NULL

    def __call__(self, *args, **kwargs):
        return _NULL

    # --- behaves like "nothing" in every value context -------------
    def __bool__(self):
        return False

    def __len__(self):
        return 0

    def __iter__(self):
        return iter(())

    def __contains__(self, item):
        return False

    def __getitem__(self, key):
        return _NULL

    def __setitem__(self, key, value):
        pass

    def __int__(self):
        return 0

    def __index__(self):
        return 0

    def __float__(self):
        return 0.0

    def __str__(self):
        return ""

    def __repr__(self):
        return "<qtstub.Null>"

    def __format__(self, spec):
        return ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __eq__(self, other):
        return other is self

    def __hash__(self):
        return id(self)

    def __lt__(self, other):
        return False

    __le__ = __gt__ = __ge__ = __lt__

    def _self(self, *other):
        return self

    # every operator Python has: drawing code does geometry on widget
    # positions (abs(p2.x() - p1.x()), round(w / 2), ...) - found the
    # hard way with abs() on a real Advanced-mode canvas
    __add__ = __radd__ = __sub__ = __rsub__ = _self
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _self
    __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = _self
    __pow__ = __rpow__ = __matmul__ = __rmatmul__ = _self
    __lshift__ = __rlshift__ = __rshift__ = __rrshift__ = _self
    __or__ = __ror__ = __and__ = __rand__ = __xor__ = __rxor__ = _self
    __neg__ = __pos__ = __invert__ = __abs__ = _self
    __iadd__ = __isub__ = __imul__ = __itruediv__ = __ior__ = _self
    __iand__ = __ixor__ = __ifloordiv__ = __imod__ = _self

    def __round__(self, ndigits=None):
        return 0

    def __trunc__(self):
        return 0

    __floor__ = __ceil__ = __trunc__

    def __divmod__(self, other):
        return (self, self)

    __rdivmod__ = __divmod__


def _noop(self, *args, **kwargs):
    return _NULL


# ``super().closeEvent(ev)`` does not go through __getattr__ - super()
# only looks in the class dictionaries. So every Qt method the ui code
# reaches through super() has to exist here for real.
for _name in ("closeEvent", "showEvent", "hideEvent", "resizeEvent",
              "paintEvent", "keyPressEvent", "keyReleaseEvent",
              "mousePressEvent", "mouseReleaseEvent", "mouseMoveEvent",
              "mouseDoubleClickEvent", "wheelEvent", "focusInEvent",
              "focusOutEvent", "enterEvent", "leaveEvent",
              "dragEnterEvent", "dragMoveEvent", "dropEvent",
              "contextMenuEvent", "changeEvent", "itemChange", "paint",
              "sizeHint", "minimumSizeHint", "translate"):
    setattr(Null, _name, _noop)
del _name

#: the one shared "nothing" returned by every call and attribute
_NULL = Null()


class _FakeModule(types.ModuleType):
    """``from PyQt6.QtWidgets import QLabel`` gets a fresh Null subclass
    named QLabel - a subclass, so ``class MyWidget(QWidget)`` and
    ``isinstance`` keep working."""

    def __init__(self, name):
        super().__init__(name)
        self.__file__ = "<qtstub>"
        self.__path__ = []          # lets "import PyQt6.QtGui.x" resolve
        self._classes = {}

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        cls = self._classes.get(name)
        if cls is None:
            cls = _NullMeta(name, (Null,), {"__module__": self.__name__})
            self._classes[name] = cls
        return cls


def install():
    """Replace QtWidgets/QtGui (and friends) for this process. Must run
    before ANY ui module is imported. Returns False if one of them was
    already imported for real - then it is too late to swap them."""
    import PyQt6
    if any(name in sys.modules and not isinstance(sys.modules[name],
                                                  _FakeModule)
           for name in STUBBED):
        return False
    for name in STUBBED:
        mod = _FakeModule(name)
        sys.modules[name] = mod
        setattr(PyQt6, name.rsplit(".", 1)[1], mod)
    return True


def is_installed():
    return isinstance(sys.modules.get("PyQt6.QtWidgets"), _FakeModule)
