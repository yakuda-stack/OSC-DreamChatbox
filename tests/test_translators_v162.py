"""
tests/test_translators_v162.py - translation fixes from v1.6.2.

lingva.adminforge.de now redirects to a LibreTranslate web page, every
public Lingva instance returns the text untranslated, and Google's
keyless endpoint rate-limits. No network here: urlopen is faked.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import urllib.error

import pytest

import core.translators as tr


class FakeResp(io.BytesIO):
    def __init__(self, body, url="https://x/"):
        super().__init__(body.encode("utf-8"))
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(monkeypatch, handler):
    monkeypatch.setattr(tr.urllib.request, "urlopen",
                        lambda req, timeout=0: handler(req.full_url))


@pytest.mark.parametrize("text, out, src, tgt, expected", [
    ("good morning my friend", "good morning my friend", "en", "zh", True),
    ("Good Morning", "good morning", "auto", "de", True),
    ("ok", "ok", "en", "de", False),                 # too short to judge
    ("VRChat", "VRChat", "en", "de", True),
    ("hello there", "hallo", "en", "de", False),
    ("hello there", "hello there", "en", "en", False),  # same language
])
def test_untranslated(text, out, src, tgt, expected):
    assert tr._untranslated(text, out, src, tgt) is expected


def test_lingva_untranslated_is_a_failure(monkeypatch):
    fake_urlopen(monkeypatch, lambda url: FakeResp(json.dumps(
        {"translation": "good morning my friend"})))
    t = tr.LingvaTranslator()
    assert t.translate("good morning my friend", "en-US", "zh-CN") is None
    assert "untranslated" in t.last_error


def test_lingva_web_page_is_named(monkeypatch):
    fake_urlopen(monkeypatch, lambda url: FakeResp(
        "<html>LibreTranslate</html>", "https://translate.adminforge.de/"))
    t = tr.LingvaTranslator("https://lingva.adminforge.de")
    assert t.translate("hello there", "en", "de") is None
    assert "no longer a Lingva server" in t.last_error
    assert "translate.adminforge.de" in t.last_error


def test_lingva_default_is_not_adminforge():
    assert "adminforge" not in tr.DEFAULT_LINGVA_URL


def test_google_429_uses_second_endpoint(monkeypatch):
    def handler(url):
        if url.startswith(tr.GoogleTranslator.DEFAULT_ENDPOINT):
            raise urllib.error.HTTPError(url, 429, "Too Many", {}, None)
        assert url.startswith(tr.GoogleTranslator.ALT_ENDPOINT)
        return FakeResp('["早上好"]')
    fake_urlopen(monkeypatch, handler)
    assert tr.GoogleTranslator().translate("good morning", "en",
                                           "zh-CN") == "早上好"


@pytest.mark.parametrize("data, out", [
    (["Guten Morgen"], "Guten Morgen"),
    ([["Guten Morgen", "en"]], "Guten Morgen"),
    ([], None), ("x", None),
])
def test_google_alt_parse(data, out):
    assert tr.GoogleTranslator._parse_alt(data) == out


def test_new_keyless_servers_listed():
    urls = [v for _l, v in tr.LIBRE_ONLINE_SERVERS]
    assert tr.ADMINFORGE_LIBRE_URL in urls
    assert tr.PYRINE_LIBRE_URL in urls


def test_lingva_not_in_fallback_chain(monkeypatch):
    """v1.6.6: chosen -> adminForge -> Google, Lingva is skipped."""
    tried = []

    def fake(self, text, s, t):
        tried.append(type(self).__name__)
        return None
    for cls in (tr.LingvaTranslator, tr.GoogleTranslator,
                tr.LibreOnlineTranslator, tr.DeepLTranslator):
        monkeypatch.setattr(cls, "translate", fake)
    assert tr.translate_with_fallback(tr.METHOD_DEEPL, "hi there",
                                      "en", "de") is None
    assert tried == ["DeepLTranslator", "LibreOnlineTranslator",
                     "GoogleTranslator"]


def test_adminforge_is_first_fallback(monkeypatch):
    tried = []

    def fake(self, text, s, t):
        tried.append(type(self).__name__)
        if isinstance(self, tr.LibreOnlineTranslator):
            return "ok"
        return None
    for cls in (tr.LingvaTranslator, tr.GoogleTranslator):
        monkeypatch.setattr(cls, "translate", fake)
    monkeypatch.setattr(tr.LibreOnlineTranslator, "translate", fake)
    out = tr.translate_with_fallback(tr.METHOD_LINGVA, "hi there",
                                     "en", "de")
    assert out == "ok"
    # Lingva picked by hand still runs, then adminForge
    assert tried == ["LingvaTranslator", "LibreOnlineTranslator"]


# ---- default + one-time migration ---------------------------------------
def _load(raw):
    from ui.config_mixin import ConfigMixin
    mix = ConfigMixin.__new__(ConfigMixin)
    return mix.load_config(raw)


def test_new_config_defaults_to_adminforge():
    cfg = _load({})
    assert cfg["stt_method"] == tr.METHOD_LIBRE_ONLINE
    assert cfg["stt_libre_online_url"] == tr.ADMINFORGE_LIBRE_URL


def test_old_lingva_config_is_moved_once():
    cfg = _load({"stt_method": "lingva", "stt_libre_online_url": ""})
    assert cfg["stt_method"] == tr.METHOD_LIBRE_ONLINE
    assert cfg["stt_libre_online_url"] == tr.ADMINFORGE_LIBRE_URL
    assert cfg["stt_migrated_v162"] is True
    # picked Lingva again later: stays Lingva
    again = _load(dict(cfg, stt_method="lingva"))
    assert again["stt_method"] == "lingva"


def test_other_choices_are_left_alone():
    cfg = _load({"stt_method": "google", "stt_libre_online_url": ""})
    assert cfg["stt_method"] == "google"
    assert cfg["stt_libre_online_url"] == ""
