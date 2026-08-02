"""
core/mediafetch.py – now-playing info: picks the backend for this OS

The actual player queries live in core/backends/:

    media_linux.MediaFetcher       MPRIS over D-Bus (Spotify, browsers,
                                   VLC, YT Music, ...)
    media_null.NullMediaFetcher    fetch() always returns None

Same pattern as core/hardware.py and core/translators.py: one name, one
contract (``fetch()`` -> dict | None), the platform decides which class
is behind it. Existing code keeps working unchanged:

    from core.mediafetch import MediaFetcher
    media = MediaFetcher(log)

On Windows the null backend answers "nothing playing", which the Media
Player card and the lyrics fetcher already handle - it is the same answer
Linux gives when no player is running.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from core.osinfo import IS_WINDOWS, OS_NAME
from core.backends.media_null import NullMediaFetcher

if IS_WINDOWS:
    # No SMTC/winrt backend yet - drop in core/backends/media_windows.py
    # and import it here when it exists.
    MediaFetcher = NullMediaFetcher
    HAS_DBUS = False
else:
    from core.backends.media_linux import HAS_DBUS, MediaFetcher  # noqa: F401

#: True when a real player source exists on this platform
MEDIA_AVAILABLE = not IS_WINDOWS
BACKEND_NAME = "mpris" if MEDIA_AVAILABLE else "null"


def get_media_fetcher(log_fn):
    """Factory - use this in new code instead of the class directly."""
    return MediaFetcher(log_fn)


def backend_note() -> str:
    """One line the UI can show next to the Media Player card."""
    if MEDIA_AVAILABLE:
        return ""
    return f"Media player detection is not implemented on {OS_NAME} yet."


__all__ = ["MediaFetcher", "NullMediaFetcher", "MEDIA_AVAILABLE",
           "BACKEND_NAME", "HAS_DBUS", "get_media_fetcher", "backend_note"]
