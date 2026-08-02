# Schritt 6 – Media Player für Windows (GSMTC)

Über Schritt 5 entpacken, danach löschen.

| Datei | |
|---|---|
| `core/backends/media_windows.py` | **NEU** – GSMTC-Backend |
| `core/mediafetch.py` | Weiche zeigt auf Windows jetzt auf GSMTC statt Null |
| `ui/pages/apps_page.py` | Kartentext plattformabhängig, Status nennt den Grund |
| `packaging/windows/osc-dreamchatbox.spec` | `winrt`/`winsdk` werden mitgepackt |
| `requirements-windows.txt` | neue Abhängigkeit |

---

## Paket-Installation – bitte genau lesen

```powershell
pip install "winrt-Windows.Media.Control[all]"
```

**Nicht `winsdk`.** Du läufst auf Python 3.14.6, und `winsdk` hat nur Wheels bis cp312 – der Befehl würde fehlschlagen oder einen Quellbau versuchen. Ich habe das auf PyPI geprüft:

| Paket | letzte Version | win_amd64-Wheels |
|---|---|---|
| `winsdk` | 1.0.0b10 | cp39 – **cp312** |
| `winrt-runtime` | 3.2.1 | cp39 – **cp314** ✅ |
| `winrt-Windows.Media.Control` | 3.2.1 | cp39 – **cp314** ✅ |

Das Backend akzeptiert beide Bindings – falls du irgendwann auf 3.12 zurückgehst, funktioniert `winsdk` weiterhin.

Das `[all]` ist nötig: es zieht `winrt-Windows.Foundation`, `.Media` und `.Storage.Streams` mit, ohne die die Timeline-Properties nicht auflösbar sind.

Danach in `venv\Scripts\python.exe -m pip` wiederholen, falls du das Build-venv separat hältst.

---

## Was funktioniert

| Feature | Quelle |
|---|---|
| Titel & Interpret | `try_get_media_properties_async()` |
| Position & Länge | `get_timeline_properties()` |
| Play/Pause | `get_playback_info().playback_status` |
| Player-Name | `source_app_user_model_id`, in lesbare Namen übersetzt |
| Lyrics | **läuft bereits** – `core/lyrics.py` ist reines HTTP (LRCLIB) plus lokale `.lrc`-Dateien, ohne Plattformbezug. Sobald Titel und Interpret ankommen, greift der Lyrics-Bereich unverändert. |

Erfasst wird alles, was sich bei Windows registriert: Spotify, Apple Music, VLC, foobar2000, MusicBee, AIMP – und jeder Browser-Tab mit Audio oder Video.

---

## Zwei Designentscheidungen

### Ein eigener Thread statt Event-Loop pro Aufruf

WinRT-Objekte sind an ihr COM-Apartment gebunden, und die API ist asynchron. Statt in jedem `run_async`-Worker eine neue Event-Loop hochzuziehen, besitzt das Backend **einen** Daemon-Thread, der das Apartment hält, eine Loop betreibt und einmal pro Sekunde einen Snapshot schreibt. `fetch()` kopiert nur diesen Snapshot – blockiert also nie und fasst nie ein WinRT-Objekt aus einem fremden Thread an.

### Position ist ein Schnappschuss, keine Uhr

Das ist die Stelle, an der Windows-Media-Integrationen typischerweise scheitern. **GSMTC aktualisiert `position` nicht laufend.** Spotify schreibt den Wert bei Play, Pause, Seek und Songwechsel – dazwischen nie. Naiv ausgelesen steht der Songbalken minutenlang still und springt dann.

Deshalb trägt die Timeline `last_updated_time`, und die Live-Position ist:

```
position + (jetzt - last_updated_time)     solange abgespielt wird
```

Abgesichert gegen alle Fälle, die dabei schiefgehen:

* pausiert → keine Extrapolation
* über Songende hinaus → auf die Länge geklemmt
* Player setzt `last_updated_time` nie (bleibt auf Epoche 1601) → würde Jahrhunderte ergeben, wird verworfen
* naive statt tz-bewusste `datetime` → wird als UTC behandelt
* gar kein Zeitstempel → Fallback auf den eigenen Lesezeitpunkt
* Browser-Tab ohne Länge → `length = 0`, die UI zeigt dann nur die Position ohne Balken (der Pfad existiert auf Linux bereits)

---

## Fehlerbehandlung

* Bindings fehlen → App startet normal, Karte zeigt „No media player detected." **plus den pip-Befehl**. Vorher wäre das von „nichts läuft gerade" nicht unterscheidbar gewesen.
* GSMTC wirft → Fehler wird **einmal** geloggt, nicht einmal pro Sekunde; Poll-Intervall verdoppelt sich bis 15 s und erholt sich automatisch
* Session ohne Metadaten → wird übersprungen, wie beim MPRIS-Backend
* Jeder einzelne Property-Zugriff ist gekapselt: ein Player, der `source_app_user_model_id` verweigert, kostet nur den Namen, nicht die ganze Anzeige

## Selbsttest

```powershell
python -m core.backends.media_windows
```

Zeigt zehn Messungen im Abstand von 1,5 s. **Die Position muss zwischen den Zeilen steigen** – das ist die Extrapolation. Steht sie still, liefert dieser Player keinen brauchbaren Zeitstempel.

## Getestet / ungetestet

Getestet: AUMID-Übersetzung, TimeSpan-Konvertierung für beide Bindings, alle sieben Extrapolations-Fälle oben, Enum-Auswertung, der Pfad ohne installierte Bindings, eingefrorener Build.

Ungetestet: die WinRT-Aufrufe selbst – dafür braucht es Windows.

Nebenbei behoben: Die Spec meldete „bundling optional package" auch für nicht installierte Pakete, weil `collect_all()` für fehlende Pakete leere Listen statt eines Fehlers liefert. Jetzt wird vorher `find_spec()` gefragt.

Linux unverändert: `source_label()` liefert dort weiterhin exakt „MPRIS".
