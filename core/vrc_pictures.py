"""
core/vrc_pictures.py – "VRC Picture Folder Fix"

Under Proton, VRChat saves camera photos into the Steam prefix, e.g.
    ~/.local/share/Steam/steamapps/compatdata/438100/pfx/drive_c/users/
        steamuser/Pictures/VRChat/
which is awkward to reach from a normal Linux file manager.

This fix replaces that in-prefix VRChat folder with a symlink pointing at
the real Linux Pictures directory (~/Pictures/VRChat, or whatever
XDG_PICTURES_DIR is set to). VRChat keeps writing to the same path inside
the prefix, but the photos now land directly in the Linux Pictures folder.

Steam root / library detection mirrors core/vrchatlog.py so both features
agree on where VRChat lives (native, common variants, Flatpak, and extra
library folders from libraryfolders.vdf).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.vrchatlog import VRCHAT_APPID, _STEAM_ROOTS

# folder inside a Steam prefix where VRChat drops camera photos
_PREFIX_PICTURES_TAIL = Path(
    "pfx/drive_c/users/steamuser/Pictures/VRChat")


def linux_pictures_dir() -> Path:
    """Real Linux target folder for the photos: <XDG_PICTURES_DIR>/VRChat,
    falling back to ~/Pictures/VRChat."""
    base = Path.home() / "Pictures"
    cfg = Path.home() / ".config" / "user-dirs.dirs"
    try:
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r'\s*XDG_PICTURES_DIR\s*=\s*"([^"]+)"', line)
            if m:
                val = m.group(1).replace("$HOME", str(Path.home()))
                base = Path(val).expanduser()
                break
    except Exception:
        pass
    return base / "VRChat"


def _library_roots():
    """Extra Steam library folders from libraryfolders.vdf (VRChat may live
    on another drive). Same parse as vrchatlog.py."""
    roots = []
    for base in _STEAM_ROOTS:
        vdf = base / "steamapps" / "libraryfolders.vdf"
        try:
            txt = vdf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r'"path"\s*"([^"]+)"', txt):
            roots.append(Path(m.group(1).replace("\\\\", "/")))
    return roots


def _candidate_picture_dirs():
    """All possible in-prefix VRChat picture folders, de-duplicated."""
    seen, out = set(), []
    for base in _STEAM_ROOTS + _library_roots():
        p = (base / "steamapps" / "compatdata" / VRCHAT_APPID
             / _PREFIX_PICTURES_TAIL)
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def find_prefix_pictures_dir():
    """The in-prefix VRChat picture folder to operate on, or None.

    Prefers a path that already exists; otherwise the first path whose
    Proton prefix exists (VRChat launched at least once), so the symlink
    can be created even before the VRChat/ subfolder does."""
    candidates = _candidate_picture_dirs()
    for p in candidates:
        if p.is_symlink() or p.is_dir():
            return p
    for p in candidates:
        # .../steamuser/Pictures  -> parent; its parent chain proves the
        # prefix exists even if the VRChat subfolder was never created
        if p.parent.exists() or p.parent.parent.exists():
            return p
    return None


def is_fixed() -> bool:
    """True if the in-prefix folder is already a symlink to the Linux
    Pictures target."""
    prefix = find_prefix_pictures_dir()
    if prefix is None or not prefix.is_symlink():
        return False
    try:
        return prefix.resolve() == linux_pictures_dir().resolve()
    except OSError:
        return False


def install_picture_fix() -> tuple[bool, str]:
    """Point the in-prefix VRChat folder at the Linux Pictures folder via a
    symlink, migrating any photos that are already in the prefix.

    Returns (changed, message)."""
    prefix = find_prefix_pictures_dir()
    if prefix is None:
        return False, ("VRChat's Proton prefix was not found. Install and "
                       "launch VRChat once via Steam/Proton, then try again.")

    target = linux_pictures_dir()
    target.mkdir(parents=True, exist_ok=True)

    # already a symlink?
    if prefix.is_symlink():
        try:
            same = prefix.resolve() == target.resolve()
        except OSError:
            same = False
        if same:
            return False, (f"Already fixed \u2013 the folder is a symlink to:\n"
                           f"{target}")
        prefix.unlink()  # repoint a wrong symlink

    # real directory with (possibly) existing photos -> migrate then replace
    elif prefix.is_dir():
        moved, skipped = 0, 0
        for item in list(prefix.iterdir()):
            dest = target / item.name
            if dest.exists():
                skipped += 1
                continue
            try:
                shutil.move(str(item), str(dest))
                moved += 1
            except OSError:
                skipped += 1
        try:
            prefix.rmdir()  # only succeeds if now empty
        except OSError:
            return False, (
                f"Moved {moved} file(s) to {target}, but the prefix folder "
                f"still has {skipped} item(s) with name clashes and could not "
                f"be replaced. Resolve those manually, then run the fix again.")

    # create the symlink (prefix path -> real Linux folder)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    try:
        prefix.symlink_to(target)
    except OSError as e:
        return False, f"Could not create the symlink:\n{e}"

    return True, (f"Done. VRChat camera photos now land in:\n{target}\n\n"
                  f"Linked from the prefix folder:\n{prefix}")
