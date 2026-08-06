"""
ui/config_mixin.py – Loading, validating, migrating and saving the JSON config.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.
"""

import json
import shutil
from core.theming import THEMES
from core.textstyle import STYLE_NORMAL, normalize as normalize_style
from core.constants import (
    CONFIG_DIR, CONFIG_FILE, LYRICS_DIR, MIN_STATUS_CYCLE_SEC, OLD_CONFIG_FILE, TITLE_MAX_LEN)
from core.boxstyle import (
    CLOCK_24_HM, DEFAULT_CUSTOM_BOX, MODE_CUSTOM as BOX_MODE_CUSTOM, normalize_clock_format, normalize_custom as normalize_box_custom, normalize_mode as normalize_box_mode, normalize_template as normalize_box_template, normalize_width as normalize_box_width)
from core.textutils import DEFAULT_CUSTOM_BAR, TIME_POS_LINE
from core.translators import METHOD_LINGVA


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
            "stt_mode": "stt",       # "stt" (speech->text) | "ttt" (text->text)
            "stt_show_both": False,  # send "source -> translation" in chat
            "aio_active": False,
            # FPS via MangoHud's log (see core/hardware.py)
            "hw_fps": False,
            "hw_mangohud_dir": "",
            # customization (core/theming.py)
            "theme": "default",
            "theme_colors": {},        # theme id -> {token: "#rrggbb"}
            "theme_background": "",    # file name inside config/backgrounds
            "theme_opacity": 0.82,     # card opacity when a background is set
            "aio_count": 1,
            # 10 switchable AIO layouts, each with its own 1-5 strings
            "aio_sets": [
                {"name": f"Template {i + 1}", "templates": [""] * 5,
                 "count": 1} for i in range(10)
            ],
            "aio_set_active": 0,
            "aio_rotate": False,
            "aio_rotate_sec": 10,
            "aio_templates": ["{text} \\n {artist} : {title} | {time} \\n {bar}",
                              "", "", "", ""],
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
            aio = ["{text} \\n {artist} : {title} | {time} \\n {bar}", "", "", "", ""]
        aio = [str(t) for t in aio][:5]
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
        # older configs may still carry a 2 s cycle from before the
        # 10 s minimum - lift those instead of leaving an out-of-range
        # value that the spin box cannot even display
        try:
            defaults["status_cycle_sec"] = max(
                MIN_STATUS_CYCLE_SEC,
                min(3600, int(defaults.get("status_cycle_sec", 10))))
        except (TypeError, ValueError):
            defaults["status_cycle_sec"] = MIN_STATUS_CYCLE_SEC
        defaults["aio_templates"] = aio + [""] * (5 - len(aio))
        defaults["aio_count"] = min(5, max(1, int(defaults.get("aio_count", 1))))
        # AIO template sets: normalise / migrate old single-list configs
        sets = defaults.get("aio_sets")
        if not isinstance(sets, list) or len(sets) != 10:
            sets = [{"name": f"Template {i + 1}", "templates": [""] * 5,
                     "count": 1} for i in range(10)]
        for t in sets:
            t.setdefault("name", "Template")
            t["templates"] = ([str(x) for x in t.get("templates", [])]
                              + [""] * 5)[:5]
            t["count"] = min(5, max(1, int(t.get("count", 1))))
        defaults["aio_sets"] = sets
        aidx = min(9, max(0, int(defaults.get("aio_set_active", 0))))
        defaults["aio_set_active"] = aidx
        # an older config only had the flat aio_templates list – seed the
        # active set from it so nobody's existing string disappears
        if any(x.strip() for x in defaults["aio_templates"]) and \
                not any(x.strip() for x in sets[aidx]["templates"]):
            sets[aidx]["templates"] = list(defaults["aio_templates"])
            sets[aidx]["count"] = defaults["aio_count"]
        else:
            defaults["aio_templates"] = list(sets[aidx]["templates"])
            defaults["aio_count"] = sets[aidx]["count"]
        # ---- Custom Box -------------------------------------------------
        # Configs written before v1.3.2 have none of these keys, so every
        # one of them falls back to the default above and an existing
        # setup comes up with the frame switched off, exactly as before.
        # Everything is clamped rather than rejected: an out-of-range
        # template index would leave the button group with nothing checked
        # and the card unusable.
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
