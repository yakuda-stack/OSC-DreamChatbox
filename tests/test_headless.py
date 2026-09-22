"""
tests/test_headless.py - terminal mode (--headless).

Two halves:

* core/qtstub.Null, in this process. The whole mode rests on the
  stand-in widgets behaving like "nothing" in every context the ui code
  can put them in - including super() calls, which bypass __getattr__
  and were the first thing that broke.

* The real thing, in a subprocess. qtstub.install() swaps modules in
  sys.modules, which must never happen inside the test process (other
  tests import the real QtWidgets). The subprocess gets its own HOME, so
  it reads a config written here and nothing of the developer's.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import headless, selflaunch
from core.qtstub import Null, _NullMeta

ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------- qtstub
def test_null_is_nothing_in_every_value_context():
    n = Null()
    assert not n
    assert str(n) == "" and f"{n}" == "" and f"{n:>5}" == ""
    assert int(n) == 0 and float(n) == 0.0 and len(n) == 0
    assert list(n) == [] and "x" not in n
    assert n.text() is not None and not n.text()
    assert not n.isChecked()
    # arithmetic and flag operators never raise
    assert not (n.width() - 10) and not (n | 3)
    # geometry in drawing code (the first bug report: abs() on a wire)
    assert not abs(n.x() - n.x()) and round(n) == 0
    assert max(40.0, min(160.0, abs(n.x()) * 0.6)) == 160.0


def test_null_class_level_lookups():
    QSizePolicy = _NullMeta("QSizePolicy", (Null,), {})
    assert not QSizePolicy.Policy.Expanding
    assert not QSizePolicy.instance()


def test_super_calls_reach_a_real_method():
    class Panel(Null):
        def closeEvent(self, ev):
            return super().closeEvent(ev)

        def keyPressEvent(self, ev):
            super().keyPressEvent(ev)
            return "handled"

    p = Panel(None)
    p.closeEvent(None)
    assert p.keyPressEvent(None) == "handled"


def test_wants_headless():
    assert headless.wants_headless(["--headless"])
    assert headless.wants_headless(["--quiet", "--terminal"])
    assert not headless.wants_headless([])
    assert not headless.wants_headless(["--stt-helper"])


# ------------------------------------------------- the real process
def _run_headless(tmp_path, cfg, stdin="DCB-show\nDCB-quit\n"):
    """Runs the app in terminal mode with its own HOME and config.
    Returns (output, config bytes before, config bytes after)."""
    cfg_dir = tmp_path / ".config" / "OSC-DreamChatbox"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.json"
    base = {
        "send_to_vrchat": False,        # nothing goes on the wire
        "media_active": False,
        "hw_active": False,
        "box_active": False,
        "oscquery_enabled": False,
    }
    base.update(cfg)
    cfg_file.write_text(json.dumps(base), encoding="utf-8")
    before = cfg_file.read_bytes()

    env = dict(os.environ, HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    env.pop("XDG_CONFIG_HOME", None)    # config_dir() must follow HOME
    proc = subprocess.run(
        [sys.executable, str(ROOT / "osc_dreamchatbox.py"),
         "--headless", "--force"],
        input=stdin, capture_output=True, text=True,
        env=env, timeout=60, cwd=str(tmp_path), check=False)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "Traceback" not in out, out
    return out, before, cfg_file.read_bytes()


linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="uses HOME for the config folder")


@linux_only
def test_headless_runs_shows_payload_and_never_writes_config(tmp_path):
    out, before, after = _run_headless(tmp_path, {
        "status_active": True,
        "status_texts": ["HEADLESS-TEST-LINE"] + [""] * 19,
        "status_count": 1,
    })
    assert "terminal mode" in out
    assert "HEADLESS-TEST-LINE" in out          # /show printed the payload
    assert "Send to VRChat is OFF" in out       # the startup hint
    assert "Ready." in out
    # read only: the window's settings file is exactly what we wrote
    assert after == before


@linux_only
def test_headless_with_a_wired_advanced_canvas(tmp_path):
    """The first bug report: a canvas with a real wire crashed the start,
    because drawing the wire does abs() on stand-in positions. The test
    canvas before that had a wire on a socket name that does not exist,
    so it was silently skipped and never drew anything."""
    graph = {
        "nodes": [
            {"id": "n1", "type": "text", "x": 0.0, "y": 0.0,
             "values": {"value": "GRAPH-OK"}},
            {"id": "n2", "type": "output", "x": 300.0, "y": 120.0,
             "values": {}},
        ],
        "edges": [{"from": "n1", "out": "out", "to": "n2", "in": "in"}],
    }
    empty = {"nodes": [], "edges": []}
    out, before, after = _run_headless(tmp_path, {
        "status_active": False,
        "aio_active": True,
        "aio_mode": "advanced",
        "aio_count": 1,
        "aio_graphs": [graph, empty, empty, empty, empty],
    })
    assert "GRAPH-OK" in out                    # evaluated from the config
    assert after == before                      # canvas never written back


@linux_only
def test_headless_commands(tmp_path):
    """The DCB- commands a person actually types, in one session: the
    typos and the numbered lists included. Sending is off, so the chat
    line must NOT go out."""
    out, before, after = _run_headless(tmp_path, {
        "status_active": True,
        "status_texts": ["HELLO"] + [""] * 19,
        "status_count": 1,
    }, stdin="help\nDCB-HELP\ndcb-plugin-status\nDCB-profil\n"
              "DCB-plugin-on\nDCB-nope\nhi there\nDCB-quit\n")
    for name, _help in headless.COMMANDS:
        assert name in out                      # help lists every command
    assert "Commands start with DCB-" in out    # bare "help" is not sent
    assert "No plugins installed" in out
    assert "No profiles yet" in out
    assert "No plugin is off." in out
    assert "Unknown command DCB-nope" in out
    assert "not sent" in out                    # Send to VRChat is off
    assert after == before


@linux_only
def test_sendvrc_is_the_only_key_written(tmp_path):
    """DCB-sendvrc stores its switch - and nothing else. The file on
    disk is the base, so keys the window wrote survive untouched."""
    out, before, after = _run_headless(tmp_path, {
        "some_key_from_a_newer_window": 123,
    }, stdin="DCB-sendvrc\nDCB-quit\n")
    assert "Send to VRChat: ON" in out
    old, new = json.loads(before), json.loads(after)
    assert new.pop("send_to_vrchat") is True
    old.pop("send_to_vrchat")
    assert new == old


def test_help_text_lists_every_command():
    text = headless.help_text()
    for name, _help in headless.COMMANDS:
        assert name in text


# ------------------------------------------------------ selflaunch
def test_self_command_from_source(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    cmd = selflaunch.self_command(["--headless"])
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("osc_dreamchatbox.py")
    assert cmd[-1] == "--headless"


def test_self_command_from_appimage(monkeypatch):
    """The running code sits in a temporary mount that vanishes with
    this process - a new copy must come from the .AppImage file."""
    monkeypatch.setenv("APPIMAGE", "/home/x/OSC-DreamChatbox.AppImage")
    monkeypatch.setenv("APPDIR", "/tmp/.mount_abc")
    monkeypatch.setenv("PYTHONPATH", "/tmp/.mount_abc/usr/lib/python3")
    monkeypatch.setenv("PATH", "/tmp/.mount_abc/usr/bin:/usr/bin")
    assert selflaunch.self_command(["--headless"]) == [
        "/home/x/OSC-DreamChatbox.AppImage", "--headless"]
    env = selflaunch.clean_env()
    assert "PYTHONPATH" not in env
    assert env["PATH"] == "/usr/bin"


# ---------------------------------------------------- instancelock
HOLD = """
import sys, time
sys.path.insert(0, {root!r})
from pathlib import Path
from core import instancelock
instancelock.LOCK_FILE = Path({lock!r})
instancelock.CONFIG_DIR = Path({lock!r}).parent
print("got" if instancelock.acquire("terminal") else "busy", flush=True)
time.sleep(float(sys.argv[1]))
"""


@pytest.fixture
def lock_in_tmp(tmp_path, monkeypatch):
    from core import instancelock
    lock = tmp_path / "instance.lock"
    monkeypatch.setattr(instancelock, "LOCK_FILE", lock)
    monkeypatch.setattr(instancelock, "CONFIG_DIR", tmp_path)
    yield instancelock, lock
    instancelock.release()


def test_lock_is_exclusive_and_says_who_holds_it(lock_in_tmp):
    instancelock, lock = lock_in_tmp
    code = HOLD.format(root=str(ROOT), lock=str(lock))
    child = subprocess.Popen([sys.executable, "-c", code, "30"],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "got"
        assert not instancelock.acquire("window")
        assert instancelock.holder() == ("terminal", child.pid)
        assert "terminal mode (PID" in instancelock.describe_holder()
    finally:
        child.kill()
        child.wait()
    # the OS dropped the lock with the process - even after a kill
    assert instancelock.acquire("window")


def test_released_lock_is_free_while_the_process_still_runs(lock_in_tmp):
    """The window hands over after close(), while its process may keep
    running for a long time - that was the bug report."""
    instancelock, lock = lock_in_tmp
    code = HOLD.format(root=str(ROOT), lock=str(lock)).replace(
        "time.sleep(float(sys.argv[1]))",
        "instancelock.release(); print('released', flush=True); "
        "time.sleep(float(sys.argv[1]))")
    child = subprocess.Popen([sys.executable, "-c", code, "30"],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "got"
        assert child.stdout.readline().strip() == "released"
        assert instancelock.wait_and_acquire("terminal", timeout=5)
    finally:
        child.kill()
        child.wait()


@linux_only
def test_second_terminal_copy_is_refused(tmp_path):
    """Two copies, one HOME: the second one must say who is running."""
    cfg_dir = tmp_path / ".config" / "OSC-DreamChatbox"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({
        "send_to_vrchat": False, "oscquery_enabled": False,
        "hw_active": False, "media_active": False}), encoding="utf-8")
    env = dict(os.environ, HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    env.pop("XDG_CONFIG_HOME", None)
    cmd = [sys.executable, str(ROOT / "osc_dreamchatbox.py"), "--headless"]
    first = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True, env=env)
    try:
        for line in first.stdout:           # wait until it is running
            if "Ready." in line:
                break
        second = subprocess.run(cmd, input="", capture_output=True,
                                text=True, env=env, timeout=60, check=False)
        assert second.returncode == 1
        assert f"terminal mode (PID {first.pid})" in second.stdout
    finally:
        first.stdin.write("DCB-quit\n")
        first.stdin.close()
        first.wait(timeout=30)
