#!/usr/bin/env python3
"""
OSC-DreamChatbox v1.0.0-alpha
A simple, clean VRChat OSC chatbox sender for Linux.

Entry point only – the actual code lives in:
    core/     logic (media, hardware, speech-to-text, helpers)
    ui/       PyQt6 user interface

Requires: PyQt6, python-osc
    pip install PyQt6 python-osc

IMPORTANT: OSC must be enabled in VRChat!
(Action Menu -> Options -> OSC -> Enabled)
"""

import sys
from pathlib import Path

# make sure the project root is importable no matter where we're
# started from (start.sh, .desktop file, terminal, ...)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.constants import APP_NAME  # noqa: E402


def main():
    from PyQt6.QtGui import QFont, QIcon
    from PyQt6.QtWidgets import QApplication
    from ui.mainwindow import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # lets Wayland/KDE match the window to the .desktop entry, so the
    # taskbar shows OUR icon instead of the generic Wayland "W"
    app.setDesktopFileName("osc-dreamchatbox")
    root = Path(__file__).resolve().parent
    # icon lives in assets/ (fallback: project root for old checkouts)
    icon_path = root / "assets" / "icon.png"
    if not icon_path.exists():
        icon_path = root / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setFont(QFont("Sans", 10))
    win = MainWindow()
    if icon_path.exists():
        win.setWindowIcon(QIcon(str(icon_path)))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
