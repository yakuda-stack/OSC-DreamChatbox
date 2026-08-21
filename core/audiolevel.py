"""
core/audiolevel.py - how loud is that chunk

Two callers need the same number, in the same units, or the feature does
not work at all:

* the level meter in the UI, so you can SEE that the selected device is
  picking your voice up before you rely on it in an instance, and
* the sensitivity setting, which is SpeechRecognition's
  ``Recognizer.energy_threshold`` - the value it compares every chunk
  against to decide "this is speech, start recording a phrase".

SpeechRecognition computes that number with ``audioop.rms()``. So this
module computes exactly that: the root mean square of signed 16-bit
samples, 0 .. 32768. A meter in dB and a threshold in RMS would be two
scales for one decision, and the marker on the bar would be a lie.

audioop is not importable any more - it was removed in Python 3.13, and
this app already ships for 3.13/3.14 (see core/backends/mic_sounddevice.py
for the same story about PyAudio wheels). The stdlib replacement is a
PyPI package that may or may not be installed, so the fallback below is
the one that has to be correct; the audioop path is only a speed-up on
old interpreters.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import array
import math

try:                    # 3.12 and older, or the audioop-lts backport
    import audioop      # type: ignore
except Exception:       # noqa: BLE001
    try:
        import audioop_lts as audioop      # type: ignore
    except Exception:   # noqa: BLE001
        audioop = None

#: full scale for signed 16-bit samples, the unit everything here is in
FULL_SCALE = 32768.0

#: sample widths the pure-python path knows. Both microphone backends
#: ask PortAudio for int16, so 2 is the only one that ever shows up -
#: the others exist so a future backend does not silently get zeros.
_TYPECODE = {1: "b", 2: "h", 4: "l"}


def rms(data, width=2):
    """Root mean square of a raw PCM chunk, 0 .. 32768.

    Returns 0 for an empty or unparsable chunk rather than raising: this
    runs per audio block, and a meter that throws is worse than a meter
    that reads zero for one frame.
    """
    if not data:
        return 0.0
    if audioop is not None:
        try:
            return float(audioop.rms(data, width))
        except Exception:      # noqa: BLE001
            pass
    code = _TYPECODE.get(int(width))
    if code is None:
        return 0.0
    try:
        samples = array.array(code)
        usable = len(data) - (len(data) % samples.itemsize)
        if usable <= 0:
            return 0.0
        samples.frombytes(bytes(data[:usable]))
    except Exception:      # noqa: BLE001
        return 0.0
    if not samples:
        return 0.0
    total = 0
    for value in samples:
        total += value * value
    value = math.sqrt(total / len(samples))
    if width == 1:      # 8-bit is unsigned-ish; scale to the same range
        value *= 256.0
    return float(value)


def peak(data, width=2):
    """Largest absolute sample in the chunk, same 0 .. 32768 scale."""
    if not data:
        return 0.0
    if audioop is not None:
        try:
            return float(audioop.max(data, width))
        except Exception:      # noqa: BLE001
            pass
    code = _TYPECODE.get(int(width))
    if code is None:
        return 0.0
    try:
        samples = array.array(code)
        usable = len(data) - (len(data) % samples.itemsize)
        if usable <= 0:
            return 0.0
        samples.frombytes(bytes(data[:usable]))
    except Exception:      # noqa: BLE001
        return 0.0
    return float(max((abs(s) for s in samples), default=0))


def to_db(value):
    """RMS -> dBFS. Silence is clamped to -90 instead of -inf."""
    value = max(0.0, float(value))
    if value < 1.0:
        return -90.0
    return max(-90.0, 20.0 * math.log10(value / FULL_SCALE))


def to_bar(value, floor_db=-60.0):
    """RMS -> 0.0 .. 1.0 for a level bar.

    Linear RMS is useless to look at: normal speech sits around 1-3% of
    full scale, so a linear bar shows a twitch at the very left edge and
    nothing else. Mapping dBFS onto the bar instead puts quiet speech in
    the middle, which is what every audio meter does and what makes
    "does it hear me" answerable at a glance.
    """
    db = to_db(value)
    if db <= floor_db:
        return 0.0
    return min(1.0, (db - floor_db) / (0.0 - floor_db))


#: Sensible sensitivity range for the UI slider, in the same RMS units.
#: 50 is "a quiet room already triggers it", 4000 is "shout at it".
THRESHOLD_MIN = 50
THRESHOLD_MAX = 4000
THRESHOLD_DEFAULT = 300


def clamp_threshold(value, default=THRESHOLD_DEFAULT):
    try:
        value = int(round(float(value)))
    except Exception:      # noqa: BLE001
        return int(default)
    return max(THRESHOLD_MIN, min(THRESHOLD_MAX, value))
