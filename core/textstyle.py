"""
core/textstyle.py – superscript / subscript rendering for chatbox text.

VRChat's chatbox is 144 characters and a handful of lines. Unicode has
modifier letters and sub/superscript digits that read as "small" without
costing extra characters, so a hardware name or a music timer can be
tucked under the line it belongs to instead of eating a whole line.

    normal        hallo            012345689
    superscript   ᴴᴬᴸᴸᴼ            ⁰¹²³⁴⁵⁶⁷⁸⁹
    subscript     ₕₐₗₗₒ            ₀₁₂₃₄₅₆₇₈₉

Unicode does NOT have a complete alphabet for either variant - that is
the whole catch. Superscript has no `q`, subscript is missing a good
half of the letters (b c d f g q w y z). A character without a mapping
is passed through unchanged, so the word simply comes out mixed rather
than mangled.

For those cases a word can be excluded from the conversion by wrapping
it in the KEEP markers::

    Playing _"Quake"_ right now   ->   ᴾᴸᴬʸᴵᴺᴳ Quake ᴿᴵᴳᴴᵀ ᴺᴼᵂ

The markers themselves are removed, so they never reach the chatbox.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import re

STYLE_NORMAL = "normal"
STYLE_SUPER = "super"
STYLE_SUB = "sub"

# what a dropdown offers, in this order. Index = position in the combo,
# value = what lands in the config.
STYLE_CHOICES = (
    ("Normal  \u2013  hallo", STYLE_NORMAL),
    ("Superscript  \u2013  \u1D34\u1D2C\u1D38\u1D38\u1D3C", STYLE_SUPER),
    ("Subscript  \u2013  \u2095\u2090\u2097\u2097\u2092", STYLE_SUB),
)
# same three for a field that only ever holds digits (the music timer)
DIGIT_STYLE_CHOICES = (
    ("Normal  \u2013  0123456789", STYLE_NORMAL),
    ("Superscript  \u2013  \u2070\u00B9\u00B2\u00B3\u2074\u2075\u2076"
     "\u2077\u2078\u2079", STYLE_SUPER),
    ("Subscript  \u2013  \u2080\u2081\u2082\u2083\u2084\u2085\u2086"
     "\u2087\u2088\u2089", STYLE_SUB),
)

# the marker that switches the conversion off for one word:  _"Quake"_
KEEP_RE = re.compile(r'_"([^"]*)"_')
KEEP_HINT = '_"word"_'

# --------------------------------------------------------------------
# the maps
# --------------------------------------------------------------------
# Superscript uses the modifier CAPITALS where Unicode has them, because
# they line up in height; the six letters that only exist as small
# modifiers (c f s x y z) fall back to those and still read fine. Both
# cases map to the same glyph - there is no lowercase set to speak of.
_SUPER_LETTERS = {
    "a": "\u1D2C", "b": "\u1D2E", "c": "\u1D9C", "d": "\u1D30",
    "e": "\u1D31", "f": "\u1DA0", "g": "\u1D33", "h": "\u1D34",
    "i": "\u1D35", "j": "\u1D36", "k": "\u1D37", "l": "\u1D38",
    "m": "\u1D39", "n": "\u1D3A", "o": "\u1D3C", "p": "\u1D3E",
    # q has no superscript form at all - hence the KEEP markers
    "r": "\u1D3F", "s": "\u02E2", "t": "\u1D40", "u": "\u1D41",
    "v": "\u2C7D", "w": "\u1D42", "x": "\u02E3", "y": "\u02B8",
    "z": "\u1DBB",
}
_SUPER_DIGITS = {
    "0": "\u2070", "1": "\u00B9", "2": "\u00B2", "3": "\u00B3",
    "4": "\u2074", "5": "\u2075", "6": "\u2076", "7": "\u2077",
    "8": "\u2078", "9": "\u2079",
}
_SUPER_EXTRA = {"+": "\u207A", "-": "\u207B", "=": "\u207C",
                "(": "\u207D", ")": "\u207E", "/": "\u141F"}

_SUB_LETTERS = {
    "a": "\u2090", "e": "\u2091", "h": "\u2095", "i": "\u1D62",
    "j": "\u2C7C", "k": "\u2096", "l": "\u2097", "m": "\u2098",
    "n": "\u2099", "o": "\u2092", "p": "\u209A", "r": "\u1D63",
    "s": "\u209B", "t": "\u209C", "u": "\u1D64", "v": "\u1D65",
    "x": "\u2093",
    # no b c d f g q w y z - they stay as they are
}
_SUB_DIGITS = {
    "0": "\u2080", "1": "\u2081", "2": "\u2082", "3": "\u2083",
    "4": "\u2084", "5": "\u2085", "6": "\u2086", "7": "\u2087",
    "8": "\u2088", "9": "\u2089",
}
_SUB_EXTRA = {"+": "\u208A", "-": "\u208B", "=": "\u208C",
              "(": "\u208D", ")": "\u208E"}

_MAPS = {
    STYLE_SUPER: (_SUPER_LETTERS, _SUPER_DIGITS, _SUPER_EXTRA),
    STYLE_SUB: (_SUB_LETTERS, _SUB_DIGITS, _SUB_EXTRA),
}


def normalize(style):
    """Anything unknown (older config, typo) means 'leave it alone'."""
    style = str(style or STYLE_NORMAL).strip().lower()
    return style if style in (STYLE_NORMAL, STYLE_SUPER, STYLE_SUB) \
        else STYLE_NORMAL


def _convert(text, style, digits_only):
    letters, digits, extra = _MAPS[style]
    out = []
    for ch in text:
        if ch.isdigit():
            out.append(digits.get(ch, ch))
        elif digits_only:
            out.append(ch)
        else:
            out.append(letters.get(ch.lower()) or extra.get(ch) or ch)
    return "".join(out)


def apply_style(text, style, digits_only=False):
    """Converts text, honouring the _"keep me"_ markers.

    digits_only is for fields that are numbers by definition (the music
    timer): letters are left alone there, so a stray unit or a slash
    keeps its normal shape instead of turning into a modifier letter.
    """
    text = "" if text is None else str(text)
    style = normalize(style)
    if style == STYLE_NORMAL or not text:
        # the markers are a formatting instruction, not content - strip
        # them even when nothing is converted, or they end up in VRChat
        return KEEP_RE.sub(r"\1", text)

    out = []
    pos = 0
    for match in KEEP_RE.finditer(text):
        out.append(_convert(text[pos:match.start()], style, digits_only))
        out.append(match.group(1))          # kept verbatim
        pos = match.end()
    out.append(_convert(text[pos:], style, digits_only))
    return "".join(out)


def unsupported(text, style, digits_only=False):
    """Characters this style cannot render, ignoring kept words.

    The UI uses this for a quiet warning next to the dropdown - it is
    much easier to see 'q cannot be converted' than to squint at the
    preview and wonder why one letter looks wrong.
    """
    style = normalize(style)
    if style == STYLE_NORMAL or not text:
        return []
    letters, digits, extra = _MAPS[style]
    stripped = KEEP_RE.sub("", str(text))
    missing = []
    for ch in stripped:
        if ch.isspace() or ch.isdigit():
            continue
        if digits_only or ch in extra or not ch.isalpha():
            continue
        if ch.lower() not in letters and ch not in missing:
            missing.append(ch)
    return missing


def preview(style, sample="hallo"):
    """Small live sample for a tooltip."""
    return apply_style(sample, style)


# --------------------------------------------------------------------
# inline markers:  {super/"word"}   {sub/"word"}
# --------------------------------------------------------------------
# The dropdowns style a whole field. These style one word inside a
# custom string instead, so a hardware line can read
#
#     GPU 68% ⱽᴿᴬᴹ 9.1G      from      GPU {gpu_usage} {super/"vram"} …
#
# without a second field and a second dropdown for every part of it.
#
# The quotes are optional and stripped when present, because a word with
# a trailing space is a real thing to want ({super/"gpu "}) and there is
# no other way to write it - everything outside the quotes is trimmed.
INLINE_RE = re.compile(
    r'\{\s*(super(?:script)?|sup|sub(?:script)?)\s*/\s*([^{}]*?)\s*\}',
    re.IGNORECASE)

#: matches only the opening part, so apply_template() can recognise a
#: style marker and leave it for apply_inline() instead of treating it
#: as an unknown placeholder and deleting it
INLINE_KEY_RE = re.compile(
    r'^\s*(super(?:script)?|sup|sub(?:script)?)\s*/', re.IGNORECASE)

INLINE_HINT = '{super/"word"}  {sub/"word"}'

# --------------------------------------------------------------------
# region tags:  {sup}...{/sup}   {sub}...{/sub}
# --------------------------------------------------------------------
# The slash form above styles ONE piece of content. That falls apart as
# soon as the region should span several placeholders and the text
# between them:
#
#     {super/{gpu_usage}} {super/"|"} {super/{gpu_temp}}     three markers
#     {sup}{gpu_usage} | {gpu_temp}{/sup}                    one region
#
# It also cannot survive a value that contains a brace, because the slash
# form has to stop at the first closing one. So the two forms coexist:
# the slash form for a single word, the region tags for a stretch.
#
# An unclosed tag styles everything to the end of the string rather than
# being dropped. Forgetting {/sup} in a 300 character field is easy, and
# "the rest came out small" is a mistake you can see and fix instantly -
# a marker that silently did nothing is not.
_STYLE_WORD = r"(?:super(?:script)?|sup|sub(?:script)?)"
REGION_TAG_RE = re.compile(
    r"\{\s*(/?)\s*(" + _STYLE_WORD + r")\s*\}", re.IGNORECASE)

#: recognises a bare {sup} / {/sup} so apply_template() leaves it alone
#: instead of looking it up as a placeholder name and deleting it
REGION_KEY_RE = re.compile(
    r"^\s*/?\s*" + _STYLE_WORD + r"\s*$", re.IGNORECASE)

REGION_HINT = '{sup}text{/sup}  {sub}text{/sub}'


def apply_regions(text):
    """Converts every {sup}...{/sup} / {sub}...{/sub} region.

    Written as a scan rather than one regex because the interesting part
    is the text BETWEEN the tags, and a nesting-free left-to-right walk
    says exactly what happens: a tag switches the current style on or
    off, everything passed over on the way is converted with whatever is
    active. Tags are always removed, styled or not.
    """
    if not text or "{" not in text:
        return text
    out = []
    pos = 0
    style = None
    for m in REGION_TAG_RE.finditer(text):
        chunk = text[pos:m.start()]
        out.append(apply_style(chunk, style) if style else chunk)
        pos = m.end()
        if m.group(1):                      # a closing tag
            style = None
        else:
            style = STYLE_SUB if m.group(2).lower().startswith("sub") \
                else STYLE_SUPER
    tail = text[pos:]
    out.append(apply_style(tail, style) if style else tail)
    return "".join(out)


def apply_inline(text):
    """Converts every {super/…} / {sub/…} marker in ``text``.

    Runs after the placeholders are filled in, so the content can come
    from one: ``{super/{cpu_usage}}`` styles whatever the value turned
    out to be. Unmappable characters pass through unchanged, exactly as
    with the field dropdowns, and the _"keep me"_ markers work inside a
    marker too.
    """
    if not text or "{" not in text:
        return text

    def rep(match):
        style = STYLE_SUB if match.group(1).lower().startswith("sub") \
            else STYLE_SUPER
        content = match.group(2)
        if len(content) >= 2 and content[0] == '"' and content[-1] == '"':
            content = content[1:-1]
        return apply_style(content, style)

    # The slash form first: it is the innermost of the two, so a
    # {super/"x"} sitting inside a {sup} region is already a finished
    # string by the time the region walk reaches it. (Converting an
    # already converted character is harmless anyway - modifier letters
    # are not in the maps and pass straight through.)
    return apply_regions(INLINE_RE.sub(rep, text))


def is_inline_marker(inner):
    """True for the inside of a ``{...}`` that is a style marker rather
    than a placeholder name - either form.

    apply_template() deletes what it cannot resolve, so without this a
    bare {sup} would be gone before apply_inline() ever saw it.
    """
    inner = inner or ""
    return bool(INLINE_KEY_RE.match(inner) or REGION_KEY_RE.match(inner))
