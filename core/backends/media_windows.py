"""
core/backends/media_windows.py – now-playing on Windows via GSMTC

Windows' counterpart to MPRIS is the Global System Media Transport
Controls (GSMTC): the same system service that draws the media flyout on
the volume overlay and reacts to the media keys. Everything that
registers there shows up here - Spotify, Apple Music, VLC, foobar2000,
and any tab in Chrome/Edge/Firefox that plays audio or video.

    winrt.windows.media.control.GlobalSystemMediaTransportControlsSessionManager

WHICH PACKAGE
-------------
Two Python bindings expose it:

  * PyWinRT (preferred) - `winrt-Windows.Media.Control`, actively
    maintained, wheels up to Python 3.14
  * winsdk (legacy)     - the older single package, wheels only up to
    Python 3.12

This module tries PyWinRT first and falls back to winsdk, so both work.
If neither is installed, nothing breaks: fetch() returns None exactly
like the null backend, and status_note() tells the user what to install.

THREADING
---------
WinRT objects have COM apartment affinity, and the API is asynchronous.
Rather than spinning up an event loop on whichever worker thread happens
to call fetch(), this backend owns ONE daemon thread that holds the
apartment, runs one asyncio loop, and refreshes a snapshot once a second.
fetch() then just copies that snapshot - it never blocks and never
touches a WinRT object from a foreign thread.

POSITION IS A SNAPSHOT, NOT A CLOCK
-----------------------------------
This is the detail that gets media integrations wrong. GSMTC does not
update `position` continuously: Spotify writes it on play, pause, seek
and track change, and nothing in between. Read naively, a song bar
freezes for minutes and then jumps. So the timeline carries
`last_updated_time`, and the live position is

    position + (now - last_updated_time)      ... while playing

which is what extrapolation below does, clamped to the track length.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import datetime
import threading
import time

# ------------------------------------------------------------ bindings
_BINDING = ""
_MediaManager = None
_init_apartment = None

for _mod, _name in (("winrt.windows.media.control", "winrt"),
                    ("winsdk.windows.media.control", "winsdk")):
    try:
        _m = __import__(_mod, fromlist=["*"])
        _MediaManager = getattr(
            _m, "GlobalSystemMediaTransportControlsSessionManager")
        _BINDING = _name
        break
    except Exception:
        continue

if _BINDING:
    # PyWinRT wants the COM apartment initialised on the thread that
    # touches WinRT objects; winsdk does it implicitly. Both are wrapped
    # because the helper moved between modules across versions.
    for _path in ("winrt.runtime", "winrt.system", "winsdk.system"):
        try:
            _r = __import__(_path, fromlist=["*"])
            _init_apartment = getattr(_r, "init_apartment", None)
            if _init_apartment:
                break
        except Exception:
            continue

HAS_WINRT = _MediaManager is not None

INSTALL_HINT = ('pip install "winrt-Windows.Media.Control[all]"')

#: GlobalSystemMediaTransportControlsSessionPlaybackStatus
_STATUS_PLAYING = 4
_STATUS_PAUSED = 5

#: how often the worker thread asks Windows for a fresh snapshot
_POLL_SEC = 1.0
#: a last_updated_time further from now than this is not trustworthy,
#: so we do not extrapolate from it (some players never set it)
_MAX_EXTRAPOLATE_SEC = 900.0

# source_app_user_model_id is an AUMID, not a name. The opaque ones are
# worth mapping; everything else is cleaned up generically below.
_APP_NAMES = {
    "spotify.exe": "Spotify",
    "308046b0af4a39cb": "Firefox",          # Mozilla's AUMID
    "6f193ccc56814779": "Firefox",          # Firefox ESR/dev builds
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
    "vivaldi.exe": "Vivaldi",
    "zen.exe": "Zen Browser",
    "vlc.exe": "VLC",
    "mpc-hc64.exe": "MPC-HC",
    "foobar2000.exe": "foobar2000",
    "musicbee.exe": "MusicBee",
    "aimp.exe": "AIMP",
    "itunes.exe": "iTunes",
    "microsoft.zunemusic": "Groove Music",
    "microsoft.zunevideo": "Films & TV",
}


def _pretty_player(aumid: str) -> str:
    """AUMID -> something a human wants to read in a chatbox."""
    raw = (aumid or "").strip()
    if not raw:
        return "Unknown"
    key = raw.lower()
    if key in _APP_NAMES:
        return _APP_NAMES[key]
    # packaged apps look like  AppleInc.AppleMusicWin_nzyj5cx40ttqa!App
    if "!" in raw:
        pkg = raw.split("!", 1)[0]
        pkg = pkg.split("_", 1)[0]              # drop the publisher hash
        name = pkg.split(".")[-1] or pkg
        for probe, pretty in (("applemusic", "Apple Music"),
                              ("spotify", "Spotify"),
                              ("zunemusic", "Groove Music")):
            if probe in name.lower():
                return pretty
        return name
    if key.endswith(".exe"):
        return raw[:-4]
    return raw


def _seconds(value):
    """TimeSpan -> float seconds.

    PyWinRT hands back a datetime.timedelta; older bindings hand back raw
    100-nanosecond ticks. Accept both rather than betting on a version.
    """
    if value is None:
        return 0.0
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    try:
        return float(value) / 1e7
    except (TypeError, ValueError):
        return 0.0


def _status_value(status):
    """Playback status enum -> int, whatever shape the binding uses."""
    for attr in ("value", "_value_"):
        v = getattr(status, attr, None)
        if isinstance(v, int):
            return v
    try:
        return int(status)
    except (TypeError, ValueError):
        return -1


class WindowsMediaFetcher:
    """Same API as core/backends/media_linux.MediaFetcher."""

    available = True
    name = "gsmtc"

    def __init__(self, log_fn):
        self.log = log_fn
        self.bus = None                 # API parity with the Linux backend
        self._cached_player = None
        self._lock = threading.Lock()
        self._snap = None               # last raw reading, or None
        self._thread = None
        self._stop = threading.Event()
        self._error = ""
        self._logged_error = ""

        if not HAS_WINRT:
            self.log("MediaPlay: the Windows media bindings are missing - "
                     f"install them with:  {INSTALL_HINT}")
            return
        self.log(f"MediaPlay: Windows GSMTC backend ({_BINDING} bindings).")
        self._start()

    # ------------------------------------------------------------ thread
    def _start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="gsmtc-poller", daemon=True)
        self._thread.start()

    def close(self):
        """Optional: stop the poller. The thread is a daemon, so an app
        that just exits is fine too."""
        self._stop.set()

    def _run(self):
        import asyncio
        if _init_apartment is not None:
            try:
                _init_apartment()
            except Exception:
                pass                    # already initialised is fine
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        backoff = _POLL_SEC
        try:
            while not self._stop.is_set():
                try:
                    snap = loop.run_until_complete(self._read_async())
                    with self._lock:
                        self._snap = snap
                        self._error = ""
                    backoff = _POLL_SEC
                except Exception as e:
                    with self._lock:
                        self._snap = None
                        self._error = f"{type(e).__name__}: {e}"
                    # log once per distinct error, not once per second
                    if self._error != self._logged_error:
                        self._logged_error = self._error
                        self.log(f"MediaPlay: GSMTC read failed ({self._error})")
                    # a failing session manager usually stays failing for a
                    # while - stop hammering it
                    backoff = min(backoff * 2, 15.0)
                self._stop.wait(backoff)
        finally:
            try:
                loop.close()
            except Exception:
                pass

    # ----------------------------------------------------------- reading
    async def _read_async(self):
        mgr = await _MediaManager.request_async()

        # Mirror the Linux backend's choice: a player that is actually
        # playing wins; otherwise fall back to whatever Windows considers
        # current, so a paused song still shows.
        chosen = None
        try:
            sessions = list(mgr.get_sessions() or [])
        except Exception:
            sessions = []
        for s in sessions:
            try:
                if _status_value(s.get_playback_info().playback_status) \
                        == _STATUS_PLAYING:
                    chosen = s
                    break
            except Exception:
                continue
        if chosen is None:
            try:
                chosen = mgr.get_current_session()
            except Exception:
                chosen = None
        if chosen is None:
            return None

        try:
            props = await chosen.try_get_media_properties_async()
        except Exception:
            props = None
        title = (getattr(props, "title", "") or "") if props else ""
        artist = (getattr(props, "artist", "") or "") if props else ""
        if not title and not artist:
            # a session with no metadata is not worth showing - same rule
            # the MPRIS backend applies
            return None

        try:
            status = _status_value(chosen.get_playback_info().playback_status)
        except Exception:
            status = -1

        position = length = 0.0
        updated = None
        try:
            tl = chosen.get_timeline_properties()
            start = _seconds(getattr(tl, "start_time", None))
            end = _seconds(getattr(tl, "end_time", None))
            position = max(0.0, _seconds(getattr(tl, "position", None)) - start)
            # a browser tab often reports no range at all -> length 0,
            # which the UI already treats as "no bar, no total time"
            length = max(0.0, end - start)
            updated = getattr(tl, "last_updated_time", None)
        except Exception:
            pass

        try:
            aumid = chosen.source_app_user_model_id
        except Exception:
            aumid = ""

        return {
            "player": _pretty_player(aumid),
            "playing": status == _STATUS_PLAYING,
            "artist": str(artist),
            "title": str(title),
            "position": float(position),
            "length": float(length),
            "_updated": updated,
            "_read_at": time.time(),
        }

    # ------------------------------------------------------------- fetch
    def fetch(self):
        """{artist, title, position, length, player, playing} or None."""
        with self._lock:
            snap = dict(self._snap) if self._snap else None
        if snap is None:
            return None
        snap["position"] = self._live_position(snap)
        snap.pop("_updated", None)
        snap.pop("_read_at", None)
        return snap

    @staticmethod
    def _live_position(snap):
        """Advance the stored position by the time that has passed.

        Without this the song bar freezes: GSMTC only rewrites `position`
        on play/pause/seek/track change, so between two Spotify events the
        raw value is minutes stale.
        """
        pos = snap.get("position", 0.0)
        if not snap.get("playing"):
            return pos
        elapsed = None
        updated = snap.get("_updated")
        if isinstance(updated, datetime.datetime):
            try:
                now = datetime.datetime.now(datetime.timezone.utc)
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=datetime.timezone.utc)
                elapsed = (now - updated).total_seconds()
            except Exception:
                elapsed = None
        if elapsed is None:
            # no usable timestamp - measure from when we read it instead
            read_at = snap.get("_read_at")
            elapsed = (time.time() - read_at) if read_at else 0.0
        # A player that never sets last_updated_time leaves it at the
        # epoch; extrapolating from that would report a position of
        # several centuries. Ignore anything implausible.
        if not (0.0 <= elapsed <= _MAX_EXTRAPOLATE_SEC):
            return pos
        pos += elapsed
        length = snap.get("length") or 0.0
        if length > 0:
            pos = min(pos, length)
        return max(0.0, pos)

    # ------------------------------------------------------------ status
    def status_note(self):
        """One line the Media card can show when nothing was found."""
        if not HAS_WINRT:
            return ("Windows media bindings not installed - run:  "
                    + INSTALL_HINT)
        if self._error:
            return f"Windows media service error: {self._error}"
        return ""


# ====================================================================
#  python -m core.backends.media_windows
# ====================================================================
def _selftest():
    print("=" * 62)
    print(" OSC-DreamChatbox - Windows media (GSMTC) self-test")
    print("=" * 62)
    print(f"bindings : {_BINDING or 'NONE'}")
    if not HAS_WINRT:
        print(f"\nNothing installed. Run:\n    {INSTALL_HINT}\n")
        return
    m = WindowsMediaFetcher(lambda s: print("  log:", s))
    print("\nStart something playing, then watch the position advance.")
    print("-" * 62)
    for i in range(10):
        time.sleep(1.5)
        info = m.fetch()
        if not info:
            print(f"[{i:2}] nothing playing "
                  f"({m.status_note() or 'no session'})")
            continue
        pos, ln = info["position"], info["length"]
        bar = f"{pos:6.1f}/{ln:6.1f}s" if ln > 0 else f"{pos:6.1f}s (no length)"
        print(f"[{i:2}] {'>' if info['playing'] else '||'} "
              f"{info['artist']} - {info['title']}  |  {bar}  "
              f"|  {info['player']}")
    m.close()
    print("-" * 62)
    print("The position must climb between lines while playing - that is")
    print("the extrapolation working. A frozen number means the timeline")
    print("timestamp from this player is unusable.")


if __name__ == "__main__":
    _selftest()
