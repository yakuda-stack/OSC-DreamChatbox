"""
oscrouter.py – OSC routing for OSC-DreamChatbox

A tiny UDP relay: other OSC programs (OSC Leash, face tracking, ...) send
to OUR listen port instead of VRChat's 9000 directly. We forward every
packet untouched (bundles included) to VRChat through ONE socket. That
avoids port conflicts and lets you see & control which programs are
talking to VRChat.

Per-source control: senders are grouped by their address (ip:port).
Disabled sources are dropped instead of forwarded.
"""

import socket
import threading
import time


def _osc_addr(data: bytes) -> str:
    """Extracts the OSC address of a datagram for display purposes."""
    if data[:1] == b"/":
        end = data.find(b"\0")
        if end > 0:
            return data[:end].decode("ascii", errors="replace")
    if data[:7] == b"#bundle":
        return "#bundle"
    return "?"


class OSCRouter:
    def __init__(self, log_fn=print):
        self.log = log_fn
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # key "ip:port" -> {"count": int, "last_addr": str, "last_seen": float,
        #                   "blocked": bool}
        self.sources = {}
        self.listen_port = 9101
        self.target = ("127.0.0.1", 9000)
        self.error = ""

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def set_target(self, ip, port):
        self.target = (ip, port)

    def set_blocked(self, key, blocked):
        with self._lock:
            if key in self.sources:
                self.sources[key]["blocked"] = blocked

    def snapshot(self):
        with self._lock:
            return {k: dict(v) for k, v in self.sources.items()}

    def start(self, listen_port, blocked_keys=()):
        if self.running:
            self.stop()
        self.listen_port = listen_port
        self.error = ""
        with self._lock:
            for k in blocked_keys:
                self.sources.setdefault(
                    k, {"count": 0, "last_addr": "?", "last_seen": 0.0,
                        "blocked": True})["blocked"] = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    # ------------------------------------------------------------------ loop
    def _run(self):
        try:
            recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            recv.bind(("0.0.0.0", self.listen_port))
            recv.settimeout(0.5)
        except Exception as e:
            self.error = f"Could not open port {self.listen_port}: {e}"
            self.log(f"OSC Routing ERROR: {self.error}")
            return
        send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.log(f"OSC Routing: listening on 0.0.0.0:{self.listen_port} "
                 f"-> forwarding to {self.target[0]}:{self.target[1]}")
        try:
            while not self._stop.is_set():
                try:
                    data, sender = recv.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break
                key = f"{sender[0]}:{sender[1]}"
                with self._lock:
                    src = self.sources.setdefault(
                        key, {"count": 0, "last_addr": "?",
                              "last_seen": 0.0, "blocked": False})
                    src["count"] += 1
                    src["last_addr"] = _osc_addr(data)
                    src["last_seen"] = time.time()
                    blocked = src["blocked"]
                if not blocked:
                    try:
                        send.sendto(data, self.target)
                    except Exception:
                        pass
        finally:
            recv.close()
            send.close()
            self.log("OSC Routing: stopped")
