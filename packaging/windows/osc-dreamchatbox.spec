# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the OSC-DreamChatbox Windows build.

Run it from the PROJECT ROOT (the folder with osc_dreamchatbox.py):

    pyinstaller packaging/windows/osc-dreamchatbox.spec

or, more comfortably, use packaging/windows/build-exe.ps1 which sets the
switches below for you.

Two environment variables change the output:

    DCB_CONSOLE=1   keep the black console window (DEFAULT while the
                    Windows port is young - it is where the traceback
                    shows up if something goes wrong)
    DCB_CONSOLE=0   windowed build, no console (what a release ships)

    DCB_ONEFILE=0   one FOLDER in dist/OSC-DreamChatbox (DEFAULT).
                    Starts fast, easy to inspect, easy to zip.
    DCB_ONEFILE=1   a single dist/OSC-DreamChatbox.exe. Nicer to hand
                    out, but unpacks itself to %TEMP% on every start.

Linux is untouched by this file: it is never read by the AppImage or
AUR build.
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------- paths
# SPECPATH is set by PyInstaller = the folder holding this .spec file
PROJECT_ROOT = Path(SPECPATH).resolve().parent.parent  # noqa: F821
ENTRY = PROJECT_ROOT / "osc_dreamchatbox.py"
if not ENTRY.exists():
    raise SystemExit(
        f"osc_dreamchatbox.py not found next to the spec ({ENTRY}). "
        "Run pyinstaller from the project root.")

sys.path.insert(0, str(PROJECT_ROOT))


def _flag(name, default):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


CONSOLE = _flag("DCB_CONSOLE", "1")
ONEFILE = _flag("DCB_ONEFILE", "0")

# read the version straight out of core/constants.py so the exe metadata
# can never drift from the app (single source of truth stays VERSION)
VERSION = "0.0.0"
for _line in (PROJECT_ROOT / "core" / "constants.py").read_text(
        encoding="utf-8").splitlines():
    if _line.startswith("VERSION"):
        VERSION = _line.split('"')[1].lstrip("v")
        break


# ----------------------------------------------------------------- icon
def _icon_path():
    """Windows wants an .ico. Use one if it is there, otherwise let
    PyInstaller convert the PNG (that needs Pillow installed)."""
    ico = PROJECT_ROOT / "assets" / "icon.ico"
    if ico.exists():
        return str(ico)
    png = PROJECT_ROOT / "assets" / "icon.png"
    if png.exists():
        try:
            import PIL  # noqa: F401
            return str(png)
        except ImportError:
            print("[spec] Pillow not installed and assets/icon.ico missing "
                  "-> building without an icon")
    return None


# ---------------------------------------------------------------- datas
# read-only files the app looks for via core.osinfo.resource_root(),
# which resolves to the unpacked bundle when frozen
datas = [
    (str(PROJECT_ROOT / "assets"), "assets"),
    (str(PROJECT_ROOT / "config"), "config"),
]
# the elevated temperature helper must ship WITH the app; it is copied
# out to CONFIG_DIR at runtime (see core/backends/wintemp.deploy_helper)
_helper = PROJECT_ROOT / "packaging" / "windows" / "dreamtemp-helper.ps1"
if _helper.exists():
    datas.append((str(_helper), "packaging/windows"))
else:
    print("[spec] WARNING: dreamtemp-helper.ps1 missing - the temperature "
          "button will not work in this build")

for _doc in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    _p = PROJECT_ROOT / _doc
    if _p.exists():
        datas.append((str(_p), "."))

# ------------------------------------------------------- hidden imports
# things PyInstaller's static analysis cannot see: python-osc is imported
# inside a function, zeroconf pulls its platform bits in dynamically
hiddenimports = [
    "pythonosc",
    "pythonosc.udp_client",
    "pythonosc.osc_message_builder",
    "zeroconf",
    "zeroconf._utils.ipaddress",
    "zeroconf._handlers.answers",
    # our own dispatch targets - imported through core/osinfo.py branches
    "core.osinfo",
    "core.backends",
    "core.backends.hardware_null",
    "core.backends.media_null",
    "core.backends.hardware_windows",
    "core.backends.wintemp",
    "core.backends.media_windows",
    # ctypes/winreg/mmap back the Windows hardware sources; winreg in
    # particular is easy for the analysis to miss behind a local import
    "winreg",
    "mmap",
    "ctypes.wintypes",
]

# optional extras: only bundled when they are actually installed, so a
# minimal build does not fail on a missing package
binaries = []
# "winrt" is the PyWinRT namespace package behind the GSMTC media
# backend; it ships compiled extension modules that the static analysis
# cannot follow, so it has to be collected wholesale. "winsdk" is the
# legacy binding for Python <= 3.12 - whichever is installed gets bundled.
import importlib.util

for _opt in ("speech_recognition", "deepl", "winrt", "winsdk"):
    # collect_all() happily returns empty lists for a package that is not
    # there, so it would report success for everything. Ask the import
    # system first, otherwise the build log lies about what went in.
    if importlib.util.find_spec(_opt) is None:
        print(f"[spec] optional package not installed, skipping: {_opt}")
        continue
    try:
        from PyInstaller.utils.hooks import collect_all
        _d, _b, _h = collect_all(_opt)
        datas += _d
        binaries += _b
        hiddenimports += _h
        print(f"[spec] bundling optional package: {_opt} "
              f"({len(_d)} data, {len(_b)} binaries)")
    except Exception as _err:
        print(f"[spec] could not bundle {_opt}: {_err}")

# ------------------------------------------------------------- excludes
excludes = [
    # the Linux-only backends: never imported when IS_WINDOWS is True,
    # and media_linux would drag in PyQt6.QtDBus which Windows Qt has no
    # module for. Leaving them out keeps the build log clean.
    "core.backends.hardware_linux",
    "core.backends.media_linux",
    "PyQt6.QtDBus",
    # Qt modules the app never touches - shaves ~100 MB off the bundle
    "PyQt6.Qt3DCore", "PyQt6.Qt3DRender", "PyQt6.Qt3DInput",
    "PyQt6.Qt3DLogic", "PyQt6.Qt3DAnimation", "PyQt6.Qt3DExtras",
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineQuick", "PyQt6.QtQuick3D", "PyQt6.QtCharts",
    "PyQt6.QtDataVisualization", "PyQt6.QtBluetooth", "PyQt6.QtNfc",
    "PyQt6.QtPositioning", "PyQt6.QtSerialPort", "PyQt6.QtSql",
    "PyQt6.QtTest", "PyQt6.QtDesigner", "PyQt6.QtHelp",
    # stdlib/3rd-party we do not use
    "tkinter", "matplotlib", "numpy", "scipy", "pandas", "PIL.ImageQt",
    "PySide6", "PyQt5", "unittest", "pydoc_data",
]

a = Analysis(          # noqa: F821
    [str(ENTRY)],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
# PyInstaller 6.x: PYZ takes only a.pure (no zipped_data, no cipher)
pyz = PYZ(a.pure)      # noqa: F821

_common = dict(
    name="OSC-DreamChatbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX + Qt DLLs = false antivirus hits
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_path(),
)

if ONEFILE:
    exe = EXE(             # noqa: F821
        pyz, a.scripts, a.binaries, a.datas, [],
        exclude_binaries=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        **_common,
    )
else:
    exe = EXE(             # noqa: F821
        pyz, a.scripts, [],
        exclude_binaries=True,
        **_common,
    )
    coll = COLLECT(        # noqa: F821
        exe, a.binaries, a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="OSC-DreamChatbox",
    )

print(f"[spec] OSC-DreamChatbox {VERSION} | "
      f"{'one-file' if ONEFILE else 'one-folder'} | "
      f"console={'on' if CONSOLE else 'off'}")
