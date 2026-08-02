# Schritt 9 – Plugin-Löschen + Options-Modul für Windows

Über Schritt 8 entpacken, danach löschen.

| Datei | |
|---|---|
| `ui/pages/plugins_page.py` | Mülleimer-Button in jeder Plugin-Zeile |
| `ui/pages/options_page.py` | Linux-Fixes unter Windows ausgeblendet, Pfadanzeige |
| `core/queryfix.py` | plattformabhängige Config-Pfade |

---

## 1. Mülleimer im Plugins-Tab

`🗑` ganz rechts in der Kopfzeile jeder Plugin-Karte, hinter dem Anchor-Dropdown. Hover wird rot.

**Interessanter Fund:** `on_plugin_delete()` existierte bereits vollständig — inklusive Bestätigungsdialog, Fehlerbehandlung, Timer-Refresh und Preview-Update — war aber **an keiner Stelle verdrahtet**. Toter Code. Es fehlte also wirklich nur der Button.

Zwei Entscheidungen dabei:

* Der Button ist auch bei **nicht unterstützten** Plugins aktiv. Alles andere in so einer Zeile ist ausgegraut, und ein Plugin, das hier nicht laufen kann, ist genau das, was man loswerden will.
* Der Bestätigungstext sagt jetzt ausdrücklich, dass **die Einstellungen mitgelöscht** werden. „Uninstall" klingt nach umkehrbar, ist es aber nicht — die `configs/` überleben nur ein *Update*, keine Deinstallation.

Gelöscht wird über `PluginManager.uninstall()`, also über die in Schritt 8 gehärtete Logik mit Read-only-Behandlung und Retry.

## 2. VRChat Picture Folder Fix + App Tray Fix

Unter Windows **komplett ausgeblendet**, nicht ausgegraut. Ein deaktivierter Button wirft die Frage auf „was verpasse ich hier?", und die ehrliche Antwort ist: nichts.

* **App Tray Fix** schreibt einen freedesktop-`.desktop`-Eintrag, damit Wayland/KDE das Fenster einem Icon zuordnen kann. Windows nimmt das Icon aus der `.exe`, und die Taskbar-Gruppierung erledigt bereits die `AppUserModelID`, die wir in Schritt 2a in `osc_dreamchatbox.py` gesetzt haben.
* **Picture Folder Fix** legt einen Symlink, damit VRChats Screenshots aus dem Proton-Prefix herausfinden. Unter Windows gibt es kein Prefix — VRChat schreibt direkt nach `%USERPROFILE%\Pictures\VRChat`.

Beide Handler sind zusätzlich abgesichert: Werden sie doch aufgerufen, erklären sie in einem Dialog warum es nichts zu tun gibt, statt einen Symlink-Fehler zu werfen. Die Button-Objekte werden weiterhin erzeugt (nur unsichtbar), damit kein anderer Code über ein fehlendes Attribut stolpert.

## 3. OSCQuery — funktioniert, mit Beleg

Kein Code geändert. `core/oscquery.py` bindet ausschließlich an `127.0.0.1` mit **Port 0**, lässt sich also vom Betriebssystem freie Ports geben — das ist auf Windows genauso korrekt wie auf Linux, und es umgeht auch die abweichende `SO_REUSEADDR`-Semantik von Windows, weil nie ein fester Port belegt wird.

**Dein eigenes Log aus Schritt 3 beweist es bereits:**

```
OSCQuery: registered 'OSC-DreamChatbox' (OSC udp/54618, HTTP tcp/54205) via mDNS
OSCQuery: VRChat found -> OSC input 127.0.0.1:9000 ('VRChat-Client-2A3642._oscjson._tcp.local.')
```

mDNS-Registrierung und VRChat-Erkennung liefen dort unter Windows 11 durch.

**Einziger praktischer Stolperstein:** Die Windows-Firewall fragt beim ersten Start nach, ob Python bzw. `OSC-DreamChatbox.exe` ins Netzwerk darf (mDNS auf UDP 5353). Wird das abgelehnt, findet OSCQuery VRChat nicht mehr und die App fällt auf Port 9000 zurück. Das ist kein Bug — aber es lohnt, es in der README zu erwähnen.

## 4. „Fix OSCQuery" — hier war echter Handlungsbedarf

Das Feature ist unter Windows **sinnvoll**, die Pfade waren es nicht: `~/.config/OSCLeash/Config.json` gibt es dort nicht.

`PROGRAMS` trägt jetzt pro Eintrag Kandidatenlisten je Plattform:

```python
"paths": {
    "linux":   ["~/.config/OSCLeash/Config.json"],
    "windows": ["%APPDATA%/OSCLeash/Config.json",
                "%LOCALAPPDATA%/OSCLeash/Config.json",
                "%USERPROFILE%/Documents/OSCLeash/Config.json",
                "%USERPROFILE%/OSCLeash/Config.json"],
}
```

Der erste **existierende** Pfad gewinnt. Die alte Einzelform `"path": ...` funktioniert weiter.

**Ehrlichkeitshinweis:** Diese Windows-Pfade sind die üblichen Orte, nicht auf jeder Installation verifiziert — es gibt dort kein XDG-Äquivalent. Das ist deshalb ungefährlich, weil die Grundregel des Moduls unverändert gilt: **es wird nur in Dateien geschrieben, die bereits existieren.** Ein falsch geratener Pfad kostet nichts, er wird übersprungen. Meldet ein Programm „config not found", obwohl es installiert ist, ist das eine Zeile in der Tabelle.

Zwei Bugs beim Testen gefunden und behoben:

1. **`os.path.expandvars` expandiert `%APPDATA%` nur unter Windows** (das macht `ntpath`, nicht `posixpath`). In meiner Simulation entstand dadurch ein Ordner, der wörtlich `%APPDATA%` hieß. Auf echtem Windows wäre es gutgegangen — aber damit wäre der Pfad auch nie testbar gewesen. Jetzt gibt es einen eigenen Expander für `%VAR%`, der auf beiden Plattformen greift.
2. **Nicht gesetzte Variablen** blieben als `%GIBTSNICHT%` im Pfad stehen. Solche Kandidaten werden jetzt verworfen, statt einen Ordner mit Prozentzeichen im Namen anzulegen.

Die Pfade stehen jetzt mit `/` statt `\` in der Tabelle — pathlib macht daraus unter Windows ohnehin Backslashes, und man kann sich an einem Escape nicht verzählen.

Kleine sichtbare Änderung **auch auf Linux**: Die Programmdetails zeigen jetzt den aufgelösten Pfad (`/home/du/.config/OSCLeash/Config.json`) statt `~/.config/...`, und bei mehreren Kandidaten den tatsächlich gefundenen. Das ist die nützlichere Angabe, wenn jemand nachsehen will.

## 5. Themes — keine Änderung nötig

Durchgesehen: Alles hängt an `CONFIG_DIR` (unter Windows also `%APPDATA%\OSC-DreamChatbox\backgrounds`), durchgängig `pathlib`, `shutil.copy2` zum Importieren, `Path(name).name` als Traversal-Schutz.

Die eine Stelle, die hätte brechen können, ist schon richtig: Das Hintergrundbild geht als **`image.as_posix()`** ins Stylesheet. Qt-QSS braucht in `url()` Forward-Slashes — mit `str(path)` wäre unter Windows `C:\Users\…` entstanden und der Hintergrund wäre stumm weiß geblieben.

---

## Getestet

Erzwungener Windows-Zweig: Kandidatenpfade expandieren korrekt, der zweite Kandidat wird gefunden wenn der erste fehlt, `fix_program` schreibt und erhält fremde Keys, doppelter Lauf meldet „already set", fehlende Configs melden sauber. Linux: Pfade byte-identisch zu vorher, alte `path`-Form funktioniert weiter, Backends unverändert. Eingefrorener Build startet ohne Traceback.
