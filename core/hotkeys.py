"""
core/hotkeys.py – pressing a key combination at the operating system.

Used by the "Send Hotkey" block on the Advanced canvas: an avatar
parameter flips, and something outside VRChat is supposed to react -
Discord's push-to-mute, OBS, a media key. The chatbox cannot do that, a
keystroke can.

There is no portable way to do this, so there are backends:

  * Windows – SendInput through ctypes. No dependency, works everywhere.
  * X11     – xdotool, which takes the combination verbatim.
  * Wayland – wtype, or ydotool where a compositor refuses synthetic
              input from anything but the uinput device.

The backend is picked once and remembered. When none is available the
block says so in the log ONCE per run rather than per frame - a message
that repeats twice a second is not a message, it is noise.

Key names are the ones people write: "ctrl+shift+m", "F13", "alt+F4".
Case and spaces do not matter, and the modifier order does not either.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform.startswith("win")

#: what counts as a modifier, in the spelling each backend wants
MODIFIERS = {
    "ctrl": ("ctrl", "ctrl"), "control": ("ctrl", "ctrl"),
    "strg": ("ctrl", "ctrl"),          # the German keyboard says Strg
    "alt": ("alt", "alt"),
    "altgr": ("alt", "alt"),
    "shift": ("shift", "shift"),
    "umschalt": ("shift", "shift"),    # ... and Umschalt
    "super": ("super", "logo"), "win": ("super", "logo"),
    "meta": ("super", "logo"), "cmd": ("super", "logo"),
}

#: Windows virtual key codes for everything that is not a plain letter
#: or digit (those are their own ASCII value).
VK = {
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "super": 0x5B,
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "space": 0x20,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "delete": 0x2E,
    "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21,
    "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25,
    "right": 0x27, "printscreen": 0x2C, "pause": 0x13,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "medianext": 0xB0, "mediaprev": 0xB1, "mediastop": 0xB2,
    "mediaplay": 0xB3,
}
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})     # F1 = 0x70 … F24

#: Virtual keys that live on the "extended" half of the keyboard. Without
#: KEYEVENTF_EXTENDEDKEY these arrive as their numpad twins - a Delete
#: turns into a decimal point, Home into a 7 - because the scan codes are
#: shared and only that flag tells them apart.
VK_EXTENDED = {
    0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22,                 # Ins Del Home End PgUp PgDn
    0x25, 0x26, 0x27, 0x28,                             # arrows
    0x90, 0x2C, 0x6F, 0xA3, 0xA5,                       # NumLock Print / RCtrl RAlt
    0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3,           # volume + media
}

#: X11 / xkb keysym names, which are case sensitive in a way people
#: writing "f13" or "escape" are not. xdotool and wtype both take these,
#: so a combination has to be translated before it is handed over -
#: `xdotool key f13` fails silently-ish where `xdotool key F13` works.
XKEYSYM = {
    "ctrl": "ctrl", "alt": "alt", "shift": "shift", "super": "super",
    "logo": "super",
    "enter": "Return", "return": "Return", "tab": "Tab", "space": "space",
    "esc": "Escape", "escape": "Escape", "backspace": "BackSpace",
    "delete": "Delete", "insert": "Insert", "home": "Home", "end": "End",
    "pageup": "Prior", "pagedown": "Next", "up": "Up", "down": "Down",
    "left": "Left", "right": "Right", "printscreen": "Print",
    "pause": "Pause", "menu": "Menu", "capslock": "Caps_Lock",
    "volumemute": "XF86AudioMute", "volumedown": "XF86AudioLowerVolume",
    "volumeup": "XF86AudioRaiseVolume", "mediaplay": "XF86AudioPlay",
    "mediastop": "XF86AudioStop", "mediaprev": "XF86AudioPrev",
    "medianext": "XF86AudioNext",
    "plus": "plus", "minus": "minus", "comma": "comma",
    "period": "period", "slash": "slash",
}
XKEYSYM.update({f"f{i}": f"F{i}" for i in range(1, 25)})

#: Linux input event codes (include/uapi/linux/input-event-codes.h), for
#: ydotool - the only backend that speaks in raw codes.
EVDEV = {
    "esc": 1, "escape": 1, "backspace": 14, "tab": 15, "enter": 28,
    "return": 28, "ctrl": 29, "shift": 42, "alt": 56, "space": 57,
    "super": 125, "logo": 125, "delete": 111, "insert": 110,
    "home": 102, "end": 107, "pageup": 104, "pagedown": 109,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "volumemute": 113, "volumedown": 114, "volumeup": 115,
    "mediaplay": 164, "mediastop": 166, "mediaprev": 165,
    "medianext": 163,
}
EVDEV.update(dict(zip("1234567890", range(2, 12))))
EVDEV.update(dict(zip("qwertyuiop", range(16, 26))))
EVDEV.update(dict(zip("asdfghjkl", range(30, 39))))
EVDEV.update(dict(zip("zxcvbnm", range(44, 51))))
EVDEV.update({f"f{i}": 58 + i for i in range(1, 11)})     # F1 = 59 … F10
EVDEV.update({"f11": 87, "f12": 88})
EVDEV.update({f"f{i}": 170 + i for i in range(13, 25)})   # F13 = 183 … F24


def to_keysym(name):
    """One key name in the spelling X wants. Unknown single characters
    pass through as themselves, which is right for letters and digits."""
    return XKEYSYM.get(name, name)


def describe(combo):
    """A one-line verdict on a combination, for the inspector.

    Returns (ok, text). Written for someone who just typed something and
    wants to know whether it will do anything, so the failure cases say
    what is wrong rather than just "invalid".
    """
    raw = str(combo or "").strip()
    if not raw:
        return False, "No combination set."
    mods, key = parse(raw)
    if mods is None:
        return False, ("Only modifiers \u2013 add an actual key, "
                       "e.g. ctrl+shift+m.")
    pretty = " + ".join([m.capitalize() for m in mods] + [to_keysym(key)])
    if not mods:
        return True, f"Single key: {pretty}"
    return True, f"Combination: {pretty}"


def parse(combo):
    """"ctrl+Shift+M" -> (["ctrl", "shift"], "m").

    Returns (None, "") when there is no actual key, only modifiers -
    "ctrl+shift" is not a hotkey, it is half of one, and firing it would
    do nothing while looking like it worked.
    """
    parts = [p.strip().lower() for p in str(combo or "").replace(" ", "")
             .split("+") if p.strip()]
    mods, key = [], ""
    for part in parts:
        if part in MODIFIERS:
            name = MODIFIERS[part][0]
            if name not in mods:
                mods.append(name)
        else:
            key = part
    if not key:
        return None, ""
    return mods, key


# ---------------------------------------------------------------------------
class HotkeySender:
    """Picks a backend once and sends combinations through it."""

    def __init__(self, log_fn=print):
        self.log = log_fn
        self._backend = None
        self._checked = False
        self._complained = False

    # -------------------------------------------------------- backend
    @property
    def backend(self):
        if not self._checked:
            self._checked = True
            self._backend = self._detect()
            if self._backend:
                self.log(f"Hotkeys: using {self._backend}")
        return self._backend

    def _detect(self):
        if IS_WINDOWS:
            try:
                import ctypes           # noqa: F401
                return "sendinput"
            except ImportError:
                return None
        # X11 first: xdotool is the one that needs no daemon and no
        # special permissions, so it is the least surprising when it
        # happens to be there.
        for tool, name in (("xdotool", "xdotool"), ("wtype", "wtype"),
                           ("ydotool", "ydotool")):
            if shutil.which(tool):
                return name
        return None

    def available(self):
        return self.backend is not None

    def missing_hint(self):
        if IS_WINDOWS:
            return "no way to send keys on this system"
        return ("no key tool found \u2013 install xdotool (X11), wtype "
                "(Wayland) or ydotool")

    # ----------------------------------------------------------- send
    def send(self, combo):
        """Presses and releases the combination. Returns (ok, message)."""
        mods, key = parse(combo)
        if mods is None:
            return False, f"{combo!r} has no key in it"
        backend = self.backend
        if backend is None:
            if not self._complained:
                self._complained = True
                self.log(f"Hotkeys: {self.missing_hint()}")
            return False, self.missing_hint()
        try:
            if backend == "sendinput":
                return self._send_windows(mods, key)
            if backend == "xdotool":
                combination = "+".join([to_keysym(m) for m in mods]
                                       + [to_keysym(key)])
                return self._run(["xdotool", "key", "--clearmodifiers",
                                  combination])
            if backend == "wtype":
                cmd = ["wtype"]
                for m in mods:
                    cmd += ["-M", to_keysym(m)]
                cmd += ["-k", to_keysym(key)]
                for m in mods:
                    cmd += ["-m", to_keysym(m)]
                return self._run(cmd)
            if backend == "ydotool":
                return self._send_ydotool(mods, key)
        except Exception as e:      # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"
        return False, "no backend"

    @staticmethod
    def _run(cmd):
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=5, check=False)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "").strip() \
                or f"{cmd[0]} exited {result.returncode}"
        return True, ""

    def _send_ydotool(self, mods, key):
        codes = []
        for name in mods + [key]:
            code = EVDEV.get(name)
            if code is None:
                return False, f"ydotool does not know the key {name!r}"
            codes.append(code)
        # press in order, release in reverse - a modifier released before
        # the key it modifies is a different keystroke
        seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
        return self._run(["ydotool", "key"] + seq)

    def _send_windows(self, mods, key):
        """SendInput, with the scan code and the extended-key flag filled
        in.

        keybd_event with a zero scan code is enough for a normal text
        field and not enough for anything that reads the keyboard
        properly: a lot of games and some overlays look at the scan code
        and ignore the virtual key entirely, and the extended flag is
        what keeps Delete from arriving as a numpad decimal point.
        """
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002
        INPUT_KEYBOARD = 1
        MAPVK_VK_TO_VSC = 0

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT(ctypes.Structure):
            class _U(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        def vk_of(name):
            if name in VK:
                return VK[name], False
            if len(name) == 1:
                # VkKeyScanW so a layout that puts the character
                # somewhere else still hits the right physical key. The
                # high byte says which modifiers the layout needs for it,
                # and bit 0 is shift - without that, "?" on a German
                # keyboard would come out as a plain "ß".
                scan = user32.VkKeyScanW(ctypes.c_wchar(name))
                if scan != -1:
                    return scan & 0xFF, bool((scan >> 8) & 1)
            return None, False

        codes = [VK[m] for m in mods if m in VK]
        code, needs_shift = vk_of(key)
        if code is None:
            return False, f"unknown key {key!r}"
        if needs_shift and VK["shift"] not in codes:
            codes.append(VK["shift"])
        codes.append(code)

        def event(vk, up):
            flags = KEYEVENTF_KEYUP if up else 0
            if vk in VK_EXTENDED:
                flags |= KEYEVENTF_EXTENDEDKEY
            return INPUT(type=INPUT_KEYBOARD,
                         ki=KEYBDINPUT(wVk=vk,
                                       wScan=user32.MapVirtualKeyW(
                                           vk, MAPVK_VK_TO_VSC),
                                       dwFlags=flags, time=0,
                                       dwExtraInfo=None))

        # press in order, release in reverse - a modifier released before
        # the key it modifies is a different keystroke
        events = [event(c, False) for c in codes] + \
                 [event(c, True) for c in reversed(codes)]
        array = (INPUT * len(events))(*events)
        sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
        if sent != len(events):
            # the usual cause: the window with focus runs elevated and
            # this app does not, so Windows drops the input silently
            return False, ("Windows rejected the keystroke \u2013 the "
                           "focused window is probably running as "
                           "administrator")
        return True, ""
