#!/usr/bin/env python3
"""
tests/smoke.py - starts the real app once in every mode and checks that it
comes up and shuts down again without an error.

    python3 tests/smoke.py            (from the project folder)
    python3 tests/smoke.py --keep     (keep the temporary config for a look)

What it does
------------
1. compiles every .py file (catches syntax errors for the Python in use)
2. terminal mode (--headless): start, wait for "Ready.", DCB-quit
3. terminal mode with --profile="…": the profile must be active afterwards
4. terminal mode WITHOUT --profile: the last profile must still be active
5. terminal mode with an unknown --profile: must say so and keep running
6. window mode (offscreen, no screen needed) with --profile: window opens,
   is closed again after a few seconds, profile must be active

Safe to run on your own machine: every start gets a throw-away HOME
(and APPDATA on Windows), so your real config, profiles and plugins are
never touched. Send to VRChat is off and the OSC target is a port
nobody listens on - nothing ever reaches a running VRChat.

Not part of pytest on purpose (it starts real processes, ~10 s); `python3 -m pytest` does not collect it.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "osc_dreamchatbox.py"
IS_WINDOWS = sys.platform.startswith("win")

#: longest a single start may take before it counts as hung
START_TIMEOUT = 90
#: how long the window stays open in step 6
WINDOW_SECONDS = 4

#: a config that can never send anything anywhere
SAFE_CONFIG = {
    "send_to_vrchat": False,
    "osc_ip": "127.0.0.1",
    "osc_port": 9,              # "discard" - nothing listens there
    "oscquery_enabled": False,
    "osc_input_enabled": False,
    "hw_active": False,
    "media_active": False,
}

#: lines that mean something went wrong, whatever the exit code says
BAD_WORDS = ("Traceback (most recent call last)", "SyntaxError",
             "ImportError", "ModuleNotFoundError")

# ------------------------------------------------------------ output
_results = []


def _ok(name, detail=""):
    _results.append((True, name))
    print(f"  OK    {name}" + (f"  ({detail})" if detail else ""), flush=True)


def _fail(name, detail):
    _results.append((False, name))
    print(f"  FAIL  {name}\n        {detail}", flush=True)


def _tail(text, lines=15):
    rows = (text or "").strip().splitlines()
    return "\n        ".join(rows[-lines:]) or "(no output)"


# ------------------------------------------------------ test sandbox
class Sandbox:
    """A throw-away HOME with a safe config and two profiles."""

    def __init__(self, keep=False):
        self.keep = keep
        self.home = Path(tempfile.mkdtemp(prefix="dcb-smoke-"))
        if IS_WINDOWS:
            self.cfg_dir = self.home / "AppData" / "Roaming" / "OSC-DreamChatbox"
        else:
            self.cfg_dir = self.home / ".config" / "OSC-DreamChatbox"
        (self.cfg_dir / "profiles").mkdir(parents=True)
        cfg = dict(SAFE_CONFIG, profile_active="Smoke A",
                   status_texts=["SMOKE A"])
        self.write_json("config.json", cfg)
        self.write_json("profiles/Smoke A.json", {"status_texts": ["SMOKE A"]})
        self.write_json("profiles/Smoke B.json", {"status_texts": ["SMOKE B"]})

    def write_json(self, rel, data):
        (self.cfg_dir / rel).write_text(json.dumps(data, indent=2),
                                        encoding="utf-8")

    def config(self):
        return json.loads((self.cfg_dir / "config.json").read_text(
            encoding="utf-8"))

    def env(self):
        env = dict(os.environ, HOME=str(self.home),
                   PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
        env.pop("XDG_CONFIG_HOME", None)
        env.pop("DCB_PERF", None)
        if IS_WINDOWS:
            env["APPDATA"] = str(self.home / "AppData" / "Roaming")
            env["USERPROFILE"] = str(self.home)
        return env

    def cleanup(self):
        if self.keep:
            print(f"\nTemporary config kept: {self.cfg_dir}")
        else:
            shutil.rmtree(self.home, ignore_errors=True)


# ------------------------------------------------------------ steps
def step_compile():
    """In memory only - no __pycache__ is written into the project."""
    name = "all files compile"
    files = [APP]
    for folder in ("core", "ui", "plugins", "scripts", "tests"):
        if (ROOT / folder).is_dir():
            files += sorted((ROOT / folder).rglob("*.py"))
    errors = []
    for f in files:
        try:
            compile(f.read_text(encoding="utf-8"), str(f), "exec")
        except (SyntaxError, ValueError, UnicodeDecodeError) as e:
            errors.append(f"{f.relative_to(ROOT)}: {e}")
    if errors:
        _fail(name, "\n        ".join(errors))
    else:
        _ok(name, f"{len(files)} files, Python {sys.version.split()[0]}")


def run_headless(box, *args, quit_after_ready=True):
    """Starts terminal mode, waits for "Ready.", sends DCB-quit.
    Returns (exit code or None on hang, full output)."""
    cmd = [sys.executable, str(APP), "--headless", *args]
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT), env=box.env(), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace")
    out = []
    deadline = time.monotonic() + START_TIMEOUT
    try:
        for line in proc.stdout:
            out.append(line)
            if "Ready." in line and quit_after_ready:
                proc.stdin.write("DCB-quit\n")
                proc.stdin.flush()
            if time.monotonic() > deadline:
                break
        code = proc.wait(timeout=30)
    except (subprocess.TimeoutExpired, BrokenPipeError, OSError):
        proc.kill()
        code = None
    return code, "".join(out)


def _check_run(name, code, out, extra=None):
    if code is None:
        _fail(name, "hung - no clean exit\n        " + _tail(out))
        return False
    bad = [w for w in BAD_WORDS if w in out]
    if code != 0 or bad:
        _fail(name, f"exit code {code}" + (f", {bad[0]}" if bad else "")
              + "\n        " + _tail(out))
        return False
    if "Ready." not in out:
        _fail(name, "never reported 'Ready.'\n        " + _tail(out))
        return False
    if extra:
        problem = extra()
        if problem:
            _fail(name, problem)
            return False
    return True


def step_headless(box):
    name = "terminal mode starts and quits"
    code, out = run_headless(box)
    if _check_run(name, code, out):
        _ok(name)


def _active_is(box, want, text):
    def check():
        cfg = box.config()
        got = (cfg.get("profile_active"), (cfg.get("status_texts") or [""])[0])
        if got != (want, text):
            return f"expected profile {want!r} / {text!r}, got {got!r}"
        return ""
    return check


def step_headless_profile(box):
    name = 'terminal mode --profile="smoke b"'
    code, out = run_headless(box, '--profile=smoke b')   # case must not matter
    if _check_run(name, code, out, _active_is(box, "Smoke B", "SMOKE B")):
        _ok(name)


def step_headless_last_profile(box):
    name = "terminal mode without --profile keeps the last one"
    code, out = run_headless(box)
    if _check_run(name, code, out, _active_is(box, "Smoke B", "SMOKE B")):
        _ok(name)


def step_headless_unknown_profile(box):
    name = "terminal mode with an unknown --profile"

    def said_so():
        if "not found" not in out:
            return "no 'not found' message\n        " + _tail(out)
        return _active_is(box, "Smoke B", "SMOKE B")()
    code, out = run_headless(box, "--profile", "Does Not Exist")
    if _check_run(name, code, out, said_so):
        _ok(name)


#: runs INSIDE the window process: the normal main(), plus a timer that
#: closes every window after a few seconds (and any dialog before it)
_WINDOW_DRIVER = r"""
import sys, runpy
sys.path.insert(0, {root!r})
import PyQt6.QtWidgets as W
from PyQt6.QtCore import QTimer

class _SmokeApp(W.QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self._started = False
        self._t = QTimer()
        self._t.timeout.connect(self._tick)
        self._t.start({ms})

    def _tick(self):
        # a dialog on top (e.g. "no emoji font") is answered first,
        # then the main window gets a normal close -> closeEvent runs
        for w in self.topLevelWidgets():
            if w.isVisible():
                if isinstance(w, W.QDialog):
                    w.reject()
                else:
                    w.close()
        if self._started:
            QTimer.singleShot(500, self.quit)

    def exec(self):
        self._started = True
        print("SMOKE: event loop running", flush=True)
        return super().exec()

W.QApplication = _SmokeApp
sys.argv = [{app!r}] + {args!r}
runpy.run_path({app!r}, run_name="__main__")
"""


def step_window(box):
    name = 'window mode (offscreen) --profile "Smoke A"'
    driver = _WINDOW_DRIVER.format(root=str(ROOT), app=str(APP),
                                   args=["--profile", "Smoke A"],
                                   ms=WINDOW_SECONDS * 1000)
    try:
        res = subprocess.run(
            [sys.executable, "-c", driver], cwd=str(ROOT), env=box.env(),
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=START_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        _fail(name, "hung - the window did not close\n        "
              + _tail((e.stdout or "") + (e.stderr or "")))
        return
    out = (res.stdout or "") + (res.stderr or "")
    bad = [w for w in BAD_WORDS if w in out]
    if res.returncode != 0 or bad:
        _fail(name, f"exit code {res.returncode}"
              + (f", {bad[0]}" if bad else "") + "\n        " + _tail(out))
        return
    if "SMOKE: event loop running" not in out:
        _fail(name, "the window never got to its event loop "
              "(closed by a dialog?)\n        " + _tail(out))
        return
    problem = _active_is(box, "Smoke A", "SMOKE A")()
    if problem:
        _fail(name, problem)
        return
    _ok(name)


# -------------------------------------------------------------- main
def main():
    keep = "--keep" in sys.argv[1:]
    print(f"OSC-DreamChatbox smoke test - Python {sys.version.split()[0]}\n")
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        print("PyQt6 is not installed for this Python "
              f"({sys.executable}) - install the requirements first.")
        return 2

    step_compile()
    box = Sandbox(keep=keep)
    try:
        step_headless(box)
        step_headless_profile(box)
        step_headless_last_profile(box)
        step_headless_unknown_profile(box)
        step_window(box)
    finally:
        box.cleanup()

    failed = [n for ok, n in _results if not ok]
    print()
    if failed:
        print(f"{len(failed)} of {len(_results)} checks FAILED.")
        return 1
    print(f"All {len(_results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
