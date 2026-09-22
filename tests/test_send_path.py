"""
tests/test_send_path.py - one send, one frame; and the first send waits.

Both run the real MainWindow (offscreen) in a subprocess with its own
HOME, so no developer config is touched and no window appears.

* A send builds the payload ONCE. send_now() hands the text it built to
  the preview instead of the preview building it again - every build
  runs all plugin hooks (on_tick, get_values), so a slow plugin paid for
  each extra copy. What VRChat gets and what the preview shows must
  still be the same text.
* The first message waits for hardware/media (MainWindow._begin_warmup),
  so it carries real values instead of "GPU °C".
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
import sys, os, json
sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ui.mainwindow import MainWindow
w = MainWindow()
w.log = lambda m: None
sent = []
class Client:
    def send_message(self, addr, args):
        sent.append(args[0])
w.osc_client = Client()
w._osc_send_delay = lambda now=None: 0.0
out = {}

# --- warm-up: hardware is on, nothing may go out before it answered
out["held"] = bool(w._warmup)
w.send_now()
out["sent_while_warming"] = len(sent)
w._on_hw_result(w.hw.snapshot())         # the first answer arrives
out["warm_after"] = w._warmup
out["sent_after_warmup"] = len(sent)

# --- one build per send
calls = {"build": 0}
real = w.build_payload
def counting(*a, **k):
    calls["build"] += 1
    return real(*a, **k)
w.build_payload = counting
w._last_sent_payload = None
w.send_now()
out["builds_per_timer_send"] = calls["build"]
out["preview_equals_sent"] = (
    w.preview_label.text() == sent[-1].replace("\x03\x1f", ""))
# a signal handing update_preview a value must not become the text
w.update_preview()
out["public_preview_rebuilds"] = calls["build"] == 2
print("RESULT=" + json.dumps(out), flush=True)
os._exit(0)
'''


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="uses HOME for the config folder")
def test_one_build_per_send_and_warmup(tmp_path):
    cfg_dir = tmp_path / ".config" / "OSC-DreamChatbox"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({
        "send_to_vrchat": True, "oscquery_enabled": False,
        "hw_active": True, "media_active": False,
        "status_active": True,
        "status_texts": ["SEND-PATH"] + [""] * 19, "status_count": 1,
    }), encoding="utf-8")
    env = dict(os.environ, HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    env.pop("XDG_CONFIG_HOME", None)
    proc = subprocess.run(
        [sys.executable, "-c", f"ROOT = {str(ROOT)!r}\n" + SCRIPT],
        capture_output=True, text=True, env=env, timeout=90, check=False)
    out = proc.stdout + proc.stderr
    assert "RESULT=" in out, out
    res = json.loads(out.split("RESULT=", 1)[1].splitlines()[0])
    assert res["held"] is True
    assert res["sent_while_warming"] == 0
    assert res["warm_after"] is None
    assert res["sent_after_warmup"] >= 1          # the held message went
    assert res["builds_per_timer_send"] == 1
    assert res["preview_equals_sent"] is True
    assert res["public_preview_rebuilds"] is True
