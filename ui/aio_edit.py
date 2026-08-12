"""
ui/aio_edit.py - the multi-line editor behind every "AIO n:" field.

The AIO template language has always used a literal backslash-n as its
line break (see AppsPageMixin.build_aio_lines(), which splits on exactly
that). Typing "\\n" by hand works but reads nothing like the message it
produces, so this widget shows the string the way it will come out -
one visible line per chatbox line - and does the translation on the way
in and out:

    stored   "{text} \\n {artist} : {title}"
    shown    "{text} "
             " {artist} : {title}"

Nothing else in the app has to know: the config keeps the exact same
format it always had, so an existing setup, a plugin reading the
template and the Custom Box's {box_start} detection all keep working,
and a config written by this version still opens in an older one.

Two more things the old QLineEdit could not do:

* Shift+Enter (or Ctrl+Enter) inserts a line break. A bare Enter is
  swallowed on purpose - in a field that sits in a form next to nine
  others, Enter is far more often a reflex than an intention, and an
  accidental break in an AIO string is invisible until VRChat shows it.
* The field is three rows tall to start with and grows with the text.
  Dragging the bottom edge pins a height of your own; double-clicking
  it hands the field back to auto-growing.

Because the placeholder picker (ui/pages/placeholder_picker.py) and the
emoji popup (ui/ui_main.py) both drive their target through the
QLineEdit API, this class keeps that API - text(), setText(), insert(),
cursorPosition(), selectionStart(), selectedText(), maxLength() - so
neither of them needed a single change. The template-side accessors are
deliberately named differently: value()/setValue() speak the stored
form, text()/setText() the shown one, and mixing them up would be a
silently corrupted template.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QPlainTextEdit

#: what the template language uses as a line break - two characters,
#: backslash + n, not an escape. build_aio_lines() splits on this.
LINE_BREAK = "\\n"

#: Qt reports a line break inside a selection as this
PARAGRAPH_SEP = "\u2029"


def decode_template(stored):
    """Stored template -> what the user sees (real line breaks)."""
    if not stored:
        return ""
    return (str(stored).replace("\r\n", "\n")
            .replace(LINE_BREAK, "\n"))


def encode_template(shown):
    """What the user sees -> the stored template."""
    return (str(shown).replace(PARAGRAPH_SEP, "\n")
            .replace("\r\n", "\n")
            .replace("\n", LINE_BREAK))


class AioTextEdit(QPlainTextEdit):
    """Multi-line template field with a QLineEdit-shaped surface."""

    #: the stored template changed (already encoded)
    valueChanged = pyqtSignal(str)
    #: the user pinned a height by dragging, in px (0 = back to auto)
    heightChanged = pyqtSignal(int)

    MIN_ROWS = 3
    MAX_ROWS = 14
    #: how many px at the bottom edge start a drag-resize
    GRIP = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aioedit")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Tab belongs to the next field, not into the string
        self.setTabChangesFocus(True)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._max_len = 0
        self._last_value = ""
        self._guard = False       # programmatic change: do not report it
        self._tuning = False      # re-entry guard for the height maths
        self._manual_h = 0        # 0 = grow with the content
        self._drag_from = None
        self._drag_h = 0
        self.document().documentLayout().documentSizeChanged.connect(
            self._on_doc_resized)
        self.textChanged.connect(self._on_text_changed)
        self._retune_height()

    # ------------------------------------------------------- template side
    def value(self):
        """The template in its stored form."""
        return encode_template(self.toPlainText())

    def setValue(self, stored):
        """Loads a stored template. Does NOT emit valueChanged - this is
        the config painting the UI, not the user editing it."""
        shown = decode_template(stored)
        self._last_value = encode_template(shown)
        if shown == self.toPlainText():
            return
        self._guard = True
        self.setPlainText(shown)
        self._guard = False
        self._retune_height()

    def _on_text_changed(self):
        if self._guard:
            return
        value = encode_template(self.toPlainText())
        if self._max_len and len(value) > self._max_len:
            # Over budget: put the last accepted state back instead of
            # truncating. Cutting mid-placeholder would leave a "{gpu_pow"
            # that renders as nothing and looks like a broken field.
            pos = self.textCursor().position()
            self._guard = True
            self.setPlainText(decode_template(self._last_value))
            self._guard = False
            cur = self.textCursor()
            cur.setPosition(min(pos, len(self.toPlainText())))
            self.setTextCursor(cur)
            self._retune_height()
            return
        self._last_value = value
        self.valueChanged.emit(value)

    # ------------------------------------------------- QLineEdit surface
    # what the placeholder picker and the emoji popup talk to. All of it
    # works on the SHOWN text, because that is what the cursor positions
    # they hand around are counted in.
    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(str(text))

    def insert(self, text):
        self.insertPlainText(str(text))

    def cursorPosition(self):
        return self.textCursor().position()

    def setCursorPosition(self, pos):
        cur = self.textCursor()
        cur.setPosition(max(0, min(int(pos), len(self.toPlainText()))))
        self.setTextCursor(cur)

    def selectionStart(self):
        cur = self.textCursor()
        return cur.selectionStart() if cur.hasSelection() else -1

    def selectedText(self):
        cur = self.textCursor()
        if not cur.hasSelection():
            return ""
        return cur.selectedText().replace(PARAGRAPH_SEP, "\n")

    def maxLength(self):
        return self._max_len

    def setMaxLength(self, length):
        """Budget for the STORED string, so a line break costs the two
        characters it actually costs."""
        self._max_len = max(0, int(length))

    # --------------------------------------------------------- keyboard
    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            mods = ev.modifiers()
            if (mods & Qt.KeyboardModifier.ShiftModifier
                    or mods & Qt.KeyboardModifier.ControlModifier):
                self.insertPlainText("\n")
            # bare Enter does nothing - see the module docstring
            ev.accept()
            return
        super().keyPressEvent(ev)

    # ----------------------------------------------------------- height
    def manualHeight(self):
        return self._manual_h

    def setManualHeight(self, px):
        """Restores a pinned height (0 = grow with the content)."""
        self._manual_h = max(0, int(px))
        self._retune_height()

    def _row_px(self):
        return max(12, QFontMetrics(self.font()).lineSpacing())

    def _chrome_px(self):
        m = self.contentsMargins()
        return (m.top() + m.bottom() + 2 * self.frameWidth()
                + 2 * int(self.document().documentMargin()) + 8)

    def _height_for(self, rows):
        return int(self._row_px() * rows + self._chrome_px())

    def _on_doc_resized(self, *_):
        self._retune_height()

    def _retune_height(self):
        if self._tuning:
            return
        self._tuning = True
        try:
            min_h = self._height_for(self.MIN_ROWS)
            max_h = self._height_for(self.MAX_ROWS)
            if self._manual_h:
                height = self._manual_h
            else:
                # QPlainTextEdit uses QPlainTextDocumentLayout, whose
                # documentSize().height() is a count of VISUAL lines
                # (wrapping included), not a pixel height - which is
                # exactly the number wanted here.
                rows = int(self.document().size().height()) or 1
                height = self._height_for(rows)
            height = max(min_h, min(max_h, height))
            if height != self.height():
                self.setFixedHeight(height)
        finally:
            self._tuning = False

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._retune_height()

    # ------------------------------------------------------ drag to size
    def _in_grip(self, pos):
        return pos.y() >= self.viewport().height() - self.GRIP

    def mousePressEvent(self, ev):
        if (ev.button() == Qt.MouseButton.LeftButton
                and self._in_grip(ev.position().toPoint())):
            self._drag_from = ev.globalPosition().toPoint().y()
            self._drag_h = self.height()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_from is not None:
            delta = ev.globalPosition().toPoint().y() - self._drag_from
            self._manual_h = max(1, self._drag_h + delta)
            self._retune_height()
            ev.accept()
            return
        self.viewport().setCursor(
            Qt.CursorShape.SizeVerCursor
            if self._in_grip(ev.position().toPoint())
            else Qt.CursorShape.IBeamCursor)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._drag_from is not None:
            self._drag_from = None
            self._manual_h = self.height()
            self.heightChanged.emit(self._manual_h)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if self._in_grip(ev.position().toPoint()):
            self._manual_h = 0
            self._retune_height()
            self.heightChanged.emit(0)
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        # the two little lines that say "this edge can be dragged"
        painter = QPainter(self.viewport())
        pen = QPen(QColor("#4a5160"))
        pen.setWidth(1)
        painter.setPen(pen)
        mid = self.viewport().width() // 2
        bottom = self.viewport().height()
        for offset in (3, 6):
            painter.drawLine(mid - 9, bottom - offset,
                             mid + 9, bottom - offset)
        painter.end()
