"""
ui/config_mixin.py – Loading, validating, migrating and saving the JSON config.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.
"""

import json
import shutil
from core.theming import THEMES
from core.audiolevel import THRESHOLD_DEFAULT, clamp_threshold
from core.textstyle import STYLE_NORMAL, normalize as normalize_style
from core.constants import (
    AIO_MAX, CHAT_MODES, DEFAULT_TRANSLATE_NOTICE, CHAT_MODE_DIRECT, CONFIG_DIR, CONFIG_FILE, LYRICS_DIR, MIN_STATUS_CYCLE_SEC, OLD_CONFIG_FILE, TITLE_MAX_LEN)
from core.boxstyle import (
    CLOCK_24_HM, DEFAULT_CUSTOM_BOX, MODE_CUSTOM as BOX_MODE_CUSTOM, normalize_clock_format, normalize_custom as normalize_box_custom, normalize_mode as normalize_box_mode, normalize_template as normalize_box_template, normalize_width as normalize_box_width)
from core.textutils import DEFAULT_CUSTOM_BAR, TIME_POS_LINE
from core.translators import METHOD_LINGVA
from core.plugins import ANCHORS, DEFAULT_ANCHOR


#: What the four rotation slots contain on a FIRST START only - i.e.
#: when neither the current nor the legacy config file exists yet. They
#: are ordinary texts afterwards: clear one and it stays cleared, this
#: is a starting point, not a value the app keeps restoring.
#: All four stay well under CHATBOX_LIMIT (144) even with the slim
#: suffix, and deliberately avoid markdown - VRChat's chatbox is plain
#: text, so "[label](url)" would show up with the brackets and burn
#: characters for nothing.
FIRST_RUN_STATUS_TEXTS = [
    "Thanks for your support! \U0001F496",
    "I'm using OSC Dream Chatbox \U0001F680 "
    "(Features requested on Discord/Github!)",
    "\u2615 Support on Ko-fi: ko-fi.com/yakuda_",
    "\U0001F4BB GitHub Repo: github.com/yakuda-stack",
]


def _clamp_float(value, fallback, low, high):
    """A float from the config, forced into range.

    Its own helper because the sensitivity timings all need it and a
    config that a user edited by hand is the normal case here - the
    values are seconds with one decimal, which is exactly the kind of
    setting people try in a text editor.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if value != value:      # NaN survives min/max, so it is caught here
        return float(fallback)
    return float(max(low, min(high, value)))


def _bool_list(value, size, fallback):
    """A fixed-length list of bools out of whatever the config held."""
    items = value if isinstance(value, list) else []
    items = [bool(x) for x in items][:size]
    return items + [fallback] * (size - len(items))


def _int_list(value, size, fallback, low, high):
    """A fixed-length list of clamped ints. A junk entry falls back to
    the default rather than taking the whole list down - one unreadable
    number should not cost a user their other four."""
    items = value if isinstance(value, list) else []
    out = []
    for item in items[:size]:
        try:
            out.append(min(high, max(low, int(item))))
        except (TypeError, ValueError):
            out.append(fallback)
    return out + [fallback] * (size - len(out))


def _graph(value):
    """The shape of one node canvas, and only the shape.

    ui/nodegraph.py drops unknown node types and dangling edges when it
    rebuilds the canvas, so a graph written by a newer version costs the
    block it mentions rather than the whole file.
    """
    value = value if isinstance(value, dict) else {}
    return {
        "nodes": [n for n in (value.get("nodes") or [])
                  if isinstance(n, dict)],
        "edges": [e for e in (value.get("edges") or [])
                  if isinstance(e, dict)],
    }


def _split_legacy_graph(graph):
    """The one-canvas graph of the first Advanced-mode build, cut into one
    canvas per AIO slot.

    Back then a single canvas held several Chatbox Output blocks, each
    carrying a "slot" value. Every block that feeds one of those outputs
    moves into that slot's canvas; a block feeding two outputs is copied
    into both, which is the only way to keep both slots working without
    inventing a shared-node concept the new format does not have.
    """
    nodes = {}
    for entry in graph.get("nodes") or []:
        node_id = str(entry.get("id") or "")
        if node_id:
            nodes[node_id] = entry
    incoming = {}
    for edge in graph.get("edges") or []:
        dst, src = str(edge.get("to") or ""), str(edge.get("from") or "")
        if dst in nodes and src in nodes:
            incoming.setdefault(dst, []).append((src, edge))

    out = {}
    for node_id, entry in nodes.items():
        if entry.get("type") != "output":
            continue
        try:
            slot = min(AIO_MAX, max(1, int((entry.get("values") or {}).get(
                "slot", 1))))
        except (TypeError, ValueError):
            slot = 1
        keep, edges, stack = set(), [], [node_id]
        while stack:
            current = stack.pop()
            if current in keep:
                continue
            keep.add(current)
            for src, edge in incoming.get(current, []):
                edges.append(edge)
                stack.append(src)
        part = {"nodes": [], "edges": edges}
        for kept in keep:
            copy = dict(nodes[kept])
            if copy.get("type") == "output":
                # the slot lives in which canvas you are on now
                copy["values"] = {k: v
                                  for k, v in (copy.get("values") or {}).items()
                                  if k != "slot"}
            part["nodes"].append(copy)
        out.setdefault(slot, part)
    return out


class ConfigMixin:
    def load_config(self):
        # first start = no config anywhere. Only then are the default
        # prompts seeded; an existing config always wins.
        first_run = not CONFIG_FILE.exists() and not OLD_CONFIG_FILE.exists()
        seed = FIRST_RUN_STATUS_TEXTS if first_run else []
        defaults = {
            "status_text": "",
            # mirror of the ACTIVE template; pre-filled on first start
            "status_texts": list(seed) + [""] * (20 - len(seed)),
            # per text: normal | super | sub (see core/textstyle.py)
            "status_styles": [STYLE_NORMAL] * 20,
            "status_count": max(1, len(seed)),
            "status_cycle_sec": 10,
            # how the next text is picked: random (the old and only
            # behaviour) or straight down the list. True keeps every
            # existing config doing exactly what it did before.
            "status_random": True,
            # 10 switchable text templates, each with its own 1-20 texts
            "status_templates": [
                {"name": f"Template {i + 1}",
                 "texts": (list(seed) + [""] * (20 - len(seed))
                           if i == 0 else [""] * 20),
                 "styles": [STYLE_NORMAL] * 20,
                 "count": max(1, len(seed)) if i == 0 else 1}
                for i in range(10)
            ],
            "status_template_active": 0,
            "status_active": True,
            "media_active": False,
            "media_show_artist": True,
            "media_show_title": True,
            "media_title_max": TITLE_MAX_LEN,  # song title cutoff (3-64)
            "media_show_time": True,
            # small-letter digits for the music timer: normal|super|sub
            "media_time_style": STYLE_NORMAL,
            "media_time_seconds": True,  # time incl. seconds (3:27);
                                         # off = old h:mm style (0:03)
            "media_show_lyrics": False,  # synced lyrics via LRCLIB
                                         # (off = zero network requests)
            "media_lyrics_local": False,  # use your own local .lrc files
            "media_lyrics_dir": str(LYRICS_DIR),  # folder with .lrc files
            # the little symbol in front of the lyrics line. Toggle it
            # off or replace it with anything you like (community
            # request); "" behaves the same as switching it off.
            "media_lyrics_prefix_on": True,
            "media_lyrics_prefix": "\u266a",
            "media_show_bar": True,
            "oscquery_enabled": True,   # natives OSCQuery (mDNS)
            "media_bar_style": 2,   # 0-5 presets, 6 = custom
            "media_bar_size": 100,  # songbar length in % (30-100)
            "media_time_pos": TIME_POS_LINE,  # line|before|after|split
            "media_bar_custom": dict(DEFAULT_CUSTOM_BAR),
            "media_poll_sec": 1,
            # ---- which player the Media card reads -------------------
            # "" = automatic (whatever is playing), otherwise a stable
            # key from core.mediafetch.player_key(): "spotify",
            # "YoutubeMusic", "firefox", "Spotify.exe" on Windows. The
            # label is stored beside it purely so the dropdown can still
            # name the choice while that player is closed.
            "media_source": "",
            "media_source_label": "",
            # When the chosen player is not running: fall back to
            # whatever is (True, the friendly default) or show nothing
            # (False, for someone who wants the line to mean Spotify or
            # mean nothing).
            "media_source_fallback": True,
            "hw_active": False,
            "app_order": ["status", "media", "hardware"],
            "textbox_presets": ["Hey! How are you doing? \U0001F60A",
                                "What are you up to? \U0001F440",
                                "What's up? status: chilling \u2728",
                                "BRB / AFK for a moment! \u2615",
                                "ERP please ?"] + [""] * 15,
            "textbox_preset_count": 5,
            "textbox_pause_sec": 10,
            "textbox_order": ["chat", "stt", "presets"],
            "stt_language": "de-DE",
            "stt_block": False,
            "stt_output": "",
            "stt_method": METHOD_LINGVA,  # lingva | google | libre | deepl
            "stt_mic": "",   # microphone name, "" = system default
            "stt_deepl_key": "",
            "stt_google_key": "",   # optional Google Cloud Translation key
            "stt_libre_url": "",
            # hosted LibreTranslate: "" = the preset public instance
            "stt_libre_online_url": "",
            "stt_libre_online_key": "",
            "stt_block_saved": [],
            # Block apps, extended (see ui/pages/textbox_page.py). Both
            # default ON: "block everything" is what the toggle already
            # promised, and the plugins/frame simply were not covered.
            # stt_block_except names what keeps running anyway - the four
            # app keys, "custombox", and "plugin:<id>" per plugin.
            "stt_block_plugins": True,
            "stt_block_box": True,
            "stt_block_except": [],
            # microphone: refuse to start when the chosen device is gone,
            # instead of silently falling back to the system default -
            # which on a machine that just lost an audio device (leaving
            # VR) is frequently the device that hangs. See
            # core/backends/mic_probe.py.
            "stt_mic_strict": True,
            # ---- microphone list + sensitivity (v1.4.2) ---------------
            # PortAudio's device list is a list of ALSA PCMs: HDMI
            # outputs, four copies of one headset, and no VR microphone
            # at all. The dropdown therefore shows the sound server's
            # grouped source list (see core/micgroups.py) and hides the
            # raw hw: entries unless they are asked for.
            "stt_mic_show_raw": False,
            # Sensitivity - SpeechRecognition knobs that were previously
            # left at their defaults. Automatic re-learns the room
            # continuously, which is right in a quiet one and drifts in a
            # noisy one (fans, game audio, a headset next to the mic);
            # the manual value is what the level meter's marker shows.
            "stt_energy_auto": True,
            "stt_energy_threshold": THRESHOLD_DEFAULT,
            # how much silence ends a phrase. Too short cuts sentences
            # in half mid-word, too long delays every message.
            "stt_pause_sec": 0.8,
            # how long a sound has to last before it counts as speech at
            # all - what keeps a keyboard click or a door from becoming
            # a transcription request
            "stt_min_phrase_sec": 0.3,
            # hard cap on one phrase, so a stuck open microphone cannot
            # record forever before anything is sent
            "stt_phrase_limit": 12,
            # ---- chat routing (core/constants.py CHAT_MODES) ----------
            # The Chat card is always Standard - it is the "take over the
            # chatbox now" control, and the other two routes only ever
            # made sense for the To Text card. This key is what Speech to
            # Text and Text to Text go out as.
            "stt_send_mode": CHAT_MODE_DIRECT,
            "chat_anchor": "aio",
            "chat_hold_sec": 0,      # 0 = keep until cleared/replaced
            "stt_mode": "stt",       # "stt" (speech->text) | "ttt" (text->text)
            "stt_show_both": False,  # send "source -> translation" in chat
            "aio_active": False,
            # "normal" = the five template strings on the Apps page,
            # "advanced" = the node canvas on the Advanced page
            # (ui/pages/advanced_page.py). The strings are kept either
            # way, so switching back and forth loses nothing.
            "aio_mode": "normal",
            # OSC input (core/oscin.py). Off by default: it binds a UDP
            # port and 9001 is contested territory.
            "osc_input_enabled": False,
            # global keyboard watching for the Get Hotkey block. Off by
            # default: it is the keyboard.
            "hotkey_input_enabled": False,
            # while a translation is still being fetched, say so in the
            # chatbox instead of leaving the previous message up
            "stt_translate_notice": True,
            "stt_translate_notice_text": DEFAULT_TRANSLATE_NOTICE,
            "osc_input_port": 9001,
            # default target for the External OSC out block when it
            # leaves IP/port empty - VRChat's own target stays separate
            "osc_ext_ip": "127.0.0.1",
            "osc_ext_port": 9002,
            # one node canvas per AIO string, so AIO 1-5 each have their
            # own graph exactly the way they each have their own text
            # field in Normal mode
            "aio_graphs": [{"nodes": [], "edges": []} for _ in range(AIO_MAX)],
            # customization (core/theming.py)
            "theme": "default",
            "theme_colors": {},        # theme id -> {token: "#rrggbb"}
            "theme_background": "",    # file name inside config/backgrounds
            "theme_opacity": 0.82,     # card opacity when a background is set
            "aio_count": 1,
            # 10 switchable AIO layouts, each with its own 1-5 strings
            "aio_sets": [
                {"name": f"Template {i + 1}", "templates": [""] * AIO_MAX,
                 "count": 1, "custom_time": [False] * AIO_MAX,
                 "custom_sec": [10] * AIO_MAX,
                 "graphs": [{"nodes": [], "edges": []}
                            for _ in range(AIO_MAX)]} for i in range(10)
            ],
            "aio_set_active": 0,
            "aio_rotate": False,
            "aio_rotate_sec": 10,
            "aio_templates": (["{text} \\n {artist} : {title} | {time} \\n {bar}"]
                              + [""] * (AIO_MAX - 1)),
            # per-string dwell time: when custom_time[i] is on, AIO i+1
            # stays on screen for custom_sec[i] instead of the shared
            # aio_rotate_sec. Off everywhere by default, so an existing
            # setup rotates exactly as it did.
            "aio_custom_time": [False] * AIO_MAX,
            "aio_custom_sec": [10] * AIO_MAX,
            # height in px a field was dragged to (0 = grow with the
            # text). Cosmetic, so it is not part of the template sets.
            "aio_heights": [0] * AIO_MAX,
            # ---- Custom Box (core/boxstyle.py, ui/pages/custom_box.py) --
            # Off by default, on purpose. How wide a frame line can get
            # before the VRChat chatbox breaks it depends on the font and
            # on which characters are on the line, and no number in here
            # can know that - it has to be set once, by eye, against the
            # game. Shipping it on would mean shipping a frame that
            # splits on somebody's setup and looks broken out of the box.
            # Everything below is still filled in, so switching it on
            # gives a working frame to adjust from rather than a blank.
            "box_active": False,
            "box_template": 2,          # 0-11 presets, 12 = custom
            "box_custom_style": dict(DEFAULT_CUSTOM_BOX),
            # fill characters, per line: the two middle texts are rarely
            # the same length, so one number for both was never enough
            "box_width_top": 7,
            "box_width_bottom": 3,
            # off, because the two widths above are deliberately
            # different - aligning would flatten them back together
            "box_align": False,
            "box_top_on": True,
            "box_bottom_on": True,
            "box_top_mode": BOX_MODE_CUSTOM,    # none | clock | custom
            "box_top_custom": "\U0001F550{box_clock}\U0001F550",
            "box_bottom_mode": BOX_MODE_CUSTOM,
            "box_bottom_custom": "OSC-DreamChatbox",
            # on, because the default top line IS a clock - a clock that
            # only moves when something else happens looks broken
            "box_clock_live": True,
            "box_clock_format": CLOCK_24_HM,
            # MediaPlay: what to show between songs. On by default -
            # a line that vanishes looks like the app stopped working
            "media_idle": True,
            "media_idle_text": "\u23F8",
            "hw_flame": False,
            "hw_custom": False,
            "hw_custom_template": "\U0001F3AE {gpu_name} {gpu_usage} | {gpu_temp} {temp_icon} \\n "
                                  "\u2699\uFE0F {cpu_name} {cpu_usage} | {cpu_temp} {temp_icon} \\n "
                                  "VRAM {vram_usage} RAM {ram_usage} {ram_type}",
            "media_icon": False,
            "media_custom": False,
            "media_custom_template": "{artist} : {title} | {time}\\n{bar}",
            "hw_poll_sec": 2,
            "hw_gpu_usage": True,
            "hw_gpu_name": True,
            "hw_gpu_custom": False,
            "hw_gpu_custom_name": "",
            "hw_gpu_name_style": STYLE_NORMAL,
            "hw_gpu_temp": True,
            # Power draw. Off by default on both: the chatbox is 144
            # characters, and switching this on for everybody would make
            # an existing hardware line longer without being asked.
            "hw_gpu_power": False,
            "hw_vram_used": True,
            "hw_vram_pct": False,
            "hw_ram_used": True,
            "hw_ram_pct": False,
            "hw_ram_type": "",
            "hw_cpu_usage": True,
            "hw_cpu_name": True,
            "hw_cpu_custom": False,
            "hw_cpu_custom_name": "",
            "hw_cpu_name_style": STYLE_NORMAL,
            "hw_cpu_temp": True,
            "hw_cpu_power": False,
            "send_to_vrchat": False,
            "interval_sec": 5,
            # push a changed text to VRChat right away instead of waiting
            # for the next interval tick. Always inside VRChat's chatbox
            # rate limit - see ui/mainwindow.py.
            "osc_instant_send": True,
            "slim_chatbox": True,   # slim bar instead of big box, default ON
            "osc_ip": "127.0.0.1",
            "osc_port": 9000,
            "debug": False,
        }
        # what the file on disk actually contained. Kept separate from
        # `defaults` because a default value is indistinguishable from a
        # stored one after the update() below - and a migration has to be
        # able to tell "the user never had this key" from "the user set
        # it to the same number the default happens to be".
        stored = {}
        try:
            if CONFIG_FILE.exists():
                stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            elif OLD_CONFIG_FILE.exists():
                # migrate settings from the old location
                stored = json.loads(
                    OLD_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                defaults.update(stored)
            else:
                stored = {}
        except Exception as e:
            # a broken/corrupt config must not silently wipe the user's
            # settings – back the file up so it can be inspected/recovered,
            # then continue with defaults and warn the user.
            self._backup_corrupt_config(e)
        # migrate the old single status text into the text list
        texts = defaults.get("status_texts")
        if not isinstance(texts, list):
            texts = [""] * 20
        # 20 slots, not 10: normalising through a 10 wide window silently
        # dropped slots 11-20 and only the template copy below put them
        # back - which fails the moment the active template is empty.
        texts = [str(t) for t in texts][:20] + [""] * max(0, 20 - len(texts))
        if defaults.get("status_text") and not any(t.strip() for t in texts):
            texts[0] = defaults["status_text"]
        defaults["status_texts"] = texts
        # pad the active texts to 20 (older configs had 10)
        while len(defaults["status_texts"]) < 20:
            defaults["status_texts"].append("")
        defaults["status_count"] = min(20, max(1, int(defaults.get("status_count", 1))))
        # per-text styles: same 20 slots as the texts. Configs written
        # before v1.3.2 have none, so everything defaults to normal and
        # nothing about an existing setup changes on update.
        styles = defaults.get("status_styles")
        if not isinstance(styles, list):
            styles = []
        styles = [normalize_style(x) for x in styles][:20]
        styles += [STYLE_NORMAL] * (20 - len(styles))
        defaults["status_styles"] = styles
        for key in ("hw_gpu_name_style", "hw_cpu_name_style",
                    "media_time_style"):
            defaults[key] = normalize_style(defaults.get(key))
        # templates: normalise / migrate old single-list configs
        tpls = defaults.get("status_templates")
        if not isinstance(tpls, list) or len(tpls) != 10:
            tpls = [{"name": f"Template {i + 1}", "texts": [""] * 20,
                     "count": 1} for i in range(10)]
        for t in tpls:
            t.setdefault("name", "Template")
            t["texts"] = (list(t.get("texts", [])) + [""] * 20)[:20]
            t["styles"] = ([normalize_style(x) for x in
                            (t.get("styles") or [])]
                           + [STYLE_NORMAL] * 20)[:20]
            t["count"] = min(20, max(1, int(t.get("count", 1))))
        defaults["status_templates"] = tpls
        idx = min(9, max(0, int(defaults.get("status_template_active", 0))))
        defaults["status_template_active"] = idx
        # keep the active template in sync with the mirror fields
        if any(x.strip() for x in defaults["status_texts"]) and \
                not any(x.strip() for x in tpls[idx]["texts"]):
            tpls[idx]["texts"] = list(defaults["status_texts"])
            tpls[idx]["styles"] = list(defaults["status_styles"])
            tpls[idx]["count"] = defaults["status_count"]
        else:
            defaults["status_texts"] = list(tpls[idx]["texts"])
            defaults["status_styles"] = list(tpls[idx]["styles"])
            defaults["status_count"] = tpls[idx]["count"]
        # migrate old default templates to the current one
        old_defaults = (
            "{gpu_name}: {gpu_usage} {gpu_temp} {vram_usage} | "
            "{cpu_name}: {cpu_usage} {cpu_temp} {ram_usage} {ram_type}",
            "{gpu_name}: {gpu_usage} {gpu_temp} | Vram {vram_usage} | "
            "{cpu_name}: {cpu_usage} {cpu_temp} {ram_usage} {ram_type}",
            "{gpu_name}: {gpu_usage} {gpu_temp} | VRAM {vram_usage} \\n "
            "{cpu_name}: {cpu_usage} {cpu_temp} \\n RAM {ram_usage} {ram_type}",
        )
        if defaults.get("hw_custom_template") in old_defaults:
            defaults["hw_custom_template"] = (
                "\U0001F3AE {gpu_name} {gpu_usage} | {gpu_temp} {temp_icon} \\n "
                "\u2699\uFE0F {cpu_name} {cpu_usage} | {cpu_temp} {temp_icon} \\n "
                "VRAM {vram_usage} RAM {ram_usage} {ram_type}")
        # validate app order (keep known keys, append missing ones)
        valid = ["status", "media", "hardware"]
        order = [k for k in defaults.get("app_order", []) if k in valid]
        order += [k for k in valid if k not in order]
        defaults["app_order"] = order
        presets = defaults.get("textbox_presets")
        if not isinstance(presets, list):
            presets = [""] * 20
        presets = [str(p) for p in presets][:20]
        defaults["textbox_presets"] = presets + [""] * (20 - len(presets))
        defaults["textbox_preset_count"] = min(20, max(1, int(
            defaults.get("textbox_preset_count", 5))))
        tvalid = ["chat", "stt", "presets"]
        torder = [k for k in defaults.get("textbox_order", []) if k in tvalid]
        torder += [k for k in tvalid if k not in torder]
        defaults["textbox_order"] = torder
        aio = defaults.get("aio_templates")
        if not isinstance(aio, list):
            aio = ["{text} \\n {artist} : {title} | {time} \\n {bar}"] + [""] * (AIO_MAX - 1)
        aio = [str(t) for t in aio][:AIO_MAX]
        if defaults.get("theme") not in THEMES:
            defaults["theme"] = "default"
        if not isinstance(defaults.get("theme_colors"), dict):
            defaults["theme_colors"] = {}
        try:
            defaults["theme_opacity"] = min(1.0, max(0.25, float(
                defaults.get("theme_opacity", 0.82))))
        except (TypeError, ValueError):
            defaults["theme_opacity"] = 0.82
        # lyrics prefix: a single short string, never None. Longer than
        # 4 characters is almost certainly a paste accident and would eat
        # into the 144 char budget on every single line.
        prefix = defaults.get("media_lyrics_prefix", "\u266a")
        if not isinstance(prefix, str):
            prefix = "\u266a"
        defaults["media_lyrics_prefix"] = prefix[:4]
        defaults["media_lyrics_prefix_on"] = bool(
            defaults.get("media_lyrics_prefix_on", True))
        for key in ("stt_libre_online_url", "stt_libre_online_key"):
            val = defaults.get(key, "")
            defaults[key] = val.strip() if isinstance(val, str) else ""
        defaults["osc_instant_send"] = bool(
            defaults.get("osc_instant_send", True))
        # ---- chat routing + the extended block --------------------------
        # Every one of these is absent from configs written before v1.3.3,
        # so each falls back to the default above and an existing setup
        # behaves exactly as it did: Standard send mode, block covering
        # everything, nothing excepted.
        # up to v1.3.2 one key covered Chat, Speech to Text and Text to
        # Text. Chat lost its dropdown, so the old value carries over to
        # the two that kept theirs.
        legacy_mode = defaults.pop("chat_send_mode", None)
        # the old key only survives one load - it is popped here - so a
        # config that still has it is by definition one that has never
        # seen the new key set to anything but its default
        if legacy_mode in CHAT_MODES and \
                defaults.get("stt_send_mode") == CHAT_MODE_DIRECT:
            defaults["stt_send_mode"] = legacy_mode
        if defaults.get("stt_send_mode") not in CHAT_MODES:
            defaults["stt_send_mode"] = CHAT_MODE_DIRECT
        if defaults.get("chat_anchor") not in ANCHORS:
            defaults["chat_anchor"] = DEFAULT_ANCHOR
        try:
            defaults["chat_hold_sec"] = min(3600, max(0, int(
                defaults.get("chat_hold_sec", 0))))
        except (TypeError, ValueError):
            defaults["chat_hold_sec"] = 0
        for key in ("stt_block_plugins", "stt_block_box", "stt_mic_strict"):
            defaults[key] = bool(defaults.get(key, True))
        # ---- microphone list + sensitivity (v1.4.2) -------------------
        # All five are absent from every older config and land on their
        # defaults, which is exactly the behaviour those versions had:
        # automatic sensitivity and SpeechRecognition's own timings.
        defaults["stt_mic_show_raw"] = bool(
            defaults.get("stt_mic_show_raw", False))
        defaults["stt_energy_auto"] = bool(
            defaults.get("stt_energy_auto", True))
        defaults["stt_energy_threshold"] = clamp_threshold(
            defaults.get("stt_energy_threshold", THRESHOLD_DEFAULT))
        defaults["stt_pause_sec"] = _clamp_float(
            defaults.get("stt_pause_sec"), 0.8, 0.2, 3.0)
        # non_speaking_duration is derived from pause_sec in
        # core/stt_child.py and must never exceed it, which is why the
        # lower bound here is not zero: a pause under 0.2 s slices into
        # the phrase itself and produces half-words.
        defaults["stt_min_phrase_sec"] = _clamp_float(
            defaults.get("stt_min_phrase_sec"), 0.3, 0.05, 2.0)
        try:
            defaults["stt_phrase_limit"] = min(60, max(3, int(
                defaults.get("stt_phrase_limit", 12))))
        except (TypeError, ValueError):
            defaults["stt_phrase_limit"] = 12
        exc = defaults.get("stt_block_except")
        defaults["stt_block_except"] = sorted(
            {str(x) for x in exc}) if isinstance(exc, list) else []
        # older configs may still carry a 2 s cycle from before the
        # 10 s minimum - lift those instead of leaving an out-of-range
        # value that the spin box cannot even display
        try:
            defaults["status_cycle_sec"] = max(
                MIN_STATUS_CYCLE_SEC,
                min(3600, int(defaults.get("status_cycle_sec", 10))))
        except (TypeError, ValueError):
            defaults["status_cycle_sec"] = MIN_STATUS_CYCLE_SEC
        # a config written before v1.4.5 has no key at all, and the
        # missing value has to mean "random" - that is what it did
        defaults["status_random"] = bool(defaults.get("status_random", True))
        defaults["aio_templates"] = aio + [""] * (AIO_MAX - len(aio))
        defaults["aio_count"] = min(AIO_MAX, max(1, int(defaults.get("aio_count", 1))))
        # per-string dwell time + field heights. All three are absent
        # from configs written before v1.3.3, so each falls back to the
        # default above: no custom time anywhere, every field auto-grown.
        defaults["aio_custom_time"] = _bool_list(
            defaults.get("aio_custom_time"), AIO_MAX, False)
        defaults["aio_custom_sec"] = _int_list(
            defaults.get("aio_custom_sec"), AIO_MAX, 10, 2, 3600)
        defaults["aio_heights"] = _int_list(
            defaults.get("aio_heights"), AIO_MAX, 0, 0, 1200)
        # ---- AIO mode + node graph (v1.4.0) -----------------------------
        # Both are absent from every older config, which lands on "normal"
        # and an empty canvas - i.e. exactly the behaviour that setup had
        # before the Advanced page existed.
        defaults["osc_input_enabled"] = bool(
            defaults.get("osc_input_enabled", False))
        defaults["hotkey_input_enabled"] = bool(
            defaults.get("hotkey_input_enabled", False))
        defaults["stt_translate_notice"] = bool(
            defaults.get("stt_translate_notice", True))
        defaults["stt_translate_notice_text"] = str(
            defaults.get("stt_translate_notice_text")
            or DEFAULT_TRANSLATE_NOTICE)
        try:
            defaults["osc_input_port"] = min(65535, max(1024, int(
                defaults.get("osc_input_port", 9001))))
        except (TypeError, ValueError):
            defaults["osc_input_port"] = 9001
        defaults["osc_ext_ip"] = str(
            defaults.get("osc_ext_ip") or "127.0.0.1").strip() or "127.0.0.1"
        try:
            defaults["osc_ext_port"] = min(65535, max(1, int(
                defaults.get("osc_ext_port", 9002))))
        except (TypeError, ValueError):
            defaults["osc_ext_port"] = 9002
        if defaults.get("aio_mode") not in ("normal", "advanced"):
            defaults["aio_mode"] = "normal"

        graphs = defaults.get("aio_graphs")
        if not isinstance(graphs, list):
            graphs = []
        graphs = [_graph(g) for g in graphs][:AIO_MAX]
        graphs += [{"nodes": [], "edges": []}
                   for _ in range(AIO_MAX - len(graphs))]
        # an early Advanced-mode build had a single canvas whose Output
        # blocks carried a slot
        # number. Split it apart: every Output block becomes the canvas
        # of its own slot, so an early graph comes back where its author
        # would look for it instead of vanishing.
        legacy = defaults.pop("aio_graph", None)
        if isinstance(legacy, dict) and legacy.get("nodes") \
                and not any(g["nodes"] for g in graphs):
            for slot, part in _split_legacy_graph(_graph(legacy)).items():
                if 1 <= slot <= AIO_MAX:
                    graphs[slot - 1] = part
        defaults["aio_graphs"] = graphs
        # AIO template sets: normalise / migrate old single-list configs
        sets = defaults.get("aio_sets")
        if not isinstance(sets, list) or len(sets) != 10:
            sets = [{"name": f"Template {i + 1}", "templates": [""] * AIO_MAX,
                     "count": 1, "custom_time": [False] * AIO_MAX,
                     "custom_sec": [10] * AIO_MAX} for i in range(10)]
        for t in sets:
            t.setdefault("name", "Template")
            t["templates"] = ([str(x) for x in t.get("templates", [])]
                              + [""] * AIO_MAX)[:AIO_MAX]
            t["count"] = min(AIO_MAX, max(1, int(t.get("count", 1))))
            t["custom_time"] = _bool_list(t.get("custom_time"), AIO_MAX, False)
            t["custom_sec"] = _int_list(t.get("custom_sec"), AIO_MAX, 10, 2,
                                        3600)
            # one canvas per string, per template. Absent in configs
            # written before v1.4.0, which lands on empty canvases -
            # i.e. exactly what those templates had.
            tgraphs = t.get("graphs")
            tgraphs = tgraphs if isinstance(tgraphs, list) else []
            tgraphs = [_graph(g) for g in tgraphs][:AIO_MAX]
            t["graphs"] = tgraphs + [{"nodes": [], "edges": []}
                                     for _ in range(AIO_MAX - len(tgraphs))]
        defaults["aio_sets"] = sets
        aidx = min(9, max(0, int(defaults.get("aio_set_active", 0))))
        defaults["aio_set_active"] = aidx
        # an older config only had the flat aio_templates list – seed the
        # active set from it so nobody's existing string disappears
        if any(x.strip() for x in defaults["aio_templates"]) and \
                not any(x.strip() for x in sets[aidx]["templates"]):
            sets[aidx]["templates"] = list(defaults["aio_templates"])
            sets[aidx]["count"] = defaults["aio_count"]
            sets[aidx]["custom_time"] = list(defaults["aio_custom_time"])
            sets[aidx]["custom_sec"] = list(defaults["aio_custom_sec"])
        else:
            defaults["aio_templates"] = list(sets[aidx]["templates"])
            defaults["aio_count"] = sets[aidx]["count"]
            defaults["aio_custom_time"] = list(sets[aidx]["custom_time"])
            defaults["aio_custom_sec"] = list(sets[aidx]["custom_sec"])
        # ---- Custom Box -------------------------------------------------
        # Configs written before v1.3.2 have none of these keys, so every
        # one of them falls back to the default above and an existing
        # setup comes up with the frame switched off, exactly as before.
        # Everything is clamped rather than rejected: an out-of-range
        # template index would leave the button group with nothing checked
        # and the card unusable.
        # A media source key comes back from JSON as whatever was in the
        # file; anything that is not a string is not a bus name.
        src = defaults.get("media_source")
        defaults["media_source"] = src.strip() if isinstance(src, str) else ""
        lbl = defaults.get("media_source_label")
        defaults["media_source_label"] = lbl.strip()[:64] \
            if isinstance(lbl, str) else ""
        defaults["media_source_fallback"] = bool(
            defaults.get("media_source_fallback", True))
        # ---- FPS moved out in v1.4.4 -----------------------------------
        # Reading a frame rate means loading something into the game - a
        # Vulkan layer on Linux, RTSS on Windows - and that has nothing
        # to do with the /proc and /sys reading the rest of the Hardware
        # card does. It lives in the World Stats plugin now.
        #
        # The old keys are dropped rather than kept: leaving hw_fps in
        # the config would mean a stale True sitting in the file forever
        # with nothing reading it. What is NOT dropped is the fact that
        # the user had it on - _fps_moved says so once, in the log, so
        # somebody whose {fps} went quiet finds out why instead of
        # filing a bug. The MangoHud folder is carried in that message
        # too, so it can be pasted straight into the plugin.
        moved = []
        if defaults.pop("hw_fps", False):
            moved.append("FPS was switched on")
        folder = defaults.pop("hw_mangohud_dir", "")
        if isinstance(folder, str) and folder.strip():
            moved.append(f"MangoHud folder was {folder.strip()}")
        defaults.pop("hw_fps_source", None)
        self._fps_moved = moved
        defaults["media_idle"] = bool(defaults.get("media_idle", True))
        idle = defaults.get("media_idle_text", "\u23F8")
        defaults["media_idle_text"] = idle[:20] if isinstance(idle, str) \
            else "\u23F8"
        defaults["box_active"] = bool(defaults.get("box_active", False))
        defaults["box_template"] = normalize_box_template(
            defaults.get("box_template"))
        defaults["box_custom_style"] = normalize_box_custom(
            defaults.get("box_custom_style"))
        # one width used to serve both lines; carry it over to the two so
        # a config from the first Custom Box build keeps its frame. Only
        # for a side the file did not already carry its own width for.
        legacy_width = defaults.pop("box_width", None)
        for key in ("box_width_top", "box_width_bottom"):
            value = defaults.get(key)
            if key not in stored and legacy_width is not None:
                value = legacy_width
            defaults[key] = normalize_box_width(value)
        defaults["box_align"] = bool(defaults.get("box_align", True))
        for key in ("box_top_on", "box_bottom_on"):
            defaults[key] = bool(defaults.get(key, True))
        for key in ("box_top_mode", "box_bottom_mode"):
            defaults[key] = normalize_box_mode(defaults.get(key))
        for key in ("box_top_custom", "box_bottom_custom"):
            val = defaults.get(key, "")
            defaults[key] = val[:120] if isinstance(val, str) else ""
        defaults["box_clock_live"] = bool(defaults.get("box_clock_live", False))
        defaults["box_clock_format"] = normalize_clock_format(
            defaults.get("box_clock_format"))
        return defaults

    def _backup_corrupt_config(self, err):
        """Called when the config JSON can't be parsed. Copies the offending
        file to ``config.json.bak`` (so nothing is lost) and records a
        human-readable warning. Runs during __init__ before the log signal
        is connected, so the message is buffered in ``self._deferred_logs``
        and replayed once logging is ready."""
        bad = CONFIG_FILE if CONFIG_FILE.exists() else (
            OLD_CONFIG_FILE if OLD_CONFIG_FILE.exists() else None)
        msg = (f"WARNING: config file could not be read ({err}). "
               f"Falling back to default settings.")
        if bad is not None:
            backup = bad.with_suffix(bad.suffix + ".bak")
            try:
                shutil.copy2(bad, backup)
                msg += f" A backup of the corrupt file was saved to {backup}."
            except Exception as e:
                msg += f" (Could not write backup file: {e})"
        # buffer if logging isn't up yet, otherwise log straight away
        if getattr(self, "_deferred_logs", None) is not None:
            self._deferred_logs.append(msg)
        else:
            self.log(msg)
        print(msg)

    def save_config(self):
        """Writes the config immediately (used for toggles, checkboxes,
        spinboxes - things you change once)."""
        self._save_timer.stop()
        self._write_config()

    def save_config_later(self):
        """Debounced variant used ONLY by text fields: while typing, the
        file is written at most once every 800 ms instead of per keystroke.
        The single-shot timer is only armed while you type and costs
        nothing otherwise."""
        self._save_timer.start(800)

    def _write_config(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            # json.dumps escapes non-ASCII by default, so this file is
            # plain ASCII today - the encoding is pinned anyway so a
            # hand-edited config with an emoji in it still loads on
            # Windows, where the default is the locale codepage
            CONFIG_FILE.write_text(json.dumps(self.cfg, indent=2),
                                   encoding="utf-8")
        except Exception as e:
            self.log(f"Could not save settings: {e}")
