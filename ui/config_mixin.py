"""
ui/config_mixin.py – Loading, validating, migrating and saving the JSON config.

Mixin for MainWindow; see ui/mainwindow.py. Kept separate so the
window class stays small. All `self.*` refer to the MainWindow instance.
"""

import json
import shutil
from core.constants import (
    CONFIG_DIR, CONFIG_FILE, LYRICS_DIR, OLD_CONFIG_FILE, TITLE_MAX_LEN)
from core.textutils import DEFAULT_CUSTOM_BAR, TIME_POS_LINE
from core.translators import METHOD_LINGVA


class ConfigMixin:
    def load_config(self):
        defaults = {
            "status_text": "",
            "status_texts": [""] * 20,   # mirror of the ACTIVE template
            "status_count": 1,
            "status_cycle_sec": 10,
            # 10 switchable text templates, each with its own 1-20 texts
            "status_templates": [
                {"name": f"Template {i + 1}", "texts": [""] * 20,
                 "count": 1} for i in range(10)
            ],
            "status_template_active": 0,
            "status_active": True,
            "media_active": False,
            "media_show_artist": True,
            "media_show_title": True,
            "media_title_max": TITLE_MAX_LEN,  # song title cutoff (3-64)
            "media_show_time": True,
            "media_time_seconds": True,  # time incl. seconds (3:27);
                                         # off = old h:mm style (0:03)
            "media_show_lyrics": False,  # synced lyrics via LRCLIB
                                         # (off = zero network requests)
            "media_lyrics_local": False,  # use your own local .lrc files
            "media_lyrics_dir": str(LYRICS_DIR),  # folder with .lrc files
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
            "stt_block_saved": [],
            "stt_mode": "stt",       # "stt" (speech->text) | "ttt" (text->text)
            "stt_show_both": False,  # send "source -> translation" in chat
            "aio_active": False,
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
            "hw_cpu_temp": True,
            "send_to_vrchat": False,
            "interval_sec": 5,
            "slim_chatbox": True,   # slim bar instead of big box, default ON
            "osc_ip": "127.0.0.1",
            "osc_port": 9000,
            "debug": False,
        }
        try:
            if CONFIG_FILE.exists():
                defaults.update(json.loads(CONFIG_FILE.read_text()))
            elif OLD_CONFIG_FILE.exists():
                # migrate settings from the old location
                defaults.update(json.loads(OLD_CONFIG_FILE.read_text()))
        except Exception as e:
            # a broken/corrupt config must not silently wipe the user's
            # settings – back the file up so it can be inspected/recovered,
            # then continue with defaults and warn the user.
            self._backup_corrupt_config(e)
        # migrate the old single status text into the text list
        texts = defaults.get("status_texts")
        if not isinstance(texts, list):
            texts = [""] * 10
        texts = [str(t) for t in texts][:10] + [""] * max(0, 10 - len(texts))
        if defaults.get("status_text") and not any(t.strip() for t in texts):
            texts[0] = defaults["status_text"]
        defaults["status_texts"] = texts
        # pad the active texts to 20 (older configs had 10)
        while len(defaults["status_texts"]) < 20:
            defaults["status_texts"].append("")
        defaults["status_count"] = min(20, max(1, int(defaults.get("status_count", 1))))
        # templates: normalise / migrate old single-list configs
        tpls = defaults.get("status_templates")
        if not isinstance(tpls, list) or len(tpls) != 10:
            tpls = [{"name": f"Template {i + 1}", "texts": [""] * 20,
                     "count": 1} for i in range(10)]
        for t in tpls:
            t.setdefault("name", "Template")
            t["texts"] = (list(t.get("texts", [])) + [""] * 20)[:20]
            t["count"] = min(20, max(1, int(t.get("count", 1))))
        defaults["status_templates"] = tpls
        idx = min(9, max(0, int(defaults.get("status_template_active", 0))))
        defaults["status_template_active"] = idx
        # keep the active template in sync with the mirror fields
        if any(x.strip() for x in defaults["status_texts"]) and \
                not any(x.strip() for x in tpls[idx]["texts"]):
            tpls[idx]["texts"] = list(defaults["status_texts"])
            tpls[idx]["count"] = defaults["status_count"]
        else:
            defaults["status_texts"] = list(tpls[idx]["texts"])
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
            CONFIG_FILE.write_text(json.dumps(self.cfg, indent=2))
        except Exception as e:
            self.log(f"Could not save settings: {e}")
