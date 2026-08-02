# Schritt 8 – Plugins-Layout, API-Key-Links, Windows-Härtung

Über Schritt 7 entpacken, danach löschen.

| Datei | |
|---|---|
| `ui/pages/plugins_page.py` | „Installed" / „Store" links unter die Überschrift |
| `ui/pages/textbox_page.py` | klickbare Links unter den API-Key-Feldern |
| `core/plugins.py` | Windows-feste Datei-Operationen |
| `core/plugin_store.py` | Aufräumfehler dürfen keine fertige Installation kippen |

---

## 1. Plugins-Tab

Neue Reihenfolge:

```
Plugins                                  [⬆ Plugin list update]
[📦 Installed] [🛍 Store]
────────────────────────────────────────────────────────────
Installed plugins                                        (n)
[➕ Install from .zip] [📂 Open folder] [🧩 Template] [🔄 Rescan]
```

Der entscheidende Teil ist nicht nur die neue Zeile, sondern **wo der Stretch sitzt**: Er steht jetzt *hinter* den Buttons statt davor. Dadurch bleiben sie nach links gepackt und wandern bei keiner Fensterbreite nach rechts aus dem Bild. Style und Verhalten sind unverändert.

Der „Plugin list update"-Button bleibt oben rechts in der Titelzeile — er erscheint ohnehin nur, wenn GitHub eine neuere `plugins.json` hat, und ist kein Navigationselement.

## 2. API-Key-Links

Unter beiden Eingabefeldern, plattformunabhängig:

* **Google API key** → `console.cloud.google.com/apis/credentials`
* **DeepL API key** → `deepl.com/your-account/keys`

Umgesetzt als Rich-Text-`QLabel` mit `setOpenExternalLinks(True)`. Qt reicht die URL an den Standardbrowser weiter — derselbe Weg, den `QDesktopServices` nimmt, also ohne Plattform-Verzweigung. Tooltip nennt den vollen Link plus einen kurzen Hinweis (bei DeepL z. B., dass der Free-Key auf `:fx` endet).

Das DeepL-Feld saß in einem reinen `QHBoxLayout`; ich habe es in ein `QVBoxLayout` gehüllt, damit die Linkzeile darunter passt.

## 3. Windows-Härtung

### Was ich geändert habe

Windows scheitert beim Löschen und Verschieben von Ordnern auf zwei Arten, die es unter Linux nicht gibt — und beide treffen exakt die Stelle direkt nach dem Entpacken eines Plugin-ZIPs:

* **WinError 5 (Zugriff verweigert)** – aus einem Archiv entpackte Dateien können das Read-only-Attribut tragen, `shutil.rmtree` verweigert dann den Dienst
* **WinError 32 (Datei in Benutzung)** – Windows Defender oder der Suchindex hält kurz nach dem Schreiben noch ein Handle

Das erste braucht das gelöschte Attribut, das zweite nur einen Moment. `_rmtree()` und `_move()` in `core/plugins.py` machen jetzt beides: Read-only entfernen, dann bis zu sechsmal über etwa eine Sekunde erneut versuchen. Auf Linux ist das ein No-Op im ersten Durchlauf.

Zwei kleinere Dinge:

* Der Entpack-Ordner heißt jetzt `_install_…`. `discover()` überspringt Ordner mit `.` oder `_` am Anfang — ein Rest von einer abgebrochenen Installation wird also nicht mehr als kaputtes Plugin gemeldet.
* `TemporaryDirectory(ignore_cleanup_errors=True)` in Installation und Store: Wenn ein Scanner die heruntergeladene Datei noch offen hält, darf das keine **bereits fertige** Installation nachträglich in eine Exception verwandeln.

### Was schon in Ordnung war

`pathlib.Path` wird durchgängig verwendet, der Ordner wird in `discover()` per `mkdir(parents=True, exist_ok=True)` angelegt, die Zip-Slip-Prüfung normalisiert bereits `\` zu `/`, und Plugin-IDs sind per Regex auf Kleinbuchstaben beschränkt — auf einem case-insensitiven Dateisystem also kollisionsfrei.

### Getestet (mit erzwungenem Windows-Zweig)

Kompletter Lebenszyklus mit dem echten `world_stats`-Plugin:

1. `discover()` legt `%APPDATA%\OSC-DreamChatbox\plugins` an ✅
2. Installation aus `.zip`, laden, Platzhalter liefern Werte ✅
3. Doppelinstallation wird mit `PluginExistsError` abgelehnt ✅
4. Update mit `overwrite` **bei read-only gesetzter config.json** — Nutzereinstellungen (`players`, `player_icon`, `world_max`) überleben ✅
5. Rescan ✅
6. Leftover-`_install_`-Ordner wird nicht als Plugin gezählt ✅
7. Deinstallation mit read-only Datei im Ordner ✅
8. **Store-Pfad komplett**: Katalog von GitHub, Tarball laden, entpacken, neu verpacken, installieren, deinstallieren ✅

Der eingefrorene Build startet mit beiden UI-Änderungen ohne Traceback.

### Ein Punkt, den ich geprüft und verworfen habe

Die Log-Meldung des `world_stats`-Plugins klang linuxspezifisch („is VRChat installed via Steam/Proton?"). Beim Nachsehen in dessen `vrchatlog.py`: Es behandelt Windows korrekt über `AppData\LocalLow\VRChat` und wählt den Text plattformabhängig. In meinem Test hat es zu Recht Linux erkannt, weil nur die App-Weiche umgestellt war, nicht das Plugin. **Kein Handlungsbedarf.**

### Offen

Windows-Pfade über 260 Zeichen. `%APPDATA%\OSC-DreamChatbox\plugins\<id>\…` lässt viel Luft, aber ein Plugin mit tiefer Ordnerstruktur könnte anstoßen. Ein `\\?\`-Präfix wäre der Fix — das greift aber tief in die Pfadbehandlung ein und lohnt erst, wenn es jemanden trifft.

Linux unverändert: `_move()` und `_rmtree()` gegen read-only Dateien gegengeprüft, alle Backends und Pfade identisch.
