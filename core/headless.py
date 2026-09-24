"""
core/headless.py - terminal mode: the chatbox without a window.

    osc-dreamchatbox --headless          (alias: --terminal)
    osc-dreamchatbox --headless --verbose  (print the log as well)

The idea: you set everything up in the normal window once, and from then
on run the app in a terminal - by hand, or with the "Start in terminal
mode" button on the Options page. It sends exactly what the window would
send - same config, same apps, same plugins, same rate limit - but
without the widget tree, fonts and graphics backend, which is where most
of the memory goes.

How it works (the short version, core/qtstub.py has the long one):
QtWidgets/QtGui are swapped for do-nothing stand-ins BEFORE the ui
package is imported, then the normal MainWindow is created on a plain
QCoreApplication and never shown. QtCore stays real, so the timers, the
worker threads and MPRIS over D-Bus behave exactly as in the window.

The terminal is for commands
----------------------------
The log does NOT go to the terminal: a line every two seconds makes
typing a command impossible. It goes to terminal.log next to the config
(DCB-log opens a second window that follows it). The terminal only shows
what a command answers, plus errors.

Start-up
--------
Hardware, media and VRChat (OSCQuery) are asked right away instead of
waiting for their first timer tick, and NOTHING is sent until they have
answered (or ~20 s passed). Otherwise the first messages in VRChat are
half-empty lines like "GPU °C".

Rules for this mode
-------------------
* The window's settings are not edited here. The only things written to
  config.json are the two a command changes on purpose: Send to VRChat
  (DCB-sendvrc) and the active profile (DCB-profil). Plugin on/off is
  stored by the plugin manager in the plugin's own config, exactly as
  the window does it.
* One sender at a time. Two copies of the app would both write into the
  same chatbox, so terminal mode refuses to start while the window (or
  another terminal copy) is running - core/instancelock.py. --force
  skips that check.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import queue
import signal
import sys
import threading
import time

from core.constants import APP_NAME, CONFIG_DIR, CONFIG_FILE, VERSION

FLAGS = ("--headless", "--terminal")

#: everything the log would have printed goes here instead
LOG_FILE = CONFIG_DIR / "terminal.log"
LOG_MAX_BYTES = 5 * 1024 * 1024

#: give up waiting for hardware/media/VRChat after this long
READY_TIMEOUT_SEC = 20
#: VRChat does not have to be running - don't hold everything for it
VRCHAT_WAIT_SEC = 6

LINE = "-" * 62

USAGE = f"""{APP_NAME} {VERSION} - terminal mode

Usage: osc-dreamchatbox --headless [--profile="name"] [--verbose] [--force]

  --headless, --terminal   run without a window (uses your saved settings)
  --profile="name"         start with this profile (works for the window too;
                           without it, the profile you used last is loaded)
  --verbose                also print the log (normally only in the log file)
  --force                  start even if another copy seems to be running
  --help                   show this help

Set everything up in the normal window first, then close it - or use
Options > General > "Start in terminal mode".
While running, type DCB-help for commands.
"""

#: (section, [(command, help)]) - the order is the order of DCB-help
COMMAND_SECTIONS = (
    ("General", (
        ("DCB-help", "show this list"),
        ("DCB-sendvrc", "Send to VRChat on/off"),
        ("DCB-show", "show what is sent right now"),
        ("DCB-profil", "list profiles and switch to one"),
        ("DCB-plugin-status", "show which plugins are on or off"),
        ("DCB-plugin-off", "switch a plugin off"),
        ("DCB-plugin-on", "switch a plugin on"),
        ("DCB-log", "open the log in a second window"),
        ("DCB-UI", "close terminal mode and open the window"),
        ("DCB-quit", "exit (Ctrl+C works too)"),
    )),
    ("Speech to Text - what YOU say", (
        ("DCB-stt", "start/stop recording your microphone"),
        ("DCB-mic", "choose the microphone"),
        ("DCB-lang", "the language you speak"),
        ("DCB-translate", "translate into ... (or not at all)"),
        ("DCB-ttt", "typed text: translate it too, on/off"),
    )),
    ("Two-way - what OTHERS say", (
        ("DCB-2way", "start/stop listening to the game audio"),
        ("DCB-2way-source", "choose what to listen to (e.g. a monitor)"),
        ("DCB-2way-lang", "the language they speak"),
        ("DCB-2way-translate", "translate them into ..."),
        ("DCB-2way-inline", "show what they say here, on/off"),
        ("DCB-2way-window", "show what they say in a second window"),
        ("DCB-2way-chatbox", "also send it into the chatbox, on/off"),
    )),
)
#: flat (command, help) list
COMMANDS = tuple(c for _title, cmds in COMMAND_SECTIONS for c in cmds)

#: other spellings that mean the same command
ALIASES = {
    "profile": "profil", "profiles": "profil", "profile-list": "profil",
    "plugins": "plugin-status", "plugin": "plugin-status",
    "exit": "quit", "window": "ui", "gui": "ui",
    "microphone": "mic", "language": "lang", "sprache": "lang",
    "twoway": "2way", "2-way": "2way",
}

#: what the others said, one line each - DCB-2way-window follows it
TWOWAY_FILE = CONFIG_DIR / "twoway.log"


def help_text():
    width = max(len(c) for c, _ in COMMANDS)
    lines = ["Commands (upper/lower case does not matter):"]
    for title, cmds in COMMAND_SECTIONS:
        lines.append(f"\n {title}")
        lines += [f"  {c.ljust(width)}   {h}" for c, h in cmds]
    lines.append(f"\n  {'<any text>'.ljust(width)}   "
                 "send it as a chat message (translated with DCB-ttt on)")
    return "\n".join(lines)


class _Toggle:
    """Stands in for a checkable QPushButton whose checked state drives
    the logic - the Speech to Text and Two-way start buttons.

    The window's code asks ``stt_button.isChecked()`` in the middle of
    starting ("did the user click stop while we were checking the
    microphone?") and stops by calling ``setChecked(False)``, relying on
    the button's toggled signal. A do-nothing stand-in answers "not
    checked" to all of that, so recording would never start. This one
    keeps the state and calls the handler on a change, like the signal
    would, and honours blockSignals()."""

    def __init__(self, on_toggled):
        self._on = False
        self._blocked = False
        self._cb = on_toggled
        self.label = ""

    def isChecked(self):                # Qt name
        return self._on

    def setChecked(self, on):
        on = bool(on)
        if on == self._on:
            return
        self._on = on
        if not self._blocked:
            self._cb(on)

    def blockSignals(self, block):
        old, self._blocked = self._blocked, bool(block)
        return old

    def setText(self, text): 
        self.label = str(text)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


class _Line:
    """Stands in for the Text to Text input field: send_ttt() reads the
    text from there and clears it."""

    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def clear(self):
        self._text = ""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


def say(text=""):
    """Everything meant for the person at the terminal goes through
    here. flush: the terminal may be a pipe (IDE, systemd)."""
    print(text, flush=True)


# ------------------------------------------------------------ helpers
def wants_headless(argv):
    """True if the command line asks for terminal mode."""
    return any(a in FLAGS for a in argv)


def _attach_windows_console():
    """A frozen Windows build is a GUI program without a console, so
    print() goes nowhere. Give it a console window of its own.

    A NEW window rather than borrowing the one of the cmd it was typed
    into: a GUI program returns to the cmd prompt immediately, and cmd
    and this app would then fight over every line typed."""
    if sys.stdout is not None and sys.stdin is not None:
        return True
    try:
        import ctypes
        if not ctypes.windll.kernel32.AllocConsole():
            return False
        ctypes.windll.kernel32.SetConsoleTitleW(f"{APP_NAME} - terminal mode")
        # kept open for the life of the process - they ARE stdout/stdin
        sys.stdout = open("CONOUT$", "w", encoding="utf-8",  # noqa: SIM115
                          buffering=1)
        sys.stderr = sys.stdout
        sys.stdin = open("CONIN$", encoding="utf-8")  # noqa: SIM115
        return True
    except Exception:       # noqa: BLE001 - no console is the answer
        return False


def _rss_mb():
    """Resident memory of this process in MB, or None (Linux only)."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


# --------------------------------------------------------------- main
def main(argv, set_process_name=None):
    """Entry point, called from osc_dreamchatbox.main() BEFORE any Qt
    widget module has been imported. Returns the exit code.

    ``set_process_name`` renames this process to APP_NAME (for htop and
    the like)."""
    if "--help" in argv or "-h" in argv:
        say(USAGE)
        return 0
    if sys.platform.startswith("win") and not _attach_windows_console():
        return 2

    say(f"{APP_NAME} {VERSION} - terminal mode")

    # One sender at a time - see core/instancelock.py. Started from the
    # window's button (--wait-pid), the window is closing right now and
    # lets go of the lock the moment it has tidied up: wait for that.
    from core import instancelock
    handover = any(a.startswith("--wait-pid") for a in argv)
    if handover:
        say("Waiting for the window to close ...")
        got = instancelock.wait_and_acquire("terminal", timeout=60)
    else:
        got = instancelock.acquire("terminal")
    if not got and "--force" not in argv:
        say(f"{APP_NAME} is already running - {instancelock.describe_holder()}.\n"
            "Close it first - two copies would both write into the same "
            "chatbox.\n"
            "Start anyway with --force.")
        return 1
    if set_process_name is not None:
        set_process_name()

    # MUST come before anything under ui/ is imported
    from core import qtstub
    if not qtstub.install():
        say("Terminal mode: Qt widgets were already loaded, cannot "
            "start without a window.")
        return 1

    from PyQt6.QtCore import QCoreApplication, QTimer
    app = QCoreApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)

    say("Loading - please wait until everything is ready ...")
    window_cls = _make_window_class()
    win = window_cls(verbose="--verbose" in argv)
    # --profile="name" - before begin_loading(), so hardware/media are
    # asked for what THIS profile shows and nothing is sent before it
    from core import profiles
    wanted = profiles.profile_from_argv(argv)
    if wanted is not None:
        _ok, msg = win.apply_start_profile(wanted)
        win.log(msg)
        say(msg)
    win.begin_loading()

    # --- Ctrl+C / kill -------------------------------------------------
    # Qt's event loop runs in C++, so Python only gets to run its signal
    # handlers when some Python code is executed. The timer below is
    # that code: 4 wake-ups a second, nothing else.
    stop = {"requested": False}

    def _on_signal(signum, _frame):
        stop["requested"] = True
    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    # --- typed commands ------------------------------------------------
    # stdin is read in a thread (readline() blocks) and handed to the Qt
    # thread through a queue; the MainWindow code must only ever run on
    # the thread that created it.
    commands = queue.Queue()

    def _reader():
        while True:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                return
            if not line:        # EOF: no terminal attached (autostart,
                return          # systemd, ...) - just keep running
            commands.put(line.rstrip("\r\n"))
    if sys.stdin is not None:
        threading.Thread(target=_reader, daemon=True,
                         name="headless-stdin").start()

    after = {"action": None}

    def _tick():
        if stop["requested"]:
            app.quit()
            return
        if not win.ready:
            win.loading_tick()
            return              # typed lines wait in the queue until then
        while True:
            try:
                line = commands.get_nowait()
            except queue.Empty:
                break
            action = win.command(line)
            if action in ("quit", "ui"):
                after["action"] = action
                app.quit()
                return

    ticker = QTimer()
    ticker.timeout.connect(_tick)
    ticker.start(250)

    code = app.exec()
    ticker.stop()
    say("\nShutting down ...")
    win.shutdown()
    instancelock.release()       # before the window starts, see below
    if after["action"] == "ui":
        # only now: the chatbox is cleared and the plugins are stopped,
        # so the window starts on a clean slate and never overlaps us
        from core import selflaunch
        ok, msg = selflaunch.start_detached(selflaunch.self_command())
        say("Opening the window ..." if ok
            else f"Could not open the window: {msg}")
    say("Bye.")
    return code


def _make_window_class():
    """Builds the terminal-mode window class. A function, because
    ui.mainwindow may only be imported after qtstub.install()."""
    from core import micgroups, profiles
    from core.atomicfile import write_text_atomic
    from core.oscquery import HAS_ZEROCONF
    from core.speechtotext import (
        LANGUAGES,
        OUTPUT_LANGUAGES,
        SpeechWorker,
        list_microphone_groups,
    )
    from ui.mainwindow import MainWindow

    class HeadlessWindow(MainWindow):
        """The normal MainWindow, never shown."""

        def __init__(self, verbose=False):
            self._verbose = verbose
            self._log_lock = threading.Lock()
            self._log_fh = None
            self._open_log()
            self.ready = False
            #: a numbered list is on screen and waits for a number:
            #: (kind, [items]) - see command()
            self._pick = None
            #: typed text goes through Text to Text (DCB-ttt)
            self._ttt = False
            #: Two-way lines are printed here (DCB-2way-inline)
            self._twoway_inline = True
            self._twoway_fh = None
            #: device id -> name, from the last DCB-mic / DCB-2way-source
            self._dev_labels = {}
            super().__init__()
            # after build_ui(), which put stand-ins there
            self.stt_button = _Toggle(self.on_stt_toggled)
            self.twoway_btn = _Toggle(self.on_twoway_toggled)

        # ============================================================ log
        def _open_log(self):
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                # one file per run: the old one is overwritten on start
                self._log_fh = open(LOG_FILE, "w",  # noqa: SIM115
                                    encoding="utf-8", buffering=1)
            except OSError as e:
                self._log_fh = None
                say(f"(log file not available: {e})")

        def log(self, msg):
            """Called from any thread (plugins, lyrics, OSCQuery), hence
            the lock. The file is the log; the terminal only gets it
            with --verbose, and errors always."""
            msg = str(msg)
            stamp = time.strftime("%H:%M:%S")
            text = f"[{stamp}] " + msg.replace("\n", "\n           ")
            with self._log_lock:
                fh = self._log_fh
                if fh is not None:
                    try:
                        if fh.tell() > LOG_MAX_BYTES:
                            fh.seek(0)
                            fh.truncate()
                            fh.write(f"[{stamp}] (log restarted - it "
                                     "reached its size limit)\n")
                        fh.write(text + "\n")
                    except (OSError, ValueError):
                        pass
            if self._verbose:
                print(text, flush=True)
            elif msg.startswith(("ERROR", "Speech to Text ERROR",
                                 "Two-way ERROR")):
                print("! " + msg, flush=True)

        # ================================================= config safety
        # The window is the editor. Nothing the ui code does in here
        # writes config.json or a profile - only the two commands that
        # change a setting on purpose do, through _patch_config().
        def save_config(self):
            pass

        def save_config_later(self):
            pass

        def _write_config(self):
            pass

        def _save_active_profile(self):
            return True

        def apply_start_profile(self, wanted):
            """--profile: like the window, plus storing the switch -
            save_config() does nothing here, and the next start without
            --profile should come up with this profile too."""
            before = self.active_profile()
            result = super().apply_start_profile(wanted)
            if self.active_profile() != before:
                cfg = self.cfg
                self._patch_config(
                    lambda raw: (raw.clear(), raw.update(cfg)))
            return result

        def _patch_config(self, change):
            """Reads config.json as it is on disk, lets ``change(raw)``
            edit it and writes it back atomically. Starting from the file
            and not from self.cfg means a command can only ever touch
            the key it is about."""
            try:
                raw = (json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                       if CONFIG_FILE.exists() else {})
                change(raw)
                write_text_atomic(CONFIG_FILE, json.dumps(raw, indent=2))
                return True
            except Exception as e:      # noqa: BLE001
                self.log(f"ERROR: could not save the change: {e}")
                return False

        # ============================================ Advanced-mode canvas
        # In the window the canvas is the live copy of a graph and gets
        # written back into cfg["aio_graphs"] (on slot/template/profile
        # switches). Here the canvas is made of stand-ins, so writing it
        # back would replace the real graph with an empty one. The
        # config is the only record in this mode; the evaluation
        # (core/nodegraph_eval.py) reads it straight from there.
        def load_graph_into_ui(self):
            self.graph_slot = 0

        def _show_graph_slot(self, idx):
            self.graph_slot = idx

        def _store_current_graph(self):
            pass

        # ======================================================= start-up
        def begin_loading(self):
            """Asks everything that takes a moment right away, instead
            of on its first timer tick (up to hw_poll_sec later)."""
            self._load_start = time.monotonic()
            self._waiting = []
            if self.cfg.get("hw_active"):
                self._waiting.append("hardware")
            if self.cfg.get("media_active"):
                self._waiting.append("media")
            if (self.cfg.get("oscquery_enabled") and HAS_ZEROCONF
                    and self.oscq_timer.isActive()):
                self._waiting.append("vrchat")
            if "hardware" in self._waiting:
                self.poll_hw()
            if "media" in self._waiting:
                self.poll_media()
            if "vrchat" in self._waiting:
                self.poll_oscquery()
            self.loading_tick()

        def _done(self, what, detail=""):
            if self.ready or what not in self._waiting:
                return
            self._waiting.remove(what)
            say(f"  ✓ {what.capitalize() if what != 'vrchat' else 'VRChat'}"
                + (f" - {detail}" if detail else ""))

        def _on_hw_result(self, info):
            super()._on_hw_result(info)
            self._done("hardware")

        def _on_media_result(self, info):
            super()._on_media_result(info)
            if info:
                self._done("media", f"{info.get('artist', '')} – "
                                    f"{info.get('title', '')}")
            else:
                self._done("media", "nothing playing")

        def poll_oscquery(self):
            super().poll_oscquery()
            if self._oscq_applied is not None:
                self._done("vrchat", "found, OSC port "
                                     f"{self._oscq_applied[1]}")

        def loading_tick(self):
            """Called 4x a second until ready."""
            if self.ready:
                return
            waited = time.monotonic() - self._load_start
            if "vrchat" in self._waiting and waited > VRCHAT_WAIT_SEC:
                self._waiting.remove("vrchat")
                say("  – VRChat not running yet (keeps looking in "
                    "the background)")
            if self._waiting and waited < READY_TIMEOUT_SEC:
                return
            for what in self._waiting:
                say(f"  – {what}: no answer yet, starting anyway")
            self._waiting = []
            self.ready = True
            self.announce()
            self.send_now()

        def send_now(self):
            # nothing goes out while loading - see module doc
            if not getattr(self, "ready", False):
                return
            super().send_now()

        def _target(self):
            client = self.osc_client
            ip = getattr(client, "_address", None) or self.cfg.get("osc_ip")
            port = getattr(client, "_port", None) or self.cfg.get("osc_port")
            return f"{ip}:{port}"

        def announce(self):
            cfg = self.cfg
            apps = [k for k in cfg.get("app_order", [])
                    if cfg.get(f"{'hw' if k == 'hardware' else k}_active")]
            if cfg.get("aio_active"):
                apps = ["All in one"
                        + (" (Advanced)" if cfg.get("aio_mode") == "advanced"
                           else "")]
            plugs = self.plugins.ordered()
            on = sum(1 for p in plugs if p.enabled)
            mem = _rss_mb()
            say(LINE)
            say("  Ready.")
            say(f"  Send to VRChat  "
                f"{'ON' if cfg.get('send_to_vrchat') else 'OFF'}"
                f"  ->  {self._target()} every {cfg.get('interval_sec')} s")
            say(f"  Apps            {', '.join(apps) or '-'}")
            say(f"  Plugins         {on} on, {len(plugs) - on} off")
            say(f"  Profile         {self.active_profile() or '-'}")
            if mem:
                say(f"  Memory          {mem:.0f} MB")
            say(f"  Log             {LOG_FILE}  (DCB-log)")
            say(LINE)
            if not cfg.get("send_to_vrchat"):
                say("  Send to VRChat is OFF - type DCB-sendvrc to start.")
            say("  DCB-help shows all commands.  Ctrl+C quits.")
            say(LINE)

        # ======================================================= commands
        def command(self, line):
            """Runs one typed line. Returns "quit" or "ui" to end."""
            text = line.strip()
            if self._pick is not None:
                self._answer_pick(text)
                return None
            if not text:
                return None
            low = text.lower()
            if low.startswith(("dcb-", "dcb ")):
                name = low[4:].strip().replace(" ", "-")
                return self._run(ALIASES.get(name, name))
            if low in ("help", "quit", "exit", "ui", "log") \
                    or low.startswith("/"):
                # almost certainly meant as a command - sending "help"
                # into the chatbox would be an embarrassing surprise
                say(f"Commands start with DCB-  (e.g. DCB-{low.lstrip('/')})."
                    "  DCB-help lists them all.")
                return None
            if not self.cfg.get("send_to_vrchat"):
                say("Send to VRChat is OFF - not sent. (DCB-sendvrc)")
                return None
            if self._ttt:
                # the window's Text to Text path: translation, notice,
                # "Send as" - _deliver_translation() prints the result
                self.ttt_input = _Line(text)
                self.send_ttt()
                return None
            self.send_manual_text(text)
            say(f"-> chatbox: {text}")
            return None

        def _run(self, name):
            if name == "help":
                say(help_text())
            elif name == "sendvrc":
                self._toggle_send()
            elif name == "profil":
                self._list_profiles()
            elif name == "plugin-status":
                self._plugin_status()
            elif name in ("plugin-off", "plugin-on"):
                self._list_plugins(on=(name == "plugin-on"))
            elif name == "show":
                say(self.build_payload() or "(nothing to send)")
            elif name == "log":
                self._open_log_window()
            elif name in self._SPEECH:
                getattr(self, self._SPEECH[name])()
            elif name == "ui":
                return "ui"
            elif name == "quit":
                return "quit"
            else:
                say(f"Unknown command DCB-{name} - DCB-help lists them all.")
            return None

        # ------------------------------------------------ Send to VRChat
        def _toggle_send(self):
            on = not self.cfg.get("send_to_vrchat")
            self.cfg["send_to_vrchat"] = on
            self._patch_config(lambda raw: raw.__setitem__(
                "send_to_vrchat", on))
            self.update_timers()
            if on:
                self._last_sent_payload = None     # send even if unchanged
                self.send_now()
            else:
                self.pending_send_timer.stop()
                self.clear_chatbox()
            say(f"Send to VRChat: {'ON' if on else 'OFF'}")

        # ---------------------------------------------------- numbered
        def _ask(self, kind, items, lines):
            """Prints a numbered list; the next line typed answers it."""
            for i, text in enumerate(lines, 1):
                say(f"  {i:>2}. {text}")
            self._pick = (kind, items)
            print(f"Number (1-{len(items)}, Enter = cancel): ",
                  end="", flush=True)

        def _answer_pick(self, text):
            kind, items = self._pick
            self._pick = None
            if not text.isdigit() or not 1 <= int(text) <= len(items):
                say("Cancelled." if not text else
                    f"'{text}' is not a number from the list - cancelled.")
                return
            item = items[int(text) - 1]
            if kind == "profile":
                self._switch_to(item)
            elif kind in ("plugin-on", "plugin-off"):
                self._set_plugin(item, kind == "plugin-on")
            else:
                self._picked_speech(kind, item)

        # ----------------------------------------------------- profiles
        def _list_profiles(self):
            names = profiles.list_profiles()
            if not names:
                say("No profiles yet - create them in the window "
                    "(bottom of the sidebar).")
                return
            active = self.active_profile()
            say("Profiles:")
            self._ask("profile", names,
                      [n + ("   <- active" if n == active else "")
                       for n in names])

        def _switch_to(self, name):
            if name == self.active_profile():
                say(f"'{name}' is already active.")
                return
            if not self.switch_profile(name):
                say(f"Could not load '{name}' - see DCB-log.")
                return
            # the window stores the switch too, so the next start (either
            # way) comes up with this profile. self.cfg is exactly what
            # the window would write here: load_config() of the profile.
            cfg = self.cfg
            self._patch_config(lambda raw: (raw.clear(), raw.update(cfg)))
            # the new setup may use hardware/media the old one did not
            if cfg.get("hw_active") and self.hw_info is None:
                self.poll_hw()
            if cfg.get("media_active"):
                self.poll_media()
            say(f"Profile '{name}' loaded.  Send to VRChat: "
                f"{'ON' if cfg.get('send_to_vrchat') else 'OFF'}")

        # ------------------------------------------------------ plugins
        @staticmethod
        def _plugin_state(p):
            if not p.supported:
                return "not for this OS"
            if p.enabled and p.error and not p.loaded:
                return "ON, but failed to load (DCB-log)"
            return "ON" if p.enabled else "off"

        def _plugin_status(self):
            plugs = self.plugins.ordered()
            if not plugs:
                say("No plugins installed - the Plugin Store is in the "
                    "window.")
                return
            width = max(len(p.name) for p in plugs)
            say("Plugins:")
            for p in plugs:
                say(f"  {p.name.ljust(width)}   {self._plugin_state(p)}")

        def _list_plugins(self, on):
            plugs = [p for p in self.plugins.ordered()
                     if p.enabled != on and (p.supported or not on)]
            if not plugs:
                say("No plugin is " + ("off." if on else "on."))
                return
            say("Switch ON:" if on else "Switch OFF:")
            self._ask("plugin-on" if on else "plugin-off",
                      [p.pid for p in plugs], [p.name for p in plugs])

        def _set_plugin(self, pid, on):
            # the window's own handler: persists, loads/unloads, restarts
            # the preview timer
            self.on_plugin_toggled(pid, on)
            p = self.plugins.plugins.get(pid)
            if p is None:
                return
            if on and not p.loaded:
                first = (p.error or "unknown error").strip().splitlines()
                say(f"'{p.name}' could not be loaded: {first[-1]}")
            else:
                say(f"'{p.name}' is now {'ON' if on else 'off'}.")

        # ---------------------------------------------------------- log
        def _open_log_window(self):
            from core import selflaunch
            ok, msg = selflaunch.open_in_terminal(
                selflaunch.log_viewer_command(LOG_FILE),
                keep_open_on_error=False)
            say("Log opened in a new window." if ok
                else f"Could not open a window: {msg}\n"
                     f"The log is here: {LOG_FILE}")

        # ================================================= speech + 2-way
        # Everything below uses the window's own handlers (preflight,
        # helper process, translation, "Send as"); only the widgets they
        # read from are replaced: the two start buttons by _Toggle, the
        # dropdowns by reading cfg directly.
        _SPEECH = {  # noqa: RUF012 - read only
            "stt": "_cmd_stt", "mic": "_cmd_mic", "lang": "_cmd_lang",
            "translate": "_cmd_translate", "ttt": "_cmd_ttt",
            "2way": "_cmd_2way", "2way-source": "_cmd_2way_source",
            "2way-lang": "_cmd_2way_lang",
            "2way-translate": "_cmd_2way_translate",
            "2way-inline": "_cmd_2way_inline",
            "2way-window": "_cmd_2way_window",
            "2way-chatbox": "_cmd_2way_chatbox",
        }

        def _save_keys(self, **values):
            """Stores settings a command changed on purpose."""
            self.cfg.update(values)
            self._patch_config(lambda raw: raw.update(values))

        @staticmethod
        def _lang_name(code, table):
            for name, c in table:
                if c == code:
                    return name
            return code or "-"

        def _speech_ready(self):
            if SpeechWorker.available():
                return True
            say("Speech to Text is not installed - open the window "
                "(DCB-UI), Textbox page, 'Install SpeechRecognition'.")
            return False

        # ---------------------------------------------- Speech to Text
        def _cmd_stt(self):
            if self.stt_button.isChecked():
                self.stt_button.setChecked(False)
                return
            if not self._speech_ready():
                return
            say("Checking the microphone ...")
            self.stt_button.setChecked(True)

        def on_stt_toggled(self, on):
            was = self.stt_recording
            super().on_stt_toggled(on)
            if not on and was:
                say("Speech to Text stopped - the apps send again.")

        def _on_stt_preflight(self, token, result):
            mine = token == getattr(self, "_stt_preflight", 0)
            super()._on_stt_preflight(token, result)
            if not mine:
                return
            if self.stt_recording:
                tgt = self.cfg.get("stt_output", "")
                say(f"Recording - {self._lang_name(self.cfg['stt_language'], LANGUAGES)}"
                    f" -> {self._lang_name(tgt, OUTPUT_LANGUAGES) if tgt else 'no translation'}"
                    f", microphone: {self._dev_name(self.cfg.get('stt_mic', ''))}")
                say("The apps pause while you record. DCB-stt stops.")
            elif result and result[2]:
                say(f"Could not start: {result[2]}")

        def _deliver_translation(self, source_text, final_text, origin):
            super()._deliver_translation(source_text, final_text, origin)
            icon = "(speech)" if origin == "Speech" else "(typed)"
            if final_text and final_text != source_text:
                say(f"{icon} {source_text}  ->  {final_text}")
            else:
                say(f"{icon} {source_text}")

        def _poll_ttt(self, result):
            if not result[1]:
                say("(translation failed - the original was sent; "
                    "DCB-log says why)")
            super()._poll_ttt(result)

        def _restart_if(self, button, what):
            """A changed device/language applies to the next start - so
            a running one is restarted right away."""
            if button.isChecked():
                say(f"Restarting {what} ...")
                button.setChecked(False)
                button.setChecked(True)

        def _device_list(self, kind, monitors_first):
            say("Looking for audio devices ...")
            key = "stt_twoway_source" if kind == "2way-source" else "stt_mic"
            want = self.cfg.get(key, "")
            show_raw = bool(self.cfg.get("stt_mic_show_raw", False))

            def work():
                return list_microphone_groups(
                    self.log, force=True, show_raw=show_raw,
                    selected=want)[0]

            def done(entries):
                order = list(micgroups.GROUP_ORDER)
                if monitors_first:
                    order.remove(micgroups.G_MONITOR)
                    order.insert(0, micgroups.G_MONITOR)
                rows = sorted(entries or [], key=lambda e: order.index(
                    e["group"]) if e["group"] in order else len(order))
                if not rows:
                    say("No audio devices found.")
                    return
                current = micgroups.normalize(want)
                # the list's own names ("Rode NT-USB") are nicer than
                # what label_for_id() can rebuild from a bare id
                self._dev_labels.update({e["id"]: e["label"] for e in rows})
                labels = []
                for e in rows:
                    label = e["label"]
                    group = micgroups.LABELS.get(e["group"], "")
                    if group and e["group"] != micgroups.G_SYSTEM:
                        label += f"   [{group}]"
                    if micgroups.normalize(e["id"]) == current:
                        label += "   <- current"
                    labels.append(label)
                say("Microphones:" if kind == "mic" else
                    "Sources (a 'monitor' is what your speakers play):")
                self._ask(kind, [e["id"] for e in rows], labels)

            self.run_async(work, done, interval=150,
                           on_error=lambda e: say(f"Device scan failed: {e}"))

        def _dev_name(self, eid):
            return self._dev_labels.get(eid) or micgroups.label_for_id(eid)

        def _cmd_mic(self):
            self._device_list("mic", monitors_first=False)

        def _lang_list(self, kind, table, key, extra=()):
            current = self.cfg.get(key, "")
            items = list(extra) + list(table)
            self._ask(kind, [c for _n, c in items],
                      [n + ("   <- current" if c == current else "")
                       for n, c in items])

        def _cmd_lang(self):
            say("Your language:")
            self._lang_list("lang", LANGUAGES, "stt_language")

        def _cmd_translate(self):
            say("Translate what you say / type into:")
            self._lang_list("translate", OUTPUT_LANGUAGES, "stt_output")

        def _cmd_ttt(self):
            self._ttt = not self._ttt
            tgt = self.cfg.get("stt_output", "")
            if self._ttt:
                say("Typed text is now translated into "
                    f"{self._lang_name(tgt, OUTPUT_LANGUAGES) if tgt else '(nothing set - DCB-translate)'}"
                    " before it is sent.")
            else:
                say("Typed text is sent as it is.")

        # ------------------------------------------------------ Two-way
        def _twoway_selected(self):
            # the window reads the dropdown; here there is none, and a
            # stand-in would silently mean "system default"
            return self.cfg.get("stt_twoway_source", "") or ""

        def _cmd_2way(self):
            if self.twoway_btn.isChecked():
                self.twoway_btn.setChecked(False)
                say("Two-way stopped.")
                return
            if not self._speech_ready():
                return
            say("Checking the audio source ...")
            self.twoway_btn.setChecked(True)

        def _on_twoway_preflight(self, token, result):
            mine = token == self._twoway_preflight
            super()._on_twoway_preflight(token, result)
            if not mine:
                return
            if self.twoway_listening:
                say(f"Listening to {self._dev_name(self.cfg.get('stt_twoway_source', ''))}"
                    f" - {self._lang_name(self.cfg.get('stt_twoway_language', 'en-US'), LANGUAGES)}"
                    f" -> {self._twoway_target()}.")
                where = ("shown here" if self._twoway_inline
                         else "in the DCB-2way-window")
                say(f"What they say is {where}. DCB-2way stops.")
            elif result and (result[2] or result[0] is None):
                say(f"Could not start: {result[2] or 'source not available'}")

        def _twoway_append(self, source, translated):
            super()._twoway_append(source, translated)
            stamp = time.strftime("%H:%M")
            if translated and translated != source:
                text = f"[{stamp}] {translated}\n        ({source})"
            else:
                text = f"[{stamp}] {source}"
            try:
                if self._twoway_fh is None:
                    self._twoway_fh = open(TWOWAY_FILE, "w",  # noqa: SIM115
                                           encoding="utf-8", buffering=1)
                self._twoway_fh.write(text + "\n")
            except OSError:
                pass
            if self._twoway_inline:
                say(">> " + text)

        def _cmd_2way_source(self):
            self._device_list("2way-source", monitors_first=True)

        def _cmd_2way_lang(self):
            say("The language the others speak:")
            self._lang_list("2way-lang", LANGUAGES, "stt_twoway_language")

        def _cmd_2way_translate(self):
            say("Translate the others into:")
            self._lang_list("2way-translate",
                            [(n, c) for n, c in OUTPUT_LANGUAGES if c],
                            "stt_twoway_target",
                            extra=[("My language (DCB-lang)", "")])

        def _cmd_2way_inline(self):
            self._twoway_inline = not self._twoway_inline
            say("Two-way lines are " + ("shown here." if self._twoway_inline
                                        else "no longer shown here."))

        def _cmd_2way_window(self):
            from core import selflaunch
            try:
                TWOWAY_FILE.touch()
            except OSError:
                pass
            ok, msg = selflaunch.open_in_terminal(
                selflaunch.log_viewer_command(TWOWAY_FILE),
                keep_open_on_error=False)
            if not ok:
                say(f"Could not open a window: {msg}")
                return
            self._twoway_inline = False
            say("Two-way opens in a second window (not shown here any "
                "more - DCB-2way-inline brings it back).")

        def _cmd_2way_chatbox(self):
            on = not self.cfg.get("stt_twoway_send", False)
            self._save_keys(stt_twoway_send=on)
            if not on:
                self.clear_twoway_text()
            say("Two-way translations go into the chatbox too."
                if on else "Two-way translations stay out of the chatbox.")

        # ---------------------------------------------- numbered answers
        def _picked_speech(self, kind, value):
            if kind == "mic":
                self._save_keys(stt_mic=value)
                say(f"Microphone: {self._dev_name(value)}")
                self._restart_if(self.stt_button, "Speech to Text")
            elif kind == "lang":
                self._save_keys(stt_language=value)
                self.stt.language = value
                say(f"You speak: {self._lang_name(value, LANGUAGES)}")
            elif kind == "translate":
                self._save_keys(stt_output=value)
                self.stt.translate_to = value
                say("Translate into: " + (self._lang_name(value, OUTPUT_LANGUAGES)
                                          if value else "no translation"))
            elif kind == "2way-source":
                self._save_keys(stt_twoway_source=value)
                say(f"Two-way listens to: {self._dev_name(value)}")
                self._restart_if(self.twoway_btn, "Two-way")
            elif kind == "2way-lang":
                self._save_keys(stt_twoway_language=value)
                self.stt_twoway.language = value
                say(f"They speak: {self._lang_name(value, LANGUAGES)}")
            elif kind == "2way-translate":
                self._save_keys(stt_twoway_target=value)
                self.stt_twoway.translate_to = self._twoway_target()
                say(f"Translate them into: {self._twoway_target()}")

        # ================================================== clean exit
        def shutdown(self):
            """The window's closeEvent does all the tidying up (clears
            the chatbox, stops plugins, helpers, OSCQuery, nvidia-smi).
            Its config write is a no-op here."""
            self.closeEvent(None)
            if self._twoway_fh is not None:
                self._twoway_fh.close()
                self._twoway_fh = None
            with self._log_lock:
                if self._log_fh is not None:
                    self._log_fh.close()
                    self._log_fh = None

    return HeadlessWindow
