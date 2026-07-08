"""
core/oscquery.py – native OSCQuery for OSC-DreamChatbox

Removes the hard-coded 9000/9001 port binding:

1. ADVERTISE (we register ourselves):
   - a free UDP port is picked dynamically (bind to port 0)
   - a tiny OSCQuery HTTP/JSON server starts on a free TCP port and
     answers  /?HOST_INFO  and the node tree ( / )
   - both are announced via mDNS/Zeroconf as
       _oscjson._tcp.local.   and   _osc._udp.local.
     so VRChat (and other tools) discover us automatically – no port
     conflicts, every tool gets its own dynamic port.

2. DISCOVER (we find VRChat):
   - browse mDNS for VRChat's  _oscjson._tcp  service
     (service names look like "VRChat-Client-XXXXXX")
   - fetch  http://<ip>:<port>/?HOST_INFO  and read OSC_IP / OSC_PORT
   - that is the REAL input port of the running VRChat instance
     (usually 9000, but different when several clients run or VRChat
     was started with a custom --osc launch option)

Requires the "zeroconf" package (pip install zeroconf). Everything
degrades gracefully: without zeroconf, HAS_ZEROCONF is False and the
app simply keeps using the manually configured target.
"""

import json
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from zeroconf import (IPVersion, ServiceBrowser, ServiceInfo,
                          ServiceListener, Zeroconf)
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False

OSCJSON_TYPE = "_oscjson._tcp.local."
OSC_TYPE = "_osc._udp.local."


def _local_ip():
    """Best-effort local IP (VRChat runs on the same machine in
    practice, so 127.0.0.1 is the safe default)."""
    return "127.0.0.1"


def _free_udp_port():
    """Asks the OS for a free UDP port (bind to 0) and KEEPS the
    socket so nobody else can grab the port. Returns (socket, port)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    return s, s.getsockname()[1]


# ----------------------------------------------------------------------------
# our own OSCQuery HTTP server
# ----------------------------------------------------------------------------
class _OSCQueryHandler(BaseHTTPRequestHandler):
    host_info = {}
    root_node = {}

    def do_GET(self):
        if "HOST_INFO" in self.path:
            payload = self.host_info
        else:
            payload = self.root_node
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):   # silence the default stderr spam
        pass


class OSCQueryService:
    """Registers OSC-DreamChatbox via OSCQuery/mDNS and discovers the
    running VRChat instance. Thread-safe; all network work happens in
    daemon threads."""

    def __init__(self, app_name, log_fn=print):
        self.app_name = app_name
        self.log = log_fn
        self._zc = None
        self._http = None
        self._http_thread = None
        self._infos = []
        self._udp_sock = None
        self.osc_port = None      # our dynamically chosen UDP port
        self.http_port = None     # our OSCQuery HTTP port
        self._lock = threading.Lock()
        self._vrchat = None       # (ip, port) once discovered
        self._browser = None
        self.error = ""

    # ------------------------------------------------------------ status
    @property
    def running(self):
        return self._zc is not None

    def vrchat_target(self):
        """(ip, port) of the discovered VRChat OSC input, or None."""
        with self._lock:
            return self._vrchat

    # ------------------------------------------------------- advertising
    def start(self):
        """Picks free ports, starts the OSCQuery HTTP server and
        announces both services via mDNS."""
        if not HAS_ZEROCONF:
            self.error = ("zeroconf is not installed "
                          "(pip install zeroconf)")
            return False
        if self.running:
            return True
        try:
            # 1) dynamic free UDP port (socket stays bound = reserved)
            self._udp_sock, self.osc_port = _free_udp_port()

            # 2) OSCQuery HTTP server on a free TCP port
            self._http = ThreadingHTTPServer(("127.0.0.1", 0),
                                             _OSCQueryHandler)
            self.http_port = self._http.server_address[1]
            _OSCQueryHandler.host_info = {
                "NAME": self.app_name,
                "OSC_IP": _local_ip(),
                "OSC_PORT": self.osc_port,
                "OSC_TRANSPORT": "UDP",
                "EXTENSIONS": {"ACCESS": True, "VALUE": True,
                               "DESCRIPTION": True},
            }
            _OSCQueryHandler.root_node = {
                "DESCRIPTION": self.app_name,
                "FULL_PATH": "/",
                "ACCESS": 0,
                "CONTENTS": {
                    # we only *send* (chatbox), but advertise the avatar
                    # namespace so VRChat treats us as a valid endpoint
                    "avatar": {"FULL_PATH": "/avatar", "ACCESS": 2},
                },
            }
            self._http_thread = threading.Thread(
                target=self._http.serve_forever, daemon=True)
            self._http_thread.start()

            # 3) announce via mDNS
            self._zc = Zeroconf(ip_version=IPVersion.V4Only)
            addr = socket.inet_aton(_local_ip())
            name = self.app_name.replace(" ", "-")
            self._infos = [
                ServiceInfo(OSCJSON_TYPE,
                            f"{name}.{OSCJSON_TYPE}",
                            addresses=[addr], port=self.http_port,
                            properties={}),
                ServiceInfo(OSC_TYPE,
                            f"{name}.{OSC_TYPE}",
                            addresses=[addr], port=self.osc_port,
                            properties={}),
            ]
            for info in self._infos:
                self._zc.register_service(info)
            self.log(f"OSCQuery: registered '{self.app_name}' "
                     f"(OSC udp/{self.osc_port}, "
                     f"HTTP tcp/{self.http_port}) via mDNS")

            # 4) start looking for VRChat
            self._browser = ServiceBrowser(self._zc, OSCJSON_TYPE,
                                           _VRChatListener(self))
            return True
        except Exception as e:
            self.error = str(e)
            self.log(f"OSCQuery: start failed: {e}")
            self.stop()
            return False

    def stop(self):
        try:
            if self._zc is not None:
                for info in self._infos:
                    try:
                        self._zc.unregister_service(info)
                    except Exception:
                        pass
                self._zc.close()
        except Exception:
            pass
        self._zc = None
        self._infos = []
        if self._http is not None:
            try:
                self._http.shutdown()
            except Exception:
                pass
            self._http = None
        if self._udp_sock is not None:
            try:
                self._udp_sock.close()
            except Exception:
                pass
            self._udp_sock = None
        with self._lock:
            self._vrchat = None

    # -------------------------------------------------------- discovery
    def _check_candidate(self, name, ip, port):
        """Called by the mDNS listener for every _oscjson service.
        VRChat instances are named 'VRChat-Client-…'. Fetch HOST_INFO
        and remember the OSC input target."""
        if "vrchat" not in name.lower():
            return
        try:
            url = f"http://{ip}:{port}/?HOST_INFO"
            with urllib.request.urlopen(url, timeout=3) as r:
                info = json.loads(r.read().decode("utf-8"))
            osc_ip = info.get("OSC_IP") or ip
            osc_port = int(info.get("OSC_PORT", 9000))
            with self._lock:
                changed = self._vrchat != (osc_ip, osc_port)
                self._vrchat = (osc_ip, osc_port)
            if changed:
                self.log(f"OSCQuery: VRChat found -> OSC input "
                         f"{osc_ip}:{osc_port} ('{name}')")
        except Exception as e:
            self.log(f"OSCQuery: could not read HOST_INFO of "
                     f"'{name}': {e}")

    def _lost_candidate(self, name):
        if "vrchat" not in name.lower():
            return
        with self._lock:
            self._vrchat = None
        self.log(f"OSCQuery: VRChat instance '{name}' disappeared")


if HAS_ZEROCONF:
    class _VRChatListener(ServiceListener):
        def __init__(self, svc):
            self.svc = svc

        def _handle(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=2000)
            if info is None or not info.addresses:
                return
            ip = socket.inet_ntoa(info.addresses[0])
            self.svc._check_candidate(name, ip, info.port)

        def add_service(self, zc, type_, name):
            threading.Thread(target=self._handle,
                             args=(zc, type_, name), daemon=True).start()

        def update_service(self, zc, type_, name):
            self.add_service(zc, type_, name)

        def remove_service(self, zc, type_, name):
            self.svc._lost_candidate(name)
else:
    class _VRChatListener:      # pragma: no cover – zeroconf missing
        def __init__(self, svc):
            pass
