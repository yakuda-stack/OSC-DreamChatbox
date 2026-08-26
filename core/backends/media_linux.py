"""
core/backends/media_linux.py - MPRIS media fetcher (Linux)

(moved out of core/mediafetch.py in v1.2.7)
(v1.4.4: the player can be chosen instead of guessed)

WHY THERE IS A CHOICE NOW
-------------------------
The old rule was "first player on the bus that says Playing wins". That
is right when one thing is playing and arbitrary when two are: leave
Spotify paused mid-song and start YouTube Music in a browser tab, and
which one the chatbox shows depends on the order D-Bus happens to list
bus names in. People noticed, because the answer changed between
restarts.

So the player is now a setting. Auto keeps the old behaviour - and stays
the default, because it is right for the single-player case most people
are in - but picking Spotify means Spotify.

KEYS HAVE TO SURVIVE A RESTART
------------------------------
The obvious key is the bus name, and the obvious key is wrong. Browsers
append a per-process suffix:

    org.mpris.MediaPlayer2.firefox.instance_1_94
    org.mpris.MediaPlayer2.chromium.instance17421

Save that and the setting points at a Firefox that no longer exists the
next time Firefox starts. ``source_key()`` strips the suffix, so the
stored value is ``firefox`` and it keeps meaning Firefox.

YOUTUBE MUSIC IS TWO DIFFERENT THINGS
-------------------------------------
Worth saying out loud because it is the case that prompted this: the
standalone desktop app is ``org.mpris.MediaPlayer2.YoutubeMusic`` and a
music.youtube.com tab is whatever browser is hosting it. They are
separate entries here and they should be - "YouTube Music" and "YouTube
Music in Firefox" behave differently, and someone who picks one did not
mean the other.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re

# MPRIS media detection via D-Bus (part of PyQt6, Linux only)
try:
    from PyQt6.QtDBus import QDBusConnection, QDBusInterface
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
IFACE_ROOT = "org.mpris.MediaPlayer2"
IFACE_PLAYER = "org.mpris.MediaPlayer2.Player"

#: the per-process tail browsers and some players append to their bus
#: name. Both spellings are in the wild: Firefox uses .instance_1_94,
#: Chromium uses .instance17421.
_INSTANCE_RE = re.compile(r"\.instance[_\d].*$", re.IGNORECASE)

#: bus suffixes whose own Identity is unhelpful or missing
_NICE_NAMES = {
    "spotify": "Spotify",
    "youtubemusic": "YouTube Music",
    "youtube-music": "YouTube Music",
    "ytmdesktop": "YouTube Music Desktop",
    "firefox": "Firefox",
    "chromium": "Chromium",
    "chrome": "Chrome",
    "brave": "Brave",
    "vivaldi": "Vivaldi",
    "zen": "Zen Browser",
    "vlc": "VLC",
    "mpv": "mpv",
    "audacious": "Audacious",
    "rhythmbox": "Rhythmbox",
    "elisa": "Elisa",
    "strawberry": "Strawberry",
    "clementine": "Clementine",
    "tauon": "Tauon",
    "amberol": "Amberol",
    "lollypop": "Lollypop",
    "plasma-browser-integration": "Browser (Plasma integration)",
}


def source_key(bus_name: str) -> str:
    """Bus name -> the stable identifier the setting stores.

    ``org.mpris.MediaPlayer2.firefox.instance_1_94`` -> ``firefox``
    """
    tail = (bus_name or "").split(MPRIS_PREFIX)[-1]
    return _INSTANCE_RE.sub("", tail)


def source_label(key: str, identity: str = "") -> str:
    """Something to put in a dropdown.

    The player's own Identity is the best answer when it has one -
    ``org.mpris.MediaPlayer2.YoutubeMusic`` calling itself "YouTube
    Music" beats anything a lookup table can do. The table is for the
    ones that report nothing useful.
    """
    identity = (identity or "").strip()
    if identity and identity.lower() not in ("mediaplayer2", "mpris"):
        return identity
    low = (key or "").lower()
    if low in _NICE_NAMES:
        return _NICE_NAMES[low]
    return key or "Unknown"


class MediaFetcher:
    """MPRIS over D-Bus.

    ``preferred`` is the setting: empty means auto, otherwise a key from
    ``source_key()``. ``fallback`` decides what happens when the chosen
    player is not on the bus - see _pick().
    """

    available = True
    name = "mpris"

    def __init__(self, log_fn):
        self.log = log_fn
        self.bus = None
        self._cached_player = None
        #: "" = automatic. Set from the UI; read on every fetch, so
        #: changing it in the dropdown takes effect on the next poll
        #: without rebuilding anything.
        self.preferred = ""
        self.fallback = True
        if HAS_DBUS:
            bus = QDBusConnection.sessionBus()
            if bus.isConnected():
                self.bus = bus
            else:
                self.log("MediaPlay: D-Bus session bus not available.")
        else:
            self.log("MediaPlay: QtDBus not available on this system.")

    # ------------------------------------------------------------- bus
    def _list_players(self):
        iface = QDBusInterface("org.freedesktop.DBus", "/org/freedesktop/DBus",
                               "org.freedesktop.DBus", self.bus)
        reply = iface.call("ListNames")
        names = reply.arguments()[0] if reply.arguments() else []
        return [n for n in names if n.startswith(MPRIS_PREFIX)]

    def _get_prop(self, service, prop, interface=IFACE_PLAYER):
        props = QDBusInterface(service, "/org/mpris/MediaPlayer2",
                               "org.freedesktop.DBus.Properties", self.bus)
        reply = props.call("Get", interface, prop)
        args = reply.arguments()
        return args[0] if args else None

    def _identity(self, service):
        try:
            value = self._get_prop(service, "Identity", IFACE_ROOT)
            return str(value or "")
        except Exception:
            return ""

    def _status(self, bus_name):
        try:
            return str(self._get_prop(bus_name, "PlaybackStatus") or "")
        except Exception:
            return ""

    # --------------------------------------------------------- sources
    def list_sources(self):
        """Every player on the bus right now, as
        ``{key, label, playing, bus}``.

        Two entries can collapse to one key - two Firefox windows each
        register their own bus name - and that is intended: the setting
        means "Firefox", not "that particular Firefox process". The one
        that is playing wins the merge, so the dropdown shows Firefox as
        active when any of its windows is.
        """
        if self.bus is None:
            return []
        try:
            names = self._list_players()
        except Exception as e:
            self.log(f"MediaPlay: could not list players ({e})")
            return []

        merged = {}
        for bus_name in names:
            key = source_key(bus_name)
            playing = self._status(bus_name) == "Playing"
            if key in merged and not playing:
                continue                # keep the better of the two
            merged[key] = {
                "key": key,
                "label": source_label(key, self._identity(bus_name)),
                "playing": playing,
                "bus": bus_name,
            }
        # playing first, then alphabetically - a stable order matters for
        # a dropdown that is rebuilt every few seconds
        return sorted(merged.values(),
                      key=lambda s: (not s["playing"], s["label"].lower()))

    def _pick(self, players):
        """Which bus name to read, honouring the setting.

        The rules, in the order they are applied:

        1. A chosen player that is playing.
        2. A chosen player that exists but is paused - still the right
           answer, and the card already shows paused songs.
        3. Nothing chosen, or the chosen one is not running and fallback
           is on: the old behaviour, first player that is playing.
        4. Fallback off and the chosen one is gone: nothing. Deliberate -
           somebody who pinned Spotify and turned the fallback off asked
           for silence rather than for whatever else happens to be on.
        """
        want = (self.preferred or "").strip()
        if want:
            mine = [p for p in players if source_key(p) == want]
            for bus_name in mine:
                if self._status(bus_name) == "Playing":
                    return bus_name, "Playing"
            if mine:
                return mine[0], self._status(mine[0])
            if not self.fallback:
                return None, ""

        for bus_name in players:
            if self._status(bus_name) == "Playing":
                return bus_name, "Playing"
        if players:
            return players[0], self._status(players[0])
        return None, ""

    # ----------------------------------------------------------- fetch
    def fetch(self):
        """Returns dict {artist, title, position, length, player,
        player_key, player_label, playing} or None if nothing is playing
        / no player found."""
        if self.bus is None:
            return None
        try:
            chosen, status = None, ""
            want = (self.preferred or "").strip()

            # Fast path: the player we read last time, if it is still the
            # one we want and still playing. Saves listing the whole bus
            # once a second.
            if self._cached_player:
                if want and source_key(self._cached_player) != want:
                    self._cached_player = None
                else:
                    st = self._status(self._cached_player)
                    if st == "Playing":
                        chosen, status = self._cached_player, st
                    else:
                        self._cached_player = None

            if chosen is None:
                players = self._list_players()
                if not players:
                    return None
                chosen, status = self._pick(players)
                if chosen is None:
                    return None
                self._cached_player = chosen

            meta = self._get_prop(chosen, "Metadata") or {}
            if not isinstance(meta, dict):
                return None
            title = str(meta.get("xesam:title", "") or "")
            artist_v = meta.get("xesam:artist", "")
            if isinstance(artist_v, (list, tuple)):
                artist = ", ".join(str(a) for a in artist_v)
            else:
                artist = str(artist_v or "")
            length_us = meta.get("mpris:length", 0) or 0
            pos_us = self._get_prop(chosen, "Position") or 0
            if not title and not artist:
                return None
            key = source_key(chosen)
            return {
                # kept as the bare bus suffix so {player} prints what it
                # always printed - the pretty name is for the dropdown
                "player": chosen.split(MPRIS_PREFIX)[-1],
                "player_key": key,
                "player_label": source_label(key, self._identity(chosen)),
                "playing": status == "Playing",
                "artist": artist,
                "title": title,
                "position": float(pos_us) / 1_000_000.0,
                "length": float(length_us) / 1_000_000.0,
            }
        except Exception as e:
            self.log(f"MediaPlay: error while querying player: {e}")
            return None

    # ---------------------------------------------------------- status
    def status_note(self):
        """One line for the Media card when nothing came back."""
        if self.bus is None:
            return "No D-Bus session bus - MPRIS players cannot be seen."
        want = (self.preferred or "").strip()
        if want and not any(s["key"] == want for s in self.list_sources()):
            label = source_label(want)
            if self.fallback:
                return f"{label} is not running - showing any other player."
            return f"{label} is not running."
        return ""
