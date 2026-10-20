# OSC-DreamChatbox – Architektur

Wo liegt was, und welche Dateien brauchst du, um etwas zu ändern.
Stand: v1.7.0

---

## 1. Grundidee in einem Satz

`osc_dreamchatbox.py` startet die App → `ui/mainwindow.py` (**MainWindow**) baut alle Seiten aus Mixins zusammen, sammelt per Timer alle aktiven Bausteine (Status, Media, Hardware, AIO, Plugins …) in **`build_payload()`** und schickt das Ergebnis in **`send_now()`** per OSC an VRChat (`/chatbox/input`).

- `core/` = Logik **ohne** UI (meist ohne Qt, testbar)
- `core/backends/` = eine Implementierung pro Betriebssystem
- `ui/` = PyQt6-Oberfläche
- `ui/pages/` = eine Datei pro Seite/Karte, als **Mixin** für MainWindow

---

## 2. Ordnerstruktur

```
OSC-DreamChatbox/
├── osc_dreamchatbox.py      Einstiegspunkt (Prozessname, --headless, MainWindow starten)
├── core/                    Logik
│   └── backends/            Linux / Windows / Null-Implementierungen
├── ui/                      Fenster, Widgets, Stylesheet
│   └── pages/               Seiten-Mixins (Apps, Advanced, Textbox, Plugins, Options …)
├── config/plugins.json      Katalog für den Plugin-Store (Liste von GitHub-Links)
├── docs/PLUGIN_API.md       Doku für Plugin-Entwickler
├── assets/                  Icon + Screenshots (p1–p11)
├── packaging/
│   ├── aur/PKGBUILD         AUR-Paket
│   ├── windows/             PyInstaller-Spec, Inno-Setup (installer.iss), Build-Skripte
│   └── osc-dreamchatbox.desktop
├── scripts/
│   ├── bump_version.py      Version überall gleichzeitig setzen
│   └── build_appimage.sh    AppImage bauen → build/
├── tests/                   pytest-Tests + smoke.py (startet App in allen Modi)
├── CHANGELOG.md             ausführlich (wird in der App angezeigt)
├── HIGHLIGHTS.md            kurz für Nutzer (wird in der App angezeigt)
└── README.md / README-DROPIN.md / THIRD_PARTY_NOTICES.md
```

---

## 3. Der Sende-Ablauf (das Herzstück)

Alles in `ui/mainwindow.py`:

```
QTimer (send_timer, aio_timer, media_timer, hw_timer, plugin_timer …)
   │
   ▼
request_send() / send_after_change()
   │
   ▼
send_now()                 ← EINZIGES Tor für automatische Nachrichten
   │  prüft: send_to_vrchat an? Warmup vorbei? STT nimmt nicht auf?
   │         manuelle Pause? Rate-Limit (_osc_send_delay)?
   ▼
build_payload(commit=True) ← baut den Text
   │  1. Plugins: invalidate() + lines_by_anchor()
   │  2. Chat-/Two-Way-Zeilen einsortieren
   │  3. AFK aktiv + afk_solo → nur AFK-Text
   │  4. AIO aktiv → Plugin-Zeilen + build_aio_lines()
   │  5. sonst: app_order durchgehen → Status / Media / Hardware
   │  6. _apply_custom_box() (Rahmen) → plugins.filter_text()
   ▼
Slim-Suffix / 144-Zeichen-Limit → osc_client.send_message("/chatbox/input", …)
   ▼
_render_preview()          ← Vorschau im Fenster
```

Getippte Nachrichten laufen **nicht** über `send_now()`, sondern über `send_manual_text()` in `ui/pages/textbox_page.py`.

Wichtige Konstanten (Limit, Rate-Limit, Pfade): `core/constants.py`
(`CHATBOX_LIMIT = 144`, `OSC_MIN_SEND_GAP_SEC`, `OSC_RATE_MAX_SENDS` …)

---

## 4. „Ich will X ändern“ → diese Dateien

| Bereich | UI (Karte/Seite) | Logik |
|---|---|---|
| **Start, CLI-Argumente** | – | `osc_dreamchatbox.py`, `core/instancelock.py`, `core/selflaunch.py` |
| **Was gesendet wird / Reihenfolge** | `ui/mainwindow.py` (`build_payload`, `send_now`) | `core/constants.py` |
| **Status-Texte** | `ui/pages/apps_page.py` (`on_status_*`, `advance_status`) | `core/textutils.py`, `core/textstyle.py` |
| **Media / Now Playing** | `ui/pages/apps_page.py` (`poll_media`, `build_media_lines`) | `core/mediafetch.py` → `core/backends/media_linux.py` / `media_windows.py` |
| **Songtexte (Lyrics)** | `ui/pages/apps_page.py` (`on_lyrics_*`) | `core/lyrics.py`, `core/lyrics_sources.py` |
| **Hardware (CPU/GPU/RAM)** | `ui/pages/apps_page.py` (`poll_hw`, `build_hw_lines`) | `core/hardware.py` → `core/backends/hardware_linux.py` / `hardware_windows.py`, `wintemp.py` |
| **FPS (MangoHud/RTSS)** | `ui/pages/apps_page.py` | `core/backends/hardware_*.py` |
| **All in one (AIO)** | `ui/pages/apps_page.py` (`on_aio_*`, `build_aio_lines`), `ui/aio_edit.py` | `core/aioscroll.py` (Scroll-Effekt) |
| **Advanced Mode / Node-Canvas** | `ui/pages/advanced_page.py`, `ui/nodegraph.py` (Zeichnen, Blöcke) | `core/nodegraph_eval.py` (Auswerten, Logik-Gatter) |
| **Canvas: Hotkeys, Programme** | `ui/pages/advanced_page.py` | `core/hotkeys.py`, `core/hotkeywatch.py`, `core/proclaunch.py`, `core/procwatch.py` |
| **Custom Box (Rahmen)** | `ui/pages/custom_box.py` | `core/boxstyle.py`, `core/boxanim.py` |
| **AFK** | `ui/pages/apps_page.py` (`on_afk_*`), `ui/mainwindow.py` (`afk_*`) | `core/afk.py` |
| **Platzhalter `{...}`** | `ui/pages/placeholder_picker.py` (+-Menü), `placeholder_complete.py` (Autovervollständigung) | `core/textutils.py` (`substitute_placeholders`) |
| **Emoji-Picker** | `ui/ui_main.py` (`EmojiPopup`) | `core/emojis.py` (Daten), `core/emojifont.py` |
| **Chat / manuelles Senden / Presets** | `ui/pages/textbox_page.py` (`send_manual*`, `on_preset_*`) | `core/inputhistory.py`, `ui/history_edit.py` (Pfeil hoch) |
| **Speech to Text** | `ui/pages/textbox_page.py` (`on_stt_*`, `on_mic_*`), `ui/miclevel.py` | `core/speechtotext.py`, `core/stt_child.py` + `core/mic_host.py` (Mikro im eigenen Prozess), `core/audiolevel.py` |
| **Mikrofon-Liste** | `ui/pages/textbox_page.py` | `core/micgroups.py`, `core/backends/mic_pactl.py`, `mic_sounddevice.py`, `mic_probe.py` |
| **Übersetzung** | `ui/pages/textbox_page.py` (`on_tr_*`, `on_libre_*`) | `core/translators.py` (alle Dienste + Fallback-Kette) |
| **KI-Übersetzung (Ollama, Claude, Gemini …)** | `ui/pages/textbox_page.py` (`on_ai_*`) | `core/ai_translator.py` |
| **Custom-Übersetzer (curl/Befehl)** | `ui/pages/textbox_page.py` (`on_custom_*`) | `core/custom_translator.py` |
| **Two-Way-Übersetzung** | `ui/pages/twoway_page.py` | `core/backends/app_capture.py` (nur bestimmte Programme aufnehmen) |
| **Plugins (Seite)** | `ui/pages/plugins_page.py` | `core/plugins.py` (Laden, API, Hooks) |
| **Plugin-Store** | `ui/pages/plugins_page.py` | `core/plugin_store.py`, `config/plugins.json` |
| **Profile** | `ui/pages/profiles_panel.py` (Seitenleiste) | `core/profiles.py` |
| **Options → General** (Updates, Changelog, Linux-Fixes) | `ui/pages/options_page.py`, `ui/docviewer.py` | `core/selfupdate.py`, `core/desktop_integration.py`, `core/vrc_pictures.py` |
| **Options → OSC** (OSCQuery, Ziel, Slim, Hotkeys, OSC-Input) | `ui/pages/options_page.py`, `ui/osc_param_log.py` | `core/oscquery.py`, `core/queryfix.py`, `core/oscin.py` |
| **Options → Design** (Themes, Farben, Hintergrund) | `ui/pages/options_page.py` | `core/theming.py`, Stylesheet in `ui/ui_main.py` (`STYLE`) |
| **Benachrichtigungston** | `ui/pages/options_page.py` (`on_notify_*`) | `core/notifysound.py` |
| **Terminal-Modus (--headless)** | – | `core/headless.py`, `core/qtstub.py` (Qt-Attrappen) |
| **Config laden/speichern/migrieren** | `ui/config_mixin.py` | `core/atomicfile.py`, `core/osinfo.py` (Pfade) |
| **Optionale Python-Pakete nachinstallieren** | – | `core/pyextras.py` |
| **Kleine Widgets** | `ui/ui_main.py` (ToggleSwitch, DebugConsole …), `ui/flowlayout.py`, `ui/nowheel.py` | – |

**Neue Einstellung hinzufügen** braucht meistens 3 Stellen:
1. Standardwert + Prüfung in `ui/config_mixin.py` (`load_config`)
2. Widget + Handler in der passenden `ui/pages/*.py`
3. Werte in UI übernehmen: `ui/mainwindow.py` → `_apply_config_to_ui()`

---

## 5. MainWindow und die Mixins

`ui/mainwindow.py`:

```python
class MainWindow(ConfigMixin, AppsPageMixin, AdvancedPageMixin,
                 CustomBoxMixin, TextboxPageMixin, TwoWayMixin, OptionsPageMixin,
                 PluginsPageMixin, PlaceholderPickerMixin, ProfilesMixin,
                 QMainWindow)
```

- Jedes Mixin ist eine eigene Datei, aber `self` ist immer das Hauptfenster → alle Mixins teilen `self.cfg`, `self.plugins`, `self.osc_client` usw.
- Seiten-Indizes: `PAGE_APPS=0`, `PAGE_ADVANCED=1`, `PAGE_TEXTBOX=2`, `PAGE_PLUGINS=3`, `PAGE_OPTIONS=4`
- `build_ui()` baut Seitenleiste + `QStackedWidget`
- `run_async()` = Standard-Muster für Arbeit im Hintergrund-Thread (Thread + Queue + QTimer)
- `log()` ist thread-sicher (läuft über ein Qt-Signal)

**Neue Seite** → neue Datei `ui/pages/xyz_page.py` mit `XyzMixin`, in die Klassenliste von MainWindow eintragen, in `build_ui()` einhängen, ggf. neuen `PAGE_*`-Index.

---

## 6. Plattform-Backends

`core/osinfo.py` ist die **einzige** Stelle, die fragt „Linux oder Windows?“ (`IS_LINUX`, `IS_WINDOWS`, Config-Pfade).

Fabrik-Prinzip: Modul in `core/` wählt das Backend, die UI importiert **nie** direkt aus `core/backends/`.

| Fabrik | Linux | Windows | Fallback |
|---|---|---|---|
| `core/hardware.py` | `hardware_linux.py` (/proc, /sys, nvidia-smi) | `hardware_windows.py` (Win32/PDH/LHM) + `wintemp.py` | `hardware_null.py` |
| `core/mediafetch.py` | `media_linux.py` (MPRIS/D-Bus) | `media_windows.py` (GSMTC) | `media_null.py` |
| Mikrofon | `mic_pactl.py` (PipeWire/Pulse) | `mic_sounddevice.py` | `mic_probe.py` (Timeout-Schutz) |

**Neue Plattform-Funktion** → Linux- **und** Null-Version mit gleichen Methoden anlegen, Windows wenn möglich.

---

## 7. Plugins

- Installiert in: `~/.config/OSC-DreamChatbox/plugins/<id>/` (`plugin.json` + Python-Datei)
- Alles dazu in `core/plugins.py`:
  - `Plugin` = ein Plugin (Manifest, Plattform-/API-Check)
  - `PluginAPI` = das `api`-Objekt für Plugins (`get`, `set`, `set_many`, `refresh`, `data_path` …)
  - `PluginManager` = Laden, Reihenfolge, Anker, Hooks (`dispatch`, `snapshot`, `lines_by_anchor`, `filter_text`), ZIP-Installation
- Hooks: `setup`, `teardown`, `get_text`, `get_lines`, `get_values`, `on_settings`, `on_text`, `on_tick`, `on_event`, `build_widget`
- Plugin-API-Version: `PLUGIN_API_VERSION` in `core/plugins.py` (aktuell v2)
- Doku für Entwickler: `docs/PLUGIN_API.md` (Test `tests/test_docs.py` prüft sie)
- Store-Katalog: `config/plugins.json` – neue Plugins einfach als GitHub-Link eintragen

---

## 8. Wo die Daten liegen (zur Laufzeit)

Pfade kommen aus `core/osinfo.py` / `core/constants.py`.
Linux: `~/.config/OSC-DreamChatbox/` · Windows: `%APPDATA%\OSC-DreamChatbox\`

| Datei/Ordner | Inhalt |
|---|---|
| `config.json` | alle Einstellungen (`CONFIG_FILE`) |
| `profiles/<Name>.json` | Profile (Kopie der Config + `plugin_<id>`-Schalter) |
| `profiles/plugins/<Name>.json` | Plugin-Settings pro Profil |
| `plugins/` | installierte Plugins |
| `plugins.json` / `plugins_sources.json` | Store-Cache / eigene Store-Quellen |
| `lyrics/` | Lyrics-Cache |
| `extras/` | nachinstallierte Python-Pakete (`core/pyextras.py`) |
| `instance.lock` | verhindert zwei laufende Instanzen |

---

## 9. Release & Build

1. Version setzen: `python3 scripts/bump_version.py 1.7.0` (welche Dateien: Liste `ZIELE` im Skript, Quelle der Wahrheit ist `VERSION` in `core/constants.py`)
2. `CHANGELOG.md` + `HIGHLIGHTS.md` selbst schreiben (Skript erinnert nur)
3. Prüfen: `python3 scripts/bump_version.py --check`
4. Bauen:
   - AppImage: `bash scripts/build_appimage.sh` → leert `build/`, legt AppImage dort ab
   - AUR: `packaging/aur/PKGBUILD` (+ `makepkg --printsrcinfo` im AUR-Repo `~/osc-dreamchatbox`)
   - Windows: `packaging/windows/` (siehe `README-BUILD.md`, `installer.iss`)
5. Ablauf drumherum: `update_dreambox.txt`

---

## 10. Tests

- `pytest` im Projektordner (Einstellungen in `pytest.ini`, Tests in `tests/`)
- `python3 tests/smoke.py` startet die echte App einmal in jedem Modus (Fenster offscreen, Terminal-Modus, Profile) mit Wegwerf-HOME
- Logik in `core/` ist absichtlich ohne Qt → dort lassen sich neue Tests am leichtesten schreiben
