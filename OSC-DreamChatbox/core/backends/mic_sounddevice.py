"""
core/backends/mic_sounddevice.py – microphone input without PyAudio

WHY THIS EXISTS
---------------
SpeechRecognition opens the microphone through ``sr.Microphone``, which
needs PyAudio. PyAudio is a compiled extension, and its wheels stop at
CPython 3.13 - on Python 3.14 ``pip install pyaudio`` falls back to a
source build that needs MSVC and a PortAudio checkout. That is not a
reasonable thing to ask a VRChat user for.

``sounddevice`` solves it: it is a pure-Python CFFI wrapper around the
same PortAudio library, and its Windows wheel is tagged
``py3-none-win_amd64`` - no CPython ABI, so it installs on 3.14 and on
whatever comes next. The wheel even carries the PortAudio DLL, so
nothing has to be installed system-wide.

HOW IT PLUGS IN
---------------
Nothing about the recognition changes. ``sr.Recognizer.listen()`` only
ever asks its source for four things:

    source.SAMPLE_RATE   source.SAMPLE_WIDTH
    source.CHUNK         source.stream.read(chunk)

So this module supplies exactly that as an ``sr.AudioSource``, and every
piece of SpeechRecognition above it - the energy threshold, the silence
detection, ``adjust_for_ambient_noise()``, the Google recognizer - keeps
working untouched. It is a swapped-out driver, not a second pipeline.

PyAudio still wins when it is installed (Linux distributions package it
properly), so nothing about an existing Linux setup changes.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util

# Probe result cache: (usable, reason). None = not probed yet.
_PROBE = None


def available():
    """True only when sounddevice can ACTUALLY be used.

    find_spec() alone is not enough and gets this wrong in a way that
    matters: the generic ``py3-none-any`` wheel installs the python files
    without any PortAudio, so the module is importable-looking but
    ``import sounddevice`` raises ``OSError: PortAudio library not
    found``. Reporting "driver present" and then failing at the first
    microphone open is worse than reporting nothing at all.

    The Windows wheel (``py3-none-win_amd64``) carries the DLL, so there
    this probe simply succeeds.

    Probed lazily and cached: on a machine with PyAudio this is never
    called, and loading PortAudio for nothing costs startup time.
    """
    global _PROBE
    if _PROBE is None:
        try:
            if importlib.util.find_spec("sounddevice") is None:
                _PROBE = (False, "sounddevice is not installed")
            else:
                import sounddevice  # noqa: F401  (loads PortAudio)
                _PROBE = (True, "")
        except Exception as e:
            _PROBE = (False, f"{type(e).__name__}: {e}")
    return _PROBE[0]


def unavailable_reason():
    available()
    return _PROBE[1]


def __getattr__(name):
    # keeps `mic_sounddevice.HAS_SOUNDDEVICE` working as a lazy property
    if name == "HAS_SOUNDDEVICE":
        return available()
    raise AttributeError(name)

# what we ask PortAudio for. 16 kHz mono 16-bit is what the Google
# recognizer wants anyway, so no resampling happens anywhere.
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2          # bytes, int16
CHUNK = 1024


def _sd():
    import sounddevice
    return sounddevice


def list_devices(log=None):
    """[(label, index)] of input devices.

    The label carries the host API - PortAudio reports the same physical
    microphone once per API (MME, DirectSound, WASAPI, WDM-KS), and MME
    additionally truncates names to 31 characters. Without the suffix the
    dropdown shows four identical, half-cut entries.
    """
    if not available():
        return []
    try:
        sd = _sd()
        apis = sd.query_hostapis()
        out = []
        for idx, dev in enumerate(sd.query_devices()):
            if int(dev.get("max_input_channels", 0)) < 1:
                continue
            name = str(dev.get("name", "")).strip()
            if not name:
                continue
            try:
                api = apis[dev["hostapi"]]["name"]
            except Exception:
                api = ""
            out.append((f"{name} [{api}]" if api else name, idx))
        return out
    except Exception as e:
        if callable(log):
            log(f"Speech to Text: sounddevice could not list devices ({e})")
        return []


def default_device_index():
    try:
        dev = _sd().default.device
        idx = dev[0] if isinstance(dev, (list, tuple)) else dev
        return int(idx) if idx is not None and int(idx) >= 0 else None
    except Exception:
        return None


def make_microphone(sr_module, device_index=-1):
    """Build an sr.AudioSource backed by sounddevice.

    Raises on failure, exactly like sr.Microphone would, so the caller's
    existing error handling still applies.
    """
    if not available():
        raise RuntimeError(unavailable_reason())

    sd = _sd()

    class _Stream:
        """The tiny part SpeechRecognition actually talks to."""

        def __init__(self, raw):
            self._raw = raw

        def read(self, size):
            # exception_on_overflow has no equivalent here; PortAudio
            # signals an overflow through a flag we deliberately ignore,
            # because dropping the chunk would cut words in half
            data, _overflowed = self._raw.read(size)
            return bytes(data)

        def close(self):
            try:
                self._raw.stop()
            finally:
                self._raw.close()

    class SoundDeviceMicrophone(sr_module.AudioSource):
        SAMPLE_RATE = globals()["SAMPLE_RATE"]
        SAMPLE_WIDTH = globals()["SAMPLE_WIDTH"]
        CHUNK = globals()["CHUNK"]

        def __init__(self, index):
            self.device_index = index if index is not None and index >= 0 \
                else None
            self.stream = None
            self._raw = None
            # SpeechRecognition reads these off the instance, so they must
            # exist as instance attributes too
            self.SAMPLE_RATE = SAMPLE_RATE
            self.SAMPLE_WIDTH = SAMPLE_WIDTH
            self.CHUNK = CHUNK

        def __enter__(self):
            if self.stream is not None:
                raise RuntimeError("this microphone is already open")
            self._raw = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=CHUNK,
                device=self.device_index,
                channels=1,
                dtype="int16")
            self._raw.start()
            self.stream = _Stream(self._raw)
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            stream, self.stream = self.stream, None
            self._raw = None
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            return False

    return SoundDeviceMicrophone(device_index)


def backend_note():
    if available():
        return ""
    return f"{unavailable_reason()} - run:  pip install sounddevice"


# ====================================================================
#  python -m core.backends.mic_sounddevice
# ====================================================================
def _selftest():
    print("=" * 62)
    print(" OSC-DreamChatbox - sounddevice microphone self-test")
    print("=" * 62)
    if not available():
        print(f"\nsounddevice unusable: {unavailable_reason()}\n"
              "    pip install sounddevice\n")
        return
    devices = list_devices(print)
    print(f"\n{len(devices)} input device(s):")
    for label, idx in devices:
        print(f"  [{idx:3}] {label}")
    print(f"\ndefault input index: {default_device_index()}")

    try:
        import speech_recognition as sr
    except ImportError:
        print("\nSpeechRecognition not installed - stopping after the "
              "device list.\n    pip install SpeechRecognition")
        return

    print("\nRecording 3 seconds from the default device ...")
    try:
        mic = make_microphone(sr, -1)
        import audioop
        peak = 0
        with mic as source:
            for _ in range(int(3 * SAMPLE_RATE / CHUNK)):
                chunk = source.stream.read(CHUNK)
                try:
                    peak = max(peak, audioop.max(chunk, SAMPLE_WIDTH))
                except Exception:
                    pass
        print(f"peak amplitude: {peak} (of 32768)")
        if peak < 200:
            print("-> almost silent. Wrong device, or Windows privacy "
                  "settings block microphone access for desktop apps.")
        else:
            print("-> microphone works.")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    _selftest()
