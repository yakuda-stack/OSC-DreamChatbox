"""
core/mediafetch.py – MPRIS media fetcher for OSC-DreamChatbox
(Spotify, YT Music, browsers, VLC, ... via D-Bus)
"""

# MPRIS media detection via D-Bus (part of PyQt6, Linux only)
try:
    from PyQt6.QtDBus import QDBusConnection, QDBusInterface
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False


class MediaFetcher:
    def __init__(self, log_fn):
        self.log = log_fn
        self.bus = None
        self._cached_player = None
        if HAS_DBUS:
            bus = QDBusConnection.sessionBus()
            if bus.isConnected():
                self.bus = bus
            else:
                self.log("MediaPlay: D-Bus session bus not available.")
        else:
            self.log("MediaPlay: QtDBus not available on this system.")

    def _list_players(self):
        iface = QDBusInterface("org.freedesktop.DBus", "/org/freedesktop/DBus",
                               "org.freedesktop.DBus", self.bus)
        reply = iface.call("ListNames")
        names = reply.arguments()[0] if reply.arguments() else []
        return [n for n in names if n.startswith("org.mpris.MediaPlayer2.")]

    def _get_prop(self, service, prop):
        props = QDBusInterface(service, "/org/mpris/MediaPlayer2",
                               "org.freedesktop.DBus.Properties", self.bus)
        reply = props.call("Get", "org.mpris.MediaPlayer2.Player", prop)
        args = reply.arguments()
        return args[0] if args else None

    def fetch(self):
        """Returns dict {artist, title, position, length, player, playing}
        or None if nothing is playing / no player found."""
        if self.bus is None:
            return None
        try:
            chosen, status = None, ""
            # fast path: re-use the last known player if it is still playing
            if self._cached_player:
                st = self._get_prop(self._cached_player, "PlaybackStatus")
                if st == "Playing":
                    chosen, status = self._cached_player, st
                else:
                    self._cached_player = None
            if chosen is None:
                players = self._list_players()
                if not players:
                    return None
                for p in players:
                    st = self._get_prop(p, "PlaybackStatus") or ""
                    if st == "Playing":
                        chosen, status = p, st
                        break
                if chosen is None:
                    chosen = players[0]
                    status = self._get_prop(chosen, "PlaybackStatus") or ""
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
            return {
                "player": chosen.split("org.mpris.MediaPlayer2.")[-1],
                "playing": status == "Playing",
                "artist": artist,
                "title": title,
                "position": float(pos_us) / 1_000_000.0,
                "length": float(length_us) / 1_000_000.0,
            }
        except Exception as e:
            self.log(f"MediaPlay: error while querying player: {e}")
            return None
