"""
tests/test_atomicfile.py - write_text_atomic() and pinned store refs.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from core.atomicfile import write_text_atomic
from core.plugin_store import parse_github_url

SHA = "2150604c80dc2f6adbb74749a645ba4d9e8290a0"


def test_writes_and_leaves_no_tmp(tmp_path):
    target = tmp_path / "config.json"
    write_text_atomic(target, '{"a": 1}')
    assert target.read_text(encoding="utf-8") == '{"a": 1}'
    assert list(tmp_path.iterdir()) == [target]


def test_overwrite_keeps_nothing_of_the_old_content(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("x" * 5000, encoding="utf-8")
    write_text_atomic(target, "short")
    assert target.read_text(encoding="utf-8") == "short"


def test_failed_write_keeps_the_old_file(tmp_path):
    # a value json.dumps would never produce, but str(...) of it fails
    class Boom:
        def __str__(self):
            raise ValueError("boom")

    target = tmp_path / "config.json"
    target.write_text("old", encoding="utf-8")
    try:
        write_text_atomic(target, Boom())
    except Exception:
        pass
    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [target]


def test_store_urls_work_for_a_pinned_commit():
    # refs/heads/<ref> would only resolve branches, so pinning a plugin
    # to a commit (or a tag) has to survive this
    src = parse_github_url(f"https://github.com/o/r/tree/{SHA}/Plugin")
    assert src.ref == SHA and src.path == "Plugin"
    assert "refs/heads" not in src.tarball
    assert src.tarball.endswith(f"/tar.gz/{SHA}")
    assert src.raw("plugin.json").endswith(f"/{SHA}/Plugin/plugin.json")
