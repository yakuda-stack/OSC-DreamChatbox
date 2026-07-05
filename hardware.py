"""
hardware.py – Hardware monitoring for OSC-DreamChatbox (Linux)

Reads CPU / RAM / GPU stats without extra dependencies:
- CPU usage:   /proc/stat
- CPU name:    /proc/cpuinfo
- CPU temp:    /sys/class/hwmon (k10temp / zenpower / coretemp)
- RAM:         /proc/meminfo
- GPU (AMD):   /sys/class/drm/card*/device (gpu_busy_percent, vram) + hwmon
- GPU (NVIDIA): nvidia-smi
- GPU name:    nvidia-smi or lspci (best effort – custom name recommended)
"""

import re
import shutil
import subprocess
from pathlib import Path

GB = 1024 ** 3


def _read(path):
    try:
        return Path(path).read_text().strip()
    except Exception:
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
    """'NVIDIA GeForce RTX 5060 Ti' -> 'RTX 5060 Ti'"""
    name = re.sub(r"\b(NVIDIA|GeForce|AMD|ATI|Radeon Graphics|Intel|Arc)\b", "", name)
    name = re.sub(r"\(R\)|\(TM\)", "", name)
    return re.sub(r"\s+", " ", name).strip() or name.strip()


class HardwareMonitor:
    def __init__(self, log_fn):
        self._hwmon_cache = {}
        self.log = log_fn
        self._prev_cpu = None          # (idle, total) from /proc/stat
        self.has_nvidia = shutil.which("nvidia-smi") is not None
        self.amd_card = self._find_amd_card()
        self.gpu_name_auto = self._detect_gpu_name()
        self.cpu_name_auto = self._detect_cpu_name()
        self.log(f"Hardware: GPU={'NVIDIA' if self.has_nvidia else ('AMD' if self.amd_card else 'none detected')}"
                 f", CPU='{self.cpu_name_auto}', GPU name='{self.gpu_name_auto}'")

    # ------------------------------------------------------------- detection
    def _find_amd_card(self):
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
            if (card / "device" / "gpu_busy_percent").exists():
                return card / "device"
        return None

    def _detect_cpu_name(self):
        txt = _read("/proc/cpuinfo") or ""
        m = re.search(r"model name\s*:\s*(.+)", txt)
        return _clean_cpu_name(m.group(1)) if m else "CPU"

    def _detect_gpu_name(self):
        if self.has_nvidia:
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=3).stdout.strip()
                if out:
                    return _clean_gpu_name(out.splitlines()[0])
            except Exception:
                pass
        # Mesa/OpenGL knows the exact marketing name of the card
        # (lspci often shows all variants sharing one PCI ID, e.g.
        #  "RX 9070/9070 XT/9070 GRE"). Needs glxinfo (package mesa-utils).
        if shutil.which("glxinfo"):
            try:
                out = subprocess.run(["glxinfo", "-B"], capture_output=True,
                                     text=True, timeout=5).stdout
                m = re.search(r"^\s*Device:\s*(.+)$", out, re.MULTILINE)
                if m:
                    name = re.sub(r"\s*\(.*\)\s*$", "", m.group(1)).strip()
                    if name and "llvmpipe" not in name.lower():
                        return _clean_gpu_name(name)
            except Exception:
                pass
        # best effort via lspci (works for AMD/Intel too)
        try:
            out = subprocess.run(["lspci"], capture_output=True, text=True,
                                 timeout=3).stdout
            for line in out.splitlines():
                if "VGA compatible controller" in line or "Display controller" in line:
                    m = re.findall(r"\[([^\]]+)\]", line)
                    if m:
                        return _clean_gpu_name(m[-1])
                    return _clean_gpu_name(line.split(":", 2)[-1])
        except Exception:
            pass
        return "GPU"

    # ----------------------------------------------------------------- temps
    def _hwmon_temp(self, wanted_names):
        # cache the matching sensor file after the first scan so we don't
        # walk /sys/class/hwmon on every poll
        key = frozenset(wanted_names)
        cached = self._hwmon_cache.get(key)
        if cached:
            v = _read(cached)
            if v:
                try:
                    return int(v) / 1000.0
                except ValueError:
                    pass
            self._hwmon_cache.pop(key, None)
        for hw in Path("/sys/class/hwmon").glob("hwmon*"):
            name = _read(hw / "name") or ""
            if name in wanted_names:
                for t in ("temp1_input", "temp2_input"):
                    v = _read(hw / t)
                    if v:
                        try:
                            val = int(v) / 1000.0
                            self._hwmon_cache[key] = hw / t
                            return val
                        except ValueError:
                            pass
        return None

    def cpu_temp(self):
        return self._hwmon_temp({"k10temp", "zenpower", "coretemp", "cpu_thermal"})

    def amd_gpu_temp(self):
        return self._hwmon_temp({"amdgpu"})

    # ----------------------------------------------------------------- cpu %
    def cpu_usage(self):
        txt = _read("/proc/stat")
        if not txt:
            return None
        parts = txt.splitlines()[0].split()[1:]
        nums = [int(p) for p in parts]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        total = sum(nums)
        if self._prev_cpu is None:
            self._prev_cpu = (idle, total)
            return None
        p_idle, p_total = self._prev_cpu
        self._prev_cpu = (idle, total)
        d_total = total - p_total
        d_idle = idle - p_idle
        if d_total <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (d_total - d_idle) / d_total))

    # ------------------------------------------------------------------- ram
    def ram(self):
        txt = _read("/proc/meminfo") or ""
        def kb(key):
            m = re.search(rf"{key}:\s*(\d+)\s*kB", txt)
            return int(m.group(1)) * 1024 if m else None
        total = kb("MemTotal")
        avail = kb("MemAvailable")
        if total is None or avail is None:
            return None
        used = total - avail
        return {"used": used / GB, "total": total / GB,
                "pct": 100.0 * used / total}

    # ------------------------------------------------------------------- gpu
    def gpu(self):
        """Returns {usage, temp, vram_used, vram_total, vram_pct} (values may be None)."""
        if self.has_nvidia:
            try:
                out = subprocess.run(
                    ["nvidia-smi",
                     "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3).stdout.strip()
                u, t, mu, mt = [float(x) for x in out.splitlines()[0].split(",")]
                return {"usage": u, "temp": t,
                        "vram_used": mu / 1024.0, "vram_total": mt / 1024.0,
                        "vram_pct": 100.0 * mu / mt if mt else None}
            except Exception:
                return None
        if self.amd_card:
            try:
                usage = _read(self.amd_card / "gpu_busy_percent")
                vu = _read(self.amd_card / "mem_info_vram_used")
                vt = _read(self.amd_card / "mem_info_vram_total")
                vu = int(vu) / GB if vu else None
                vt = int(vt) / GB if vt else None
                return {"usage": float(usage) if usage else None,
                        "temp": self.amd_gpu_temp(),
                        "vram_used": vu, "vram_total": vt,
                        "vram_pct": (100.0 * vu / vt) if (vu is not None and vt) else None}
            except Exception:
                return None
        return None

    # -------------------------------------------------------------- snapshot
    def snapshot(self):
        return {"cpu_usage": self.cpu_usage(),
                "cpu_temp": self.cpu_temp(),
                "ram": self.ram(),
                "gpu": self.gpu()}
