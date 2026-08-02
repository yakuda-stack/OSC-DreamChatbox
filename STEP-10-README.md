# Schritt 10 – Cross-Platform Bug-Check

Über Schritt 9 entpacken, danach löschen.

| Datei | Befund |
|---|---|
| `ui/mainwindow.py` | `run_async` konnte Busy-Flags dauerhaft blockieren; Exception im Callback konnte die App abbrechen; `closeEvent` schrieb die Config zu spät |
| `ui/pages/plugins_page.py` | Store nach einem Netzwerkfehler dauerhaft tot |
| `ui/pages/apps_page.py` | Hardware-/Media-Poller nach einem Fehler dauerhaft tot |
| `ui/pages/textbox_page.py` | LibreTranslate-Poller fror das Fenster minutenlang ein |
| `core/speechtotext.py` | bis zu 6 s GUI-Freeze beim Neustart + Race mit der alten Session |
| `core/translators.py` | Datei-Handle-Leck (sperrt unter Windows die Logdatei) |

---

## Teil 1 – Betriebssystem-Prüfung: alles sauber

**OS-spezifische Importe.** Per AST alle 11 Vorkommen geprüft (`winreg`, `sounddevice`, `speech_recognition`, `zeroconf`, `deepl`, `setproctitle`, `winrt`): **jeder** liegt in `try` und/oder in einer Funktion. Kein ungeschützter Import.

**Subprocess-Aufrufe.** Alle 12 geprüft. Die 6 ohne `creationflags` liegen ausschließlich in `hardware_linux.py` (aus dem Windows-Build ausgeschlossen) und `desktop_integration.py` (auf Windows nur über den ausgeblendeten Tray-Fix erreichbar, der zusätzlich abgesichert ist). Kein Handlungsbedarf.

**Sockets / OSC-Ports.** Kein Unterschied zwischen den Plattformen. `oscquery.py` bindet ausschließlich an `127.0.0.1` mit **Port 0** — das Betriebssystem vergibt die Ports, es wird nie ein fester Port belegt. Damit ist auch Windows' abweichende `SO_REUSEADDR`-Semantik irrelevant. Der reservierte UDP-Socket wird nie gelesen; er hält nur den Port, den wir per mDNS ankündigen. Korrekt auf beiden Systemen — dein Log aus Schritt 3 bestätigt es praktisch.

**Weitere Scans:** 0 nackte `except:`, 0 veränderliche Default-Argumente, 1 Handle-Leck (siehe unten).

---

## Teil 2 – Fünf echte Bugs

### 1. Ein Netzwerkfehler tötete den Plugin-Store dauerhaft ⚠ schwerwiegend

`run_async(work, on_done)` rief `on_done` **nur bei Erfolg** auf. Jeder Aufrufer, der vorher ein Busy-Flag setzt, hing damit fest:

```python
self._store_busy = True
def work(): return self.store.refresh(installed)   # StoreError wenn offline
self.run_async(work, self._on_store_refreshed)     # -> Flag bleibt True
```

**Reproduzierbar:** offline gehen, Store-Tab öffnen, wieder online gehen → der Store bleibt bis zum Neustart der App tot, Button dauerhaft ausgegraut. Dasselbe galt für `_hw_busy` und `_media_busy`: eine einzige fehlgeschlagene Abfrage und die Hardware- oder Media-Karte aktualisiert sich nie wieder.

`run_async` hat jetzt einen `on_error`-Parameter, und alle betroffenen Aufrufer geben ihn mit. Der Store bekommt zusätzlich `_store_release()`, das Flag und Buttons an einer Stelle zurücksetzt und den Grund anzeigt.

*(`on_store_install` und `check_plugin_updates` fangen Exceptions bereits in `work()` ab und waren nie betroffen.)*

### 2. Exception im Callback konnte die App abschießen

Ein Fehler in einem `on_done` landete ungefangen in einem Qt-Slot. PyQt6 reicht das an `sys.excepthook` weiter, dessen Standardverhalten den **Prozess beendet**. Ein Anzeigefehler hätte also die laufende Aufnahme mitgerissen. `on_done` und `on_error` laufen jetzt gekapselt.

### 3. LibreTranslate-Start fror das Fenster minutenlang ein

`_poll_libre_server` lief auf einem 750-ms-Timer, also im GUI-Thread, und rief `check_ready()` → HTTP-Request mit 1 s Timeout. Während des ersten Starts lädt LibreTranslate Sprachmodelle: Der Socket nimmt Verbindungen an, antwortet aber nicht → **1 s Freeze alle 750 ms, über die gesamte Downloaddauer**. Die Statusmeldung sagt selbst „can take a while".

Die Probe läuft jetzt über `run_async`; der Timer plant sie nur noch ein.

### 4. Speech to Text: 6 s Freeze plus Race

`SpeechWorker.start()` machte `self._thread.join(timeout=6)` — im GUI-Thread. Da `r.listen()` das Stop-Flag nur zwischen Phrasen prüft, fror ein Neustart (Sprachwechsel, schnelles Aus/An) das Fenster bis zu 6 Sekunden ein.

Dazu ein Race, den ich beim Nachbauen gefunden habe: Die alte Session sendet ihr `"stopped"` **nachdem** die neue lief — und die UI liest das als „Aufnahme beendet" und hakt den Button ab. Die neue Aufnahme starb also still.

Beides gelöst: Der Join passiert jetzt auf dem neuen Worker-Thread, jede Session hat ein eigenes Stop-Event und eine Nummer, und Nachrichten veralteter Sessions werden verworfen.

Verifiziert: zweiter `start()`-Aufruf blockiert **1 ms** statt bis zu 6000 ms; das verspätete `"stopped"` wird verworfen.

### 5. Datei-Handle-Leck (Windows-relevant)

`LibreTranslateServer.start()` öffnete `libretranslate.log` und schloss die eigene Kopie nie — ein Handle pro Start. Unter Windows hält ein offenes Handle die Datei **gesperrt**, sie ließe sich danach nicht mehr ersetzen oder löschen. `Popen` dupliziert den Deskriptor für das Kind, unsere Kopie kann also sofort weg. Gegengeprüft: Das Kind schreibt weiterhin ins Log.

### 6. Config-Verlust beim Beenden

`closeEvent` schrieb die Konfiguration **zuletzt** — nach `libre_server.stop_sync()`, das mehrere Sekunden auf einen sterbenden Prozess wartet. Wer das scheinbar eingefrorene Fenster abschießt, verlor die Einstellungen der ganzen Sitzung. Jetzt wird zuerst gespeichert, dann aufgeräumt, und jeder Teardown-Schritt ist einzeln gekapselt, damit ein Fehler die folgenden nicht überspringt.

---

## Getestet

Bugs 1, 2 und 4 habe ich vorher/nachher reproduziert, Bug 5 mit einem echten Kindprozess gegengeprüft. Beide Zweige importieren sauber, alle Dateien parsen, der eingefrorene Windows-Build startet ohne Traceback, Linux-Backends unverändert.

## Was ich mir angesehen und NICHT geändert habe

* **`run_async`-Timer** hängen als Kind an `self` und werden per `deleteLater()` entsorgt — kein Leck.
* **`log()`** ist thread-sicher (`print` + Queued Signal), wird korrekt aus Worker-Threads benutzt.
* **Themes** — reine `CONFIG_DIR`-Pfade, `as_posix()` im Stylesheet.
* **Plugin-Dateisystem** — in Schritt 8 gehärtet.
