# Building the Windows .exe

Everything here runs on a Windows machine. Linux builds (AppImage, AUR)
are unaffected and use `scripts/build_appimage.sh` / `packaging/aur/`.

---

## TL;DR

```powershell
cd C:\Dev\OSC-DreamChatbox
.\packaging\windows\build-exe.ps1              # test build (folder + console)
.\packaging\windows\build-exe.ps1 -NoConsole   # release build
iscc packaging\windows\installer.iss           # optional: installer
```

---

## 1. Prerequisites

| | |
|---|---|
| **Python 3.11 – 3.14** | from python.org, tick *"Add python.exe to PATH"* |
| **Visual C++ 2015-2022 Redistributable (x64)** | **on the build machine.** Not for you - so the build can copy `MSVCP140.dll` into the package for *your users*. See §4. |
| Inno Setup 6 *(optional)* | https://jrsoftware.org/isdl.php - only for the installer |

Do **not** use the Microsoft Store version of Python. It runs in a
sandbox with redirected `%APPDATA%`, and PyInstaller builds made with it
tend to fail in ways that are hard to diagnose.

---

## 2. First: run from source

Always do this before building. A PyInstaller traceback is much harder
to read than a normal one, and 90 % of problems show up here already.

```powershell
cd C:\Dev\OSC-DreamChatbox
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-windows.txt
python osc_dreamchatbox.py
```

If PowerShell refuses to activate the venv:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Expected: the window opens, Media and Hardware cards fill in, the debug
console names the backends it picked.

---

## 3. Build

```powershell
.\packaging\windows\build-exe.ps1
```

The script creates its own `.build-venv`, installs
`requirements-windows.txt`, converts `assets\icon.png` to `.ico` and runs
PyInstaller with `packaging\windows\osc-dreamchatbox.spec`.

| Switch | Effect |
|---|---|
| *(none)* | one **folder** + console window - the test build |
| `-NoConsole` | no console window - the release build |
| `-OneFile` | a single `.exe` (see §5 for why that is not the default) |
| `-Clean` | wipe `build\` and `dist\` first |
| `-SkipDeps` | reuse the venv untouched - much faster rebuilds |

Result: `dist\OSC-DreamChatbox\OSC-DreamChatbox.exe`

Behind the scenes the spec sets two environment variables, so this also
works if you call PyInstaller yourself:

```powershell
$env:DCB_CONSOLE = "0"   # 1 = keep console (default)
$env:DCB_ONEFILE = "0"   # 1 = single file
pyinstaller --noconfirm --clean packaging\windows\osc-dreamchatbox.spec
```

---

## 4. The DLL question (VCRUNTIME140 / MSVCP140)

This is the classic "works on my machine" trap. Two separate runtimes
are involved:

* **`VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`** - the C runtime. CPython
  itself needs it, and python.org ships a copy next to `python.exe`.
  PyInstaller normally picks this one up on its own.
* **`MSVCP140.dll`** (+ `_1`, `_2`, `CONCRT140`) - the **C++** runtime.
  **Qt6 needs it.** It usually only exists in `System32`, because some
  installer put the VC++ redistributable there - and PyInstaller
  deliberately does not collect DLLs it considers part of the operating
  system.

So on your machine everything works, and on a fresh Windows install the
app dies at startup with *"The code execution cannot proceed because
MSVCP140.dll was not found"*.

The spec handles it: it looks for these DLLs next to `python.exe` first,
then in `System32`, and copies whatever it finds into the package. This
is app-local deployment, which Microsoft documents and permits for the
redistributable files.

**Watch the build log:**

```
[spec] MSVC runtime: VCRUNTIME140.dll  <- C:\Users\...\Python314
[spec] MSVC runtime: MSVCP140.dll      <- C:\Windows\System32
```

If instead you see:

```
[spec] WARNING: MSVCP140.dll was not found anywhere.
```

then install the **Visual C++ 2015-2022 Redistributable (x64)** on the
build machine and rebuild. Otherwise your users need it installed.

### Verify before you ship

```powershell
dir dist\OSC-DreamChatbox\_internal\*140*.dll
dir dist\OSC-DreamChatbox\_internal\Qt6Core.dll
dir dist\OSC-DreamChatbox\_internal\_sounddevice_data\portaudio-binaries\
```

The real test is a machine that has never had Python or Visual Studio on
it. A fresh Windows VM is worth the twenty minutes.

---

## 5. One folder or one file?

**Use one folder.** `-OneFile` exists, but:

| | one folder | one file |
|---|---|---|
| Start time | instant | 3-10 s **every launch** - it unpacks ~200 MB to `%TEMP%` first |
| Antivirus | normal | frequent false positives; self-extracting behaviour looks like a dropper |
| Debugging | you can look inside `_internal` | opaque |
| Distribution | needs a zip or installer | one file to hand out |
| `%TEMP%` litter | none | a crash leaves a `_MEIxxxxxx` folder behind |

The single-file convenience is the only argument for it, and an
installer solves that better.

**Your configs are safe either way.** The app resolves its config
directory through `core/osinfo.py`, which returns
`%APPDATA%\OSC-DreamChatbox` on Windows - never a path inside the
bundle. So the `%TEMP%` unpack folder of a one-file build cannot take
settings, plugins or themes with it when it disappears.

---

## 6. Releases

```powershell
.\packaging\windows\make-release.ps1
```

Builds both artifacts that belong on the releases page and nothing else:

| Artifact | What it is |
|---|---|
| `OSC-DreamChatbox-<ver>-setup.exe` | Inno Setup installer, the default download |
| `OSC-DreamChatbox-<ver>-portable.exe` | one-file build, for people who refuse installers |

The version is read from `core/constants.py` and passed to Inno Setup with
`/DAppVersion=`, so the `.iss` can no longer drift.

### Never ship a zip of `dist\OSC-DreamChatbox\`

That is where this bug report comes from:

```
Failed to load Python DLL 'C:\Users\...\Downloads\_internal\python314.dll'.
LoadLibrary: Das angegebene Modul wurde nicht gefunden.
```

The user dragged `OSC-DreamChatbox.exe` out of the zip and left `_internal`
behind, or ran it straight out of Explorer's zip preview, which extracts
only the file that was double-clicked. The exe *is* the PyInstaller
bootloader - it needs `_internal\pythonXXX.dll` sitting next to it, and it
dies before a single line of our Python runs. There is no way to catch this
in the app; the only fix is not to hand out that shape in the first place.

### Building the installer by hand

```powershell
iscc /DAppVersion=1.4.0 packaging\windows\installer.iss
```

The script installs per-user (`PrivilegesRequired=lowest`), so there is
no UAC prompt at install time. Start-menu entry, optional desktop icon,
optional autostart, proper uninstaller.

`%APPDATA%\OSC-DreamChatbox` is deliberately **not** removed on
uninstall - that is the user's config, plugins and themes.

Bump `#define AppVersion` in the `.iss` when you bump
`core/constants.py`.

---

## 7. Troubleshooting

| Symptom | Cause |
|---|---|
| `ModuleNotFoundError` right after launch | add the module to `hiddenimports` in the spec |
| MSVCP140.dll dialog on another PC | §4 - the redistributable was missing at build time |
| Media card empty | `pip install "winrt-Windows.Media.Control[all]"` - **not** `winsdk`, it has no wheels past 3.12 |
| Microphone missing | `pip install sounddevice` - **not** `pyaudio`, no wheels past 3.13 |
| A black console flashes over the game | a `subprocess` call without `creationflags` - use `core.osinfo.subprocess_flags()` |
| Antivirus quarantines the build | unsigned executables get flagged; a code-signing certificate is the only real fix. One folder is flagged far less than one file. |
| OSCQuery finds no VRChat | Windows Firewall blocked mDNS on first run - allow it, or the app falls back to port 9000 |
