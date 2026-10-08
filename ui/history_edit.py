"""
ui/history_edit.py – Arrow Up / Down history for a QLineEdit (v1.6.6)

    hist = attach_history(line_edit)
    ...
    hist.push(text)          # after the message was sent

The logic is in core/inputhistory.py; this file only listens for the
two arrow keys.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from PyQt6.QtCore import QEvent, QObject, Qt

from core.inputhistory import InputHistory


class _HistoryFilter(QObject):
    def __init__(self, edit, history):
        super().__init__(edit)
        self.edit = edit
        self.history = history
        self._setting = False
        edit.textEdited.connect(self._on_edited)

    def _on_edited(self, _text):
        # typed by hand -> leave browse mode
        if not self._setting:
            self.history.reset()

    def _show(self, text):
        self._setting = True
        try:
            self.edit.setText(text)
            self.edit.end(False)
        finally:
            self._setting = False

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
                return False
            if key == Qt.Key.Key_Up:
                text = self.history.up(self.edit.text())
                if text is not None:
                    self._show(text)
                return True
            if key == Qt.Key.Key_Down:
                text = self.history.down()
                if text is not None:
                    self._show(text)
                return True
        return False


def attach_history(edit, history=None) -> InputHistory:
    """Installs the arrow-key history on `edit` and returns the
    InputHistory to push sent messages into."""
    history = history or InputHistory()
    flt = _HistoryFilter(edit, history)
    edit.installEventFilter(flt)
    edit._history_filter = flt      # keep a reference
    edit.setToolTip((edit.toolTip() + "\n" if edit.toolTip() else "")
                    + "↑ / ↓: previous messages")
    return history
