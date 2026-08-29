"""
core/hardware.py – hardware monitoring: picks the backend for this OS

The readings themselves live in core/backends/:

    hardware_linux.HardwareMonitor          /proc, /sys, nvidia-smi
    hardware_windows.WindowsHardwareMonitor Win32/PDH/nvidia-smi/LHM
    hardware_null.NullHardwareMonitor       every value is None

This module only decides which of them the name ``HardwareMonitor``
refers to, the same way core/translators.py hands out a backend through
``get_translator()``. Existing code keeps working unchanged:

    from core.hardware import HardwareMonitor
    hw = HardwareMonitor(log)

On Linux that is byte-for-byte the class that has always been here, just
in a different file.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from core.osinfo import IS_WINDOWS, OS_NAME
from core.backends.hardware_null import NullHardwareMonitor

#: filled in below; "linux" / "windows" / "null"
BACKEND_NAME = "null"
#: why we fell back, if we did - the UI can show this later
BACKEND_ERROR = ""

if IS_WINDOWS:
    GB = 1024 ** 3

    def _read(path):        # noqa: D401 - kept for API parity
        """Not meaningful on Windows (no /proc, no /sys)."""
        return None

    try:
        from core.backends.hardware_windows import (  # noqa: F401
            WindowsHardwareMonitor as HardwareMonitor,
            _clean_cpu_name, _clean_gpu_name)
        BACKEND_NAME = "windows"
    except Exception as _e:      # ctypes/winreg missing, Wine, ...
        # A broken import here must never stop the app from starting:
        # empty hardware values are survivable, a crash on launch is not.
        BACKEND_ERROR = f"{type(_e).__name__}: {_e}"
        HardwareMonitor = NullHardwareMonitor

        def _clean_cpu_name(name: str) -> str:
            return (name or "").strip()

        def _clean_gpu_name(name: str) -> str:
            return (name or "").strip()
else:
    from core.backends.hardware_linux import (  # noqa: F401
        GB, HardwareMonitor, _clean_cpu_name, _clean_gpu_name, _read)
    BACKEND_NAME = "linux"

#: True when the backend can produce real readings
HARDWARE_AVAILABLE = BACKEND_NAME != "null"


def get_hardware_monitor(log_fn):
    """Factory - use this in new code instead of the class directly."""
    return HardwareMonitor(log_fn)


def backend_note() -> str:
    """One line the UI can show next to the Hardware card."""
    if BACKEND_ERROR:
        return (f"Hardware backend for {OS_NAME} failed to load "
                f"({BACKEND_ERROR}) - values stay empty.")
    if not HARDWARE_AVAILABLE:
        return f"Hardware readings are not implemented on {OS_NAME} yet."
    if BACKEND_NAME == "windows":
        # the one value Windows cannot produce on its own, so nobody
        # files a bug about an empty temperature field
        return ("Temperatures need LibreHardwareMonitor (Options > Remote "
                "Web Server). Everything else works without extra "
                "software.")
    return ""


__all__ = ["HardwareMonitor", "NullHardwareMonitor", "HARDWARE_AVAILABLE",
           "BACKEND_NAME", "BACKEND_ERROR", "get_hardware_monitor",
           "backend_note", "GB"]
