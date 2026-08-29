"""
core/mic_host.py - talking to the microphone helper process

core/stt_child.py explains WHY the microphone lives in a process of its
own (short version: PortAudio aborts the process it runs in, and it has
been doing that to people on PipeWire). This module is the other half:
it spawns that helper, reads its messages and kills it when the user
presses stop.

Three things it buys, none of which are possible in-process:

* A heap corruption in the audio stack kills the helper. The app gets an
  error message and a record button that goes back to "Start".
* A wedged PortAudio call can actually be ABANDONED. A thread parked in
  a blocking C call is stuck for the life of the process; a process is
  one SIGKILL away. The old timeout guard could only leak the thread and
  refuse to try again (see core/backends/mic_probe.py).
* Listing devices no longer touches the audio stack of the process that
  is holding an open stream, so filling the dropdown while recording is
  harmless.

Finding the helper is the fiddly part, because "run python" means three
different things:

    from source     sys.executable is the venv python, and
                    core/stt_child.py is a file on disk
    AppImage        the same, with PYTHONPATH already exported by AppRun
                    and the file inside the mounted image
    frozen (.exe)   there is no python and no .py file - sys.executable
                    IS the app, so it is re-run with a marker argument
                    that the entry point intercepts before Qt loads
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from core import osinfo
from core.osinfo import IS_FROZEN

#: argv marker a frozen build uses to become the helper instead of the
#: app. Handled at the very top of osc_dreamchatbox.py.
HELPER_FLAG = "--stt-helper"

#: Set to 1 to keep the microphone inside the app process (the pre-1.4.1
#: behaviour). Only useful for debugging - the whole point of the helper
#: is that the audio stack cannot take the UI with it.
ENV_INPROCESS = "OSC_DREAMCHATBOX_STT_INPROCESS"

#: how long a device enumeration may take before the helper is killed.
#: Killing works, unlike the in-process guard, so this can be generous
#: without leaking anything.
LIST_TIMEOUT = 8.0

#: stderr lines kept for the crash report. ALSA prints pages of noise on
#: a healthy system, so only the tail is interesting.
STDERR_KEEP = 12

#: noise every ALSA/JACK setup produces and nobody needs in a bug report
_NOISE = ("ALSA lib", "jack server", "JackShmReadWritePtr", "Cannot connect",
          "Unknown PCM", "snd_pcm_", "pcm_", "connect(2) call to")


def in_process_forced():
    return str(os.environ.get(ENV_INPROCESS, "")).strip() in ("1", "true",
                                                              "yes", "on")


def helper_script():
    """Path to core/stt_child.py, or None in a frozen build."""
    if IS_FROZEN:
        return None
    path = osinfo.resource("core", "stt_child.py")
    return path if path.exists() else None


def helper_argv(mode):
    """The command line that starts the helper in `mode`, or None."""
    if in_process_forced():
        return None
    exe = sys.executable
    if not exe:
        return None
    if IS_FROZEN:
        return [exe, HELPER_FLAG, mode]
    script = helper_script()
    if script is None:
        return None
    return [exe, str(script), mode]


def available():
    return helper_argv("list") is not None


def _popen(argv, stdin=None, node=""):
    """Start the helper, optionally pointed at a specific audio node.

    `node` is where the separate process finally pays off twice over.
    PipeWire and PulseAudio pick the source for a new ALSA client from
    the environment (PULSE_SOURCE / PIPEWIRE_NODE), read once when the
    stream opens - so selecting "the WiVRn microphone" means setting a
    variable for the process that opens it. Doing that in-process would
    mean mutating the app's own environment, which every future stream
    (and any child it spawns) would then inherit.

    The variables are also actively REMOVED when no node is given: a
    user who exported PULSE_SOURCE in their shell would otherwise have
    it quietly override "System default" here, and the app would be
    recording from something it never offered.
    """
    from core.backends import mic_pactl
    env = mic_pactl.clean_env()
    env.update(mic_pactl.env_for(node))
    return subprocess.Popen(
        argv,
        stdin=stdin if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, env=env,
        **osinfo.subprocess_flags(new_group=True))


def _clean_stderr(lines):
    kept = [ln.strip() for ln in lines
            if ln.strip() and not any(n in ln for n in _NOISE)]
    return kept[-STDERR_KEEP:]


def _exit_note(proc, stderr_lines):
    """A sentence about how the helper died, for the log."""
    code = proc.returncode
    detail = "; ".join(_clean_stderr(stderr_lines))
    if code is not None and code < 0:
        # negative = killed by a signal. SIGABRT is glibc noticing the
        # corrupted heap; that is the crash this whole module exists for.
        name = {6: "SIGABRT (the audio library aborted)",
                11: "SIGSEGV (the audio library crashed)",
                9: "SIGKILL"}.get(-code, f"signal {-code}")
        note = f"the microphone helper was killed by {name}"
    elif code:
        note = f"the microphone helper exited with code {code}"
    else:
        note = "the microphone helper stopped"
    return f"{note}{' - ' + detail if detail else ''}"


# --------------------------------------------------------- one-shot calls
def _run_json(mode, timeout=LIST_TIMEOUT, log=None):
    """Run the helper in a one-shot mode and return its result object.

    Returns ``(ok, payload, answered)``. `payload` is the parsed dict on
    success and a reason string otherwise. Never raises.

    ``answered`` separates the two failures that need different
    handling: the helper ran and told us what is wrong with the audio
    (answered - repeating the attempt in this process would only produce
    the same message twice, and touching PortAudio here is what we are
    avoiding), or it never got off the ground at all (not answered - a
    build where spawning does not work should still fill the dropdown
    the old way rather than look broken).
    """
    argv = helper_argv(mode)
    if argv is None:
        return False, "the microphone helper is not available", False
    try:
        proc = _popen(argv)
    except Exception as e:      # noqa: BLE001
        return False, f"could not start the microphone helper ({e})", False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # The helper is wedged inside PortAudio. Unlike a thread, it can
        # simply be removed - which is the entire reason it is a process.
        # It answered in the sense that matters: trying the same call in
        # this process would wedge THIS one.
        _kill(proc)
        if callable(log):
            log(f"Speech to Text: the {mode} helper did not answer within "
                f"{timeout:.0f}s and was stopped. The audio device is most "
                f"likely gone (VR session ended?).")
        return False, f"the {mode} helper timed out after {timeout:.0f}s", True
    except Exception as e:      # noqa: BLE001
        _kill(proc)
        return False, f"the microphone helper failed ({e})", False
    result = None
    for line in (out or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("kind") == "result":
            result = obj
    if result is None:
        note = "; ".join(_clean_stderr((err or "").splitlines()))
        # A helper that died on a signal DID reach the audio stack - that
        # is the crash this module exists for, and repeating it in the
        # app process would repeat it with the app process.
        crashed = proc.returncode is not None and proc.returncode < 0
        return False, (_exit_note(proc, (err or "").splitlines())
                       if proc.returncode else
                       f"the microphone helper said nothing"
                       f"{' - ' + note if note else ''}"), crashed
    if not result.get("ok"):
        return False, str(result.get("error") or "unknown error"), True
    return True, result, True


def _kill(proc):
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.communicate(timeout=2)
    except Exception:
        pass


def list_devices(log=None, timeout=LIST_TIMEOUT):
    """``(ok, devices | reason, answered)`` - see _run_json for what
    `answered` decides."""
    ok, res, answered = _run_json("list", timeout=timeout, log=log)
    if not ok:
        return False, res, answered
    devices = []
    for entry in res.get("devices") or ():
        try:
            devices.append((str(entry[0]), int(entry[1])))
        except Exception:
            continue
    return True, devices, True


def default_device(log=None, timeout=LIST_TIMEOUT):
    ok, res, answered = _run_json("default", timeout=timeout, log=log)
    if not ok:
        return False, res, answered
    return True, str(res.get("name") or ""), True


# ------------------------------------------------------------- recording
class Session:
    """A running helper that is holding the microphone open.

    Usage from the worker thread:

        s = Session(language=..., mic_index=...)
        if not s.start():  -> s.error
        for msg in s.messages():   # blocks, ends when the helper stops
            ...
        s.stop()
    """

    #: after "stop" on stdin, how long the helper may take to leave the
    #: listen loop before it is terminated
    GRACE = 3.0

    def __init__(self, language="en-US", mic_index=-1, phrase_limit=12,
                 calibrate=0.4, log=None, node="", sensitivity=None,
                 mode="listen"):
        self.language = language
        self.mic_index = -1 if mic_index is None else int(mic_index)
        self.phrase_limit = phrase_limit
        self.calibrate = calibrate
        self.log = log
        #: sound-server source to route the helper at, "" = the default
        self.node = node or ""
        #: {energy_auto, energy_threshold, pause_sec, min_phrase_sec}
        self.sensitivity = dict(sensitivity or {})
        self.mode = mode
        self.proc = None
        self.stopped = False
        self.error = ""
        self._stderr = []
        self._stderr_lock = threading.Lock()

    def start(self):
        argv = helper_argv(self.mode)
        if argv is None:
            self.error = "the microphone helper is not available"
            return False
        try:
            self.proc = _popen(argv, stdin=subprocess.PIPE, node=self.node)
        except Exception as e:      # noqa: BLE001
            self.error = f"could not start the microphone helper ({e})"
            return False
        threading.Thread(target=self._drain_stderr, daemon=True,
                         name="stt-helper-stderr").start()
        cfg = {"language": self.language, "mic_index": self.mic_index,
               "phrase_limit": self.phrase_limit,
               "calibrate": self.calibrate}
        cfg.update(self.sensitivity)
        try:
            self.proc.stdin.write(json.dumps(cfg) + "\n")
            self.proc.stdin.flush()
        except Exception as e:      # noqa: BLE001
            self.error = f"the microphone helper closed immediately ({e})"
            self.stop()
            return False
        return True

    def _drain_stderr(self):
        """Keeps the tail of the helper's stderr. Without this the pipe
        fills up on an ALSA-noisy system and the helper blocks writing
        into it - and the tail is what says WHY it died."""
        stream = self.proc.stderr if self.proc else None
        if stream is None:
            return
        try:
            for line in stream:
                with self._stderr_lock:
                    self._stderr.append(line)
                    if len(self._stderr) > 200:
                        del self._stderr[:-100]
        except Exception:
            pass

    def messages(self):
        """Yields the helper's message dicts until it stops."""
        stream = self.proc.stdout if self.proc else None
        if stream is None:
            return
        try:
            for line in stream:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
        except Exception:
            return

    def exit_note(self):
        """Why the helper is gone, once messages() ran out."""
        if self.proc is None:
            return ""
        try:
            self.proc.wait(timeout=2)
        except Exception:
            pass
        with self._stderr_lock:
            lines = list(self._stderr)
        return _exit_note(self.proc, lines)

    def attached_source(self):
        """The source the helper is REALLY recording from, or ''.

        Setting PULSE_SOURCE is a request, not a guarantee: a node that
        disappeared between the dropdown and the click, a server that
        does not honour it, an ALSA path that never went through the
        sound server at all - each of those produces a recording that
        works perfectly and listens to the wrong thing. That is the
        worst possible failure for this feature, because the user finds
        out from the people in the instance.

        So the routing is read back out of the audio graph and shown.
        Best effort by design: no pactl, no answer, no harm done.
        """
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return ""
        try:
            from core.backends import mic_pactl
            return mic_pactl.active_source(proc.pid, self.log)
        except Exception:      # noqa: BLE001
            return ""

    def crashed(self):
        """True when the helper died on a signal - the abort this module
        exists for, as opposed to an orderly stop."""
        if self.proc is None or self.proc.returncode is None:
            return False
        return self.proc.returncode < 0

    def stop(self, grace=None):
        """Ask nicely, then insist. A helper wedged inside PortAudio
        never answers, and waiting for it is what used to leave a dead
        recording behind.

        `grace` overrides the polite wait - the app closing down passes
        a short one, because a helper that outlives the window keeps the
        microphone busy for a process nobody can see any more.

        The process object is KEPT afterwards: crashed() and exit_note()
        are the report the user gets, and throwing the handle away here
        would mean the abort this module exists to survive is the one
        thing it cannot describe.
        """
        proc = self.proc
        if proc is None or self.stopped:
            return
        self.stopped = True
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write("stop\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()      # EOF says stop as well
        except Exception:
            pass
        deadline = time.monotonic() + (self.GRACE if grace is None
                                       else max(0.0, float(grace)))
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.05)
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
            return
        except Exception:
            pass
        _kill(proc)


class LevelSession(Session):
    """A helper that only measures - the microphone test.

    Same process, same routing, same kill switch; it just never builds a
    recogniser, so it starts immediately and costs nothing on the
    network. Splitting it out of Session rather than adding a flag keeps
    the recording path from growing a second meaning: this one is
    started and stopped by a button the user is holding, and it must be
    safe to do that fifty times in a row.
    """

    #: nothing is in flight, so there is nothing to wait for
    GRACE = 0.5

    def __init__(self, mic_index=-1, node="", threshold=0, log=None):
        super().__init__(mic_index=mic_index, node=node, log=log,
                         mode="level",
                         sensitivity={"energy_threshold": threshold})


def describe():
    """One line for the log, so a bug report says which path was used."""
    if in_process_forced():
        return f"in-process (forced by {ENV_INPROCESS})"
    argv = helper_argv("list")
    if argv is None:
        return "in-process (no helper available)"
    where = "frozen" if IS_FROZEN else str(helper_script())
    return f"helper process via {os.path.basename(sys.executable)} ({where})"


# also exported for the entry point, which must not import Qt first
__all__ = ["HELPER_FLAG", "LevelSession", "Session", "available",
           "default_device", "describe", "list_devices", "in_process_forced"]