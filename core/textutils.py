"""
core/textutils.py – text helpers (templates, time formatting)
"""

import re


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_time_hm(seconds: float) -> str:
    """Time WITHOUT seconds – hours and minutes only (h:mm).
    Used for the music timer, e.g. 0:03 for a 3-minute position."""
    seconds = max(0, int(seconds))
    h, m = divmod(seconds // 60, 60)
    return f"{h}:{m:02d}"


# ---------------------------------------------------------------- songbar
# The 5 selectable music progress-bar styles. Index = config value
# "media_bar_style". Previews are rendered at ~40 % progress.
SONGBAR_STYLES = [
    "[\u2500\u2500\u2500\u25CF\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500]",       # 1  [───●────────]
    "\u2500\u2500\u25A0\u2500\u2500",                                                   # 2  ──■──
    "[\u2588\u2588\u2588\u2588\u2588\u2591\u2591\u2591\u2591\u2591\u2591\u2591]",       # 3  [█████░░░░░░░]
    "\u25B0\u25B0\u25B0\u25B0\u25B0\u25B1\u25B1\u25B1\u25B1\u25B1\u25B1\u25B1",         # 4  ▰▰▰▰▰▱▱▱▱▱▱▱
    "\U0001F3B5\U0001F3B5\U0001F3B5\u2500\u2500\u2500\u2500\u2500\u2500",               # 5  🎵🎵🎵──────
    "\u2593\u2593\u2593\u2593\u2593\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591",   # 6  ▓▓▓▓▓░░░░░░░░ (classic)
]


def make_songbar(frac: float, style: int, length: int = 13) -> str:
    """Builds the music progress bar in the chosen style.
    frac = progress 0.0 … 1.0, style = index into SONGBAR_STYLES."""
    frac = min(1.0, max(0.0, frac))
    if style == 0:      # [───●────────────────]
        pos = min(length - 1, round(frac * (length - 1)))
        return ("[" + "\u2500" * pos + "\u25CF"
                + "\u2500" * (length - 1 - pos) + "]")
    if style == 1:      # ──■──  (compact slider, half length)
        short = max(5, length // 2)
        pos = min(short - 1, round(frac * (short - 1)))
        return "\u2500" * pos + "\u25A0" + "\u2500" * (short - 1 - pos)
    if style == 3:      # ▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱
        filled = round(frac * length)
        return "\u25B0" * filled + "\u25B1" * (length - filled)
    if style == 4:      # 🎵🎵🎵🎵🎵🎵🎵─────────────
        filled = round(frac * length)
        return "\U0001F3B5" * filled + "\u2500" * (length - filled)
    if style == 5:      # ▓▓▓▓▓▓▓▓░░░░░ (classic look)
        filled = round(frac * length)
        return "\u2593" * filled + "\u2591" * (length - filled)
    # default / style 2:  [████████░░░░░░░░░░░░]
    filled = round(frac * length)
    return ("[" + "\u2588" * filled + "\u2591" * (length - filled) + "]")


PLACEHOLDER_ALIASES = {
    "ram_typ": "ram_type", "ramtype": "ram_type",
    "gpu_temperature": "gpu_temp", "cpu_temperature": "cpu_temp",
    "vram": "vram_usage", "ram": "ram_usage",
    "song": "title", "song_title": "title", "songtitle": "title",
    "songbar": "bar",
    "tempicon": "temp_icon", "temp": "temp_icon",
}


def apply_template(template: str, values: dict) -> str:
    """Replaces {placeholders} (case-insensitive) and turns \\n into
    real line breaks. Unknown/missing placeholders become empty."""
    def rep(m):
        key = m.group(1).strip().lower().replace(" ", "_")
        key = PLACEHOLDER_ALIASES.get(key, key)
        v = values.get(key)
        return "" if v is None else str(v)
    text = re.sub(r"\{([^{}]+)\}", rep, template)
    text = text.replace("\\n", "\n")
    out = []
    for ln in text.split("\n"):
        ln = re.sub(r"\s{2,}", " ", ln).strip()
        # tidy up separators left over from empty placeholders,
        # e.g. "GPU:  | Vram | CPU: 27%" -> "GPU: | CPU: 27%"
        ln = re.sub(r"([|:])(\s*[|:])+", r"\1", ln)      # collapse ": |" "| |"
        ln = re.sub(r"^[\s|:\-]+", "", ln)                 # leading separators
        ln = re.sub(r"[\s|:\-]+$", "", ln)                 # trailing separators
        ln = re.sub(r"\s{2,}", " ", ln).strip()
        if ln:
            out.append(ln)
    return "\n".join(out)
