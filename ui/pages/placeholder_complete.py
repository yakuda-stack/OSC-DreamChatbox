"""
ui/pages/placeholder_complete.py - typing "{har" offers the names

The "+" menu (ui/pages/placeholder_picker.py) answers "what is there";
this answers "I know roughly what it is called". Once a name is in your
fingers, opening a menu, finding the folder and clicking an entry is
slower than typing four letters - but four letters only work if you
remember whether it was {hmd_battery} or {battery_hmd}, and nobody does
for four hundred names.

So: type an opening brace and at least one character, and a list drops
under the cursor. Enter or a click completes the whole name, closing
brace included; typing on narrows the list; Escape makes it go away and
never come back for that word.

Design notes:

* The list is fed by the SAME index the picker's search line uses
  (PlaceholderPickerMixin._picker_entries), so a field that can resolve
  a name can complete it, and one that cannot never offers it. A plugin
  installed while the field is open shows up on the next keystroke,
  because the index is rebuilt per fragment rather than cached.

* Ranking is prefix first, then anywhere in the name, then the
  description - "{bat" should reach {hmd_battery} without knowing that
  the world stats plugin calls it that, but a description hit must not
  push a literal name match down the list.

* Nothing pops up while the field does not have the focus. Loading the
  config sets every template field, and a popup appearing under a widget
  the user is not typing in is a UI bug, not a feature.

* The widget only has to look like a QLineEdit (text/setText/
  cursorPosition/setCursorPosition/maxLength), which is exactly the
  surface AioTextEdit already grew for the picker - so the AIO fields,
  the Hardware and Media custom strings and a plugin's own string all
  take the same object.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QCompleter

#: the word being typed: an opening brace plus name characters, ending
#: at the cursor. A closed "{gpu_usage}" cannot match - the brace is not
#: in the character class - so completion stops on its own.
FRAGMENT_RE = re.compile(r"\{[A-Za-z0-9_]*$")

#: how many characters after the brace before the list appears. One is
#: enough to cut four hundred names down to something readable; zero
#: would drop the entire vocabulary on you for pressing "{".
MIN_CHARS = 1

#: entries in the drop-down. More than this and it is a menu again.
MAX_ITEMS = 12

#: how a name is told apart from its description in a row label. The
#: picker spells its labels the same way (see _add_items).
LABEL_SEP = "   "

POPUP_STYLE = (
    "QListView { background: #14161c; border: 1px solid #333947;"
    " border-radius: 6px; color: #d7dae0; padding: 2px;"
    " outline: none; }"
    "QListView::item { padding: 3px 8px; border-radius: 4px; }"
    "QListView::item:selected { background: #2b3242; color: #ffffff; }"
)


def fragment_at(text, cursor):
    """(start, fragment) for the placeholder being typed, or None.

    `cursor` is a position in `text`; everything behind it is ignored,
    so completing in the middle of a line works the same as at the end.
    """
    head = text[:max(0, min(int(cursor), len(text)))]
    match = FRAGMENT_RE.search(head)
    if not match:
        return None
    frag = match.group(0)
    if len(frag) - 1 < MIN_CHARS:
        return None
    return match.start(), frag


class PlaceholderCompleter(QObject):
    """Attaches inline placeholder completion to one template field."""

    def __init__(self, edit, provider, log=None):
        """`provider()` returns the picker's entry tuples
        [(payload, name, note, path, source_key), ...]."""
        super().__init__(edit)
        self.edit = edit
        self.provider = provider
        self.log = log
        self._dismissed = None      # fragment the user pressed Escape on
        self._busy = False          # our own edit, not the user's typing

        self.model = QStandardItemModel(self)
        self.completer = QCompleter(self.model, edit)
        self.completer.setWidget(edit)
        # The list is filtered by us, not by Qt: Qt would only ever match
        # on the display string, which carries the description and the
        # group as well, so "{bat" would hit every row that mentions a
        # battery anywhere in its text.
        self.completer.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        popup = self.completer.popup()
        popup.setStyleSheet(POPUP_STYLE)
        popup.setUniformItemSizes(False)
        popup.installEventFilter(self)
        if hasattr(edit, "setCompleterPopup"):
            # a field that handles Return itself has to stand back while
            # the list is open - see AioTextEdit.setCompleterPopup()
            edit.setCompleterPopup(popup)
        self.completer.activated[str].connect(self._accept)
        edit.textChanged.connect(self._on_text_changed)

    # ------------------------------------------------------------------
    def _state(self):
        return self.edit.text(), self.edit.cursorPosition()

    def _on_text_changed(self, *_):
        if self._busy:
            return
        if not self.edit.hasFocus():
            # the config painting the field, or the picker inserting -
            # neither is somebody typing a name
            return
        text, cursor = self._state()
        found = fragment_at(text, cursor)
        if found is None:
            self._dismissed = None
            self._hide()
            return
        _start, frag = found
        if self._dismissed is not None and frag.startswith(self._dismissed):
            # Escape means "not this word". Deleting back past the point
            # it was pressed starts a new word and arms it again.
            return
        self._dismissed = None
        hits = self._hits(frag)
        if not hits:
            self._hide()
            return
        self._show(hits)

    def _hits(self, frag):
        body = frag[1:].lower()
        seen = set()
        ranked = []
        for entry in self.provider() or ():
            payload, name, note, path, _key = entry
            if not isinstance(payload, str) or not name.startswith("{"):
                # wrappers like {sup}…{/sup} are a selection tool, not a
                # value - completing one would drop half a tag into the
                # middle of a word
                continue
            low = name.lower()
            if low.startswith(frag.lower()):
                rank = 0
            elif body in low:
                rank = 1
            elif len(body) >= 3 and body in (note or "").lower():
                rank = 2
            else:
                continue
            if name in seen:
                continue
            seen.add(name)
            ranked.append((rank, len(name), len(ranked), name, note, path))
        # shortest first inside a rank: {time} before {time_status} when
        # both start with what was typed
        ranked.sort(key=lambda r: (r[0], r[1], r[2]))
        return ranked[:MAX_ITEMS]

    def _show(self, hits):
        self.model.clear()
        for _rank, _len, _idx, name, note, path in hits:
            label = f"{name}{LABEL_SEP}\u2013  {note}" if note else name
            if path:
                label += f"      \u00b7  {path}"
            self.model.appendRow(QStandardItem(label))
        popup = self.completer.popup()
        popup.setCurrentIndex(self.model.index(0, 0))
        rect = self._popup_rect(popup)
        if rect is not None:
            self.completer.complete(rect)
        else:
            self.completer.complete()

    def _popup_rect(self, popup):
        """Where the list should hang: under the caret for a multi-line
        field, under the whole field for a one-line one (a QLineEdit does
        not hand out its caret rectangle)."""
        if not hasattr(self.edit, "cursorRect"):
            return None
        try:
            rect = self.edit.cursorRect()
        except TypeError:
            return None
        width = popup.sizeHintForColumn(0) + 24
        rect.setWidth(max(240, min(width, 620)))
        return rect

    def _hide(self):
        popup = self.completer.popup()
        if popup is not None and popup.isVisible():
            popup.hide()

    def _accept(self, label):
        """Puts the picked name in place of the fragment."""
        name = label.split(LABEL_SEP)[0].strip()
        if not name:
            return
        text, cursor = self._state()
        found = fragment_at(text, cursor)
        if found is None:
            return
        start, frag = found
        end = cursor
        if text[end:end + 1] == "}":
            # somebody typed the closing brace first and went back into
            # the word - completing would otherwise leave "{gpu_usage}}"
            end += 1
        new = text[:start] + name + text[end:]
        limit = self.edit.maxLength()
        if limit and len(new) > limit:
            if self.log:
                self.log(f"Completion: no room left for {name} \u2013 the "
                         f"field is limited to {limit} characters.")
            return
        self._busy = True
        try:
            self.edit.setText(new)
            self.edit.setCursorPosition(start + len(name))
        finally:
            self._busy = False
        self.edit.setFocus()

    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        """Escape closes the list for this word.

        The completer's popup owns the keyboard while it is up, so this
        filter sits on the popup rather than on the field.
        """
        if event.type() == QEvent.Type.KeyPress and \
                event.key() == Qt.Key.Key_Escape:
            text, cursor = self._state()
            found = fragment_at(text, cursor)
            self._dismissed = found[1] if found else None
        return super().eventFilter(obj, event)
