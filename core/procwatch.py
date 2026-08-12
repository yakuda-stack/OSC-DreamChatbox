"""
core/procwatch.py – "is this program running right now?"

Feeds the "Program running" block on the Advanced canvas, which is what
makes "when VRChat starts, launch these three things" possible.

Polled, not evented. There is a portable way to ask for the list of
processes and no portable way to be told when one appears, and for a
question answered every couple of seconds a poll is both simpler and
good enough - a launcher does not need to know within 50 ms.

The list is shared: every block asking about a different program reads
the same snapshot, so ten watcher blocks still cost one scan.

One backend per platform and no optional ones: /proc on Linux, the
Toolhelp snapshot API through ctypes on Windows. An optional psutil path
used to sit in front of both, which meant the list of programs offered
in the picker quietly depended on whether an unrelated package happened
to be installed - and psutil reports kernel threads, so it filled the
list with several hundred kworkers.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys
import threading
import time

IS_WINDOWS = sys.platform.startswith("win")

#: how stale an answer may be. Two seconds keeps a launch feeling
#: immediate without scanning /proc on every frame.
TTL = 2.0


class ProcessWatcher:
    """Set of running process names, refreshed at most every TTL."""

    def __init__(self, log_fn=print):
        self.log = log_fn
        self._lock = threading.Lock()
        self._names = set()
        self._stamp = 0.0
        self._failed = False

    # ------------------------------------------------------------------
    def names(self):
        """The current process names, lower-cased. Refreshed lazily, so
        a canvas with no watcher block never scans anything at all."""
        now = time.monotonic()
        with self._lock:
            fresh = now - self._stamp < TTL
            if fresh:
                return self._names
        try:
            found = self._scan()
        except Exception as e:      # noqa: BLE001
            if not self._failed:
                self._failed = True
                self.log(f"Process watch: cannot read the process list "
                         f"({e})")
            found = set()
        with self._lock:
            self._names = found
            self._stamp = now
            return found

    def is_running(self, needle):
        """True when a running process matches.

        Substring, case-insensitive, and matched against the executable
        name: people write "vrchat", the process is "VRChat.exe" under
        Proton and "VRChat" native. Asking them which one is asking them
        to know something they have no reason to know.
        """
        needle = str(needle or "").strip().lower()
        if not needle:
            return False
        return any(needle in name for name in self.names())

    def matches(self, needle):
        needle = str(needle or "").strip().lower()
        if not needle:
            return []
        return sorted(n for n in self.names() if needle in n)

    # ------------------------------------------------------------------
    def _scan(self):
        if IS_WINDOWS:
            return self._scan_windows()
        return self._scan_proc()

    @staticmethod
    def _scan_proc():
        found = set()
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                # a kernel thread has an empty cmdline and a real process
                # never does - the cheapest way to keep the several
                # hundred kworkers out of a list a person has to read
                with open(f"/proc/{entry}/cmdline", "rb") as fh:
                    if not fh.read(1):
                        continue
                with open(f"/proc/{entry}/comm", "rb") as fh:
                    name = fh.read().decode("utf-8", "replace").strip()
            except OSError:
                # the process ended between listdir and open, which is
                # normal and not worth a log line
                continue
            if name:
                found.add(name.lower())
        return found

    @staticmethod
    def _scan_windows():
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        INVALID = ctypes.c_void_p(-1).value

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        k32 = ctypes.windll.kernel32
        snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID:
            raise OSError("CreateToolhelp32Snapshot failed")
        found = set()
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                if entry.szExeFile:
                    found.add(entry.szExeFile.lower())
                ok = k32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snapshot)
        return found
