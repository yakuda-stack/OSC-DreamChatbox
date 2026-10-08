"""
core/inputhistory.py – message history for the text fields (v1.6.6)

Arrow Up in the Chat / Text-to-Text field brings back the last sent
message, like a terminal. Arrow Down walks forward again and finally
restores whatever was typed before browsing started.

Pure Python on purpose (no Qt) so it can be unit-tested; the Qt glue
lives in ui/history_edit.py. Kept in memory only - nothing is written
to disk, the history is gone when the app closes.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

#: how many sent messages are remembered per field
MAX_HISTORY = 50


class InputHistory:
    """Newest entry last. `_pos` is None while not browsing, otherwise
    the index into `items` that is currently shown."""

    def __init__(self, limit: int = MAX_HISTORY):
        self.limit = max(1, int(limit))
        self.items: list[str] = []
        self._pos = None
        self._draft = ""

    def push(self, text: str) -> None:
        """Remember a sent message. Empty text and a repeat of the
        newest entry are skipped; browsing state is reset."""
        text = (text or "").strip()
        self._pos = None
        self._draft = ""
        if not text:
            return
        if self.items and self.items[-1] == text:
            return
        self.items.append(text)
        if len(self.items) > self.limit:
            del self.items[:len(self.items) - self.limit]

    def up(self, current: str = ""):
        """One step back in time. Returns the text to show, or None when
        there is nothing (older) to show."""
        if not self.items:
            return None
        if self._pos is None:
            self._draft = current
            self._pos = len(self.items) - 1
        elif self._pos > 0:
            self._pos -= 1
        else:
            return None
        return self.items[self._pos]

    def down(self):
        """One step forward. Past the newest entry the text that was
        typed before browsing comes back. None when not browsing."""
        if self._pos is None:
            return None
        if self._pos < len(self.items) - 1:
            self._pos += 1
            return self.items[self._pos]
        self._pos = None
        draft, self._draft = self._draft, ""
        return draft

    def reset(self) -> None:
        """Typing ends browsing - the next Up starts at the newest."""
        self._pos = None

    @property
    def browsing(self) -> bool:
        return self._pos is not None
