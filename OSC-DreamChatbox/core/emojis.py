"""
core/emojis.py – the palette behind the emoji picker.

Everything here is data. The picker itself lives in ui/ui_main.py.

Two rules decided what got in, and both come from the chatbox rather
than from taste:

**Single codepoints wherever a single codepoint exists.** A "family"
emoji is five codepoints glued together with zero-width joiners, and it
still costs its full length against the 144 characters even where the
font draws it as one glyph. A single-codepoint emoji costs one. So no
skin tone modifiers, no ZWJ variants of something that already exists on
its own.

**Variation selectors are kept where the character needs one.** ``❤`` and
``❤️`` are different strings: without U+FE0F many fonts draw the older
monochrome glyph. Those entries cost two characters instead of one, which
is why `cost()` exists and why the picker puts it in the tooltip - with
144 characters to spend, "this one costs double" is worth knowing before
you pick it rather than after.

**Flags are the deliberate exception** (added in v1.4.5). Every one of
them breaks the first rule: a country flag is two regional indicators,
the rainbow flag is four codepoints and the trans flag is five. They are
here anyway because "where I am from" and "who I am" are things people
actually want to put in a chatbox, and no single codepoint says either.
The price is real, so it is shown rather than hidden - `cost()` reports
it and the picker prints it under the grid instead of in a tooltip
nobody hovers. Whether they *render* is up to VRChat's font, which is
why the two flag categories carry a note saying so.

Categories are ordered the way someone hunting for an icon would look,
not alphabetically: faces first, because that is what most people are
after. Flags sit at the end, where a category you visit on purpose
belongs.
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

# --------------------------------------------------------------------
# Pride
# --------------------------------------------------------------------
# Unicode has exactly two pride flags: rainbow and transgender. Every
# other identity - bi, pan, lesbian, ace, non-binary, agender - has a
# flag in the world and no emoji for it, and it never will, because
# encoding one would mean encoding all of them.
#
# What people already do instead is spell the flag out in coloured
# hearts, so that is what the second half of this category is: the
# stripes of each flag, in order, as heart emoji. They are ordinary
# single-codepoint hearts, which means they render in VRChat's chatbox
# where a ZWJ flag might not - the cost is one character per stripe
# rather than one per flag, and cost() reports that honestly.
#
# Four stripes is the ceiling, and it is a layout limit rather than a
# taste one: the picker draws one entry per cell, and a six-heart
# rainbow row does not fit in a cell sized for anything else. Rainbow
# already has two entries that do fit, so nothing is lost.
PRIDE = _split(
    # the two real ones, then the pieces they are built from
    "🏳️‍🌈 🏳️‍⚧️ 🌈 ⚧️ ⚢ ⚣ "
    # stripe sets for the flags Unicode does not have
    "💗💜💙 "          # trans
    "💖💜💙 "          # bisexual
    "💖💛💙 "          # pansexual
    "🧡🤍💗 "          # lesbian
    "🖤🤍💜 "          # asexual
    "💛🤍💜🖤 "        # non-binary
    "🖤🤍💚 "          # agender
    "💚🤍🖤")          # aromantic


# --------------------------------------------------------------------
# Country flags
# --------------------------------------------------------------------
def _flag(code: str) -> str:
    """The regional-indicator pair for a two-letter country code.

    Built rather than pasted: a table of 150 literal flag emoji is 150
    chances to typo a pair of invisible-by-design codepoints into
    something that renders as a different country, and nobody proof-
    reading a diff would catch it. From the ISO code it is arithmetic.
    """
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


#: (ISO 3166-1 alpha-2, English name, German name), alphabetical by the
#: English name. Alphabetical and not "popular first" on purpose - any
#: hand-picked front of the list is somebody's country pushed to the
#: back, and the search box is the real answer to "find mine fast".
COUNTRIES = (
    ("AF", "Afghanistan", "Afghanistan"),
    ("AL", "Albania", "Albanien"),
    ("DZ", "Algeria", "Algerien"),
    ("AD", "Andorra", "Andorra"),
    ("AO", "Angola", "Angola"),
    ("AR", "Argentina", "Argentinien"),
    ("AM", "Armenia", "Armenien"),
    ("AU", "Australia", "Australien"),
    ("AT", "Austria", "Oesterreich Österreich"),
    ("AZ", "Azerbaijan", "Aserbaidschan"),
    ("BH", "Bahrain", "Bahrain"),
    ("BD", "Bangladesh", "Bangladesch"),
    ("BY", "Belarus", "Belarus Weissrussland"),
    ("BE", "Belgium", "Belgien"),
    ("BT", "Bhutan", "Bhutan"),
    ("BO", "Bolivia", "Bolivien"),
    ("BA", "Bosnia and Herzegovina", "Bosnien und Herzegowina"),
    ("BW", "Botswana", "Botswana"),
    ("BR", "Brazil", "Brasilien"),
    ("BN", "Brunei", "Brunei"),
    ("BG", "Bulgaria", "Bulgarien"),
    ("KH", "Cambodia", "Kambodscha"),
    ("CM", "Cameroon", "Kamerun"),
    ("CA", "Canada", "Kanada"),
    ("CL", "Chile", "Chile"),
    ("CN", "China", "China"),
    ("CO", "Colombia", "Kolumbien"),
    ("CR", "Costa Rica", "Costa Rica"),
    ("HR", "Croatia", "Kroatien"),
    ("CU", "Cuba", "Kuba"),
    ("CY", "Cyprus", "Zypern"),
    ("CZ", "Czechia", "Tschechien"),
    ("CD", "DR Congo", "Kongo"),
    ("DK", "Denmark", "Daenemark Dänemark"),
    ("DO", "Dominican Republic", "Dominikanische Republik"),
    ("EC", "Ecuador", "Ecuador"),
    ("EG", "Egypt", "Aegypten Ägypten"),
    ("SV", "El Salvador", "El Salvador"),
    ("EE", "Estonia", "Estland"),
    ("ET", "Ethiopia", "Aethiopien Äthiopien"),
    ("EU", "European Union", "Europaeische Union Europäische Union EU"),
    ("FJ", "Fiji", "Fidschi"),
    ("FI", "Finland", "Finnland"),
    ("FR", "France", "Frankreich"),
    ("GE", "Georgia", "Georgien"),
    ("DE", "Germany", "Deutschland"),
    ("GH", "Ghana", "Ghana"),
    ("GR", "Greece", "Griechenland"),
    ("GT", "Guatemala", "Guatemala"),
    ("HN", "Honduras", "Honduras"),
    ("HK", "Hong Kong", "Hongkong"),
    ("HU", "Hungary", "Ungarn"),
    ("IS", "Iceland", "Island"),
    ("IN", "India", "Indien"),
    ("ID", "Indonesia", "Indonesien"),
    ("IR", "Iran", "Iran"),
    ("IQ", "Iraq", "Irak"),
    ("IE", "Ireland", "Irland"),
    ("IL", "Israel", "Israel"),
    ("IT", "Italy", "Italien"),
    ("CI", "Ivory Coast", "Elfenbeinkueste Elfenbeinküste"),
    ("JM", "Jamaica", "Jamaika"),
    ("JP", "Japan", "Japan"),
    ("JO", "Jordan", "Jordanien"),
    ("KZ", "Kazakhstan", "Kasachstan"),
    ("KE", "Kenya", "Kenia"),
    ("KW", "Kuwait", "Kuwait"),
    ("KG", "Kyrgyzstan", "Kirgisistan"),
    ("LA", "Laos", "Laos"),
    ("LV", "Latvia", "Lettland"),
    ("LB", "Lebanon", "Libanon"),
    ("LY", "Libya", "Libyen"),
    ("LI", "Liechtenstein", "Liechtenstein"),
    ("LT", "Lithuania", "Litauen"),
    ("LU", "Luxembourg", "Luxemburg"),
    ("MG", "Madagascar", "Madagaskar"),
    ("MW", "Malawi", "Malawi"),
    ("MY", "Malaysia", "Malaysia"),
    ("MV", "Maldives", "Malediven"),
    ("ML", "Mali", "Mali"),
    ("MT", "Malta", "Malta"),
    ("MX", "Mexico", "Mexiko"),
    ("MD", "Moldova", "Moldau"),
    ("MC", "Monaco", "Monaco"),
    ("MN", "Mongolia", "Mongolei"),
    ("ME", "Montenegro", "Montenegro"),
    ("MA", "Morocco", "Marokko"),
    ("MZ", "Mozambique", "Mosambik"),
    ("MM", "Myanmar", "Myanmar"),
    ("NA", "Namibia", "Namibia"),
    ("NP", "Nepal", "Nepal"),
    ("NL", "Netherlands", "Niederlande Holland"),
    ("NZ", "New Zealand", "Neuseeland"),
    ("NI", "Nicaragua", "Nicaragua"),
    ("NG", "Nigeria", "Nigeria"),
    ("KP", "North Korea", "Nordkorea"),
    ("MK", "North Macedonia", "Nordmazedonien"),
    ("NO", "Norway", "Norwegen"),
    ("OM", "Oman", "Oman"),
    ("PK", "Pakistan", "Pakistan"),
    ("PS", "Palestine", "Palaestina Palästina"),
    ("PA", "Panama", "Panama"),
    ("PG", "Papua New Guinea", "Papua-Neuguinea"),
    ("PY", "Paraguay", "Paraguay"),
    ("PE", "Peru", "Peru"),
    ("PH", "Philippines", "Philippinen"),
    ("PL", "Poland", "Polen"),
    ("PT", "Portugal", "Portugal"),
    ("PR", "Puerto Rico", "Puerto Rico"),
    ("QA", "Qatar", "Katar"),
    ("RO", "Romania", "Rumaenien Rumänien"),
    ("RU", "Russia", "Russland"),
    ("RW", "Rwanda", "Ruanda"),
    ("SA", "Saudi Arabia", "Saudi-Arabien"),
    ("SN", "Senegal", "Senegal"),
    ("RS", "Serbia", "Serbien"),
    ("SG", "Singapore", "Singapur"),
    ("SK", "Slovakia", "Slowakei"),
    ("SI", "Slovenia", "Slowenien"),
    ("SO", "Somalia", "Somalia"),
    ("ZA", "South Africa", "Suedafrika Südafrika"),
    ("KR", "South Korea", "Suedkorea Südkorea"),
    ("ES", "Spain", "Spanien"),
    ("LK", "Sri Lanka", "Sri Lanka"),
    ("SD", "Sudan", "Sudan"),
    ("SE", "Sweden", "Schweden"),
    ("CH", "Switzerland", "Schweiz"),
    ("SY", "Syria", "Syrien"),
    ("TW", "Taiwan", "Taiwan"),
    ("TJ", "Tajikistan", "Tadschikistan"),
    ("TZ", "Tanzania", "Tansania"),
    ("TH", "Thailand", "Thailand"),
    ("TT", "Trinidad and Tobago", "Trinidad und Tobago"),
    ("TN", "Tunisia", "Tunesien"),
    ("TR", "Turkey", "Tuerkei Türkei"),
    ("TM", "Turkmenistan", "Turkmenistan"),
    ("UG", "Uganda", "Uganda"),
    ("UA", "Ukraine", "Ukraine"),
    ("AE", "United Arab Emirates", "Vereinigte Arabische Emirate"),
    ("GB", "United Kingdom", "Grossbritannien Großbritannien England UK"),
    ("UN", "United Nations", "Vereinte Nationen UN UNO"),
    ("US", "United States", "USA Vereinigte Staaten Amerika"),
    ("UY", "Uruguay", "Uruguay"),
    ("UZ", "Uzbekistan", "Usbekistan"),
    ("VE", "Venezuela", "Venezuela"),
    ("VN", "Vietnam", "Vietnam"),
    ("YE", "Yemen", "Jemen"),
    ("ZM", "Zambia", "Sambia"),
    ("ZW", "Zimbabwe", "Simbabwe"),
)

#: the generic flags first, then every country
FLAGS = (["🏁", "🚩", "🏳️", "🏴", "🏴‍☠️"]
         + [_flag(code) for code, _en, _de in COUNTRIES])

#: emoji -> the search text for it. Country flags carry no useful
#: Unicode name (a German flag is "REGIONAL INDICATOR SYMBOL LETTER D"
#: plus "... LETTER E"), so the names come from the table above instead.
FLAG_NAMES = {
    _flag(code): f"flag flagge {en} {de} {code}".lower()
    for code, en, de in COUNTRIES
}

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
    ("Pride", "🏳️‍🌈", PRIDE),
    ("Flags", "🏳️", FLAGS),
)

#: a line the picker shows under the grid for categories that need a
#: warning the tooltips cannot carry. Only the two flag categories have
#: one, and both say the same thing for the same reason.
CATEGORY_NOTES = {
    "Pride": "Flags cost 4-5 characters and need font support - the "
             "heart rows always render.",
    "Flags": "A country flag costs 2 characters and may show as letters "
             "(DE, US) where the font has no flag.",
}

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
    drawn for it. A country flag costs 2, the rainbow flag 4, the trans
    flag 5, and a pride heart row one per stripe.
    """
    return len(emoji)


_ZWJ = "\u200D"


def visual_len(emoji: str) -> int:
    """How many glyphs this entry *draws*, which is not how many
    characters it costs.

    The picker needs this and cost() cannot answer it: 🏳️‍⚧️ costs five
    characters and draws one, 💗💜💙 costs three and draws three. Sizing
    a 32px button by cost would shrink the trans flag to nothing and
    sizing it by 1 would clip the heart rows.

    Anything joined by ZWJ is one glyph by definition - that is what the
    joiner is for. Otherwise regional indicators pair up and everything
    else counts as itself, with the invisible variation selectors
    dropped first.
    """
    if _ZWJ in emoji:
        return 1
    body = emoji.replace("\uFE0F", "").replace("\uFE0E", "")
    regional = sum(1 for ch in body if 0x1F1E6 <= ord(ch) <= 0x1F1FF)
    return max(1, (regional + 1) // 2 + (len(body) - regional))


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
    "\U0001F3AE": "game gaming spiel controller vrchat vrc",
    "\U0001F579": "game gaming spiel joystick",
    "\U0001F4BB": "pc computer laptop rechner",
    "\U0001F5A5": "pc computer monitor bildschirm gpu grafik",
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
    # ---- pride -------------------------------------------------------
    # The Unicode names here are useless for finding these: the rainbow
    # flag is "WAVING WHITE FLAG" plus "RAINBOW", and the stripe rows
    # have no name at all beyond the hearts they are made of.
    "\U0001F3F3\uFE0F\u200D\U0001F308":
        "pride rainbow flag regenbogen lgbt lgbtq gay queer schwul",
    "\U0001F3F3\uFE0F\u200D\u26A7\uFE0F":
        "trans transgender flag flagge pride enby",
    "\U0001F308": "rainbow regenbogen pride lgbt gay",
    "\u26A7\uFE0F": "trans transgender symbol pride",
    "\u26A2": "lesbian lesbisch wlw pride",
    "\u26A3": "gay schwul mlm pride",
    "\U0001F497\U0001F49C\U0001F499": "trans transgender pride stripes herzen",
    "\U0001F496\U0001F49C\U0001F499": "bi bisexual bisexuell pride stripes",
    "\U0001F496\U0001F49B\U0001F499": "pan pansexual pansexuell pride stripes",
    "\U0001F9E1\U0001F90D\U0001F497": "lesbian lesbisch wlw pride stripes",
    "\U0001F5A4\U0001F90D\U0001F49C": "ace asexual asexuell pride stripes",
    "\U0001F49B\U0001F90D\U0001F49C\U0001F5A4":
        "nonbinary non-binary enby nichtbinaer nb pride stripes",
    "\U0001F5A4\U0001F90D\U0001F49A": "agender pride stripes",
    "\U0001F49A\U0001F90D\U0001F5A4": "aro aromantic aromantisch pride stripes",
    # ---- the generic flags; the countries come from FLAG_NAMES --------
    "\U0001F3C1": "flag flagge finish ziel race rennen",
    "\U0001F6A9": "flag flagge marker pin",
    "\U0001F3F3\uFE0F": "flag flagge white weiss surrender",
    "\U0001F3F4": "flag flagge black schwarz",
    "\U0001F3F4\u200D\u2620\uFE0F": "pirate flag pirat jolly roger flagge",
}

# The countries are a table, not a hand-written alias each. Merged in
# rather than looked up separately so _build_index() keeps having
# exactly one source of extra search terms.
ALIASES.update(FLAG_NAMES)

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
                # "REGIONAL INDICATOR SYMBOL LETTER D" is not what
                # anybody types to find Germany, and it puts the words
                # "letter" and "symbol" on 150 entries where they match
                # queries meant for something else. Same for the
                # variation selectors, which are on a fifth of the
                # palette and mean nothing to anyone.
                if not uname or uname.startswith(
                        ("REGIONAL INDICATOR SYMBOL", "VARIATION SELECTOR")):
                    continue
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
    # The whole index is scanned rather than stopping at `limit` hits.
    # Stopping early ranks by position in the palette instead of by
    # quality, and the flags are the last category: "japan" filled its
    # six slots with JAPANESE OGRE and JAPANESE POST OFFICE and gave up
    # two rows above the Japanese flag. A thousand substring checks cost
    # nothing next to being wrong.
    return (exact + partial)[:limit]
