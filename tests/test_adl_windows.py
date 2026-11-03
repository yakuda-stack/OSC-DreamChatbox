"""
tests/test_adl_windows.py - AMD sensors from atiadlxx.dll (v1.7.1).

No test machine here has the AMD driver, so a fake DLL stands in for it.
That pins the struct layout, the sensor choice, which card gets which
numbers and the fallback to the other sources. Whether AMD's sensor
numbers are right can only be seen in the log line on a real card.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import ctypes

import pytest

from core.backends import adl_windows, hardware_windows
from core.backends.adl_windows import (
    AdapterInfo, AdlReader, PmLogOutput, _norm)
from core.backends.hardware_windows import WindowsHardwareMonitor


class FakeAdl:
    """rows: (index, name, bus); sensors: {index: {number: value}}"""

    def __init__(self, rows, sensors):
        self.rows = rows
        self.sensors = sensors
        self.reads = 0

    def ADL2_Adapter_NumberOfAdapters_Get(self, _context, count):
        count._obj.value = len(self.rows)
        return 0

    def ADL2_Adapter_AdapterInfo_Get(self, _context, table, _size):
        for row, (index, name, bus) in zip(table._obj, self.rows):
            row.iAdapterIndex = index
            row.strAdapterName = name.encode()
            row.iBusNumber = bus
        return 0

    def ADL2_New_QueryPMLogData_Get(self, _context, index, buffer):
        self.reads += 1
        values = self.sensors.get(index)
        if values is None:
            return -1
        for number, value in values.items():
            buffer._obj.output.sensors[number].supported = 1
            buffer._obj.output.sensors[number].value = value
        return 0


RX = "AMD Radeon RX 9060 XT"
SENSORS = {73: 145, 23: 120, 8: 52, 27: 71, 19: 37}


def reader(rows=((0, RX, 3), (1, RX, 3)), sensors=None):
    table = {0: SENSORS, 1: SENSORS} if sensors is None else sensors
    return AdlReader(lib=FakeAdl(list(rows), table), context=1)


def test_struct_sizes_match_adl():
    assert ctypes.sizeof(AdapterInfo) == 1572
    assert ctypes.sizeof(PmLogOutput) == 2052


def test_display_outputs_of_one_card_are_one_card():
    assert len(reader().cards) == 1


def test_board_power_beats_asic_and_edge_beats_hotspot():
    got = reader().values(RX)
    assert (got["power"], got["temp"], got["usage"]) == (145.0, 52.0, 37.0)
    assert got["hotspot"] == 71.0


def test_extras_and_a_standing_fan():
    got = reader(sensors={0: {15: 0, 14: 0, 1: 2450, 2: 1200, 9: 66}}
                 ).values(RX)
    assert (got["fan"], got["fan_rpm"]) == (0.0, 0.0), "0 is a real speed"
    assert (got["clock"], got["vram_clock"]) == (2450.0, 1200.0)
    assert got["vram_temp"] == 66.0


def test_older_card_falls_back_to_asic_power():
    got = reader(sensors={0: {23: 120, 8: 40}}).values(RX)
    assert got["power"] == 120.0


def test_nonsense_values_are_dropped():
    got = reader(sensors={0: {73: 99999, 23: 0, 8: 900, 19: 500}}).values(RX)
    assert (got["power"], got["temp"], got["usage"]) == (None, None, None)


def test_unknown_card_gets_nothing():
    assert reader().values("Intel UHD Graphics") == {}


def test_sole_adapter_matches_despite_spelling():
    assert reader().values("AMD RX 9060 XT Series", sole=True)["power"] == 145


def test_two_cards_keep_their_own_numbers():
    igpu = "AMD Radeon(TM) Graphics"
    r = reader(rows=((0, igpu, 16), (1, RX, 3)),
               sensors={0: {23: 9}, 1: SENSORS})
    assert r.values(igpu)["power"] == 9
    assert r.values(RX)["power"] == 145


def test_reads_are_cached():
    r = reader()
    before = r._lib.reads
    r.values(RX)
    r.values(RX)
    assert r._lib.reads == before + 1


def test_no_readable_card_raises():
    with pytest.raises(OSError):
        reader(sensors={})


def test_norm_ignores_markers_and_case():
    assert _norm("AMD Radeon(TM) RX-9060") == "amdradeonrx9060"


# -------------------------------------------------------- the backend
@pytest.fixture
def backend(monkeypatch):
    def build(adapters, rows=((0, RX, 3),), sensors=None):
        fake = reader(rows=rows, sensors=sensors or {0: SENSORS})
        monkeypatch.setattr(hardware_windows, "_registry_gpus",
                            lambda: list(adapters))
        monkeypatch.setattr(hardware_windows, "_find_nvidia_smi",
                            lambda: None)
        monkeypatch.setattr(adl_windows, "AdlReader", lambda _log: fake)
        hw = WindowsHardwareMonitor(lambda _m: None)
        hw._pdh = None
        hw.temp_helper = None
        hw._lhm.temps = lambda: (None, None)
        hw._lhm.powers = lambda: (None, None)
        return hw
    return build


def test_gpu_gives_watts_and_temp_without_lhm(backend):
    got = backend([(RX, 8 << 30)]).gpu()
    assert (got["power"], got["temp"], got["usage"]) == (145.0, 52.0, 37.0)
    assert got["vram_total"] == 8


def test_card_the_driver_knows_comes_before_a_stale_entry(backend):
    hw = backend([("AMD Radeon RX 580", 16 << 30), (RX, 8 << 30)])
    assert hw.gpu_name_auto == "RX 9060 XT"
    assert hw.gpu()["power"] == 145.0


def test_second_card_with_sensors_is_not_name_only(backend):
    igpu = "AMD Radeon(TM) Graphics"
    hw = backend([(RX, 8 << 30), (igpu, 1 << 30)],
                 rows=((0, RX, 3), (1, igpu, 16)),
                 sensors={0: SENSORS, 1: {23: 9, 19: 4}})
    second = hw.list_gpus()[1]
    assert "name only" not in second["label"]
    assert hw.gpu(second["id"])["power"] == 9


def test_intel_card_next_to_radeon_gets_no_amd_numbers(backend):
    intel = "Intel(R) UHD Graphics"
    hw = backend([(RX, 8 << 30), (intel, 1 << 30)])
    second = hw.list_gpus()[1]
    assert hw.gpu(second["id"])["power"] is None


def test_lhm_still_fills_in_when_adl_has_no_value(backend):
    hw = backend([(RX, 8 << 30)], sensors={0: {19: 5}})
    hw._lhm.powers = lambda: (None, 88.0)
    hw._lhm.temps = lambda: (None, 44.0)
    got = hw.gpu()
    assert (got["power"], got["temp"]) == (88.0, 44.0)
