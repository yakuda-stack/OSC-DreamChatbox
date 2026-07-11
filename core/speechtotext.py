"""
speechtotext.py – speech to text for OSC-DreamChatbox

Translation uses the modular four-tier system in core/translators.py
(Lingva proxy = default, direct Google endpoint for lowest latency,
local LibreTranslate, DeepL API). If the chosen method fails, the
chain falls back to Lingva first and then to direct Google.

Uses the SpeechRecognition library (Google Web Speech API) with your
microphone. Runs in a background thread and pushes recognized phrases
into a queue that the UI polls.

Requires:
    pip install SpeechRecognition pyaudio
    (Arch: sudo pacman -S python-pyaudio   or:  portaudio + pip install pyaudio)
"""

import os
import json
import queue
import threading
from contextlib import contextmanager

from core.translators import (METHOD_LINGVA,
                              translate_with_fallback)


@contextmanager
def _silence_stderr():
    """Suppresses the ALSA/JACK error spam that PyAudio prints to stderr
    when opening the microphone."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        os.dup2(devnull, 2)
    except Exception:
        yield
        return
    try:
        yield
    finally:
        try:
            os.dup2(old_stderr, 2)
            os.close(devnull)
            os.close(old_stderr)
        except Exception:
            pass

try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False

LANGUAGES = [
    ("German", "de-DE"),
    ("English (US)", "en-US"),
    ("English (UK)", "en-GB"),
    ("French", "fr-FR"),
    ("Spanish", "es-ES"),
    ("Italian", "it-IT"),
    ("Portuguese", "pt-PT"),
    ("Portuguese (BR)", "pt-BR"),
    ("Dutch", "nl-NL"),
    ("Polish", "pl-PL"),
    ("Russian", "ru-RU"),
    ("Turkish", "tr-TR"),
    ("Japanese", "ja-JP"),
    ("Korean", "ko-KR"),
    ("Chinese (Mandarin)", "zh-CN"),
]


OUTPUT_LANGUAGES = [
    ("Same as spoken (no translation)", ""),
    ("English", "en"),
    ("German", "de"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Dutch", "nl"),
    ("Polish", "pl"),
    ("Russian", "ru"),
    ("Turkish", "tr"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("Chinese", "zh-CN"),
]


class SpeechWorker:
    """Background microphone -> text worker.
    Messages arrive in self.messages as (kind, payload):
      kind = "status" | "text" | "error" | "stopped"
    """

    def __init__(self):
        self.messages = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self.language = "en-US"
        self.translate_to = ""  # e.g. "en" - empty = no translation
        self.method = METHOD_LINGVA   # "lingva" | "libre" | "deepl"
        self.deepl_key = ""
        self.libre_url = ""

    @staticmethod
    def available():
        return HAS_SR

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, language, translate_to="", method=METHOD_LINGVA,
              deepl_key="", libre_url=""):
        # make sure a previous recording thread is fully stopped first
        # (otherwise restarting after a language change silently fails)
        if self.running:
            self._stop.set()
            self._thread.join(timeout=6)
        # drain leftover messages from the previous session
        while not self.messages.empty():
            try:
                self.messages.get_nowait()
            except Exception:
                break
        self.language = language
        self.translate_to = translate_to or ""
        self.method = method or METHOD_LINGVA
        self.deepl_key = deepl_key or ""
        self.libre_url = libre_url or ""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------ loop
    def _run(self):
        if not HAS_SR:
            self.messages.put(("error", "SpeechRecognition is not installed."))
            return
        try:
            with _silence_stderr():
                r = sr.Recognizer()
                r.dynamic_energy_threshold = True
                mic = sr.Microphone()
        except Exception as e:
            self.messages.put(("error",
                               f"Microphone not available ({e}). "
                               "Install pyaudio (Arch: pacman -S python-pyaudio)."))
            return
        try:
            with _silence_stderr(), mic as source:
                r.adjust_for_ambient_noise(source, duration=0.4)
                self.messages.put(("status", "Listening \u2026 speak now"))
                while not self._stop.is_set():
                    try:
                        audio = r.listen(source, timeout=1, phrase_time_limit=12)
                    except sr.WaitTimeoutError:
                        continue
                    if self._stop.is_set():
                        break
                    self.messages.put(("status", "Transcribing \u2026"))
                    try:
                        text = r.recognize_google(audio, language=self.language)
                        text = text.strip()
                        if text:
                            out = text
                            tgt = self.translate_to
                            if tgt and not self.language.lower().startswith(
                                    tgt.lower().split("-")[0]):
                                self.messages.put(("status", "Translating \u2026"))
                                tr = translate_with_fallback(
                                    self.method, text,
                                    self.language, tgt,
                                    deepl_key=self.deepl_key,
                                    libre_url=self.libre_url,
                                    log=lambda m: self.messages.put(
                                        ("status", m)))
                                if tr:
                                    self.messages.put(
                                        ("status", f'\"{text}\" \u2192 \"{tr}\"'))
                                    out = tr
                                else:
                                    self.messages.put(
                                        ("status", "Translation failed \u2013 "
                                                   "sending original"))
                            self.messages.put(("text", out))
                        self.messages.put(("status", "Listening \u2026"))
                    except sr.UnknownValueError:
                        self.messages.put(("status",
                                           "Didn't catch that \u2013 listening \u2026"))
                    except sr.RequestError as e:
                        self.messages.put(("error", f"Speech API error: {e}"))
                        break
        except Exception as e:
            self.messages.put(("error", f"Recording error: {e}"))
        finally:
            self.messages.put(("stopped", ""))
