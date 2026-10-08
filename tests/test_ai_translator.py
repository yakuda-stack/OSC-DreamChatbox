"""
tests/test_ai_translator.py - v1.6.5: AI translation + favorite services.

No network and no real AI: urlopen and the CLI run are faked, the
Custom AI test runs a tiny Python command instead.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import shlex
import sys

import core.ai_translator as ai
import core.translators as tr


def test_ai_services_are_in_the_dropdown():
    ids = [m for _l, m in tr.METHODS]
    for m in ai.AI_METHODS:
        assert m in ids
    assert len(ids) == len(set(ids))


def test_get_translator_builds_ai_translator():
    t = tr.get_translator(ai.METHOD_CLAUDE)
    assert isinstance(t, tr.AITranslator)
    assert t.name == "Claude Code"


def test_prompt_names_the_languages():
    p = ai.make_prompt("hallo", "de-DE", "en")
    assert "from German into English" in p
    assert p.rstrip().endswith("hallo")
    # two-way: source "" = auto-detect, no "from"
    assert "from" not in ai.make_prompt("x", "", "ja").split("\n")[0]


def test_clean_answer():
    assert ai.clean_answer('"Hello there"') == "Hello there"
    assert ai.clean_answer("<think>hm</think>\nHi") == "Hi"
    assert ai.clean_answer("\x1b[32mHi\x1b[0m") == "Hi"


def test_model_falls_back_to_default():
    ai.use_config({"stt_ai_claude_model": ""})
    assert ai.model_of(ai.METHOD_CLAUDE) == "haiku"
    ai.use_config({"stt_ai_claude_model": "sonnet"})
    assert ai.model_of(ai.METHOD_CLAUDE) == "sonnet"
    ai.use_config({})


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_request(monkeypatch):
    seen = {}

    def fake(req, timeout=0):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        return _Resp(json.dumps({"response": " Hello! "}).encode())
    monkeypatch.setattr(ai.urllib.request, "urlopen", fake)
    ai.use_config({"stt_ai_ollama_model": "qwen3:4b"})
    out = tr.get_translator(ai.METHOD_OLLAMA).translate("Hallo!", "de", "en")
    ai.use_config({})
    assert out == "Hello!"
    assert seen["url"].endswith("/api/generate")
    assert seen["body"]["model"] == "qwen3:4b"


def test_ai_failure_falls_back(monkeypatch):
    def boom(*a, **k):
        raise ai.AIError("not logged in")
    monkeypatch.setattr(ai, "translate", boom)
    # v1.6.6: chain is AI -> adminForge (LibreOnline) -> Google; no
    # network in tests, so adminForge has to fail here too
    monkeypatch.setattr(tr.LibreOnlineTranslator, "translate",
                        lambda self, *a: None)
    monkeypatch.setattr(tr.GoogleTranslator, "translate",
                        lambda self, *a: "fallback")
    logs = []
    out = tr.translate_with_fallback(ai.METHOD_GEMINI, "hallo", "de", "en",
                                     log=logs.append)
    assert out == "fallback"
    assert any("not logged in" in m for m in logs)


def test_cli_command_shapes():
    argv, stdin = ai.build_command(ai.METHOD_CLAUDE, "P", "haiku")
    assert argv == ["claude", "-p", "P", "--model", "haiku"] and stdin is None
    argv, stdin = ai.build_command(ai.METHOD_CHATGPT, "P", "gpt-5.6-luna")
    assert argv[-1] == "-" and stdin == "P"
    argv, _ = ai.build_command(ai.METHOD_GEMINI, "P", "flash")
    assert "--output-format" in argv


def test_custom_ai_command():
    # prints the prompt's last line upper-cased - stands in for an AI
    code = "import sys; print(sys.argv[1].splitlines()[-1].upper())"
    ai.use_config({"stt_ai_custom_cmd":
                   f"{shlex.quote(sys.executable)} -c "
                   f"{shlex.quote(code)} {{prompt}}"})
    out = tr.get_translator(ai.METHOD_AI_CUSTOM).translate("hallo", "de",
                                                            "en")
    ai.use_config({})
    assert out == "HALLO"


def _load(raw):
    from ui.config_mixin import ConfigMixin
    mix = ConfigMixin.__new__(ConfigMixin)
    return mix.load_config(raw)


def test_config_defaults_and_favorites():
    cfg = _load({})
    assert cfg["stt_tr_favorites"] == []
    assert cfg["stt_ai_ollama_model"] == ai.DEFAULTS["stt_ai_ollama_model"]
    cfg = _load({"stt_tr_favorites": ["deepl", 5, "deepl", "ai_claude"],
                 "stt_ai_claude_model": 3})
    assert cfg["stt_tr_favorites"] == ["deepl", "ai_claude"]
    assert cfg["stt_ai_claude_model"] == "haiku"
