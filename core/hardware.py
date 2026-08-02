"""
core/hardware.py – hardware monitoring: picks the backend for this OS

The readings themselves live in core/backends/:

    hardware_linux.HardwareMonitor    /proc, /sys, nvidia-smi, MangoHud
    hardware_null.NullHardwareMonitor every value is None

This module only decides which of them the name ``HardwareMonitor``
refers to, the same way core/translators.py hands out a backend through
``get_translator()``. Existing code keeps working unchanged:

    from core.hardware import HardwareMonitor
    hw = HardwareMonitor(log, mangohud_dir)

On Linux that is byte-for-byte the class that has always been here, just
in a different file. On Windows it is the null backend, so the Hardware
card renders with empty values instead of the app failing to start.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from core.osinfo import IS_WINDOWS, OS_NAME
from core.backends.hardware_null import NullHardwareMonitor

if IS_WINDOWS:
    # No Windows readings yet - deliberately not a half-working guess.
    # Drop in core/backends/hardware_windows.py and import it here.
    HardwareMonitor = NullHardwareMonitor
    GB = 1024 ** 3

    def _read(path):        # noqa: D401 - kept for API parity
        """Not available without a real backend."""
        return None

    def _clean_cpu_name(name: str) -> str:
        return (name or "").strip()

    def _clean_gpu_name(name: str) -> str:
        return (name or "").strip()
else:
    from core.backends.hardware_linux import (  # noqa: F401
        GB, HardwareMonitor, _clean_cpu_name, _clean_gpu_name, _read)

#: True when the readings are real, False when they are all None
HARDWARE_AVAILABLE = not IS_WINDOWS
#: which backend got picked - for the debug console / bug reports
BACKEND_NAME = "linux" if HARDWARE_AVAILABLE else "null"


def get_hardware_monitor(log_fn, mangohud_dir=None):
    """Factory - use this in new code instead of the class directly."""
    return HardwareMonitor(log_fn, mangohud_dir)


def backend_note() -> str:
    """One line the UI can show next to the Hardware card."""
    if HARDWARE_AVAILABLE:
        return ""
    return f"Hardware readings are not implemented on {OS_NAME} yet."


__all__ = ["HardwareMonitor", "NullHardwareMonitor", "HARDWARE_AVAILABLE",
           "BACKEND_NAME", "get_hardware_monitor", "backend_note", "GB"]
