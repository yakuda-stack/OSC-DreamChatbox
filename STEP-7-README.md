# Schritt 7 – Speech to Text & Übersetzung unter Windows

Über Schritt 6 entpacken, danach löschen.

| Datei | |
|---|---|
| `core/backends/mic_sounddevice.py` | **NEU** – Mikrofon ohne PyAudio |
| `core/speechtotext.py` | zwei Mikrofon-Treiber, plattformrichtige Meldungen |
| `core/pyextras.py` | **Bugfix**: `sys.executable` im gefrorenen Build; `sounddevice` installierbar |
| `core/osinfo.py` | `subprocess_flags()` für beide Plattformen |
| `core/translators.py` | **Bugfix**: LibreTranslate-Prozessverwaltung unter Windows |
| `ui/pages/textbox_page.py` | Installer-Button deckt jetzt auch den Mikrofon-Treiber ab |
| `packaging/windows/*.spec`, `requirements-windows.txt` | neue Abhängigkeiten |

---

## Paket-Installation

```powershell
pip install SpeechRecognition sounddevice
```

**Nicht `pyaudio`.** Ich habe die Wheels auf PyPI geprüft:

| Paket | win_amd64-Wheels |
|---|---|
| `PyAudio` 0.2.14 | cp39 – **cp313** ❌ (du hast 3.14) |
| `sounddevice` 0.5.5 | **`py3-none-win_amd64`** ✅ – keine CPython-ABI, läuft auf jedem 3.x |
| `SpeechRecognition` 3.17 | reines Python ✅ |
| `cffi` 2.1.0 | bis **cp314** ✅ |

Auf Python 3.14 würde `pip install pyaudio` in einen Quellbau fallen, der Visual Studio und einen PortAudio-Checkout braucht. Das wollte ich dir nicht zumuten.

Das `sounddevice`-Windows-Wheel **enthält die PortAudio-DLL** (`libportaudio64bit.dll`, inkl. ASIO-Variante) – es muss also nichts systemweit installiert werden. Verifiziert durch direkten Blick ins Wheel.

Übersetzung braucht **nichts Zusätzliches**: `core/translators.py` ist reines `urllib`. Nur DeepL will optional `pip install deepl` (reines Python-Wheel).

---

## Warum sounddevice statt PyAudio – und warum das nichts umbaut

SpeechRecognition öffnet das Mikrofon über `sr.Microphone`, das PyAudio braucht. Aber `sr.Recognizer.listen()` fragt seine Quelle nur nach vier Dingen:

```
source.SAMPLE_RATE   source.SAMPLE_WIDTH
source.CHUNK         source.stream.read(chunk)
```

Genau das liefert `mic_sounddevice.py` als `sr.AudioSource`. Alles darüber – Energieschwelle, Silence-Detection, `adjust_for_ambient_noise()`, der Google-Recognizer, der WAV-Export – läuft **unverändert** weiter. Ausgetauschter Treiber, keine zweite Pipeline.

PyAudio gewinnt weiterhin, wenn es installiert ist. Bestehende Linux-Installationen bleiben also exakt auf ihrem gewohnten Pfad.

Getestet: gegen echtes SpeechRecognition mit gefälschtem PortAudio-Stream. `adjust_for_ambient_noise` → `listen()` → `AudioData` → `get_wav_data()` (RIFF-Header) laufen komplett durch; doppeltes Öffnen wird sauber abgelehnt.

---

## Drei echte Bugs, die ich dabei gefunden habe

### 1. `sys.executable` im gefrorenen Build

`core/pyextras.py` rief `[sys.executable, "-m", "pip", ...]` auf. In einem PyInstaller-Build ist `sys.executable` **die .exe selbst** – der „Install SpeechRecognition"-Knopf hätte also eine **zweite Kopie der Chatbox gestartet** statt zu installieren, und die Extra-Argumente wären ignoriert worden. Für den Nutzer sähe das wie ein Hänger aus, nicht wie ein Fehler.

Jetzt sucht `python_executable()` im gefrorenen Zustand einen echten Interpreter auf dem System und gibt sonst eine verständliche Meldung. `core/translators.py` hatte dieselbe Falle beim Start von LibreTranslate.

### 2. LibreTranslate-Prozesse unter Windows

`start_new_session=True` ist POSIX-only und wird unter Windows stillschweigend ignoriert; `os.killpg`/`SIGKILL` existieren dort nicht. Beim Stoppen wäre nur der Launcher gestorben – die Worker hätten den Port weiter belegt und der nächste Start wäre an „address in use" gescheitert. Jetzt: `CREATE_NEW_PROCESS_GROUP` beim Start, `taskkill /F /T` beim Stoppen.

### 3. `find_spec("sounddevice")` lügt

Das generische `py3-none-any`-Wheel installiert die Python-Dateien **ohne** PortAudio. `find_spec` meldet dann „vorhanden", `import sounddevice` wirft aber `OSError: PortAudio library not found`. Die App hätte „Treiber da" angezeigt und wäre beim ersten Mikrofonzugriff gescheitert. Jetzt wird tatsächlich importiert (lazy und gecacht, damit es auf PyAudio-Systemen nie passiert).

Nebenbei: `_silence_stderr()` unterdrückt ALSA-Spam, den es auf Windows nicht gibt – und in einer fensterlosen .exe ist Dateideskriptor 2 womöglich kein echtes Handle. Dort jetzt No-Op, sonst würden echte Fehler verschluckt.

---

## UI

Der Installer-Knopf deckt jetzt beide Lücken ab: fehlt SpeechRecognition → „Install SpeechRecognition"; fehlt nur der Mikrofon-Treiber → „Install microphone driver (sounddevice)". Nach dem Einbau wird die Treiber-Erkennung neu geprüft (`reload_mic_driver()`), damit kein Neustart nötig ist – analog zum bestehenden `reload_sr()`.

Die Geräteliste hängt die Host-API an (`Mikrofon (Realtek) [WASAPI]`). PortAudio meldet dasselbe Mikrofon einmal pro API, und MME kürzt Namen auf 31 Zeichen – ohne Suffix stünden dort vier identische, halb abgeschnittene Einträge.

Die Fehlermeldung beim Mikrofonöffnen nennt unter Windows den häufigsten Grund: **Einstellungen › Datenschutz › Mikrofon › „Desktop-Apps Zugriff erlauben"**. Ist das aus, öffnet das Gerät und bleibt still.

---

## Erster Test

```powershell
python -m core.backends.mic_sounddevice
```

Listet die Eingabegeräte und nimmt 3 Sekunden auf. **Die Peak-Amplitude muss deutlich über 200 liegen**, wenn du dabei sprichst. Bleibt sie darunter, ist es fast immer die Datenschutz-Einstellung oben.

## Nach dem .exe-Build prüfen

```powershell
dir dist\OSC-DreamChatbox\_internal\_sounddevice_data\portaudio-binaries\
```

Dort muss `libportaudio64bit.dll` liegen. PyInstaller hat einen eigenen `hook-sounddevice.py`, der das erledigt; ich habe zusätzlich `_sounddevice_data` explizit in die Spec aufgenommen, weil `sounddevice` selbst ein einzelnes Modul und kein Paket ist – `collect_all()` findet darin keine Daten und warnt sogar darüber.

Linux unverändert: PyAudio bleibt erste Wahl, alle Meldungen und Pfade dort identisch.
