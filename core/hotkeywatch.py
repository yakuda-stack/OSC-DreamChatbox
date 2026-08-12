"""
core/hotkeywatch.py – noticing that a key combination was pressed.

The mirror image of core/hotkeys.py: that one presses keys, this one
watches for them. Used by the "Get Hotkey" block, so a graph can react
to a keyboard shortcut the same way it reacts to an avatar parameter -
press F13 and something happens, without VRChat being involved at all.

Watching the keyboard globally is not something an application gets for
free, so there are backends:

  * Windows – a WH_KEYBOARD_LL hook on its own thread with its own
    message pump. Nothing to install.
  * Linux   – python-evdev, reading the keyboard device directly. Needs
              read access to /dev/input, which on most distributions
              means being in the `input` group.

Both keep one thing: the set of key names currently held down. Turning
that into "was pressed" is the graph's job (a rising edge), because the
graph is where the user decides whether they want the press or the hold.

Off unless asked for. A keylogger-shaped feature is not something to
start quietly, and the Options card says as much.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import threading

from core.hotkeys import EVDEV, IS_WINDOWS, VK, parse

try:
    import evdev
    HAS_EVDEV = True
except ImportError:
    evdev = None
    HAS_EVDEV = False

#: evdev code -> our key name. Built from the table in core/hotkeys.py so
#: pressing and watching cannot drift apart on what a key is called.
_EVDEV_NAMES = {code: name for name, code in EVDEV.items()}
#: the left/right pairs collapse onto one name - nobody writes
#: "right shift + m" when they mean "shift + m"
_EVDEV_NAMES.update({
    97: "ctrl", 54: "shift", 100: "alt", 126: "super",
})

#: Windows virtual key -> our key name, same idea
_VK_NAMES = {code: name for name, code in VK.items()}
_VK_NAMES.update({
    0xA0: "shift", 0xA1: "shift", 0xA2: "ctrl", 0xA3: "ctrl",
    0xA4: "alt", 0xA5: "alt", 0x5B: "super", 0x5C: "super",
})


def _vk_name(code):
    name = _VK_NAMES.get(code)
    if name:
        return name
    if 0x30 <= code <= 0x5A:        # 0-9 and A-Z
        return chr(code).lower()
    return f"vk{code:02x}"


class HotkeyListener:
    """The set of keys currently held down, and a test for combinations."""

    def __init__(self, log_fn=print):
        self.log = log_fn
        self._held = set()
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._devices = []
        self._hook = None
        self.error = ""
        self.backend = ""

    # ------------------------------------------------------------ state
    @property
    def running(self):
        return self._running

    def held(self):
        with self._lock:
            return set(self._held)

    def is_pressed(self, combo):
        """True while every key of the combination is down.

        Deliberately "is held", not "was pressed": an edge is a decision
        about what the user wants, and the graph already knows how to
        make one.
        """
        mods, key = parse(combo)
        if mods is None:
            return False
        with self._lock:
            return all(k in self._held for k in mods + [key])

    def _set(self, name, down):
        with self._lock:
            if down:
                self._held.add(name)
            else:
                self._held.discard(name)

    # ------------------------------------------------------------ start
    def start(self):
        if self._running:
            return True
        if IS_WINDOWS:
            ok = self._start_windows()
        else:
            ok = self._start_evdev()
        if ok:
            self._running = True
            self.log(f"Hotkey input: watching via {self.backend}")
        return ok

    def stop(self):
        self._running = False
        for device in self._devices:
            try:
                device.close()
            except Exception:      # noqa: BLE001
                pass
        self._devices = []
        with self._lock:
            self._held.clear()

    def missing_hint(self):
        if IS_WINDOWS:
            return "the keyboard hook could not be installed"
        if not HAS_EVDEV:
            return ("python-evdev is not installed \u2013 "
                    "pip install evdev")
        return ("no readable keyboard under /dev/input \u2013 add your "
                "user to the `input` group and log out once")

    # ------------------------------------------------------------ linux
    def _start_evdev(self):
        self.backend = "evdev"
        if not HAS_EVDEV:
            self.error = self.missing_hint()
            self.log(f"Hotkey input: {self.error}")
            return False
        devices = []
        for path in evdev.list_devices():
            try:
                device = evdev.InputDevice(path)
            except OSError:
                # no permission for this one; others may still work, so
                # this is not the moment to give up
                continue
            caps = device.capabilities()
            keys = caps.get(evdev.ecodes.EV_KEY) or []
            # a mouse also reports EV_KEY (its buttons), so ask for a key
            # that only a keyboard has
            if evdev.ecodes.KEY_A in keys:
                devices.append(device)
            else:
                device.close()
        if not devices:
            self.error = self.missing_hint()
            self.log(f"Hotkey input: {self.error}")
            return False
        self._devices = devices
        self.log(f"Hotkey input: reading {len(devices)} keyboard"
                 f"{'' if len(devices) == 1 else 's'}")
        self._thread = threading.Thread(target=self._loop_evdev, daemon=True)
        self._thread.start()
        return True

    def _loop_evdev(self):
        from select import select
        while self._running or not self._thread:
            devices = self._devices
            if not devices:
                return
            try:
                ready, _, _ = select(devices, [], [], 0.5)
            except (OSError, ValueError):
                return
            for device in ready:
                try:
                    for event in device.read():
                        if event.type != evdev.ecodes.EV_KEY:
                            continue
                        name = _EVDEV_NAMES.get(event.code)
                        if name is None:
                            continue
                        # value 2 is auto-repeat, which is still "held"
                        self._set(name, event.value != 0)
                except OSError:
                    # unplugged mid-session; drop it and carry on
                    self._devices = [d for d in self._devices
                                     if d is not device]

    # ---------------------------------------------------------- windows
    def _start_windows(self):
        self.backend = "keyboard hook"
        self._thread = threading.Thread(target=self._loop_windows,
                                        daemon=True)
        self._thread.start()
        return True

    def _loop_windows(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        WH_KEYBOARD_LL = 13
        WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
        WM_KEYUP, WM_SYSKEYUP = 0x0101, 0x0105

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD),
                        ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int,
                                   wintypes.WPARAM, wintypes.LPARAM)

        def callback(code, wparam, lparam):
            if code >= 0:
                data = ctypes.cast(
                    lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                name = _vk_name(data.vkCode)
                if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self._set(name, True)
                elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                    self._set(name, False)
            # never swallow the key: this watches, it does not intercept
            return user32.CallNextHookEx(None, code, wparam, lparam)

        self._hook_proc = proto(callback)      # kept alive deliberately
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._hook_proc,
            kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            self.error = self.missing_hint()
            self.log(f"Hotkey input: {self.error}")
            return
        # a low-level hook only fires while its thread pumps messages
        msg = wintypes.MSG()
        while self._running or self._hook:
            if not user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if not self._running:
                    break
                import time
                time.sleep(0.02)
                continue
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
