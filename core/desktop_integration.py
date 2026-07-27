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
_DATA_HOME = Path(
    os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
APPLICATIONS_DIR = _DATA_HOME / "applications"
SYSTEM_APP_DIRS = ("/usr/share/applications", "/usr/local/share/applications")

# KDE/Wayland taskbars resolve the window icon via the .desktop Icon= key,
# and that works reliably only with an icon-THEME NAME (not an absolute
# path). So we install the PNG into the hicolor theme exactly like the AUR
# package does and reference it by name.
ICON_NAME = "osc-dreamchatbox"
ICON_DIR = _DATA_HOME / "icons" / "hicolor" / "256x256" / "apps"

_ASSETS_DIR = PROJECT_DIR / "assets"
_BIN_LAUNCHER = Path.home() / ".local" / "bin" / "osc-dreamchatbox"


def _store_file() -> Path:
    return DESKTOP_STORE_DIR / DESKTOP_BASENAME


def _link_file() -> Path:
    return APPLICATIONS_DIR / DESKTOP_BASENAME


def _icon_file() -> Path:
    return ICON_DIR / f"{ICON_NAME}.png"


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


def _source_icon_png() -> Path | None:
    """The bundled PNG we copy into the hicolor theme."""
    for candidate in (_ASSETS_DIR / "icon.png", PROJECT_DIR / "icon.png"):
        if candidate.exists():
            return candidate
    return None


def _install_icon() -> bool:
    """Copy the bundled PNG into the user's hicolor icon theme so the
    .desktop can reference it by name. Returns True if the icon is in place."""
    src = _source_icon_png()
    if src is None:
        return _icon_file().exists()
    try:
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, _icon_file())
        return True
    except OSError:
        return _icon_file().exists()


def _desktop_text(exec_cmd: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=OSC DreamChatbox\n"
        "GenericName=VRChat OSC Chatbox Companion\n"
        "Comment=VRChat OSC chatbox companion for Linux\n"
        f"Exec={exec_cmd}\n"
        f"Icon={ICON_NAME}\n"           # theme name, not an absolute path
        "Terminal=false\n"
        "Categories=Utility;Network;Chat;\n"
        "Keywords=VRChat;OSC;Chatbox;VR;\n"
        "StartupNotify=true\n"
        f"StartupWMClass={WM_CLASS}\n"
    )


def system_entry_present() -> bool:
    """True if an AUR / system package already shipped the .desktop."""
    return any((Path(d) / DESKTOP_BASENAME).exists() for d in SYSTEM_APP_DIRS)


def _entry_is_current() -> bool:
    """True only if the user-local entry is already exactly what we want:
    a symlink pointing at our store, whose .desktop references the themed
    icon by name, with the hicolor icon actually installed. Anything else
    (a real-file entry, a symlink elsewhere, an absolute Icon= path, or a
    missing icon) counts as an OLD entry that should be replaced."""
    link = _link_file()
    store = _store_file()
    if not link.is_symlink():
        return False
    try:
        if link.resolve() != store.resolve():
            return False
    except OSError:
        return False
    if not _icon_file().exists():
        return False
    try:
        return f"Icon={ICON_NAME}\n" in store.read_text(encoding="utf-8")
    except OSError:
        return False


def _remove_old_entry() -> bool:
    """Delete any existing user-local osc-dreamchatbox entry (symlink OR a
    real .desktop file) plus a stale store file. Returns True if something
    was actually removed."""
    removed = False
    for path in (_link_file(), _store_file()):
        if path.is_symlink() or path.exists():
            try:
                path.unlink()
                removed = True
            except OSError:
                pass
    return removed


def is_installed() -> bool:
    """True if a complete, correct entry already exists so the button can
    say 'nothing to do'. A system (AUR) entry counts on its own; a
    user-local entry only counts when it is fully current (see
    _entry_is_current). Otherwise the fix will replace the old entry."""
    return system_entry_present() or _entry_is_current()


def install_desktop_entry() -> tuple[bool, str]:
    """Delete any old user-local osc-dreamchatbox entry and create a fresh
    one: copy the icon into the hicolor theme, write the canonical .desktop
    referencing it by name, and symlink it into applications/. Safe to run
    repeatedly.

    Returns (changed, message)."""
    if system_entry_present():
        return False, ("A system package (AUR) already provides the desktop "
                       "entry \u2013 nothing to do.")

    # find and remove any old entry (symlink or real file) before adding new
    removed_old = _remove_old_entry()

    icon_ok = _install_icon()
    exec_cmd = _resolve_exec()

    DESKTOP_STORE_DIR.mkdir(parents=True, exist_ok=True)
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    store = _store_file()
    store.write_text(_desktop_text(exec_cmd), encoding="utf-8")
    store.chmod(0o755)

    link = _link_file()
    link.symlink_to(store)

    _refresh_desktop_database()
    _refresh_icon_cache()

    de = detect_desktop_environment()
    head = ("Replaced the old desktop entry with a fresh one"
            if removed_old else "Desktop entry installed")
    icon_note = ("" if icon_ok else
                 "\n\nNote: bundled icon.png was not found, so the taskbar "
                 "may still show a generic icon.")
    return True, (f"{head} for '{de}':\n"
                  f"{store}\n\u2192 {link}\n"
                  f"Icon: {_icon_file()}\n\n"
                  "Fully restart the app (and on KDE/Wayland log out and back "
                  "in once) for the taskbar icon to refresh." + icon_note)


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


def _refresh_icon_cache() -> None:
    tool = shutil.which("gtk-update-icon-cache")
    if not tool:
        return
    theme_root = _DATA_HOME / "icons" / "hicolor"
    try:
        subprocess.run(
            [tool, "-f", "-t", str(theme_root)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
