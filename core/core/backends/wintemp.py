"""
core/backends/wintemp.py – elevated temperature helper for Windows

WHY THIS IS NOT JUST "run something as admin"
---------------------------------------------
CPU die temperatures on x86 live in MSRs (model-specific registers).
Those are readable only from ring 0 - kernel mode. Administrator rights
do NOT help: an elevated process still runs in ring 3. Every Windows
tool that shows a CPU temperature (HWiNFO, MSI Afterburner, Core Temp,
LibreHardwareMonitor) ships a signed kernel driver for exactly this.

So a helper script that "just reads the CPU temperature as admin" cannot
exist. What CAN be done from an elevated user-mode process is two things,
and this module does both:

  1. ACPI thermal zones  (MSAcpi_ThermalZoneTemperature, root\\WMI)
     A firmware-provided reading that needs elevation but no driver.
     Present on most laptops and many OEM boards; most enthusiast
     desktop boards expose nothing here. Free to try, so we try it.

  2. Drive LibreHardwareMonitor
     LHM already has the signed driver, is GPL (same licence as this
     app) and exposes every sensor over WMI and over an HTTP endpoint.
     It only needs elevation to load its driver - which is precisely
     what the "grant admin rights" button is for.

Deliberately NOT done: shipping our own copy of WinRing0.sys, the driver
LHM and friends use. It has published privilege-escalation CVEs
(CVE-2020-14979 / CVE-2020-14980 - arbitrary MSR and physical memory
access for any local user), Microsoft's vulnerable-driver blocklist
rejects older builds on any machine with Memory Integrity on, and
antivirus flags it. A VRChat chatbox has no business installing a ring-0
attack surface on its users' machines.

ARCHITECTURE
------------
    UI button
      -> TempHelper.enable()
         -> deploy dreamtemp-helper.ps1 into CONFIG_DIR/helper/
         -> ShellExecuteW(verb="runas")  -> UAC prompt
      -> elevated powershell polls ACPI + LHM's WMI namespace
         and writes CONFIG_DIR/temps.json once a second
    main app (unelevated)
      -> TempHelper.temps() just reads that file

The file is the whole IPC: no sockets, no pipes, no privileged code in
the app itself. The helper carries the app's PID and exits by itself
when the app is gone, so a stray elevated process can never survive.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from core.constants import CONFIG_DIR
from core.osinfo import IS_WINDOWS, resource_root

HELPER_NAME = "dreamtemp-helper.ps1"
HELPER_DIR = CONFIG_DIR / "helper"
HELPER_SCRIPT = HELPER_DIR / HELPER_NAME
TEMPS_FILE = CONFIG_DIR / "temps.json"
STOP_FILE = HELPER_DIR / "stop"

#: a reading older than this is stale - the helper died or was killed
FRESH_SEC = 8.0

LHM_DOWNLOAD_URL = ("https://github.com/LibreHardwareMonitor"
                    "/LibreHardwareMonitor/releases")
# RTSS is not on GitHub; Guru3D is where the author publishes it.
# It also ships inside MSI Afterburner, so many people already have it.
RTSS_DOWNLOAD_URL = ("https://www.guru3d.com/download/"
                     "rtss-rivatuner-statistics-server-download/")

# ShellExecuteW returns <= 32 on failure; 5 is "user said No to UAC"
_SE_ACCESS_DENIED = 5
_SW_HIDE = 0


# ------------------------------------------------------------------ LHM
def _lhm_candidates():
    """Every place LibreHardwareMonitor realistically installs to."""
    out = []
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)",
                "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        out.append(Path(base) / "LibreHardwareMonitor"
                   / "LibreHardwareMonitor.exe")
        out.append(Path(base) / "Programs" / "LibreHardwareMonitor"
                   / "LibreHardwareMonitor.exe")
    home = Path.home()
    # scoop
    out.append(home / "scoop" / "apps" / "librehardwaremonitor" / "current"
               / "LibreHardwareMonitor.exe")
    # chocolatey
    out.append(Path(r"C:\ProgramData\chocolatey\lib\librehardwaremonitor"
                    r"\tools\LibreHardwareMonitor.exe"))
    return out


def _lhm_from_registry():
    """Uninstall entries know where it went, whatever installer was used."""
    found = []
    try:
        import winreg
    except Exception:
        return found
    roots = ((winreg.HKEY_LOCAL_MACHINE,
              r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE,
              r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER,
              r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"))
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as root:
                for i in range(4096):
                    try:
                        sub = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            name = str(winreg.QueryValueEx(
                                k, "DisplayName")[0])
                            if "librehardwaremonitor" not in \
                                    name.replace(" ", "").lower():
                                continue
                            try:
                                loc = winreg.QueryValueEx(
                                    k, "InstallLocation")[0]
                                if loc:
                                    found.append(Path(loc)
                                                 / "LibreHardwareMonitor.exe")
                            except OSError:
                                pass
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def find_lhm():
    """Path to LibreHardwareMonitor.exe, or None."""
    if not IS_WINDOWS:
        return None
    for cand in _lhm_from_registry() + _lhm_candidates():
        try:
            if cand and cand.is_file():
                return cand
        except OSError:
            continue
    which = shutil.which("LibreHardwareMonitor")
    return Path(which) if which else None


def _lhm_running():
    """True when an LHM process exists. Cheap enough for a button click."""
    try:
        import subprocess
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq LibreHardwareMonitor.exe",
             "/NH"], capture_output=True, text=True, timeout=5,
            creationflags=0x08000000).stdout
        return "LibreHardwareMonitor" in out
    except Exception:
        return False


def configure_lhm_webserver(exe_path, port=8085):
    """Turn on LHM's web server in its own config file.

    ONLY safe while LHM is not running: it rewrites this file on exit and
    would drop our change again. Returns (ok, message).
    """
    cfg = Path(exe_path).with_name("LibreHardwareMonitor.config")
    wanted = {"runWebServer": "true", "listenerPort": str(port)}
    try:
        import xml.etree.ElementTree as ET
        if cfg.exists():
            tree = ET.parse(cfg)
            root = tree.getroot()
            app = root.find("appSettings")
            if app is None:
                app = ET.SubElement(root, "appSettings")
        else:
            root = ET.Element("configuration")
            app = ET.SubElement(root, "appSettings")
            tree = ET.ElementTree(root)
        for key, value in wanted.items():
            node = None
            for add in app.findall("add"):
                if add.get("key") == key:
                    node = add
                    break
            if node is None:
                node = ET.SubElement(app, "add")
                node.set("key", key)
            node.set("value", value)
        tree.write(cfg, encoding="utf-8", xml_declaration=True)
        return True, f"Web server enabled in {cfg.name} (port {port})"
    except PermissionError:
        # Program Files is not writable without elevation
        return False, ("Could not write LibreHardwareMonitor.config "
                       "(no permission). Enable Options > Remote Web Server "
                       "inside LHM once, by hand.")
    except Exception as e:
        return False, f"Could not edit LibreHardwareMonitor.config ({e})"


# -------------------------------------------------------------- elevate
def _shell_execute_runas(exe, params, workdir=None):
    """Start a program elevated. Returns (ok, message).

    The UAC prompt is the user's consent - we never try to work around
    it, and a "No" is reported back as a normal outcome, not an error.
    """
    try:
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(exe), params,
            str(workdir) if workdir else None, _SW_HIDE)
    except Exception as e:
        return False, f"ShellExecuteW failed ({e})"
    if rc > 32:
        return True, ""
    if rc == _SE_ACCESS_DENIED:
        return False, "Administrator rights were declined in the UAC prompt."
    return False, f"Could not start elevated (ShellExecute code {rc})."


def deploy_helper():
    """Copy the helper script out of the app bundle into CONFIG_DIR.

    It must live at a stable, real path: in a one-file PyInstaller build
    the bundle is a temp folder that an elevated process should not be
    pointed at, and it disappears when the app exits.
    """
    src = resource_root() / "packaging" / "windows" / HELPER_NAME
    if not src.is_file():
        src = resource_root() / HELPER_NAME     # flat bundle fallback
    if not src.is_file():
        return None, f"{HELPER_NAME} is missing from this build."
    try:
        HELPER_DIR.mkdir(parents=True, exist_ok=True)
        # always refresh, so an app update ships a new helper
        shutil.copyfile(src, HELPER_SCRIPT)
        STOP_FILE.unlink(missing_ok=True)
        return HELPER_SCRIPT, ""
    except Exception as e:
        return None, f"Could not deploy the helper ({e})"


# ==================================================================
class TempHelper:
    """Coordinates the elevated helper and LibreHardwareMonitor.

    Everything here is safe to call from a background thread except
    ``enable()``, which pops a UAC dialog and belongs on the GUI thread.
    """

    def __init__(self, log=None):
        self.log = log
        self.last_message = ""
        self._cache = (0.0, None, None, "")
        # a launch takes a few seconds to produce its first reading. Until
        # then the status still says "not active", and people click again -
        # which means a second UAC prompt and a second elevated helper.
        self._pending_until = 0.0

    # ---------------------------------------------------------- reading
    def temps(self):
        """(cpu_temp, gpu_temp) from the helper file, or (None, None).

        Reading a small JSON file is cheap, but snapshot() asks several
        times per poll, so a one-second cache keeps it to one stat().
        """
        now = time.monotonic()
        if now - self._cache[0] < 1.0:
            return self._cache[1], self._cache[2]
        cpu = gpu = None
        source = ""
        try:
            # utf-8-sig, not utf-8: PowerShell 5.1 writes a BOM and
            # json.loads() chokes on it
            data = json.loads(TEMPS_FILE.read_text(encoding="utf-8-sig"))
            if time.time() - float(data.get("ts", 0)) <= FRESH_SEC:
                cpu = data.get("cpu")
                gpu = data.get("gpu")
                source = str(data.get("source") or "")
                cpu = float(cpu) if isinstance(cpu, (int, float)) else None
                gpu = float(gpu) if isinstance(gpu, (int, float)) else None
                if cpu is not None and not (0 < cpu < 150):
                    cpu = None
                if gpu is not None and not (0 < gpu < 150):
                    gpu = None
        except Exception:
            pass
        self._cache = (now, cpu, gpu, source)
        return cpu, gpu

    def source(self):
        self.temps()
        return self._cache[3]

    def running(self):
        """True when a fresh reading exists, i.e. the helper is alive."""
        cpu, gpu = self.temps()
        return cpu is not None or gpu is not None

    # ----------------------------------------------------------- status
    def status(self):
        """(state, text) for the UI. state in:
        'active' | 'lhm-ready' | 'lhm-found' | 'none'"""
        if self.running():
            self._pending_until = 0.0
            src = self.source() or "helper"
            return "active", f"Temperature monitoring active (source: {src})."
        if time.monotonic() < self._pending_until:
            return "starting", ("Helper started \u2013 waiting for the first "
                                "reading\u2026")
        exe = find_lhm()
        if exe and _lhm_running():
            return "lhm-ready", ("LibreHardwareMonitor is running but not "
                                 "reachable - enable Options > Remote Web "
                                 "Server inside LHM.")
        if exe:
            return "lhm-found", ("LibreHardwareMonitor is installed but not "
                                 "running.")
        return "none", ("No temperature source. Windows cannot read CPU "
                        "temperatures without a kernel driver.")

    # ----------------------------------------------------------- action
    def enable(self):
        """The button. Returns (ok, message). Pops UAC; GUI thread only."""
        if not IS_WINDOWS:
            return False, "Windows only."
        if self.running():
            return True, "Temperature monitoring is already active."
        if time.monotonic() < self._pending_until:
            return True, ("A helper was just started - give it a few seconds "
                          "before trying again.")

        messages = []

        # --- path A: LibreHardwareMonitor, the real sensor source ---
        exe = find_lhm()
        if exe:
            if not _lhm_running():
                ok, msg = configure_lhm_webserver(exe)
                messages.append(msg)
                ok, msg = _shell_execute_runas(exe, "", exe.parent)
                if ok:
                    messages.append("LibreHardwareMonitor started with "
                                    "administrator rights.")
                else:
                    messages.append(msg)
            else:
                messages.append("LibreHardwareMonitor is already running.")

        # --- path B: our own elevated ACPI helper ---
        # Runs regardless: on boards that expose ACPI thermal zones it
        # gives a reading without LHM at all, and when LHM IS running it
        # additionally mirrors LHM's WMI sensors into temps.json.
        script, err = deploy_helper()
        if script is None:
            messages.append(err)
        else:
            params = (f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                      f'-File "{script}" '
                      f'-OutFile "{TEMPS_FILE}" '
                      f'-StopFile "{STOP_FILE}" '
                      f'-ParentPid {os.getpid()}')
            ok, msg = _shell_execute_runas("powershell.exe", params,
                                           HELPER_DIR)
            if ok:
                messages.append("Temperature helper started with "
                                "administrator rights.")
            else:
                messages.append(msg)

        if not exe:
            # Deliberately phrased as a possibility: ACPI thermal zones do
            # work on many laptops, so promising that LHM is REQUIRED was
            # wrong on exactly the machines where the button just worked.
            messages.append(
                "If no CPU temperature shows up in a few seconds, this "
                "board exposes no ACPI thermal zone and you need "
                "LibreHardwareMonitor - it ships the signed kernel driver "
                "Windows requires.")

        # block a second launch (and a second UAC prompt) while the first
        # one is still finding its feet
        self._pending_until = time.monotonic() + 20.0
        text = " ".join(m for m in messages if m)
        self.last_message = text
        if callable(self.log):
            self.log(f"Temps: {text}")
        # give the helper a moment before the UI re-reads the status
        return True, text

    def stop(self):
        """Ask a running helper to exit (it also exits when we do)."""
        try:
            HELPER_DIR.mkdir(parents=True, exist_ok=True)
            STOP_FILE.write_text("stop", encoding="utf-8")
            return True
        except Exception:
            return False
