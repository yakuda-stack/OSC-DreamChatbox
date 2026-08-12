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
import time
from contextlib import contextmanager

from core.osinfo import IS_WINDOWS
from core.translators import (METHOD_LINGVA,
                              translate_with_fallback)


#: File descriptor 2 belongs to the whole PROCESS, not to a thread, so
#: two threads inside _silence_stderr() at the same time will trample
#: each other: the one that leaves first restores its saved descriptor,
#: which is the /dev/null the other one installed - and stderr is gone
#: for the rest of the session. That is not hypothetical here; filling
#: the microphone dropdown and opening the microphone happen on two
#: different threads and both silence stderr.
_STDERR_LOCK = threading.Lock()


@contextmanager
def _silence_stderr():
    """Suppresses the ALSA/JACK error spam that PyAudio prints to stderr
    when opening the microphone.

    Linux only: that spam comes from ALSA, which Windows does not have,
    and in a windowed .exe file descriptor 2 may not be a real handle at
    all - redirecting it there would hide genuine errors for no gain.

    The lock is taken WITHOUT blocking on purpose. If another thread is
    already redirecting - or is parked forever inside a wedged PortAudio
    call while holding it - waiting for it would hand the hang straight
    to this thread as well. Printing some ALSA noise is the cheaper of
    the two outcomes by a wide margin.
    """
    if IS_WINDOWS:
        yield
        return
    if not _STDERR_LOCK.acquire(blocking=False):
        yield
        return
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        os.dup2(devnull, 2)
    except Exception:
        _STDERR_LOCK.release()
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
        _STDERR_LOCK.release()

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
# every blocking PortAudio call in this module goes through here - see
# core/backends/mic_probe.py for why nothing may run unguarded
from core.backends import mic_probe


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

#: Last successful device list. Enumerating PortAudio is the exact call
#: that hangs when a device vanished, so the app keeps the last good
#: answer around: a stale dropdown is far better than a frozen window,
#: and the entry the user picked is still in it.
_DEVICE_CACHE = []
_DEVICE_CACHE_AT = 0.0


def _enumerate_devices(log=None):
    """The raw, BLOCKING enumeration. Never call this directly - go
    through list_microphones(), which wraps it in the timeout guard."""
    if HAS_PYAUDIO:
        with _silence_stderr():
            names = sr.Microphone.list_microphone_names()
        return [(n, i) for i, n in enumerate(names) if n]
    return mic_sounddevice.list_devices(log)


def list_microphones(log=None, timeout=None, force=False):
    """[(name, device_index)] of available input devices, for the UI
    dropdown. Empty list when SpeechRecognition/pyaudio is missing.

    NEVER CALL THIS ON THE GUI THREAD. It is guarded against hanging, but
    a guard still costs up to `timeout` seconds of waiting, and the whole
    point is that the window stays responsive. The Textbox page runs it
    through run_async().

    The reason is logged rather than swallowed - an empty dropdown that
    only ever says "System default" is otherwise indistinguishable from
    a machine that genuinely has one microphone.
    """
    global _DEVICE_CACHE, _DEVICE_CACHE_AT
    if not HAS_SR or not has_microphone_driver():
        if callable(log):
            log(f"Speech to Text: {missing_dependency()}")
        return []
    if force:
        mic_probe.clear_stuck()
    ok, res = mic_probe.guarded(
        lambda: _enumerate_devices(log),
        timeout=timeout or mic_probe.LIST_TIMEOUT,
        label="microphone list", log=log,
        respect_stuck=not force)
    if ok and isinstance(res, list):
        _DEVICE_CACHE = res
        _DEVICE_CACHE_AT = time.time()
        return res
    if callable(log) and not isinstance(res, mic_probe.MicTimeout):
        log(f"Speech to Text: microphones could not be listed ({res})")
    # a stale list still lets the user pick something; an empty one
    # would look like the machine has no microphone at all
    return list(_DEVICE_CACHE)


def cached_microphones():
    """The last successful device list, without touching PortAudio at
    all. Safe to call from the GUI thread."""
    return list(_DEVICE_CACHE)


def driver_stuck():
    """Reason string when a previous PortAudio call never returned."""
    return mic_probe.stuck()


def clear_driver_stuck():
    """Try PortAudio again after a timeout (the \u27F3 Refresh button)."""
    mic_probe.clear_stuck()


def resolve_device(name, log=None, devices=None):
    """Turn a saved microphone NAME into a currently valid device index.

    Returns ``(index, note)``. ``index`` is -1 for the system default and
    None when the saved device is gone; ``note`` is a sentence for the
    user, or "" when everything is in order.

    This is where the "left VR, microphone disappeared" case is caught.
    The old code answered "not found -> use the system default", which is
    the worst possible answer: the default on a machine whose audio graph
    just lost a node is frequently the very device that hangs. Reporting
    the gap and letting the caller refuse to start is what keeps the app
    from walking into the blocking open.
    """
    if not name:
        return -1, ""
    if devices is None:
        devices = list_microphones(log)
    for dev_name, idx in devices:
        if dev_name == name:
            return idx, ""
    return None, (f"The selected microphone \u201c{name}\u201d is not "
                  f"available right now. If you just left VR, its virtual "
                  f"microphone is gone \u2013 pick another device or press "
                  f"\u27F3 Refresh.")


def default_device_note(log=None):
    """"" when PortAudio has a usable default input device, otherwise a
    sentence explaining what is wrong.

    Called before every recording start. `sr.Microphone()` with no index
    asks PortAudio for its default input, and on a Linux box whose audio
    graph lost a node that lookup is one of the calls that blocks - so it
    happens here, inside the guard, rather than unprotected further down.
    """
    if HAS_PYAUDIO:
        def probe():
            with _silence_stderr():
                pa = sr.Microphone.get_pyaudio().PyAudio()
                try:
                    return pa.get_default_input_device_info()
                finally:
                    pa.terminate()
    else:
        def probe():
            return mic_sounddevice.default_device_index()

    ok, res = mic_probe.guarded(
        probe, timeout=mic_probe.LIST_TIMEOUT,
        label="default microphone lookup", log=log)
    if ok and res is not None:
        return ""
    if isinstance(res, mic_probe.MicTimeout):
        return ("The system default microphone did not answer. This "
                "usually means a device disappeared while it was still "
                "registered \u2013 leaving VR does exactly that. Pick a "
                "specific microphone from the list instead of \u201cSystem "
                "default\u201d, or press \u27F3 Refresh once it is back.")
    return (f"No usable system default microphone ({res}). Pick a "
            f"specific device from the list.")


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
        # Every start() opens a new session. The old recording thread can
        # still be sitting inside r.listen() (up to phrase_time_limit
        # seconds) and will emit a "stopped" AFTER the new one began -
        # which the UI reads as "recording ended" and unchecks the button.
        # Messages therefore carry the session they belong to, and a
        # stale session's messages are dropped.
        self._session = 0
        self.language = "en-US"
        self.translate_to = ""  # e.g. "en" - empty = no translation
        # "lingva" | "google" | "libre" | "libre_online" | "deepl"
        self.method = METHOD_LINGVA
        self.deepl_key = ""
        self.libre_url = ""
        self.libre_online_url = ""   # "" = the preset public instance
        self.libre_online_key = ""   # optional, some instances need one
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
              google_key="", libre_online_url="", libre_online_key=""):
        # A previous recording thread has to finish before the new one
        # opens the microphone. It used to be joined RIGHT HERE - on the
        # GUI thread, for up to 6 seconds, because r.listen() only checks
        # the stop flag between phrases. Toggling Speech to Text off and
        # on, or changing the language, froze the window for that long.
        # The wait now happens on the new worker thread instead.
        previous, prev_stop = self._thread, self._stop
        if previous is not None and previous.is_alive():
            prev_stop.set()
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
        self.libre_online_url = libre_online_url or ""
        self.libre_online_key = libre_online_key or ""
        self.google_key = google_key or ""
        self.mic_index = mic_index if mic_index is not None else -1
        # a fresh Event per session: clearing the shared one would also
        # un-stop the thread we just asked to quit
        self._stop = threading.Event()
        self._session += 1
        self._thread = threading.Thread(
            target=self._run, args=(self._stop, self._session, previous),
            daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # -------------------------------------------------------------- errors
    @staticmethod
    def _open_error_text(err):
        """One sentence the user can act on, for every way opening the
        microphone can fail."""
        if isinstance(err, mic_probe.MicTimeout):
            return ("The microphone did not respond and the attempt was "
                    "abandoned. That happens when a device disappears "
                    "while the system still lists it \u2013 leaving VR does "
                    "exactly that to a virtual microphone. Pick a specific "
                    "device from the list instead of \u201cSystem "
                    "default\u201d, then press \u27F3 Refresh.")
        if IS_WINDOWS:
            return (f"Microphone not available ({err}). Check Windows "
                    "Settings \u203a Privacy & security \u203a Microphone: "
                    "\u201cLet desktop apps access your microphone\u201d has "
                    "to be on, otherwise the device opens but stays "
                    "silent. If no driver is installed at all:  "
                    "pip install sounddevice")
        return (f"Microphone not available ({err}). NOTE: the app runs "
                "inside its own venv \u2013 a pacman/system install of "
                "pyaudio is NOT visible there. Install it into the "
                "venv instead:  ./venv/bin/pip install pyaudio  "
                "(needs portaudio: pacman -S portaudio).")

    @staticmethod
    def _close(mic):
        """Closing can block just like opening, so it gets the same guard.
        respect_stuck is off: this is the cleanup path, and refusing to
        even try would leak the stream on every recovered error."""
        mic_probe.guarded(
            lambda: mic.__exit__(None, None, None),
            timeout=mic_probe.OPEN_TIMEOUT, label="microphone close",
            respect_stuck=False)

    # ------------------------------------------------------------------ loop
    def _run(self, stop, session, previous=None):
        def emit(kind, payload):
            """Only the current session may talk to the UI."""
            if session == self._session:
                self.messages.put((kind, payload))

        me = threading.current_thread()

        if previous is not None and previous.is_alive():
            # the blocking wait, moved off the GUI thread. A session the
            # watchdog gave up on is deliberately NOT waited for: that
            # thread is parked inside PortAudio and is never coming back,
            # so joining it would only add 20 dead seconds to the restart.
            if getattr(previous, "dc_stalled", False):
                emit("status", "The previous session is still stuck in the "
                               "audio driver \u2013 starting a new one "
                               "next to it \u2026")
            else:
                previous.join(timeout=20)
        if not HAS_SR:
            emit("error", "SpeechRecognition is not installed.")
            emit("stopped", "")
            return

        # ---- 1. recognizer + microphone object -------------------------
        # sr.Microphone() is not a passive object: its constructor asks
        # PortAudio for the default device and the sample rate. On a
        # machine whose audio graph just lost a node that lookup is one
        # of the calls that never returns, so even this runs guarded.
        def build():
            with _silence_stderr():
                rec = sr.Recognizer()
                rec.dynamic_energy_threshold = True
                if HAS_PYAUDIO:
                    device = (sr.Microphone(device_index=self.mic_index)
                              if self.mic_index >= 0 else sr.Microphone())
                else:
                    device = mic_sounddevice.make_microphone(
                        sr, self.mic_index)
            return rec, device

        ok, res = mic_probe.guarded(
            build, timeout=mic_probe.OPEN_TIMEOUT, label="microphone setup")
        if not ok:
            me.dc_stalled = isinstance(res, mic_probe.MicTimeout)
            emit("error", self._open_error_text(res))
            emit("stopped", "")
            return
        r, mic = res

        # ---- 2. open the stream ----------------------------------------
        def do_open():
            with _silence_stderr():
                return mic.__enter__()

        ok, res = mic_probe.guarded(
            do_open, timeout=mic_probe.OPEN_TIMEOUT, label="microphone open")
        if not ok:
            timed_out = isinstance(res, mic_probe.MicTimeout)
            me.dc_stalled = timed_out
            emit("error", self._open_error_text(res))
            # On a timeout the open is STILL RUNNING in a parked thread.
            # Closing a stream another thread is inside of is how you get
            # a segfault instead of an error message, so leave it alone
            # and let the process reclaim it at exit.
            if not timed_out:
                self._close(mic)
            emit("stopped", "")
            return
        source = res

        # ---- 3. calibrate ----------------------------------------------
        ok, res = mic_probe.guarded(
            lambda: r.adjust_for_ambient_noise(source, duration=0.4),
            timeout=mic_probe.OPEN_TIMEOUT, label="microphone calibration")
        if not ok:
            timed_out = isinstance(res, mic_probe.MicTimeout)
            me.dc_stalled = timed_out
            emit("error", self._open_error_text(res))
            if not timed_out:
                self._close(mic)
            emit("stopped", "")
            return

        # ---- 4. the listen loop, watched --------------------------------
        # A device that dies WHILE recording does not raise - it simply
        # stops delivering audio, and r.listen() sits in a read that never
        # completes. The loop cannot notice that itself (it is the thing
        # that is blocked), so a second thread watches the heartbeat and
        # tells the UI what happened. It cannot free the parked thread,
        # but it turns a silently dead recording into a message and a
        # button that goes back to "Start".
        beat = [time.monotonic()]
        stalled = threading.Event()

        def tick():
            beat[0] = time.monotonic()

        def watchdog():
            while not stop.wait(1.0):
                if stalled.is_set():
                    return
                if time.monotonic() - beat[0] > mic_probe.STALL_TIMEOUT:
                    stalled.set()
                    me.dc_stalled = True
                    mic_probe.mark_stuck(
                        "the microphone stopped delivering audio")
                    emit("error",
                         "The microphone stopped delivering audio and did "
                         "not recover. The device was most likely removed "
                         "while recording \u2013 leaving VR takes its "
                         "virtual microphone with it. Recording was "
                         "stopped; pick another device and press \u27F3 "
                         "Refresh.")
                    emit("stopped", "")
                    return

        threading.Thread(target=watchdog, daemon=True,
                         name="stt-watchdog").start()

        emit("status", "Listening \u2026 speak now")
        try:
            while not stop.is_set() and not stalled.is_set():
                tick()
                try:
                    audio = r.listen(source, timeout=1, phrase_time_limit=12)
                except sr.WaitTimeoutError:
                    continue
                tick()
                if stop.is_set() or stalled.is_set():
                    break
                emit("status", "Transcribing \u2026")
                try:
                    text = r.recognize_google(audio, language=self.language)
                    tick()      # transcription is a network call
                    text = text.strip()
                    if text:
                        out = text
                        tgt = self.translate_to
                        if tgt and not self.language.lower().startswith(
                                tgt.lower().split("-")[0]):
                            emit("status", "Translating \u2026")
                            # its own event, not a status string the UI
                            # would have to pattern-match: the chatbox
                            # notice is a behaviour, and hanging it off
                            # the wording of a label would break the
                            # first time that label is reworded
                            emit("translating", text)
                            tr = translate_with_fallback(
                                self.method, text,
                                self.language, tgt,
                                deepl_key=self.deepl_key,
                                libre_url=self.libre_url,
                                google_key=self.google_key,
                                libre_online_url=self.libre_online_url,
                                libre_online_key=self.libre_online_key,
                                log=lambda m: emit("status", m))
                            tick()  # so is translation
                            if tr:
                                emit("status",
                                     f'\"{text}\" \u2192 \"{tr}\"')
                                out = tr
                            else:
                                emit("status",
                                     "Translation failed \u2013 "
                                     "sending original")
                        # emit (source, final) so the UI can show both
                        emit("text", (text, out))
                    emit("status", "Listening \u2026")
                except sr.UnknownValueError:
                    tick()
                    emit("status",
                         "Didn't catch that \u2013 listening \u2026")
                except sr.RequestError as e:
                    emit("error", f"Speech API error: {e}")
                    break
        except Exception as e:
            if not stalled.is_set():
                emit("error", f"Recording error: {e}")
        finally:
            stop.set()          # retires the watchdog
            if not stalled.is_set():
                self._close(mic)
                emit("stopped", "")
