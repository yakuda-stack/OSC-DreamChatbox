"""tests/test_custom_translator.py - the "Custom" translation service."""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core import custom_translator as ct
from core import translators as tr
from core.backends import mic_pactl
from core import micgroups


class _Libre(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Libre.seen.append(body)
        out = json.dumps({"translatedText": f"[{body['target']}] {body['q']}"})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out.encode())

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Libre)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_libre_example_with_placeholders(server):
    snip = ct.LIBRE_EXAMPLE.replace("http://localhost:5000", server)
    out = ct.translate(snip, "", 'Hallo "Welt"', "de", "en")
    assert out == '[en] Hallo "Welt"'


def test_pasted_doc_example_without_placeholders(server):
    snip = (f"curl -X POST -H 'Content-Type: application/json' "
            f"-d '{{\"q\": \"Hello!\", \"source\": \"en\", \"target\": \"es\"}}' "
            f"{server}/translate")
    assert ct.translate(snip, "", "Guten Tag", "de", "fr") == "[fr] Guten Tag"
    assert _Libre.seen[-1]["source"] == "de"


def test_command_line_translator(tmp_path):
    script = tmp_path / "t.py"
    script.write_text("import sys; print(sys.argv[2].upper() + '-' + sys.argv[1])")
    snip = f'"{sys.executable}" "{script}" {{target}} {{text}}'
    assert ct.translate(snip, "", "hallo", "de", "en") == "HALLO-en"


def test_python_file(tmp_path):
    f = tmp_path / "my.py"
    f.write_text("def translate(text, source, target):\n"
                 "    return f'{source}>{target}:{text}'\n")
    assert ct.translate("", str(f), "x", "de", "en") == "de>en:x"


def test_translator_class_reports_errors():
    t = tr.get_translator(tr.METHOD_CUSTOM, custom_snippet="")
    assert t.translate("x", "de", "en") is None
    assert t.last_error.startswith("Custom:")


def test_response_path():
    body = json.dumps({"a": {"b": [{"c": "ok"}]}})
    assert ct.extract_answer(body, "a.b[0].c") == "ok"


def test_monitor_env_targets_sink():
    env = mic_pactl.env_for("alsa_output.usb-headset.analog-stereo.monitor")
    assert env["PIPEWIRE_NODE"] == "alsa_output.usb-headset.analog-stereo"
    assert "capture.sink" in env["PIPEWIRE_PROPS"]
    assert env["PULSE_SOURCE"].endswith(".monitor")


def test_monitor_prefers_pulse_pcm():
    devices = [("pipewire", 5), ("pulse", 7)]
    assert micgroups.pick_server(devices)[1] == 5
    assert micgroups.pick_server(devices, monitor=True)[1] == 7


def test_2way_placeholders_resolve():
    from core.textutils import apply_template, canonical_placeholder
    assert canonical_placeholder("2wayin") == "twoway_input"
    assert canonical_placeholder("2wayout") == "twoway_output"
    out = apply_template("Them: {2wayout} ({2wayin})",
                         {"twoway_input": "Hello", "twoway_output": "Hallo"})
    assert out == "Them: Hallo (Hello)"
