"""
core/translators.py – modular translation backends for OSC-DreamChatbox

Four selectable methods, all behind ONE unified interface:

    translator.translate(text, source_lang, target_lang) -> str | None

1. LingvaTranslator  (DEFAULT) – anonymous Lingva-Translate proxy
   (e.g. https://lingva.adminforge.de). No API key, plain HTTP GET,
   shields the user from direct Google tracking.
2. GoogleTranslator  (direct/fast) – the un-anonymised Google
   Translate web endpoint for minimal latency. No key; the request
   goes straight to Google (tracking possible – user's choice).
3. LibreTranslator   (optional/local) – a locally running
   LibreTranslate instance (default http://localhost:5000) for 100%
   offline translation on the user's own machine
   (install manually: pip install libretranslate).
4. DeepLTranslator   (optional/power user) – official DeepL API via
   the `deepl` Python library (raw-HTTP fallback if the library is
   not installed). Clean error handling for quota/auth problems.

`translate_with_fallback()` picks the configured method and – if it
fails for any reason – automatically retries with Lingva (primary
fallback) and then with direct Google (secondary fallback), so
speech-to-text keeps working even when DeepL hits its monthly limit
or the local LibreTranslate instance is down. Every backend swallows
its exceptions and returns None instead of crashing the app.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

# official DeepL library (pip install deepl) – optional
try:
    import deepl as _deepl
    HAS_DEEPL_LIB = True
except ImportError:
    HAS_DEEPL_LIB = False

# method ids used in config / UI dropdown
METHOD_LINGVA = "lingva"
METHOD_GOOGLE = "google"
METHOD_LIBRE = "libre"
METHOD_DEEPL = "deepl"

METHODS = [
    ("Lingva Translate (anonymous proxy, no key)", METHOD_LINGVA),
    ("Google Translate (direct / fastest, no key)", METHOD_GOOGLE),
    ("LibreTranslate (local instance, offline)", METHOD_LIBRE),
    ("DeepL API (best quality, own API key)", METHOD_DEEPL),
]

DEFAULT_LINGVA_URL = "https://lingva.adminforge.de"
DEFAULT_LIBRE_URL = "http://127.0.0.1:5000"

_TIMEOUT = 8


def _lang_base(code: str) -> str:
    """'zh-CN' -> 'zh', 'en-US' -> 'en' (Lingva/Libre use base codes)."""
    return (code or "").split("-")[0].lower()


# ----------------------------------------------------------------------------
# unified interface
# ----------------------------------------------------------------------------
class Translator:
    """Base class – every backend implements translate() and returns
    the translated text or None on ANY failure (never raises)."""

    name = "base"

    def translate(self, text: str, source_lang: str,
                  target_lang: str) -> str | None:
        raise NotImplementedError

    # human-readable reason of the last failure (for logging/UI)
    last_error = ""


# ----------------------------------------------------------------------------
# 1) Lingva Translate – anonymous proxy (default)
# ----------------------------------------------------------------------------
class LingvaTranslator(Translator):
    """GET {instance}/api/v1/{source}/{target}/{urlencoded text}
    -> {"translation": "..."}   source may be "auto"."""

    name = "Lingva"

    def __init__(self, instance_url: str = DEFAULT_LINGVA_URL):
        self.instance_url = (instance_url or
                             DEFAULT_LINGVA_URL).rstrip("/")

    def translate(self, text, source_lang, target_lang):
        self.last_error = ""
        try:
            src = _lang_base(source_lang) or "auto"
            tgt = _lang_base(target_lang)
            if not tgt:
                return None
            url = (f"{self.instance_url}/api/v1/{src}/{tgt}/"
                   + urllib.parse.quote(text, safe=""))
            req = urllib.request.Request(
                url, headers={"User-Agent": "OSC-DreamChatbox"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            out = (data.get("translation") or "").strip()
            return out or None
        except Exception as e:
            self.last_error = f"Lingva: {e}"
            return None


# ----------------------------------------------------------------------------
# 2) Google Translate – direct web endpoint (fastest, un-anonymised)
# ----------------------------------------------------------------------------
class GoogleTranslator(Translator):
    """The classic free gtx endpoint, hit DIRECTLY (no proxy) for
    minimal latency. No API key. Note: the request goes straight to
    Google, so this is the non-private option – the user chooses.
    endpoint is only overridden in tests."""

    name = "Google"
    DEFAULT_ENDPOINT = ("https://translate.googleapis.com"
                        "/translate_a/single")

    def __init__(self, endpoint: str = ""):
        self.endpoint = (endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    def translate(self, text, source_lang, target_lang):
        self.last_error = ""
        try:
            tgt = _lang_base(target_lang)
            if not tgt:
                return None
            src = _lang_base(source_lang) or "auto"
            url = (f"{self.endpoint}?client=gtx&dt=t"
                   f"&sl={urllib.parse.quote(src)}"
                   f"&tl={urllib.parse.quote(tgt)}"
                   "&q=" + urllib.parse.quote(text))
            req = urllib.request.Request(
                url, headers={"User-Agent": "OSC-DreamChatbox"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            out = "".join(seg[0] for seg in data[0] if seg and seg[0])
            out = out.strip()
            return out or None
        except Exception as e:
            self.last_error = f"Google: {e}"
            return None


# ----------------------------------------------------------------------------
# 3) LibreTranslate – local instance (100% offline)
# ----------------------------------------------------------------------------
class LibreTranslator(Translator):
    """POST {url}/translate  {"q", "source", "target", "format"}
    -> {"translatedText": "..."}   source may be "auto"."""

    name = "LibreTranslate"

    def __init__(self, url: str = DEFAULT_LIBRE_URL, api_key: str = ""):
        url = (url or DEFAULT_LIBRE_URL).strip().rstrip("/")
        if url and "://" not in url:
            url = "http://" + url   # user typed "localhost:5000"
        self.url = url
        self.api_key = api_key or ""

    def _request(self, text, source, target):
        payload = {"q": text, "source": source, "target": target,
                   "format": "text"}
        if self.api_key:
            payload["api_key"] = self.api_key
        req = urllib.request.Request(
            f"{self.url}/translate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "User-Agent": "OSC-DreamChatbox"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data.get("translatedText") or "").strip() or None

    @staticmethod
    def _http_error_text(e) -> str:
        """LibreTranslate answers errors as {"error": "..."} – surface
        the real reason instead of a generic HTTP code."""
        try:
            body = json.loads(e.read().decode("utf-8"))
            msg = body.get("error") or ""
        except Exception:
            msg = ""
        return msg or f"HTTP {e.code}"

    def translate(self, text, source_lang, target_lang):
        self.last_error = ""
        tgt = _lang_base(target_lang)
        if not tgt:
            return None
        src = _lang_base(source_lang) or "auto"
        try:
            return self._request(text, src, tgt)
        except urllib.error.HTTPError as e:
            msg = self._http_error_text(e)
            # explicit source rejected (language pack missing etc.)
            # -> one retry with auto-detect, like the web UI does
            if e.code == 400 and src != "auto":
                try:
                    out = self._request(text, "auto", tgt)
                    if out is not None:
                        return out
                except urllib.error.HTTPError as e2:
                    msg = self._http_error_text(e2)
                except Exception as e2:
                    msg = str(e2)
            self.last_error = f"LibreTranslate: {msg}"
            return None
        except urllib.error.URLError as e:
            self.last_error = (f"LibreTranslate not reachable at "
                               f"{self.url} ({e.reason}) – is the local "
                               "instance running?")
            return None
        except Exception as e:
            self.last_error = f"LibreTranslate: {e}"
            return None


# ----------------------------------------------------------------------------
# 4) DeepL – official API (own key)
# ----------------------------------------------------------------------------
_DEEPL_TARGETS = {"en": "EN-US", "pt": "PT-PT", "zh": "ZH",
                  "zh-cn": "ZH"}


class DeepLTranslator(Translator):
    """Official `deepl` library when installed (clean error types for
    quota/auth), raw-HTTP fallback otherwise. server_url is only used
    for testing against a mock server."""

    name = "DeepL"

    def __init__(self, api_key: str, server_url: str = ""):
        self.api_key = (api_key or "").strip()
        self.server_url = server_url

    def _target(self, target_lang):
        t = (target_lang or "").lower()
        return _DEEPL_TARGETS.get(t, _lang_base(t).upper())

    def translate(self, text, source_lang, target_lang):
        self.last_error = ""
        if not self.api_key:
            self.last_error = "DeepL: no API key configured"
            return None
        if HAS_DEEPL_LIB:
            return self._via_library(text, source_lang, target_lang)
        return self._via_http(text, source_lang, target_lang)

    # ---- official library, with typed error handling ----
    def _via_library(self, text, source_lang, target_lang):
        try:
            kwargs = {}
            if self.server_url:
                kwargs["server_url"] = self.server_url
            client = _deepl.Translator(self.api_key, **kwargs)
            src = _lang_base(source_lang).upper() or None
            result = client.translate_text(
                text, source_lang=src,
                target_lang=self._target(target_lang))
            out = (result.text or "").strip()
            return out or None
        except _deepl.QuotaExceededException:
            self.last_error = ("DeepL: monthly character limit reached "
                               "(quota exceeded)")
            return None
        except _deepl.AuthorizationException:
            self.last_error = "DeepL: invalid API key (authorization failed)"
            return None
        except _deepl.TooManyRequestsException:
            self.last_error = "DeepL: rate limit hit (too many requests)"
            return None
        except _deepl.DeepLException as e:
            self.last_error = f"DeepL: {e}"
            return None
        except Exception as e:
            self.last_error = f"DeepL: {e}"
            return None

    # ---- raw HTTP fallback (no extra dependency needed) ----
    def _via_http(self, text, source_lang, target_lang):
        try:
            key = self.api_key
            host = ("api-free.deepl.com" if key.endswith(":fx")
                    else "api.deepl.com")
            base = self.server_url.rstrip("/") if self.server_url \
                else f"https://{host}"
            params = {"text": text, "target_lang": self._target(target_lang)}
            src = _lang_base(source_lang)
            if src:
                params["source_lang"] = src.upper()
            req = urllib.request.Request(
                f"{base}/v2/translate",
                data=urllib.parse.urlencode(params).encode("utf-8"),
                headers={"Authorization": f"DeepL-Auth-Key {key}",
                         "Content-Type":
                             "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            out = " ".join(t["text"] for t in data.get("translations", []))
            out = out.strip()
            return out or None
        except urllib.error.HTTPError as e:
            if e.code == 456:
                self.last_error = ("DeepL: monthly character limit "
                                   "reached (quota exceeded)")
            elif e.code in (401, 403):
                self.last_error = "DeepL: invalid API key"
            elif e.code == 429:
                self.last_error = "DeepL: rate limit hit"
            else:
                self.last_error = f"DeepL: HTTP {e.code}"
            return None
        except Exception as e:
            self.last_error = f"DeepL: {e}"
            return None


# ----------------------------------------------------------------------------
# factory + fallback chain
# ----------------------------------------------------------------------------
def get_translator(method: str, deepl_key: str = "",
                   libre_url: str = "",
                   lingva_url: str = "",
                   google_endpoint: str = "") -> Translator:
    """Builds the translator for the configured method."""
    if method == METHOD_DEEPL:
        return DeepLTranslator(deepl_key)
    if method == METHOD_LIBRE:
        return LibreTranslator(libre_url or DEFAULT_LIBRE_URL)
    if method == METHOD_GOOGLE:
        return GoogleTranslator(google_endpoint)
    return LingvaTranslator(lingva_url or DEFAULT_LINGVA_URL)


def translate_with_fallback(method, text, source_lang, target_lang,
                            deepl_key="", libre_url="", lingva_url="",
                            google_endpoint="", log=lambda s: None):
    """Translates with the chosen method; on ANY failure the chain
    automatically continues with Lingva (primary fallback) and then
    with direct Google (secondary fallback). Each backend runs at
    most once. Returns the translated text or None if everything
    failed – never raises."""
    chain = [get_translator(method, deepl_key, libre_url, lingva_url,
                            google_endpoint)]
    if method != METHOD_LINGVA:
        chain.append(LingvaTranslator(lingva_url or DEFAULT_LINGVA_URL))
    if method != METHOD_GOOGLE:
        chain.append(GoogleTranslator(google_endpoint))
    for i, tr in enumerate(chain):
        out = tr.translate(text, source_lang, target_lang)
        if out is not None:
            return out
        if tr.last_error:
            log(tr.last_error)
        if i + 1 < len(chain):
            log(f"{tr.name} failed – falling back to "
                f"{chain[i + 1].name}")
    return None


# ----------------------------------------------------------------------------
# LibreTranslate server lifecycle (used by the Start/Stop button)
# ----------------------------------------------------------------------------
class LibreTranslateServer:
    """Manages a locally started LibreTranslate server process.

    start()        launches `libretranslate --port <port>` detached
                   (own process group, output -> libretranslate.log)
    check_ready()  non-blocking probe: HTTP GET /languages until the
                   server answers (first run can take minutes while
                   language models are downloaded)
    stop()         terminates the whole process group in a background
                   thread (SIGTERM, then SIGKILL after 5 s)
    stop_sync()    blocking variant for app shutdown (closeEvent) so
                   no orphaned server keeps running in the background
    """

    def __init__(self, log=lambda s: None):
        self.log = log
        self.proc = None
        self.port = 5000
        self.ready = False
        self.error = ""
        try:
            from core.constants import CONFIG_DIR
            self.log_path = CONFIG_DIR / "libretranslate.log"
        except Exception:
            self.log_path = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, port: int = 5000) -> bool:
        """Launches the server. Returns False (with self.error set)
        if the command is missing or spawning fails. Never raises."""
        if self.running:
            return True
        self.error = ""
        self.ready = False
        self.port = int(port) if port else 5000
        exe = shutil.which("libretranslate")
        argv = ([exe] if exe
                else [sys.executable, "-m", "libretranslate.main"])
        if exe is None and not libretranslate_installed():
            self.error = "libretranslate is not installed"
            return False
        try:
            out = subprocess.DEVNULL
            if self.log_path is not None:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                out = open(self.log_path, "wb")
            self.proc = subprocess.Popen(
                argv + ["--port", str(self.port)],
                stdout=out, stderr=subprocess.STDOUT,
                start_new_session=True)
            self.log(f"LibreTranslate: server starting on port "
                     f"{self.port} (PID {self.proc.pid})")
            return True
        except Exception as e:
            self.error = f"could not start server: {e}"
            self.proc = None
            return False

    def _log_tail(self) -> str:
        try:
            lines = self.log_path.read_text(
                errors="replace").strip().splitlines()
            return lines[-1] if lines else ""
        except Exception:
            return ""

    def check_ready(self) -> bool:
        """One non-blocking readiness probe. Sets self.ready on
        success; sets self.error if the process died. Call this
        periodically (e.g. from a QTimer) while starting."""
        if self.ready:
            return True
        if not self.running:
            if self.proc is not None:
                tail = self._log_tail()
                self.error = ("server exited"
                              + (f": {tail}" if tail else ""))
            return False
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/languages",
                headers={"User-Agent": "OSC-DreamChatbox"})
            with urllib.request.urlopen(req, timeout=1):
                self.ready = True
                self.log(f"LibreTranslate: server ready on port "
                         f"{self.port}")
                return True
        except Exception:
            return False   # still booting / downloading models
        return False

    def _terminate(self, proc):
        try:
            import os
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
                proc.wait(timeout=3)
            self.log("LibreTranslate: server stopped")
        except Exception:
            pass

    def stop(self):
        """Non-blocking stop: terminates the process group in a
        background thread so the UI never freezes."""
        proc, self.proc = self.proc, None
        self.ready = False
        if proc is None or proc.poll() is not None:
            return
        import threading
        threading.Thread(target=self._terminate, args=(proc,),
                         daemon=True).start()

    def stop_sync(self):
        """Blocking stop for app shutdown (closeEvent) – guarantees no
        orphaned server survives the app."""
        proc, self.proc = self.proc, None
        self.ready = False
        if proc is not None and proc.poll() is None:
            self._terminate(proc)



def libretranslate_installed() -> bool:
    """True if LibreTranslate is available – either importable in this
    interpreter or as a command on PATH."""
    if shutil.which("libretranslate"):
        return True
    try:
        return importlib.util.find_spec("libretranslate") is not None
    except Exception:
        return False
