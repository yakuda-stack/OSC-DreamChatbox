"""
core/backends/mic_probe.py - a timeout guard around PortAudio

WHY THIS EXISTS
---------------
PortAudio has no timeouts. Enumerating or opening an audio device is a
blocking C call, and on Linux it goes through ALSA -> PulseAudio/PipeWire
over a unix socket. When a device disappears while its node is still
registered - which is exactly what happens when you leave VR and WiVRn's
virtual microphone goes away - that call can block forever. Nothing in
SpeechRecognition, pyaudio or sounddevice can interrupt it.

Two consequences the app used to suffer from:

1. The call ran on the GUI thread (the microphone dropdown was filled
   there, and the record button resolved the device index there), so a
   blocked PortAudio froze the window. A frozen Qt client on Wayland that
   still holds the input focus makes the whole desktop look dead, which
   is why this showed up as "my whole Linux desktop hangs".

2. Because there was no timeout, a second attempt simply queued up behind
   the first one - every click leaked another thread parked inside the
   same PortAudio lock.

WHAT THIS MODULE DOES
---------------------
`guarded()` runs a callable on a daemon thread and waits with a deadline.
If the deadline passes, the caller gets an error back and carries on; the
stuck thread stays parked and dies with the process. Since a thread cannot
be killed, the important half is `_stuck`: once something timed out, the
audio driver is assumed wedged and every further call fails fast instead
of leaking one more thread. `clear_stuck()` is what the "Refresh" button
calls to try again after the user fixed things.

This module deliberately contains no audio code at all - it only wraps
whatever the caller passes in, so both the pyaudio and the sounddevice
path get the same protection.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import threading

#: How long a device enumeration may take before we give up on it. A
#: healthy ALSA/PipeWire setup answers in well under a second; six
#: seconds is "something is wrong", not "this machine is slow".
LIST_TIMEOUT = 6.0

#: Opening the stream is allowed to take longer - PipeWire may have to
#: start a node, and a cold Bluetooth headset genuinely needs a moment.
OPEN_TIMEOUT = 10.0

#: No audio arrived for this long while recording -> the device died
#: under us (unplugged, VR session ended). See SpeechWorker._run.
STALL_TIMEOUT = 30.0


class MicTimeout(Exception):
    """Raised inside guarded() when the deadline passed."""


_state_lock = threading.Lock()
#: reason string once something timed out, None while everything is fine
_stuck_reason = None
#: how many guard threads are still parked in a call that never returned
_leaked = 0


def stuck():
    """The reason the audio driver is considered wedged, or ''."""
    with _state_lock:
        return _stuck_reason or ""


def leaked():
    """Number of guard threads still parked inside PortAudio."""
    with _state_lock:
        return _leaked


def clear_stuck():
    """Forget a previous timeout so the next call is attempted again.

    Called by the Refresh button and by the record button, because the
    usual fix is on the user's side (plug the device back in, restart
    PipeWire) and the app has no way to notice that happened.
    """
    global _stuck_reason
    with _state_lock:
        _stuck_reason = None


def _mark_stuck(reason):
    global _stuck_reason, _leaked
    with _state_lock:
        _stuck_reason = reason
        _leaked += 1


def mark_stuck(reason):
    """Declare the audio driver wedged without a timed-out guard call.

    Used by the recording stall watchdog: an open stream that stops
    delivering audio is the same wedged driver, it just shows up as
    silence instead of a call that never returns.
    """
    global _stuck_reason
    with _state_lock:
        _stuck_reason = str(reason)


def _unleak():
    global _leaked
    with _state_lock:
        _leaked = max(0, _leaked - 1)


def guarded(fn, timeout=LIST_TIMEOUT, label="audio call", log=None,
            respect_stuck=True):
    """Run ``fn()`` on a daemon thread with a deadline.

    Returns ``(True, value)`` on success and ``(False, exception)`` on
    failure - including a :class:`MicTimeout` when the deadline passed.
    Never raises, so callers can treat "hung" exactly like "errored".

    ``respect_stuck=False`` forces the attempt even after a previous
    timeout; the record button uses it after clear_stuck() so a user who
    fixed their audio does not have to restart the app.
    """
    if respect_stuck:
        reason = stuck()
        if reason:
            return False, MicTimeout(
                f"the audio driver is not responding ({reason}) - "
                f"use \u27F3 Refresh once the device is back")

    box = {}
    done = threading.Event()
    # guards the "did the waiter already give up?" flag, so the leak
    # counter stays honest when a call returns in the same moment the
    # deadline passes
    bookkeeping = threading.Lock()

    def run():
        try:
            box["value"] = fn()
            box["ok"] = True
        except BaseException as e:      # noqa: BLE001 - reported, not raised
            box["error"] = e
            box["ok"] = False
        finally:
            done.set()
            with bookkeeping:
                # it came back after all, so it is no longer parked
                if box.get("abandoned"):
                    box["abandoned"] = False
                    _unleak()

    worker = threading.Thread(target=run, daemon=True,
                              name=f"mic-probe:{label}")
    worker.start()
    if not done.wait(timeout):
        with bookkeeping:
            if not done.is_set():
                box["abandoned"] = True
                _mark_stuck(f"{label} did not return within {timeout:.0f}s")
        if callable(log):
            log(f"Speech to Text: {label} did not answer within "
                f"{timeout:.0f}s - the audio device is most likely gone "
                f"(VR session ended?). The app stays usable; pick another "
                f"microphone or press \u27F3 Refresh.")
        return False, MicTimeout(
            f"{label} timed out after {timeout:.0f}s")
    if box.get("ok"):
        return True, box.get("value")
    return False, box.get("error") or RuntimeError(f"{label} failed")
