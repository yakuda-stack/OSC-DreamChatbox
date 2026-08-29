"""
core/lyrics.py – synced lyrics for OSC-DreamChatbox

LRCLIB (https://lrclib.net) is an open, key-less database of .lrc
files with exact timestamps.

Matching strategy (many platform titles differ from the "canonical"
song name – "(Official Video)", "feat. XY", third-party uploads,
"Artist - Topic" channels, remaster tags ...), so we run a chain of
lookups from strict to fuzzy:

    1. /api/get  with the raw artist + title (+ duration)
    2. /api/get  with CLEANED artist + title (+ duration)
    3. /api/search  "cleaned artist  cleaned title"  -> best hit
    4. /api/search  cleaned title only               -> best hit

Search hits are scored, never taken blindly:
    - the hit must have syncedLyrics
    - the normalized titles must be PREFIX-compatible (one must start
      with the other) – so "Blinding Lights (Official Video)" matches
      "Blinding Lights", but a totally different song never does
    - if we know the song duration, the hit must be within ±10 s
    - matching artist and closer duration raise the score

Performance rules:
  - NOTHING happens unless the UI asks (the "Lyrics" checkbox gates
    every call, so unchecked = zero network traffic).
  - one fetch chain per song, in a daemon thread, results are cached
    (including negative results, so unknown songs are not re-queried
    on every poll tick).
  - current_line() itself is pure in-memory work and safe to call
    every second from the media poll.

LRCLIB is the first place we look and the one this chain was built
around. When it comes back empty the additional sources in
core/lyrics_sources.py are tried in turn - LyricsPlus, Better Lyrics,
Paxsenix, KuGou, Musixmatch - each one gated by its own checkbox, each
one only ever contacted after everything above it found nothing. A song
LRCLIB knows therefore costs exactly what it always did.

No extra dependencies – urllib only.
"""

import json
import os
import re
import threading
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from core.lyrics_sources import FETCHERS, normalize_sources, source_label

API_GET = "https://lrclib.net/api/get"
API_SEARCH = "https://lrclib.net/api/search"

# LRCLIB asks clients to identify themselves via User-Agent
USER_AGENT = ("OSC-DreamChatbox "
              "(https://github.com/yakuda-stack/OSC-DreamChatbox)")

LYRIC_MAX_LEN = 60          # keep chatbox lines short (144-char limit)
DURATION_TOLERANCE = 10     # seconds – third-party uploads differ a bit
MIN_PREFIX_LEN = 4          # normalized title prefix must be this long

_TS = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")

# noise commonly appended to titles on YouTube/Spotify/uploads –
# bracketed segments containing one of these words are stripped
_NOISE_WORDS = (
    "official", "video", "audio", "lyric", "lyrics", "visualizer",
    "visualiser", "hd", "4k", "hq", "mv", "m/v", "remaster",
    "remastered", "explicit", "clean", "radio edit", "album version",
    "single version", "official music video", "color coded",
    "sub espa\u00f1ol", "legendado", "topic",
)
_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_FEAT = re.compile(r"\b(feat\.?|ft\.?|featuring)\b.*$", re.IGNORECASE)
_DASH_TAIL = re.compile(
    r"\s[-\u2013|]\s*(" + "|".join(re.escape(w) for w in _NOISE_WORDS)
    + r")[^-\u2013|]*$", re.IGNORECASE)


def _parse_lrc(text):
    """'[mm:ss.xx] line' -> sorted [(seconds, line), ...].
    Handles multiple timestamps per line; skips empty lines."""
    out = []
    for raw in (text or "").splitlines():
        stamps = _TS.findall(raw)
        if not stamps:
            continue
        line = _TS.sub("", raw).strip()
        if not line:
            continue
        if len(line) > LYRIC_MAX_LEN:
            line = line[:LYRIC_MAX_LEN - 1] + "\u2026"
        for m, s in stamps:
            out.append((int(m) * 60 + float(s), line))
    out.sort(key=lambda x: x[0])
    return out


# ------------------------------------------------------------- normalizing
def _norm(s):
    """Lowercase, strip accents/punctuation, collapse whitespace –
    the comparison form for titles and artists."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\u0400-\u04ff\u3040-\u30ff\u4e00-\u9fff ]+",
               " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_title(title):
    """Removes platform noise from a title:
    'Song (Official Video) [4K] feat. XY - Remastered' -> 'Song'."""
    t = title or ""

    def drop_noisy(m):
        inner = m.group(0).lower()
        return "" if any(w in inner for w in _NOISE_WORDS) or \
            _FEAT.search(inner) else m.group(0)

    t = _BRACKETS.sub(drop_noisy, t)
    t = _DASH_TAIL.sub("", t)
    t = _FEAT.sub("", t)
    return re.sub(r"\s+", " ", t).strip(" -\u2013|") or (title or "")


def clean_artist(artist):
    """First/primary artist only: 'A feat. B', 'A, B', 'A - Topic'
    -> 'A'. Deliberately does NOT split on '&' or 'x' (band names)."""
    a = artist or ""
    a = re.sub(r"\s*-\s*topic\s*$", "", a, flags=re.IGNORECASE)
    a = _FEAT.sub("", a)
    a = a.split(",")[0]
    return re.sub(r"\s+", " ", a).strip() or (artist or "")


def _prefix_match(a, b):
    """True when the normalized titles agree at the START – one must
    be a prefix of the other (min. MIN_PREFIX_LEN chars)."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) < MIN_PREFIX_LEN and short != long_:
        return False
    return long_.startswith(short)


def _score_hit(hit, artist, title, length):
    """Scores a /api/search hit. Returns -1 = reject, else a score
    (higher = better)."""
    if not hit.get("syncedLyrics"):
        return -1
    h_title = hit.get("trackName") or hit.get("name") or ""
    h_artist = hit.get("artistName") or ""
    h_dur = hit.get("duration") or 0
    # the title START must match (raw or cleaned form)
    if not (_prefix_match(h_title, title)
            or _prefix_match(clean_title(h_title), clean_title(title))):
        return -1
    score = 1.0
    # duration check: hard reject outside the tolerance window
    if length > 0 and h_dur > 0:
        diff = abs(h_dur - length)
        if diff > DURATION_TOLERANCE:
            return -1
        score += 2.0 * (1.0 - diff / DURATION_TOLERANCE)
    # artist agreement (prefix works for 'A feat. B' vs 'A')
    if _prefix_match(clean_artist(h_artist), clean_artist(artist)) \
            or _norm(clean_artist(artist)) in _norm(h_artist):
        score += 2.0
    # exact normalized title beats prefix-only
    if _norm(clean_title(h_title)) == _norm(clean_title(title)):
        score += 1.0
    return score


class _SourceContext:
    """What one of the extra sources needs to do its job.

    The matching helpers are handed over rather than imported on the
    other side, so core/lyrics_sources.py stays a leaf module: it knows
    how to talk to six web services and nothing about how this app
    decides that two song titles are the same.
    """

    def __init__(self, artist, title, length, album=""):
        self.artist = artist
        self.title = title
        self.length = int(length or 0)
        self.album = album or ""
        self.clean_artist = clean_artist(artist)
        self.clean_title = clean_title(title)
        self.tolerance = DURATION_TOLERANCE

    def score(self, hit_title, hit_artist, hit_duration):
        """Same scoring the LRCLIB search hits go through, so a hit from
        Apple Music is held to the title-prefix and duration rules the
        rest of this module already enforces."""
        return _score_hit({"trackName": hit_title,
                           "artistName": hit_artist,
                           "duration": hit_duration},
                          self.artist, self.title, self.length)


class LyricsFetcher:
    """Per-song lyrics cache with background fetching.

    Usage (from the UI thread):
        lyr = fetcher.current_line(artist, title, length, position)
    Returns the lyric line for the current position, or None while
    fetching / when no synced lyrics exist for the song.
    """

    def __init__(self, log_fn=print):
        self.log = log_fn
        self._lock = threading.Lock()
        self._cache = {}      # key -> [(sec, line), ...]  ([] = none found)
        self._pending = set()
        # local .lrc files (your own lyrics, offline, take priority)
        self._local_enabled = False
        self._local_dir = None
        # which web sources may be asked, in lookup order
        self._sources = normalize_sources(None)

    # ---------------------------------------------------------- local .lrc
    def set_local(self, enabled: bool, folder: str | None):
        """Enable/point the local .lrc lookup. Clears the cache so songs
        are re-resolved with the new setting on the next poll."""
        d = None
        if folder:
            p = Path(folder).expanduser()
            d = p if p.is_dir() else None
        changed = (bool(enabled) != self._local_enabled
                   or d != self._local_dir)
        self._local_enabled = bool(enabled)
        self._local_dir = d
        if changed:
            with self._lock:
                self._cache.clear()
                self._pending.clear()

    # -------------------------------------------------------- web sources
    def set_sources(self, sources):
        """Which of the lyrics services may be contacted, in order.

        Clears the cache when it changes, including the negative
        entries: the whole point of switching a source on is to re-ask
        for the songs that came back empty, and a cached "not found"
        would silently make the new checkbox do nothing until the next
        restart.
        """
        new = normalize_sources(sources)
        if new != self._sources:
            self._sources = new
            with self._lock:
                self._cache.clear()
                self._pending.clear()

    def _try_extra_sources(self, artist, title, length):
        """Everything after LRCLIB, in order, first synced hit wins.

        One source failing must never take the chain down with it -
        these are six independent third-party services and at any given
        moment one of them is having a bad day.
        """
        ctx = _SourceContext(artist, title, length)
        for sid in self._sources:
            fetch = FETCHERS.get(sid)
            if fetch is None:      # 'lrclib' is handled above, not here
                continue
            try:
                got = fetch(ctx)
            except Exception as e:
                self.log(f"Lyrics: {source_label(sid)} failed \u2013 {e}")
                continue
            if not got:
                continue
            lrc, got_artist, got_title = got
            lines = _parse_lrc(lrc)
            if lines:
                return lines, got_artist, got_title, source_label(sid)
        return None

    def _read_local(self, artist, title):
        """Returns raw .lrc text of the best local file match, or None.
        Filenames may be 'Artist - Title.lrc', 'Title.lrc',
        'Artist_Title.lrc' … – matched on the normalized form."""
        folder = self._local_dir
        if not folder:
            return None
        t_title = _norm(clean_title(title))
        t_artist = _norm(clean_artist(artist))
        if len(t_title) < MIN_PREFIX_LEN:
            return None
        best_path, best_score = None, 0
        try:
            names = os.listdir(folder)
        except Exception:
            return None
        for name in names:
            if not name.lower().endswith(".lrc"):
                continue
            stem = _norm(name[:-4])
            if not stem:
                continue
            score = 0
            if stem == f"{t_artist} {t_title}".strip() \
                    or stem == f"{t_title} {t_artist}".strip():
                score = 4
            elif stem == t_title:
                score = 3
            elif t_title in stem and (not t_artist or t_artist in stem):
                score = 2
            elif t_title in stem and not t_artist:
                score = 1
            if score > best_score:
                best_score, best_path = score, folder / name
        if not best_path:
            return None
        try:
            return best_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

    @staticmethod
    def _key(artist, title, length):
        return ((artist or "").strip().lower(),
                (title or "").strip().lower(),
                int(length or 0))

    # ---------------------------------------------------------------- fetch
    def prefetch(self, artist, title, length):
        """Starts a background fetch for the song (no-op if already
        cached or in flight)."""
        if not (title or "").strip():
            return
        key = self._key(artist, title, length)
        with self._lock:
            if key in self._cache or key in self._pending:
                return
            self._pending.add(key)
        threading.Thread(target=self._fetch, daemon=True,
                         args=(key, artist or "", title or "",
                               int(length or 0))).start()

    def _http_json(self, url, params):
        full = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(full,
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read().decode("utf-8"))

    # ------------------------------------------------ fetch chain (thread)
    def _try_get(self, artist, title, length):
        """/api/get – exact lookup, with and without duration."""
        for with_dur in (True, False):
            try:
                params = {"artist_name": artist, "track_name": title}
                if with_dur:
                    if length <= 0:
                        continue
                    params["duration"] = length
                data = self._http_json(API_GET, params)
                if data and data.get("syncedLyrics"):
                    # /api/get without duration may return a different
                    # version of the song – keep the tolerance check
                    d = data.get("duration") or 0
                    if (not with_dur and length > 0 and d > 0
                            and abs(d - length) > DURATION_TOLERANCE):
                        continue
                    return data
            except Exception:
                pass
        return None

    def _try_search(self, query, artist, title, length):
        """/api/search – fuzzy lookup, best scored hit or None."""
        try:
            hits = self._http_json(API_SEARCH, {"q": query}) or []
        except Exception:
            return None
        best, best_score = None, 0.0
        for h in hits[:20]:
            s = _score_hit(h, artist, title, length)
            if s > best_score:
                best, best_score = h, s
        return best

    def _fetch(self, key, artist, title, length):
        lines = []
        c_artist, c_title = clean_artist(artist), clean_title(title)
        try:
            # 0) local .lrc file – your own lyrics, offline, take priority
            if self._local_enabled:
                local = self._read_local(artist, title)
                if local:
                    lines = _parse_lrc(local)
                    if lines:
                        self.log(f"Lyrics: {len(lines)} synced lines for "
                                 f"\"{artist} \u2013 {title}\" "
                                 "(local .lrc file)")
                        with self._lock:
                            self._cache[key] = lines
                            self._pending.discard(key)
                        return
            # 1) exact – raw metadata  (LRCLIB, first because this whole
            #    matching chain was built around its two endpoints)
            data = None
            if "lrclib" in self._sources:
                data = self._try_get(artist, title, length)
                # 2) exact – cleaned metadata (skip if identical)
                if not data and (c_artist, c_title) != (artist, title):
                    data = self._try_get(c_artist, c_title, length)
                # 3) fuzzy search: cleaned artist + title
                if not data:
                    q = f"{c_artist} {c_title}".strip()
                    data = self._try_search(q, artist, title, length)
                # 4) fuzzy search: title only (catches wrong/'Various
                #    Artists'/uploader-as-artist metadata)
                if not data and c_title:
                    data = self._try_search(c_title, artist, title, length)

            source = "LRCLIB"
            got_a, got_t = c_artist, c_title
            if data and data.get("syncedLyrics"):
                lines = _parse_lrc(data["syncedLyrics"])
                got_t = data.get("trackName") or c_title
                got_a = data.get("artistName") or c_artist
            if not lines:
                # 5) everything LRCLIB does not have: the extra sources,
                #    in order, first synced hit wins
                found = self._try_extra_sources(artist, title, length)
                if found:
                    lines, got_a, got_t, source = found
            if lines:
                self.log(f"Lyrics: {len(lines)} synced lines for "
                         f"\"{artist} – {title}\" "
                         f"(matched \"{got_a} – {got_t}\", {source})")
            else:
                tried = ", ".join(source_label(s) for s in self._sources)
                self.log(f"Lyrics: no synced lyrics found for "
                         f"\"{artist} – {title}\" "
                         f"(also tried \"{c_artist} – {c_title}\"; "
                         f"sources: {tried or 'none enabled'})")
        except Exception as e:
            self.log(f"Lyrics: lookup failed for \"{title}\": {e}")
        finally:
            with self._lock:
                self._cache[key] = lines      # [] = negative cache
                self._pending.discard(key)

    # --------------------------------------------------------------- lookup
    def current_line(self, artist, title, length, position):
        """Lyric line at `position` seconds, or None. Triggers a
        background fetch on the first call for a new song."""
        key = self._key(artist, title, length)
        with self._lock:
            lines = self._cache.get(key)
        if lines is None:
            self.prefetch(artist, title, length)
            return None
        if not lines:
            return None
        # last line whose timestamp is <= position (small linear scan,
        # lists are a few hundred entries at most)
        current = None
        for ts, line in lines:
            if ts <= position:
                current = line
            else:
                break
        return current
