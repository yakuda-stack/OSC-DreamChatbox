"""
tests/test_feedback_v159.py - the three things from user feedback in v1.5.9.

* Personal Status holds more than 20 texts (STATUS_MAX_TEXTS), and the
  rotation walks all of them.
* {ram_used} / {vram_used} are the numbers only, next to {ram_usage}
  (numbers and/or percent, as ticked) and {ram_pct}.
* The CPU temperature sensor can be picked by hand - on Linux from
  /sys/class/hwmon, on Windows from LibreHardwareMonitor's tree.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from core.backends import hardware_linux
from core.constants import STATUS_MAX_TEXTS
from ui.pages.apps_page import AppsPageMixin


# ------------------------------------------------------------ status limit
def test_the_cap_is_above_the_old_twenty():
    assert STATUS_MAX_TEXTS > 20


def test_rotation_reaches_texts_beyond_twenty():
    page = AppsPageMixin.__new__(AppsPageMixin)
    texts = [f"Quote {i + 1}" for i in range(STATUS_MAX_TEXTS)]
    page.cfg = {"status_texts": texts, "status_count": STATUS_MAX_TEXTS,
                "status_random": False, "send_to_vrchat": False}
    page.status_index = 0
    page.pending_status_index = None
    page.sending_live = lambda: False
    page.afk_holds_the_chatbox = lambda: False
    page.update_preview = lambda: None
    seen = []
    for _ in range(STATUS_MAX_TEXTS):
        seen.append(page.current_status_text())
        page.advance_status()
    assert seen == texts


# ------------------------------------------------------------ RAM values
def _hw_page(used, pct):
    page = AppsPageMixin.__new__(AppsPageMixin)
    page.cfg = {
        "hw_vram_used": used, "hw_vram_pct": pct,
        "hw_ram_used": used, "hw_ram_pct": pct, "hw_ram_type": "",
        "hw_gpu_usage": True, "hw_gpu_temp": False, "hw_gpu_power": False,
        "hw_cpu_usage": True, "hw_cpu_temp": False, "hw_cpu_power": False,
        "hw_gpu2": False, "hw_flame": False,
    }
    page._hw_display_name = lambda which: which.upper()
    return page


INFO = {"ram": {"used": 12.0, "total": 32.0, "pct": 37.5},
        "gpu": {"vram_used": 4.0, "vram_total": 16.0, "vram_pct": 25.0}}


def test_used_is_numbers_only_with_both_ticks():
    vals = _hw_page(True, True)._hw_values(INFO)
    assert vals["ram_usage"] == "12/32GB 38%"      # unchanged behaviour
    assert vals["ram_used"] == "12/32GB"
    assert vals["ram_pct"] == "38%"
    assert vals["vram_used"] == "4/16GB"
    assert vals["vram_pct"] == "25%"


def test_used_follows_the_numbers_tick():
    vals = _hw_page(False, True)._hw_values(INFO)
    assert vals["ram_used"] is None
    assert vals["vram_used"] is None
    assert vals["ram_usage"] == "38%"


# ------------------------------------------------------ CPU temp, Linux
@pytest.fixture
def fake_hwmon(tmp_path, monkeypatch):
    root = tmp_path / "hwmon"

    def node(n, name, temps):
        d = root / f"hwmon{n}"
        d.mkdir(parents=True)
        (d / "name").write_text(name + "\n")
        for i, (label, milli) in enumerate(temps, 1):
            (d / f"temp{i}_input").write_text(f"{milli}\n")
            if label:
                (d / f"temp{i}_label").write_text(label + "\n")

    node(0, "k10temp", [("Tctl", 71000), ("Tccd1", 52000)])
    node(1, "nvme", [("Composite", 40000)])
    node(2, "nvme", [("Composite", 44000)])
    node(3, "acpitz", [(None, 27800)])

    real = Path

    def fake_path(*args):
        p = real(*args)
        if str(p).startswith("/sys/class/hwmon"):
            return real(str(p).replace("/sys/class/hwmon", str(root), 1))
        return p
    monkeypatch.setattr(hardware_linux, "Path", fake_path)
    mon = hardware_linux.HardwareMonitor.__new__(hardware_linux.HardwareMonitor)
    mon._hwmon_cache = {}
    mon.log = lambda *_a: None
    mon.sel_cpu_temp = None
    mon._sel_temp_path = None
    mon._sel_temp_warned = False
    return mon, root


def test_linux_lists_every_sensor_with_stable_ids(fake_hwmon):
    mon, _ = fake_hwmon
    ids = [s["id"] for s in mon.list_temp_sensors()]
    assert ids == ["k10temp/Tctl", "k10temp/Tccd1", "nvme/Composite",
                   "nvme/Composite#2", "acpitz/temp1"]


def test_linux_automatic_is_unchanged(fake_hwmon):
    mon, _ = fake_hwmon
    assert mon.cpu_temp() == 71.0


def test_linux_picked_sensor_wins(fake_hwmon):
    mon, root = fake_hwmon
    mon.select_cpu_temp("k10temp/Tccd1")
    assert mon.cpu_temp() == 52.0
    (root / "hwmon0" / "temp2_input").write_text("55000\n")
    assert mon.cpu_temp() == 55.0            # cached path, fresh value


def test_linux_missing_sensor_falls_back(fake_hwmon):
    mon, _ = fake_hwmon
    mon.select_cpu_temp("zenpower/Tdie")
    assert mon.cpu_temp() == 71.0
    mon.select_cpu_temp(None)
    assert mon.cpu_temp() == 71.0


# ---------------------------------------------------- CPU temp, Windows
def test_windows_lhm_pick(monkeypatch):
    from core.backends.hardware_windows import _Lhm

    def sensor(text, value):
        return {"Text": text, "Value": value, "Children": []}
    tree = {"Text": "Sensor", "Children": [{"Text": "PC", "Children": [
        {"Text": "AMD Ryzen 7 5800X", "Children": [
            {"Text": "Temperatures", "Children": [
                sensor("Core (Tctl/Tdie)", "80,0 °C"),
                sensor("CCD1 (Tdie)", "55,0 °C")]}]},
        {"Text": "Nuvoton NCT6798D", "Children": [
            {"Text": "Temperatures", "Children": [
                sensor("CPU", "48,0 °C")]}]},
    ]}]}
    lhm = _Lhm(url="http://x")
    monkeypatch.setattr(lhm, "_fetch", lambda: tree)
    cpu, _gpu = lhm.temps()
    assert cpu == 80.0
    ids = [t["id"] for t in lhm.temp_list]
    assert "Nuvoton NCT6798D / Temperatures / CPU" in ids
    lhm.cpu_pick = "AMD Ryzen 7 5800X / Temperatures / CCD1 (Tdie)"
    lhm._cache = (0.0, None, None)
    assert lhm.temps()[0] == 55.0
