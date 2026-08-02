# Schritt 5 – Download-Buttons + Doppelklick-Schutz (Drop-in)

Über Schritt 4 entpacken, danach löschen.

| Datei | |
|---|---|
| `ui/pages/apps_page.py` | LHM-Empfehlung + Download-Button, RTSS als klickbarer Link + Button, Button-Sperre während des Starts |
| `core/backends/wintemp.py` | `RTSS_DOWNLOAD_URL`, Grace-Period gegen Doppelstart, ehrlichere Meldung |

## Sprache

Deine Vorlage war deutsch, die restliche UI ist durchgehend englisch ("Enable advanced temperature monitoring", "FPS (needs RTSS…)"). Ich habe den Text deshalb **englisch** umgesetzt, damit die Karte nicht mitten im Absatz die Sprache wechselt:

> Recommended extra software: LibreHardwareMonitor (LHM). Lightweight, open source and uses practically no system resources, so your performance stays untouched. Inside LHM, enable Options › Remote Web Server once.

Willst du es doch deutsch, ist das eine Zeile in `_build_wintemp_row()` – sag einfach Bescheid.

## Was neu ist

**CPU-Temperatur-Bereich** (nur Windows), von oben nach unten:
1. Button „Enable advanced temperature monitoring…"
2. Statuszeile (⏳ während des Starts, ✔ wenn aktiv)
3. Empfehlungstext zu LHM
4. Button „Download LibreHardwareMonitor" → GitHub Releases

**FPS-Bereich** (nur Windows):
* Das Wort **RTSS** im Hinweis ist jetzt ein echter Link (Rich-Text-Label, `setOpenExternalLinks`)
* Darunter zusätzlich ein Button „Download RTSS / MSI Afterburner" → Guru3D

Zwei Wege zum selben Ziel, weil niemand erwartet, dass ein grauer Hinweistext klickbar ist.

RTSS liegt nicht auf GitHub – Guru3D ist die Seite, auf der der Autor es veröffentlicht.

## Zwei Fehler aus deinem Log behoben

**1. Doppelter UAC-Prompt.** Im Log steht „Temperature helper started" zweimal – zwei elevierte Prozesse. Ursache: Nach dem Klick passierte sichtbar nichts, weil der Helper einige Sekunden bis zum ersten Messwert braucht, der Button aber sofort wieder klickbar war.

Jetzt gibt es einen dritten Zustand `starting`: 20 Sekunden Grace-Period, in der Button und `enable()` beide blockieren. Der Button zeigt „Starting…", die Statuszeile „waiting for the first reading…". Nur ein *abgelehnter* UAC-Prompt macht ihn sofort wieder frei, damit man es erneut versuchen kann.

**2. Falsche Aussage.** Die Meldung behauptete „on a desktop board you will most likely need LibreHardwareMonitor" – ausgerechnet auf deinem Laptop, wo ACPI gerade funktioniert hatte. Jetzt konditional formuliert: nur *falls* nach ein paar Sekunden nichts erscheint, wird LHM gebraucht.

Linux ist unverändert: Alle neuen Elemente hängen an `if IS_WINDOWS`.
