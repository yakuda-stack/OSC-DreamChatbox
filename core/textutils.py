"""
core/textutils.py – text helpers (templates, time formatting)
"""

import re

from core.textstyle import apply_inline, is_inline_marker


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


# ---------------------------------------------------------------------------
# songbar size + time placement
# ---------------------------------------------------------------------------
# where the time is rendered relative to the songbar. Everything except
# TIME_POS_LINE merges time AND bar into ONE line, so the chatbox stays
# at two lines instead of three.
TIME_POS_LINE = "line"       # time on the text line, bar on its own line
TIME_POS_BEFORE = "before"   # 0:27/1:06 ▓▓▓▓░░░░
TIME_POS_AFTER = "after"     # ▓▓▓▓░░░░ 0:27/1:06
TIME_POS_SPLIT = "split"     # 0:27▓▓▓▓░░░░1:06

TIME_POSITIONS = [
    ("Own line \u2013 time with artist/title", TIME_POS_LINE),
    ("Before bar \u2013 0:27/1:06 \u2593\u2593\u2591\u2591", TIME_POS_BEFORE),
    ("After bar \u2013 \u2593\u2593\u2591\u2591 0:27/1:06", TIME_POS_AFTER),
    ("Around bar \u2013 0:27\u2593\u2593\u2591\u25911:06", TIME_POS_SPLIT),
]


def bar_length(size_pct, base_len: int) -> int:
    """Effective songbar length for a size percentage (30-100 %).
    Shorter bars leave room for the time on the same line."""
    pct = min(100, max(30, int(size_pct or 100)))
    return max(4, round(base_len * pct / 100))


def compose_bar_line(bar: str, pos_str: str, len_str: str,
                     time_pos: str) -> str:
    """Merges songbar and time into a SINGLE line according to the
    chosen placement. With TIME_POS_LINE the bar is returned as is
    (the time then lives on the artist/title line)."""
    if not bar:
        return ""
    if time_pos == TIME_POS_BEFORE:
        return f"{pos_str}/{len_str} {bar}"
    if time_pos == TIME_POS_AFTER:
        return f"{bar} {pos_str}/{len_str}"
    if time_pos == TIME_POS_SPLIT:
        return f"{pos_str}{bar}{len_str}"
    return bar


# index used for the user-defined custom style (= after the presets)
CUSTOM_STYLE_INDEX = len(SONGBAR_STYLES)

DEFAULT_CUSTOM_BAR = {"prefix": "[", "filled": "\u2588",
                      "empty": "\u2591", "knob": "", "suffix": "]"}


def make_songbar(frac: float, style: int, length: int = 13,
                 custom: dict | None = None) -> str:
    """Builds the music progress bar in the chosen style.
    frac = progress 0.0 … 1.0, style = index into SONGBAR_STYLES or
    CUSTOM_STYLE_INDEX for the user-defined style.

    Custom style dict: {"prefix", "filled", "empty", "knob", "suffix"}
      - knob EMPTY  -> fill mode:  prefix + filled*n + empty*rest + suffix
      - knob SET    -> knob mode:  prefix + empty*pos + knob + empty*rest
                                   + suffix (the knob travels)"""
    frac = min(1.0, max(0.0, frac))
    if style == CUSTOM_STYLE_INDEX:
        c = dict(DEFAULT_CUSTOM_BAR)
        c.update(custom or {})
        pre, suf = c.get("prefix", ""), c.get("suffix", "")
        filled_ch = c.get("filled") or "\u2588"
        empty_ch = c.get("empty") or "\u2591"
        knob = c.get("knob", "")
        if knob:
            pos = min(length - 1, round(frac * (length - 1)))
            return (pre + empty_ch * pos + knob
                    + empty_ch * (length - 1 - pos) + suf)
        filled = round(frac * length)
        return pre + filled_ch * filled + empty_ch * (length - filled) + suf
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
    "lyric": "lyrics", "songtext": "lyrics", "liedtext": "lyrics",
    "tempicon": "temp_icon", "temp": "temp_icon",
    # live world / clock placeholders (Personal Status)
    "playerin_word": "player_in_world", "playerinworld": "player_in_world",
    "player_count": "player_in_world", "players": "player_in_world",
    "playercount": "player_in_world",
    "world": "group_world", "world_name": "group_world",
    "groupworld": "group_world", "worldname": "group_world",
    "clock": "realtime", "time_now": "realtime", "pctime": "realtime",
    "instancetype": "instance_type", "instance": "instance_type",
    # Power draw in watts. {gpu_watt} reads more naturally than
    # {gpu_power} to most people, so both spellings work.
    "gpu_watt": "gpu_power", "gpu_watts": "gpu_power",
    "gpu_w": "gpu_power", "gpupower": "gpu_power",
    "cpu_watt": "cpu_power", "cpu_watts": "cpu_power",
    "cpu_w": "cpu_power", "cpupower": "cpu_power",
    # Chat / Speech to Text / Text to Text (see the "Send as" dropdown on
    # the Textbox page). {text_input} is what was typed or said,
    # {text_output} what actually goes out - the translation, when there
    # is one. {chat_*}, {stt_*} and {ttt_*} are the same pair narrowed to
    # ONE source, so an All-in-one string can treat a spoken sentence
    # differently from a typed one. They are real names of their own, not
    # aliases - only the spellings below fold onto them.
    "chatinput": "chat_input", "chat_in": "chat_input",
    "chatoutput": "chat_output", "chat_out": "chat_output",
    "chat": "chat_output", "chattext": "chat_output",
    "sttinput": "stt_input", "stt_in": "stt_input",
    "spoken": "stt_input", "said": "stt_input", "heard": "stt_input",
    "sttoutput": "stt_output", "stt_out": "stt_output",
    "tttinput": "ttt_input", "ttt_in": "ttt_input", "typed": "ttt_input",
    "tttoutput": "ttt_output", "ttt_out": "ttt_output",
    "textinput": "text_input", "textoutput": "text_output",
    # Custom Box frame lines (core/boxstyle.py). {box_start} is the line
    # above everything, {box_stop} the one below it.
    "box_top": "box_start", "box_open": "box_start", "boxstart": "box_start",
    "box_end": "box_stop", "box_bottom": "box_stop",
    "box_close": "box_stop", "boxstop": "box_stop",
}


#: {text_t3}, {text_template3}, {text_tpl3_5}, {text_t03} - all the ways
#: of naming "template 3" (and optionally slot 5 inside it). They are
#: folded onto one canonical spelling, text_t<X>[_<N>], so the value side
#: only has to answer one shape. See ui/pages/apps_page.py.
_TEXT_TEMPLATE_RE = re.compile(
    r"^text_(?:t|tpl|template)(\d{1,2})(?:_(\d{1,2}))?$")


def canonical_placeholder(key: str) -> str:
    """The one spelling a placeholder name is looked up under.

    A plain alias table cannot express the template placeholders: ten
    templates times twenty slots is 200 names before counting the three
    ways of writing "template", so they are matched with a pattern and
    normalised here instead.
    """
    key = PLACEHOLDER_ALIASES.get(key, key)
    m = _TEXT_TEMPLATE_RE.match(key)
    if not m:
        return key
    slot = m.group(2)
    return (f"text_t{int(m.group(1))}"
            + (f"_{int(slot)}" if slot is not None else ""))


def substitute_placeholders(template: str, values: dict) -> str:
    """Replaces {placeholders} (case-insensitive) and nothing else.

    Split out of apply_template so the node graph
    (core/nodegraph_eval.py) can resolve a block's text without also
    running the line clean-up on it: a Join separator of " | " has to
    survive until the whole string is assembled, and the tidy pass would
    eat it halfway through.
    """
    def rep(m):
        inner = m.group(1)
        if is_inline_marker(inner):
            # a style marker, not a placeholder name - hand it through
            # untouched or it would be looked up, missed and deleted
            return m.group(0)
        key = canonical_placeholder(
            inner.strip().lower().replace(" ", "_"))
        v = values.get(key)
        return "" if v is None else str(v)
    return re.sub(r"\{([^{}]+)\}", rep, template)


def finish_template(text: str) -> str:
    """The second half of apply_template: inline styles, \\n as a real
    line break, and the per-line tidy that removes what empty
    placeholders left behind."""
    text = apply_inline(text)
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


def apply_template(template: str, values: dict) -> str:
    """Replaces {placeholders} (case-insensitive) and turns \\n into
    real line breaks. Unknown/missing placeholders become empty.

    {super/"word"} and {sub/"word"} are styled rather than substituted -
    see core/textstyle.py. They are resolved after the placeholders, so
    the content can be one: {super/{cpu_usage}} styles the value.
    """
    return finish_template(substitute_placeholders(template, values))


