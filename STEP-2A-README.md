# Schritt 2a – Plattform-Weiche + Null-Backends (Drop-in)

Dieses ZIP enthält **nur die geänderten und neuen Dateien**, in der
Ordnerstruktur des Projekts. Einfach über einen sauberen Checkout von
OSC-DreamChatbox v1.2.6 entpacken und überschreiben lassen.

Diese Datei (`STEP-2A-README.md`) danach löschen – sie gehört nicht ins Repo.

---

## Neue Dateien

| Datei | Zweck |
|---|---|
| `core/osinfo.py` | **Die zentrale Weiche.** Einzige Stelle mit `platform.system()`. Liefert `IS_WINDOWS` / `IS_LINUX` / `OS_NAME`, `resource_root()` (Projektordner bzw. PyInstaller-Bundle) und `config_dir()` (`~/.config` bzw. `%APPDATA%`) inkl. einmaliger Migration. |
| `core/backends/__init__.py` | Paket-Doku: eine Implementierung pro Plattform. |
| `core/backends/hardware_linux.py` | Der bisherige Inhalt von `core/hardware.py`, **Code unverändert** – nur der Docstring-Header ist neu. |
| `core/backends/hardware_null.py` | Null-Backend: gleiche API, jeder Wert `None`. |
| `core/backends/media_linux.py` | Der bisherige Inhalt von `core/mediafetch.py`, **Code unverändert**. |
| `core/backends/media_null.py` | Null-Backend: `fetch()` liefert immer `None`. |
| `requirements-windows.txt` | Abhängigkeiten für den Windows-Build. `requirements.txt` bleibt unangetastet. |
| `packaging/windows/osc-dreamchatbox.spec` | PyInstaller-Rezept (One-Folder/One-File, Konsole an/aus über Env-Vars). |
| `packaging/windows/build-exe.ps1` | Build-Skript: venv, Deps, Icon-Konvertierung, PyInstaller. |
| `packaging/windows/build-exe.bat` | Doppelklick-Wrapper um das PS1-Skript. |

## Geänderte Dateien

| Datei | Änderung |
|---|---|
| `osc_dreamchatbox.py` | Config-Migration vor dem ersten Zugriff; `prctl`/`.desktop` nur noch auf Linux; `SetCurrentProcessExplicitAppUserModelID` für das Windows-Taskbar-Icon; Icon-Pfad über `osinfo.resource()`; Plattform-Zeile im Debug-Log. |
| `core/constants.py` | Pfade kommen aus `core/osinfo.py`. Auf Linux **identische Werte** wie vorher. |
| `core/hardware.py` | Nur noch Weiche: exportiert `HardwareMonitor` passend zur Plattform, plus `get_hardware_monitor()`, `HARDWARE_AVAILABLE`, `backend_note()`. |
| `core/mediafetch.py` | Dito für `MediaFetcher`. |
| `core/plugins.py` | **3 Zeilen:** `import platform` raus, `from core.osinfo import ...` rein, lokale Flag-Definition durch Kommentar ersetzt. Die Namen `IS_WINDOWS` / `IS_LINUX` / `OS_NAME` bleiben von hier importierbar – bestehende Plugins und `plugin.json` funktionieren unverändert. |
| `scripts/build_appimage.sh` | Eine Zeile: `config/` wird jetzt mit ins AppImage kopiert (`STORE_SOURCES_FILE` zeigt dorthin, fehlte bisher). Mit `if` gegen `set -e` abgesichert. |
| `.gitignore` | Ausnahme `!packaging/windows/*.spec`, sonst hätte `*.spec` die neue Datei verschluckt. Dazu `assets/icon.ico` (Build-Artefakt). |

---

## Was NICHT drin ist

* Keine UI-Dateien (Schritt 2b). `ui/` ist komplett unangetastet.
* Keine echten Windows-Hardware-/Media-Features.
* Kein CHANGELOG-Eintrag – die Version ist noch nicht gebumpt.
* `packaging/aur/PKGBUILD` ist bewusst unverändert (siehe unten).

---

## Schnelltest nach dem Entpacken

Auf **Linux** muss sich nichts ändern:

```bash
python3 -c "
from core import constants, hardware, mediafetch, plugins, osinfo
print(osinfo.OS_NAME, constants.CONFIG_DIR)
print(hardware.BACKEND_NAME, mediafetch.BACKEND_NAME)
assert str(constants.CONFIG_DIR).endswith('/.config/OSC-DreamChatbox')
assert hardware.BACKEND_NAME == 'linux'
assert mediafetch.BACKEND_NAME == 'mpris'
print('Linux unveraendert – ok')
"
```

Dann normal starten (`./start.sh`) und prüfen, dass Media-Player-Karte,
Hardware-Karte und Plugins weiterhin laufen.

---

## Offener Punkt: PKGBUILD

`packaging/aur/PKGBUILD` kopiert `config/` ebenfalls nicht mit, hat also
dieselbe Lücke wie das AppImage-Skript. Ich habe es **nicht** angefasst,
weil das einen neuen `pkgrel` und ein AUR-Republish bedeutet. Der Fix
wäre eine Zeile im `package()`-Block, direkt nach `cp -r core ui`:

```bash
    cp -r config "${app}/"
```
