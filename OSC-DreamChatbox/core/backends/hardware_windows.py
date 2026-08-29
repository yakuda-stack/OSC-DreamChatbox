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
without hwmon reports None too), and the Hardware
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

FPS used to be read here too, from RTSS. It moved into the World Stats
plugin in v1.4.4: a frame rate only exists inside the process drawing it,
so getting one means reading something that lives in the game rather than
in the operating system, which is a different kind of job from everything
above.

One environment variable exists as an escape hatch until the Options page
gets a proper row for it (step 2b):

    DCB_LHM_URL       default http://localhost:8085/data.json

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
import subprocess
import time
import urllib.request
from pathlib import Path

GB = 1024 ** 3

# how long a dead optional source is not retried again (seconds)
_RETRY_LHM = 60.0

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
        # LHM reports power in the same tree as the temperatures, so it
        # comes out of the same fetch - a second HTTP round trip per poll
        # for one more number would be silly
        self._power = (None, None)        # (cpu_power, gpu_power)

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
        best_cpu_w = best_gpu_w = (-1, None)
        for trail, text, value in rows:
            joined = " / ".join(trail).lower()
            if "power" in joined:
                # Watts. "CPU Package" / "GPU Package" are the totals the
                # vendor tools show; "CPU Cores" and "GPU Memory" are
                # parts of them and would understate the draw, so they
                # only win when nothing better is there.
                w = _num(value)
                if w is None or not (0 < w < 2000):
                    continue
                label = text.lower()
                score = 3 if "package" in label else (
                    2 if "total" in label else 1)
                if "gpu" in joined:
                    if score > best_gpu_w[0]:
                        best_gpu_w = (score, w)
                elif score > best_cpu_w[0]:
                    best_cpu_w = (score, w)
                continue
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
        self._power = (best_cpu_w[1], best_gpu_w[1])
        self._cache = (now, cpu, gpu)
        return cpu, gpu

    def powers(self):
        """-> (cpu_power, gpu_power) in watts, either may be None.

        Filled as a side effect of temps(), which is what refreshes the
        cache - calling this alone would answer with whatever the last
        fetch happened to see, so it asks for a reading first.
        """
        self.temps()
        return self._power


# ====================================================================
# the backend itself
# ====================================================================
class WindowsHardwareMonitor:
    """Same API as core/backends/hardware_linux.HardwareMonitor."""

    available = True
    name = "windows"

    def __init__(self, log_fn):
        self.log = log_fn

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
        # elevated helper (Hardware card button) - see core/backends/wintemp.py
        try:
            from core.backends.wintemp import TempHelper
            self.temp_helper = TempHelper(log_fn)
        except Exception:
            self.temp_helper = None

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
        self.log("Hardware: temperatures need a kernel driver on Windows - use the \"Enable advanced temperature monitoring\" button on the Hardware card. It is optional.")

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

    def _temps(self):
        """(cpu, gpu) from LHM's web server, falling back to the elevated
        helper file. Two independent paths to the same numbers: the web
        server needs LHM configured, the helper only needs the button."""
        cpu, gpu = self._lhm.temps()
        if (cpu is None or gpu is None) and self.temp_helper is not None:
            h_cpu, h_gpu = self.temp_helper.temps()
            cpu = cpu if cpu is not None else h_cpu
            gpu = gpu if gpu is not None else h_gpu
        return cpu, gpu

    def cpu_temp(self):
        return self._temps()[0]

    def amd_gpu_temp(self):
        return self._temps()[1]

    def cpu_power(self):
        """Watts, from LibreHardwareMonitor. Windows exposes no power
        counter of its own - there is no PDH equivalent of RAPL - so this
        is empty unless LHM's web server is running, exactly like the
        temperatures."""
        return self._lhm.powers()[0]

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
                        "memory.used,memory.total,power.draw",
                        "--format=csv,noheader,nounits"])
            try:
                cols = out.splitlines()[0].split(",")
                u, t, mu, mt = [float(x) for x in cols[:4]]
                # "[N/A]" on cards that do not report it - parsed on its
                # own so it cannot cost us the four that always work
                try:
                    power = float(cols[4])
                except (IndexError, ValueError):
                    power = None
                return {"usage": u, "temp": t, "power": power,
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
                "temp": self._temps()[1],
                "power": self._lhm.powers()[1],
                "vram_used": vu,
                "vram_total": vt,
                "vram_pct": (100.0 * vu / vt)
                            if (vu is not None and vt) else None}

    # -------------------------------------------------------- snapshot
    def snapshot(self):
        return {"cpu_usage": self.cpu_usage(),
                "cpu_temp": self.cpu_temp(),
                "cpu_power": self.cpu_power(),
                "ram": self.ram(),
                "gpu": self.gpu()}


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
        if round_no == 1:
            time.sleep(2)
    print("\n" + "-" * 62)
    print("None means 'no source for this value', not an error.")
    print("Expected without extra software: CPU usage, RAM, GPU usage,")
    print("VRAM and both names work; temperatures are None.")
    print("=" * 62)


if __name__ == "__main__":
    _selftest()
