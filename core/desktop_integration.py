"""
core/desktop_integration.py – desktop entry / app-tray integration

Install-script users (curl | bash) don't get the .desktop file the AUR
package ships in /usr/share/applications, so the app shows up with the
generic Wayland "W" icon in the taskbar/tray and is missing from the
application menu.

This module writes the canonical .desktop into
    ~/.config/OSC-DreamChatbox/desktop/osc-dreamchatbox.desktop
and symlinks it into
    ~/.local/share/applications/osc-dreamchatbox.desktop
which every freedesktop-compliant DE (KDE, GNOME, XFCE, LXQt, Cinnamon,
MATE, Budgie, …) reads the same way – so there is no real per-DE special
casing needed, only detection for logging/UX.

The basename MUST stay 'osc-dreamchatbox' to match both the AUR package
and app.setDesktopFileName("osc-dreamchatbox") in osc_dreamchatbox.py –
otherwise the Wayland app_id / icon match breaks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from core.constants import CONFIG_DIR, PROJECT_DIR

# must equal the AUR .desktop basename AND setDesktopFileName()
DESKTOP_BASENAME = "osc-dreamchatbox.desktop"
WM_CLASS = "osc-dreamchatbox"

# canonical store (what the user asked for) + the dir the DEs actually scan
DESKTOP_STORE_DIR = CONFIG_DIR / "desktop"
APPLICATIONS_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    / "applications"
)
SYSTEM_APP_DIRS = ("/usr/share/applications", "/usr/local/share/applications")

_ASSETS_DIR = PROJECT_DIR / "assets"
_BIN_LAUNCHER = Path.home() / ".local" / "bin" / "osc-dreamchatbox"


def _store_file() -> Path:
    return DESKTOP_STORE_DIR / DESKTOP_BASENAME


def _link_file() -> Path:
    return APPLICATIONS_DIR / DESKTOP_BASENAME


def detect_desktop_environment() -> str:
    """Best-effort DE name (lowercase), e.g. 'kde', 'gnome', 'xfce'."""
    for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        value = os.environ.get(var, "").strip()
        if value:
            return value.split(":")[0].lower()
    return "unknown"


def _resolve_exec() -> str:
    """Command for Exec=. Prefer the launcher install.sh creates, then any
    osc-dreamchatbox on PATH, else re-run this interpreter on the entry point."""
    if _BIN_LAUNCHER.exists():
        return str(_BIN_LAUNCHER)
    on_path = shutil.which("osc-dreamchatbox")
    if on_path:
        return on_path
    entry = PROJECT_DIR / "osc_dreamchatbox.py"
    return f"{sys.executable} {entry}"


def _resolve_icon() -> str:
    for name in ("icon.png",):
        candidate = _ASSETS_DIR / name
        if candidate.exists():
            return str(candidate)
    legacy = PROJECT_DIR / "icon.png"
    if legacy.exists():
        return str(legacy)
    return WM_CLASS  # fall back to icon-theme lookup by name


def _desktop_text(exec_cmd: str, icon: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=OSC DreamChatbox\n"
        "GenericName=VRChat OSC Chatbox Companion\n"
        "Comment=VRChat OSC chatbox companion for Linux\n"
        f"Exec={exec_cmd}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Utility;Network;Chat;\n"
        "Keywords=VRChat;OSC;Chatbox;VR;\n"
        "StartupNotify=true\n"
        f"StartupWMClass={WM_CLASS}\n"
    )


def system_entry_present() -> bool:
    """True if an AUR / system package already shipped the .desktop."""
    return any((Path(d) / DESKTOP_BASENAME).exists() for d in SYSTEM_APP_DIRS)


def is_installed() -> bool:
    """True if a usable desktop entry already exists – symlink OR real file,
    in the user applications dir OR a system dir. This is the check the
    Settings button uses so it does nothing when an entry is already there."""
    link = _link_file()
    # .exists() follows symlinks; also treat a broken symlink as "present"
    # so we don't silently leave a dangling link in place.
    if link.exists() or link.is_symlink():
        return True
    return system_entry_present()


def install_desktop_entry() -> tuple[bool, str]:
    """Create the canonical .desktop and symlink it into applications/.

    Returns (changed, message). changed=False means nothing was written
    (an entry already existed)."""
    if system_entry_present():
        return False, ("A system package (AUR) already provides the desktop "
                       "entry – nothing to do.")

    link = _link_file()
    if link.exists() or link.is_symlink():
        return False, (f"A desktop entry already exists:\n{link}\n"
                       "Nothing to do.")

    exec_cmd = _resolve_exec()
    icon = _resolve_icon()

    DESKTOP_STORE_DIR.mkdir(parents=True, exist_ok=True)
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    store = _store_file()
    store.write_text(_desktop_text(exec_cmd, icon), encoding="utf-8")
    store.chmod(0o755)

    link.symlink_to(store)
    _refresh_desktop_database()

    de = detect_desktop_environment()
    return True, (f"Desktop entry created for '{de}':\n"
                  f"{store}\n\u2192 {link}\n\n"
                  "Restart the app (and re-login on some desktops) for the "
                  "taskbar/tray icon to refresh.")


def _refresh_desktop_database() -> None:
    tool = shutil.which("update-desktop-database")
    if not tool:
        return
    try:
        subprocess.run(
            [tool, str(APPLICATIONS_DIR)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
