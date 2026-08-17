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
    "core.backends.mic_sounddevice",
    # the microphone helper. A frozen build re-runs itself with
    # --stt-helper instead of spawning python (see core/mic_host.py), so
    # this module has to be INSIDE the exe - and it is only imported at
    # the top of main(), behind an argv check the analysis cannot follow.
    "core.mic_host",
    "core.stt_child",
    # sounddevice talks to PortAudio through CFFI
    "_cffi_backend",
    # ctypes/winreg/mmap back the Windows hardware sources; winreg in
    # particular is easy for the analysis to miss behind a local import
    "winreg",
    "mmap",
    "ctypes.wintypes",
]

# optional extras: only bundled when they are actually installed, so a
# minimal build does not fail on a missing package
binaries = []

# ------------------------------------------------ MSVC runtime (Windows)
# The classic "the code execution cannot proceed because VCRUNTIME140.dll
# was not found" dialog. Two different runtimes are involved:
#
#   VCRUNTIME140.dll / VCRUNTIME140_1.dll   the C runtime - CPython itself
#                                           needs it, and python.org ships
#                                           a copy next to python.exe
#   MSVCP140.dll (+ _1/_2, CONCRT140)       the C++ runtime - Qt6 needs it,
#                                           and it usually only exists in
#                                           System32 because some installer
#                                           put the VC++ redistributable
#                                           there
#
# PyInstaller follows binary dependencies, but it deliberately does not
# collect DLLs it considers part of the operating system - which is exactly
# where MSVCP140.dll normally lives. On the build machine everything works
# (the redistributable is installed); on a fresh Windows box the app dies
# at startup with that dialog.
#
# Copying these next to the app is app-local deployment, which Microsoft
# documents and permits for the VC++ redistributable files.
#
# Anything found here is REPORTED, so the build log tells you what you are
# actually shipping instead of leaving you to find out from a bug report.
def _msvc_runtime():
    if os.name != "nt":
        return []
    wanted = ["VCRUNTIME140.dll", "VCRUNTIME140_1.dll",
              "MSVCP140.dll", "MSVCP140_1.dll", "MSVCP140_2.dll",
              "CONCRT140.dll"]
    # python.org puts its own copy next to python.exe; System32 holds the
    # system-wide redistributable. Prefer the python one: it is guaranteed
    # to match the interpreter we are freezing.
    search = [Path(sys.executable).parent,
              Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"]
    found, missing = [], []
    for dll in wanted:
        for folder in search:
            candidate = folder / dll
            if candidate.is_file():
                found.append((str(candidate), "."))
                print(f"[spec] MSVC runtime: {dll}  <- {folder}")
                break
        else:
            missing.append(dll)
    if missing:
        # _1/_2 variants genuinely do not exist in older toolsets, so this
        # is information, not an error
        print(f"[spec] MSVC runtime not found (may be fine): "
              f"{', '.join(missing)}")
    if not any(f[0].lower().endswith("msvcp140.dll") for f in found):
        print("[spec] WARNING: MSVCP140.dll was not found anywhere. Qt6 "
              "needs it. Install the 'Microsoft Visual C++ 2015-2022 "
              "Redistributable (x64)' on this build machine and rebuild, "
              "or your users will need it installed.")
    return found


binaries += _msvc_runtime()

# "winrt" is the PyWinRT namespace package behind the GSMTC media
# backend; it ships compiled extension modules that the static analysis
# cannot follow, so it has to be collected wholesale. "winsdk" is the
# legacy binding for Python <= 3.12 - whichever is installed gets bundled.
import importlib.util

for _opt in ("speech_recognition", "deepl", "winrt", "winsdk",
             # sounddevice itself is a single MODULE (sounddevice.py), so
             # collect_all finds no data in it - PyInstaller even warns
             # about that. The PortAudio DLL lives in the separate
             # _sounddevice_data PACKAGE, which has to be collected by
             # name or the frozen app has the wrapper without the library.
             "sounddevice", "_sounddevice_data"):
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
