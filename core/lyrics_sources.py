"""
core/lyrics_sources.py – where synced lyrics can come from.

LRCLIB alone misses a lot: anything released in the last few weeks,
anything with a non-Latin title, and most of what plays through YouTube
with a third-party upload's metadata. This module adds five more places
to look, all reachable without an API key.

    lrclib        lrclib.net                     open database, no key
    lyricsplus    lyricsplus.binimum.org (+2)    aggregator, no key
    betterlyrics  lyrics-api.boidu.dev           TTML, word timings
    paxsenix      lyrics.paxsenix.org            Apple Music catalogue
    kugou         lyrics.kugou.com               huge CJK catalogue
    musixmatch    apic-desktop.musixmatch.com    guest token, unofficial

The endpoints were taken from Meld (github.com/FrancescoGrazioso/Meld,
GPL-3.0), which is where this list comes from in the first place.

**They are tried in order and the first synced result wins.** A source
that is switched off costs nothing, and a source further down the list
is only ever contacted when everything above it came back empty - so
the common case (LRCLIB knows the song) is exactly as fast and as quiet
as it was before this module existed.

Two of them are worth knowing about before switching them on:

  * **Musixmatch** talks to the desktop app's private API with a guest
    token. It works, and it is the same data Spotify shows, but it is
    not a published interface: it rate-limits, and it can stop working
    without notice. Off by default for that reason, not a legal one.
  * **KuGou** is a Chinese service whose catalogue is enormous for CJK
    music and thin for everything else. Off by default because for most
    users here it would only add a round trip to every lookup that
    failed everywhere else.

Everything here is stdlib only - urllib, json, base64, ElementTree - so
nothing new has to be installed and the AppImage does not grow.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import base64
import json
import re
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = ("OSC-DreamChatbox "
              "(https://github.com/yakuda-stack/OSC-DreamChatbox)")
# Musixmatch's desktop endpoint rejects anything that does not look like
# a browser, so that one call gets a browser string instead.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/122.0.0.0 Safari/537.36")

TIMEOUT = 8


# --------------------------------------------------------------- http
def http_json(url, params=None, headers=None, timeout=TIMEOUT):
    """GET + parse JSON. Raises on anything that goes wrong - every
    caller is already inside a try, and a source that fails has to fall
    through to the next one rather than return a half-answer."""
    if params:
        clean = {k: v for k, v in params.items()
                 if v is not None and v != ""}
        url = url + "?" + urllib.parse.urlencode(clean)
    head = {"User-Agent": USER_AGENT}
    head.update(headers or {})
    req = urllib.request.Request(url, headers=head)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------- lrc
def _lrc_stamp(ms):
    """Milliseconds -> '[mm:ss.cc]'. Centiseconds, because that is what
    an .lrc timestamp holds and the parser on the other side reads."""
    ms = max(0, int(ms))
    return f"[{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000 // 10:02d}]"


def lines_to_lrc(pairs):
    """[(milliseconds, text), ...] -> .lrc text.

    Empty lines are dropped rather than written with a timestamp: in the
    chatbox an empty lyric line reads as the song having stopped, so a
    gap is better shown by simply leaving the previous line up.
    """
    out = [f"{_lrc_stamp(ms)}{text.strip()}"
           for ms, text in pairs if (text or "").strip()]
    return "\n".join(out)


_TTML_CLOCK = re.compile(
    r"^(?:(\d+):)?(\d+):(\d+(?:[.,]\d+)?)$")     # [hh:]mm:ss[.fff]
_TTML_OFFSET = re.compile(r"^(\d+(?:[.,]\d+)?)(ms|s|m|h)$")


def _ttml_time(value):
    """A TTML begin= attribute -> milliseconds, or None.

    TTML allows both clock time ('00:01:23.450') and offset time
    ('83.45s', '1200ms'). Both turn up in the wild from these APIs, so
    both are handled instead of guessing one.
    """
    text = (value or "").strip().replace(",", ".")
    if not text:
        return None
    m = _TTML_CLOCK.match(text)
    if m:
        hours = int(m.group(1) or 0)
        return int((hours * 3600 + int(m.group(2)) * 60
                    + float(m.group(3))) * 1000)
    m = _TTML_OFFSET.match(text)
    if m:
        scale = {"ms": 1, "s": 1000, "m": 60000, "h": 3600000}[m.group(2)]
        return int(float(m.group(1)) * scale)
    return None


def ttml_to_lrc(ttml):
    """TTML (Apple Music's format) -> .lrc text, or "".

    Only the line-level ``<p begin=…>`` timings are kept. Word-level
    ``<span>`` timings inside a line are flattened into the line's text:
    a chatbox shows one line at a time and cannot animate a word, so
    keeping them would mean throwing them away later anyway.
    """
    if not (ttml or "").strip():
        return ""
    try:
        root = ET.fromstring(ttml)
    except ET.ParseError:
        return ""
    pairs = []
    for node in root.iter():
        # tags arrive namespaced ('{http://www.w3.org/ns/ttml}p')
        if node.tag.rsplit("}", 1)[-1] != "p":
            continue
        ms = _ttml_time(node.get("begin"))
        if ms is None:
            continue
        text = " ".join(part.strip()
                        for part in node.itertext() if part.strip())
        if text:
            pairs.append((ms, text))
    pairs.sort(key=lambda p: p[0])
    return lines_to_lrc(pairs)


# ------------------------------------------------------------ sources
def _fetch_lyricsplus(ctx):
    """LyricsPlus - an aggregator that asks Apple, Musixmatch and
    Spotify at once. Several deployments exist and they go up and down,
    so the list is walked until one answers."""
    bases = ("https://lyricsplus.binimum.org",
             "https://lyricsplus.atomix.one",
             "https://lyricsplus-seven.vercel.app")
    params = {
        "title": ctx.title, "artist": ctx.artist,
        "duration": ctx.length if ctx.length > 0 else -1,
        "album": ctx.album or None,
        "source": "apple,lyricsplus,musixmatch,spotify",
    }
    for base in bases:
        try:
            data = http_json(base + "/v2/lyrics/get", params)
        except Exception:
            continue
        rows = (data or {}).get("lyrics") or []
        lrc = lines_to_lrc([(row.get("time") or 0, row.get("text") or "")
                            for row in rows if isinstance(row, dict)])
        if lrc:
            return lrc, ctx.artist, ctx.title
    return None


def _fetch_betterlyrics(ctx):
    """Better Lyrics - returns Apple's TTML, which carries the tightest
    timings of anything in this list."""
    data = http_json("https://lyrics-api.boidu.dev/getLyrics", {
        "s": ctx.title, "a": ctx.artist,
        "d": ctx.length if ctx.length > 0 else None,
        "al": ctx.album or None,
    })
    lrc = ttml_to_lrc((data or {}).get("ttml"))
    return (lrc, ctx.artist, ctx.title) if lrc else None


def _fetch_paxsenix(ctx):
    """Paxsenix - searches Apple Music, then pulls that track's lyrics.

    Two round trips, so the search hits are scored before the second one
    is spent: taking the first result blindly is how you end up with a
    karaoke cover's timings under the original recording.
    """
    base = "https://lyrics.paxsenix.org"
    query = f"{ctx.clean_artist} {ctx.clean_title}".strip()
    hits = http_json(base + "/apple-music/search", {"q": query}) or []
    scored = []
    for hit in hits[:20]:
        if not isinstance(hit, dict):
            continue
        h_title = hit.get("trackName") or hit.get("songName") or ""
        h_artist = hit.get("artistName") or ""
        # Apple reports milliseconds; everything in this app is seconds
        h_dur = int((hit.get("duration") or 0) / 1000)
        score = ctx.score(h_title, h_artist, h_dur)
        if score > 0 and hit.get("id"):
            scored.append((score, hit["id"], h_artist, h_title))
    scored.sort(key=lambda s: s[0], reverse=True)
    for _score, track_id, h_artist, h_title in scored[:3]:
        try:
            data = http_json(base + "/apple-music/lyrics", {"id": track_id})
        except Exception:
            continue
        data = data or {}
        lrc = ttml_to_lrc(data.get("ttmlContent"))
        if not lrc:
            # ELRC is LRC with word timings in angle brackets; the
            # parser on the other side ignores what it does not know,
            # but stripping them here keeps the chatbox line clean
            raw = data.get("elrcMultiPerson") or data.get("elrc") or ""
            lrc = re.sub(r"<[^>]*>", "", raw).strip()
        if lrc:
            return lrc, h_artist, h_title
    return None


def _fetch_kugou(ctx):
    """KuGou - search for a lyrics candidate, then download it.

    The download comes back base64-encoded, and the file starts with a
    block of ``[ti:]`` / ``[ar:]`` / ``[by:]`` metadata lines. Those are
    left in: the .lrc parser skips anything without a timestamp, and
    cutting them here would only be a second place to get it wrong.
    """
    keyword = f"{ctx.clean_title} - {ctx.clean_artist}".strip(" -")
    found = http_json("https://lyrics.kugou.com/search", {
        "ver": 1, "man": "yes", "client": "pc", "keyword": keyword,
        "duration": ctx.length * 1000 if ctx.length > 0 else None,
    })
    candidates = (found or {}).get("candidates") or []
    for cand in candidates[:3]:
        if not isinstance(cand, dict):
            continue
        # KuGou answers in milliseconds
        if (ctx.length > 0 and cand.get("duration")
                and abs(int(cand["duration"]) / 1000
                        - ctx.length) > ctx.tolerance):
            continue
        try:
            got = http_json("https://lyrics.kugou.com/download", {
                "fmt": "lrc", "charset": "utf8", "client": "pc", "ver": 1,
                "id": cand.get("id"), "accesskey": cand.get("accesskey"),
            })
            content = (got or {}).get("content") or ""
            lrc = base64.b64decode(content).decode("utf-8", "replace")
        except Exception:
            continue
        if "[" in lrc:
            return lrc, ctx.artist, ctx.title
    return None


_MXM_BASE = "https://apic-desktop.musixmatch.com/ws/1.1"
_MXM_APP_ID = "web-desktop-app-v1.0"
_mxm_token = None
_mxm_lock = threading.Lock()


def _musixmatch_token():
    """The guest token, fetched once and kept for the process.

    Behind a lock because several songs can be resolved at once and
    every one of them asking for its own token is the fastest way to get
    the whole app rate-limited.
    """
    global _mxm_token
    if _mxm_token:
        return _mxm_token
    with _mxm_lock:
        if _mxm_token:
            return _mxm_token
        data = http_json(_MXM_BASE + "/token.get",
                         {"app_id": _MXM_APP_ID, "format": "json"},
                         {"User-Agent": BROWSER_UA,
                          "Cookie": "AWSELB=0; AWSELBCORS=0"})
        message = (data or {}).get("message") or {}
        if (message.get("header") or {}).get("status_code") != 200:
            return None
        token = (message.get("body") or {}).get("user_token") or ""
        # the API hands out this placeholder instead of an error when it
        # does not feel like issuing a real one
        if not token or token.startswith("UpgradeOnly"):
            return None
        _mxm_token = token
        return token


def _fetch_musixmatch(ctx):
    """Musixmatch - the same source Spotify shows, via the desktop app's
    private API. Synced subtitle first; plain lyrics are not used,
    because an unsynced block cannot be shown line by line anyway."""
    token = _musixmatch_token()
    if not token:
        return None
    data = http_json(_MXM_BASE + "/macro.subtitles.get", {
        "format": "json", "namespace": "lyrics_richsynced",
        "subtitle_format": "lrc", "app_id": _MXM_APP_ID,
        "usertoken": token, "q_track": ctx.title, "q_artist": ctx.artist,
        "q_album": ctx.album or None,
        "q_duration": ctx.length if ctx.length > 0 else None,
        "f_subtitle_length": ctx.length if ctx.length > 0 else None,
    }, {"User-Agent": BROWSER_UA, "Cookie": "AWSELB=0; AWSELBCORS=0"})
    body = ((data or {}).get("message") or {}).get("body") or {}
    calls = body.get("macro_calls") or {}
    subs = (((calls.get("track.subtitles.get") or {}).get("message") or {})
            .get("body") or {}).get("subtitle_list") or []
    for entry in subs:
        text = ((entry or {}).get("subtitle") or {}).get("subtitle_body")
        if (text or "").strip():
            return text, ctx.artist, ctx.title
    return None


#: id -> (label, default_on, one-line description for the tooltip).
#: The order here IS the lookup order.
SOURCES = (
    ("lrclib", "LRCLIB", True,
     ("lrclib.net \u2013 the open, key-less lyrics database. Best "
      "coverage for Western pop and the only one that was here "
      "before.")),
    ("lyricsplus", "LyricsPlus", True,
     ("An aggregator that asks Apple, Musixmatch and Spotify at once. "
      "Good catch-all when LRCLIB has never heard of the song.")),
    ("betterlyrics", "Better Lyrics", True,
     ("lyrics-api.boidu.dev \u2013 serves Apple's TTML, which carries "
      "the tightest timings of anything in this list.")),
    ("paxsenix", "Paxsenix", False,
     ("Searches the Apple Music catalogue, then pulls that track's "
      "lyrics. Two round trips, so it is off by default.")),
    ("kugou", "KuGou", False,
     ("A Chinese service with an enormous CJK catalogue and a thin one "
      "for everything else. Worth switching on if you listen to "
      "Mandarin, Cantonese, Japanese or Korean music.")),
    ("musixmatch", "Musixmatch", False,
     ("The same source Spotify shows, through the desktop app's "
      "private API with a guest token. It works, but it is not a "
      "published interface: it rate-limits and can stop working "
      "without notice.")),
)

#: id -> fetch function. LRCLIB is not in here: it lives in
#: core/lyrics.py, which already has a four-step matching chain built
#: around its two endpoints and would lose more than it gained by being
#: squeezed into the one-shot shape the others share.
FETCHERS = {
    "lyricsplus": _fetch_lyricsplus,
    "betterlyrics": _fetch_betterlyrics,
    "paxsenix": _fetch_paxsenix,
    "kugou": _fetch_kugou,
    "musixmatch": _fetch_musixmatch,
}

SOURCE_IDS = tuple(sid for sid, _l, _d, _b in SOURCES)
DEFAULT_SOURCES = tuple(sid for sid, _l, on, _b in SOURCES if on)


def source_label(sid):
    for source_id, label, _on, _blurb in SOURCES:
        if source_id == sid:
            return label
    return sid


def normalize_sources(value):
    """A stored list -> the ids we actually know, in lookup order.

    Order is taken from SOURCES rather than from the config, so a
    hand-edited or half-migrated list cannot end up asking the slow
    unofficial endpoint first. Anything unknown is dropped.
    """
    if value is None or isinstance(value, (str, bytes)):
        return list(DEFAULT_SOURCES)
    try:
        wanted = {str(v) for v in value}
    except TypeError:
        return list(DEFAULT_SOURCES)
    return [sid for sid in SOURCE_IDS if sid in wanted]
