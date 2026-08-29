"""core/backends/wintemp.py - the lookups must not repeat on every poll.

status() hangs off refresh_wintemp_status(), which hangs off every
hardware poll. Uncached, find_lhm() sweeps three Uninstall registry hives
and _lhm_running() spawns tasklist - every two seconds, on the GUI
thread, for the whole session. These tests pin the caches down so the
next refactor cannot quietly take them out again.

Runs on any platform: the Windows-only bits are stubbed.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.backends import wintemp


def _reset():
    wintemp._find_cache = (0.0, None)
    wintemp._running_cache = (0.0, False)


def test_find_lhm_scans_the_registry_once(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(wintemp, "IS_WINDOWS", True)
    monkeypatch.setattr(wintemp, "_lhm_from_registry",
                        lambda: calls.append("registry") or [])
    monkeypatch.setattr(wintemp, "_lhm_candidates", list)
    monkeypatch.setattr(wintemp.shutil, "which", lambda _n: None)

    for _ in range(50):          # ~100 seconds of 2 s polling
        wintemp.find_lhm()

    assert len(calls) == 1, f"registry swept {len(calls)}x, expected once"


def test_find_lhm_force_bypasses_the_cache(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(wintemp, "IS_WINDOWS", True)
    monkeypatch.setattr(wintemp, "_lhm_from_registry",
                        lambda: calls.append("registry") or [])
    monkeypatch.setattr(wintemp, "_lhm_candidates", list)
    monkeypatch.setattr(wintemp.shutil, "which", lambda _n: None)

    wintemp.find_lhm()
    wintemp.find_lhm(force=True)
    assert len(calls) == 2, "force=True must re-scan - the button needs it"


def test_find_lhm_caches_a_hit_too(monkeypatch):
    """A found path is as worth caching as a missing one - the machine
    that HAS LibreHardwareMonitor is not the one that should pay more."""
    _reset()
    calls = []
    here = Path(__file__).resolve()
    monkeypatch.setattr(wintemp, "IS_WINDOWS", True)
    monkeypatch.setattr(wintemp, "_lhm_from_registry",
                        lambda: calls.append("registry") or [here])
    monkeypatch.setattr(wintemp, "_lhm_candidates", list)

    first = wintemp.find_lhm()
    again = wintemp.find_lhm()
    assert first == here
    assert again == here
    assert len(calls) == 1


def test_find_lhm_expires(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(wintemp, "IS_WINDOWS", True)
    monkeypatch.setattr(wintemp, "_lhm_from_registry",
                        lambda: calls.append("registry") or [])
    monkeypatch.setattr(wintemp, "_lhm_candidates", list)
    monkeypatch.setattr(wintemp.shutil, "which", lambda _n: None)

    clock = [1000.0]
    monkeypatch.setattr(wintemp.time, "monotonic", lambda: clock[0])

    wintemp.find_lhm()
    clock[0] += wintemp._FIND_TTL + 1
    wintemp.find_lhm()
    assert len(calls) == 2, "an install that happened mid-session must " \
                            "still be noticed eventually"


def test_lhm_running_spawns_tasklist_once(monkeypatch):
    _reset()
    calls = []

    class FakeResult:
        stdout = ""

    def fake_run(*_a, **_kw):
        calls.append("tasklist")
        return FakeResult()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)

    for _ in range(10):
        wintemp._lhm_running()

    assert len(calls) == 1, f"tasklist spawned {len(calls)}x, expected once"
    assert wintemp._lhm_running(force=True) is False
    assert len(calls) == 2, "force=True must re-check"


def test_find_lhm_is_none_off_windows(monkeypatch):
    _reset()
    monkeypatch.setattr(wintemp, "IS_WINDOWS", False)

    def boom():
        raise AssertionError("the registry must never be touched on Linux")

    monkeypatch.setattr(wintemp, "_lhm_from_registry", boom)
    assert wintemp.find_lhm() is None
