"""
core/backends/hardware_linux.py – Hardware monitoring on Linux
(moved out of core/hardware.py in v1.2.7, code unchanged)

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
import time
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
    def __init__(self, log_fn, mangohud_dir=None):
        # set from the config; None disables the FPS readout entirely
        self.mangohud_dir = Path(mangohud_dir).expanduser() \
            if mangohud_dir else None
        self._init(log_fn)

    def _init(self, log_fn):
        self._hwmon_cache = {}
        self.log = log_fn
        self._prev_cpu = None          # (idle, total) from /proc/stat
        # RAPL is a cumulative counter, so watts only exist as a delta -
        # None = not scanned yet, [] = scanned and nothing usable
        self._rapl_zones = None
        self._rapl_prev = None         # (monotonic, microjoules)
        # same idea for a hwmon energy counter (zenergy)
        self._energy_prev = None
        self._rapl_warned = False
        # one log line each, not one per poll
        self._cpu_power_warned = False
        self._gpu_power_warned = False
        # a counter/zone was found, even if it has not produced a delta
        # yet - see cpu_power()
        self._cpu_power_source = False
        # what the powercap/hwmon scans actually saw, for the log line
        self._rapl_seen = []
        self.has_nvidia = shutil.which("nvidia-smi") is not None
        self.amd_card = self._find_amd_card()
        self.gpu_name_auto = self._detect_gpu_name()
        self.cpu_name_auto = self._detect_cpu_name()
        self.log(f"Hardware: GPU={'NVIDIA' if self.has_nvidia else ('AMD' if self.amd_card else 'none detected')}"
                 f", CPU='{self.cpu_name_auto}', GPU name='{self.gpu_name_auto}'")

    # ------------------------------------------------------------- detection
    def _find_amd_card(self):
        """The AMD card to report on.

        A Ryzen desktop chip brings its own integrated Radeon, so there
        are usually two candidates and card0 is as likely to be the iGPU
        as the discrete card. Whichever has more VRAM is the one the user
        means - an iGPU carves a few hundred MB out of system memory, a
        discrete card has gigabytes - and that beats trusting the
        numbering, which changes with the boot order.
        """
        best, best_vram = None, -1
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
            dev = card / "device"
            if not (dev / "gpu_busy_percent").exists():
                continue
            try:
                vram = int(_read(dev / "mem_info_vram_total") or 0)
            except ValueError:
                vram = 0
            if vram > best_vram:
                best, best_vram = dev, vram
        return best

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
        """Same reasoning as amd_gpu_power(): our card's own node first,
        so the temperature cannot come from the iGPU while the load
        comes from the discrete card."""
        node = self._card_hwmon()
        if node:
            for t in ("temp1_input", "temp2_input"):
                v = _read(node / t)
                if v:
                    try:
                        return int(v) / 1000.0
                    except ValueError:
                        pass
        return self._hwmon_temp({"amdgpu"})

    # ---------------------------------------------------------------- power
    # Three sources, because no single one covers both vendors:
    #
    #   hwmon power1_average / power1_input   AMD GPUs (amdgpu) and, for
    #                                         the CPU, zenpower's SVI2
    #                                         reading. Instantaneous
    #                                         watts, nothing to compute.
    #   powercap RAPL energy_uj               Intel and Zen through the
    #                                         intel-rapl driver. Cumulative
    #                                         MICROJOULES, so watts only
    #                                         exist as a delta - see
    #                                         _rapl_watts().
    #   nvidia-smi power.draw                 NVIDIA, one more column on a
    #                                         query we already run.
    def _hwmon_power(self, wanted_names):
        """Instantaneous watts from a hwmon node, or None.

        Cached the same way the temperatures are: /sys/class/hwmon is
        walked once and the matching file remembered, because polling
        every two seconds must not mean globbing sysfs every two seconds.
        """
        key = ("power", frozenset(wanted_names))
        cached = self._hwmon_cache.get(key)
        if cached:
            v = _read(cached)
            if v:
                try:
                    return int(v) / 1_000_000.0      # microwatts -> W
                except ValueError:
                    pass
            self._hwmon_cache.pop(key, None)
        for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            name = _read(hw / "name") or ""
            if name not in wanted_names:
                continue
            watts = self._power_from_node(hw, key)
            if watts is not None:
                return watts
        return None

    def _power_from_node(self, hw, key=None):
        """Watts out of one specific hwmon directory, or None.

        average before input: power1_average is the windowed value the
        vendor tools show, power1_input is a single sample and jumps
        around far too much to read in a chatbox.
        """
        for f in ("power1_average", "power1_input"):
            v = _read(hw / f)
            if v:
                try:
                    watts = int(v) / 1_000_000.0
                except ValueError:
                    continue
                if key is not None:
                    self._hwmon_cache[key] = hw / f
                return watts
        return None

    def _card_hwmon(self):
        """The hwmon directory belonging to *our* GPU.

        A desktop Ryzen has an integrated Radeon on top of the discrete
        card, so /sys/class/hwmon holds two nodes called `amdgpu` and
        glob() hands them back in filesystem order, which is not stable
        across boots. Picking "the first one named amdgpu" therefore
        reads the iGPU's sensors about as often as the dGPU's - while
        usage and VRAM come from self.amd_card either way, so the line
        ends up mixing two different chips.

        The card device owns its own hwmon node, so going through it
        removes the guess entirely.
        """
        if not self.amd_card:
            return None
        if "card_hwmon" in self._hwmon_cache:
            return self._hwmon_cache["card_hwmon"]
        try:
            nodes = sorted((self.amd_card / "hwmon").glob("hwmon*"))
        except OSError:
            nodes = []
        node = nodes[0] if nodes else None
        self._hwmon_cache["card_hwmon"] = node
        return node

    def _hwmon_energy(self, wanted_names):
        """Watts from a hwmon *energy* counter, or None.

        zenergy - currently the driver that actually works on Zen 4/5,
        where zenpower3 does not - publishes no watts at all. It exposes
        `energyN_input`, a cumulative MICROJOULE counter, so a single
        read says nothing and watts only exist as a delta between two
        polls. Same maths as _rapl_watts(), and the same consequence:
        the value needs one poll interval to appear after a start.

        Which counter is the package one matters. The layout inherited
        from amd_energy lists the per-core counters first and the socket
        totals after them, so `energy1_input` is usually *core 0* - a
        handful of watts that would look like a plausible reading while
        being wrong by a factor of ten. The labels are therefore read
        and the socket entries preferred, with energy1_input kept only
        as a fallback for a driver that ships no labels.
        """
        key = ("energy", frozenset(wanted_names))
        paths = self._hwmon_cache.get(key)
        if paths is None:
            paths = []
            for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
                if (_read(hw / "name") or "") not in wanted_names:
                    continue
                socket, any_input = [], []
                for f in sorted(hw.glob("energy*_input")):
                    if _read(f) is None:
                        continue
                    any_input.append(f)
                    label = (_read(f.with_name(
                        f.name.replace("_input", "_label"))) or "").lower()
                    if "socket" in label or "package" in label:
                        socket.append(f)
                paths = socket or any_input[:1]
                if paths:
                    break
            self._hwmon_cache[key] = paths
        if not paths:
            return None
        self._cpu_power_source = True
        total = 0
        for f in paths:
            v = _read(f)
            if v is None:
                self._hwmon_cache.pop(key, None)   # module unloaded
                self._energy_prev = None
                return None
            try:
                total += int(v)
            except ValueError:
                return None
        now = time.monotonic()
        prev = self._energy_prev
        self._energy_prev = (now, total)
        if prev is None:
            return None                    # first read is the baseline
        dt = now - prev[0]
        dj = total - prev[1]
        if dt <= 0 or dj < 0:
            return None                    # counter wrapped - skip a frame
        watts = (dj / 1_000_000.0) / dt
        return watts if 0 < watts < 1000 else None

    def _rapl_scan(self):
        """Every powercap zone that reports package energy.

        The layout is not one fixed path. /sys/class/powercap holds both
        control types and zones as symlinks, and the zones also nest
        underneath their control type, so the same counter is reachable
        as `intel-rapl:0` and as `intel-rapl/intel-rapl:0`. Different
        kernels and vendors also use different control-type names -
        intel-rapl, intel-rapl-mmio, and AMD builds that ship their own.
        Matching one hardcoded prefix, which is what this did before, is
        exactly how a machine that clearly has the counter ends up
        reporting nothing.

        So: walk the class directory, take anything with an energy_uj,
        and let the zone's own `name` decide. Only `package*` counts -
        the `core` and `dram` subzones would otherwise be added on top
        of the package they are already part of.
        """
        root = Path("/sys/class/powercap")
        found, seen_paths = [], set()
        try:
            entries = sorted(root.glob("*"))
        except OSError:
            return []
        for entry in entries:
            candidates = [entry] + sorted(entry.glob("*:*"))
            for zone in candidates:
                f = zone / "energy_uj"
                try:
                    real = f.resolve()
                except OSError:
                    continue
                if real in seen_paths or not f.exists():
                    continue
                seen_paths.add(real)
                name = (_read(zone / "name") or "").strip()
                found.append((zone.name, name, f))
        self._rapl_seen = found
        return [f for _zone, name, f in found
                if name.lower().startswith("package")]

    def _rapl_watts(self):
        """CPU package power from the powercap RAPL counters.

        The counter is cumulative energy, so a single read says nothing:
        the first call records a baseline and returns None, every call
        after it divides the energy delta by the time delta. Which is
        also why this value needs one poll to appear after a start.

        Since kernel 5.10 these files are root-only (CVE-2020-8694 - the
        counter leaks enough for a side-channel attack), so on most
        desktops they are simply unreadable. That is not worth shouting
        about: it is logged once, the scan is not repeated, and the hwmon
        path above covers most AMD machines anyway.
        """
        if self._rapl_zones is None:
            self._rapl_zones = self._rapl_scan()
        if not self._rapl_zones:
            return None
        self._cpu_power_source = True
        total = 0
        for f in self._rapl_zones:
            v = _read(f)
            if v is None:
                if not self._rapl_warned:
                    self._rapl_warned = True
                    self.log("Hardware: the RAPL power counters are not "
                             "readable (root only since kernel 5.10) - "
                             "{cpu_power} stays empty unless the CPU "
                             "exposes a hwmon power sensor.")
                self._rapl_zones = []      # stop retrying on every poll
                return None
            try:
                total += int(v)
            except ValueError:
                return None
        now = time.monotonic()
        prev = self._rapl_prev
        self._rapl_prev = (now, total)
        if prev is None:
            return None                    # first read is the baseline
        dt = now - prev[0]
        dj = total - prev[1]
        if dt <= 0 or dj < 0:
            return None                    # counter wrapped - skip a frame
        watts = (dj / 1_000_000.0) / dt
        return watts if 0 < watts < 1000 else None

    def cpu_power(self):
        """CPU package power in watts, or None when nothing reports it.

        Three routes, because no single one covers the Zen generations:

          power1_*        zenpower / zenpower5 read the SVI2 rails and
                          publish watts directly. k10temp is in the list
                          because it is what an AMD desktop always has,
                          but on Zen it only exposes temperatures.
          energyN_input   zenergy, the one that currently works on Zen
                          4/5. Joules, so watts are a delta.
          RAPL            root-only since kernel 5.10, so on a stock
                          install this one rarely answers.
        """
        watts = self._hwmon_power({"zenpower", "zenpower3", "zenpower5",
                                   "k10temp", "coretemp"})
        if watts is None:
            watts = self._hwmon_energy({"zenergy", "amd_energy"})
        if watts is None:
            watts = self._rapl_watts()
        # "no value yet" and "no sensor at all" are different answers.
        # An energy counter returns None on its first read by design -
        # watts are a delta, so the baseline poll has nothing to report -
        # and warning about that would call a working setup broken one
        # poll before it starts working.
        if (watts is None and not self._cpu_power_warned
                and not self._cpu_power_source):
            self._cpu_power_warned = True
            # Say what was actually found, not just that nothing worked.
            # Guessing from the outside which sensor a machine has costs
            # a round trip per guess.
            seen = ", ".join(f"{z}({n or '?'})" for z, n, _f in
                             self._rapl_seen) or "none"
            self.log("Hardware: nothing on this machine reports CPU power "
                     "- {cpu_power} stays empty.")
            self.log(f"Hardware: powercap zones seen: {seen}")
            self.log(f"Hardware: hwmon names seen: {self._hwmon_names()}")
            self.log("Hardware: if btop shows CPU watts on this machine, "
                     "the counter exists and this list is what to send "
                     "back - it is a lookup problem, not a missing sensor.")
        return watts

    def _hwmon_names(self):
        """Every hwmon node with the attributes we could use, for the
        diagnostic log line above."""
        out = []
        try:
            nodes = sorted(Path("/sys/class/hwmon").glob("hwmon*"))
        except OSError:
            return "unreadable"
        for hw in nodes:
            name = (_read(hw / "name") or "?").strip()
            attrs = []
            for f in ("power1_average", "power1_input"):
                if (hw / f).exists():
                    attrs.append(f)
            if list(hw.glob("energy*_input")):
                attrs.append("energy*_input")
            if attrs:
                out.append(f"{name}[{'+'.join(attrs)}]")
            else:
                out.append(name)
        return ", ".join(out) or "none"

    def amd_gpu_power(self):
        """Watts from our own card's hwmon node - see _card_hwmon()."""
        node = self._card_hwmon()
        watts = self._power_from_node(node) if node else None
        if watts is None:
            # older kernels put the node elsewhere; the global scan is
            # still a reasonable second try
            watts = self._hwmon_power({"amdgpu"})
        if watts is None and not self._gpu_power_warned:
            self._gpu_power_warned = True
            self.log("Hardware: this GPU reports no power sensor "
                     "- {gpu_power} stays empty.")
        return watts

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
                     "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3).stdout.strip()
                cols = out.splitlines()[0].split(",")
                u, t, mu, mt = [float(x) for x in cols[:4]]
                # power.draw reads "[N/A]" on cards that do not report it,
                # and asking for it must not cost us the four values that
                # always work - hence parsed separately
                try:
                    power = float(cols[4])
                except (IndexError, ValueError):
                    power = None
                return {"usage": u, "temp": t, "power": power,
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
                        "power": self.amd_gpu_power(),
                        "vram_used": vu, "vram_total": vt,
                        "vram_pct": (100.0 * vu / vt) if (vu is not None and vt) else None}
            except Exception:
                return None
        return None

    # ------------------------------------------------------------------ fps
    #
    # There is no universal way to read a game's frame rate on Linux: the
    # kernel exposes GPU load through /sys, but frames per second only
    # exist inside the process drawing them. MangoHud already sits in that
    # process, and with logging on it appends a CSV row per interval - so
    # tailing its newest log is the one source that works for any Vulkan
    # or OpenGL title, VRChat under Proton included.
    #
    # Enable it in VRChat's Steam launch options, e.g.
    #   MANGOHUD=1 MANGOHUD_CONFIG=output_folder=/home/<you>/mangohud,\
    #   autostart_log=1,log_interval=1000 mangohud %command%
    def fps(self, folder=None):
        """Newest FPS value from MangoHud's log folder, or None."""
        folder = Path(folder).expanduser() if folder else self.mangohud_dir
        if folder is None or not folder.is_dir():
            return None
        try:
            logs = [p for p in folder.iterdir()
                    if p.is_file() and p.suffix.lower() == ".csv"]
            if not logs:
                return None
            newest = max(logs, key=lambda p: p.stat().st_mtime)
            # a stale log would otherwise report the FPS of a session that
            # ended hours ago
            if time.time() - newest.stat().st_mtime > 15:
                return None
            return self._last_fps(newest)
        except OSError as e:
            self.log(f"FPS: {folder} not readable ({e})")
            return None

    @staticmethod
    def _last_fps(path):
        """Reads the fps column of the last data row. Only the tail is
        read, so a long benchmark log stays cheap to poll."""
        try:
            size = path.stat().st_size
            with open(path, "rb") as fh:
                fh.seek(max(0, size - 4096))
                tail = fh.read().decode("utf-8", "replace")
        except OSError:
            return None
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        col = 0
        for ln in lines:
            if "fps" in ln.lower() and "," in ln:
                header = [c.strip().lower() for c in ln.split(",")]
                if "fps" in header:
                    col = header.index("fps")
                break
        for ln in reversed(lines):
            parts = ln.split(",")
            if len(parts) <= col:
                continue
            try:
                value = float(parts[col])
            except ValueError:
                continue          # header or a summary row
            if 0 < value < 10000:
                return value
        return None

    # -------------------------------------------------------------- snapshot
    def snapshot(self):
        return {"cpu_usage": self.cpu_usage(),
                "cpu_temp": self.cpu_temp(),
                "cpu_power": self.cpu_power(),
                "ram": self.ram(),
                "gpu": self.gpu(),
                "fps": self.fps()}
