# Drop-in v1.4.6

Über den Baum kopieren. `AppDir/` ist bewusst nicht dabei.

## Versionsbump

    core/constants.py               VERSION = "v1.4.6"
    osc_dreamchatbox.py             Docstring
    packaging/aur/PKGBUILD          pkgver=1.4.6
    .SRCINFO                        pkgver + beide Source-URLs
    packaging/windows/installer.iss AppVersion-Fallback + Kommentarbeispiel
    CHANGELOG.md                    neuer [v1.4.6]-Eintrag, 2026-08-28

Historische Erwähnungen von v1.4.5 in Kommentaren, README und Tests
("ein Config vor v1.4.5 hat den Key nicht") sind absichtlich stehen
geblieben - die beschreiben, wann etwas passiert ist, nicht was gerade
läuft.

`sha256sums` im PKGBUILD steht weiter auf SKIP, das macht `updpkgsums`
vor dem Upload wie immer.

## Inhalt

**Fix:** `find_lhm()` wird 300 s gecacht, `_lhm_running()` 15 s, beide
mit `force=True` für den Button. Vorher lief bei jedem, der den
Temperatur-Button nie gedrückt hat, alle zwei Sekunden eine Enumeration
von drei Uninstall-Registry-Hives blockierend über den GUI-Thread.
6 Tests, laufen auf jeder Plattform.

**Neu:** `core/perfprobe.py`, aus solange `DCB_PERF` nicht gesetzt ist.

    PowerShell:  $env:DCB_PERF=1; .\OSC-DreamChatbox.exe
    Linux:       DCB_PERF=1 ./start.sh

Report alle 30 s in die Debug-Console und nach
`%APPDATA%\OSC-DreamChatbox\perf-report.txt` bzw.
`~/.config/OSC-DreamChatbox/perf-report.txt`.

Zwei Aufrufe im Entry-Point, das ist Absicht:

    perfprobe.arm(MainWindow)   # VOR der Konstruktion
    win = MainWindow()
    perfprobe.install(win)      # danach

`MainWindow.__init__` macht `self.hw_timer.timeout.connect(self.poll_hw)`,
und eine Qt-Verbindung speichert die gebundene Methode, die sie bekommen
hat. Ein Instanz-Attribut danach zu überschreiben ändert alles außer den
Timern - also genau die einzigen Aufrufer, um die es geht.

## Getestet

    79 bestehende Tests   grün
    6 neue wintemp-Tests  grün
    Smoke-Test der Sonde  grün
    ruff                  nur BLE001/S110/S112, wie im Bestandscode
    VERSION               v1.4.6

## Nicht angefasst

Drei Windows-Funde, alle real, keiner der große Brocken - und
ungetesteter Windows-Code an Kernfeatures wollte ich nicht schicken:

- `core/hotkeywatch.py:249` - der `WH_KEYBOARD_LL`-Hook pumpt mit
  `PeekMessageW` + `time.sleep(0.02)` statt blockierendem `GetMessageW`.
  Ein Low-Level-Hook serialisiert systemweit jeden Tastendruck durch
  diesen Thread; 20 ms Pollschlaf heißt bis zu 20 ms Verzögerung, und
  Windows hat dafür einen `LowLevelHooksTimeout`.
- `core/backends/media_windows.py:256` - `_start()` läuft unbedingt im
  Konstruktor, der GSMTC-Poller arbeitet also auch bei ausgeschaltetem
  MediaPlay, und holt pro Sekunde einen neuen SessionManager statt einen
  wiederzuverwenden.
- `core/backends/hardware_windows.py:673` - `snapshot()` ruft `_temps()`
  und `_lhm.powers()` je zweimal pro Poll. Der 1-Sekunden-Cache fängt es
  ab, unnötig ist es trotzdem.
