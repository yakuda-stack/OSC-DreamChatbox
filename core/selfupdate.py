"""
core/selfupdate.py – in-app update for the Windows installer (v1.6.6)

The update check (Options -> General -> Check for updates) already
knows when a newer release is out. On Windows this module does the
rest: find the "...-setup.exe" in the release assets, download it to
%TEMP% and start it. The app then closes so the installer can replace
its files.

Linux is not touched: AUR and AppImage update their own way.

No Qt in here - the download runs in a worker thread and reports its
progress through a plain callback, so it stays testable.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import re
import subprocess
import sys
import tempfile
import urllib.request

#: matches the Inno Setup output name (packaging/windows/installer.iss:
#: OutputBaseFilename=OSC-DreamChatbox-{#AppVersion}-setup)
SETUP_RE = re.compile(r"^OSC-DreamChatbox-.*-setup\.exe$", re.IGNORECASE)

_UA = {"User-Agent": "OSC-DreamChatbox"}
_CHUNK = 64 * 1024


class UpdateCancelled(Exception):
    pass


def find_setup_asset(release: dict):
    """The installer asset of a GitHub release JSON as
    (name, download_url, size), or None if the release has none."""
    for a in (release or {}).get("assets") or []:
        name = a.get("name") or ""
        url = a.get("browser_download_url") or ""
        if SETUP_RE.match(name) and url.startswith("https://"):
            return (name, url, int(a.get("size") or 0))
    return None


def is_installed_windows_build() -> bool:
    """True only for the frozen Windows build. Running from source on
    Windows has no installer to replace, so the button stays away."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def download_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "OSC-DreamChatbox-update")
    os.makedirs(d, exist_ok=True)
    return d


def download(url: str, name: str, size: int = 0,
             progress=lambda done, total: None,
             cancelled=lambda: False, timeout: int = 20) -> str:
    """Downloads the installer and returns its path. Writes to a .part
    file first, so a broken download never looks like a finished one.
    Raises on any error (the caller shows it)."""
    if not SETUP_RE.match(name or ""):
        raise ValueError(f"not an installer: {name!r}")
    dest = os.path.join(download_dir(), os.path.basename(name))
    part = dest + ".part"
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length") or size or 0)
        done = 0
        with open(part, "wb") as f:
            while True:
                if cancelled():
                    raise UpdateCancelled()
                chunk = r.read(_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                progress(done, total)
    if total and done != total:
        raise IOError(f"download incomplete ({done} of {total} bytes)")
    if done < 1024 * 1024:
        # the real setup is ~100 MB - a few KB is an error page
        raise IOError(f"download too small ({done} bytes)")
    os.replace(part, dest)
    return dest


def launch_setup(path: str) -> None:
    """Starts the installer detached from this process, so it keeps
    running after the app has closed. /CLOSEAPPLICATIONS lets Inno
    Setup close anything still holding the files."""
    if sys.platform != "win32":
        raise RuntimeError("the installer only runs on Windows")
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    subprocess.Popen([path, "/CLOSEAPPLICATIONS"], close_fds=True,
                     creationflags=flags)
