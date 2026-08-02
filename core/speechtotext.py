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
import queue
import threading
from contextlib import contextmanager

from core.osinfo import IS_WINDOWS
from core.translators import (METHOD_LINGVA,
                              translate_with_fallback)


@contextmanager
def _silence_stderr():
    """Suppresses the ALSA/JACK error spam that PyAudio prints to stderr
    when opening the microphone.

    Linux only: that spam comes from ALSA, which Windows does not have,
    and in a windowed .exe file descriptor 2 may not be a real handle at
    all - redirecting it there would hide genuine errors for no gain.
    """
    if IS_WINDOWS:
        yield
        return
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
    from core import pyextras
    pyextras.activate()      # no-op when the folder does not exist
except Exception:
    pyextras = None

try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False


def has_sr():
    """Live check. HAS_SR is a module constant, so anything that imported
    it by value would keep reporting the state from startup and never
    notice the in-app installer."""
    return HAS_SR


def reload_sr():
    """Re-attempts the import after the in-app installer ran, so Speech
    to Text becomes usable without restarting the app."""
    global sr, HAS_SR
    try:
        import importlib
        importlib.invalidate_caches()
        import speech_recognition as _sr
        sr = _sr
        HAS_SR = True
    except Exception:
        HAS_SR = False
    return HAS_SR

# SpeechRecognition imports fine WITHOUT pyaudio - it only needs it the
# moment you touch sr.Microphone. Checking HAS_SR alone therefore reports
# "available" on a system where the microphone can never open, which ends
# in an empty device list and a Start button that does nothing.
import importlib.util
try:
    # presence check only - importing pyaudio here would print ALSA noise
    HAS_PYAUDIO = importlib.util.find_spec("pyaudio") is not None
except Exception:      # a broken install can raise instead of returning None
    HAS_PYAUDIO = False

# Second microphone driver: sounddevice wraps the same PortAudio through
# CFFI instead of a compiled extension, so it installs on Python versions
# PyAudio has no wheels for (3.13, 3.14, ...). PyAudio still wins when it
# is there, which keeps every existing Linux install on its usual path.
from core.backends import mic_sounddevice


def has_sounddevice():
    """Probed lazily - see mic_sounddevice.available() for why a plain
    find_spec() would report a driver that cannot actually open."""
    return mic_sounddevice.available()


def reload_mic_driver():
    """Re-probe after the in-app installer ran, so a freshly installed
    driver becomes usable without restarting the app - the same reason
    reload_sr() exists."""
    global HAS_PYAUDIO
    try:
        import importlib
        importlib.invalidate_caches()
        HAS_PYAUDIO = importlib.util.find_spec("pyaudio") is not None
    except Exception:
        HAS_PYAUDIO = False
    mic_sounddevice._PROBE = None      # drop the cached probe result
    return mic_driver()


def mic_driver():
    """'pyaudio' | 'sounddevice' | '' - which one will actually be used."""
    if HAS_PYAUDIO:
        return "pyaudio"
    if has_sounddevice():
        return "sounddevice"
    return ""


def has_microphone_driver():
    return bool(mic_driver())


def missing_dependency():
    """What exactly is missing, as a sentence the user can act on."""
    if not HAS_SR:
        # On Arch the only package is the AUR one, and that currently
        # fails to build - so point at the in-app installer instead of a
        # command line that may not work.
        return ("SpeechRecognition is not installed \u2013 use the "
                "\u201cInstall SpeechRecognition\u201d button below.")
    if not has_microphone_driver():
        if IS_WINDOWS:
            # PyAudio has no wheels beyond CPython 3.13, so naming it
            # first would send people into a source build that needs
            # Visual Studio. sounddevice is a plain wheel on every 3.x.
            return ("No microphone driver - run:  pip install sounddevice "
                    "(works on every Python version; PyAudio has no "
                    "wheels for 3.13+)")
        return ("pyaudio is missing - without it no microphone can be "
                "opened. Arch: sudo pacman -S python-pyaudio  |  "
                "Debian/Mint: sudo apt install portaudio19-dev && "
                "./venv/bin/pip install pyaudio  |  or simply: "
                "pip install sounddevice")
    return ""

def list_microphones(log=None):
    """[(name, device_index)] of available input devices, for the UI
    dropdown. Empty list when SpeechRecognition/pyaudio is missing.

    The reason is logged rather than swallowed - an empty dropdown that
    only ever says "System default" is otherwise indistinguishable from
    a machine that genuinely has one microphone.
    """
    if not HAS_SR or not has_microphone_driver():
        if callable(log):
            log(f"Speech to Text: {missing_dependency()}")
        return []
    if HAS_PYAUDIO:
        try:
            with _silence_stderr():
                names = sr.Microphone.list_microphone_names()
            return [(n, i) for i, n in enumerate(names) if n]
        except Exception as e:
            if callable(log):
                log(f"Speech to Text: microphones could not be listed ({e})")
            return []
    return mic_sounddevice.list_devices(log)


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
        self.google_key = ""  # optional Google Cloud Translation key
        self.mic_index = -1   # -1 = system default microphone

    @staticmethod
    def available():
        """Both parts have to be there: SpeechRecognition for the
        recognition and a microphone driver (pyaudio or sounddevice) to
        open the input device at all."""
        return HAS_SR and has_microphone_driver()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, language, translate_to="", method=METHOD_LINGVA,
              deepl_key="", libre_url="", mic_index=-1,
              google_key=""):
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
        self.google_key = google_key or ""
        self.mic_index = mic_index if mic_index is not None else -1
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
                if HAS_PYAUDIO:
                    mic = (sr.Microphone(device_index=self.mic_index)
                           if self.mic_index >= 0 else sr.Microphone())
                else:
                    mic = mic_sounddevice.make_microphone(sr, self.mic_index)
        except Exception as e:
            if IS_WINDOWS:
                self.messages.put((
                    "error",
                    f"Microphone not available ({e}). Check Windows "
                    "Settings \u203a Privacy & security \u203a Microphone: "
                    "\u201cLet desktop apps access your microphone\u201d has "
                    "to be on, otherwise the device opens but stays "
                    "silent. If no driver is installed at all:  "
                    "pip install sounddevice"))
            else:
                self.messages.put((
                    "error",
                    f"Microphone not available ({e}). NOTE: the app runs "
                    "inside its own venv \u2013 a pacman/system install of "
                    "pyaudio is NOT visible there. Install it into the "
                    "venv instead:  ./venv/bin/pip install pyaudio  "
                    "(needs portaudio: pacman -S portaudio)."))
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
                                    google_key=self.google_key,
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
                            # emit (source, final) so the UI can show both
                            self.messages.put(("text", (text, out)))
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
