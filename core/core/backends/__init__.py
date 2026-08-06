"""
core/backends/ – one implementation per platform, one interface for the app.

Same idea as core/translators.py: several classes behind a single
contract, and a factory in the parent module picks the right one at
startup. The UI never imports from here directly - it keeps importing
``HardwareMonitor`` from core/hardware.py and ``MediaFetcher`` from
core/mediafetch.py, which now resolve to whichever backend fits the
running platform.

    hardware_linux.py   real readings from /proc, /sys and nvidia-smi
    hardware_null.py    everything returns None (Windows, for now)
    media_linux.py      MPRIS over D-Bus
    media_null.py       nothing is playing, ever (Windows, for now)

Adding a real Windows backend later means dropping in
``hardware_windows.py`` and pointing the factory at it - nothing else
in the app has to change.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later
