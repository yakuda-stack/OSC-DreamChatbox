"""
core/vrchatlog.py – reads VRChat's output_log to expose live world info

VRChat does NOT send the current world name or the number of players in
the instance over OSC. The only source available offline on Linux is the
game's own text log (`output_log_*.txt`). This is exactly what the
Windows tools (MagicChatbox, VRCX ...) parse too.

Under Proton the log lives inside the Steam prefix, e.g.

    ~/.local/share/Steam/steamapps/compatdata/438100/pfx/drive_c/users/
        steamuser/AppData/LocalLow/VRChat/VRChat/output_log_*.txt

We resolve the folder from a couple of well-known Steam locations (native
+ Flatpak + extra library folders from libraryfolders.vdf), or from a
manual override. The newest `output_log_*.txt` is the running session.

What we parse (all lines carry a `[Behaviour]` tag):
    - "Joining wrld_…:<instanceId>~<tokens>"  -> new instance: reset the
      player set + derive the instance/access type (Public, Friends,
      Group, Group+, Invite …)
    - "Joining or Creating Room: <name>"      -> the human world name
    - "OnPlayerJoined <name>"                 -> +1 player (incl. yourself)
    - "OnPlayerLeft <name>"                   -> -1 player
    - "OnLeftRoom" / "Successfully left room" -> left the instance

Everything runs in a daemon thread (log files get large; we never touch
the file from the GUI thread). The GUI reads a cheap snapshot() under a
lock. Reading is incremental – only the bytes appended since the last
poll are parsed, so it stays light even during long sessions.

No extra dependencies – stdlib only.
"""

import os
import re
import threading
import time
from pathlib import Path

VRCHAT_APPID = "438100"

# folder inside a Steam prefix where VRChat drops its logs
_PREFIX_TAIL = Path(
    "pfx/drive_c/users/steamuser/AppData/LocalLow/VRChat/VRChat")

# Steam roots to probe (native + common variants + Flatpak)
_STEAM_ROOTS = [
    Path.home() / ".local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".steam/root",
    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam",
]

# ---------------------------------------------------------------- log regex
_RE_JOIN_INSTANCE = re.compile(r"Joining (wrld_[^\s:]+):(\S+)")
_RE_JOIN_ROOM = re.compile(r"Joining or Creating Room:\s*(.+?)\s*$")
_RE_PLAYER_JOIN = re.compile(
    r"OnPlayerJoined\s+(.+?)(?:\s+\(usr_[0-9a-fA-F-]+\))?\s*$")
_RE_PLAYER_LEFT = re.compile(
    r"OnPlayerLeft\s+(.+?)(?:\s+\(usr_[0-9a-fA-F-]+\))?\s*$")
_RE_LEFT_ROOM = re.compile(r"OnLeftRoom|Successfully left room")


def _instance_type(descriptor: str) -> str:
    """Human name for the access type of an instance descriptor like
    '12345~group(grp_x)~groupAccessType(members)~region(use)'."""
    d = descriptor
    if "~group(" in d or "~groupAccessType(" in d:
        if "groupAccessType(public)" in d:
            return "Group Public"
        if "groupAccessType(plus)" in d:
            return "Group+"
        return "Group"
    if "~hidden(" in d:
        return "Friends+"
    if "~friends(" in d:
        return "Friends"
    if "~private(" in d:
        return "Invite+" if "~canRequestInvite" in d else "Invite"
    return "Public"


class VRChatLogWatcher:
    """Live world/player info from VRChat's output log.

    Start it once (start()); it keeps a background thread that tails the
    newest log file. Read the current state via snapshot(). Set an
    explicit folder with set_override() (empty = auto-detect)."""

    def __init__(self, log_fn=print):
        self.log = log_fn
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self._override = ""

        # parsed state (guarded by _lock)
        self._world = ""
        self._itype = ""
        self._players = set()
        self._in_world = False

        # file tracking
        self._cur_path = None
        self._offset = 0
        self._warned = False

    # ----------------------------------------------------------- lifecycle
    def set_override(self, path: str):
        """Manual log folder ('' = auto-detect). Forces a re-attach."""
        with self._lock:
            self._override = (path or "").strip()
            self._cur_path = None
            self._offset = 0
            self._warned = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def snapshot(self):
        """Current state as a dict. Cheap; safe from the GUI thread."""
        with self._lock:
            return {
                "in_world": self._in_world,
                "world": self._world,
                "instance_type": self._itype,
                "player_count": len(self._players),
                "log_dir": (str(self._cur_path.parent)
                            if self._cur_path else ""),
            }

    # ----------------------------------------------------------- discovery
    def _library_roots(self):
        """Extra Steam library folders parsed from libraryfolders.vdf –
        VRChat may live on a different drive than the main Steam root."""
        roots = []
        for base in _STEAM_ROOTS:
            vdf = base / "steamapps" / "libraryfolders.vdf"
            try:
                txt = vdf.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in re.finditer(r'"path"\s*"([^"]+)"', txt):
                roots.append(Path(m.group(1).replace("\\\\", "/")))
        return roots

    def _find_log_dir(self):
        """Resolve the VRChat log folder (override wins, else probe)."""
        if self._override:
            p = Path(self._override).expanduser()
            return p if p.is_dir() else None
        candidates = []
        for base in _STEAM_ROOTS + self._library_roots():
            candidates.append(
                base / "steamapps" / "compatdata" / VRCHAT_APPID
                / _PREFIX_TAIL)
        seen = set()
        for c in candidates:
            key = str(c)
            if key in seen:
                continue
            seen.add(key)
            if c.is_dir():
                return c
        return None

    def _newest_log(self, folder: Path):
        try:
            logs = [p for p in folder.glob("output_log_*.txt")]
        except Exception:
            return None
        if not logs:
            return None
        return max(logs, key=lambda p: p.stat().st_mtime)

    # ----------------------------------------------------------------- run
    def _run(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                if not self._warned:
                    self.log(f"VRChat log: read error – {e}")
                    self._warned = True
            self._stop.wait(2.0)

    def _tick(self):
        folder = self._find_log_dir()
        if folder is None:
            if not self._warned:
                self.log("VRChat log: no output_log folder found "
                         "(is VRChat installed via Steam/Proton?). "
                         "Set the folder manually in Personal Status.")
                self._warned = True
            with self._lock:
                self._in_world = False
            return

        newest = self._newest_log(folder)
        if newest is None:
            with self._lock:
                self._in_world = False
            return

        # new session / rotated file -> restart from the top
        if newest != self._cur_path:
            self.log(f"VRChat log: reading {newest.name}")
            with self._lock:
                self._cur_path = newest
                self._offset = 0
                self._world = ""
                self._itype = ""
                self._players = set()
                self._in_world = False
                self._warned = False

        try:
            size = newest.stat().st_size
        except Exception:
            return
        # file truncated/replaced under us -> re-read from start
        if size < self._offset:
            self._offset = 0
            with self._lock:
                self._players = set()

        if size == self._offset:
            return

        with open(newest, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(self._offset)
            chunk = f.read()
            self._offset = f.tell()

        for raw in chunk.splitlines():
            if "[Behaviour]" not in raw:
                continue
            self._parse_line(raw)

    def _parse_line(self, line: str):
        m = _RE_JOIN_INSTANCE.search(line)
        if m:
            with self._lock:
                self._players = set()
                self._itype = _instance_type(m.group(2))
                self._in_world = True
            return
        m = _RE_JOIN_ROOM.search(line)
        if m:
            with self._lock:
                self._world = m.group(1).strip()
                self._in_world = True
            return
        m = _RE_PLAYER_JOIN.search(line)
        if m:
            with self._lock:
                self._players.add(m.group(1).strip())
            return
        m = _RE_PLAYER_LEFT.search(line)
        if m:
            with self._lock:
                self._players.discard(m.group(1).strip())
            return
        if _RE_LEFT_ROOM.search(line):
            with self._lock:
                self._players = set()
                self._in_world = False
                self._world = ""
                self._itype = ""
