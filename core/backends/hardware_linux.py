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

Since v1.5.1 every card the machine has is enumerated instead of one
being guessed: list_gpus() returns them all with a stable id, and
select_gpus() says which one the GPU line reports on and which one -
if any - fills the second set of values. gpu() with no argument keeps
meaning "the selected card", so callers written before this still work.
"""

import re
import shlex
import shutil
import subprocess
import threading
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
            "vram_pct": 100.0 * mu / mt if mt else None}


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
        with no reader and gets SIGPIPE on its next line
    """

    QUERY = ("index,utilization.gpu,temperature.gpu,"
             "memory.used,memory.total,power.draw")
    IDLE_STOP_SEC = 15

    def __init__(self, interval=2, log_fn=print):
        self.interval = interval
        self.log = log_fn
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
                ["nvidia-smi", f"--query-gpu={self.QUERY}",
                 "--format=csv,noheader,nounits", f"--loop={self.interval}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1)
        except Exception as e:
            self._proc = None
            self._fail(f"could not be started ({e})")
            return
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


class HardwareMonitor:
    def __init__(self, log_fn):
        # FPS used to be read here. It moved into the World Stats plugin
        # in v1.4.4, because getting a frame rate means loading something
        # into the game itself - a Vulkan layer - and that is a different
        # kind of thing from reading /proc and /sys.
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
        self._nvsmi = _NvidiaSmiLoop(log_fn=log_fn) if self.has_nvidia else None
        self.amd_cards = self._find_amd_cards()
        # kept as a single value because plugins and the UI read it to
        # decide "is there an AMD card at all"
        self.amd_card = self.amd_cards[0][1] if self.amd_cards else None
        self._gpus = self._enumerate_gpus()
        #: ids chosen in the Hardware card; None = "the first one"
        self.sel_gpu = None
        self.sel_gpu2 = None
        self.gpu_name_auto = self._name_of(self._gpu_entry(None))
        self.gpu2_name_auto = "GPU"
        self.cpu_name_auto = self._detect_cpu_name()
        self.log(f"Hardware: GPU={'NVIDIA' if self.has_nvidia else ('AMD' if self.amd_card else 'none detected')}"
                 f", CPU='{self.cpu_name_auto}', GPU name='{self.gpu_name_auto}'")
        if len(self._gpus) > 1:
            self.log("Hardware: cards found: "
                     + ", ".join(f"{g['id']}='{g['name']}'"
                                 for g in self._gpus))

    # ------------------------------------------------------------- detection
    def _find_amd_cards(self):
        """Every AMD card sysfs reports on, the one with the most VRAM
        first. Returns [(card name, device dir, vram bytes), ...].

        A Ryzen desktop chip brings its own integrated Radeon, so there
        are usually two candidates and card0 is as likely to be the iGPU
        as the discrete card. Whichever has more VRAM is the better
        default - an iGPU carves a few hundred MB out of system memory, a
        discrete card has gigabytes - and that beats trusting the
        numbering, which changes with the boot order. Since v1.5.1 the
        other cards are not thrown away: they end up in the GPU dropdown,
        so a wrong guess is a dropdown away from being corrected.
        """
        found = []
        for card in sorted(Path("/sys/class/drm").glob("card*")):
            # cardN, not the cardN-DP-1 connector directories next to it
            if not re.fullmatch(r"card\d+", card.name):
                continue
            dev = card / "device"
            if not (dev / "gpu_busy_percent").exists():
                continue
            try:
                vram = int(_read(dev / "mem_info_vram_total") or 0)
            except ValueError:
                vram = 0
            found.append((card.name, dev, vram))
        found.sort(key=lambda c: -c[2])
        return found

    def _find_nvidia_cards(self):
        """[(index, name), ...] from nvidia-smi, or []."""
        if not self.has_nvidia:
            return []
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,name",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return []
        cards = []
        for line in out.splitlines():
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

    def _pci_device_names(self):
        """{"03:00.0": "Navi 48 [Radeon RX 9070 XT]"} from lspci.

        sysfs knows a card's PCI address but not its marketing name, so
        the two are joined here. Called once per start, like every other
        detection step.
        """
        names = {}
        if not shutil.which("lspci"):
            return names
        try:
            out = subprocess.run(["lspci", "-mm"], capture_output=True,
                                 text=True, timeout=3).stdout
        except Exception:
            return names
        for line in out.splitlines():
            try:
                fields = shlex.split(line)
            except ValueError:
                continue
            if len(fields) >= 4:
                names[fields[0]] = fields[3]
        return names

    def _enumerate_gpus(self):
        """Every card the machine has, as the dicts list_gpus() hands out.

        {"id": "nvidia:0" | "amd:card1", "name", "vendor", "label",
         "index" (NVIDIA), "path" (AMD)}
        """
        gpus = []
        nvidia = self._find_nvidia_cards()
        if not nvidia and self.has_nvidia:
            # nvidia-smi is there but the enumerating call did not answer
            # (driver still loading, a timeout). Card 0 is what this
            # backend has always read, so it stays available either way.
            nvidia = [(0, self._detect_gpu_name())]
        for idx, name in nvidia:
            gpus.append({"id": f"nvidia:{idx}", "name": name,
                         "vendor": "NVIDIA", "index": idx,
                         "label": f"NVIDIA #{idx} · {name}"})
        pci = self._pci_device_names() if self.amd_cards else {}
        for pos, (card, dev, vram) in enumerate(self.amd_cards):
            name = ""
            try:
                slot = dev.resolve().name.split(":", 1)[-1]
            except OSError:
                slot = ""
            if slot:
                raw = pci.get(slot, "")
                # "Navi 32 [Radeon RX 7700 XT / 7800 XT]" -> bracket part
                br = re.findall(r"\[([^\]]+)\]", raw)
                name = _clean_gpu_name(br[-1] if br else raw)
            # the card with the most VRAM is the one glxinfo describes
            # (it reports the renderer the desktop is running on), and a
            # Mesa name is exact where lspci often lists every variant
            # sharing one PCI id. Only a renderer that really IS an AMD
            # card counts: on an NVIDIA + AMD machine the generic
            # _detect_gpu_name() asks nvidia-smi first and handed the AMD
            # card the GeForce's name (v1.5.1: "AMD card2 · RTX 3060").
            if pos == 0:
                name = self._detect_mesa_amd_name() or name
            if not name:
                name = f"GPU {card}"
            gb = vram / GB if vram else 0
            # the sysfs node name only helps telling two AMD cards apart
            tag = f"AMD {card}" if len(self.amd_cards) > 1 else "AMD"
            gpus.append({"id": f"amd:{card}", "name": name, "vendor": "AMD",
                         "path": dev,
                         "label": f"{tag} · {name}"
                                  + (f" ({gb:.0f}GB)" if gb >= 1 else "")})
        if not gpus:
            # Intel, or a driver with no counters: nothing to read, but
            # the detected name still fills {gpu_name} the way it did
            # before there was a list at all
            name = self._detect_gpu_name()
            gpus.append({"id": "display", "name": name, "vendor": "",
                         "label": f"{name} (name only - no readings)"})
        return gpus

    # --------------------------------------------------------- selection
    def list_gpus(self):
        """Every card that can be reported on. The UI fills its dropdown
        from this, so the ids are what end up in the config file."""
        return list(self._gpus)

    def select_gpus(self, primary=None, second=None):
        """Which card the GPU values come from, and which one - if any -
        fills the second set. Both are ids from list_gpus(); anything
        unknown falls back to the default card (primary) or to nothing
        (second), so a card that was unplugged cannot empty the line."""
        self.sel_gpu = primary or None
        self.sel_gpu2 = second or None
        self.gpu_name_auto = self._name_of(self._gpu_entry(None))
        self.gpu2_name_auto = self._name_of(
            self._gpu_entry(self.sel_gpu2, fallback=False)) if self.sel_gpu2 \
            else "GPU"

    def _gpu_entry(self, gpu_id=None, fallback=True):
        """The dict for one id. None means "the selected card"."""
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
        """The detected name of one card, for the second GPU's label."""
        return self._name_of(self._gpu_entry(gpu_id, fallback=False))

    def _detect_cpu_name(self):
        txt = _read("/proc/cpuinfo") or ""
        m = re.search(r"model name\s*:\s*(.+)", txt)
        return _clean_cpu_name(m.group(1)) if m else "CPU"

    def _detect_mesa_amd_name(self):
        """Marketing name of the AMD card Mesa renders on, or "".

        Never consults nvidia-smi, and ignores a glxinfo renderer that is
        not AMD (PRIME setups where the desktop runs on another card)."""
        if not shutil.which("glxinfo"):
            return ""
        try:
            out = subprocess.run(["glxinfo", "-B"], capture_output=True,
                                 text=True, timeout=5).stdout
        except Exception:
            return ""
        m = re.search(r"^\s*Device:\s*(.+)$", out, re.MULTILINE)
        if not m:
            return ""
        raw = m.group(1)
        if not re.search(r"\b(AMD|ATI|Radeon|radeonsi)\b", raw, re.I):
            return ""
        name = re.sub(r"\s*\(.*\)\s*$", "", raw).strip()
        return _clean_gpu_name(name) if name else ""

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

    def amd_gpu_temp(self, card=None):
        """Same reasoning as amd_gpu_power(): our card's own node first,
        so the temperature cannot come from the iGPU while the load
        comes from the discrete card.

        `card` is a device directory from list_gpus(); None means the
        selected one, which is what every pre-1.5.1 caller wants."""
        node = self._card_hwmon(card)
        if node:
            for t in ("temp1_input", "temp2_input"):
                v = _read(node / t)
                if v:
                    try:
                        return int(v) / 1000.0
                    except ValueError:
                        pass
        # The global scan is a second try for older kernels that put the
        # node elsewhere - but only for the card this monitor defaults to.
        # For a specifically chosen second card it would be a coin flip
        # between two nodes both called amdgpu, and a temperature from the
        # wrong chip is worse than an empty one.
        if card is not None and card != self.amd_card:
            return None
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

    def _card_hwmon(self, card=None):
        """The hwmon directory belonging to *our* GPU.

        A desktop Ryzen has an integrated Radeon on top of the discrete
        card, so /sys/class/hwmon holds two nodes called `amdgpu` and
        glob() hands them back in filesystem order, which is not stable
        across boots. Picking "the first one named amdgpu" therefore
        reads the iGPU's sensors about as often as the dGPU's - while
        usage and VRAM come from self.amd_card either way, so the line
        ends up mixing two different chips.

        The card device owns its own hwmon node, so going through it
        removes the guess entirely - and it is what makes a second card
        readable at all: both of them are called amdgpu in
        /sys/class/hwmon, only their own directories tell them apart.
        """
        card = card if card is not None else self.amd_card
        if not card:
            return None
        key = ("card_hwmon", str(card))
        if key in self._hwmon_cache:
            return self._hwmon_cache[key]
        try:
            nodes = sorted((card / "hwmon").glob("hwmon*"))
        except OSError:
            nodes = []
        node = nodes[0] if nodes else None
        self._hwmon_cache[key] = node
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

    def amd_gpu_power(self, card=None):
        """Watts from our own card's hwmon node - see _card_hwmon()."""
        node = self._card_hwmon(card)
        watts = self._power_from_node(node) if node else None
        if watts is None and (card is None or card == self.amd_card):
            # older kernels put the node elsewhere; the global scan is
            # still a reasonable second try - but only for the default
            # card, see amd_gpu_temp()
            watts = self._hwmon_power({"amdgpu"})
        if (watts is None and not self._gpu_power_warned
                and (card is None or card == self.amd_card)):
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
    def gpu(self, gpu_id=None):
        """Returns {usage, temp, power, vram_used, vram_total, vram_pct}
        (values may be None) for one card.

        `gpu_id` is an id from list_gpus(); None means the card selected
        in the Hardware card, which is what this method always returned.
        """
        entry = self._gpu_entry(gpu_id, fallback=gpu_id is None)
        if entry is None:
            return None
        if entry["vendor"] == "NVIDIA":
            idx = entry["index"]
            line = (self._nvsmi_once(idx) if self._nvsmi.broken
                    else self._nvsmi.latest(idx))
            return _parse_nvsmi(line, idx)
        card = entry.get("path")
        if card:
            try:
                usage = _read(card / "gpu_busy_percent")
                vu = _read(card / "mem_info_vram_used")
                vt = _read(card / "mem_info_vram_total")
                vu = int(vu) / GB if vu else None
                vt = int(vt) / GB if vt else None
                return {"usage": float(usage) if usage else None,
                        "temp": self.amd_gpu_temp(card),
                        "power": self.amd_gpu_power(card),
                        "vram_used": vu, "vram_total": vt,
                        "vram_pct": (100.0 * vu / vt) if (vu is not None and vt) else None}
            except Exception:
                return None
        return None

    def gpu2(self):
        """The second card's values, or None when none is selected."""
        if not self.sel_gpu2 or self.sel_gpu2 == self.sel_gpu:
            return None
        return self.gpu(self.sel_gpu2)

    def _nvsmi_once(self, index=0):
        """Fallback: the old one call per poll, for one card."""
        try:
            out = subprocess.run(
                ["nvidia-smi", "-i", str(index),
                 f"--query-gpu={_NvidiaSmiLoop.QUERY}",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3).stdout.strip()
            return out.splitlines()[0]
        except Exception:
            return None

    def close(self):
        """Called from closeEvent - ends the nvidia-smi process."""
        if self._nvsmi is not None:
            self._nvsmi.close()

    def snapshot(self):
        return {"cpu_usage": self.cpu_usage(),
                "cpu_temp": self.cpu_temp(),
                "cpu_power": self.cpu_power(),
                "ram": self.ram(),
                "gpu": self.gpu(),
                "gpu2": self.gpu2()}
