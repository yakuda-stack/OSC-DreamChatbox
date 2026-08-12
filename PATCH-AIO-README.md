# AIO mehrzeilig + Custom Time · Hardware Watt-Haken

Drop-in für **v1.3.3**. Über den Projektordner entpacken, überschreiben
lassen, fertig.

## Dateien

| Datei | Status |
| --- | --- |
| `ui/aio_edit.py` | **neu** – mehrzeiliges Editor-Widget |
| `ui/pages/apps_page.py` | geändert – AIO-Zeilen, Custom Time, Watt-Haken |
| `ui/pages/placeholder_picker.py` | geändert – Hinweis bei den Watt-Platzhaltern |
| `ui/mainwindow.py` | geändert – Config→UI, Timer-Intervall |
| `ui/config_mixin.py` | geändert – neue Keys + Migration |
| `ui/ui_main.py` | geändert – Stylesheet für `#aioedit` |
| `CHANGELOG.md`, `README.md` | Doku |

---

# 1 · Hardware: Watt-Haken für CPU und GPU

Die Leistungsaufnahme war als `{gpu_power}` / `{cpu_power}` lesbar, hatte
aber keinen Weg in die normalen Hardware-Zeilen. Beide Abschnitte haben
jetzt einen Haken **power draw in watts**:

```
GPU: 68% 61°C 213W | VRAM 9/16GB
Ryzen 7 9700X: 27% 54°C 68W
```

**Beide standardmäßig aus.** Die Chatbox hat 144 Zeichen, und das für
alle anzuschalten würde eine bestehende Hardware-Zeile länger machen,
ohne dass jemand danach gefragt hat.

## Eine Sache beim Update beachten

Die Haken sind **auch der Schalter für die Platzhalter**, genau wie
*GPU temp* / *CPU temp* es für `{gpu_temp}` / `{cpu_temp}` sind. Ein
String mit `{gpu_power}` braucht also ab jetzt den Haken – vorher hat
sich der Platzhalter von selbst aufgelöst.

Ich habe das bewusst so gemacht, weil `_hw_values()` als Regel führt
„die Platzhalter folgen den Checkboxen darüber", und eine einzige
Ausnahme davon ist ein Sonderfall, den man sich merken muss. Da v1.3.3
noch nicht draußen ist, kostet die Umstellung jetzt niemanden etwas.

Falls du das lieber andersherum willst – Haken nur für die
Standardzeilen, Platzhalter weiter ungated –, sind es zwei Zeilen in
`_hw_values()`:

```python
gpu_power = gpu.get("power")          # statt: if c["hw_gpu_power"] else None
cpu_power = info.get("cpu_power")
```

Wo nichts gemeldet wird, bleibt die Zeile einfach wie sie war. NVIDIA
meldet immer, AMD braucht amdgpus hwmon-Node, CPU-Watt brauchen zenpower
oder lesbare RAPL-Counter, unter Windows kommt beides aus
LibreHardwareMonitor. Dargestellt als `213W`, unter zehn Watt als `4.2W`
– ein Idle-Chip bei 4.2 W als flaches `4` sagt nichts.

Neue Keys:

```
hw_gpu_power  false
hw_cpu_power  false
```

---

# 2 · AIO: mehrzeilige Felder

Jedes Feld **AIO 1–5** ist standardmäßig 3 Zeilen hoch und zeigt den
String so, wie er rauskommt – eine sichtbare Zeile pro Chatbox-Zeile.

* **Shift+Enter** (oder Ctrl+Enter) macht einen Umbruch und schreibt das
  `\n` im Hintergrund.
* **Blankes Enter macht nichts** – in einem Formular mit neun weiteren
  Feldern ist Enter öfter Reflex als Absicht, und ein versehentlicher
  Umbruch fällt erst in VRChat auf.
* Das Feld **wächst mit dem Text** (bis 14 Zeilen, danach Scrollbar).
  **Unterkante ziehen** fixiert eine eigene Höhe – die zwei kleinen
  Striche unten in der Mitte sind der Griff –, **Doppelklick** darauf
  gibt es ans Auto-Wachsen zurück.

Das **Speicherformat bleibt unverändert**: in der Config steht weiterhin
`{text} \n {artist}`. Bestehende Strings öffnen unverändert, ein von Hand
getipptes `\n` funktioniert weiter, Plugins sehen dasselbe wie vorher,
und eine Config aus dieser Version öffnet auch in einer älteren.

Das 300-Zeichen-Limit zählt jetzt auf dem **gespeicherten** String, ein
Umbruch kostet also die 2 Zeichen, die er wirklich kostet. Läuft ein Feld
über, wird der letzte gültige Stand zurückgesetzt statt abgeschnitten –
ein mitten im Platzhalter gekapptes `{gpu_pow` rendert zu nichts und
sieht aus wie ein kaputtes Feld.

---

# 3 · AIO: Custom Time pro String

Unter jedem Feld ein Haken **Custom time** plus Sekundenfeld. Ist er
gesetzt, bleibt genau dieser String seine eigene Zeit stehen und
ignoriert *Rotate strings every N sec*. Der nächste String ist wieder auf
dem gemeinsamen Wert, außer er hat selbst einen Haken.

AIO 1 auf den geteilten 25 s, AIO 2 mit 60 s, AIO 3 wieder 25 s – genau
so. Das Intervall wird **pro Schritt** neu gesetzt, nicht einmal beim
Start; nur deshalb können drei verschiedene Standzeiten in einer
Rotation leben.

Neue Keys, alle per Default aus:

```
aio_custom_time  [false, false, false, false, false]
aio_custom_sec   [10, 10, 10, 10, 10]
aio_heights      [0, 0, 0, 0, 0]        # 0 = mit dem Text wachsen
```

`aio_custom_time` / `aio_custom_sec` wandern mit in die 10
Template-Sets, jedes Layout behält also sein eigenes Timing.
`aio_heights` bewusst nicht – die Höhen sind kosmetisch, und Felder, die
bei jedem Layout-Wechsel springen, wären das Gegenteil von hilfreich.

---

## Umbau im Detail

`AioTextEdit` (`ui/aio_edit.py`) bildet die **QLineEdit-API** nach –
`text()`, `setText()`, `insert()`, `cursorPosition()`,
`setCursorPosition()`, `selectionStart()`, `selectedText()`,
`maxLength()`. Deshalb musste am Placeholder-Picker und am Emoji-Popup
**nichts** geändert werden: beide steuern ihr Ziel über genau diese
Methoden.

Die Template-Seite hat bewusst **andere Namen**: `value()` / `setValue()`
sprechen die gespeicherte Form (mit `\n`), `text()` / `setText()` die
angezeigte (echte Umbrüche). Wer die verwechselt, korrumpiert ein
Template – deshalb kein gemeinsamer Name. `setValue()` feuert **kein**
`valueChanged`: das ist die Config, die die UI malt, nicht der User, der
tippt.

Neu in `apps_page.py`:

* `_aio_active_indices()` – die Slot-Nummern der Strings, die tatsächlich
  rotieren. Die Nummer wandert mit dem String mit, damit ein leeres
  **AIO 2** nicht die Standzeit von AIO 3 auf AIO 4 schiebt.
* `current_aio_index()` – welcher Slot gerade zu sehen ist.
* `aio_interval_ms()` – seine eigene Zeit, sonst die geteilte.
* `advance_aio()` startet den Timer mit dem neuen Intervall neu.

## Getestet

**Hardware / Watt**

* Haken aus: Zeile unverändert, `{gpu_power}` / `{cpu_power}` leer
* Haken an: `GPU: 68% 61°C 213W`, `Xeon: 27% 54°C 68W`, Platzhalter
  gefüllt
* Custom-Template-Pfad mit `{gpu_power}` / `{cpu_power}`
* Kein Sensor vorhanden → Zeile exakt wie ohne Haken, kein loses
  Trennzeichen
* Kleine Werte behalten die Nachkommastelle (`4.2W`)
* Speichern/Laden

**AIO**

* Roundtrip `stored ↔ angezeigt`, inkl. erhaltener Leerzeichen um `\n`
* Shift+Enter fügt ein, blankes Enter nicht
* Auto-Höhe: 3 Zeilen leer, wächst mit echten Umbrüchen **und** mit
  Wortumbruch, Deckel bei 14 Zeilen + Scrollbar
* Manuelle Höhe setzen / auf Auto zurück
* Picker-Fassade: Auswahl, Cursor, Einfügen, Zeichenlimit
* Rotation 25 / 60 / 25 s über echte `QTimer`-Intervalle
* Leeres AIO 2 verschiebt keine Zeiten
* Speichern/Laden: `\n` landet korrekt in der JSON
* Template-Set-Wechsel nimmt Zeiten und Haken mit
* `build_aio_lines()` splittet unverändert, `{box_start}`-Erkennung der
  Custom Box sieht das Template weiterhin
