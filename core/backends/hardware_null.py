"""
core/backends/hardware_null.py – "no readings available" hardware backend

Used on every platform that has no real implementation yet (currently
Windows). It exposes the exact same attributes and methods as
core/backends/hardware_linux.HardwareMonitor, but every reading is None.

That is deliberately not an error state: the Hardware card in the UI
already treats None as "unknown" and simply leaves that value out of the
chatbox line, because on Linux a missing sensor or a machine without
a missing backend hits the same path. So the app runs, the card renders, and
nothing is sent that we cannot actually measure.

When the real Windows readings land (LibreHardwareMonitor / WMI /
nvidia-smi), they go into hardware_windows.py and the factory in
core/hardware.py switches over - this file stays as the fallback for
anything still unsupported.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations


from core.osinfo import OS_NAME

GB = 1024 ** 3


class NullHardwareMonitor:
    """API-compatible stand-in for HardwareMonitor. Reads nothing."""

    #: lets the UI / plugins tell a stub apart from a real backend
    available = False
    name = "null"

    def __init__(self, log_fn):
        self.log = log_fn
        # attributes the Hardware card reads directly
        self.has_nvidia = False
        self.amd_card = None
        self.cpu_name_auto = "CPU"
        self.gpu_name_auto = "GPU"
        self.gpu2_name_auto = "GPU"
        # GPU selection (v1.5.1). Nothing to choose from, so the list is
        # empty and the Hardware card hides its dropdown by itself.
        self.sel_gpu = None
        self.sel_gpu2 = None
        # see hardware_windows.py: lets the UI print a platform-correct
        # label instead of the hardcoded Linux "AMD (sysfs)"
        self.gpu_backend_label = "none detected"
        self._prev_cpu = None
        self.log(f"Hardware: no backend for {OS_NAME} yet - CPU/GPU/RAM "
                 f"stay empty. Set a custom CPU/GPU name in the Hardware "
                 f"card if you want the labels filled in.")

    # ------------------------------------------------------- single values
    def cpu_usage(self):
        return None

    def cpu_power(self):
        return None

    def amd_gpu_power(self):
        return None

    def cpu_temp(self):
        return None

    def amd_gpu_temp(self):
        return None

    def ram(self):
        """Would be {'used', 'total', 'pct'} - None means "don't show"."""
        return None

    def gpu(self, gpu_id=None):
        """Would be {'usage', 'temp', 'vram_used', 'vram_total',
        'vram_pct'} - None means "don't show"."""
        return None

    def gpu2(self):
        return None

    # ------------------------------------------------------ gpu selection
    def list_gpus(self):
        """No card can be read here, so there is nothing to pick from."""
        return []

    def select_gpus(self, primary=None, second=None):
        self.sel_gpu = primary or None
        self.sel_gpu2 = second or None

    def gpu_name_for(self, gpu_id):
        return "GPU"

    def snapshot(self):
        """Same shape as the Linux backend, so poll_hw() needs no
        special case: keys exist, values are None."""
        return {"cpu_usage": None,
                "cpu_temp": None,
                "cpu_power": None,
                "ram": None,
                "gpu": None,
                "gpu2": None}
