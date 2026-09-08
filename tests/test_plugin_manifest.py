"""
tests/test_plugin_manifest.py - the two manifest keys added for the
store: "about" and "unity".

Three things are worth pinning down.

The **shapes of "about"**, because the whole reason the key exists is
that JSON has no multi-line string: an author may write one, a list of
lines or a dict with a format, and all three have to come out as the
same (text, format) pair. A shape nobody anticipated must end in an
empty string, never in a traceback - a manifest comes off the network.

The **URL filter**, because the value ends up in
QDesktopServices.openUrl(). "https://" is not enough of a check on its
own; "file://", a bare host and a link with whitespace in it each have
to be refused, and refusing them is the entire security story of the
button.

The **fallbacks**, because both keys are additive: a manifest with only
"description" must produce exactly what it produced before, and a
manifest with only "about" must not leave the Installed row blank.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from core.plugins import (
    DEFAULT_ABOUT_FORMAT, PluginManager, http_url, read_about, url_filename)

FOLDER = Path("/tmp/does-not-have-to-exist")


def make(**keys):
    """A minimal valid manifest plus whatever the test is about."""
    data = {"id": "demo", "name": "Demo"}
    data.update(keys)
    return PluginManager._plugin_from_dict(data, FOLDER)


# ------------------------------------------------------------- about
def test_about_string_is_left_alone():
    assert read_about("one line") == ("one line", "text")


def test_about_list_joins_with_newlines():
    text, fmt = read_about(["first", "", "second"])
    assert text == "first\n\nsecond"
    assert fmt == "text"


def test_about_dict_carries_its_format():
    assert read_about({"format": "markdown", "text": "**b**"}) == (
        "**b**", "markdown")


def test_about_dict_text_may_be_a_list():
    text, fmt = read_about({"format": "markdown",
                            "text": ["## Title", "", "- point"]})
    assert text == "## Title\n\n- point"
    assert fmt == "markdown"


def test_unknown_format_falls_back_to_plain_text():
    """Losing the markup is better than losing the text."""
    text, fmt = read_about({"format": "html", "text": "<b>x</b>"})
    assert text == "<b>x</b>"
    assert fmt == DEFAULT_ABOUT_FORMAT


def test_guessed_key_still_shows_up():
    assert read_about({"markdown": "# T"}) == ("# T", "markdown")


def test_junk_about_is_empty_not_an_exception():
    for value in (None, {}, [], 42.0 and {"text": None}, {"text": [{}]}):
        text, fmt = read_about(value)
        assert text == ""
        assert fmt == DEFAULT_ABOUT_FORMAT


def test_non_text_items_in_a_list_are_skipped():
    """A stray dict is an author's typo. Its repr on the store page
    would be worse than the missing line."""
    assert read_about(["ok", {"nope": 1}, "fine"])[0] == "ok\nfine"


# -------------------------------------------------------------- unity
def test_plain_https_link_survives():
    url = "https://github.com/x/y/releases/download/v1/OSCLeash.prefab"
    assert http_url(url) == url


def test_local_and_script_urls_are_refused():
    for url in ("file:///etc/passwd", "javascript:alert(1)",
                "smb://share/x.prefab", "data:text/html,<b>"):
        assert http_url(url) == ""


def test_a_bare_host_is_not_upgraded():
    """Plugin.github_url prepends https:// to 'github.com/user'. This
    one must not: the same helper would happily 'fix' file:///etc."""
    assert http_url("github.com/x/y") == ""


def test_url_needs_a_host():
    assert http_url("https://") == ""
    assert http_url("https:///only/a/path") == ""


def test_whitespace_and_control_characters_are_refused():
    assert http_url("https://host/a file.prefab") == ""
    assert http_url("https://host/a\nb") == ""


def test_scheme_comparison_ignores_case():
    assert http_url("HTTPS://host/x.unitypackage")


def test_filename_for_the_tooltip():
    assert url_filename("https://h/a/b/OSCLeash.prefab") == "OSCLeash.prefab"
    assert url_filename("https://h/x.unitypackage?dl=1") == "x.unitypackage"


def test_filename_of_a_bare_host_is_empty():
    """'host' is not a file name and would read like one."""
    assert url_filename("https://host") == ""
    assert url_filename("https://host/") == ""


# ---------------------------------------------------------- manifests
def test_manifest_without_the_new_keys_is_unchanged():
    plugin = make(description="the old single string")
    assert plugin.description == "the old single string"
    assert plugin.about == ""
    assert plugin.long_text == "the old single string"
    assert plugin.long_format == "text"
    assert plugin.unity == ""
    assert plugin.unity_name == ""


def test_about_becomes_the_long_text_and_description_stays():
    plugin = make(description="short and plain",
                  about={"format": "markdown", "text": "# Long"})
    assert plugin.description == "short and plain"
    assert plugin.long_text == "# Long"
    assert plugin.long_format == "markdown"


def test_about_fills_in_for_a_missing_description():
    """Otherwise the Installed row and its tooltip would be blank."""
    plugin = make(about=["line one", "line two"])
    assert plugin.description == "line one\nline two"
    assert plugin.summary == "line one\nline two"


def test_a_plain_description_is_never_treated_as_markdown():
    """Every manifest predating the key would lose its * and _."""
    plugin = make(description="rate 5*3 and file_name_here")
    assert plugin.long_format == "text"


def test_bad_unity_link_is_dropped_not_kept():
    assert make(unity="file:///home/me/x.prefab").unity == ""


def test_good_unity_link_reaches_the_plugin():
    plugin = make(unity="https://example.org/pack/Leash.prefab")
    assert plugin.unity == "https://example.org/pack/Leash.prefab"
    assert plugin.unity_name == "Leash.prefab"


def test_new_keys_no_longer_land_in_extra():
    """extra is for keys this build does not know. Both are known now,
    and leaving them there would mean writing them out twice."""
    plugin = make(about="x", unity="https://h/y.prefab")
    assert "about" not in plugin.extra
    assert "unity" not in plugin.extra
