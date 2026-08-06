"""
ui/mainwindow.py – main window of OSC-DreamChatbox
(pages: Apps, Textbox, Options)

The per-page UI + handlers live in mixins (ui/pages/, ui/config_mixin.py)
to keep this file focused on window scaffolding, the send pipeline and
shared plumbing. MainWindow composes them via multiple inheritance, so
every method still runs as a normal MainWindow method (self is the window).
"""

import queue as _queue
import threading
import time
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)
from core.constants import (
    APP_NAME, CHATBOX_INPUT, CHATBOX_LIMIT, OSC_MIN_SEND_GAP_SEC, OSC_RATE_MAX_SENDS, OSC_RATE_WINDOW_SEC, SLIM_SUFFIX, VERSION)
from core.hardware import HardwareMonitor
from core.lyrics import LyricsFetcher
from core.mediafetch import MediaFetcher
from core.oscquery import HAS_ZEROCONF, OSCQueryService
from core.theming import build_style
from core.plugins import PluginManager
from core.speechtotext import SpeechWorker
from core.textstyle import STYLE_NORMAL, apply_style
from core.textutils import (
    CUSTOM_STYLE_INDEX, DEFAULT_CUSTOM_BAR, TIME_POS_LINE, fmt_time, fmt_time_hm)
from core.translators import LibreTranslateServer, METHOD_DEEPL, METHOD_LINGVA
from ui.ui_main import (
    DebugConsole, EmojiPopup, STYLE, ToggleLabel, ToggleSwitch)
from ui.config_mixin import ConfigMixin
from ui.pages.apps_page import AppsPageMixin
from ui.pages.custom_box import CustomBoxMixin
from ui.pages.textbox_page import TextboxPageMixin
from ui.pages.options_page import OptionsPageMixin
from ui.pages.plugins_page import PluginsPageMixin


class MainWindow(ConfigMixin, AppsPageMixin, CustomBoxMixin,
                 TextboxPageMixin, OptionsPageMixin, PluginsPageMixin,
                 QMainWindow):
    # emitted by log() – possibly from background threads (lyrics
    # fetcher, OSCQuery/mDNS listeners). Qt delivers cross-thread
    # signals as queued connection, so the debug console is only
    # ever touched from the GUI thread (direct calls SIGSEGV).
    _log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OSC DreamChatbox")
        self.resize(1024, 760)
        self.setMinimumSize(760, 420)  # freely resizable, pages scroll instead

        # --- state / settings ---
        # warnings raised before the debug console / log signal exist are
        # buffered here and flushed once logging is wired up below
        self._deferred_logs = []
        self.cfg = self.load_config()
        self.osc_client = None
        self.debug_console = DebugConsole(APP_NAME)
        self._log_signal.connect(self._log_gui)
        # now that logging works, replay anything buffered during load_config
        for _m in self._deferred_logs:
            self.log(_m)
        self._deferred_logs = []
        self.emoji_popup = EmojiPopup()
        self.status_index = 0
        # a text switch waiting to be sent - see advance_status()
        self.pending_status_index = None
        self.media = MediaFetcher(self.log)
        self.media_info = None
        self.lyrics = LyricsFetcher(self.log)
        self.manual_pause_until = 0.0
        self.last_manual_text = ""
        # OSC rate limiting (see _osc_send_delay): timestamps of the
        # sends inside the current window, and the payload that is
        # actually on screen in VRChat right now.
        self._send_times = []
        self._last_sent_payload = None
        self.aio_index = 0
        self.stt = SpeechWorker()
        self.stt_recording = False
        self.oscq = OSCQueryService(APP_NAME, self.log)
        self.libre_server = LibreTranslateServer(self.log)
        self._oscq_applied = None   # zuletzt uebernommenes VRChat-Ziel
        self._block_updating = False
        self.hw = HardwareMonitor(
            self.log, self.cfg.get("hw_mangohud_dir") or None)
        self.hw_info = None
        # user plugins (core/plugins.py) – discovered before build_ui()
        # so the Plugins page can render the list right away. Their
        # settings live in plugins/<id>/configs/config.json, not in cfg.
        self.plugins = PluginManager(self.log, host=self)
        self.plugins.discover()

        # --- timers ---
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._write_config)
        self.send_timer = QTimer(self)
        self.send_timer.timeout.connect(self.send_now)
        # fires once when a send had to be postponed for the rate limit
        self.pending_send_timer = QTimer(self)
        self.pending_send_timer.setSingleShot(True)
        self.pending_send_timer.timeout.connect(self.send_now)
        self.media_timer = QTimer(self)
        self.media_timer.timeout.connect(self.poll_media)
        self.rotate_timer = QTimer(self)
        self.rotate_timer.timeout.connect(self.advance_status)
        self.aio_timer = QTimer(self)
        self.aio_timer.timeout.connect(self.advance_aio)
        # Custom Box clock. Only ever runs while the realtime toggle is
        # on AND a side is set to Clock - see _update_box_timer().
        self.box_timer = QTimer(self)
        self.box_timer.timeout.connect(self._box_tick)
        self._box_clock_last = None
        self.stt_timer = QTimer(self)
        self.stt_timer.timeout.connect(self.poll_stt)
        self.hw_timer = QTimer(self)
        self.hw_timer.timeout.connect(self.poll_hw)
        # refreshes the preview so live plugin values (clocks, world info)
        # stay current between sends
        self.plugin_timer = QTimer(self)
        self.plugin_timer.timeout.connect(self.update_preview)

        self.build_ui()
        self.apply_config_to_ui()
        # import enabled plugins once the window is fully built, so a
        # plugin's setup(api) can already touch api.host safely
        self.mangohud_dir_lbl.setText(
            self.cfg.get("hw_mangohud_dir") or "(not set)")
        self.plugins.load_enabled()
        self.refresh_plugin_list()
        self._update_plugin_timer()
        # natives OSCQuery: dynamische Ports + VRChat-Discovery
        self.oscq_timer = QTimer(self)
        self.oscq_timer.timeout.connect(self.poll_oscquery)
        if self.cfg.get("oscquery_enabled") and HAS_ZEROCONF:
            if self.oscq.start():
                self.oscq_timer.start(2000)
        self.update_osc_client()
        self.update_timers()

    def run_async(self, work, on_done, interval=200, on_error=None):
        """Runs ``work()`` in a daemon thread and delivers its return value
        to ``on_done(result)`` back on the GUI thread. This is the single
        implementation of the worker+queue+QTimer pattern used everywhere
        (translation test, text-to-text, update check, media/hardware polls).

        The worker thread NEVER touches the GUI; the result travels through a
        Queue and a short-lived QTimer that is disposed of once it fires, so
        no timer objects accumulate on the window. Exceptions inside ``work``
        are caught and logged instead of silently hanging the poller.

        ``on_error(exception)`` is the important half of that promise. Any
        caller that flips a "busy" flag before starting MUST pass it,
        because a failing ``work()`` used to mean ``on_done`` never ran -
        so the flag stayed True and that poller (or the whole plugin
        store) was dead until the app restarted. One offline moment was
        enough to lose the Store for the rest of the session.
        """
        q = _queue.Queue()

        def worker():
            try:
                q.put((True, work()))
            except Exception as e:
                q.put((False, e))
        threading.Thread(target=worker, daemon=True).start()

        timer = QTimer(self)

        def poll():
            try:
                ok, res = q.get_nowait()
            except _queue.Empty:
                return
            timer.stop()
            timer.deleteLater()   # don't leak one QTimer per call
            if ok:
                # An exception raised inside a Qt slot does not just get
                # printed: PyQt6 hands it to sys.excepthook, whose default
                # aborts the process. A callback bug must not take the
                # whole app down with it.
                try:
                    on_done(res)
                except Exception as e:      # noqa: BLE001
                    self.log(f"run_async: result handler failed: "
                             f"{type(e).__name__}: {e}")
            else:
                self.log(f"run_async: background task failed: {res}")
                if on_error is not None:
                    try:
                        on_error(res)
                    except Exception as e:  # noqa: BLE001
                        self.log(f"run_async: error handler failed: "
                                 f"{type(e).__name__}: {e}")
        timer.timeout.connect(poll)
        timer.start(interval)
        return timer

    def build_ui(self):
        root = QWidget()
        root.setObjectName("root")   # theming paints the background here
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        # ===================== sidebar (left) =====================
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 20, 12, 12)
        sb_layout.setSpacing(6)

        self.btn_apps = QPushButton("Apps")
        self.btn_textbox = QPushButton("Textbox")
        self.btn_plugins = QPushButton("Plugins")
        self.btn_options = QPushButton("Options")
        self.nav_buttons = (self.btn_apps, self.btn_textbox,
                            self.btn_plugins, self.btn_options)
        for i, b in enumerate(self.nav_buttons):
            b.setObjectName("navbtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, idx=i: self.switch_page(idx))
            sb_layout.addWidget(b)
        self.btn_apps.setChecked(True)
        sb_layout.addStretch()

        # ===================== middle (pages) =====================
        self.pages = QStackedWidget()
        self.pages.addWidget(self._wrap_scroll(self.build_apps_page()))
        self.pages.addWidget(self._wrap_scroll(self.build_textbox_page()))
        # order must match nav_buttons above - switch_page() indexes both
        self.pages.addWidget(self._wrap_scroll(self.build_plugins_page()))
        self.pages.addWidget(self._wrap_scroll(self.build_options_page()))

        # ===================== right column =====================
        right = QFrame()
        right.setObjectName("rightpanel")
        right.setFixedWidth(250)
        r_layout = QVBoxLayout(right)
        r_layout.setContentsMargins(14, 14, 14, 10)
        r_layout.setSpacing(14)

        preview_frame = QFrame()
        preview_frame.setObjectName("previewbox")
        pv_layout = QVBoxLayout(preview_frame)
        pv_layout.setContentsMargins(10, 8, 10, 10)
        pv_title = QLabel("Preview")
        pv_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        pv_title.setObjectName("previewtitle")
        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.preview_label.setMinimumHeight(140)
        pv_layout.addWidget(pv_title)
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setObjectName("hline")
        pv_layout.addWidget(line)
        pv_layout.addWidget(self.preview_label, 1)
        self.char_count_lbl = QLabel("")
        self.char_count_lbl.setObjectName("dim")
        self.char_count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        pv_layout.addWidget(self.char_count_lbl)
        r_layout.addWidget(preview_frame)

        # SendToVRChat (below Preview, above Debug)
        row1 = QHBoxLayout()
        self.toggle_send = ToggleSwitch()
        self.toggle_send.toggled.connect(self.on_send_toggled)
        row1.addWidget(self.toggle_send)
        row1.addWidget(ToggleLabel("SendToVRChat", self.toggle_send))
        row1.addStretch()
        r_layout.addLayout(row1)

        # Debug Toggle
        row2 = QHBoxLayout()
        self.toggle_debug = ToggleSwitch()
        self.toggle_debug.toggled.connect(self.on_debug_toggled)
        row2.addWidget(self.toggle_debug)
        row2.addWidget(ToggleLabel("Debug Toggle", self.toggle_debug))
        row2.addStretch()
        r_layout.addLayout(row2)

        r_layout.addStretch()

        ver = QLabel(VERSION)
        ver.setObjectName("dim")
        ver.setAlignment(Qt.AlignmentFlag.AlignRight)
        r_layout.addWidget(ver)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.pages, 1)
        root_layout.addWidget(right)

        self.apply_theme()

    @staticmethod
    def _wrap_scroll(widget):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(widget)
        return sa

    def make_settings_expander(self, on_toggled, label="Settings"):
        """The › / ⌄ arrow every collapsible block uses. `label` is only
        for blocks that are not settings - the Parameters list under All
        in one, for instance - so every existing caller keeps its text
        without passing anything."""
        btn = QPushButton(f"›  {label}")
        btn.setObjectName("expander")
        btn.setCheckable(True)
        btn.setChecked(False)  # collapsed by default on start
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.toggled.connect(on_toggled)
        return btn

    @staticmethod
    def set_expanded(btn, content, expanded, label="Settings"):
        content.setVisible(expanded)
        btn.setText((f"⌄  {label}") if expanded else (f"›  {label}"))

    def apply_theme(self):
        """(Re)builds the stylesheet from the current theme settings and
        applies it to the whole window. Cheap enough to call on every
        change, so the colour picker can update live."""
        try:
            style = build_style(
                STYLE,
                self.cfg.get("theme", "default"),
                self.cfg.get("theme_colors", {}).get(
                    self.cfg.get("theme", "default"), {}),
                self.cfg.get("theme_background", ""),
                float(self.cfg.get("theme_opacity", 0.82)))
        except Exception as e:      # noqa: BLE001 - never leave it unstyled
            self.log(f"Theme could not be built ({e}), using the default")
            style = STYLE
        self.setStyleSheet(style)

    def switch_page(self, idx):
        self.pages.setCurrentIndex(idx)
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == idx)

    def apply_config_to_ui(self):
        self._block_updating = True
        for i, edit in enumerate(self.status_edits):
            edit.setText(self.cfg["status_texts"][i])
            self.set_style_combo(self.status_style_combos[i],
                                 self.cfg["status_styles"][i])
        self.status_count_spin.setValue(self.cfg["status_count"])
        self.status_cycle_spin.setValue(self.cfg["status_cycle_sec"])
        self.tpl_buttons[self.cfg["status_template_active"]].setChecked(True)
        self._update_texts_expander_label()
        for i, row in enumerate(self.status_rows):
            row.setVisible(i < self.cfg["status_count"])
        self.toggle_active.setChecked(self.cfg["status_active"])
        self.toggle_media.setChecked(self.cfg["media_active"])
        self.chk_artist.setChecked(self.cfg["media_show_artist"])
        self.chk_title.setChecked(self.cfg["media_show_title"])
        tmax = self._title_max()
        self.cfg["media_title_max"] = tmax
        self.title_max_slider.blockSignals(True)
        self.title_max_slider.setValue(tmax)
        self.title_max_slider.blockSignals(False)
        self.title_max_lbl.setText(f"{tmax} characters")
        self.chk_time.setChecked(self.cfg["media_show_time"])
        self.chk_time_seconds.setChecked(
            self.cfg.get("media_time_seconds", True))
        self.set_style_combo(self.time_style_combo,
                             self.cfg.get("media_time_style", STYLE_NORMAL))
        self.chk_lyrics.setChecked(self.cfg.get("media_show_lyrics", False))
        self.chk_lyrics_local.setChecked(
            self.cfg.get("media_lyrics_local", False))
        prefix_on = bool(self.cfg.get("media_lyrics_prefix_on", True))
        self.chk_lyrics_prefix.blockSignals(True)
        self.chk_lyrics_prefix.setChecked(prefix_on)
        self.chk_lyrics_prefix.blockSignals(False)
        self.lyrics_prefix_input.blockSignals(True)
        self.lyrics_prefix_input.setText(
            str(self.cfg.get("media_lyrics_prefix", "\u266a"))[:4])
        self.lyrics_prefix_input.blockSignals(False)
        self.lyrics_prefix_input.setEnabled(prefix_on)
        self.chk_bar.setChecked(self.cfg["media_show_bar"])
        # local lyrics folder row + fetcher state
        self._sync_lyrics_local()
        self.bar_style_combo.blockSignals(True)
        idx = min(CUSTOM_STYLE_INDEX,
                  max(0, int(self.cfg.get("media_bar_style", 2))))
        self.bar_style_combo.setCurrentIndex(idx)
        self.bar_style_combo.blockSignals(False)
        custom = dict(DEFAULT_CUSTOM_BAR)
        custom.update(self.cfg.get("media_bar_custom", {}))
        self.cfg["media_bar_custom"] = custom
        for key, edit in self.bar_custom_inputs.items():
            edit.blockSignals(True)
            edit.setText(custom.get(key, ""))
            edit.blockSignals(False)
        size = min(100, max(30, int(self.cfg.get("media_bar_size", 100))))
        self.cfg["media_bar_size"] = size
        self.bar_size_slider.blockSignals(True)
        self.bar_size_slider.setValue(size)
        self.bar_size_slider.blockSignals(False)
        self.bar_size_lbl.setText(f"{size}%")
        tpos = self.cfg.get("media_time_pos", TIME_POS_LINE)
        tidx = next((i for i in range(self.time_pos_combo.count())
                     if self.time_pos_combo.itemData(i) == tpos), 0)
        self.time_pos_combo.blockSignals(True)
        self.time_pos_combo.setCurrentIndex(tidx)
        self.time_pos_combo.blockSignals(False)
        self._update_bar_custom_preview()
        self._update_bar_line_preview()
        self._sync_media_dependents()
        self.poll_spin.setValue(self.cfg["media_poll_sec"])
        self.chk_media_icon.setChecked(self.cfg["media_icon"])
        self.chk_media_idle.setChecked(self.cfg["media_idle"])
        self.media_idle_input.setText(self.cfg["media_idle_text"])
        self.chk_media_custom.setChecked(self.cfg["media_custom"])
        self.media_custom_input.setText(self.cfg["media_custom_template"])
        for i, edit in enumerate(self.preset_edits):
            edit.setText(self.cfg["textbox_presets"][i])
        self.preset_count_spin.setValue(self.cfg["textbox_preset_count"])
        for i, row in enumerate(self.preset_rows):
            row.setVisible(i < self.cfg["textbox_preset_count"])
        self.pause_spin.setValue(self.cfg["textbox_pause_sec"])
        self.toggle_stt_block.setChecked(self.cfg["stt_block"])
        self.toggle_stt_mode.blockSignals(True)
        self.toggle_stt_mode.setChecked(
            self.cfg.get("stt_mode", "stt") == "ttt")
        self.toggle_stt_mode.blockSignals(False)
        self.toggle_stt_both.setChecked(self.cfg.get("stt_show_both", False))
        self._sync_mode_ui()
        idx = self.stt_lang_combo.findData(self.cfg["stt_language"])
        if idx >= 0:
            self.stt_lang_combo.setCurrentIndex(idx)
        oidx = self.stt_out_combo.findData(self.cfg["stt_output"])
        if oidx >= 0:
            self.stt_out_combo.setCurrentIndex(oidx)
        # Migration: alte "stt_deepl"-Checkbox-Configs uebernehmen
        if self.cfg.get("stt_deepl") and self.cfg.get(
                "stt_method", METHOD_LINGVA) == METHOD_LINGVA:
            self.cfg["stt_method"] = METHOD_DEEPL
        self.tr_method_combo.blockSignals(True)
        midx = next((i for i in range(self.tr_method_combo.count())
                     if self.tr_method_combo.itemData(i)
                     == self.cfg.get("stt_method", METHOD_LINGVA)), 0)
        self.tr_method_combo.setCurrentIndex(midx)
        self.tr_method_combo.blockSignals(False)
        self.deepl_key_input.setText(self.cfg["stt_deepl_key"])
        self.google_key_input.setText(self.cfg.get("stt_google_key", ""))
        self.libre_url_input.setText(self.cfg.get("stt_libre_url", ""))
        self.libre_online_url_input.blockSignals(True)
        self.libre_online_url_input.setText(
            self.cfg.get("stt_libre_online_url", ""))
        self.libre_online_url_input.blockSignals(False)
        self.libre_online_key_input.blockSignals(True)
        self.libre_online_key_input.setText(
            self.cfg.get("stt_libre_online_key", ""))
        self.libre_online_key_input.blockSignals(False)
        self._sync_libre_online_ui()
        pos = self.mic_combo.findData(self.cfg.get("stt_mic", ""))
        self.mic_combo.blockSignals(True)
        self.mic_combo.setCurrentIndex(pos if pos >= 0 else 0)
        self.mic_combo.blockSignals(False)
        self._update_tr_method_ui()
        self.toggle_aio.setChecked(self.cfg["aio_active"])
        self.aio_set_buttons[self.cfg["aio_set_active"]].setChecked(True)
        self.aio_count_spin.setValue(self.cfg["aio_count"])
        self.chk_aio_rotate.setChecked(self.cfg["aio_rotate"])
        self.aio_rotate_spin.setValue(self.cfg["aio_rotate_sec"])
        for i, edit in enumerate(self.aio_edits):
            edit.setText(self.cfg["aio_templates"][i])
        for i, row in enumerate(self.aio_rows):
            row.setVisible(i < self.cfg["aio_count"])
        self.apply_box_config_to_ui()
        self.chk_hw_flame.setChecked(self.cfg["hw_flame"])
        self.chk_hw_custom.setChecked(self.cfg["hw_custom"])
        self.hw_custom_input.setText(self.cfg["hw_custom_template"])
        self.toggle_hw.setChecked(self.cfg["hw_active"])
        self.chk_gpu_usage.setChecked(self.cfg["hw_gpu_usage"])
        self.chk_gpu_name.setChecked(self.cfg["hw_gpu_name"])
        self.chk_gpu_custom.setChecked(self.cfg["hw_gpu_custom"])
        self.gpu_custom_input.setText(self.cfg["hw_gpu_custom_name"])
        self.set_style_combo(self.gpu_style_combo,
                             self.cfg.get("hw_gpu_name_style", STYLE_NORMAL))
        self.set_style_combo(self.cpu_style_combo,
                             self.cfg.get("hw_cpu_name_style", STYLE_NORMAL))
        self.chk_gpu_temp.setChecked(self.cfg["hw_gpu_temp"])
        self.chk_vram_used.setChecked(self.cfg["hw_vram_used"])
        self.chk_vram_pct.setChecked(self.cfg["hw_vram_pct"])
        self.chk_ram_used.setChecked(self.cfg["hw_ram_used"])
        self.chk_ram_pct.setChecked(self.cfg["hw_ram_pct"])
        self.ram_type_input.setText(self.cfg["hw_ram_type"])
        self.chk_cpu_usage.setChecked(self.cfg["hw_cpu_usage"])
        self.chk_cpu_name.setChecked(self.cfg["hw_cpu_name"])
        self.chk_cpu_custom.setChecked(self.cfg["hw_cpu_custom"])
        self.cpu_custom_input.setText(self.cfg["hw_cpu_custom_name"])
        self.chk_cpu_temp.setChecked(self.cfg["hw_cpu_temp"])
        self.hw_poll_spin.setValue(self.cfg["hw_poll_sec"])
        self.toggle_send.setChecked(self.cfg["send_to_vrchat"])
        self.interval_spin.setValue(self.cfg["interval_sec"])
        self.toggle_instant.blockSignals(True)
        self.toggle_instant.setChecked(
            bool(self.cfg.get("osc_instant_send", True)))
        self.toggle_instant.blockSignals(False)
        self.toggle_slim.setChecked(self.cfg["slim_chatbox"])
        self.toggle_oscquery.blockSignals(True)
        self.toggle_oscquery.setChecked(
            bool(self.cfg.get("oscquery_enabled", True)) and HAS_ZEROCONF)
        self.toggle_oscquery.blockSignals(False)
        self.ip_input.setText(self.cfg["osc_ip"])
        self.port_input.setValue(self.cfg["osc_port"])
        self.toggle_debug.setChecked(self.cfg["debug"])
        self.update_preview()
        self._block_updating = False

    def anything_to_send(self):
        status_on = self.cfg["status_active"] and bool(self.current_status_text())
        media_on = self.cfg["media_active"] and self.media_info is not None
        return status_on or media_on

    def update_timers(self):
        # media poll timer
        if self.cfg["media_active"]:
            self.media_timer.start(self.cfg["media_poll_sec"] * 1000)
        else:
            self.media_timer.stop()
        # hardware poll timer
        if self.cfg["hw_active"]:
            self.hw_timer.start(self.cfg["hw_poll_sec"] * 1000)
        else:
            self.hw_timer.stop()
        # status text rotation
        active_texts = [t for t in
                        self.cfg["status_texts"][:self.cfg["status_count"]]
                        if t.strip()]
        if (self.cfg["status_active"] and self.cfg["status_count"] > 1
                and len(active_texts) > 1):
            self.rotate_timer.start(self.cfg["status_cycle_sec"] * 1000)
        else:
            self.rotate_timer.stop()
            self.status_index = 0
        # a text switch waiting to be sent - see advance_status()
        self.pending_status_index = None
        # AIO string rotation (only when AIO active, rotation enabled
        # and more than one non-empty string exists)
        if (self.cfg["aio_active"] and self.cfg["aio_rotate"]
                and len(self._aio_active_templates()) > 1):
            self.aio_timer.start(self.cfg["aio_rotate_sec"] * 1000)
        else:
            self.aio_timer.stop()
            self.aio_index = 0
        # Custom Box clock (started only when it can change anything)
        self._update_box_timer()
        # send timer
        if self.cfg["send_to_vrchat"]:
            self.send_timer.start(self.cfg["interval_sec"] * 1000)
        else:
            self.send_timer.stop()

    def build_payload(self):
        """Combines all active apps in the order of the cards (drag to change).
        If All in one is active, only the AIO string is sent instead."""
        # one snapshot per frame: every plugin hook runs exactly once, no
        # matter how many templates ask for its values below
        self.plugins.invalidate()
        # plugin lines grouped by the app they are anchored above; each
        # group is already in the order set on the Plugins page
        anchored = self.plugins.lines_by_anchor()
        if self.cfg["aio_active"]:
            # All in one is one block at the very bottom, so every plugin
            # line goes above it - anchors have nothing else to sit on here
            lines = self.plugins.render_lines()
            lines.extend(self.build_aio_lines())
            return self.plugins.filter_text(
                "\n".join(self._apply_custom_box(lines)))
        lines = []
        for key in self.cfg["app_order"]:
            lines.extend(anchored.get(key, []))    # anchored ABOVE this app
            if key == "status" and self.cfg["status_active"]:
                cur = self._render_status(self.current_status_text(),
                                          self.current_status_style())
                if cur:
                    lines.append(cur)
            elif key == "media" and self.cfg["media_active"]:
                lines.extend(self.build_media_lines())
            elif key == "hardware" and self.cfg["hw_active"]:
                lines.extend(self.build_hw_lines())
        # "Above All in one" with AIO off means: after everything else
        lines.extend(anchored.get("aio", []))
        return self.plugins.filter_text(
            "\n".join(self._apply_custom_box(lines)))

    def sending_live(self):
        """True when a payload would actually reach VRChat right now.

        This used to read a key called "send_active", which has not
        existed in the config since the toggle was renamed to
        "send_to_vrchat" - so it was False for everybody, always.
        Every instant send behind it (a rotated text, a switched
        template) silently did nothing and VRChat only caught up on the
        next interval tick, up to `interval_sec` later. That is exactly
        the "VRChat doesn't get the updates as fast as the app does"
        report from Discord.
        """
        return bool(self.cfg.get("send_to_vrchat")
                    and self.osc_client is not None
                    and not self.stt_recording
                    and time.time() >= self.manual_pause_until)

    def _osc_send_delay(self, now=None):
        """Seconds to wait before the next chatbox message may go out.
        0.0 means "right now".

        VRChat allows about 5 chatbox messages inside a 5 second window;
        going over that earns a ~30 second cooldown during which nothing
        is displayed at all. So a burst is not merely wasteful, it makes
        the chatbox go blank - much worse than being a second late.

        Two rules, whichever is stricter wins:
          * a minimum gap between two consecutive sends, and
          * at most OSC_RATE_MAX_SENDS inside the rolling window.
        """
        now = time.time() if now is None else now
        # drop everything that fell out of the window
        self._send_times = [t for t in self._send_times
                            if now - t < OSC_RATE_WINDOW_SEC]
        delay = 0.0
        if self._send_times:
            gap = OSC_MIN_SEND_GAP_SEC - (now - self._send_times[-1])
            delay = max(delay, gap)
        if len(self._send_times) >= OSC_RATE_MAX_SENDS:
            # wait until the oldest send leaves the window
            oldest = self._send_times[-OSC_RATE_MAX_SENDS]
            delay = max(delay, OSC_RATE_WINDOW_SEC - (now - oldest))
        return max(0.0, delay)

    def request_send(self):
        """Asks for the current payload to reach VRChat as soon as the
        rate limit allows.

        Called whenever the text may have changed. Repeat calls inside
        the waiting period COALESCE into the single pending send instead
        of queueing up, so typing in a status field costs one message,
        not one per keystroke.
        """
        if not self.cfg.get("osc_instant_send", True):
            return
        if not self.sending_live():
            return
        delay = self._osc_send_delay()
        if delay <= 0:
            self.send_after_change()
        elif not self.pending_send_timer.isActive():
            self.pending_send_timer.start(int(delay * 1000) + 20)

    def send_after_change(self):
        """Sends immediately because the text changed, and restarts the
        send timer from now.

        Restarting matters: otherwise a scheduled tick can land a fraction
        of a second later and send the very same payload twice, which
        counts against VRChat's chatbox rate limit for nothing.
        """
        if not self.sending_live():
            return
        self.send_now()
        if self.send_timer.isActive():
            self.send_timer.start(self.cfg["interval_sec"] * 1000)

    def send_now(self):
        if self.stt_recording:
            return  # speech to text is recording - sending is blocked
        if time.time() < self.manual_pause_until:
            return  # a manual textbox message is currently shown
        delay = self._osc_send_delay()
        if delay > 0:
            # too soon for VRChat - postpone instead of dropping, so the
            # text still arrives, just at the earliest legal moment
            if not self.pending_send_timer.isActive():
                self.pending_send_timer.start(int(delay * 1000) + 20)
            return
        # take over a pending text switch, so what we send is exactly what
        # the preview shows afterwards
        self.commit_status()
        text = self.build_payload()
        if not text or self.osc_client is None:
            return
        if self.cfg["slim_chatbox"]:
            # the slim suffix ALWAYS stays at the end - if the text is too
            # long, the text itself gets trimmed instead of dropping the
            # suffix (otherwise the big box would suddenly come back)
            text = text[:CHATBOX_LIMIT - len(SLIM_SUFFIX)]
            payload = text + SLIM_SUFFIX
        else:
            payload = text[:CHATBOX_LIMIT]
        try:
            # /chatbox/input  [text, send immediately (no keyboard), no sound]
            self.osc_client.send_message(CHATBOX_INPUT, [payload, True, False])
            # only a send that actually went out counts against the limit
            self._send_times.append(time.time())
            self._last_sent_payload = payload
            slim = " [+SLIM]" if payload != text else ""
            self.log(f"-> OSC {CHATBOX_INPUT} {text.count(chr(10)) + 1} line(s), "
                     f"{len(payload)} chars{slim} "
                     f"to {self.cfg['osc_ip']}:{self.cfg['osc_port']}\n{text}")
        except Exception as e:
            self.log(f"ERROR while sending: {e}")
        # the committed switch has to reach the preview as well, otherwise
        # the two drift apart in the other direction
        self.update_preview()

    def update_preview(self):
        paused = (time.time() < self.manual_pause_until
                  and bool(self.last_manual_text))
        if paused:
            text = self.last_manual_text
        else:
            text = self.build_payload()
        self.preview_label.setText(text if text else "[Status Text goes here]")
        # the card's own two-line preview follows the same values, so a
        # placeholder in a frame line is never stale next to the big one
        self.update_box_preview()
        # Everything that changes the output ends up here, so this is the
        # one place that can notice "the app shows something VRChat does
        # not" - which was the whole complaint. Comparing against the
        # payload we last put on the wire also stops a feedback loop:
        # send_now() calls update_preview() again, and by then the two
        # match, so nothing is requested a second time.
        if not paused and text and not self._matches_last_sent(text):
            self.request_send()
        n = len(text) + (len(SLIM_SUFFIX) if self.cfg["slim_chatbox"] else 0)
        if not text:
            self.char_count_lbl.setText("")
        elif n > CHATBOX_LIMIT:
            self.char_count_lbl.setText(f"⚠ {n}/{CHATBOX_LIMIT} – too long, will be cut!")
            self.char_count_lbl.setStyleSheet("color: #d9884a; font-size: 12px;")
        else:
            self.char_count_lbl.setText(f"{n}/{CHATBOX_LIMIT}")
            self.char_count_lbl.setStyleSheet("")

    def _matches_last_sent(self, text):
        """True when `text` is what VRChat is already showing. The stored
        payload carries the slim suffix and the length cut, so the
        comparison has to go through the same treatment."""
        if self._last_sent_payload is None:
            return False
        if self.cfg["slim_chatbox"]:
            payload = text[:CHATBOX_LIMIT - len(SLIM_SUFFIX)] + SLIM_SUFFIX
        else:
            payload = text[:CHATBOX_LIMIT]
        return payload == self._last_sent_payload

    def _fmt_media_time(self, seconds):
        """Media time formatting following the "Time with seconds"
        toggle: ON -> m:ss / h:mm:ss (3:27), OFF -> h:mm (0:03,
        the old behaviour). Used by the time line AND the {time}
        {time_status} {time_end} {position} {length} placeholders."""
        text = (fmt_time(seconds) if self.cfg.get("media_time_seconds", True)
                else fmt_time_hm(seconds))
        # small-letter digits, if the user picked them: one choke point
        # for the time line, the merged songbar line and the {time}
        # {position} {length} placeholders alike. digits_only keeps the
        # ':' and '/' at normal size, which is what makes it readable.
        return apply_style(text, self.cfg.get("media_time_style",
                                              STYLE_NORMAL),
                           digits_only=True)

    def log(self, msg):
        # safe to call from ANY thread: print is thread-safe and the
        # signal emit is queued into the GUI thread when needed
        print(msg)
        self._log_signal.emit(str(msg))

    def _log_gui(self, msg):
        # runs in the GUI thread only (signal/slot)
        if self.debug_console is not None:
            self.debug_console.log(msg)

    def closeEvent(self, ev):
        # ORDER MATTERS. The config used to be written last, AFTER
        # libre_server.stop_sync(), which waits for a process to die and
        # can take several seconds. Anything that went wrong in there -
        # or an impatient user killing the seemingly frozen window - cost
        # the settings of the whole session. So: persist first, tidy up
        # afterwards.
        self._save_timer.stop()
        try:
            self._write_config()
        except Exception as e:      # noqa: BLE001
            print(f"closeEvent: config could not be written: {e}")

        # Each step is isolated: one failing teardown must not skip the
        # ones after it, or we leak a server / leave text in the chatbox.
        for name, step in (
                ("clear_chatbox", self.clear_chatbox),
                ("plugins.shutdown", self.plugins.shutdown),
                ("stt.stop", self.stt.stop),
                # slowest one last - by now everything else is done and
                # the config is safely on disk
                ("libre_server.stop_sync", self.libre_server.stop_sync),
                ("oscq.stop", self.oscq.stop),
                ("debug_console.close", self.debug_console.close)):
            try:
                step()
            except Exception as e:  # noqa: BLE001
                print(f"closeEvent: {name} failed: {e}")
        super().closeEvent(ev)
