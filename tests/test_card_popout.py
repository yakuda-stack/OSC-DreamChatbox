"""
tests/test_card_popout.py - v1.7.5: To Text tidier + pop-out cards.

Runs the real MainWindow (offscreen) in a subprocess with its own HOME,
like tests/test_send_path.py.

* To Text: Start recording, the text field and the status stay visible,
  the settings (service, languages, microphone ...) fold away under
  "Speech settings".
* the pop-out button (box + arrow) moves To Text / Two-way into their own window, a placeholder keeps
  the place in the card order; closing the window puts the card back
  at the same spot.
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
from ui.card_popout import CardPopout
w = MainWindow()
w.log = lambda m: None
out = {}
body = w.stt_body
out["rec_outside"] = not body.isAncestorOf(w.rec_row_w)
out["text_outside"] = not body.isAncestorOf(w.stt_text_box)
out["status_outside"] = not body.isAncestorOf(w.stt_status_lbl)
out["settings_inside"] = all(body.isAncestorOf(x) for x in (
    w.tr_active_combo, w.stt_lang_combo, w.stt_out_combo, w.mic_combo,
    w.toggle_mic_raw, w.toggle_mic_strict))
out["label"] = w.stt_expander.text()

for key in ("stt", "twoway"):
    card = w.tb_cards[key]
    idx = w.tb_layout.indexOf(card)
    count = w.tb_layout.count()
    w.toggle_card_popout(key)
    win = w.popouts.get(key)
    res = {"popped": isinstance(win, CardPopout),
           "card_in_window": win is not None and win.isAncestorOf(card),
           "slot_at_idx": w.tb_layout.indexOf(w.popout_slots[key]) == idx,
           "button": w.popout_btns[key].toolTip()}
    # dragging another card while this one is out must not pull it back
    other = "presets"
    w.tb_card_drag(other, w.tb_cards["chat"].mapToGlobal(
        w.tb_cards["chat"].rect().center()))
    res["still_out"] = win.isAncestorOf(card)
    w.tb_card_drag(other, w.tb_cards[other].mapToGlobal(
        w.tb_cards[other].rect().bottomRight()) * 10)
    win.close()
    app.processEvents()
    res["docked"] = key not in w.popouts
    res["card_back"] = w.tb_layout.indexOf(card) >= 0
    res["slot_gone"] = w.tb_layout.indexOf(w.popout_slots[key]) < 0
    res["count_same"] = w.tb_layout.count() == count
    res["button_back"] = w.popout_btns[key].toolTip()
    res["has_icon"] = not w.popout_btns[key].icon().isNull()
    out[key] = res
print("RESULT=" + json.dumps(out), flush=True)
os._exit(0)
'''


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="uses HOME for the config folder")
def test_to_text_tidy_and_cards_pop_out(tmp_path):
    cfg_dir = tmp_path / ".config" / "OSC-DreamChatbox"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({
        "send_to_vrchat": False, "oscquery_enabled": False,
    }), encoding="utf-8")
    env = dict(os.environ, HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    env.pop("XDG_CONFIG_HOME", None)
    proc = subprocess.run(
        [sys.executable, "-c", f"ROOT = {str(ROOT)!r}\n" + SCRIPT],
        capture_output=True, text=True, env=env, timeout=90, check=False)
    out = proc.stdout + proc.stderr
    assert "RESULT=" in out, out
    res = json.loads(out.split("RESULT=", 1)[1].splitlines()[0])
    assert res["rec_outside"] and res["text_outside"] and res["status_outside"]
    assert res["settings_inside"]
    assert "Speech settings" in res["label"]
    for key in ("stt", "twoway"):
        r = res[key]
        assert r["popped"] and r["card_in_window"] and r["slot_at_idx"], r
        assert r["button"] == "Back into the app" and r["still_out"], r
        assert r["docked"] and r["card_back"] and r["slot_gone"], r
        assert r["count_same"] and r["button_back"].startswith("Pop out"), r
        assert r["has_icon"], r
