"""
core/backends/media_null.py – "nothing is playing" media backend

Stand-in for core/backends/media_linux.MediaFetcher on platforms without
a media source yet (currently Windows). ``fetch()`` always returns None,
which is the same answer the Linux backend gives when no MPRIS player is
running - so the Media Player card, the lyrics fetcher and the send
pipeline all behave like a paused desktop instead of hitting an error.

The real Windows source will be the SMTC (System Media Transport
Controls) via winsdk/winrt, which reports title, artist, position and
length for Spotify, browsers and most native players. That goes into
media_windows.py later; the factory in core/mediafetch.py then picks it.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from core.osinfo import OS_NAME

# kept so `from core.mediafetch import HAS_DBUS` keeps working everywhere
HAS_DBUS = False


class NullMediaFetcher:
    """API-compatible stand-in for MediaFetcher. Finds no player."""

    available = False
    name = "null"

    def __init__(self, log_fn):
        self.log = log_fn
        self.bus = None
        self._cached_player = None
        # API parity with the real backends: the UI sets these without
        # asking which platform it is on, and a stand-in that raises
        # AttributeError instead of ignoring them defeats the point of
        # having a stand-in.
        self.preferred = ""
        self.fallback = True
        self.log(f"MediaPlay: no media backend for {OS_NAME} yet - the "
                 f"Media Player card stays empty.")

    def fetch(self):
        """Would be {artist, title, position, length, player, playing}.
        None = nothing playing, exactly like the Linux backend reports
        when no MPRIS player is on the bus."""
        return None

    def list_sources(self):
        """No players, ever - so the dropdown shows Automatic and
        whatever was saved earlier, and nothing else."""
        return []
