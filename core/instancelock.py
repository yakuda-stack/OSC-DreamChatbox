"""
core/instancelock.py - "is the app already running?", done properly.

Two copies of the app - window and terminal mode, or two terminals -
would both write into the same chatbox. So each copy holds a lock on
``instance.lock`` in the config folder while it runs.

Why a lock and not a look at the process list (the first version):
* A process name is not an identity. The AppImage runtime has the same
  first 15 characters ("OSC-DreamChatbo") as the app itself.
* A process that is shutting down still counts. When the window hands
  over to terminal mode, the window has finished everything that
  matters (config saved, chatbox cleared, plugins stopped) long before
  the python process is actually gone - a plugin thread can hold the
  interpreter open for a good while. The window releases the lock the
  moment its own tidying up is done, so the terminal can start right
  away instead of waiting for the process to disappear.
* The operating system drops the lock by itself when the process dies,
  even after a crash or a kill -9. A stale lock cannot exist.

POSIX record locks (fcntl.lockf) on purpose, not flock(): they belong
to the process and are NOT inherited by a fork(), so nothing a plugin
starts can keep the app "running" after it closed.

The file also says who holds it ("window 12345"), for the message the
other copy shows. That is information only - the lock is what counts.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import sys
import time

from core.constants import CONFIG_DIR

LOCK_FILE = CONFIG_DIR / "instance.lock"
IS_WINDOWS = sys.platform.startswith("win")

#: the file descriptor while we hold the lock
_fd = None


def _try_lock(fd):
    """True if we got the lock on byte 0 of ``fd``."""
    if IS_WINDOWS:
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    import fcntl
    fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
    return True


def acquire(mode):
    """Takes the lock for this process. ``mode`` is "window" or
    "terminal" and only ends up in the message the other copy shows.
    Returns True when we hold it (also when locking is not possible on
    this system at all - then there is simply no check)."""
    global _fd
    if _fd is not None:
        return True
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return True
    try:
        _try_lock(fd)
    except OSError:
        os.close(fd)            # someone else holds it
        return False
    except Exception:           # noqa: BLE001 - no locking here at all
        os.close(fd)
        return True
    _fd = fd
    try:
        # after byte 0 - on Windows the locked byte cannot be read by the
        # other copy, and the note has to be readable
        info = f" {mode} {os.getpid()}\n".encode()
        os.lseek(fd, 1, os.SEEK_SET)
        os.write(fd, info)
        os.ftruncate(fd, 1 + len(info))
    except OSError:
        pass
    return True


def release():
    """Gives the lock up early (the window does this after its closeEvent,
    see module doc). Exiting releases it as well."""
    global _fd
    if _fd is None:
        return
    fd, _fd = _fd, None
    try:
        os.close(fd)            # closing drops the lock
    except OSError:
        pass


def holder():
    """(mode, pid) of the copy that holds the lock, as far as its note
    says - or ("", None). Never call this while holding the lock
    yourself: with POSIX locks, closing ANY descriptor of the file drops
    the lock of the whole process."""
    if _fd is not None:
        return "", None
    try:
        text = LOCK_FILE.read_bytes()[1:].decode("ascii", "replace").split()
    except OSError:
        return "", None
    if len(text) >= 2 and text[1].isdigit():
        return text[0], int(text[1])
    return "", None


def describe_holder():
    """'the window (PID 123)' - for messages."""
    mode, pid = holder()
    what = {"window": "the window", "terminal": "terminal mode"}.get(
        mode, "another copy")
    return f"{what} (PID {pid})" if pid else what


def wait_and_acquire(mode, timeout):
    """Keeps trying for ``timeout`` seconds. True once we hold it."""
    end = time.monotonic() + timeout
    while True:
        if acquire(mode):
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)
