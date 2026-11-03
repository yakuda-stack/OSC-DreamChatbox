"""
core/backends/netstats.py – download and upload speed

One connection is reported. Automatic takes the real connection that has
moved the most data so far, skipping virtual ones: a VPN or a Docker
bridge counts the same traffic a second time. The Hardware card can name
one instead.

Nothing here runs until a Network tick is on, so nobody pays for a value
they did not ask for.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
import time

_VIRTUAL = re.compile(
    r"^(lo|docker|veth|br-|virbr|vnet|tun|tap|wg|tailscale|zt)|"
    r"loopback|isatap|teredo|virtual|vethernet|hyper-v|wsl|vpn|"
    r"pseudo|wan miniport", re.IGNORECASE)


def is_virtual(name):
    return bool(_VIRTUAL.search(name or ""))


def pick_interface(totals, selected=None):
    """The connection to report, from {name: bytes moved}, or None."""
    if selected and selected in totals:
        return selected
    real = [n for n in totals if not is_virtual(n)]
    if not real:
        return None
    return max(sorted(real), key=lambda n: totals[n])


def parse_proc_net(text):
    """/proc/net/dev -> {interface: (received, sent)} in bytes."""
    out = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        cols = rest.split()
        try:
            out[name.strip()] = (int(cols[0]), int(cols[8]))
        except (IndexError, ValueError):
            continue
    return out


class LinuxNetSource:
    """Counters of /proc/net/dev turned into speeds."""

    def __init__(self, path="/proc/net/dev"):
        self.path = path
        self.totals = {}
        self._prev = {}
        self._prev_at = 0.0

    def sample(self):
        """-> {interface: (down, up)} in bytes per second. Empty on the
        first call, a speed needs two readings."""
        with open(self.path, encoding="utf-8") as f:
            now_counters = parse_proc_net(f.read())
        now = time.monotonic()
        seconds = now - self._prev_at
        rates = {}
        if self._prev and seconds > 0:
            for name, (rx, tx) in now_counters.items():
                old = self._prev.get(name)
                if old is None or rx < old[0] or tx < old[1]:
                    continue        # a new interface, or a counter reset
                rates[name] = ((rx - old[0]) / seconds,
                               (tx - old[1]) / seconds)
        self._prev, self._prev_at = now_counters, now
        self.totals = {n: rx + tx for n, (rx, tx) in now_counters.items()}
        return rates


class NetMonitor:
    """Starts the source on first use and picks the connection.

    `factory` builds the source; on Windows that opens a performance
    counter query, which is the reason it waits until a tick is on.
    """

    def __init__(self, factory, log=None):
        self._factory = factory
        self.log = log
        self.enabled = False
        self.selected = None
        self._source = None
        self._failed = False

    def configure(self, enabled, interface=None):
        self.enabled = bool(enabled)
        self.selected = interface or None

    def read(self):
        """{"down", "up", "interface", "names"}, or None while off."""
        if not self.enabled or self._failed:
            return None
        try:
            if self._source is None:
                self._source = self._factory()
            rates = self._source.sample()
        except Exception as e:
            self._failed = True
            if callable(self.log):
                self.log(f"Hardware: network speed unavailable ({e}).")
            return None
        totals = self._source.totals
        name = pick_interface(totals, self.selected)
        down, up = rates.get(name, (None, None))
        return {"down": down, "up": up, "interface": name,
                "names": sorted(totals)}
