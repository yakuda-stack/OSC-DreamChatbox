"""
core/mediafetch.py – now-playing info: picks the backend for this OS

The actual player queries live in core/backends/:

    media_linux.MediaFetcher          MPRIS over D-Bus (Spotify, browsers,
                                      VLC, YT Music, ...)
    media_windows.WindowsMediaFetcher GSMTC - the system media session
                                      Windows itself uses for the media
                                      keys and the volume flyout
    media_null.NullMediaFetcher       fetch() always returns None

Same pattern as core/hardware.py and core/translators.py: one name, one
contract (``fetch()`` -> dict | None), the platform decides which class
is behind it. Existing code keeps working unchanged:

    from core.mediafetch import MediaFetcher
    media = MediaFetcher(log)

The Windows backend needs a WinRT binding (see media_windows.py). If it
is not installed, that backend still constructs and simply reports
"nothing playing" - the same answer Linux gives when no MPRIS player is
on the bus - and ``status_note()`` says what to install.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math

from core.osinfo import IS_WINDOWS, OS_NAME
from core.backends.media_null import NullMediaFetcher

#: "mpris" / "gsmtc" / "null"
BACKEND_NAME = "null"
#: why we fell back, if we did
BACKEND_ERROR = ""

if IS_WINDOWS:
    HAS_DBUS = False
    try:
        from core.backends.media_windows import (  # noqa: F401
            HAS_WINRT, INSTALL_HINT, WindowsMediaFetcher as MediaFetcher,
            source_key as player_key, source_label as player_label)
        BACKEND_NAME = "gsmtc"
    except Exception as _e:
        # Must never stop the app from starting: an empty Media card is
        # survivable, a crash on launch is not.
        BACKEND_ERROR = f"{type(_e).__name__}: {_e}"
        MediaFetcher = NullMediaFetcher
        HAS_WINRT = False
        INSTALL_HINT = 'pip install "winrt-Windows.Media.Control[all]"'

        def player_key(name):
            return (name or "").strip().lower()

        def player_label(key):
            return key or "Unknown"
else:
    from core.backends.media_linux import (  # noqa: F401
        HAS_DBUS, MediaFetcher, source_key as player_key,
        source_label as player_label)
    BACKEND_NAME = "mpris"
    HAS_WINRT = False
    INSTALL_HINT = ""

#: True when a real player source exists on this platform
MEDIA_AVAILABLE = BACKEND_NAME != "null"


def fmt_volume(volume):
    """Player volume 0.0-1.0 -> "65%". None (not reported) -> None.

    Values above 1.0 exist (VLC goes to 125%) and are shown as they are.
    """
    if volume is None:
        return None
    try:
        return f"{round(max(0.0, float(volume)) * 100)}%"
    except (TypeError, ValueError):
        return None


def fmt_volume_db(volume):
    """Player volume as dB relative to 100%: 0.5 -> "-6.0 dB",
    1.0 -> "0.0 dB", 0 -> "-\u221e dB" (muted). None -> None.

    Treats the MPRIS value as a linear amplitude factor - which is what
    the spec suggests; a player that maps its slider differently gets a
    number that is close, not exact.
    """
    if volume is None:
        return None
    try:
        v = float(volume)
    except (TypeError, ValueError):
        return None
    if v <= 0.0:
        return "-\u221e dB"
    db = 20.0 * math.log10(v)
    # -0.0 would read oddly
    return f"{0.0 if abs(db) < 0.05 else db:.1f} dB"


def get_media_fetcher(log_fn):
    """Factory - use this in new code instead of the class directly."""
    return MediaFetcher(log_fn)


def backend_note() -> str:
    """One line the UI can show next to the Media Player card."""
    if BACKEND_ERROR:
        return (f"Media backend for {OS_NAME} failed to load "
                f"({BACKEND_ERROR}).")
    if not MEDIA_AVAILABLE:
        return f"Media player detection is not implemented on {OS_NAME} yet."
    if IS_WINDOWS and not HAS_WINRT:
        return ("Windows media bindings are missing - run:  " + INSTALL_HINT)
    return ""


def source_label() -> str:
    """Human name of the system service the values come from."""
    # Linux keeps the exact word it always had; the sentence this ends up
    # in already carries a closing bracket, so no nested parens here
    return {"mpris": "MPRIS",
            "gsmtc": "the Windows media session"}.get(
                BACKEND_NAME, "no system media service")


__all__ = ["MediaFetcher", "NullMediaFetcher", "MEDIA_AVAILABLE",
           "BACKEND_NAME", "BACKEND_ERROR", "HAS_DBUS", "HAS_WINRT",
           "INSTALL_HINT", "get_media_fetcher", "backend_note",
           "source_label", "player_key", "player_label",
           "fmt_volume", "fmt_volume_db"]
