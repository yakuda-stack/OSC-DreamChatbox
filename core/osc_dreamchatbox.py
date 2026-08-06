#!/usr/bin/env python3
"""
OSC-DreamChatbox v1.3.1
A clean VRChat OSC chatbox sender.

Entry point only – the actual code lives in:
    core/     logic (media, hardware, speech-to-text, helpers)
    core/backends/  one implementation per platform (see core/osinfo.py)
    ui/       PyQt6 user interface

Requires: PyQt6, python-osc
    pip install PyQt6 python-osc

IMPORTANT: OSC must be enabled in VRChat!
(Action Menu -> Options -> OSC -> Enabled)
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from pathlib import Path

# make sure the project root is importable no matter where we're
# started from (start.sh, .desktop file, terminal, the .exe, ...)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import osinfo  # noqa: E402
from core.osinfo import IS_LINUX, IS_WINDOWS  # noqa: E402

# Windows only: bring an existing ~/.config/OSC-DreamChatbox over to
# %APPDATA% once. Runs BEFORE core.constants is used for anything, so
# the rest of the app only ever sees the final location.
_MIGRATION = osinfo.migrate_config_dir()

from core.constants import APP_NAME  # noqa: E402
from core import pyextras  # noqa: E402

# our own extras folder goes on sys.path before anything optional is
# imported - see core/pyextras.py for why it exists
pyextras.activate()


def _set_process_name(name=APP_NAME):
    """Makes the process show up as 'OSC-DreamChatbox' instead of
    'python' in htop/btop/KDE system monitor.
    1) setproctitle rewrites the full command line (cmdline view)
    2) prctl(PR_SET_NAME) sets the kernel comm name (max 15 chars),
       which top/btop and KDE use in the process column.
    On Windows the .exe already carries the right name, and there is no
    libc/prctl - so only the harmless setproctitle call is attempted."""
    try:
        from setproctitle import setproctitle
        setproctitle(name)
    except Exception:
        pass
    if not IS_LINUX:
        return
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(15, name.encode()[:15], 0, 0, 0)  # 15 = PR_SET_NAME
    except Exception:
        pass


def _set_windows_app_id(app_id="yakuda-stack.OSC-DreamChatbox"):
    """Windows taskbar grouping + icon: without an explicit AppUserModelID
    a pythonw/PyInstaller process inherits the host's, and the taskbar
    shows the generic python icon instead of ours. No-op elsewhere."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def main():
    _set_process_name()
    _set_windows_app_id()
    from PyQt6.QtGui import QFont, QIcon
    from PyQt6.QtWidgets import QApplication
    from ui.mainwindow import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # lets Wayland/KDE match the window to the .desktop entry, so the
    # taskbar shows OUR icon instead of the generic Wayland "W".
    # Only register the name if the .desktop file actually exists –
    # otherwise KDE's portal logs "App info not found for
    # 'osc-dreamchatbox'" on every start. Linux/freedesktop only.
    if IS_LINUX:
        import os
        data_dirs = [Path.home() / ".local" / "share"]
        data_dirs += [Path(d) for d in os.environ.get(
            "XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if d]
        if any((d / "applications" / "osc-dreamchatbox.desktop").exists()
               for d in data_dirs):
            app.setDesktopFileName("osc-dreamchatbox")
    # icon lives in assets/; osinfo knows where that is when frozen
    icon_path = osinfo.resource("assets", "icon.png")
    if not icon_path.exists():
        icon_path = osinfo.resource("icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setFont(QFont("Sans", 10))
    win = MainWindow()
    if icon_path.exists():
        win.setWindowIcon(QIcon(str(icon_path)))
    # log what we ended up on + whether a config was moved, so a bug
    # report from a .exe user says which platform/backends were active
    try:
        win.log(f"Platform: {osinfo.describe()}")
        if _MIGRATION[1]:
            win.log(_MIGRATION[1])
    except Exception:
        pass
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
