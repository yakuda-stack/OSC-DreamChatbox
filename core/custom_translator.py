"""
core/custom_translator.py - "Custom" translation service

For people who run a translator the app does not know about. What they
paste (or the file they pick) can be one of three things:

1. a curl command - the form every API documentation shows, e.g. the
   LibreTranslate one:

       curl -X POST -H "Content-Type: application/json" \\
            -d '{"q": "{text}", "source": "{source}", "target": "{target}"}' \\
            http://localhost:5000/translate

   It is NOT run through a shell; it is parsed and sent with urllib, so
   it works on Windows too. Placeholders: {text} {source} {target}.
   A pasted doc example WITHOUT placeholders works as well: in a JSON
   body the usual keys (q/text, source/from, target/to ...) are filled
   in automatically.

2. any other command line - an installed CLI translator, e.g.

       argos-translate --from {source} --to {target} {text}

   Run directly (no shell), placeholders substituted per argument. When
   no argument contains {text}, the text is fed on stdin. Whatever the
   command prints is the translation.

3. a Python file (.py) defining  translate(text, source, target) -> str.

The answer of an HTTP call is searched for the translation in the usual
places (translatedText, translation, text, translations[0].text, ...).
A comment line "# response: path.to[0].field" names it explicitly.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 15

#: pasted from the LibreTranslate docs, with placeholders filled in
LIBRE_EXAMPLE = (
    "# Example: a LibreTranslate server (local or hosted).\n"
    "# {text} {source} {target} are filled in by the app.\n"
    "curl -X POST -H \"Content-Type: application/json\" \\\n"
    "  -d '{\"q\": \"{text}\", \"source\": \"{source}\", "
    "\"target\": \"{target}\", \"format\": \"text\"}' \\\n"
    "  http://localhost:5000/translate\n")

_TEXT_KEYS = ("q", "text", "query", "input", "content")
_SRC_KEYS = ("source", "source_lang", "sourceLang", "from", "sl", "src")
_TGT_KEYS = ("target", "target_lang", "targetLang", "to", "tl", "tgt")
_ANSWER_PATHS = ("translatedText", "translation", "translated_text",
                 "translated", "result", "text", "output",
                 "translations.0.text", "translations.0.translatedText",
                 "data.translations.0.translatedText", "data.translation",
                 "0.translatedText", "0.text")


class CustomError(Exception):
    pass


# ---------------------------------------------------------------- parsing
def _clean(snippet: str):
    """Comment lines out, backslash-continuations joined. Returns
    (command string, response path or '')."""
    resp = ""
    lines = []
    for ln in (snippet or "").replace("\r\n", "\n").split("\n"):
        st = ln.strip()
        if st.startswith("#"):
            m = re.match(r"#\s*response\s*:\s*(\S+)", st, re.I)
            if m:
                resp = m.group(1)
            continue
        lines.append(ln)
    cmd = "\n".join(lines)
    # "\<newline>" (bash) and "^<newline>" (cmd.exe) continuations
    cmd = re.sub(r"[\\^]\s*\n", " ", cmd)
    return " ".join(cmd.split("\n")).strip(), resp


def _fill(value: str, text, src, tgt, enc=None):
    enc = enc or (lambda v: v)
    return (value.replace("{text}", enc(text))
                 .replace("{source}", enc(src))
                 .replace("{target}", enc(tgt)))


def parse_curl(cmd: str) -> dict:
    """curl command line -> {method, url, headers, data, get}."""
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        raise CustomError(f"could not read the curl command ({e})")
    if not argv or Path(argv[0]).name.lower() not in ("curl", "curl.exe"):
        raise CustomError("not a curl command")
    out = {"method": "", "url": "", "headers": {}, "data": [], "get": False}
    takes_value = {"-o", "--output", "-m", "--max-time",
                   "--connect-timeout", "-A", "--user-agent", "-e",
                   "--referer", "-u", "--user", "-b", "--cookie",
                   "-w", "--write-out"}
    i = 1
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        if a in ("-X", "--request"):
            out["method"] = nxt.upper()
            i += 2
            continue
        if a in ("-H", "--header"):
            if ":" in nxt:
                k, v = nxt.split(":", 1)
                out["headers"][k.strip()] = v.strip()
            i += 2
            continue
        if a in ("-d", "--data", "--data-raw", "--data-binary",
                 "--data-ascii", "--data-urlencode", "--json"):
            out["data"].append(nxt)
            if a == "--json":
                out["headers"].setdefault("Content-Type",
                                          "application/json")
            i += 2
            continue
        if a == "--url":
            out["url"] = nxt
            i += 2
            continue
        if a in ("-G", "--get"):
            out["get"] = True
            i += 1
            continue
        if a in ("-A", "--user-agent"):
            out["headers"]["User-Agent"] = nxt
            i += 2
            continue
        if a in takes_value:
            i += 2
            continue
        if a.startswith("-"):
            i += 1          # -s, -S, -L, -k, --compressed, -i ...
            continue
        if not out["url"]:
            out["url"] = a
        i += 1
    if not out["url"]:
        raise CustomError("the curl command has no URL")
    if "://" not in out["url"]:
        out["url"] = "http://" + out["url"]
    if not out["method"]:
        out["method"] = "POST" if out["data"] and not out["get"] else "GET"
    return out


def _json_fill(obj, text, src, tgt):
    """Doc examples without placeholders: fill the well-known keys."""
    if isinstance(obj, dict):
        for k in list(obj):
            if k in _TEXT_KEYS and isinstance(obj[k], (str, list)):
                obj[k] = [text] if isinstance(obj[k], list) else text
            elif k in _SRC_KEYS and isinstance(obj[k], str):
                obj[k] = src
            elif k in _TGT_KEYS and isinstance(obj[k], str):
                obj[k] = tgt
            else:
                _json_fill(obj[k], text, src, tgt)
    elif isinstance(obj, list):
        for v in obj:
            _json_fill(v, text, src, tgt)
    return obj


def _dig(data, path):
    cur = data
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def extract_answer(body: str, path: str = ""):
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip() or None      # plain-text API
    if isinstance(data, str):
        return data.strip() or None
    for p in ([path.replace("[", ".").replace("]", "")] if path
              else _ANSWER_PATHS):
        v = _dig(data, p)
        if isinstance(v, list) and v and isinstance(v[0], str):
            v = " ".join(v)
        if isinstance(v, str) and v.strip():
            return v.strip()
    if isinstance(data, dict) and data.get("error"):
        raise CustomError(str(data["error"]))
    raise CustomError("answer has no recognisable translation field - add "
                      "a line  # response: <field>  to the snippet")


# -------------------------------------------------------------- running
def _run_curl(cmd, resp_path, text, src, tgt):
    spec = parse_curl(cmd)
    url_has_ph = any(p in spec["url"] for p in ("{text}", "{source}",
                                                "{target}"))
    url = _fill(spec["url"], text, src, tgt, urllib.parse.quote)
    headers = {k: _fill(v, text, src, tgt)
               for k, v in spec["headers"].items()}
    headers.setdefault("User-Agent", "OSC-DreamChatbox")
    body = None
    if spec["data"]:
        raw = "&".join(spec["data"])
        ctype = headers.get("Content-Type", "").lower()
        is_json = "json" in ctype or raw.lstrip().startswith(("{", "["))
        has_ph = any(p in raw for p in ("{text}", "{source}", "{target}"))
        if is_json:
            if has_ph:
                # JSON-escape the values, without the surrounding quotes
                enc = lambda v: json.dumps(v)[1:-1]  # noqa: E731
                raw = _fill(raw, text, src, tgt, enc)
            else:
                try:
                    raw = json.dumps(_json_fill(json.loads(raw), text,
                                                src, tgt))
                except ValueError:
                    pass
            headers.setdefault("Content-Type", "application/json")
        else:
            raw = _fill(raw, text, src, tgt, urllib.parse.quote_plus)
            headers.setdefault("Content-Type",
                               "application/x-www-form-urlencoded")
        if spec["get"]:
            url += ("&" if "?" in url else "?") + raw
        else:
            body = raw.encode("utf-8")
    elif not url_has_ph and spec["method"] == "GET":
        raise CustomError("the command sends neither {text} nor a body")
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method=spec["method"])
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            answer = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:      # noqa: BLE001
            detail = ""
        raise CustomError(f"HTTP {e.code} {detail}".strip())
    except urllib.error.URLError as e:
        raise CustomError(f"{spec['url']} not reachable ({e.reason})")
    return extract_answer(answer, resp_path)


def _run_command(cmd, text, src, tgt):
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        raise CustomError(f"could not read the command ({e})")
    if not argv:
        raise CustomError("the snippet is empty")
    uses_text = any("{text}" in a for a in argv)
    argv = [_fill(a, text, src, tgt) for a in argv]
    from core.osinfo import subprocess_flags
    try:
        res = subprocess.run(argv, input=None if uses_text else text,
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=TIMEOUT, **subprocess_flags())
    except FileNotFoundError:
        raise CustomError(f"command not found: {argv[0]}")
    except subprocess.TimeoutExpired:
        raise CustomError(f"{argv[0]} took longer than {TIMEOUT} s")
    if res.returncode != 0:
        err = (res.stderr or "").strip().splitlines()
        raise CustomError(f"{argv[0]} exited with {res.returncode}"
                          + (f": {err[-1]}" if err else ""))
    out = (res.stdout or "").strip()
    return out or None


def _run_python(path, text, src, tgt):
    spec = importlib.util.spec_from_file_location("dc_custom_translator",
                                                  str(path))
    if spec is None or spec.loader is None:
        raise CustomError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "translate", None)
    if not callable(fn):
        raise CustomError(f"{Path(path).name} has no translate(text, "
                          "source, target) function")
    out = fn(text, src, tgt)
    return str(out).strip() if out else None


def translate(snippet: str, file_path: str, text: str, src: str,
              tgt: str):
    """The one entry point. Raises CustomError with a readable reason."""
    file_path = (file_path or "").strip()
    if file_path:
        p = Path(file_path).expanduser()
        if not p.is_file():
            raise CustomError(f"file not found: {p}")
        if p.suffix.lower() == ".py":
            return _run_python(p, text, src, tgt)
        snippet = p.read_text(encoding="utf-8", errors="replace")
    cmd, resp = _clean(snippet)
    if not cmd:
        raise CustomError("no command set - paste one or choose a file")
    first = cmd.split(None, 1)[0].strip("'\"")
    if Path(first).name.lower() in ("curl", "curl.exe"):
        return _run_curl(cmd, resp, text, src, tgt)
    return _run_command(cmd, text, src, tgt)
