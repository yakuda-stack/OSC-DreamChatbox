"""
core/oscin.py – the receiving half of the OSC link.

Everything else in the app only ever sends: one message to
/chatbox/input and done. Reacting to the avatar needs the other
direction, so this listens for the parameter stream VRChat puts out and
keeps the last value of every parameter it has seen.

Deliberately a snapshot, not an event stream. The node graph is
evaluated on a timer and asks "what is this parameter right now" - so
the only thing worth keeping is the latest value per name. Anything
event-shaped (a toggle that flipped twice between two frames) is not
something a chatbox line can show anyway.

Two ways VRChat can reach us:

  * OSCQuery is on – VRChat sends to the dynamic port the OSCQuery
    service already reserved, so the socket is handed in here and read
    rather than a second one being opened.
  * OSCQuery is off – we bind VRChat's classic output port (9001)
    ourselves.

The socket is read on a daemon thread with a timeout, so stop() is a
flag and never a join that can hang the GUI.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import socket
import threading

try:
    from pythonosc.osc_packet import OscPacket
    HAS_OSC = True
except ImportError:      # pragma: no cover - python-osc is a hard dep
    OscPacket = None
    HAS_OSC = False

#: VRChat's default "OSC out" port
DEFAULT_IN_PORT = 9001

#: prefix of the avatar parameter namespace
PARAM_PREFIX = "/avatar/parameters/"

#: how many parameters we are willing to remember. An avatar with a few
#: hundred parameters is normal; a runaway sender is not, and an
#: unbounded dict fed from the network is how a long session turns into
#: a memory leak.
MAX_PARAMS = 2000


class OscParameterListener:
    """Last known value of every /avatar/parameters/* seen so far."""

    def __init__(self, log_fn=print):
        self.log = log_fn
        self._sock = None
        self._own_socket = False
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self._params = {}
        # everything else that arrives, by full address. The avatar
        # namespace gets its own dict because that is the one with a
        # picker in front of it; this one is for the External OSC Input
        # block, which addresses whatever an external tool sends.
        self._addresses = {}
        self._changed = 0        # bumped on every value change
        self.error = ""
        self.port = None

    # ------------------------------------------------------------ state
    @property
    def running(self):
        return self._running

    def get(self, name):
        """The value of one parameter, or None when it has never been
        seen. Names are matched exactly - VRChat's parameters are
        case-sensitive and quietly lower-casing them would make a
        working graph fail for no visible reason."""
        with self._lock:
            return self._params.get(str(name or "").strip())

    def snapshot(self):
        with self._lock:
            return dict(self._params)

    def get_address(self, address):
        """The last value seen at a full OSC address, or None. Leading
        slash optional, because half the world writes it and half does
        not."""
        address = str(address or "").strip()
        if not address:
            return None
        if not address.startswith("/"):
            address = "/" + address
        with self._lock:
            return self._addresses.get(address)

    def address_snapshot(self):
        with self._lock:
            return dict(self._addresses)

    def revision(self):
        """Counter that changes whenever any value changed - lets the UI
        repaint a parameter list without polling the whole dict."""
        with self._lock:
            return self._changed

    # ------------------------------------------------------------ start
    def start(self, port=DEFAULT_IN_PORT, sock=None):
        """Begins listening. ``sock`` adopts an already bound socket (the
        one OSCQuery reserved); otherwise ``port`` is bound here."""
        if self._running:
            return True
        if not HAS_OSC:
            self.error = "python-osc is not installed"
            self.log("OSC input: python-osc is not installed")
            return False
        try:
            if sock is not None:
                self._sock = sock
                self._own_socket = False
                self.port = sock.getsockname()[1]
            else:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", int(port)))
                self._sock = s
                self._own_socket = True
                self.port = int(port)
            self._sock.settimeout(0.5)
        except OSError as e:
            # the usual case is another OSC tool already holding 9001.
            # That is a normal situation, not a crash - say so and stay
            # off rather than taking the app down.
            self.error = str(e)
            self._sock = None
            self.log(f"OSC input: port {port} could not be opened ({e}). "
                     "Another OSC app is probably using it.")
            return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log(f"OSC input: listening on udp/{self.port}")
        return True

    def stop(self):
        self._running = False
        sock, self._sock = self._sock, None
        if sock is not None and self._own_socket:
            try:
                sock.close()
            except OSError:
                pass
        self._own_socket = False
        self.port = None

    def clear(self):
        with self._lock:
            self._params.clear()
            self._addresses.clear()
            self._changed += 1

    # ------------------------------------------------------------- loop
    def _loop(self):
        while self._running:
            sock = self._sock
            if sock is None:
                break
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                # socket closed under us by stop()
                break
            try:
                self._handle(data)
            except Exception:      # noqa: BLE001
                # a malformed packet is not worth a log line per frame;
                # VRChat is not the only thing that can be on that port
                continue

    def _handle(self, data):
        packet = OscPacket(data)
        for timed in packet.messages:
            message = timed.message
            address = message.address or ""
            if not address:
                continue
            params = list(message.params)
            value = params[0] if len(params) == 1 else (
                tuple(params) if params else None)
            name = address[len(PARAM_PREFIX):] \
                if address.startswith(PARAM_PREFIX) else ""
            with self._lock:
                if len(self._addresses) < MAX_PARAMS or \
                        address in self._addresses:
                    if self._addresses.get(address) != value:
                        self._addresses[address] = value
                        self._changed += 1
                if not name:
                    continue
                if len(self._params) >= MAX_PARAMS and \
                        name not in self._params:
                    continue
                if self._params.get(name) != value:
                    self._params[name] = value
                    self._changed += 1


# ---------------------------------------------------------------------------
def format_value(value):
    """A parameter as the template language sees it: everything is a
    string, and a bool is "1" / "" so it reads as true / false the same
    way every other value in the graph does."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, float):
        # 0.5 not 0.5000000001; trailing zeros dropped so a float that
        # happens to be whole prints like an int
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def value_type(value):
    """What kind of thing arrived, in the words the External OSC Input
    block's Type output uses."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    return "other"


def coerce_value(text, kind):
    """The other direction: what to actually put on the wire for an
    outgoing parameter. Returns None when the text cannot be that type,
    and the caller skips the send rather than guessing."""
    text = "" if text is None else str(text).strip()
    if kind == "auto":
        # what the text looks like, in the order that loses the least:
        # an int stays an int, "0.5" does not become 0
        low = text.lower()
        if low in ("true", "on", "yes"):
            return True
        if low in ("false", "off", "no"):
            return False
        for cast in (int, float):
            try:
                return cast(text.replace(",", "."))
            except (TypeError, ValueError):
                pass
        return text
    if kind == "string":
        return text
    if kind == "bool":
        return bool(text) and text.lower() not in ("0", "false", "off", "no")
    try:
        if kind == "int":
            return int(float(text.replace(",", ".")))
        if kind == "float":
            return float(text.replace(",", "."))
    except (TypeError, ValueError):
        return None
    return text
