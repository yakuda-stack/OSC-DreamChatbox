"""
core/theming.py – UI themes, custom colours and background images.

The whole app is styled by the one stylesheet in ui/ui_main.py, so
theming works by substituting a handful of colour tokens in it rather
than touching widgets. Every theme is just a dict of those tokens:

    bg        window background
    panel     sidebar / darker surfaces
    card      card and input background
    inner     nested boxes inside a card
    border    borders and separators
    accent    the highlight colour (buttons, checked states, links)
    accent_hi hover/pressed variant of the accent
    text      primary text
    dim       secondary text
    danger    stop/delete colour

A user can start from a preset and override any token with the colour
picker; overrides are stored per theme so switching presets and coming
back keeps them. A background image is optional and sits behind the
whole window, with the cards drawn semi-transparent on top so the image
stays visible without making text unreadable.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import re
import shutil
from pathlib import Path

from core.constants import CONFIG_DIR

# uploaded backgrounds are copied here so the app does not depend on a
# file the user might move or delete later
BACKGROUND_DIR = CONFIG_DIR / "backgrounds"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# token -> colour of the built-in look. The keys are also the search
# terms used against the stylesheet, so they must stay in sync with
# ui/ui_main.py; _TOKEN_MAP below does that mapping.
DEFAULT_TOKENS = {
    "bg": "#14161c",
    "panel": "#0f1116",
    "card": "#191c24",
    "inner": "#232833",
    "border": "#333947",
    "accent": "#5b8dc9",
    "accent_hi": "#6d9cd4",
    "text": "#e5e9ef",
    "dim": "#7a8290",
    "danger": "#c95b5b",
}

# every literal colour in the stylesheet, mapped to the token it belongs
# to. Anything not listed keeps its hard-coded value.
_TOKEN_MAP = {
    "#14161c": "bg",
    "#101218": "bg",
    "#0f1116": "panel",
    "#0d0f13": "panel",
    "#191c24": "card",
    "#232833": "inner",
    "#2a2f3a": "inner",
    "#2c313c": "inner",
    "#2f3542": "border",
    "#333947": "border",
    "#3a3f4a": "border",
    "#3a4150": "border",
    "#444c5c": "border",
    "#5b8dc9": "accent",
    "#4c7cb5": "accent",
    "#6d9cd4": "accent_hi",
    "#e5e9ef": "text",
    "#e8ecf2": "text",
    "#d7dbe2": "text",
    "#aeb4bf": "dim",
    "#7a8290": "dim",
    "#5a6270": "dim",
    "#c95b5b": "danger",
}

THEMES = {
    "default": {"name": "Default", "tokens": dict(DEFAULT_TOKENS)},
    "carbon": {"name": "Carbon", "tokens": {
        "bg": "#151515", "panel": "#101010", "card": "#1b1b1b",
        "inner": "#242424", "border": "#383838", "accent": "#9aa0a6",
        "accent_hi": "#b9bfc6", "text": "#e8e8e8", "dim": "#8b8b8b",
        "danger": "#c96b6b"}},
    "nebula": {"name": "Nebula", "tokens": {
        "bg": "#16121f", "panel": "#110d19", "card": "#1d1729",
        "inner": "#282038", "border": "#3d3355", "accent": "#8b6ee0",
        "accent_hi": "#a288ef", "text": "#ece7f7", "dim": "#8a80a3",
        "danger": "#d05b8c"}},
    "embers": {"name": "Embers", "tokens": {
        "bg": "#1a1310", "panel": "#140e0b", "card": "#221913",
        "inner": "#2e211a", "border": "#4a3427", "accent": "#e07a3c",
        "accent_hi": "#f0954f", "text": "#f2e6dc", "dim": "#9c8676",
        "danger": "#d0503c"}},
    "grass": {"name": "Grass", "tokens": {
        "bg": "#131a15", "panel": "#0e140f", "card": "#18211a",
        "inner": "#212c23", "border": "#334438", "accent": "#6fae72",
        "accent_hi": "#87c48a", "text": "#e4efe4", "dim": "#7d907f",
        "danger": "#c96b5b"}},
    "ocean": {"name": "Ocean", "tokens": {
        "bg": "#101a20", "panel": "#0b1419", "card": "#152229",
        "inner": "#1d2e37", "border": "#2c4753", "accent": "#3fa9c9",
        "accent_hi": "#57c0df", "text": "#e0eef3", "dim": "#748c96",
        "danger": "#c96b6b"}},
    "rose": {"name": "Rose", "tokens": {
        "bg": "#1c1418", "panel": "#150f12", "card": "#251a1f",
        "inner": "#31232a", "border": "#4b3540", "accent": "#d76a9a",
        "accent_hi": "#e884ae", "text": "#f5e7ee", "dim": "#9b8290",
        "danger": "#d0553c"}},
    "mono": {"name": "Mono", "tokens": {
        "bg": "#0c0c0c", "panel": "#070707", "card": "#141414",
        "inner": "#1d1d1d", "border": "#2e2e2e", "accent": "#f0f0f0",
        "accent_hi": "#ffffff", "text": "#f4f4f4", "dim": "#7d7d7d",
        "danger": "#d06060"}},
}

TOKEN_LABELS = [
    ("accent", "Accent"),
    ("bg", "Window"),
    ("panel", "Sidebar"),
    ("card", "Cards"),
    ("inner", "Inner boxes"),
    ("border", "Borders"),
    ("text", "Text"),
    ("dim", "Secondary text"),
    ("danger", "Stop / delete"),
]


def theme_ids():
    return list(THEMES.keys())


def theme_name(theme_id):
    return THEMES.get(theme_id, THEMES["default"])["name"]


def base_tokens(theme_id):
    """The preset's colours, without the user's overrides."""
    theme = THEMES.get(theme_id) or THEMES["default"]
    return dict(theme["tokens"])


def resolve_tokens(theme_id, overrides=None):
    """Preset colours with the user's per-token overrides applied. An
    override that is not a valid hex colour is ignored rather than
    breaking the whole stylesheet."""
    tokens = base_tokens(theme_id)
    for key, value in (overrides or {}).items():
        if key in tokens and is_hex_colour(value):
            tokens[key] = str(value).lower()
    return tokens


def is_hex_colour(value):
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", str(value or "")))


def _lighten(hex_colour, amount):
    """Nudges a colour towards white – used for the hover variant so a
    custom accent still has a visible hover state."""
    try:
        r = int(hex_colour[1:3], 16)
        g = int(hex_colour[3:5], 16)
        b = int(hex_colour[5:7], 16)
    except (ValueError, IndexError):
        return hex_colour
    f = lambda c: min(255, int(c + (255 - c) * amount))   # noqa: E731
    return f"#{f(r):02x}{f(g):02x}{f(b):02x}"


def build_style(base_style, theme_id="default", overrides=None,
                background="", opacity=0.82):
    """Rewrites the app stylesheet in the chosen colours.

    Works by literal colour substitution, so a theme automatically covers
    every widget the base stylesheet already styles - no widget needs to
    know that theming exists.
    """
    tokens = resolve_tokens(theme_id, overrides)
    # a custom accent without a matching hover colour would look dead
    if (overrides or {}).get("accent") and not (overrides or {}).get("accent_hi"):
        tokens["accent_hi"] = _lighten(tokens["accent"], 0.18)

    out = base_style
    for literal, token in _TOKEN_MAP.items():
        out = out.replace(literal, tokens[token])
        out = out.replace(literal.upper(), tokens[token])

    image = background_path(background)
    if image is not None:
        # the image goes behind everything; cards get a translucent
        # background so it stays visible without hurting readability
        rgba = _rgba(tokens["card"], opacity)
        panel_rgba = _rgba(tokens["panel"], min(1.0, opacity + 0.08))
        out += (
            f"\nQWidget#root {{ border-image: url('{image.as_posix()}')"
            f" 0 0 0 0 stretch stretch; }}\n"
            f"QFrame#card {{ background: {rgba}; }}\n"
            f"QFrame#sidebar {{ background: {panel_rgba}; }}\n")
    return out


def _rgba(hex_colour, alpha):
    try:
        r = int(hex_colour[1:3], 16)
        g = int(hex_colour[3:5], 16)
        b = int(hex_colour[5:7], 16)
    except (ValueError, IndexError):
        return hex_colour
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, alpha)):.2f})"


# --------------------------------------------------------------------
# background images
# --------------------------------------------------------------------
def background_path(name):
    """Resolves a stored background name to a file, or None. Only files
    inside BACKGROUND_DIR are accepted, so a stale config can't make the
    app load something unexpected from elsewhere on disk."""
    name = str(name or "").strip()
    if not name:
        return None
    candidate = BACKGROUND_DIR / Path(name).name
    return candidate if candidate.is_file() else None


def list_backgrounds():
    """Every image the user imported, newest first."""
    if not BACKGROUND_DIR.is_dir():
        return []
    files = [p for p in BACKGROUND_DIR.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def import_background(src_path):
    """Copies an image into the config folder and returns its name.

    Copying rather than referencing means the background survives the
    user moving or deleting the original, which is the usual way a
    'my theme is broken' report happens.
    """
    src = Path(src_path).expanduser()
    if not src.is_file():
        raise ValueError("file not found")
    if src.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"unsupported format ({src.suffix or 'no suffix'})")
    BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKGROUND_DIR / src.name
    stem, suffix, n = target.stem, target.suffix, 1
    while target.exists() and target.stat().st_size != src.stat().st_size:
        target = BACKGROUND_DIR / f"{stem}_{n}{suffix}"
        n += 1
    if not target.exists():
        shutil.copy2(src, target)
    return target.name


def remove_background(name):
    path = background_path(name)
    if path is None:
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False
