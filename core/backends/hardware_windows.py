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
       DXGI (dxgi_windows.py)            GPU names, VRAM total, LUIDs
       winreg                            CPU name, GPU fallback

    2. PDH performance counters        – stdlib, no install, Win10 1709+
       \\GPU Engine(*)\\Utilization Percentage      GPU usage (any vendor)
       \\GPU Adapter Memory(*)\\Dedicated Usage     VRAM used (any vendor)
       This is exactly what the Task Manager's GPU column reads. Every
       instance name carries the adapter's LUID, so each card gets its
       own numbers.

    3. nvidia-smi                      – ships with every NVIDIA driver
       Preferred when present, as one long-running process (nvsmi.py).

    4. atiadlxx.dll                    – ships with every AMD driver
       The same idea for AMD: power, temperatures, fan and clocks per
       card, no administrator rights, nothing to install. See
       adl_windows.py.

    5. LibreHardwareMonitor            – optional, user installs it
       LHM has a built-in web server (Options -> Remote Web Server).
       Switch it on and it serves every sensor as JSON on port 8085.
       That is where Intel GPU temps and ANY CPU temp and CPU watts
       come from.
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

from core.backends import dxgi_windows, netstats, ramtype
from core.backends.nvsmi import _NvidiaSmiLoop, _parse_nvsmi

GB = 1024 ** 3

# how long a dead optional source is not retried again (seconds)
_RETRY_LHM = 60.0

# nvidia-smi: this many polls without an answer, then a break. A driver
# in trouble can take seconds per call, and the app should not spend
# those on every poll.
_SMI_MAX_FAILS = 3
_SMI_PAUSE_SEC = 300.0

#: a performance counter sample is good for this long. gpu() and gpu2()
#: run right after each other, and counter rates over milliseconds are
#: noise.
_PDH_CACHE_SEC = 1.0

#: the values only some cards report, see gpu()
_GPU_EXTRAS = ("hotspot", "vram_temp", "fan", "fan_rpm", "clock",
               "vram_clock")

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


def _registry_gpus():
    """[(name, vram_total_bytes), ...], the adapter with the most VRAM
    first.

    Sorting by VRAM size puts the Microsoft Basic Display Adapter last
    and, on a laptop, the dedicated card before the iGPU. Everything is
    kept since v1.5.1: the Hardware card's GPU dropdown is filled from
    this, so a machine with two adapters can say which one it means.
    """
    found = []
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
                        found.append((desc, vram))
                except OSError:
                    continue
    except Exception:
        pass
    # de-duplicate: one physical adapter can have several class subkeys
    seen, out = set(), []
    for name, vram in sorted(found, key=lambda a: -a[1]):
        if name in seen:
            continue
        seen.add(name)
        out.append((name, vram))
    return out


def _registry_gpu():
    """(name, vram_total_bytes) of the adapter with the most VRAM."""
    gpus = _registry_gpus()
    return gpus[0] if gpus else ("", 0)


def _vendor_from_name(name):
    """Registry entries carry no vendor id, the name has to do."""
    low = (name or "").lower()
    if "nvidia" in low or "geforce" in low:
        return dxgi_windows.VENDOR_NVIDIA
    if "amd" in low or "radeon" in low:
        return dxgi_windows.VENDOR_AMD
    if "intel" in low:
        return dxgi_windows.VENDOR_INTEL
    return None


def _windows_adapters():
    """[{"name", "vram", "luid", "vendor"}, ...], most VRAM first. DXGI
    knows what is really in the machine; the registry is the fallback and
    has no LUIDs."""
    try:
        found = dxgi_windows.list_adapters()
    except Exception:
        found = []
    if found:
        return found
    return [{"name": name, "vram": vram, "luid": None,
             "vendor": _vendor_from_name(name)}
            for name, vram in _registry_gpus()]


# ====================================================================
# 2. PDH performance counters (GPU usage + VRAM, any vendor)
# ====================================================================
_PDH_FMT_DOUBLE = 0x00000200
_PDH_MORE_DATA = 0x800007D2
_PDH_CSTATUS_VALID = (0x00000000, 0x00000001)   # VALID_DATA, NEW_DATA

_C_GPU_UTIL = r"\GPU Engine(*)\Utilization Percentage"
_C_GPU_VRAM = r"\GPU Process Memory(*)\Dedicated Usage"
_C_GPU_ADAPTER = r"\GPU Adapter Memory(*)\Dedicated Usage"
_C_NET_DOWN = r"\Network Interface(*)\Bytes Received/sec"
_C_NET_UP = r"\Network Interface(*)\Bytes Sent/sec"

_LUID_RE = re.compile(r"luid_0x([0-9a-f]+)_0x([0-9a-f]+)", re.IGNORECASE)


def _luid_key(instance):
    """'..._luid_0x00000000_0x0000ABCD_...' -> (0, 0xABCD), else None."""
    m = _LUID_RE.search(instance or "")
    return (int(m.group(1), 16), int(m.group(2), 16)) if m else None


def _gpu_counters(util_rows, process_rows, adapter_rows):
    """Counter rows -> {luid: (usage, vram_bytes)}.

    The key None is the whole machine, for adapters without a LUID.

    Summing every engine double-counts, because 3D, Copy and VideoDecode
    run in parallel on the same chip. The Task Manager sums per engine
    TYPE and shows the busiest type - do the same.

    VRAM prefers GPU Adapter Memory, the adapter's own total. Adding up
    GPU Process Memory is the fallback for a Windows without it.
    """
    per_type = {}
    for name, value in util_rows:
        m = re.search(r"engtype_(\w+)", name or "")
        engine = m.group(1) if m else "other"
        for key in {_luid_key(name), None}:
            types = per_type.setdefault(key, {})
            types[engine] = types.get(engine, 0.0) + value

    def memory(rows):
        total = {}
        for name, value in rows:
            if value <= 0:
                continue
            for key in {_luid_key(name), None}:
                total[key] = total.get(key, 0.0) + value
        return total

    vram = memory(process_rows)
    vram.update(memory(adapter_rows))

    out = {}
    for key in set(per_type) | set(vram):
        types = per_type.get(key)
        usage = (max(0.0, min(100.0, max(types.values())))
                 if types else None)
        out[key] = (usage, vram.get(key))
    return out


class _PdhBase:
    """A wildcard PDH query, kept open across polls.

    Rate counters need two samples: the first collect in a subclass only
    sets the baseline, real values start with the next one.
    """

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.pdh = ctypes.WinDLL("pdh")
        # ctypes defaults to a signed int, which would turn PDH_MORE_DATA
        # into a negative number that never equals the constant
        self.pdh.PdhGetFormattedCounterArrayW.restype = wintypes.DWORD

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


class _PdhGpu(_PdhBase):
    """GPU usage and VRAM per adapter."""

    def __init__(self):
        super().__init__()
        self._util = self._add(_C_GPU_UTIL)
        self._vram = self._add(_C_GPU_VRAM)
        self._adapter = self._add(_C_GPU_ADAPTER)
        if self._util is None and self._vram is None \
                and self._adapter is None:
            raise OSError("no GPU performance counters on this system")
        self.pdh.PdhCollectQueryData(self._query)
        self._values = {}
        self._sampled_at = 0.0

    def poll(self, luid=None):
        """-> (usage_percent | None, vram_used_bytes | None) of one
        adapter, or of the whole machine for None."""
        now = time.monotonic()
        if now - self._sampled_at >= _PDH_CACHE_SEC:
            if self.pdh.PdhCollectQueryData(self._query) != 0:
                return None, None
            self._sampled_at = now
            self._values = _gpu_counters(self._read(self._util),
                                         self._read(self._vram),
                                         self._read(self._adapter))
        if luid is not None and luid not in self._values and self._values:
            # nothing is running on this card, so no engine has an
            # instance at all. That is an idle card, not a missing value.
            return 0.0, None
        return self._values.get(luid, (None, None))


class _PdhNet(_PdhBase):
    """Network speed per connection. Windows computes the rate itself."""

    def __init__(self):
        super().__init__()
        self._down = self._add(_C_NET_DOWN)
        self._up = self._add(_C_NET_UP)
        if self._down is None or self._up is None:
            raise OSError("no network performance counters on this system")
        self.pdh.PdhCollectQueryData(self._query)
        self.totals = {}
        self._sampled_at = None

    def sample(self):
        """-> {connection: (down, up)} in bytes per second."""
        if self.pdh.PdhCollectQueryData(self._query) != 0:
            return {}
        now = time.monotonic()
        seconds = now - self._sampled_at if self._sampled_at else 0.0
        self._sampled_at = now
        down = dict(self._read(self._down))
        up = dict(self._read(self._up))
        rates = {}
        for name in set(down) | set(up):
            rates[name] = (down.get(name, 0.0), up.get(name, 0.0))
            # no byte counters on this path, so "moved the most" is added
            # up from the speeds
            self.totals[name] = self.totals.get(name, 0.0) \
                + sum(rates[name]) * seconds
        return rates


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
# 5. LibreHardwareMonitor web server (the CPU temperature source)
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
        #: CPU temp sensor picked on the Hardware card: the joined LHM
        #: tree path of one temperature; None = scoring, see temps()
        self.cpu_pick = None
        #: every temperature of the last fetch, [{"id", "label", "value"}]
        self.temp_list = []

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
        temp_list = []
        picked = None
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
            # trail = [Sensor, PC, <hardware>, Temperatures, <sensor>]
            sid = " / ".join(t for t in trail[2:] if t) or text
            hw_name = trail[-3] if len(trail) >= 3 else ""
            temp_list.append({"id": sid, "value": v,
                              "label": f"{hw_name} \u00b7 {text}"
                              if hw_name else text})
            if self.cpu_pick and sid == self.cpu_pick:
                picked = v
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
        if picked is not None:
            cpu = picked
        self.temp_list = temp_list
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


def _wmi_ram_type():
    return ramtype.parse_wmi_output(_run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "(Get-CimInstance Win32_PhysicalMemory).SMBIOSMemoryType"],
        timeout=20))


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
        # a leftover nvidia-smi.exe after swapping to another vendor must
        # not count as an NVIDIA card, it would switch off the PDH path
        if self.has_nvidia and not self._nvidia_cards():
            self.nvidia_smi = None
            self.has_nvidia = False
        self._nvsmi = None
        self._smi_fails = 0
        self._smi_pause_until = 0.0
        if self.has_nvidia:
            self._nvsmi = _NvidiaSmiLoop(
                log_fn=log_fn, exe=self.nvidia_smi,
                creationflags=_CREATE_NO_WINDOW)
        # the Linux backend exposes .amd_card; the UI only tests it for
        # truthiness to label the backend, so a plain flag is enough
        self.amd_card = None

        #: every card nvidia-smi does not answer for
        self._others = [
            a for a in _windows_adapters()
            if not (self.has_nvidia
                    and a["vendor"] == dxgi_windows.VENDOR_NVIDIA)]

        # the driver's own sensors, the AMD counterpart to nvidia-smi
        self._adl = None
        if any(a["vendor"] in (dxgi_windows.VENDOR_AMD, None)
               for a in self._others):
            try:
                from core.backends import adl_windows
                self._adl = adl_windows.AdlReader(log_fn)
            except Exception as e:
                self.log(f"Hardware: no AMD driver sensors ({e}).")
        if self._adl:
            # the registry keeps the entries of cards that were swapped
            # out; what the driver can read really is in the machine
            self._others.sort(key=lambda a: not self._adl.has(a["name"]))

        self._pdh = None
        if self._others or not self.has_nvidia:
            # a pure NVIDIA machine does not need it, nvidia-smi answers
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

        self.net = netstats.NetMonitor(_PdhNet, log_fn)
        self._ram_type = ramtype.RamTypeProbe(_wmi_ram_type)

        reg_name = self._others[0]["name"] if self._others else ""
        reg_vram = self._others[0]["vram"] if self._others else 0
        self._vram_total_bytes = reg_vram or None
        if not self.has_nvidia:
            self.amd_card = bool(reg_name) or None

        self.cpu_name_auto = _registry_cpu_name() or "CPU"
        self._gpus = self._enumerate_gpus(reg_name)
        #: ids chosen in the Hardware card; None = "the first one"
        self.sel_gpu = None
        self.sel_gpu2 = None
        self.gpu_name_auto = self._name_of(self._gpu_entry(None))
        self.gpu2_name_auto = "GPU"

        # the UI currently hardcodes "AMD (sysfs)" for a non-NVIDIA card,
        # which is a Linux-only phrase. Step 2b can read this instead:
        #   getattr(self.hw, "gpu_backend_label", None)
        if self.has_nvidia:
            self.gpu_backend_label = "NVIDIA (nvidia-smi)"
        elif self._adl and self._pdh:
            self.gpu_backend_label = "AMD driver + performance counters"
        elif self._adl:
            self.gpu_backend_label = "AMD driver"
        elif self._pdh:
            self.gpu_backend_label = "Windows (performance counters)"
        else:
            self.gpu_backend_label = "none detected"

        sources = []
        if self._win32:
            sources.append("Win32")
        if self.has_nvidia:
            sources.append("nvidia-smi")
        if self._adl:
            sources.append("ADL")
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

    # ------------------------------------------------------ gpu selection
    def _nvidia_cards(self):
        """[(index, name), ...] from nvidia-smi, or []."""
        if not self.has_nvidia:
            return []
        out = _run([self.nvidia_smi, "--query-gpu=index,name",
                    "--format=csv,noheader"], timeout=5)
        cards = []
        for line in (out or "").splitlines():
            parts = line.split(",", 1)
            if len(parts) != 2:
                continue
            try:
                idx = int(parts[0].strip())
            except ValueError:
                continue
            cards.append((idx, _clean_gpu_name(parts[1].strip()) or "GPU"))
        cards.sort()
        return cards

    def _enumerate_gpus(self, registry_name=""):
        """Every card the Hardware card can offer.

        NVIDIA cards are listed one by one, because nvidia-smi answers per
        card. Every other card comes from DXGI and gets its readings from
        the performance counters through its LUID. Only the registry
        fallback has no LUIDs: there the counters are machine-wide, so the
        first entry carries them and the rest are names, unless the AMD
        driver reads them (the label says which).
        """
        gpus = []
        nvidia = self._nvidia_cards()
        if not nvidia and self.has_nvidia:
            nvidia = [(0, self._detect_gpu_name(registry_name))]
        for idx, name in nvidia:
            gpus.append({"id": f"nvidia:{idx}", "name": name,
                         "vendor": "NVIDIA", "index": idx,
                         "label": f"NVIDIA #{idx} · {name}"})
        for pos, adapter in enumerate(self._others):
            name, vram = adapter["name"], adapter["vram"]
            luid = adapter["luid"]
            clean = _clean_gpu_name(name) or "GPU"
            gb = (vram or 0) / GB
            label = f"{clean}" + (f" ({gb:.0f}GB)" if gb >= 1 else "")
            readable = (pos == 0 or luid is not None
                        or (self._adl is not None and self._adl.has(name)))
            gpus.append({"id": f"win:{pos}", "name": clean,
                         "reg_name": name, "luid": luid,
                         "vendor": "Windows",
                         "counters": luid is not None or pos == 0,
                         # LHM and the helper report one GPU, not per card
                         "shared_sensors": pos == 0 and not self.has_nvidia,
                         "vram_total": vram or None,
                         "label": label if readable
                                  else f"{label} - name only"})
        if not gpus:
            name = self._detect_gpu_name(registry_name)
            gpus.append({"id": "display", "name": name, "vendor": "",
                         "counters": False, "vram_total": None,
                         "label": f"{name} (name only - no readings)"})
        return gpus

    def list_gpus(self):
        return list(self._gpus)

    def select_gpus(self, primary=None, second=None):
        self.sel_gpu = primary or None
        self.sel_gpu2 = second or None
        self.gpu_name_auto = self._name_of(self._gpu_entry(None))
        self.gpu2_name_auto = (
            self._name_of(self._gpu_entry(self.sel_gpu2, fallback=False))
            if self.sel_gpu2 else "GPU")

    def _gpu_entry(self, gpu_id=None, fallback=True):
        if gpu_id is None:
            gpu_id = self.sel_gpu
        for g in self._gpus:
            if g["id"] == gpu_id:
                return g
        if fallback and self._gpus:
            return self._gpus[0]
        return None

    @staticmethod
    def _name_of(entry):
        return entry["name"] if entry else "GPU"

    def gpu_name_for(self, gpu_id):
        return self._name_of(self._gpu_entry(gpu_id, fallback=False))

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

    # ------------------------------------------------ CPU temp selection
    def list_temp_sensors(self):
        """Every temperature LibreHardwareMonitor reports, for the CPU
        sensor dropdown. Empty while LHM is not reachable - the elevated
        helper only hands over two finished numbers, nothing to pick."""
        self._lhm.temps()
        return list(self._lhm.temp_list)

    def select_cpu_temp(self, sensor_id=None):
        self._lhm.cpu_pick = sensor_id or None
        self._lhm._cache = (0.0, None, None)     # next read re-scores

    def _adl_values(self, entry):
        """This card's values from the AMD driver, {} when it has none."""
        if self._adl is None or not entry:
            return {}
        return self._adl.values(entry.get("reg_name") or entry.get("name"),
                                sole=len(self._others) <= 1)

    def amd_gpu_temp(self):
        temp = self._adl_values(self._gpu_entry(None)).get("temp")
        return temp if temp is not None else self._temps()[1]

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
    def gpu(self, gpu_id=None):
        """{usage, temp, vram_used, vram_total, vram_pct}, values may be
        None. Returns None only when there is no GPU source at all - the
        Linux backend behaves the same way."""
        entry = self._gpu_entry(gpu_id, fallback=gpu_id is None) or {}
        if entry.get("vendor") == "NVIDIA":
            got = self._nvidia_values(entry.get("index", 0))
            if got is not None:
                return got
            # driver hiccup - fall through to PDH/LHM

        adl = self._adl_values(entry)
        extras = {key: adl.get(key) for key in _GPU_EXTRAS}

        # An adapter without counters (a later entry of the registry
        # fallback) has its name, the VRAM size the driver wrote down and
        # whatever the AMD driver reports per card. Saying so with None
        # values is better than handing back the machine-wide counters
        # under its name.
        if entry and entry.get("vendor") == "Windows" \
                and not entry.get("counters"):
            vt = entry.get("vram_total")
            return {"usage": adl.get("usage"), "temp": adl.get("temp"),
                    "power": adl.get("power"),
                    "vram_used": None,
                    "vram_total": vt / GB if vt else None,
                    "vram_pct": None, **extras}
        if self._pdh is None and not adl:
            return None
        luid = entry.get("luid")
        usage, vram_used = self._pdh.poll(luid) if self._pdh else (None, None)
        # the counters are per card only with a LUID, ADL always is
        if adl.get("usage") is not None and (usage is None or luid is None):
            usage = adl["usage"]
        temp, power = adl.get("temp"), adl.get("power")
        if entry.get("shared_sensors", True):
            if temp is None:
                temp = self._temps()[1]
            if power is None:
                power = self._lhm.powers()[1]
        vu = vram_used / GB if vram_used else None
        total = entry.get("vram_total") or self._vram_total_bytes
        vt = total / GB if total else None
        return {"usage": usage,
                "temp": temp,
                "power": power,
                "vram_used": vu,
                "vram_total": vt,
                "vram_pct": (100.0 * vu / vt)
                            if (vu is not None and vt) else None,
                **extras}

    def _nvidia_values(self, index):
        """One NVIDIA card, or None. After a few polls without an answer
        it pauses instead of waiting on a broken driver every time."""
        now = time.monotonic()
        if now < self._smi_pause_until:
            return None
        if self._nvsmi.broken:
            out = _run([self.nvidia_smi, "-i", str(index),
                        f"--query-gpu={self._nvsmi.query}",
                        "--format=csv,noheader,nounits"])
            line = out.splitlines()[0] if out else None
        else:
            line = self._nvsmi.latest(index)
        got = _parse_nvsmi(line, index)
        if got is not None:
            self._smi_fails = 0
            return got
        self._smi_fails += 1
        if self._smi_fails >= _SMI_MAX_FAILS:
            self._smi_fails = 0
            self._smi_pause_until = now + _SMI_PAUSE_SEC
            self.log("Hardware: nvidia-smi does not answer - trying again "
                     f"in {_SMI_PAUSE_SEC / 60:.0f} minutes.")
        return None

    def close(self):
        """Called on app exit - ends the nvidia-smi process."""
        if self._nvsmi is not None:
            self._nvsmi.close()

    # ------------------------------------------------- network, RAM type
    def set_net(self, enabled, interface=None):
        self.net.configure(enabled, interface)

    def ram_type(self):
        return self._ram_type.get()

    def gpu2(self):
        """The second card's values, or None when none is selected."""
        if not self.sel_gpu2 or self.sel_gpu2 == self.sel_gpu:
            return None
        return self.gpu(self.sel_gpu2)

    # -------------------------------------------------------- snapshot
    def snapshot(self):
        return {"cpu_usage": self.cpu_usage(),
                "cpu_temp": self.cpu_temp(),
                "cpu_power": self.cpu_power(),
                "ram": self.ram(),
                "gpu": self.gpu(),
                "gpu2": self.gpu2(),
                "net": self.net.read(),
                "ram_type": self.ram_type()}


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
        print(f"  CPU watts : {snap['cpu_power']}   (needs LibreHardwareMonitor)")
        print(f"  RAM       : {snap['ram']}")
        print(f"  GPU       : {snap['gpu']}")
        if round_no == 1:
            time.sleep(2)
    print("\n" + "-" * 62)
    print("None means 'no source for this value', not an error.")
    print("Expected without extra software: CPU usage, RAM, GPU usage,")
    print("VRAM and both names work. NVIDIA and AMD cards also report GPU")
    print("temperature and watts; the CPU values stay None.")
    print("=" * 62)


if __name__ == "__main__":
    _selftest()
