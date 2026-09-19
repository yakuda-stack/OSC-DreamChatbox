"""
core/emojifont.py – making sure the emoji in the palette have a glyph.

core/emojis.py decides *which* characters the picker offers. This
module answers the other half of the question: whether the font the
widget is drawn with can draw them at all.

The bug this exists for: the picker showed empty cells and the preview
dropped every emoji while plain symbols like ``♡`` came through
fine. Nothing was wrong with the text - it was sent to VRChat intact,
which is why the clocks appeared in-game and not in the window. The
text simply had no glyph in the font Qt had chosen for it.

Two things caused that:

**A family asked for by name.** ``QFont("Sans")`` (and the system
fixed-width font behind the box preview) resolves to one family, and
DejaVu Sans / DejaVu Sans Mono cover the old monochrome symbol blocks -
hearts, card suits, arrows - but stop before U+1F300. Qt does look for
a fallback when a glyph is missing, but on Linux that search goes
through fontconfig, and how far it gets depends on the distro's
configuration; on a minimal Arch install it frequently gets nowhere.
Relying on it is relying on the user's fontconfig being helpful.

**No emoji font installed at all.** No amount of fallback invents a
glyph. Arch does not pull ``noto-fonts-emoji`` in with anything, so a
clean install genuinely has nothing to draw an emoji with.

The fix for the first is `apply()`: Qt 6 takes an ordered list of
families via ``QFont.setFamilies()`` and walks it per character, so
naming an emoji family explicitly puts it in the chain regardless of
what fontconfig would have done. The second cannot be fixed from here,
only reported - `missing_hint()` produces the one line the log needs so
the answer is "install this package" instead of "it is broken".

The candidate list is ordered by how well the family covers current
Unicode, with each platform's built-in first. Only families actually
installed are passed on: a name Qt cannot resolve is not harmless in a
fallback chain, it is a lookup on every miss.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo

from core.osinfo import IS_MACOS, IS_WINDOWS

#: Emoji-capable families, best coverage first. The colour fonts lead
#: because a monochrome fallback is a last resort, not a preference.
_CANDIDATES_WINDOWS = ("Segoe UI Emoji", "Segoe UI Symbol")
_CANDIDATES_MACOS = ("Apple Color Emoji",)
_CANDIDATES_LINUX = (
    "Noto Color Emoji",     # the package every distro ships
    "Twemoji",              # Twitter's, packaged on Arch/Fedora
    "JoyPixels",
    "OpenMoji Color",
    "Segoe UI Emoji",       # a Windows font someone copied over
    "Noto Emoji",           # monochrome, but a glyph beats a blank cell
    "Symbola",
)

_cache = None


def _installed():
    """The candidates this machine actually has, in candidate order.

    Cached: QFontDatabase.families() is a real query and the answer
    cannot change while the app runs.
    """
    global _cache
    if _cache is None:
        if IS_WINDOWS:
            wanted = _CANDIDATES_WINDOWS
        elif IS_MACOS:
            wanted = _CANDIDATES_MACOS + _CANDIDATES_LINUX
        else:
            wanted = _CANDIDATES_LINUX
        have = {f.casefold() for f in QFontDatabase.families()}
        _cache = tuple(f for f in wanted if f.casefold() in have)
    return _cache


def available():
    """True when at least one emoji font is installed."""
    return bool(_installed())


def apply(font):
    """Append the installed emoji families to `font`'s fallback chain.

    Returns the same QFont, so it can be wrapped around a font being
    built:  ``lbl.setFont(emojifont.apply(mono))``.

    The base family stays first - this adds a fallback, it does not
    change what ordinary text is drawn with.
    """
    extra = _installed()
    if not extra:
        return font
    base = [f for f in font.families() if f]
    if len(base) <= 1:
        # A single name may be a fontconfig alias - "Sans", and the
        # "monospace" that QFontDatabase hands back for the system
        # fixed-width font. Qt resolves an alias when it is the font's
        # *family*, and stops resolving it once it is one entry in a
        # families list: asking for ["monospace", <emoji>] draws the
        # box frame in DejaVu Sans, proportional, and the preview stops
        # lining up. QFontInfo reports the family Qt actually picked,
        # so the chain is built from that instead of from the alias.
        base = [QFontInfo(font).family() or font.family()]
    base = [f for f in base if f]
    # never list a family twice: Qt walks the chain in order and a
    # repeat is a second failed lookup for every missing glyph
    seen = {f.casefold() for f in base}
    font.setFamilies(base + [f for f in extra if f.casefold() not in seen])
    return font


def ui_font(family, point_size):
    """The app-wide font: `family` for text, emoji fonts behind it."""
    return apply(QFont(family, point_size))


#: package manager id -> the one command that installs Noto Color Emoji.
#: Keyed by what /etc/os-release reports in ID or ID_LIKE.
_COMMANDS = (
    (("arch", "archlinux", "manjaro", "endeavouros", "cachyos"),
     "sudo pacman -S noto-fonts-emoji"),
    (("debian", "ubuntu", "linuxmint", "pop", "raspbian"),
     "sudo apt install fonts-noto-color-emoji"),
    (("fedora", "rhel", "centos"),
     "sudo dnf install google-noto-emoji-color-fonts"),
    (("opensuse", "suse", "opensuse-tumbleweed", "opensuse-leap"),
     "sudo zypper install noto-coloremoji-fonts"),
    (("gentoo",), "sudo emerge media-fonts/noto-emoji"),
    (("alpine",), "sudo apk add font-noto-emoji"),
    (("void",), "sudo xbps-install -S noto-fonts-emoji"),
)

#: what to suggest when /etc/os-release says nothing we recognise.
#: Arch first because that is who runs this, and because a wrong guess
#: costs a failed command rather than a broken system.
_COMMAND_FALLBACK = "sudo pacman -S noto-fonts-emoji"


def install_command():
    """The command that installs an emoji font on *this* distro.

    Read from /etc/os-release rather than guessed: telling an Ubuntu
    user to run pacman is worse than saying nothing. ID is the distro
    itself, ID_LIKE what it is derived from, so a derivative nobody
    listed still lands on its parent's package manager.
    """
    ids = []
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                key, _, value = line.partition("=")
                if key in ("ID", "ID_LIKE"):
                    ids += value.strip().strip('"').lower().split()
    except OSError:
        pass
    for names, command in _COMMANDS:
        if any(i in names for i in ids):
            return command
    return _COMMAND_FALLBACK


def missing_hint():
    """One log line when nothing can draw an emoji, else ``""``.

    Deliberately names the package rather than the font: the person
    reading this wants the command, not a font family to go looking
    for.
    """
    if available():
        return ""
    if IS_WINDOWS or IS_MACOS:
        return ("No emoji font found - emoji will show as empty boxes. "
                "This is unusual on this platform; a system update or "
                "font repair should restore it.")
    return ("No emoji font found - emoji will show as empty boxes or "
            "blank cells in the picker. Install one: "
            f"{install_command()}")
