# Schritt 4 – MangoHud-Bereinigung + Temperatur-Helper (Drop-in)

Über den Stand aus Schritt 3 entpacken. Danach diese Datei löschen.

| Datei | |
|---|---|
| `ui/pages/apps_page.py` | geändert – MangoHud-Zeile nur noch auf Linux, RTSS-Hinweis auf Windows, neuer Temperatur-Button, GPU-Backend-Label |
| `core/backends/wintemp.py` | **NEU** – Koordinator für den elevierten Helper |
| `packaging/windows/dreamtemp-helper.ps1` | **NEU** – der eleviert laufende Helper |
| `core/backends/hardware_windows.py` | geändert – liest Helper-Werte als zweite Temperaturquelle |
| `packaging/windows/osc-dreamchatbox.spec` | geändert – Helper-Skript wird mitgepackt |

---

## Punkt 1 – MangoHud

Auf **Windows** verschwinden Ordner-Zeile, „Choose…"-Button und die Steam-Launch-Options aus dem Tooltip vollständig. Stattdessen:

* Checkbox: `FPS (needs RTSS, see below)`
* Hinweis: „read via RTSS – nothing to configure"
* Tooltip erklärt RTSS und dass es MSI Afterburner beiliegt

Auf **Linux** ist alles unverändert – gleicher Text, gleicher Tooltip, gleicher Button.

Ein Detail: `self.mangohud_dir_lbl` wird auf **beiden** Plattformen erzeugt, aber auf Windows keinem Layout hinzugefügt. Grund: `ui/mainwindow.py` Zeile 114 schreibt beim Start in dieses Label. Würde es auf Windows fehlen, gäbe es dort einen `AttributeError` beim Start.

Außerdem behoben: `_on_hw_result` schrieb fest verdrahtet „AMD (sysfs)" für jede Nicht-NVIDIA-Karte. Auf Windows mit Radeon stand da also ein Linux-Begriff. Jetzt wird `gpu_backend_label` benutzt, falls das Backend eins liefert – auf Linux fällt es auf die alte Logik zurück.

---

## Punkt 2 – Temperatur-Helper

### Warum es kein reines „Admin-Skript" sein kann

CPU-Kerntemperaturen liegen in MSRs (Model-Specific Registers). Die sind **nur aus Ring 0** lesbar, also aus Kernel-Mode. Administrator-Rechte ändern daran nichts: Ein elevierter Prozess läuft weiterhin in Ring 3. Deshalb bringt *jedes* Windows-Tool, das CPU-Temperaturen zeigt (HWiNFO, Core Temp, Afterburner, LibreHardwareMonitor), einen signierten Kernel-Treiber mit.

Ein Skript, das „als Admin einfach die CPU-Temperatur ausliest", kann es also nicht geben.

### Was der Helper stattdessen macht

Er liest alle Quellen, die ein elevierter User-Mode-Prozess **ohne** Treiber erreichen kann:

1. `root/LibreHardwareMonitor` (WMI) – LHMs eigener Namespace. Das ist die echte Die-Temperatur, weil LHM den Treiber hat.
2. `root/OpenHardwareMonitor` – dasselbe für das ältere OHM.
3. `root/WMI MSAcpi_ThermalZoneTemperature` – ACPI-Thermalzonen aus der Firmware. Braucht Elevation, aber keinen Treiber. Auf Laptops und OEM-Boards häufig vorhanden, auf Enthusiasten-Desktopboards meist nicht.

Zusätzlich startet der Button LibreHardwareMonitor eleviert, falls installiert, und aktiviert vorher dessen Webserver in `LibreHardwareMonitor.config`.

**Auf deinem 9700X-Desktop wird Quelle 3 mit hoher Wahrscheinlichkeit nichts liefern.** Rechne damit, dass du LHM brauchst. Der Button sagt das dann auch und verlinkt es.

### Was ich bewusst NICHT gebaut habe

Ich habe **kein** WinRing0.sys mitgeliefert – den Treiber, den LHM und Co. benutzen. Gründe:

* Veröffentlichte Privilege-Escalation-CVEs (CVE-2020-14979 / CVE-2020-14980): beliebiger MSR- und Physical-Memory-Zugriff für **jeden** lokalen Nutzer. Wird aktiv von Malware und Cheats missbraucht.
* Microsofts Vulnerable-Driver-Blocklist blockt ältere Builds auf jedem System mit aktivem Memory Integrity – bei Windows 11 oft Standard.
* Antivirus schlägt darauf an. Deine `.exe` wäre danach für viele Nutzer nicht mehr startbar.

Eine VRChat-Chatbox hat keinen Grund, ihren Nutzern eine Ring-0-Angriffsfläche zu installieren. Falls du das trotzdem willst: Es bräuchte ein EV-Zertifikat plus Microsoft-Attestation-Signing, und die Verantwortung dafür läge bei dir.

### Architektur

```
UI-Button
  -> TempHelper.enable()
     -> dreamtemp-helper.ps1 nach CONFIG_DIR/helper/ kopieren
     -> ShellExecuteW(verb="runas")   -> UAC-Prompt
  -> elevierte PowerShell schreibt CONFIG_DIR/temps.json (1x pro Sekunde)
App (nicht eleviert)
  -> TempHelper.temps() liest nur diese Datei
```

Die Datei ist die komplette IPC. Kein Socket, keine Pipe, kein privilegierter Code in der App selbst.

**Sicherheitsmaßnahmen im Helper:**

* Beendet sich selbst, wenn die App weg ist (`-ParentPid`) – ein verwaister Admin-Prozess kann die Chatbox nicht überleben
* Beendet sich, wenn die App eine Stop-Datei ablegt
* Schreibt atomar (temp-Datei + Move), die App liest nie ein halbes JSON
* Fasst nichts außer der Ausgabedatei an: keine Registry, keine Dienste, keine Treiber, keine Installation
* Wird bei jedem App-Update frisch aus dem Bundle kopiert

**Robustheit in der App:** Messwerte älter als 8 s werden verworfen, kaputtes JSON wird ignoriert, unplausible Werte (≤0 °C oder ≥150 °C) fliegen raus. Alles einzeln getestet.

---

## Ungetestet – bitte zuerst prüfen

Ich kann hier **kein PowerShell und keine Windows-API ausführen**. Getestet sind: die IPC-Logik, Stale-/Müll-/Absurd-Werte, das BOM-Verhalten, der eingefrorene Build und dass der Helper im Bundle landet.

**Nicht** getestet: das PowerShell-Skript selbst und `ShellExecuteW`. Beim Durchsehen habe ich dabei zwei echte Bugs gefunden und behoben:

1. `Get-Date -UFormat %s` ist in PowerShell 5.1 zeitzonenbehaftet. Die App hätte jede Messung für 1–2 Stunden alt gehalten und verworfen. Jetzt wird die Epoche explizit in UTC berechnet.
2. `Set-Content -Encoding UTF8` schreibt in PS 5.1 ein BOM. `json.loads()` wäre daran gescheitert. Die App liest jetzt `utf-8-sig`.

Erster Test von Hand, **bevor** du den Button in der App drückst:

```powershell
# als Administrator
powershell -ExecutionPolicy Bypass -File packaging\windows\dreamtemp-helper.ps1 `
           -OutFile "$env:APPDATA\OSC-DreamChatbox\temps.json" -Debug1
```

`-Debug1` gibt jede geschriebene Zeile aus. Läuft LHM parallel, solltest du sofort `wmi:LibreHardwareMonitor` sehen. Ohne LHM entweder `acpi` oder gar nichts – dann brauchst du LHM.

Falls das Skript still bleibt: `$ErrorActionPreference = "SilentlyContinue"` in Zeile 40 auf `"Continue"` setzen, dann werden die WMI-Fehler sichtbar.

Kein CHANGELOG-Eintrag, Version weiterhin nicht gebumpt.
