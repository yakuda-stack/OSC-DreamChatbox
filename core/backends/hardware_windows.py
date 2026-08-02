"""
core/backends/hardware_windows.py – Hardware monitoring on Windows

Linux has one honest answer for every value: /proc, /sys, hwmon. Windows
has none. There is no single API that gives CPU load, GPU load, VRAM and
temperatures together, and temperatures are not readable at all from a
normal user process – they need a signed kernel driver.

So this backend stacks four sources, from "always works" to "only if the
user installed something". Every one of them is optional and isolated:
if a source is missing or throws, its values stay None and the rest keeps
working. That is the same contract the Linux backend has (a machine
without hwmon, or without MangoHud, reports None too), and the Hardware
card already renders None as "leave this out".

    1. Win32 API via ctypes            – stdlib, no install, always on
       GetSystemTimes()                  CPU usage
       GlobalMemoryStatusEx()            RAM used/total
       winreg                            CPU name, GPU name, VRAM total

    2. PDH performance counters        – stdlib, no install, Win10 1709+
       \\GPU Engine(*)\\Utilization Percentage      GPU usage (any vendor)
       \\GPU Process Memory(*)\\Dedicated Usage     VRAM used (any vendor)
       This is exactly what the Task Manager's GPU column reads.

    3. nvidia-smi                      – ships with every NVIDIA driver
       Preferred when present: gives usage, temperature and VRAM in one
       call, and it is the only no-extra-software temperature source.

    4. LibreHardwareMonitor            – optional, user installs it
       LHM has a built-in web server (Options -> Remote Web Server).
       Switch it on and it serves every sensor as JSON on port 8085.
       That is where AMD/Intel GPU temps and ANY CPU temp come from.
       Auto-detected, no configuration: if LHM is not running we simply
       never get temperatures, exactly like a Linux box without hwmon.

    FPS: RivaTuner Statistics Server (RTSS) shared memory, the same
    source MSI Afterburner's overlay uses. It is the Windows counterpart
    to MangoHud – auto-detected, nothing to configure.

Two environment variables exist as an escape hatch until the Options page
gets proper rows for this (step 2b):

    DCB_LHM_URL       default http://localhost:8085/data.json
    DCB_FPS_PROCESS   substring of the game's .exe, default "vrchat"

Run this file directly to see which sources work on a given machine:

    python -m core.backends.hardware_windows
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

GB = 1024 ** 3

# how long a dead optional source is not retried again (seconds)
_RETRY_LHM = 60.0
_RETRY_RTSS = 10.0

# keeps subprocess calls from flashing a console window in a windowed
# (console=False) PyInstaller build - without this every nvidia-smi poll
# blinks a black box over the game
_CREATE_NO_WINDOW = 0x08000000


def _run(cmd, timeout=3):
    """subprocess.run for a GUI app: no console flash, never raises."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW).stdout.strip()
    except Exception:
        return ""


def _num(text):
    """'45,2 °C' / '45.2 C' / '  61 %' -> 45.2 / 61.0, else None.
    The comma case is real: LHM formats with the system locale."""
    if text is None:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(text))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def _clean_cpu_name(name: str) -> str:
    """'AMD Ryzen 7 9700X 8-Core Processor' -> 'Ryzen 7 9700X'"""
    name = re.sub(r"\(R\)|\(TM\)|\(r\)|\(tm\)", "", name)
    name = re.sub(r"^(AMD|Intel|Intel Core)\s+", "", name, flags=re.I)
    name = re.sub(r"\s+(CPU|Processor)\b.*$", "", name, flags=re.I)
    name = re.sub(r"\s+\d+-Core.*$", "", name, flags=re.I)
    name = re.sub(r"\s+@.*$", "", name)
    return re.sub(r"\s+", " ", name).strip()


def _clean_gpu_name(name: str) -> str:
    """'NVIDIA GeForce RTX 5060 Ti' -> 'RTX 5060 Ti'
    'AMD Radeon RX 9070 XT' -> 'RX 9070 XT'"""
    # (R)/(TM) must go first and NOT inside the \b group: a word boundary
    # never matches before "(", so 'Intel(R) Arc(TM) A770' would keep the
    # markers and come out as '(R) (TM) A770'
    name = re.sub(r"\(R\)|\(TM\)|\(r\)|\(tm\)", " ", name)
    name = re.sub(r"\b(NVIDIA|GeForce|AMD|ATI|Radeon Graphics|Radeon|"
                  r"Intel|Arc|Graphics)\b", " ", name)
    return re.sub(r"\s+", " ", name).strip() or name.strip()


# ====================================================================
# 1. Win32 API via ctypes
# ====================================================================
class _Win32:
    """CPU load and RAM straight from kernel32. No dependencies."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD),
                        ("dwHighDateTime", wintypes.DWORD)]

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD),
                        ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        self._FILETIME = FILETIME
        self._MEMORYSTATUSEX = MEMORYSTATUSEX
        self._prev = None      # (idle, total) from the last call

    @staticmethod
    def _ft(ft):
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

    def cpu_usage(self):
        """Percent since the previous call. First call returns None -
        same priming behaviour as the Linux /proc/stat reader."""
        idle, kern, user = (self._FILETIME(), self._FILETIME(),
                            self._FILETIME())
        ok = self.k32.GetSystemTimes(self.ctypes.byref(idle),
                                     self.ctypes.byref(kern),
                                     self.ctypes.byref(user))
        if not ok:
            return None
        # NOTE: kernel time INCLUDES idle time, so total = kernel + user
        i, k, u = self._ft(idle), self._ft(kern), self._ft(user)
        total = k + u
        if self._prev is None:
            self._prev = (i, total)
            return None
        p_idle, p_total = self._prev
        self._prev = (i, total)
        d_total = total - p_total
        d_idle = i - p_idle
        if d_total <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (d_total - d_idle) / d_total))

    def ram(self):
        st = self._MEMORYSTATUSEX()
        st.dwLength = self.ctypes.sizeof(self._MEMORYSTATUSEX)
        if not self.k32.GlobalMemoryStatusEx(self.ctypes.byref(st)):
            return None
        total = st.ullTotalPhys
        avail = st.ullAvailPhys
        if not total:
            return None
        used = total - avail
        return {"used": used / GB, "total": total / GB,
                "pct": 100.0 * used / total}


def _registry_cpu_name():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        with key:
            return _clean_cpu_name(
                winreg.QueryValueEx(key, "ProcessorNameString")[0])
    except Exception:
        return ""


# display adapter class GUID - one subkey (0000, 0001, ...) per adapter
_GPU_CLASS = r"SYSTEM\CurrentControlSet\Control\Class" \
             r"\{4d36e968-e325-11ce-bfc1-08002be10318}"


def _registry_gpu():
    """(name, vram_total_bytes) of the adapter with the most VRAM.

    Picking by VRAM size skips the Microsoft Basic Display Adapter and,
    on a laptop, prefers the dedicated card over the iGPU.
    """
    best = ("", 0)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _GPU_CLASS) as root:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        desc = winreg.QueryValueEx(k, "DriverDesc")[0]
                        if "Basic Display" in desc:
                            continue
                        try:
                            vram = int(winreg.QueryValueEx(
                                k, "HardwareInformation.qwMemorySize")[0])
                        except Exception:
                            vram = 0
                        if vram >= best[1]:
                            best = (desc, vram)
                except OSError:
                    continue
    except Exception:
        pass
    return best


# ====================================================================
# 2. PDH performance counters (GPU usage + VRAM, any vendor)
# ====================================================================
_PDH_FMT_DOUBLE = 0x00000200
_PDH_MORE_DATA = 0x800007D2
_PDH_CSTATUS_VALID = (0x00000000, 0x00000800)   # VALID_DATA, NEW_DATA

_C_GPU_UTIL = r"\GPU Engine(*)\Utilization Percentage"
_C_GPU_VRAM = r"\GPU Process Memory(*)\Dedicated Usage"


class _PdhGpu:
    """Wildcard PDH query, kept open across polls.

    Utilization Percentage needs two samples, so the query is primed once
    at construction; from the second poll on the values are real.
    """

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.pdh = ctypes.WinDLL("pdh")

        class CV(ctypes.Union):
            _fields_ = [("longValue", ctypes.c_long),
                        ("doubleValue", ctypes.c_double),
                        ("largeValue", ctypes.c_longlong),
                        ("AnsiStringValue", ctypes.c_char_p),
                        ("WideStringValue", ctypes.c_wchar_p)]

        class PDH_FMT_COUNTERVALUE(ctypes.Structure):
            _fields_ = [("CStatus", wintypes.DWORD), ("u", CV)]

        class ITEM(ctypes.Structure):
            _fields_ = [("szName", ctypes.c_wchar_p),
                        ("FmtValue", PDH_FMT_COUNTERVALUE)]

        self._ITEM = ITEM
        self._query = ctypes.c_void_p()
        if self.pdh.PdhOpenQueryW(None, 0,
                                  ctypes.byref(self._query)) != 0:
            raise OSError("PdhOpenQueryW failed")
        self._util = self._add(_C_GPU_UTIL)
        self._vram = self._add(_C_GPU_VRAM)
        if self._util is None and self._vram is None:
            raise OSError("no GPU performance counters on this system")
        # prime: the first collect only establishes the baseline
        self.pdh.PdhCollectQueryData(self._query)

    def _add(self, path):
        h = self.ctypes.c_void_p()
        # ...English... so the call works on a German/French Windows too,
        # where the localised counter names differ
        if self.pdh.PdhAddEnglishCounterW(
                self._query, path, 0, self.ctypes.byref(h)) != 0:
            return None
        return h

    def _read(self, handle):
        """-> list of (instance_name, value), empty on any problem."""
        if handle is None:
            return []
        ctypes = self.ctypes
        from ctypes import wintypes
        size = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        rc = self.pdh.PdhGetFormattedCounterArrayW(
            handle, _PDH_FMT_DOUBLE, ctypes.byref(size),
            ctypes.byref(count), None)
        if rc != _PDH_MORE_DATA or size.value == 0:
            return []
        buf = ctypes.create_string_buffer(size.value)
        rc = self.pdh.PdhGetFormattedCounterArrayW(
            handle, _PDH_FMT_DOUBLE, ctypes.byref(size),
            ctypes.byref(count), ctypes.byref(buf))
        if rc != 0:
            return []
        items = ctypes.cast(
            buf, ctypes.POINTER(self._ITEM * count.value)).contents
        out = []
        for it in items:
            if it.FmtValue.CStatus not in _PDH_CSTATUS_VALID:
                continue
            out.append((it.szName or "", it.FmtValue.u.doubleValue))
        return out

    def poll(self):
        """-> (usage_percent | None, vram_used_bytes | None)"""
        if self.pdh.PdhCollectQueryData(self._query) != 0:
            return None, None

        usage = None
        rows = self._read(self._util)
        if rows:
            # Instances look like
            #   pid_1234_luid_0x00000000_0x0000ABCD_phys_0_eng_0_engtype_3D
            # Summing everything double-counts, because 3D, Copy and
            # VideoDecode run in parallel on the same chip. The Task
            # Manager sums per engine TYPE and shows the busiest type -
            # do the same.
            per_type = {}
            for name, val in rows:
                m = re.search(r"engtype_(\w+)", name or "")
                key = m.group(1) if m else "other"
                per_type[key] = per_type.get(key, 0.0) + val
            if per_type:
                usage = max(0.0, min(100.0, max(per_type.values())))

        vram = None
        rows = self._read(self._vram)
        if rows:
            total = sum(v for _, v in rows if v > 0)
            vram = total if total > 0 else None
        return usage, vram


# ====================================================================
# 3. nvidia-smi
# ====================================================================
def _find_nvidia_smi():
    exe = shutil.which("nvidia-smi")
    if exe:
        return exe
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramW6432", r"C:\Program Files")):
        cand = Path(base) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"
        if cand.exists():
            return str(cand)
    return None


# ====================================================================
# 4. LibreHardwareMonitor web server (the only temperature source)
# ====================================================================
_LHM_DEFAULT_URL = "http://localhost:8085/data.json"


class _Lhm:
    """Reads LibreHardwareMonitor's /data.json.

    LHM must be running with Options -> Remote Web Server -> Run enabled.
    Nothing is installed or started by us; if it is not there, temps stay
    None and we retry only once a minute so a missing LHM never costs
    anything per poll.
    """

    def __init__(self, log=None, url=None):
        self.url = url or os.environ.get("DCB_LHM_URL", _LHM_DEFAULT_URL)
        self.log = log
        self.ok = None            # None = never tried yet
        self._next_try = 0.0
        self._cache = (0.0, None, None)   # (when, cpu_temp, gpu_temp)

    def _fetch(self):
        try:
            with urllib.request.urlopen(self.url, timeout=1.5) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return None

    @staticmethod
    def _walk(node, trail, out):
        """Flattens the sensor tree into (path_of_texts, text, value)."""
        text = node.get("Text", "") or ""
        value = node.get("Value")
        here = trail + [text]
        if value not in (None, ""):
            out.append((here, text, value))
        for child in node.get("Children") or []:
            _Lhm._walk(child, here, out)

    def temps(self):
        """-> (cpu_temp, gpu_temp), either may be None."""
        now = time.monotonic()
        # a reading is good for one second; several snapshot() calls in
        # the same poll must not hit the HTTP server repeatedly
        if now - self._cache[0] < 1.0:
            return self._cache[1], self._cache[2]
        if self.ok is False and now < self._next_try:
            return None, None

        data = self._fetch()
        if data is None:
            if self.ok is not False and callable(self.log):
                self.log("Hardware: LibreHardwareMonitor not reachable at "
                         f"{self.url} - temperatures stay empty. Start LHM "
                         "and enable Options > Remote Web Server.")
            self.ok = False
            self._next_try = now + _RETRY_LHM
            return None, None
        if not self.ok:
            self.ok = True
            if callable(self.log):
                self.log(f"Hardware: LibreHardwareMonitor found at {self.url}")

        rows = []
        try:
            self._walk(data, [], rows)
        except Exception:
            return None, None

        # Several sensors qualify, so score them instead of taking the
        # first hit: "CPU Package"/"Tctl" beats "Core #3", and "GPU Core"
        # beats "GPU Hot Spot" (the hot spot runs ~15 K higher and would
        # look alarming in a chatbox).
        best_cpu = best_gpu = (-1, None)     # (score, value)
        for trail, text, value in rows:
            joined = " / ".join(trail).lower()
            if "temperatur" not in joined:          # matches "Temperatures"
                continue
            v = _num(value)
            if v is None or not (0 < v < 150):
                continue
            label = text.lower()
            if "gpu" in joined:
                score = 3 if "core" in label else (0 if "hot" in label else 1)
                if score > best_gpu[0]:
                    best_gpu = (score, v)
            else:
                if any(w in label for w in ("tctl", "tdie", "package")):
                    score = 3
                elif "average" in label:
                    score = 2
                elif "max" in label:
                    score = 0
                else:
                    score = 1
                if score > best_cpu[0]:
                    best_cpu = (score, v)

        cpu, gpu = best_cpu[1], best_gpu[1]
        self._cache = (now, cpu, gpu)
        return cpu, gpu


# ====================================================================
# FPS: RivaTuner Statistics Server shared memory
# ====================================================================
_RTSS_MAP = "RTSSSharedMemoryV2"
# RTSS_SHARED_MEMORY header: signature, version, appEntrySize,
# appArrOffset, appArrSize, osdEntrySize, osdArrOffset, osdArrSize
_RTSS_HEADER = struct.Struct("<8I")
# per-app entry: dwProcessID, szName[260], dwFlags, dwTime0, dwTime1,
# dwFrames, dwFrameTime
_RTSS_ENTRY_HEAD = struct.Struct("<I260sIIIII")


class _Rtss:
    """FPS from RTSS's shared memory - the Windows analogue of tailing a
    MangoHud CSV. RTSS ships with MSI Afterburner and is what almost
    every Windows overlay already uses, so most people have it."""

    def __init__(self, log=None, want=None):
        self.log = log
        self.want = (want or os.environ.get("DCB_FPS_PROCESS", "vrchat")).lower()
        self.ok = None
        self._next_try = 0.0

    def fps(self):
        now = time.monotonic()
        if self.ok is False and now < self._next_try:
            return None
        try:
            import mmap
            mm = mmap.mmap(-1, 0, tagname=_RTSS_MAP,
                           access=mmap.ACCESS_READ)
        except Exception:
            if self.ok is not False and callable(self.log):
                self.log("Hardware: RTSS not running - FPS stays empty. "
                         "Install RivaTuner Statistics Server (ships with "
                         "MSI Afterburner) to get frame rates.")
            self.ok = False
            self._next_try = now + _RETRY_RTSS
            return None
        try:
            return self._parse(mm)
        except Exception:
            return None
        finally:
            try:
                mm.close()
            except Exception:
                pass

    def _parse(self, mm):
        raw = mm[:_RTSS_HEADER.size]
        (sig, _ver, entry_size, arr_off, arr_size,
         _osd_e, _osd_o, _osd_s) = _RTSS_HEADER.unpack(raw)
        # b'RTSS' little-endian
        if sig not in (0x53535452, 0x52545353):
            return None
        if not entry_size or not arr_size:
            return None
        if self.ok is not True:
            self.ok = True
            if callable(self.log):
                self.log("Hardware: RTSS shared memory found - FPS available.")

        best = None
        for i in range(min(arr_size, 256)):
            off = arr_off + i * entry_size
            if off + _RTSS_ENTRY_HEAD.size > len(mm):
                break
            (pid, name, _flags, t0, t1, frames,
             _ftime) = _RTSS_ENTRY_HEAD.unpack(
                mm[off:off + _RTSS_ENTRY_HEAD.size])
            if not pid or t1 <= t0 or not frames:
                continue
            exe = name.split(b"\x00", 1)[0].decode("utf-8", "replace")
            value = frames * 1000.0 / (t1 - t0)
            if not (0 < value < 10000):
                continue
            hit = self.want and self.want in exe.lower()
            # the wanted process wins outright; otherwise keep the
            # busiest entry, which is the game in practice
            if hit:
                return value
            if best is None or value > best:
                best = value
        return best


# ====================================================================
# the backend itself
# ====================================================================
class WindowsHardwareMonitor:
    """Same API as core/backends/hardware_linux.HardwareMonitor."""

    available = True
    name = "windows"

    def __init__(self, log_fn, mangohud_dir=None):
        self.log = log_fn
        # kept for API parity; Windows has no MangoHud, FPS comes from RTSS
        self.mangohud_dir = Path(mangohud_dir).expanduser() \
            if mangohud_dir else None

        self._win32 = None
        try:
            self._win32 = _Win32()
        except Exception as e:
            self.log(f"Hardware: Win32 API unavailable ({e}) - "
                     f"CPU/RAM stay empty.")

        self.nvidia_smi = _find_nvidia_smi()
        self.has_nvidia = self.nvidia_smi is not None
        # the Linux backend exposes .amd_card; the UI only tests it for
        # truthiness to label the backend, so a plain flag is enough
        self.amd_card = None

        self._pdh = None
        if not self.has_nvidia:
            # with nvidia-smi around, PDH adds nothing but overhead
            try:
                self._pdh = _PdhGpu()
            except Exception as e:
                self.log(f"Hardware: GPU performance counters unavailable "
                         f"({e}) - GPU usage/VRAM stay empty.")

        self._lhm = _Lhm(log_fn)
        self._rtss = _Rtss(log_fn)

        reg_name, reg_vram = _registry_gpu()
        self._vram_total_bytes = reg_vram or None
        if not self.has_nvidia:
            self.amd_card = bool(reg_name) or None

        self.cpu_name_auto = _registry_cpu_name() or "CPU"
        self.gpu_name_auto = self._detect_gpu_name(reg_name)

        # the UI currently hardcodes "AMD (sysfs)" for a non-NVIDIA card,
        # which is a Linux-only phrase. Step 2b can read this instead:
        #   getattr(self.hw, "gpu_backend_label", None)
        if self.has_nvidia:
            self.gpu_backend_label = "NVIDIA (nvidia-smi)"
        elif self._pdh:
            self.gpu_backend_label = "Windows (performance counters)"
        else:
            self.gpu_backend_label = "none detected"

        sources = []
        if self._win32:
            sources.append("Win32")
        if self.has_nvidia:
            sources.append("nvidia-smi")
        if self._pdh:
            sources.append("PDH")
        self.log(f"Hardware: Windows backend, sources={'+'.join(sources) or 'none'}"
                 f", CPU='{self.cpu_name_auto}', GPU name='{self.gpu_name_auto}'")
        self.log("Hardware: temperatures need LibreHardwareMonitor "
                 "(web server on), FPS needs RTSS. Both are optional.")

    # ------------------------------------------------------------ names
    def _detect_gpu_name(self, registry_name=""):
        if self.has_nvidia:
            out = _run([self.nvidia_smi, "--query-gpu=name",
                        "--format=csv,noheader"])
            if out:
                return _clean_gpu_name(out.splitlines()[0])
        if registry_name:
            return _clean_gpu_name(registry_name)
        return "GPU"

    # ------------------------------------------------------------- cpu
    def cpu_usage(self):
        return self._win32.cpu_usage() if self._win32 else None

    def cpu_temp(self):
        return self._lhm.temps()[0]

    def amd_gpu_temp(self):
        return self._lhm.temps()[1]

    # ------------------------------------------------------------- ram
    def ram(self):
        return self._win32.ram() if self._win32 else None

    # ------------------------------------------------------------- gpu
    def gpu(self):
        """{usage, temp, vram_used, vram_total, vram_pct}, values may be
        None. Returns None only when there is no GPU source at all - the
        Linux backend behaves the same way."""
        if self.has_nvidia:
            out = _run([self.nvidia_smi,
                        "--query-gpu=utilization.gpu,temperature.gpu,"
                        "memory.used,memory.total",
                        "--format=csv,noheader,nounits"])
            try:
                u, t, mu, mt = [float(x) for x in out.splitlines()[0].split(",")]
                return {"usage": u, "temp": t,
                        "vram_used": mu / 1024.0, "vram_total": mt / 1024.0,
                        "vram_pct": 100.0 * mu / mt if mt else None}
            except Exception:
                pass          # driver hiccup - fall through to PDH/LHM

        if self._pdh is None:
            return None
        usage, vram_used = self._pdh.poll()
        vu = vram_used / GB if vram_used else None
        vt = self._vram_total_bytes / GB if self._vram_total_bytes else None
        return {"usage": usage,
                "temp": self._lhm.temps()[1],
                "vram_used": vu,
                "vram_total": vt,
                "vram_pct": (100.0 * vu / vt)
                            if (vu is not None and vt) else None}

    # ------------------------------------------------------------- fps
    def fps(self, folder=None):
        """`folder` is ignored - kept so the signature matches Linux."""
        return self._rtss.fps()

    # -------------------------------------------------------- snapshot
    def snapshot(self):
        return {"cpu_usage": self.cpu_usage(),
                "cpu_temp": self.cpu_temp(),
                "ram": self.ram(),
                "gpu": self.gpu(),
                "fps": self.fps()}


# ====================================================================
# diagnostics:  python -m core.backends.hardware_windows
# ====================================================================
def _selftest():
    print("=" * 62)
    print(" OSC-DreamChatbox - Windows hardware backend self-test")
    print("=" * 62)
    hw = WindowsHardwareMonitor(lambda m: print("  log:", m))
    print("-" * 62)
    print("Priming CPU counter, waiting 2s ...")
    hw.cpu_usage()
    time.sleep(2)
    for round_no in (1, 2):
        snap = hw.snapshot()
        print(f"\n--- snapshot {round_no} ---")
        print(f"  CPU usage : {snap['cpu_usage']}")
        print(f"  CPU temp  : {snap['cpu_temp']}   (needs LibreHardwareMonitor)")
        print(f"  RAM       : {snap['ram']}")
        print(f"  GPU       : {snap['gpu']}")
        print(f"  FPS       : {snap['fps']}   (needs RTSS + a running game)")
        if round_no == 1:
            time.sleep(2)
    print("\n" + "-" * 62)
    print("None means 'no source for this value', not an error.")
    print("Expected without extra software: CPU usage, RAM, GPU usage,")
    print("VRAM and both names work; temperatures and FPS are None.")
    print("=" * 62)


if __name__ == "__main__":
    _selftest()
