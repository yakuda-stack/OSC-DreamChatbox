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
# ... and, whenever it can, through a process of its own instead of a
# thread of our own: PortAudio does not raise, it aborts. See
# core/mic_host.py and core/stt_child.py.
from core import mic_host
# What PortAudio calls a device list is a list of ALSA PCMs; what the
# user is looking for is a PipeWire source. These two turn one into the
# other - see core/backends/mic_pactl.py and core/micgroups.py.
from core.backends import mic_pactl
from core import micgroups


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


def microphone_mode():
    """One line for the log: where the microphone is actually opened.

    Worth having in every bug report - "the app crashed when I pressed
    record" and "the helper process crashed" are two very different
    reports, and the answer to which one you are reading is here.
    """
    return mic_host.describe()


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
    through list_microphones(), which wraps it in the timeout guard.

    Only reached when the helper process is unavailable; see
    core/mic_host.py for why enumerating in this process is a hazard
    while a recording is running.
    """
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
    # Preferred path: a helper process does the enumeration. It cannot
    # disturb a recording that is running (Pa_Terminate tears down every
    # stream in ITS OWN process, and that process holds none), and if it
    # wedges it can be killed rather than leaked. See core/mic_host.py.
    if mic_host.available():
        ok, res, answered = mic_host.list_devices(log)
        if ok:
            _DEVICE_CACHE = res
            _DEVICE_CACHE_AT = time.time()
            return res
        if callable(log):
            log(f"Speech to Text: microphones could not be listed ({res})")
        if answered:
            # The helper reached the audio stack and that is where the
            # answer came from. Asking again in THIS process would only
            # repeat the message - or repeat the crash, with the app.
            return list(_DEVICE_CACHE)
        # never got off the ground (no interpreter, spawn refused): fall
        # through so a build that cannot spawn still fills the dropdown
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


#: Last successful pactl source list, for the same reason _DEVICE_CACHE
#: exists: the dropdown should keep showing what it last knew instead of
#: emptying itself while the audio graph is in flux.
_SOURCE_CACHE = []


def list_sources(log=None):
    """The sound server's sources, grouped (see core/backends/mic_pactl.py).

    Cheap and safe: pactl talks over a unix socket and cannot wedge in a
    driver the way PortAudio can. Still not called from the GUI thread,
    because it is a subprocess and the dropdown is already filled
    asynchronously anyway.
    """
    global _SOURCE_CACHE
    try:
        sources = mic_pactl.list_sources(log)
    except Exception as e:      # noqa: BLE001
        if callable(log):
            log(f"Speech to Text: the source list failed ({e}) - using the "
                f"plain device list.")
        return list(_SOURCE_CACHE)
    if sources:
        _SOURCE_CACHE = sources
    return sources


def cached_sources():
    return list(_SOURCE_CACHE)


def list_microphone_groups(log=None, force=False, show_raw=False,
                           selected=""):
    """The whole dropdown, ready to paint: grouped entries with ids.

    NEVER CALL THIS ON THE GUI THREAD - it goes through
    list_microphones(), which is the blocking part.
    """
    devices = list_microphones(log, force=force)
    sources = list_sources(log)
    return micgroups.build(devices, sources=sources, show_raw=show_raw,
                           selected=selected, log=log), devices, sources


def resolve_entry(eid, log=None, devices=None, sources=None):
    """Turn a stored ``stt_mic`` id into ``(index, node, note)``.

    The successor to resolve_device(), which only ever knew about
    PortAudio names. Bare names still work - see core/micgroups.py.
    """
    if devices is None:
        devices = list_microphones(log)
    if sources is None:
        sources = list_sources(log)
    return micgroups.resolve(eid, devices, sources=sources, log=log)


def describe_entry(eid):
    """The friendly name of a stored id, for log lines and labels."""
    return micgroups.label_for_id(eid)


class MicTest:
    """The microphone test: open a device and report how loud it is.

    Its own tiny worker rather than a mode of SpeechWorker, because the
    two have opposite lifetimes - a recording runs for as long as the
    user talks and must survive a bumpy audio graph, while this one is
    started and stopped by a panel opening and closing and must be
    instant and disposable in both directions.

    Messages arrive in ``self.messages`` as (kind, payload):
      "level"  -> (rms, peak, threshold)
      "ready"  -> the source it is actually attached to, or ""
      "error"  -> a sentence for the user
      "stopped"
    """

    def __init__(self):
        self.messages = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._session = None
        self._seq = 0

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, mic_index=-1, node="", threshold=0, log=None):
        self.stop()
        while not self.messages.empty():
            try:
                self.messages.get_nowait()
            except Exception:      # noqa: BLE001
                break
        self._stop = threading.Event()
        self._seq += 1
        self._thread = threading.Thread(
            target=self._run,
            args=(self._stop, self._seq, mic_index, node, threshold, log),
            daemon=True, name="stt-mictest")
        self._thread.start()

    def stop(self):
        self._stop.set()
        sess = self._session
        if sess is not None:
            try:
                sess.stop(grace=0.2)
            except Exception:      # noqa: BLE001
                pass
            self._session = None

    def _run(self, stop, seq, mic_index, node, threshold, log):
        def emit(kind, payload):
            if seq == self._seq:
                self.messages.put((kind, payload))

        if not mic_host.available():
            # No helper means the test would have to open PortAudio in
            # THIS process - the one thing 1.4.1 moved out of it. A
            # missing level bar is a much smaller problem than an app
            # that aborts because somebody opened a settings panel.
            emit("error", "The microphone test needs the helper process, "
                          "which is not available in this build.")
            emit("stopped", "")
            return
        sess = mic_host.LevelSession(mic_index=mic_index, node=node,
                                     threshold=threshold, log=log)
        if not sess.start():
            emit("error", f"The microphone test could not start "
                          f"({sess.error}).")
            emit("stopped", "")
            return
        self._session = sess

        def stopper():
            stop.wait()
            sess.stop(grace=0.2)

        threading.Thread(target=stopper, daemon=True,
                         name="stt-mictest-stop").start()
        try:
            for msg in sess.messages():
                if stop.is_set():
                    break
                kind = str(msg.get("kind") or "")
                if kind == "level":
                    emit("level", (float(msg.get("rms") or 0.0),
                                   float(msg.get("peak") or 0.0),
                                   float(msg.get("threshold") or 0.0)))
                elif kind == "ready":
                    emit("ready", sess.attached_source())
                elif kind == "error":
                    emit("error", str(msg.get("text") or ""))
                    break
        except Exception as e:      # noqa: BLE001
            emit("error", f"The microphone test failed ({e}).")
        finally:
            stop.set()
            sess.stop(grace=0.2)
            if self._session is sess:
                self._session = None
            emit("stopped", "")


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
    if mic_host.available():
        # Same reason as list_microphones(): asking PortAudio for its
        # default input builds and tears down a PyAudio instance, and
        # Pa_Terminate() aborts every open stream in the process it runs
        # in. Doing that in the app while the app is recording is how a
        # working session ends in a corrupted heap.
        ok, res, answered = mic_host.default_device(log)
        if ok:
            return ""
        if not answered:
            # spawning failed outright - try the old in-process probe
            # below rather than refusing to start over a missing helper
            res = ""
        elif "timed out" in str(res):
            return ("The system default microphone did not answer. This "
                    "usually means a device disappeared while it was still "
                    "registered \u2013 leaving VR does exactly that. Pick a "
                    "specific microphone from the list instead of "
                    "\u201cSystem default\u201d, or press \u27F3 Refresh "
                    "once it is back.")
        elif res:
            return (f"No usable system default microphone ({res}). Pick a "
                    f"specific device from the list.")

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
        # sound-server source to point the helper at ("" = the default).
        # Separate from mic_index on purpose: the index says WHICH DOOR
        # (the "pipewire" PCM), the node says which room behind it.
        self.mic_node = ""
        # {energy_auto, energy_threshold, pause_sec, min_phrase_sec,
        #  phrase_limit} - see core/stt_child.py _apply_sensitivity()
        self.sensitivity = {}
        # levels for the UI meter, so the bar keeps moving while a
        # recording is running instead of going dark exactly when it
        # matters most
        self.levels = queue.Queue(maxsize=64)
        # the helper process currently holding the microphone, so
        # shutdown() can end it instead of leaving an orphan behind
        self._active_session = None

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
              google_key="", libre_online_url="", libre_online_key="",
              mic_node="", sensitivity=None):
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
        self.mic_node = mic_node or ""
        self.sensitivity = dict(sensitivity or {})
        while not self.levels.empty():
            try:
                self.levels.get_nowait()
            except Exception:      # noqa: BLE001
                break
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

    def shutdown(self):
        """Stop AND make sure the helper process is gone before we
        return. stop() only sets a flag; the thread that acts on it is a
        daemon, so at application exit it can be killed halfway through
        and leave a helper holding the microphone for a window that no
        longer exists. Called from MainWindow.closeEvent()."""
        self._stop.set()
        sess = self._active_session
        if sess is not None:
            try:
                sess.stop(grace=0.5)
            except Exception:      # noqa: BLE001
                pass

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

        # The microphone belongs in a process of its own whenever that is
        # possible. PortAudio does not fail, it ABORTS - a corrupted heap
        # inside PipeWire's ALSA plugin takes down whatever process it is
        # in, and that must not be the one holding the user's window and
        # their unsaved config. See core/mic_host.py.
        if mic_host.available():
            self._run_helper(stop, emit)
            return
        self._run_inprocess(stop, emit, me)

    # --------------------------------------------------- helper process
    #: what the helper's short status words mean in the UI
    _HELPER_STATUS = {
        "listening": "Listening \u2026",
        "transcribing": "Transcribing \u2026",
        "unknown": "Didn't catch that \u2013 listening \u2026",
    }

    def _run_helper(self, stop, emit):
        """Supervise core/stt_child.py and translate what it heard."""
        sensitivity = dict(self.sensitivity)
        sensitivity.setdefault("levels", True)
        phrase_limit = sensitivity.pop("phrase_limit", 12)
        sess = mic_host.Session(language=self.language,
                                mic_index=self.mic_index,
                                node=self.mic_node,
                                phrase_limit=phrase_limit,
                                sensitivity=sensitivity)
        if not sess.start():
            emit("error", f"The microphone helper could not start "
                          f"({sess.error}).")
            emit("stopped", "")
            return

        self._active_session = sess

        def stopper():
            # Stopping is a kill, not a join: a helper wedged inside
            # PortAudio would otherwise keep the record button hostage.
            stop.wait()
            sess.stop()

        threading.Thread(target=stopper, daemon=True,
                         name="stt-stopper").start()

        saw_error = False
        try:
            for msg in sess.messages():
                if stop.is_set():
                    break
                kind = str(msg.get("kind") or "")
                if kind == "level":
                    # Its own queue, not the message queue: levels arrive
                    # twenty times a second and the UI drains messages
                    # every 200 ms, so mixing them would bury a "heard"
                    # under two hundred meter updates.
                    self._push_level(msg)
                    continue
                text = str(msg.get("text") or "")
                if kind == "ready":
                    emit("status", "Listening \u2026 speak now")
                    # What it is ACTUALLY recording from, which is not
                    # always what was asked for - see
                    # mic_host.Session.attached_source().
                    actual = sess.attached_source()
                    if actual:
                        emit("source", actual)
                elif kind == "heard":
                    self._deliver(text, emit)
                elif kind == "status":
                    emit("status", self._HELPER_STATUS.get(text, text))
                elif kind == "error":
                    saw_error = True
                    emit("error", self._helper_error_text(text))
                    break
        except Exception as e:      # noqa: BLE001
            emit("error", f"Recording error: {e}")
            saw_error = True
        finally:
            requested = stop.is_set()
            stop.set()
            sess.stop()
            if not requested and not saw_error:
                if sess.crashed():
                    # The exact failure this whole helper exists for.
                    # Before 1.4.1 this line was the app disappearing.
                    mic_probe.mark_stuck(
                        "the audio driver aborted the microphone helper")
                    emit("error",
                         "The audio driver crashed the microphone helper "
                         "process. The recording stopped, but the app is "
                         "unaffected \u2013 this is a bug in PortAudio / "
                         "PipeWire, not in the chatbox. Try a different "
                         "device (a plain \u201cpipewire\u201d or "
                         "\u201cpulse\u201d entry is the most reliable), "
                         f"then press \u27F3 Refresh. Details: "
                         f"{sess.exit_note()}")
                else:
                    emit("error", f"The microphone stopped "
                                  f"({sess.exit_note()}).")
            if self._active_session is sess:
                self._active_session = None
            emit("stopped", "")

    def _push_level(self, msg):
        """Newest level wins. The queue is bounded and the OLDEST entry
        is dropped when it is full, because a meter showing what the
        microphone did two seconds ago is not a meter."""
        item = (float(msg.get("rms") or 0.0), float(msg.get("peak") or 0.0),
                float(msg.get("threshold") or 0.0))
        try:
            self.levels.put_nowait(item)
        except Exception:      # noqa: BLE001 - queue.Full
            try:
                self.levels.get_nowait()
                self.levels.put_nowait(item)
            except Exception:      # noqa: BLE001
                pass

    def latest_level(self):
        """The most recent (rms, peak, threshold), or None. Drains the
        queue - the UI paints one frame, not a backlog."""
        item = None
        while True:
            try:
                item = self.levels.get_nowait()
            except Exception:      # noqa: BLE001 - queue.Empty
                return item

    @staticmethod
    def _helper_error_text(text):
        low = (text or "").lower()
        if "no microphone driver" in low or "speechrecognition" in low:
            return missing_dependency() or text
        if "microphone" in low and ("open" in low or "setup" in low):
            return (f"{text}. If you just left VR, its virtual microphone "
                    f"is gone \u2013 pick another device and press "
                    f"\u27F3 Refresh.")
        return text

    # ------------------------------------------------- translation side
    def _deliver(self, text, emit):
        """One recognised phrase: translate it if asked, then hand the
        pair (spoken, sent) to the UI.

        Shared by both paths on purpose - the microphone moved out of
        the process, the language settings did not.
        """
        text = (text or "").strip()
        if not text:
            return
        out = text
        tgt = self.translate_to
        if tgt and not self.language.lower().startswith(
                tgt.lower().split("-")[0]):
            emit("status", "Translating \u2026")
            # its own event, not a status string the UI would have to
            # pattern-match: the chatbox notice is a behaviour, and
            # hanging it off the wording of a label would break the
            # first time that label is reworded
            emit("translating", text)
            tr = translate_with_fallback(
                self.method, text, self.language, tgt,
                deepl_key=self.deepl_key,
                libre_url=self.libre_url,
                google_key=self.google_key,
                libre_online_url=self.libre_online_url,
                libre_online_key=self.libre_online_key,
                log=lambda m: emit("status", m))
            if tr:
                emit("status", f'\"{text}\" \u2192 \"{tr}\"')
                out = tr
            else:
                emit("status", "Translation failed \u2013 sending original")
        # emit (source, final) so the UI can show both
        emit("text", (text, out))

    def _apply_sensitivity(self, rec):
        """The same four knobs the helper sets, for the fallback path.

        Deliberately duplicated rather than imported from
        core/stt_child.py: that module is a standalone script that must
        not import the app, and this one must not import a script whose
        whole purpose is to run in a different process. Four assignments
        are a cheaper price than tangling the two.
        """
        cfg = self.sensitivity or {}
        rec.dynamic_energy_threshold = bool(cfg.get("energy_auto", True))
        try:
            rec.energy_threshold = float(
                cfg.get("energy_threshold", 300) or 300)
        except Exception:      # noqa: BLE001
            rec.energy_threshold = 300.0
        try:
            pause = float(cfg.get("pause_sec", 0.8) or 0.8)
        except Exception:      # noqa: BLE001
            pause = 0.8
        pause = max(0.2, min(3.0, pause))
        rec.pause_threshold = pause
        try:
            rec.phrase_threshold = max(0.05, min(2.0, float(
                cfg.get("min_phrase_sec", 0.3) or 0.3)))
        except Exception:      # noqa: BLE001
            rec.phrase_threshold = 0.3
        rec.non_speaking_duration = min(pause, 0.5)
        return rec

    def _phrase_limit(self):
        try:
            return max(3, min(60, int(
                (self.sensitivity or {}).get("phrase_limit", 12) or 12)))
        except Exception:      # noqa: BLE001
            return 12

    # ------------------------------------------------ in-process fallback
    def _run_inprocess(self, stop, emit, me):
        """The old path, for a build where no helper can be spawned.

        Still worth having: a frozen build with a broken re-exec, or
        somebody debugging with OSC_DREAMCHATBOX_STT_INPROCESS=1. It is
        the same code as before except for one thing that mattered - the
        stream is opened, calibrated and read on THIS thread now, not on
        three different throwaway guard threads.
        """
        # ---- 1. recognizer + microphone object -------------------------
        # sr.Microphone() is not a passive object: its constructor asks
        # PortAudio for the default device and the sample rate. On a
        # machine whose audio graph just lost a node that lookup is one
        # of the calls that never returns - so a watchdog reports it,
        # but the call itself stays on this thread (see mic_probe.watched
        # for why moving it was actively harmful).
        try:
            with mic_probe.watched("microphone setup") as late:
                with _silence_stderr():
                    r = sr.Recognizer()
                    self._apply_sensitivity(r)
                    if HAS_PYAUDIO:
                        mic = (sr.Microphone(device_index=self.mic_index)
                               if self.mic_index >= 0 else sr.Microphone())
                    else:
                        mic = mic_sounddevice.make_microphone(
                            sr, self.mic_index)
        except Exception as e:      # noqa: BLE001
            me.dc_stalled = False
            emit("error", self._open_error_text(e))
            emit("stopped", "")
            return
        if late.is_set():
            me.dc_stalled = True

        # ---- 2. open the stream ----------------------------------------
        try:
            with mic_probe.watched("microphone open") as late:
                with _silence_stderr():
                    source = mic.__enter__()
        except Exception as e:      # noqa: BLE001
            emit("error", self._open_error_text(e))
            self._close(mic)
            emit("stopped", "")
            return
        if late.is_set():
            me.dc_stalled = True

        # ---- 3. calibrate ----------------------------------------------
        # Only in automatic mode: adjust_for_ambient_noise() writes what
        # it measured into energy_threshold, so running it would silently
        # discard a manually set sensitivity.
        if self.sensitivity.get("energy_auto", True):
            try:
                with mic_probe.watched("microphone calibration") as late:
                    r.adjust_for_ambient_noise(source, duration=0.4)
            except Exception as e:      # noqa: BLE001
                emit("error", self._open_error_text(e))
                self._close(mic)
                emit("stopped", "")
                return
            if late.is_set():
                me.dc_stalled = True

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
                    audio = r.listen(source, timeout=1,
                                     phrase_time_limit=self._phrase_limit())
                except sr.WaitTimeoutError:
                    continue
                tick()
                if stop.is_set() or stalled.is_set():
                    break
                emit("status", "Transcribing \u2026")
                try:
                    text = r.recognize_google(audio, language=self.language)
                    tick()      # transcription is a network call
                    # same delivery as the helper path - one place that
                    # knows about the language settings
                    self._deliver(text, emit)
                    tick()      # so is the translation inside it
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
