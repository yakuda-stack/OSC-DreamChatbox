"""
core/oscbridge.py - the OSC endpoint behind ``api.osc``.

A plugin that talks OSC used to have to build the whole stack itself:
encode and decode the wire format, bind a socket, run an OSCQuery HTTP
server, register it over mDNS, and find VRChat's real input port. That
is several hundred lines per plugin, all of it identical, all of it
already present in this app.

So the app hands it over instead. Two backends, one plugin-facing
object:

**shared** (the default). The plugin sends through the target the app
already discovered, receives from the stream core/oscin.py is already
reading, and advertises its addresses inside the OSCQuery tree
core/oscquery.py is already publishing. No extra socket, no extra mDNS
service, no extra thread. This is what a plugin reacting to avatar
parameters wants - it does not need a port of its own, it needs VRChat
to push to it, and VRChat pushes to whoever is announced.

**own**. A UDP socket bound to a port the plugin (or the user) picks,
with its own OSCQuery service on top. Worth the extra machinery in one
case: something other than VRChat has to reach the plugin on a fixed,
known port - an external tool, a phone app, a hardware bridge. A fixed
port only means anything when somebody outside is typing it in.

The plugin-facing API is identical either way, so a plugin written
against one backend runs on the other unchanged.

Threading: callbacks handed to subscribe() run on a receive thread, not
on the GUI thread. No Qt in them - the same rule as build_widget(), and
for the same reason. api.set() is safe from any thread and is the
intended way back.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.oscquery import (HAS_ZEROCONF, OSC_TYPE, OSCJSON_TYPE, _local_ip)

try:
    from pythonosc.osc_message_builder import OscMessageBuilder
    from pythonosc.osc_packet import OscPacket
    HAS_OSC = True
except ImportError:      # pragma: no cover - python-osc is a hard dep
    OscMessageBuilder = None
    OscPacket = None
    HAS_OSC = False

if HAS_ZEROCONF:
    from zeroconf import IPVersion, ServiceInfo, Zeroconf

#: what a manifest may ask for
OSC_MODES = ("shared", "own")
DEFAULT_OSC_MODE = "shared"

#: VRChat's usual input port. Only ever a last resort - the app
#: discovers the real one, which differs as soon as two clients run.
FALLBACK_TARGET = ("127.0.0.1", 9000)


def encode(address, args=()):
    """One OSC message as bytes."""
    builder = OscMessageBuilder(address=str(address))
    for arg in args:
        builder.add_arg(arg)
    return builder.build().dgram


# ---------------------------------------------------------------------
# the object a plugin gets
# ---------------------------------------------------------------------
class OscEndpoint:
    """Base for both backends. A plugin only ever sees this surface."""

    mode = DEFAULT_OSC_MODE

    def __init__(self, pid, spec, hub):
        self.pid = pid
        self.spec = dict(spec or {})
        self._hub = hub
        self._log = hub.log
        self._subs = []           # (fn, prefix)
        self._lock = threading.Lock()
        self._paths = {}
        self.error = ""

    # ------------------------------------------------------------ state
    @property
    def available(self):
        """False when nothing can be sent or received at all - no
        python-osc, or a socket that would not open. A plugin should
        check this once and say so in its own UI rather than failing
        quietly every frame."""
        return HAS_OSC

    @property
    def port(self):
        """The port actually in use. Ask this instead of assuming the
        wish in the manifest was granted - it is not, when the port was
        taken or the backend is shared."""
        return 0

    @property
    def oscquery(self):
        """True when this endpoint is announced over mDNS. False without
        zeroconf, and False when the manifest turned it off."""
        return False

    @property
    def receiving(self):
        """True when messages can actually arrive right now.

        Separate from ``available`` on purpose: in shared mode this is
        off while the user has the app's OSC input switched off, which
        is a normal setting and not an error. A plugin that needs the
        incoming direction can tell the user exactly that.
        """
        return False

    @property
    def target(self):
        """(ip, port) of VRChat as the app currently knows it."""
        return self._hub.target()

    # ------------------------------------------------------------ send
    def send(self, address, *args, to=None):
        """One OSC message to VRChat, or to ``to`` = (ip, port).

        Returns True when it went out. A plugin should never hardcode
        9000: the app discovers the running client's real port, and on a
        machine with two clients that is not 9000.
        """
        if not HAS_OSC:
            return False
        dest = to or self.target
        if not dest:
            return False
        try:
            self._hub.sendto(encode(address, args), dest)
            return True
        except OSError as e:
            self._log(f"[{self.pid}] OSC send failed: {e}")
            return False

    # --------------------------------------------------------- receive
    def subscribe(self, fn, prefix=""):
        """Call ``fn(address, args)`` for every message that arrives.

        ``prefix`` filters by address start - "/avatar/parameters/" is
        the usual one. Returns the function, so it can be handed back to
        unsubscribe().

        Runs on a receive thread. Do not touch Qt in it.
        """
        with self._lock:
            self._subs.append((fn, str(prefix or "")))
        return fn

    def unsubscribe(self, fn):
        with self._lock:
            self._subs = [(f, p) for f, p in self._subs if f is not fn]

    def _dispatch(self, address, args):
        """Fan one message out to the subscribers. Never raises: a
        plugin callback that blows up is dropped, not allowed to stop
        the socket everything else is reading."""
        with self._lock:
            subs = list(self._subs)
        for fn, prefix in subs:
            if prefix and not address.startswith(prefix):
                continue
            try:
                fn(address, args)
            except Exception:      # noqa: BLE001
                self._log(f"[{self.pid}] an OSC callback raised - "
                          f"dropping it")
                self.unsubscribe(fn)

    # ------------------------------------------------------- advertise
    def advertise(self, paths):
        """Tell the world which addresses this plugin accepts.

        ``paths`` is {"/avatar/parameters/Foo": "f"} - address to OSC
        type tag ("f" float, "i" int, "T"/"F" bool). This is what makes
        VRChat push those values here; without it an endpoint is
        send-only in practice.

        Replaces the previous set rather than adding to it, so a plugin
        that switched profiles stops being sent the old profile's
        parameters.
        """
        self._paths = {str(k): str(v or "f")[:1] or "f"
                       for k, v in (paths or {}).items()
                       if str(k).startswith("/")}
        self._apply_paths()
        return len(self._paths)

    def _apply_paths(self):
        pass

    # ----------------------------------------------------------- close
    def close(self):
        with self._lock:
            self._subs = []
        self._paths = {}


class SharedEndpoint(OscEndpoint):
    """Rides on the app's own socket, tree and discovery."""

    mode = "shared"

    @property
    def port(self):
        return self._hub.shared_port()

    @property
    def oscquery(self):
        return self._hub.oscquery_running()

    @property
    def receiving(self):
        return self._hub.shared_receiving()

    def _apply_paths(self):
        self._hub.set_paths(self.pid, self._paths)

    def close(self):
        super().close()
        self._hub.set_paths(self.pid, {})


class OwnEndpoint(OscEndpoint):
    """Its own UDP socket, its own OSCQuery service.

    For the one case that shared cannot serve: something outside VRChat
    has to reach this plugin on a port it was told about in advance.
    """

    mode = "own"

    def __init__(self, pid, spec, hub, app_name="plugin"):
        super().__init__(pid, spec, hub)
        self.app_name = app_name
        self._sock = None
        self._thread = None
        self._running = False
        self._port = 0
        self._http = None
        self._http_port = 0
        self._zc = None
        self._infos = []
        self._want_query = bool(spec.get("oscquery", True))
        self._start(int(spec.get("port") or 0))

    # ------------------------------------------------------------ state
    @property
    def available(self):
        return HAS_OSC and self._sock is not None

    @property
    def port(self):
        return self._port

    @property
    def oscquery(self):
        return self._zc is not None

    @property
    def receiving(self):
        return self._running

    # ----------------------------------------------------------- setup
    def _start(self, wanted):
        if not HAS_OSC:
            self.error = "python-osc is not installed"
            return
        try:
            self._bind(wanted)
        except OSError as e:
            if not wanted:
                self.error = str(e)
                self._log(f"[{self.pid}] OSC: no socket ({e})")
                return
            # the wished-for port was taken. Falling back to an
            # ephemeral one keeps the plugin working for everything that
            # discovers it through OSCQuery; only a sender that was
            # given the fixed number by hand is out of luck, and it gets
            # told which port to use instead.
            self._log(f"[{self.pid}] OSC: udp/{wanted} is taken ({e}) - "
                      f"falling back to an automatic port")
            try:
                self._bind(0)
            except OSError as e2:
                self.error = str(e2)
                self._log(f"[{self.pid}] OSC: no socket ({e2})")
                return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._log(f"[{self.pid}] OSC: listening on udp/{self._port}")
        if self._want_query:
            self._announce()

    def _bind(self, port):
        # deliberately NO SO_REUSEADDR. core/oscin.py sets it because it
        # rebinds 9001 across restarts, but here it would let two
        # endpoints hold the same port and quietly split the traffic
        # between them - a bug that looks like "half my messages
        # vanish". Failing is what makes the fallback below possible.
        # UDP has no TIME_WAIT, so nothing is lost by leaving it off.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", int(port)))
        sock.settimeout(0.5)
        self._sock = sock
        self._port = sock.getsockname()[1]

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
                break
            try:
                packet = OscPacket(data)
            except Exception:      # noqa: BLE001
                # a malformed packet is not worth a log line per frame
                continue
            for timed in packet.messages:
                msg = timed.message
                if msg.address:
                    self._dispatch(msg.address, list(msg.params))

    # ------------------------------------------------------- OSCQuery
    def _apply_paths(self):
        if self._http is not None:
            self._http.RequestHandlerClass.node = self._tree()
        elif self._want_query:
            self._announce()

    def _tree(self):
        root = {"DESCRIPTION": self.app_name, "FULL_PATH": "/",
                "ACCESS": 0, "CONTENTS": {}}
        for path, tag in self._paths.items():
            node = root
            walked = ""
            for part in [p for p in path.split("/") if p]:
                walked += "/" + part
                node = node.setdefault("CONTENTS", {}).setdefault(
                    part, {"FULL_PATH": walked, "ACCESS": 0})
            node["ACCESS"] = 3
            node["TYPE"] = tag
        return root

    def _announce(self):
        if not HAS_ZEROCONF or self._sock is None:
            if not HAS_ZEROCONF:
                # not an error: sending still works, and so does
                # receiving from anything told the port by hand. Only
                # automatic discovery is gone.
                self._log(f"[{self.pid}] OSC: zeroconf missing - "
                          f"udp/{self._port} is not announced")
            return
        try:
            handler = _endpoint_handler(self._tree(), self._port,
                                        self.app_name)
            self._http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            self._http_port = self._http.server_address[1]
            threading.Thread(target=self._http.serve_forever,
                             daemon=True).start()
            self._zc = Zeroconf(ip_version=IPVersion.V4Only)
            addr = socket.inet_aton(_local_ip())
            name = self.app_name.replace(" ", "-")
            self._infos = [
                ServiceInfo(OSCJSON_TYPE, f"{name}.{OSCJSON_TYPE}",
                            addresses=[addr], port=self._http_port,
                            properties={}),
                ServiceInfo(OSC_TYPE, f"{name}.{OSC_TYPE}",
                            addresses=[addr], port=self._port,
                            properties={}),
            ]
            for info in self._infos:
                self._zc.register_service(info)
            self._log(f"[{self.pid}] OSC: announced as '{name}' "
                      f"(udp/{self._port}, http tcp/{self._http_port})")
        except Exception as e:      # noqa: BLE001
            self.error = str(e)
            self._log(f"[{self.pid}] OSC: could not announce ({e})")

    # ----------------------------------------------------------- close
    def close(self):
        super().close()
        self._running = False
        for info in self._infos:
            try:
                self._zc.unregister_service(info)
            except Exception:      # noqa: BLE001
                pass
        self._infos = []
        if self._zc is not None:
            try:
                self._zc.close()
            except Exception:      # noqa: BLE001
                pass
            self._zc = None
        if self._http is not None:
            try:
                self._http.shutdown()
            except Exception:      # noqa: BLE001
                pass
            self._http = None
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        # Closing the fd is not enough: a thread blocked in recvfrom
        # still holds the socket alive until its call returns, so the
        # port stays taken for up to one timeout. rebind_osc() reopens
        # on the SAME port immediately afterwards - without this wait it
        # would find its own old socket in the way and fall back to a
        # random port, which is precisely the port the user just typed
        # in not being used.
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)


def _endpoint_handler(node, osc_port, app_name):
    """A tiny OSCQuery HTTP handler class for one endpoint."""

    class Handler(BaseHTTPRequestHandler):
        node_tree = node
        port = osc_port
        name = app_name

        def do_GET(self):        # noqa: N802 - stdlib naming
            import json
            if "HOST_INFO" in (self.path or ""):
                body = {"NAME": self.name, "OSC_IP": _local_ip(),
                        "OSC_PORT": self.port, "OSC_TRANSPORT": "UDP",
                        "EXTENSIONS": {"ACCESS": True, "VALUE": True}}
            else:
                body = type(self).node_tree
            raw = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    return Handler


# ---------------------------------------------------------------------
# the hub
# ---------------------------------------------------------------------
class OscHub:
    """Owns every plugin endpoint and the one shared socket behind them.

    Reads the app's state through ``host`` (the MainWindow) rather than
    holding its own copy, so a user changing the OSC target in Options
    reaches every plugin without anything having to be notified. Without
    a host - the manager runs headless in tests - everything degrades to
    "nothing to send to", which is a state the plugins already have to
    handle.
    """

    def __init__(self, host=None, log=print, app_name="plugin"):
        self.host = host
        self.log = log
        self.app_name = app_name
        self._endpoints = {}
        self._send_sock = None
        self._sink_installed = False
        self._lock = threading.Lock()

    # ------------------------------------------------------ lifecycle
    def open(self, pid, spec):
        """Builds the endpoint a manifest asked for, or None."""
        if not spec or not spec.get("enabled"):
            return None
        self.close(pid)
        mode = spec.get("mode") or DEFAULT_OSC_MODE
        if mode == "own":
            endpoint = OwnEndpoint(pid, spec, self,
                                   app_name=f"{self.app_name}-{pid}")
        else:
            endpoint = SharedEndpoint(pid, spec, self)
            self._install_sink()
        self._endpoints[pid] = endpoint
        return endpoint

    def close(self, pid):
        endpoint = self._endpoints.pop(pid, None)
        if endpoint is not None:
            endpoint.close()
        if not any(e.mode == "shared" for e in self._endpoints.values()):
            self._remove_sink()

    def close_all(self):
        for pid in list(self._endpoints):
            self.close(pid)
        sock, self._send_sock = self._send_sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # ---------------------------------------------------- shared side
    def _install_sink(self):
        listener = getattr(self.host, "osc_in", None)
        if listener is None or self._sink_installed:
            return
        if hasattr(listener, "add_sink"):
            listener.add_sink(self._on_message)
            self._sink_installed = True

    def _remove_sink(self):
        listener = getattr(self.host, "osc_in", None)
        if listener is not None and self._sink_installed:
            if hasattr(listener, "remove_sink"):
                listener.remove_sink(self._on_message)
        self._sink_installed = False

    def _on_message(self, address, args):
        for endpoint in list(self._endpoints.values()):
            if endpoint.mode == "shared":
                endpoint._dispatch(address, args)

    def shared_port(self):
        listener = getattr(self.host, "osc_in", None)
        port = getattr(listener, "port", None)
        if port:
            return int(port)
        service = getattr(self.host, "oscq", None)
        return int(getattr(service, "osc_port", 0) or 0)

    def shared_receiving(self):
        listener = getattr(self.host, "osc_in", None)
        return bool(getattr(listener, "running", False))

    def oscquery_running(self):
        service = getattr(self.host, "oscq", None)
        return bool(getattr(service, "running", False))

    def set_paths(self, pid, paths):
        service = getattr(self.host, "oscq", None)
        if service is not None and hasattr(service, "add_paths"):
            service.add_paths(pid, paths)

    # ---------------------------------------------------------- target
    def target(self):
        """(ip, port) of VRChat: what OSCQuery discovered, else what the
        user configured in Options, else nothing.

        Nothing - rather than 9000 - because a plugin silently shouting
        at a port with no listener is worse than one that can say "no
        VRChat found".
        """
        service = getattr(self.host, "oscq", None)
        if service is not None and hasattr(service, "vrchat_target"):
            found = service.vrchat_target()
            if found:
                return found
        cfg = getattr(self.host, "cfg", None)
        if isinstance(cfg, dict) and cfg.get("osc_ip"):
            try:
                return (str(cfg["osc_ip"]), int(cfg.get("osc_port") or 0))
            except (TypeError, ValueError):
                return None
        return None

    def sendto(self, data, dest):
        with self._lock:
            if self._send_sock is None:
                self._send_sock = socket.socket(socket.AF_INET,
                                                socket.SOCK_DGRAM)
            self._send_sock.sendto(data, (dest[0], int(dest[1])))
