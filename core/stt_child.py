"""
core/stt_child.py - the microphone, in a process of its own

WHY THIS EXISTS
---------------
PortAudio can take the whole application down with it. Not "raise an
exception" - abort it:

    malloc(): mismatching next->prev_size (unsorted)
    free(): corrupted unsorted chunks
    [1]  1234175 abort (core dumped)  osc-dreamchatbox

That is glibc noticing a corrupted heap, and it is reported from inside
the audio stack (PipeWire's ALSA plugin, the pipewire data-loop, or
PyAudio_ReadStream). No amount of try/except helps: by the time the
process aborts, Python is not running any more. Reported for CachyOS
with PipeWire 1.6 and PyAudio 0.2.14, on the AUR build, the AppImage
and a source checkout alike.

Two things made it worse on our side, and both are fixed:

1. Every PortAudio call used to run on a THROWAWAY THREAD (the timeout
   guard in core/backends/mic_probe.py). So the stream was opened on one
   thread, calibrated on a second and read on a third, while the first
   two had already exited. PipeWire keeps per-thread client state; a
   stream whose creating thread is gone is exactly the shape of bug
   above - which is why the faulting thread in the reported coredumps is
   called ``mic-probe:*``. Here, one process does open, calibrate, read
   and close on ITS MAIN THREAD, start to finish.

2. Enumerating devices constructs a PyAudio object and terminates it
   again, and ``Pa_Terminate()`` tears down every open stream in the
   process. Filling the microphone dropdown while a recording was
   running could therefore pull the stream out from under the reader.
   Now the dropdown is filled by a separate short-lived process, so the
   worst it can do is crash itself.

WHAT THE PARENT SEES
--------------------
Newline-delimited JSON on stdout, one object per line:

    {"kind": "ready"}                     microphone open and calibrated
    {"kind": "status",  "text": "..."}    something to show the user
    {"kind": "heard",   "text": "..."}    a recognised phrase
    {"kind": "level",   "rms": 812.0,     how loud the input is right now
                        "peak": 4210.0,   (see core/audiolevel.py) plus the
                        "threshold": 300} value speech has to beat
    {"kind": "error",   "text": "..."}    fatal, the helper stops after it

The level messages are what makes "is this device even hearing me"
answerable without going into an instance and finding out the hard way.
They are emitted from inside the read path, so they report the audio the
recogniser is actually working with rather than a second stream that
might be attached to a different node.

Translation is deliberately NOT done here: it is a network call with a
lot of configuration behind it (see core/translators.py) and it does not
touch the microphone, so it stays in the app where its settings live.

Modes:

    stt_child.py list        print the input devices as JSON, exit
    stt_child.py default     print the default input device, exit
    stt_child.py listen      read one JSON config line from stdin, then
                             stream messages until stdin closes
    stt_child.py level       the same, but only the level messages - the
                             microphone test, which opens nothing in the
                             app process and can be killed at any moment

A crash in any of them is a dead helper process and a message in the
app. It is not a dead app.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

# Started as a plain script (that is the point - importing the app would
# drag Qt into a process that only needs a microphone), so the project
# root has to go on the path by hand.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def emit(kind, **fields):
    """One JSON object per line, flushed - the parent reads this live."""
    try:
        sys.stdout.write(json.dumps({"kind": kind, **fields}) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _driver():
    """('pyaudio' | 'sounddevice' | '', reason)"""
    try:
        from core import pyextras
        pyextras.activate()
    except Exception:
        pass
    import importlib.util
    try:
        if importlib.util.find_spec("pyaudio") is not None:
            return "pyaudio", ""
    except Exception:
        pass
    try:
        from core.backends import mic_sounddevice
        if mic_sounddevice.available():
            return "sounddevice", ""
        return "", mic_sounddevice.unavailable_reason()
    except Exception as e:      # noqa: BLE001
        return "", f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- list
def cmd_list():
    driver, reason = _driver()
    if not driver:
        emit("result", ok=False, error=reason or "no microphone driver")
        return 2
    try:
        if driver == "pyaudio":
            import speech_recognition as sr
            names = sr.Microphone.list_microphone_names()
            devices = [[n, i] for i, n in enumerate(names) if n]
        else:
            from core.backends import mic_sounddevice
            devices = [[n, i] for n, i in mic_sounddevice.list_devices()]
    except Exception as e:      # noqa: BLE001
        emit("result", ok=False, error=f"{type(e).__name__}: {e}")
        return 1
    emit("result", ok=True, devices=devices, driver=driver)
    return 0


def cmd_default():
    driver, reason = _driver()
    if not driver:
        emit("result", ok=False, error=reason or "no microphone driver")
        return 2
    try:
        if driver == "pyaudio":
            import speech_recognition as sr
            pa = sr.Microphone.get_pyaudio().PyAudio()
            try:
                info = pa.get_default_input_device_info()
            finally:
                pa.terminate()
            name = str(info.get("name", "")) if info else ""
        else:
            from core.backends import mic_sounddevice
            idx = mic_sounddevice.default_device_index()
            if idx is None:
                emit("result", ok=False, error="no default input device")
                return 1
            name = str(idx)
    except Exception as e:      # noqa: BLE001
        emit("result", ok=False, error=f"{type(e).__name__}: {e}")
        return 1
    emit("result", ok=True, name=name, driver=driver)
    return 0


# --------------------------------------------------------------- level
#: how often level messages go up the pipe. 20/s looks smooth in a bar
#: and is nothing next to the audio itself; the recogniser reads chunks
#: of 1024 frames at 16 kHz, i.e. about 16 of them a second, so this is
#: really "every chunk" with a cap for backends using smaller ones.
LEVEL_INTERVAL = 0.05


class _LevelTap:
    """Wraps ``source.stream`` and reports how loud each chunk was.

    SpeechRecognition only ever calls ``stream.read(size)`` (see
    core/backends/mic_sounddevice.py), so a thin object with that one
    method in front of the real stream is enough to measure the audio
    without changing a single thing about how it is recognised. The
    alternative - a second stream on the same device - would fight the
    first one for a raw ALSA device and, worse, might end up on a
    different node entirely and show levels for audio nobody is
    transcribing.
    """

    def __init__(self, inner, width, threshold=0.0,
                 interval=LEVEL_INTERVAL):
        self._inner = inner
        self._width = width
        self._interval = interval
        self._last = 0.0
        self._peak = 0.0
        self.threshold = threshold

    def read(self, size, *args, **kwargs):
        data = self._inner.read(size, *args, **kwargs)
        try:
            self._measure(data)
        except Exception:      # noqa: BLE001 - a meter never breaks audio
            pass
        return data

    def _measure(self, data):
        import time as _time
        from core import audiolevel
        value = audiolevel.rms(data, self._width)
        self._peak = max(self._peak, audiolevel.peak(data, self._width))
        now = _time.monotonic()
        if now - self._last < self._interval:
            return
        self._last = now
        # The threshold may be a live value: with automatic sensitivity
        # SpeechRecognition re-learns it on every chunk, so a number
        # captured at start-up would put the marker on the bar in a
        # place that has not been true for minutes.
        mark = self.threshold
        if callable(mark):
            try:
                mark = mark()
            except Exception:      # noqa: BLE001
                mark = 0.0
        emit("level", rms=round(value, 1), peak=round(self._peak, 1),
             threshold=round(float(mark or 0.0), 1))
        self._peak = 0.0

    def __getattr__(self, item):
        # close(), and anything a future backend adds
        return getattr(self._inner, item)


def _apply_sensitivity(rec, cfg):
    """Puts the user's sensitivity settings on the Recognizer.

    Every one of these is a SpeechRecognition knob that was previously
    left at its default, and each of them is a real complaint:

    energy_threshold        how loud a chunk has to be to start a phrase
    dynamic_energy_...      let it re-learn the room continuously. Great
                            in a quiet room, and the reason a noisy one
                            (fans, a game, a VR headset's own audio)
                            drifts until either everything or nothing
                            counts as speech.
    pause_threshold         how much silence ends a phrase. Too low cuts
                            sentences in half mid-word.
    phrase_threshold        how long a sound must last to count as speech
                            at all - the setting that stops a keyboard
                            click or a door from becoming a transcription
                            request.
    non_speaking_duration   how much silence is KEPT around a phrase, and
                            it must never exceed pause_threshold or
                            SpeechRecognition slices into the phrase.
    """
    auto = bool(cfg.get("energy_auto", True))
    rec.dynamic_energy_threshold = auto
    try:
        rec.energy_threshold = float(cfg.get("energy_threshold", 300) or 300)
    except Exception:      # noqa: BLE001
        rec.energy_threshold = 300.0
    try:
        pause = float(cfg.get("pause_sec", 0.8) or 0.8)
    except Exception:      # noqa: BLE001
        pause = 0.8
    pause = max(0.2, min(3.0, pause))
    rec.pause_threshold = pause
    try:
        phrase = float(cfg.get("min_phrase_sec", 0.3) or 0.3)
    except Exception:      # noqa: BLE001
        phrase = 0.3
    rec.phrase_threshold = max(0.05, min(2.0, phrase))
    rec.non_speaking_duration = min(pause, 0.5)
    return rec


def cmd_level():
    """Open the microphone and report nothing but how loud it is.

    Deliberately not a recogniser: this is the "does this device hear
    me" test, it must start instantly, and it must be killable from the
    parent at any moment without a phrase in flight.
    """
    stop = threading.Event()
    try:
        first = sys.stdin.readline()
        cfg = json.loads(first) if first.strip() else {}
    except Exception as e:      # noqa: BLE001
        emit("error", text=f"could not read the helper configuration ({e})")
        return 2

    mic_index = int(cfg.get("mic_index", -1))
    threshold = float(cfg.get("energy_threshold", 0) or 0)

    driver, reason = _driver()
    if not driver:
        emit("error", text=reason or "no microphone driver")
        return 2
    try:
        import speech_recognition as sr
    except Exception as e:      # noqa: BLE001
        emit("error", text=f"SpeechRecognition is not importable ({e})")
        return 2

    threading.Thread(target=_stdin_watch, args=(stop,),
                     daemon=True, name="stt-stdin").start()

    try:
        if driver == "pyaudio":
            mic = (sr.Microphone(device_index=mic_index) if mic_index >= 0
                   else sr.Microphone())
        else:
            from core.backends import mic_sounddevice
            mic = mic_sounddevice.make_microphone(sr, mic_index)
    except Exception as e:      # noqa: BLE001
        emit("error", text=f"microphone setup failed: {type(e).__name__}: {e}")
        return 1

    try:
        with mic as source:
            emit("ready")
            tap = _LevelTap(source.stream, source.SAMPLE_WIDTH, threshold)
            chunk = getattr(source, "CHUNK", 1024)
            while not stop.is_set():
                try:
                    tap.read(chunk)
                except Exception as e:      # noqa: BLE001
                    emit("error", text=f"microphone read failed: "
                                       f"{type(e).__name__}: {e}")
                    return 1
    except Exception as e:      # noqa: BLE001
        emit("error", text=f"microphone open failed: "
                           f"{type(e).__name__}: {e}")
        return 1
    return 0


# -------------------------------------------------------------- listen
def _stdin_watch(stop):
    """The only extra thread in this process, and it never goes near
    PortAudio: it waits for the parent to say stop (or to close the
    pipe, which means the app is gone) and sets a flag the main loop
    checks between phrases."""
    try:
        for line in sys.stdin:
            if line.strip().lower() in ("stop", "quit", "exit"):
                break
    except Exception:
        pass
    stop.set()


def cmd_listen():
    stop = threading.Event()
    try:
        first = sys.stdin.readline()
        cfg = json.loads(first) if first.strip() else {}
    except Exception as e:      # noqa: BLE001
        emit("error", text=f"could not read the helper configuration ({e})")
        return 2

    language = str(cfg.get("language") or "en-US")
    mic_index = int(cfg.get("mic_index", -1))
    phrase_limit = int(cfg.get("phrase_limit", 12) or 12)
    calibrate = float(cfg.get("calibrate", 0.4) or 0.4)
    energy_auto = bool(cfg.get("energy_auto", True))
    want_levels = bool(cfg.get("levels", True))

    driver, reason = _driver()
    if not driver:
        emit("error", text=reason or "no microphone driver")
        return 2
    try:
        import speech_recognition as sr
    except Exception as e:      # noqa: BLE001
        emit("error", text=f"SpeechRecognition is not importable ({e})")
        return 2

    threading.Thread(target=_stdin_watch, args=(stop,),
                     daemon=True, name="stt-stdin").start()

    # Everything from here down happens on THIS thread. See the module
    # docstring: the thread that opens the stream has to be the thread
    # that reads it and the thread that closes it.
    try:
        rec = sr.Recognizer()
        _apply_sensitivity(rec, cfg)
        if driver == "pyaudio":
            mic = (sr.Microphone(device_index=mic_index) if mic_index >= 0
                   else sr.Microphone())
        else:
            from core.backends import mic_sounddevice
            mic = mic_sounddevice.make_microphone(sr, mic_index)
    except Exception as e:      # noqa: BLE001
        emit("error", text=f"microphone setup failed: {type(e).__name__}: {e}")
        return 1

    try:
        with mic as source:
            if energy_auto:
                try:
                    rec.adjust_for_ambient_noise(source, duration=calibrate)
                except Exception as e:      # noqa: BLE001
                    emit("status", text=f"calibration skipped ({e})")
            # else: adjust_for_ambient_noise() OVERWRITES energy_threshold
            # with what it measured, so running it in manual mode would
            # throw away the value the user just set and leave them
            # adjusting a slider that does nothing.
            if want_levels:
                source.stream = _LevelTap(
                    source.stream, source.SAMPLE_WIDTH,
                    lambda: getattr(rec, "energy_threshold", 0.0))
            emit("ready")
            while not stop.is_set():
                try:
                    audio = rec.listen(source, timeout=1,
                                       phrase_time_limit=phrase_limit)
                except sr.WaitTimeoutError:
                    continue
                except Exception as e:      # noqa: BLE001
                    emit("error", text=f"recording error: "
                                       f"{type(e).__name__}: {e}")
                    return 1
                if stop.is_set():
                    break
                emit("status", text="transcribing")
                try:
                    text = (rec.recognize_google(
                        audio, language=language) or "").strip()
                except sr.UnknownValueError:
                    emit("status", text="unknown")
                    continue
                except sr.RequestError as e:
                    emit("error", text=f"speech API error: {e}")
                    return 1
                except Exception as e:      # noqa: BLE001
                    emit("error", text=f"recognition failed: "
                                       f"{type(e).__name__}: {e}")
                    return 1
                if text:
                    emit("heard", text=text)
                emit("status", text="listening")
    except Exception as e:      # noqa: BLE001
        emit("error", text=f"microphone open failed: "
                           f"{type(e).__name__}: {e}")
        return 1
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "listen"
    if mode == "list":
        return cmd_list()
    if mode == "default":
        return cmd_default()
    if mode == "listen":
        return cmd_listen()
    if mode == "level":
        return cmd_level()
    emit("result", ok=False, error=f"unknown helper mode {mode!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
