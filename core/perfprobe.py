"""
core/perfprobe.py - opt-in performance probe.

Answers one question and nothing else: WHERE does this process burn CPU
on the machine that has the problem? A user cannot install py-spy into a
frozen .exe, and "it feels laggy" is not a bug report, so the app has to
be able to measure itself.

Off unless asked for. Enable with an environment variable:

    Windows (cmd):        set DCB_PERF=1 && OSC-DreamChatbox.exe
    Windows (PowerShell): $env:DCB_PERF=1; .\\OSC-DreamChatbox.exe
    Linux:                DCB_PERF=1 ./start.sh

    DCB_PERF_SEC=30   seconds between reports        (default 30)
    DCB_PERF_MS=20    stack sampling interval in ms  (default 20)

Reports go to the Debug Console AND to a file next to the config:

    Windows: %APPDATA%\\OSC-DreamChatbox\\perf-report.txt
    Linux:   ~/.config/OSC-DreamChatbox/perf-report.txt

Three independent measurements, because each one alone lies:

1. Per-thread CPU time (exact, from the OS)
   Windows GetThreadTimes(), Linux /proc/self/task/<tid>/stat. This is
   the ground truth: it counts CPU actually consumed, so a thread parked
   in recv() shows 0 no matter how it looks in a stack sample.

2. Stack sampling (where, not how much)
   Every DCB_PERF_MS the top-most frame of every thread that is inside
   this application is counted. Sampling on its own cannot tell busy
   from blocked - which is exactly what (1) is there to correct.

3. Wall-clock timing of the known pollers
   The QTimer slots and the two background fetches are wrapped and
   counted. A poller that takes 300 ms on the GUI thread is a stutter
   even if its total CPU share is small, and only this shows that.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")

#: methods on the main window that a timer drives. Missing ones are
#: skipped without complaint - the list has to survive a rename.
_WRAP_WINDOW = (
    "poll_hw", "poll_media", "poll_stt", "poll_mic_level",
    "update_preview", "build_payload", "send_now", "tick_graph",
    "advance_aio", "advance_status", "poll_oscquery", "_box_tick",
    "refresh_wintemp_status", "update_box_preview", "update_media_preview",
    "run_graph_automation",
)

#: (attribute path on the window, method name) - the work that runs in a
#: worker thread, where the wall-clock number IS the CPU number
_WRAP_ATTRS = (
    ("hw", "snapshot"),
    ("media", "fetch"),
    ("plugins", "values"),
)


#: Shared by arm() and install(), which run at different moments and
#: have to add to the same tally.
_CALLS = None


def enabled() -> bool:
    return (os.environ.get("DCB_PERF", "") or "").strip().lower() \
        in ("1", "true", "yes", "on")


def _env_num(name, default, lo, hi):
    try:
        return max(lo, min(hi, float(os.environ.get(name, "") or default)))
    except ValueError:
        return default


# ======================================================================
# 1. per-thread CPU time
# ======================================================================
class _ThreadCpu:
    """native thread id -> CPU seconds consumed since the process began.

    Returns {} when the platform has no cheap way to ask, which makes
    every caller degrade to the sampler on its own.
    """

    def __init__(self):
        self._k32 = None
        if IS_WINDOWS:
            try:
                import ctypes
                self._ctypes = ctypes
                self._k32 = ctypes.WinDLL("kernel32")
            except Exception:
                self._k32 = None

    def read(self):
        if IS_WINDOWS:
            return self._read_windows()
        return self._read_linux()

    def _read_windows(self):
        if self._k32 is None:
            return {}
        ctypes = self._ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            # ctypes reads _fields_ off the class; a ClassVar annotation
            # would be a lie about what it is
            _fields_ = [("low", wintypes.DWORD),   # noqa: RUF012
                        ("high", wintypes.DWORD)]

        def secs(ft):
            # FILETIME counts 100 ns ticks
            return ((ft.high << 32) | ft.low) / 1e7

        THREAD_QUERY_LIMITED_INFORMATION = 0x0800
        out = {}
        for t in threading.enumerate():
            tid = getattr(t, "native_id", None)
            if not tid:
                continue
            handle = self._k32.OpenThread(
                THREAD_QUERY_LIMITED_INFORMATION, False, int(tid))
            if not handle:
                continue
            try:
                created = FILETIME()
                exited = FILETIME()
                kernel = FILETIME()
                user = FILETIME()
                ok = self._k32.GetThreadTimes(
                    ctypes.c_void_p(handle),
                    ctypes.byref(created), ctypes.byref(exited),
                    ctypes.byref(kernel), ctypes.byref(user))
                if ok:
                    out[int(tid)] = secs(kernel) + secs(user)
            finally:
                self._k32.CloseHandle(ctypes.c_void_p(handle))
        return out

    @staticmethod
    def _read_linux():
        out = {}
        try:
            ticks = os.sysconf("SC_CLK_TCK") or 100
        except (ValueError, OSError):
            ticks = 100
        try:
            names = os.listdir("/proc/self/task")
        except OSError:
            return out
        for name in names:
            try:
                with open(f"/proc/self/task/{name}/stat", "rb") as fh:
                    raw = fh.read().decode("utf-8", "replace")
                # the comm field can contain spaces AND ')' - split on the
                # LAST ')' or the field offsets are wrong for a thread
                # named something like "gsmtc (poller)"
                fields = raw[raw.rfind(")") + 1:].split()
                # after comm and state, utime is field 11 and stime 12 in
                # proc(5) numbering; here that is index 11 and 12
                utime, stime = float(fields[11]), float(fields[12])
                out[int(name)] = (utime + stime) / ticks
            except (OSError, ValueError, IndexError):
                continue
        return out


def _thread_names():
    """(by native id, by ident) -> a readable name, so a report says
    'gsmtc-poller' rather than a number nobody can look up.

    Both maps exist because the two halves of this module are keyed
    differently and neither key is convertible into the other after the
    fact: the OS reports CPU time per NATIVE id, while
    sys._current_frames() is keyed by the Python IDENT. Only a live
    Thread object knows both.
    """
    by_native, by_ident = {}, {}
    for t in threading.enumerate():
        nid = getattr(t, "native_id", None)
        if nid:
            by_native[int(nid)] = t.name
        if t.ident:
            by_ident[t.ident] = t.name
    return by_native, by_ident


def _ident_name(ident):
    return f"thread {ident}"


# ======================================================================
# 2. stack sampler
# ======================================================================
class _Sampler(threading.Thread):
    """Counts the deepest frame that belongs to this application, per
    thread. Never touches Qt, never allocates per sample beyond a dict
    bump - it has to be able to run for an hour without becoming the
    thing it is measuring."""

    def __init__(self, root: Path, interval: float):
        super().__init__(name="dcb-perf-sampler", daemon=True)
        self._root = os.path.abspath(str(root)).lower()
        # the sampler measuring itself is the one result guaranteed to be
        # useless. Matched as a whole path, NOT as the substring
        # "perfprobe": anything else in the tree that happens to carry
        # the word in its name is real code and has to stay countable.
        self._self = os.path.abspath(__file__).lower()
        self._interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._known = {}                    # co_filename -> bool, see _mine
        # keyed by (thread ident, "file:line func") rather than by the
        # location alone. Sampling cannot tell a busy thread from a
        # blocked one, so every line has to stay attached to the thread
        # it came from - only then can the report pair it with that
        # thread's MEASURED cpu time and show which half is real.
        self.counts = defaultdict(int)
        self.per_thread = defaultdict(int)  # thread ident -> hits
        self.total = 0

    def _mine(self, filename: str) -> bool:
        """Is this frame our code?

        co_filename is whatever the import used, which can be relative
        ("ui/mainwindow.py" when started from the project folder) and is
        a _MEIPASS path in a frozen build. So it gets absolutised - and
        cached, because this runs for every frame of every thread fifty
        times a second and abspath() is a syscall-shaped thing.
        """
        hit = self._known.get(filename)
        if hit is None:
            low = os.path.abspath(filename).lower()
            hit = low.startswith(self._root) and low != self._self
            self._known[filename] = hit
        return hit

    def run(self):
        while not self._stop.wait(self._interval):
            try:
                frames = sys._current_frames()
            except Exception:
                continue
            # get_ident(), not get_native_id(): sys._current_frames() is
            # keyed by the ident, and on Linux the two are different
            # numbers - comparing the wrong one means the sampler happily
            # counts itself.
            me = threading.get_ident()
            rows = []
            for tid, frame in frames.items():
                if tid == me:
                    continue
                f = frame
                while f is not None:
                    code = f.f_code
                    if self._mine(code.co_filename):
                        where = (f"{Path(code.co_filename).name}:"
                                 f"{f.f_lineno} {code.co_name}()")
                        rows.append((tid, where))
                        break
                    f = f.f_back
                del f
            del frames
            with self._lock:
                self.total += 1
                for tid, key in rows:
                    self.counts[(tid, key)] += 1
                    self.per_thread[tid] += 1

    def snapshot(self):
        with self._lock:
            return dict(self.counts), dict(self.per_thread), self.total

    def stop(self):
        self._stop.set()


# ======================================================================
# 3. call timing
# ======================================================================
class _Calls:
    def __init__(self):
        self._lock = threading.Lock()
        self.data = defaultdict(lambda: [0, 0.0, 0.0])   # n, total, worst

    def wrap(self, label, fn):
        def wrapped(*a, **kw):
            t0 = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                dt = time.perf_counter() - t0
                with self._lock:
                    row = self.data[label]
                    row[0] += 1
                    row[1] += dt
                    row[2] = max(row[2], dt)
        wrapped.__name__ = getattr(fn, "__name__", label)
        wrapped._dcb_perf_wrapped = True
        return wrapped

    def snapshot(self):
        with self._lock:
            return {k: list(v) for k, v in self.data.items()}


# ======================================================================
# the probe
# ======================================================================
class Probe:
    def __init__(self, window, root: Path, report_path: Path,
                 report_sec: float, sample_ms: float):
        global _CALLS
        if _CALLS is None:
            _CALLS = _Calls()
        self.win = window
        self.report_path = report_path
        self.report_sec = report_sec
        self.calls = _CALLS
        self.cpu = _ThreadCpu()
        self.sampler = _Sampler(root, sample_ms / 1000.0)
        self._t0 = time.monotonic()
        self._last_cpu = self.cpu.read()
        self._last_at = self._t0
        self._round = 0

    # ---------------------------------------------------------- wiring
    def wrap_all(self):
        found = []
        # Anything arm() already handled is skipped by the flag. What is
        # left is caught here as a fallback - it will miss calls that a
        # timer connected during __init__, which is exactly why arm()
        # exists and should be preferred.
        for name in _WRAP_WINDOW:
            fn = getattr(self.win, name, None)
            if callable(fn) and not getattr(fn, "_dcb_perf_wrapped", False):
                setattr(self.win, name, self.calls.wrap(name, fn))
                found.append(name)
        for attr, name in _WRAP_ATTRS:
            obj = getattr(self.win, attr, None)
            fn = getattr(obj, name, None)
            if callable(fn) and not getattr(fn, "_dcb_perf_wrapped", False):
                label = f"{attr}.{name}"
                try:
                    setattr(obj, name, self.calls.wrap(label, fn))
                    found.append(label)
                except (AttributeError, TypeError):
                    pass          # slots / read-only object, skip it
        return found

    # --------------------------------------------------------- reading
    def _rss_mb(self):
        try:
            if IS_WINDOWS:
                import ctypes
                from ctypes import wintypes

                class PMC(ctypes.Structure):
                    _fields_ = [("cb", wintypes.DWORD),
                                ("PageFaultCount", wintypes.DWORD),
                                ("PeakWorkingSetSize", ctypes.c_size_t),
                                ("WorkingSetSize", ctypes.c_size_t),
                                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                                ("PagefileUsage", ctypes.c_size_t),
                                ("PeakPagefileUsage", ctypes.c_size_t)]

                pmc = PMC()
                pmc.cb = ctypes.sizeof(PMC)
                psapi = ctypes.WinDLL("psapi")
                k32 = ctypes.WinDLL("kernel32")
                if psapi.GetProcessMemoryInfo(
                        ctypes.c_void_p(k32.GetCurrentProcess()),
                        ctypes.byref(pmc), pmc.cb):
                    return pmc.WorkingSetSize / (1024 * 1024)
            else:
                with open("/proc/self/statm", "rb") as fh:
                    pages = int(fh.read().split()[1])
                return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
        except Exception:
            pass
        return None

    def _gc_counts(self):
        try:
            import gc
            objs = len(gc.get_objects())
            return objs
        except Exception:
            return None

    # ---------------------------------------------------------- report
    def report(self):
        self._round += 1
        now = time.monotonic()
        window = max(0.001, now - self._last_at)
        cpu_now = self.cpu.read()
        prev_cpu = self._last_cpu
        names, idents = _thread_names()

        lines = []
        add = lines.append
        add("=" * 68)
        add(f" OSC-DreamChatbox performance report #{self._round}"
            f"   (last {window:.0f}s, uptime {now - self._t0:.0f}s)")
        add("=" * 68)

        rss = self._rss_mb()
        objs = self._gc_counts()
        add(f" RSS: {rss:.0f} MB" if rss is not None else " RSS: unknown")
        if objs is not None:
            add(f" live Python objects: {objs}")
        add(f" threads: {threading.active_count()}")

        # -- 1. CPU per thread -------------------------------------
        add("")
        add(" CPU per thread (exact - a blocked thread reads 0)")
        add(" " + "-" * 66)
        deltas = []
        total_delta = 0.0
        for tid, used in cpu_now.items():
            before = prev_cpu.get(tid)
            if before is None:
                continue
            d = used - before
            if d <= 0.0005:
                continue
            deltas.append((d, tid))
            total_delta += d
        deltas.sort(reverse=True)
        if not deltas:
            add("   (no measurable CPU - or this platform will not say)")
        for d, tid in deltas[:12]:
            pct = 100.0 * d / window
            add(f"   {pct:6.1f}% of one core   {d:7.2f}s   "
                f"{names.get(tid, '?')} (tid {tid})")
        add(f"   {'-' * 20}")
        add(f"   {100.0 * total_delta / window:6.1f}% of one core   "
            f"total across all threads")

        # -- 2. where the time is spent ----------------------------
        # Grouped BY THREAD and headed with that thread's measured CPU,
        # because the two numbers only mean something together: a thread
        # parked in recv() spends 100% of its samples on one line while
        # costing nothing. Read the percentages under a 0.0% heading as
        # "where this thread waits", not "where the CPU goes".
        counts, per_thread, total = self.sampler.snapshot()
        cpu_by_ident = {}
        for t in threading.enumerate():
            nid = getattr(t, "native_id", None)
            if nid and t.ident:
                before = prev_cpu.get(int(nid))
                nowv = cpu_now.get(int(nid))
                if before is not None and nowv is not None:
                    cpu_by_ident[t.ident] = max(0.0, nowv - before)

        add("")
        add(f" Hottest code per thread ({total} stack samples since start)")
        add(" " + "-" * 66)
        if not counts:
            add("   (nothing of ours was ever on top - the time is going"
                " into Qt, a driver or a C extension)")
        by_thread = defaultdict(list)
        for (ident, key), n in counts.items():
            by_thread[ident].append((n, key))
        order = sorted(by_thread, key=lambda i: -cpu_by_ident.get(i, -1.0))
        for ident in order[:8]:
            hits = per_thread.get(ident, 0) or 1
            used = cpu_by_ident.get(ident)
            head = idents.get(ident) or _ident_name(ident)
            if used is None:
                add(f"   {head} - cpu unknown ({hits} samples)")
            else:
                add(f"   {head} - {100.0 * used / window:.1f}% of one core "
                    f"({hits} samples)")
            for n, key in sorted(by_thread[ident], reverse=True)[:6]:
                add(f"       {100.0 * n / hits:5.1f}%  {n:6d}  {key}")

        # -- 3. pollers --------------------------------------------
        add("")
        add(" Pollers (wall clock - a slow one on the GUI thread stutters)")
        add(" " + "-" * 66)
        rows = self.calls.snapshot()
        if not rows:
            add("   (nothing wrapped)")
        for label, (n, tot, worst) in sorted(
                rows.items(), key=lambda kv: -kv[1][1])[:18]:
            avg = 1000.0 * tot / n if n else 0.0
            add(f"   {label:<26} {n:6d} calls  avg {avg:7.1f} ms  "
                f"worst {1000.0 * worst:7.1f} ms  total {tot:6.1f}s")

        add("=" * 68)
        text = "\n".join(lines)

        self._last_cpu = cpu_now
        self._last_at = now

        try:
            with open(self.report_path, "a", encoding="utf-8") as fh:
                fh.write(text + "\n\n")
        except OSError:
            pass
        return text


# ======================================================================
def arm(window_class):
    """Wrap the window's methods on the CLASS, before it is built.

    This has to happen first, and it cannot be folded into install().
    MainWindow.__init__ does ``self.hw_timer.timeout.connect(self.poll_hw)``,
    and a Qt connection stores the bound method it was handed. Replacing
    the attribute on the instance afterwards therefore changes what
    ``self.poll_hw()`` means everywhere EXCEPT in the timers - which are
    the only callers that matter here. Patching the class before
    construction means the connect() call binds the wrapper instead.

    Returns the list of wrapped names (empty when the probe is off).
    """
    global _CALLS
    if not enabled():
        return []
    if _CALLS is None:
        _CALLS = _Calls()
    done = []
    for name in _WRAP_WINDOW:
        fn = getattr(window_class, name, None)
        if callable(fn) and not getattr(fn, "_dcb_perf_wrapped", False):
            try:
                setattr(window_class, name, _CALLS.wrap(name, fn))
                done.append(name)
            except (AttributeError, TypeError):
                pass
    return done


def install(window, log=None):
    """Turns the probe on if DCB_PERF says so. Returns the Probe or None.

    Safe to call unconditionally: everything below only happens when the
    variable is set, and any failure in here is swallowed - a broken
    probe must never be the reason the app does not start.
    """
    if not enabled():
        return None
    log = log or getattr(window, "log", None) or (lambda m: None)
    try:
        root = Path(__file__).resolve().parent.parent
        try:
            from core.constants import CONFIG_DIR
            report = Path(CONFIG_DIR) / "perf-report.txt"
        except Exception:
            report = root / "perf-report.txt"
        report.parent.mkdir(parents=True, exist_ok=True)

        report_sec = _env_num("DCB_PERF_SEC", 30, 5, 3600)
        sample_ms = _env_num("DCB_PERF_MS", 20, 5, 500)

        probe = Probe(window, root, report, report_sec, sample_ms)
        wrapped = probe.wrap_all()
        probe.sampler.start()

        from PyQt6.QtCore import QTimer
        timer = QTimer(window)
        timer.timeout.connect(lambda: log("\n" + probe.report()))
        timer.start(int(report_sec * 1000))
        probe._timer = timer          # keep it alive

        log(f"Performance probe ON - report every {report_sec:.0f}s to "
            f"{report}. Watching {len(wrapped)} callables, sampling every "
            f"{sample_ms:.0f} ms.")
        return probe
    except Exception as e:
        log(f"Performance probe could not start ({type(e).__name__}: {e}).")
        return None
