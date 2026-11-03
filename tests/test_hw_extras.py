"""
tests/test_hw_extras.py - the hardware additions of v1.7.1.

No Windows and no real card here, so every source is fed with what the
real one is documented to hand back: a fake COM object for DXGI, counter
instance names for PDH, CSV lines for nvidia-smi, a fake hwmon folder.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import ctypes
import subprocess

import pytest

from core.backends import (adl_windows, dxgi_windows, hardware_windows,
                           netstats, nvsmi, ramtype)
from core.backends.dxgi_windows import DXGI_ADAPTER_DESC1
from core.backends.hardware_linux import _amd_extras
from core.backends.hardware_windows import (
    WindowsHardwareMonitor, _gpu_counters, _luid_key)
from core.backends.nvsmi import _NvidiaSmiLoop, _parse_nvsmi
from core.textutils import canonical_placeholder


# ====================================================================
# DXGI through a fake COM object
# ====================================================================
class FakeCom:
    """A pointer to a table of function pointers, like a real COM object."""

    def __init__(self, methods):
        self.released = 0
        self._keep = []
        table = (ctypes.c_void_p * 16)()
        for index, fn in methods.items():
            self._keep.append(fn)
            table[index] = ctypes.cast(fn, ctypes.c_void_p)
        release = ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
            self._release)
        self._keep.append(release)
        table[2] = ctypes.cast(release, ctypes.c_void_p)
        self._table = table
        self.pointer = ctypes.pointer(ctypes.c_void_p(
            ctypes.addressof(table)))
        self.address = ctypes.cast(self.pointer, ctypes.c_void_p)

    def _release(self, _self):
        self.released += 1
        return 0


def fake_adapter(name, vendor, vram, luid_low, flags=0):
    def get_desc1(_self, desc):
        d = desc.contents
        for i, ch in enumerate(name):
            d.Description[i] = ord(ch)
        d.VendorId = vendor
        d.DedicatedVideoMemory = vram
        d.LuidLowPart = luid_low
        d.LuidHighPart = -1
        d.Flags = flags
        return 0
    proto = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                             ctypes.POINTER(DXGI_ADAPTER_DESC1))
    return FakeCom({10: proto(get_desc1)})


def fake_factory(adapters):
    def enum_adapters1(_self, index, out):
        if index >= len(adapters):
            return -1
        out[0] = adapters[index].address.value
        return 0
    proto = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
                             ctypes.POINTER(ctypes.c_void_p))
    return FakeCom({12: proto(enum_adapters1)})


def test_desc_layout_matches_windows():
    assert ctypes.sizeof(DXGI_ADAPTER_DESC1) == 312


def test_factory_walk_reads_each_adapter_and_releases_it():
    adapters = [fake_adapter("AMD Radeon RX 9060 XT", dxgi_windows.VENDOR_AMD,
                             8 << 30, 0xABCD)]
    factory = fake_factory(adapters)
    got = dxgi_windows.walk_factory(factory.address)
    assert got == [{"name": "AMD Radeon RX 9060 XT",
                    "vendor": dxgi_windows.VENDOR_AMD, "vram": 8 << 30,
                    "luid": (0xFFFFFFFF, 0xABCD), "software": False}]
    assert adapters[0].released == 1


def test_usable_drops_software_and_sorts_by_vram():
    rows = [{"name": "Basic", "vendor": dxgi_windows.VENDOR_MICROSOFT,
             "vram": 0, "software": False},
            {"name": "Sw", "vendor": 1, "vram": 9, "software": True},
            {"name": "iGPU", "vendor": 2, "vram": 1, "software": False},
            {"name": "dGPU", "vendor": 3, "vram": 8, "software": False}]
    assert [a["name"] for a in dxgi_windows.usable(rows)] == ["dGPU", "iGPU"]


# ====================================================================
# PDH per card
# ====================================================================
A = "luid_0x00000000_0x0000AAAA_phys_0"
B = "luid_0x00000000_0x0000BBBB_phys_0"


def engine(luid, kind, pid=1):
    return f"pid_{pid}_{luid}_eng_0_engtype_{kind}"


def test_luid_is_read_from_the_instance_name():
    assert _luid_key(engine(A, "3D")) == (0, 0xAAAA)
    assert _luid_key(A.upper().replace("0X", "0x")) == (0, 0xAAAA)
    assert _luid_key("no id here") is None


def test_each_card_gets_its_own_load_and_memory():
    got = _gpu_counters(
        [(engine(A, "3D", 1), 40.0), (engine(A, "3D", 2), 20.0),
         (engine(A, "Copy"), 5.0), (engine(B, "3D"), 7.0)],
        [],
        [(A, 2e9), (B, 1e9)])
    assert got[(0, 0xAAAA)] == (60.0, 2e9)
    assert got[(0, 0xBBBB)] == (7.0, 1e9)


def test_adapter_memory_beats_the_process_sum():
    got = _gpu_counters([], [(f"pid_1_{A}", 5e9)], [(A, 2e9)])
    assert got[(0, 0xAAAA)][1] == 2e9


def test_process_memory_is_the_fallback():
    got = _gpu_counters([], [(f"pid_1_{A}", 1e9), (f"pid_2_{A}", 1e9)], [])
    assert got[(0, 0xAAAA)][1] == 2e9


def test_no_luid_means_the_whole_machine():
    got = _gpu_counters([(engine(A, "3D"), 30.0), (engine(B, "3D"), 30.0)],
                        [], [])
    assert got[None][0] == 60.0


# ====================================================================
# nvidia-smi
# ====================================================================
FULL = "0, 42, 61, 4096, 16384, 180.0, 55, 2100, 9500, 70"


def test_new_columns_are_read():
    got = _parse_nvsmi(FULL, 0)
    assert (got["fan"], got["clock"], got["vram_clock"], got["vram_temp"]) \
        == (55.0, 2100.0, 9500.0, 70.0)


def test_laptop_without_fan_keeps_everything_else():
    got = _parse_nvsmi("0, 42, 61, 4096, 16384, [N/A], [N/A], 2100, 9500", 0)
    assert got["usage"] == 42
    assert got["power"] is None and got["fan"] is None
    assert got["vram_temp"] is None


def probe_result(monkeypatch, code):
    monkeypatch.setattr(
        nvsmi.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, code, "", ""))


def test_memory_temp_is_asked_for_only_where_the_driver_knows_it(monkeypatch):
    probe_result(monkeypatch, 0)
    assert nvsmi.query_for().endswith(",temperature.memory")
    probe_result(monkeypatch, 2)
    assert nvsmi.query_for() == _NvidiaSmiLoop.QUERY


def test_a_missing_nvidia_smi_does_not_raise():
    assert nvsmi.query_for("/no/such/exe") == _NvidiaSmiLoop.QUERY


# ====================================================================
# Linux hwmon
# ====================================================================
def test_hwmon_files_are_found_by_their_label(tmp_path):
    files = {"temp1_label": "edge", "temp1_input": "50000",
             "temp2_label": "junction", "temp2_input": "71000",
             "temp3_label": "mem", "temp3_input": "66000",
             "freq1_label": "sclk", "freq1_input": "2450000000",
             "freq2_label": "mclk", "freq2_input": "1200000000",
             "pwm1": "127", "pwm1_max": "255", "fan1_input": "1450"}
    for name, value in files.items():
        (tmp_path / name).write_text(value + "\n")
    got = _amd_extras(tmp_path)
    assert (got["hotspot"], got["vram_temp"]) == (71.0, 66.0)
    assert (got["clock"], got["vram_clock"]) == (2450.0, 1200.0)
    assert got["fan"] == pytest.approx(49.8, abs=0.1)
    assert got["fan_rpm"] == 1450


def test_no_hwmon_node_is_no_values():
    assert _amd_extras(None) == {}


# ====================================================================
# network
# ====================================================================
PROC = """Inter-|   Receive  |  Transmit
 face |bytes packets errs drop fifo frame compressed multicast|bytes
    lo: 900 1 0 0 0 0 0 0 900 1 0 0 0 0 0 0
enp5s0: 5000 1 0 0 0 0 0 0 700 1 0 0 0 0 0 0
tun0: 9000 1 0 0 0 0 0 0 800 1 0 0 0 0 0 0
"""


def test_proc_net_columns():
    assert netstats.parse_proc_net(PROC)["enp5s0"] == (5000, 700)


def test_automatic_skips_virtual_connections():
    assert netstats.pick_interface(
        {"lo": 99, "tun0": 98, "enp5s0": 5}) == "enp5s0"


def test_a_picked_connection_wins_if_it_exists():
    totals = {"enp5s0": 5, "wlan0": 1}
    assert netstats.pick_interface(totals, "wlan0") == "wlan0"
    assert netstats.pick_interface(totals, "gone0") == "enp5s0"


def test_linux_source_gives_speed_from_two_readings(tmp_path):
    path = tmp_path / "dev"
    path.write_text("eth0: 1000 0 0 0 0 0 0 0 100 0 0 0 0 0 0 0\n")
    source = netstats.LinuxNetSource(str(path))
    assert source.sample() == {}
    source._prev_at -= 2.0
    path.write_text("eth0: 3000 0 0 0 0 0 0 0 300 0 0 0 0 0 0 0\n")
    down, up = source.sample()["eth0"]
    assert down == pytest.approx(1000, rel=0.05)
    assert up == pytest.approx(100, rel=0.05)


def test_monitor_does_nothing_until_a_tick_is_on():
    calls = []
    monitor = netstats.NetMonitor(lambda: calls.append(1))
    assert monitor.read() is None
    assert calls == [], "the source must not be built while off"


def test_monitor_survives_a_broken_source():
    def explode():
        raise OSError("nope")
    logged = []
    monitor = netstats.NetMonitor(explode, logged.append)
    monitor.configure(True)
    assert monitor.read() is None and monitor.read() is None
    assert len(logged) == 1


# ====================================================================
# RAM type
# ====================================================================
def test_empty_slots_do_not_hide_the_real_type():
    assert ramtype.first_known([0, 2, 34, 34]) == "DDR5"
    assert ramtype.first_known([0]) is None


def test_powershell_output():
    assert ramtype.parse_wmi_output("26\r\n26\r\n") == "DDR4"
    assert ramtype.parse_wmi_output("") is None


def test_dmi_table_is_read_at_the_type_offset(tmp_path):
    raw = bytearray(40)
    raw[0x12] = 34
    (tmp_path / "17-0").write_bytes(raw)
    assert ramtype.linux_ram_type(str(tmp_path / "17-*")) == "DDR5"


def test_probe_never_blocks_and_only_runs_once():
    calls = []
    probe = ramtype.RamTypeProbe(lambda: calls.append(1) or "DDR4")
    probe.get()
    probe._started = True
    import threading
    for t in threading.enumerate():
        if t.name == "ram-type":
            t.join(1)
    assert probe.get() == "DDR4"
    assert calls == [1]


# ====================================================================
# the Windows backend with mixed cards
# ====================================================================
class FakePdh:
    def __init__(self, values):
        self.values = values

    def poll(self, luid=None):
        return self.values.get(luid, (None, None))


NV_ADAPTER = {"name": "NVIDIA GeForce RTX 4060", "vram": 8 << 30,
              "luid": (0, 1), "vendor": dxgi_windows.VENDOR_NVIDIA}
RX_ADAPTER = {"name": "AMD Radeon RX 9060 XT", "vram": 8 << 30,
              "luid": (0, 2), "vendor": dxgi_windows.VENDOR_AMD}
INTEL_ADAPTER = {"name": "Intel(R) UHD Graphics", "vram": 1 << 30,
                 "luid": (0, 3), "vendor": dxgi_windows.VENDOR_INTEL}


def backend(monkeypatch, adapters, smi=None):
    monkeypatch.setattr(hardware_windows, "_windows_adapters",
                        lambda: [dict(a) for a in adapters])
    monkeypatch.setattr(hardware_windows, "_find_nvidia_smi", lambda: smi)
    monkeypatch.setattr(adl_windows, "AdlReader",
                        lambda _log: (_ for _ in ()).throw(OSError("none")))
    monkeypatch.setattr(nvsmi, "query_for", lambda *a: "index")
    monkeypatch.setattr(
        hardware_windows, "_run",
        lambda cmd, timeout=3: "0, NVIDIA GeForce RTX 4060" if smi else "")
    hw = WindowsHardwareMonitor(lambda _m: None)
    hw.temp_helper = None
    hw._lhm.temps = lambda: (None, None)
    hw._lhm.powers = lambda: (None, None)
    return hw


def test_every_card_has_its_own_numbers(monkeypatch):
    hw = backend(monkeypatch, [RX_ADAPTER, INTEL_ADAPTER])
    hw._pdh = FakePdh({(0, 2): (50.0, 2 << 30), (0, 3): (9.0, 1 << 29)})
    first, second = hw.list_gpus()
    assert "name only" not in second["label"]
    assert hw.gpu(first["id"])["usage"] == 50.0
    got = hw.gpu(second["id"])
    assert got["usage"] == 9.0
    assert got["vram_used"] == 0.5 and got["vram_total"] == 1


def test_lhm_sensors_never_land_on_the_second_card(monkeypatch):
    hw = backend(monkeypatch, [RX_ADAPTER, INTEL_ADAPTER])
    hw._pdh = FakePdh({})
    hw._lhm.temps = lambda: (None, 60.0)
    first, second = hw.list_gpus()
    assert hw.gpu(first["id"])["temp"] == 60.0
    assert hw.gpu(second["id"])["temp"] is None


def test_nvidia_and_amd_are_both_listed(monkeypatch):
    hw = backend(monkeypatch, [NV_ADAPTER, RX_ADAPTER], smi="nvidia-smi.exe")
    names = [g["name"] for g in hw.list_gpus()]
    assert names == ["RTX 4060", "RX 9060 XT"]


def test_nvidia_without_nvidia_smi_is_still_listed(monkeypatch):
    hw = backend(monkeypatch, [NV_ADAPTER])
    assert [g["name"] for g in hw.list_gpus()] == ["RTX 4060"]


def test_nvidia_smi_pauses_after_three_silent_polls(monkeypatch):
    hw = backend(monkeypatch, [NV_ADAPTER], smi="nvidia-smi.exe")
    asked = []
    hw._nvsmi.latest = lambda index: asked.append(index)
    for _ in range(5):
        assert hw._nvidia_values(0) is None
    assert len(asked) == 3, "the last two polls should not ask at all"


def test_snapshot_carries_network_and_ram_type(monkeypatch):
    hw = backend(monkeypatch, [RX_ADAPTER])
    hw._pdh = FakePdh({})
    snap = hw.snapshot()
    assert "net" in snap and "ram_type" in snap


# ====================================================================
# placeholders
# ====================================================================
@pytest.mark.parametrize("typed, real", [
    ("hotspot", "gpu_hotspot"), ("gpu_2_fan", "gpu2_fan"),
    ("vram_temperature", "vram_temp"), ("download", "net_down"),
    ("upload", "net_up"),
])
def test_spellings(typed, real):
    assert canonical_placeholder(typed) == real
