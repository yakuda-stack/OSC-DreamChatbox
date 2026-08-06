"""
core/emojis.py – the palette behind the emoji picker.

Everything here is data. The picker itself lives in ui/ui_main.py.

Two rules decided what got in, and both come from the chatbox rather
than from taste:

**No ZWJ sequences, no flags, no skin tone modifiers.** A "family" emoji
is five codepoints glued together with zero-width joiners; a flag is two
regional indicators. VRChat's chatbox font renders a good part of them as
tofu, and where it does not, the sequence still costs its full length
against the 144 characters. A single-codepoint emoji costs one. So the
palette is built from single codepoints wherever a single codepoint
exists.

**Variation selectors are kept where the character needs one.** ``❤`` and
``❤️`` are different strings: without U+FE0F many fonts draw the older
monochrome glyph. Those entries cost two characters instead of one, which
is why `cost()` exists and why the picker puts it in the tooltip - with
144 characters to spend, "this one costs double" is worth knowing before
you pick it rather than after.

Categories are ordered the way someone hunting for an icon would look,
not alphabetically: faces first, because that is what most people are
after.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later


def _split(block: str):
    """A category written as one space-separated string. Multi-codepoint
    entries survive because the separator is a space and none of them
    contain one."""
    return [e for e in block.split() if e]


# --------------------------------------------------------------------
# the categories:  (name, tab icon, [emoji, ...])
# --------------------------------------------------------------------
SMILEYS = _split(
    "😀 😃 😄 😁 😆 😅 🤣 😂 🙂 🙃 😉 😊 😇 🥰 😍 🤩 😘 😗 😚 😙 "
    "😋 😛 😜 🤪 😝 🤑 🤗 🤭 🤫 🤔 🤐 🤨 😐 😑 😶 😏 😒 🙄 😬 😌 "
    "😔 😪 🤤 😴 😷 🤒 🤕 🤢 🤮 🤧 🥵 🥶 🥴 😵 🤯 🤠 🥳 😎 🤓 🧐 "
    "😕 😟 🙁 😮 😯 😲 😳 🥺 😦 😧 😨 😰 😥 😢 😭 😱 😖 😣 😞 😓 "
    "😩 😫 🥱 😤 😡 😠 🤬 😈 👿 💀 💩 🤡 👹 👺 👻 👽 👾 🤖 "
    "😺 😸 😹 😻 😼 😽 🙀 😿 😾 🙈 🙉 🙊")

GESTURES = _split(
    "👋 🤚 🖐 ✋ 🖖 👌 🤌 🤏 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👍 👎 "
    "✊ 👊 🤛 🤜 👏 🙌 👐 🤲 🤝 🙏 💅 🤳 💪 🦾 🦿 🦵 🦶 👂 🦻 👃 "
    "🧠 🫀 🫁 🦷 🦴 👀 👁 👅 👄 💋 👶 🧒 👦 👧 🧑 👨 👩 🧓 👴 👵 "
    "🧙 🧚 🧛 🧜 🧝 🧞 🧟 👼 🎅 🤶 👸 🤴 🥷 🦸 🦹")

HEARTS = _split(
    "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💟 ♥️ "
    "💌 💐 🌹 🥀 🌷 🌸 🌺 🌻 🌼 💮 🏵️ 🌟 ⭐ 🌠 💫 ✨ 💥 💢 💦 💨 "
    "🕳 💤 🗨 💬 💭 🗯")

ANIMALS = _split(
    "🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🐔 🐧 🐦 🐤 🦆 "
    "🦅 🦉 🦇 🐺 🐗 🐴 🦄 🐝 🐛 🦋 🐌 🐞 🐜 🦗 🕷 🦂 🐢 🐍 🦎 🐙 "
    "🦑 🦐 🦀 🐡 🐠 🐟 🐬 🐳 🐋 🦈 🐊 🐅 🐆 🦓 🦍 🐘 🦛 🦏 🐪 🐫 "
    "🦒 🦘 🐃 🐄 🐎 🐖 🐑 🦙 🐐 🦌 🐕 🐩 🐈 🐓 🦃 🦚 🦜 🦢 🕊 🐇 "
    "🦝 🦡 🐁 🐀 🐿 🦔 🐾 🐉 🐲 🦕 🦖")

NATURE = _split(
    "🌵 🎄 🌲 🌳 🌴 🌱 🌿 ☘️ 🍀 🎍 🎋 🍃 🍂 🍁 🍄 🌾 🐚 🌍 🌎 🌏 "
    "🌕 🌖 🌗 🌘 🌑 🌒 🌓 🌔 🌙 🌚 🌛 🌜 🌝 🌞 ☀️ 🌤 ⛅ 🌥 ☁️ 🌦 "
    "🌧 ⛈ 🌩 🌨 ❄️ ☃️ ⛄ 🌬 💨 🌪 🌫 🌈 ☂️ ☔ ⚡ 🔥 💧 🌊 ☄️ 🌡")

FOOD = _split(
    "🍏 🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🫐 🍈 🍒 🍑 🥭 🍍 🥥 🥝 🍅 🍆 🥑 "
    "🥦 🥬 🥒 🌶 🌽 🥕 🧄 🧅 🥔 🍠 🥐 🥯 🍞 🥖 🥨 🧀 🥚 🍳 🧈 🥞 "
    "🧇 🥓 🥩 🍗 🍖 🌭 🍔 🍟 🍕 🥪 🥙 🧆 🌮 🌯 🥗 🥘 🍝 🍜 🍲 🍛 "
    "🍣 🍱 🥟 🍤 🍙 🍚 🍘 🍥 🥠 🥮 🍢 🍡 🍧 🍨 🍦 🥧 🧁 🍰 🎂 🍮 "
    "🍭 🍬 🍫 🍿 🍩 🍪 🌰 🥜 🍯 🥛 🍼 ☕ 🍵 🧃 🥤 🍶 🍺 🍻 🥂 🍷 "
    "🥃 🍸 🍹 🧉 🍾 🧊 🥄 🍴 🍽 🥢")

ACTIVITIES = _split(
    "⚽ 🏀 🏈 ⚾ 🥎 🎾 🏐 🏉 🥏 🎱 🪀 🏓 🏸 🏒 🏑 🥍 🏏 🥅 ⛳ 🪁 "
    "🏹 🎣 🤿 🥊 🥋 🎽 🛹 🛷 ⛸ 🥌 🎿 ⛷ 🏂 🏋 🤼 🤸 ⛹ 🤺 🤾 🏌 "
    "🏇 🧘 🏄 🏊 🤽 🚣 🧗 🚴 🚵 🏆 🥇 🥈 🥉 🏅 🎖 🏵 🎗 🎫 🎟 🎪 "
    "🎭 🎨 🎬 🎤 🎧 🎼 🎵 🎶 🎹 🥁 🎷 🎺 🎸 🪕 🎻 🎲 🎯 🎳 🎮 🕹 "
    "🎰 🧩 🎁 🎈 🎏 🎀 🎊 🎉 🎎 🏮 🎐 🧧 🪅")

TRAVEL = _split(
    "🚗 🚕 🚙 🚌 🚎 🏎 🚓 🚑 🚒 🚐 🚚 🚛 🚜 🛴 🚲 🛵 🏍 🛺 🚨 🚔 "
    "🚍 🚘 🚖 🚡 🚠 🚟 🚃 🚋 🚞 🚝 🚄 🚅 🚈 🚂 🚆 🚇 🚊 🚉 ✈️ 🛫 "
    "🛬 🛩 💺 🛰 🚀 🛸 🚁 🛶 ⛵ 🚤 🛥 🛳 ⛴ 🚢 ⚓ ⛽ 🚧 🚦 🚥 🗺 "
    "🗿 🗽 🗼 🏰 🏯 🏟 🎡 🎢 🎠 ⛲ ⛱ 🏖 🏝 🏜 🌋 ⛰ 🏔 🗻 🏕 ⛺ "
    "🏠 🏡 🏘 🏚 🏗 🏭 🏢 🏬 🏣 🏤 🏥 🏦 🏨 🏪 🏫 🏩 💒 🏛 ⛪ 🕌 "
    "🕍 🛕 🕋 ⛩ 🌁 🌃 🏙 🌄 🌅 🌆 🌇 🌉")

OBJECTS = _split(
    "⌚ 📱 💻 ⌨️ 🖥 🖨 🖱 🖲 🕹 💽 💾 💿 📀 📼 📷 📸 📹 🎥 📽 🎞 "
    "📞 ☎️ 📟 📠 📺 📻 🎙 🎚 🎛 🧭 ⏱ ⏲ ⏰ 🕰 ⌛ ⏳ 📡 🔋 🔌 💡 "
    "🔦 🕯 🧯 🛢 💸 💵 💴 💶 💷 💰 💳 💎 ⚖️ 🧰 🔧 🔨 ⚒ 🛠 ⛏ 🔩 "
    "⚙️ 🧱 ⛓ 🧲 🔫 💣 🧨 🪓 🔪 🗡 ⚔️ 🛡 ⚰️ ⚱️ 🏺 🔮 📿 🧿 💈 ⚗️ "
    "🔭 🔬 🕳 💊 💉 🩸 🩹 🩺 🧬 🦠 🧫 🧪 🧹 🧺 🧻 🚽 🚰 🚿 🛁 🛀 "
    "🧼 🪒 🧽 🧴 🛎 🔑 🗝 🚪 🪑 🛋 🛏 🛌 🧸 🖼 🛍 🛒 📦 📫 📮 📜 "
    "📃 📄 📑 📊 📈 📉 🗒 🗓 📆 📅 📇 🗃 🗳 🗄 📋 📁 📂 🗂 🗞 📰 "
    "📓 📔 📒 📕 📗 📘 📙 📚 📖 🔖 🧷 🔗 📎 🖇 📐 📏 🧮 📌 📍 ✂️ "
    "🖊 🖋 ✒️ 🖌 🖍 📝 ✏️ 🔍 🔎 🔏 🔐 🔒 🔓")

SYMBOLS = _split(
    "❗ ❓ ❕ ❔ ‼️ ⁉️ 💯 ⚠️ 🚸 🔱 ⚜️ 🔰 ♻️ ✅ 🚫 ❌ ❎ ✳️ ✴️ ❇️ ©️ "
    "®️ ™️ 🔟 🔠 🔡 🔢 🔣 🔤 🆒 🆓 🆕 🆖 🆗 🆘 🆙 🆚 ℹ️ 🅰️ 🅱️ 🅾️ "
    "🅿️ ➕ ➖ ➗ ✖️ ♾️ 💲 💱 🔺 🔻 🔸 🔹 🔶 🔷 🔳 🔲 ▪️ ▫️ ◾ ◽ "
    "◼️ ◻️ ⬛ ⬜ 🔈 🔇 🔉 🔊 🔔 🔕 📣 📢 ♠️ ♣️ ♥️ ♦️ 🃏 🀄 🎴 "
    "♈ ♉ ♊ ♋ ♌ ♍ ♎ ♏ ♐ ♑ ♒ ♓ ⛎ 🔀 🔁 🔂 ▶️ ⏩ ⏭ ⏯ ◀️ ⏪ "
    "⏮ 🔼 ⏫ 🔽 ⏬ ⏸ ⏹ ⏺ ⏏️ 📶 📳 📴 ✔️ ☑️ 🔘 ⚪ ⚫ 🔴 🔵 ⭕ "
    "〰️ ➰ ➿ ⭐ ✨ ⚡ 💠 🕐 🕑 🕒 🕓 🕔 🕕 🕖 🕗 🕘 🕙 🕚 🕛")

#: (name, the icon shown on the category tab, entries)
EMOJI_CATEGORIES = (
    ("Smileys", "😀", SMILEYS),
    ("People", "👋", GESTURES),
    ("Hearts", "❤️", HEARTS),
    ("Animals", "🐶", ANIMALS),
    ("Nature", "🌍", NATURE),
    ("Food", "🍕", FOOD),
    ("Activities", "⚽", ACTIVITIES),
    ("Travel", "🚗", TRAVEL),
    ("Objects", "💡", OBJECTS),
    ("Symbols", "❗", SYMBOLS),
)

#: flat list, kept because the old picker exported one under this name.
#: A handful of entries sit in two categories on purpose - a heart is
#: both a heart and a symbol - so the flat view drops the repeats while
#: keeping the order.
EMOJIS = list(dict.fromkeys(
    e for _name, _icon, block in EMOJI_CATEGORIES for e in block))


def cost(emoji: str) -> int:
    """How many characters this entry spends of the chatbox's 144.

    Almost always 1. Entries carrying a variation selector cost 2 - the
    selector is a real character in the payload even though nothing is
    drawn for it.
    """
    return len(emoji)


# --------------------------------------------------------------------
# search
# --------------------------------------------------------------------
# The search terms come from unicodedata, not from a hand-written table.
# Every entry in this palette has an official Unicode name and they are
# usually the words someone would type - FIRE, ROCKET, DOG FACE - so a
# thousand hand-maintained keyword lists would be a thousand chances to
# drift from the palette for no gain.
#
# What Unicode does not give is the shorthand people actually use, and it
# gives nothing in German. That is what ALIASES is for: short, common,
# and deliberately not exhaustive - a term earns its place by being one
# somebody would plausibly type into a chatbox tool.
ALIASES = {
    "\U0001F602": "lol laughing lachen",
    "\U0001F923": "rofl lmao lachen",
    "\U0001F600": "smile happy lachen freude",
    "\U0001F60A": "smile happy freude",
    "\U0001F622": "sad cry weinen traurig",
    "\U0001F62D": "sad cry weinen traurig",
    "\U0001F621": "angry mad wut sauer",
    "\U0001F620": "angry mad wut sauer",
    "\U0001F634": "sleep tired schlafen muede afk",
    "\U0001F4A4": "sleep zzz schlafen afk",
    "\u2764\uFE0F": "love herz liebe",
    "\U0001F494": "broken herz liebe",
    "\U0001F525": "fire lit feuer hot",
    "\U0001F4A7": "water wasser drop",
    "\U0001F31F": "star stern",
    "\u2B50": "star stern",
    "\U0001F319": "moon mond night nacht",
    "\u2600\uFE0F": "sun sonne day tag",
    "\U0001F3B5": "music musik song lied note",
    "\U0001F3B6": "music musik song lied note",
    "\U0001F3A7": "headphones kopfhoerer audio musik",
    "\U0001F3A4": "mic microphone mikrofon voice stimme",
    "\U0001F3AE": "game gaming spiel controller vrchat",
    "\U0001F579": "game gaming spiel joystick",
    "\U0001F4BB": "pc computer laptop rechner",
    "\U0001F5A5": "pc computer monitor bildschirm gpu grafik",
    "\U0001F3AE": "game gaming spiel controller vrchat vrc",
    "\U0001F4E1": "network netzwerk ping signal",
    "\U0001F39A": "slider regler settings einstellungen",
    "\U0001F9CA": "ice cold kalt kuehl temp",
    "\U0001F4FA": "tv fps screen bildschirm",
    "\U0001F5A8": "printer drucker",
    "\U0001F4F1": "phone handy smartphone",
    "\U0001F50B": "battery akku power strom",
    "\U0001F4A1": "idea light lampe licht",
    "\u26A1": "power strom energy blitz fast",
    "\U0001F321": "temp temperature thermometer grad",
    "\U0001F9E0": "brain gehirn cpu prozessor",
    "\U0001F4BE": "save disk speichern ram memory speicher",
    "\U0001F4C8": "chart graph stats usage auslastung fps",
    "\U0001F4C9": "chart graph stats",
    "\U0001F4CA": "chart graph stats bar",
    "\U0001F680": "rocket rakete fast schnell",
    "\U0001F6AB": "no stop verboten",
    "\u2705": "ok yes ja check haken done",
    "\u274C": "no nein cross falsch",
    "\u2757": "important wichtig achtung",
    "\u26A0\uFE0F": "warning warnung achtung",
    "\U0001F4AC": "chat message nachricht talk reden",
    "\U0001F44B": "hi hello hallo wave winken tschuess",
    "\U0001F44D": "yes ok good gut daumen like",
    "\U0001F44E": "no bad schlecht daumen dislike",
    "\U0001F64F": "please thanks danke bitte pray",
    "\U0001F4AA": "strong stark muscle muskel gym",
    "\U0001F436": "dog hund puppy",
    "\U0001F431": "cat katze kitty",
    "\U0001F98A": "fox fuchs",
    "\U0001F43A": "wolf",
    "\U0001F955": "carrot karotte",
    "\U0001F355": "pizza",
    "\U0001F37A": "beer bier drink",
    "\u2615": "coffee kaffee tea",
    "\U0001F382": "cake kuchen birthday geburtstag",
    "\U0001F381": "gift geschenk present",
    "\U0001F3AC": "movie film video",
    "\U0001F3A5": "movie film camera kamera",
    "\U0001F4F7": "photo foto camera kamera",
    "\U0001F30D": "earth erde welt world globe",
    "\U0001F3E0": "home haus house",
    "\U0001F697": "car auto",
    "\u2708\uFE0F": "plane flugzeug fly travel reisen",
    "\U0001F512": "lock schloss privat locked",
    "\U0001F513": "unlock offen open",
    "\U0001F511": "key schluessel",
    "\U0001F50D": "search suche find finden zoom",
    "\U0001F4C5": "date datum calendar kalender",
    "\u23F0": "alarm wecker time zeit uhr",
    "\U0001F550": "time zeit uhr clock",
    "\U0001F480": "skull dead tot totenkopf",
    "\U0001F47E": "alien retro game invader",
    "\U0001F916": "robot roboter bot ai",
    "\U0001F47B": "ghost geist spooky",
    "\U0001F60E": "cool sunglasses sonnenbrille",
    "\U0001F970": "love herz liebe cute suess",
    "\U0001F92F": "mind blown wow",
    "\u2728": "sparkle glitzer shiny neu new",
}

_INDEX = None


def _build_index():
    """emoji -> the lowercase text a query is matched against.

    Built once, on the first search. Roughly a thousand `unicodedata`
    lookups, which is nothing, but there is no reason to pay it for a
    session where nobody types in the search box.
    """
    import unicodedata
    index = {}
    for name, _icon, block in EMOJI_CATEGORIES:
        for emoji in block:
            parts = [name.lower()]
            for char in emoji:
                uname = unicodedata.name(char, "")
                if uname:
                    parts.append(uname.lower())
            alias = ALIASES.get(emoji)
            if alias:
                parts.append(alias)
            # a repeat in a second category extends the first entry
            # rather than replacing it, so "heart" and "symbols" both
            # find the same heart
            if emoji in index:
                index[emoji] += " " + " ".join(parts)
            else:
                index[emoji] = " ".join(parts)
    return index


def search(query: str, limit: int = 120):
    """Entries whose name, category or alias contains every word of the
    query. All words must match, so a second word narrows rather than
    widens - "face heart" is the smiling-with-hearts one, not both sets.

    Matching is substring-based, so "herz" finds nothing on its own but
    "heart" does, and a partial word like "rock" still finds ROCKET.
    """
    global _INDEX
    query = (query or "").strip().lower()
    if not query:
        return []
    if _INDEX is None:
        _INDEX = _build_index()
    words = query.split()
    exact, partial = [], []
    for emoji, text in _INDEX.items():
        if not all(word in text for word in words):
            continue
        # "lol" is a substring of LOLLIPOP and "pc" of CUPCAKE, so a
        # plain substring search buries the obvious answer under sweets.
        # Entries where every query word is a whole word come first;
        # the substring hits still show, just below.
        if all(word in text.split() for word in words):
            exact.append(emoji)
        else:
            partial.append(emoji)
        if len(exact) + len(partial) >= limit:
            break
    return (exact + partial)[:limit]
