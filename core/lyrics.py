"""
core/lyrics.py – synced lyrics for OSC-DreamChatbox (via LRCLIB)

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

No extra dependencies – urllib only.
"""

import json
import re
import threading
import unicodedata
import urllib.parse
import urllib.request

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
            # 1) exact – raw metadata
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

            if data and data.get("syncedLyrics"):
                lines = _parse_lrc(data["syncedLyrics"])
            if lines:
                got_t = data.get("trackName") or c_title
                got_a = data.get("artistName") or c_artist
                self.log(f"Lyrics: {len(lines)} synced lines for "
                         f"\"{artist} – {title}\" "
                         f"(matched \"{got_a} – {got_t}\", LRCLIB)")
            else:
                self.log(f"Lyrics: no synced lyrics found for "
                         f"\"{artist} – {title}\" "
                         f"(also tried \"{c_artist} – {c_title}\")")
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
