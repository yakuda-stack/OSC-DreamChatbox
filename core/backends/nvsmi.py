"""
core/backends/nvsmi.py – reading nvidia-smi, shared by Linux and Windows

Both backends keep one long-running `nvidia-smi --loop` instead of
starting a process for every poll. Linux has done that for a long time;
it lives here so Windows gets the same thing and the two cannot drift.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import subprocess
import sys
import threading
import time

_JOB_LIMIT_KILL_ON_CLOSE = 0x00002000
_JOB_EXTENDED_LIMIT_INFO_CLASS = 9
#: sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION) on 64-bit Windows, with
#: LimitFlags 16 bytes in
_JOB_INFO_SIZE = 144
_JOB_FLAGS_OFFSET = 16


def query_for(exe="nvidia-smi", creationflags=0):
    """The fields to ask for on this machine.

    An unknown field fails the whole query, not just its column, and
    temperature.memory is the one field older drivers do not know. So it
    is tried once on its own. Its column goes last, which keeps every
    other column in the same place with or without it.
    """
    try:
        probe = subprocess.run(
            [exe, "--query-gpu=temperature.memory",
             "--format=csv,noheader"], capture_output=True, text=True,
            timeout=3, creationflags=creationflags)
    except Exception:
        return _NvidiaSmiLoop.QUERY
    if probe.returncode != 0:
        return _NvidiaSmiLoop.QUERY
    return _NvidiaSmiLoop.QUERY + ",temperature.memory"


def _bind_to_app(proc, job=None):
    """Windows: tie a child process to this one. -> the job handle.

    A job object closes with its last handle, ours, and takes the process
    with it however the app ended. Best effort: without it a crash can
    leave one nvidia-smi behind, nothing worse.
    """
    if sys.platform != "win32":
        return job
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        k32.SetInformationJobObject.argtypes = (
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)
        k32.AssignProcessToJobObject.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p)
        if job is None:
            job = k32.CreateJobObjectW(None, None)
            info = ctypes.create_string_buffer(_JOB_INFO_SIZE)
            ctypes.c_ulong.from_buffer(info, _JOB_FLAGS_OFFSET).value = \
                _JOB_LIMIT_KILL_ON_CLOSE
            k32.SetInformationJobObject(
                job, _JOB_EXTENDED_LIMIT_INFO_CLASS, info, _JOB_INFO_SIZE)
        k32.AssignProcessToJobObject(job, int(proc._handle))
    except Exception:
        pass
    return job


def _optional(cols, index):
    """One column that may be missing or "[N/A]", as a float or None."""
    try:
        return float(cols[index])
    except (IndexError, ValueError):
        return None


def _nvsmi_index(line):
    """The index column of an nvidia-smi CSV line, or None."""
    if not line:
        return None
    try:
        return int(float(line.split(",", 1)[0].strip()))
    except (IndexError, ValueError):
        return None


def _parse_nvsmi(line, index=None):
    """'0, 41, 55, 1234, 8192, 120.5' -> the gpu() dict, or None.

    `index` is the card the caller wants: a line from another card is
    rejected, because with --loop every card prints its own line and the
    index column is what tells them apart. None accepts any line, which
    is what the single-card fallback path wants.
    """
    if not line:
        return None
    cols = [c.strip() for c in line.split(",")]
    try:
        if index is not None and int(float(cols[0])) != index:
            return None
        u, t, mu, mt = [float(x) for x in cols[1:5]]
    except (IndexError, ValueError):
        return None
    # power.draw reads "[N/A]" on cards that do not report it, and asking
    # for it must not cost us the four values that always work - hence
    # parsed separately
    try:
        power = float(cols[5])
    except (IndexError, ValueError):
        power = None
    return {"usage": u, "temp": t, "power": power,
            "vram_used": mu / 1024.0, "vram_total": mt / 1024.0,
            "vram_pct": 100.0 * mu / mt if mt else None,
            "fan": _optional(cols, 6), "clock": _optional(cols, 7),
            "vram_clock": _optional(cols, 8),
            "vram_temp": _optional(cols, 9)}


class _NvidiaSmiLoop:
    """One long-running nvidia-smi instead of a new process per poll.

    `nvidia-smi --loop=N` prints a fresh CSV line every N seconds; a
    reader thread keeps the newest one. Starting a process every two
    seconds costs far more than reading a line from a pipe that is
    already there.

    Tidying up:
      * `close()` on app exit (ui/mainwindow.py closeEvent)
      * no poll for IDLE_STOP_SEC (Hardware card switched off) stops the
        process; the next call starts it again
      * if the app dies without closing, nvidia-smi writes into a pipe
        with no reader and gets SIGPIPE on its next line. Windows has no
        SIGPIPE, there a job object takes the process down with the app
    """

    QUERY = ("index,utilization.gpu,temperature.gpu,"
             "memory.used,memory.total,power.draw,"
             "fan.speed,clocks.gr,clocks.mem")
    IDLE_STOP_SEC = 15

    def __init__(self, interval=2, log_fn=print, exe="nvidia-smi",
                 creationflags=0):
        self.interval = interval
        self.log = log_fn
        self.exe = exe
        self.creationflags = creationflags
        self.query = query_for(exe, creationflags)
        self._job = None           # Windows, see _bind_to_app()
        self.broken = False        # fall back to one call per poll
        self._proc = None
        #: index -> (csv line, monotonic time). Every card gets its own
        #: entry since v1.5.1: keeping only card 0 made a second NVIDIA
        #: card unreadable even though its line was already in the pipe.
        self._lines = {}
        self._last_ask = 0.0
        self._fails = 0
        self._lock = threading.Lock()
        self._have_line = threading.Event()

    # ------------------------------------------------------------ read
    def latest(self, index=0, wait=3.0):
        """Newest CSV line of one card, or None. Starts the process if
        needed."""
        with self._lock:
            self._last_ask = time.monotonic()
            start_now = self._proc is None or self._proc.poll() is not None
            if start_now:
                self._start_locked()
        self._have_line.wait(wait)          # only waits on the first line
        with self._lock:
            entry = self._lines.get(index)
            if entry is None:
                return None
            line, stamp = entry
            stale = time.monotonic() - stamp > 3 * self.interval + 2
            return None if stale else line

    def _start_locked(self):
        self._lines = {}
        self._have_line.clear()
        try:
            self._proc = subprocess.Popen(
                [self.exe, f"--query-gpu={self.query}",
                 "--format=csv,noheader,nounits", f"--loop={self.interval}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, creationflags=self.creationflags)
        except Exception as e:
            self._proc = None
            self._fail(f"could not be started ({e})")
            return
        self._job = _bind_to_app(self._proc, self._job)
        threading.Thread(target=self._reader, args=(self._proc,),
                         daemon=True, name="nvidia-smi-loop").start()

    def _reader(self, proc):
        got_line = False
        for raw in proc.stdout:
            line = raw.strip()
            # every card prints its own line per round, and all of them
            # are kept - which card is reported is decided by the caller
            idx = _nvsmi_index(line)
            if idx is None:
                continue
            with self._lock:
                if proc is not self._proc:      # replaced or closed
                    return
                self._lines[idx] = (line, time.monotonic())
                self._fails = 0
                idle = time.monotonic() - self._last_ask > self.IDLE_STOP_SEC
            got_line = True
            self._have_line.set()
            if idle:
                self.close()                    # Hardware card is off
                return
        # process ended on its own
        self._have_line.set()
        if not got_line:
            with self._lock:
                if proc is self._proc:
                    self._fail("ended without a line")

    def _fail(self, why):
        """Three starts without a single line: stop trying the loop and
        let gpu() go back to one call per poll (old driver, no --loop)."""
        self._fails += 1
        if self._fails >= 3 and not self.broken:
            self.broken = True
            self.log(f"Hardware: nvidia-smi --loop {why} - "
                     "falling back to one call per poll")

    # ----------------------------------------------------------- close
    def close(self):
        with self._lock:
            proc, self._proc = self._proc, None
            self._lines = {}
        self._have_line.set()
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
