"""
core/startlog.py - what happened during the last start, in a file.

Started from the menu or the desktop icon there is no terminal: when the
app dies before its window is up, the user sees the icon bounce for a few
seconds and then nothing at all. Every error message went to a stderr
nobody reads. So the window mode writes ``last-start.log`` in the config
folder:

* a header (version, platform, Python, Qt platform from the environment)
* Python tracebacks (sys.excepthook)
* hard crashes - SIGSEGV / SIGABRT from Qt, the GPU driver or a C module -
  through faulthandler, which still works when Python itself can't
* on Linux, when stderr is not a terminal: everything printed to stderr,
  including Qt's own "could not load the Qt platform plugin" lines

The file is rewritten on every start, so it is always about the last one
and never grows. ``fail()`` additionally tries to tell the user (dialog,
else notify-send) where the file is.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import faulthandler
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback

from core.constants import APP_NAME, CONFIG_DIR, VERSION

LOG_FILE = CONFIG_DIR / "last-start.log"

#: the open log file while the app runs (faulthandler needs it open)
_fh = None


def install() -> None:
    """Start the log. Never raises - a log must not be a new way to fail."""
    global _fh
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _fh = open(LOG_FILE, "w", encoding="utf-8", buffering=1)
        env = {k: os.environ.get(k, "") for k in
               ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "QT_QPA_PLATFORM", "APPIMAGE")}
        _fh.write(f"{APP_NAME} {VERSION} - start {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                  f"Platform: {platform.platform()} · Python {platform.python_version()}\n"
                  + "".join(f"{k}={v}\n" for k, v in env.items() if v) + "\n")
        faulthandler.enable(file=_fh, all_threads=True)
        if sys.platform.startswith("linux") and not _is_tty(2):
            # Qt / C libraries write straight to fd 2 - catch that too
            os.dup2(_fh.fileno(), 2)
        old_hook = sys.excepthook

        def hook(kind, value, tb):
            write("Uncaught exception:\n" + "".join(traceback.format_exception(kind, value, tb)))
            old_hook(kind, value, tb)
        sys.excepthook = hook
    except Exception:  # noqa: BLE001
        _fh = None


def _is_tty(fd: int) -> bool:
    try:
        return os.isatty(fd)
    except OSError:
        return False


def write(text: str) -> None:
    if _fh is None:
        return
    try:
        _fh.write(text if text.endswith("\n") else text + "\n")
        _fh.flush()
    except Exception:  # noqa: BLE001
        pass


def started() -> None:
    """The window is up - noted, so a log ending here means 'started fine'."""
    write(f"Window shown after start ({time.strftime('%H:%M:%S')}).")


def fail(exc: BaseException) -> None:
    """The start failed: traceback into the log, then tell the user."""
    write("Start failed:\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    text = (f"{APP_NAME} could not start:\n\n{type(exc).__name__}: {exc}\n\n"
            f"Details are in:\n{LOG_FILE}\n\n"
            "Please send this file in the Discord or on GitHub.")
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(None, APP_NAME, text)
            return
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", "-a", APP_NAME, f"{APP_NAME} could not start",
                            f"Details: {LOG_FILE}"], timeout=5)
        except Exception:  # noqa: BLE001
            pass
