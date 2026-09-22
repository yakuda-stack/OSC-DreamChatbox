"""
tests/test_headless_speech.py - Speech to Text and Two-way in terminal mode.

Runs a whole typed session in a subprocess (terminal mode swaps Qt
modules, which must not happen in the test process). Only the bottom
layer is faked - the device scan and the recording helper, since a test
machine has no microphone. Everything above it is the real code: the
DCB- commands, the _Toggle stand-ins for the start buttons, the window's
preflight, the poll timers, _deliver_translation and the saved config.

What it guards: the start buttons. The window checks
stt_button.isChecked() halfway through starting; with a plain stand-in
that answered "not checked" and recording never began. And Two-way read
its source from a dropdown stand-in, which silently meant "system
default" instead of the monitor that was chosen.
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

SESSION = r'''
import sys, json
sys.path.insert(0, ROOT)
from core import qtstub; qtstub.install()
from PyQt6.QtCore import QCoreApplication, QTimer
app = QCoreApplication([])
import core.speechtotext as st
ENTRIES = [
  {"id": "", "label": "System default", "group": "system", "default": True},
  {"id": "pulse:mic.rode", "label": "Rode NT-USB", "group": "mic",
   "default": False},
  {"id": "pulse:out.monitor", "label": "Speakers (monitor)",
   "group": "monitor", "default": False},
]
st.list_microphone_groups = lambda *a, **k: (ENTRIES, [], [])
st.SpeechWorker.available = staticmethod(lambda: True)
STARTED = []
def fake_start(self, lang, out, *a, **k):
    STARTED.append([lang, out, k.get("mic_node")])
    self.messages.put(("text", ("hallo zusammen", "hello everyone")))
st.SpeechWorker.start = fake_start
st.SpeechWorker.stop = lambda self: None
import ui.pages.textbox_page as tp, ui.pages.twoway_page as tw
for m in (tp, tw):
    m.list_microphone_groups = st.list_microphone_groups
    m.resolve_entry = lambda eid, *a, **k: (3, eid.replace("pulse:", ""), "")
from core import headless
W = headless._make_window_class()(verbose=False)
W.begin_loading()
script = ["DCB-mic", "2", "DCB-lang", "1", "DCB-translate", "2",
          "DCB-stt", "WAIT", "DCB-stt",
          "DCB-2way-source", "1", "DCB-2way-lang", "2",
          "DCB-2way", "WAIT", "DCB-2way", "DCB-quit"]
def step():
    if not W.ready:
        W.loading_tick(); return
    cmd = script.pop(0)
    if cmd == "WAIT":
        return
    if W.command(cmd) == "quit":
        W.shutdown()
        print("STARTED=" + json.dumps(STARTED), flush=True)
        app.quit()
t = QTimer(); t.timeout.connect(step); t.start(300)
app.exec()
'''


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="uses HOME for the config folder")
def test_speech_and_twoway_session(tmp_path):
    cfg_dir = tmp_path / ".config" / "OSC-DreamChatbox"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps({
        "send_to_vrchat": False, "oscquery_enabled": False,
        "hw_active": False, "media_active": False,
        "stt_language": "en-US", "stt_output": ""}), encoding="utf-8")
    env = dict(os.environ, HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    env.pop("XDG_CONFIG_HOME", None)
    code = f"ROOT = {str(ROOT)!r}\n" + SESSION
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, env=env, timeout=90, check=False)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "Traceback" not in out, out

    # the helpers were started with what was picked - device node and
    # languages - not with a stand-in's "nothing"
    started = json.loads(out.split("STARTED=", 1)[1].splitlines()[0])
    assert started == [["de-DE", "en", "mic.rode"],
                       ["en-US", "de", "out.monitor"]]
    # what was heard reached the terminal
    assert "(speech) hallo zusammen  ->  hello everyone" in out
    assert ">> [" in out and "hello everyone" in out
    assert "Microphone: Rode NT-USB" in out
    assert "Speech to Text stopped" in out and "Two-way stopped." in out
    # and the choices are stored for the next start (and the window)
    cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert cfg["stt_mic"] == "pulse:mic.rode"
    assert cfg["stt_language"] == "de-DE"
    assert cfg["stt_output"] == "en"
    assert cfg["stt_twoway_source"] == "pulse:out.monitor"
    assert cfg["stt_twoway_language"] == "en-US"
