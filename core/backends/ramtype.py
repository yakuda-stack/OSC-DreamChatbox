"""
core/backends/ramtype.py – which memory generation is installed

The SMBIOS tables say it. Windows hands them to a normal user through
WMI; on Linux they are readable by root only, so a normal start gets
nothing and the Hardware card's Manual field is the way there.

It cannot change while the app runs, so it is asked once, on a thread of
its own, because PowerShell takes a second or two to start and the first
hardware poll should not wait for that.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import glob
import threading

#: SMBIOS memory device type -> name
SMBIOS_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 29: "LPDDR3",
                30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}

#: offset of the memory type inside an SMBIOS type 17 structure
_TYPE_OFFSET = 0x12


def first_known(codes):
    """The name of the first code that means something, or None. Empty
    slots report 0 or 2 ("unknown"), so this cannot just take the first."""
    for code in codes:
        name = SMBIOS_TYPES.get(code)
        if name:
            return name
    return None


def linux_ram_type(pattern="/sys/firmware/dmi/entries/17-*/raw"):
    codes = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        if len(raw) > _TYPE_OFFSET:
            codes.append(raw[_TYPE_OFFSET])
    return first_known(codes)


def parse_wmi_output(text):
    """The lines PowerShell printed -> a memory type name, or None."""
    codes = []
    for line in (text or "").splitlines():
        try:
            codes.append(int(line.strip()))
        except ValueError:
            continue
    return first_known(codes)


class RamTypeProbe:
    """Runs `detect` once in the background. get() never blocks."""

    def __init__(self, detect):
        self._detect = detect
        self._started = False
        self._result = None

    def get(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True,
                             name="ram-type").start()
        return self._result

    def _run(self):
        try:
            self._result = self._detect()
        except Exception:
            self._result = None
