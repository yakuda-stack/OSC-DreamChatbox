# Schritt 3 – Hardware-Backend für Windows (Drop-in)

Über den Stand aus Schritt 2a entpacken. Danach diese Datei löschen.

| Datei | |
|---|---|
| `core/backends/hardware_windows.py` | **NEU** – das eigentliche Backend |
| `core/hardware.py` | geändert – Weiche zeigt jetzt auf Windows statt Null |
| `core/backends/hardware_null.py` | geändert – ein Attribut ergänzt (`gpu_backend_label`) |
| `packaging/windows/osc-dreamchatbox.spec` | geändert – `winreg`/`mmap`/`ctypes.wintypes` in den `hiddenimports` |

`ui/` bleibt weiterhin komplett unangetastet.

---

## Was ohne Zusatzsoftware funktioniert

| Wert | Quelle | Status |
|---|---|---|
| CPU-Auslastung | `GetSystemTimes()` (kernel32) | ✅ immer |
| RAM used/total/% | `GlobalMemoryStatusEx()` | ✅ immer |
| CPU-Name | Registry `ProcessorNameString` | ✅ immer |
| GPU-Name | nvidia-smi, sonst Registry `DriverDesc` | ✅ immer |
| GPU-Auslastung | nvidia-smi, sonst PDH `\GPU Engine` | ✅ ab Win10 1709 |
| VRAM used | nvidia-smi, sonst PDH `\GPU Process Memory` | ✅ ab Win10 1709 |
| VRAM total | nvidia-smi, sonst Registry `qwMemorySize` | ✅ immer |
| GPU-Temperatur | nvidia-smi | ✅ **nur NVIDIA** |

## Was Zusatzsoftware braucht

| Wert | Braucht | Warum |
|---|---|---|
| CPU-Temperatur | LibreHardwareMonitor | Windows gibt Kerntemperaturen ohne signierten Kernel-Treiber nicht an Userspace-Prozesse heraus. Es gibt dafür keine API. |
| GPU-Temperatur (AMD/Intel) | LibreHardwareMonitor | dito |
| FPS | RTSS | FPS existieren nur im zeichnenden Prozess – auf Linux liest die App dafür MangoHuds CSV, auf Windows RTSS' Shared Memory |

**LibreHardwareMonitor:** installieren, starten, `Options → Remote Web Server → Run` aktivieren. Die App findet ihn dann automatisch auf `http://localhost:8085/data.json`. Läuft er nicht, wird genau **einmal** geloggt und danach nur noch minütlich erneut versucht – kostet also nichts pro Poll.

**RTSS:** liegt MSI Afterburner bei. Wird automatisch erkannt.

Beides ist optional und ohne Konfiguration. Fehlt es, bleiben die Werte `None` – genau wie auf einem Linux-Rechner ohne `hwmon` oder ohne MangoHud.

---

## Erst diagnostizieren, dann die App starten

```powershell
cd C:\Dev\OSC-DreamChatbox
.\venv\Scripts\Activate.ps1
python -m core.backends.hardware_windows
```

Das gibt jede Quelle einzeln aus und wartet zwischen zwei Snapshots. Erwartete Ausgabe **ohne** LHM/RTSS:

```
  CPU usage : 12.4
  CPU temp  : None    (needs LibreHardwareMonitor)
  RAM       : {'used': 14.2, 'total': 31.9, 'pct': 44.5}
  GPU       : {'usage': 31.0, 'temp': None, 'vram_used': 3.4, ...}
  FPS       : None    (needs RTSS + a running game)
```

`None` heißt „keine Quelle für diesen Wert", **nicht** „Fehler".

Zwei Env-Vars als Notausgang, solange die Options-Seite noch keine Zeilen dafür hat:

```powershell
$env:DCB_LHM_URL     = "http://localhost:8085/data.json"   # anderer Port
$env:DCB_FPS_PROCESS = "vrchat"                            # welche .exe zaehlt
```

---

## Umsetzungsdetails, die auf Windows leicht schiefgehen

* **Kein Konsolen-Blitzen.** Jeder `subprocess`-Aufruf (nvidia-smi) läuft mit `CREATE_NO_WINDOW`. Ohne das blinkt bei einem `-NoConsole`-Build alle paar Sekunden ein schwarzes Fenster über dem Spiel.
* **`PdhAddEnglishCounterW`**, nicht `PdhAddCounterW`. Auf einem deutschen Windows heißen die Zähler lokalisiert; die englische Variante funktioniert überall.
* **GPU-Auslastung wird pro Engine-Typ summiert, dann das Maximum genommen.** Einfaches Aufsummieren aller Instanzen zählt doppelt, weil 3D, Copy und VideoDecode parallel laufen. Das ist die Rechnung, die auch der Task-Manager benutzt.
* **`GetSystemTimes`: Kernel-Zeit enthält bereits die Idle-Zeit**, `total = kernel + user`. Ein häufiger Fehler ist, Idle zusätzlich zu addieren.
* **Zahlen-Parsing verträgt Komma.** LHM formatiert mit der Systemlocale, auf deinem System also `62,4 °C`.
* **Temperatur-Sensoren werden bewertet, nicht der erste Treffer genommen.** `Core (Tctl/Tdie)` schlägt `Core #3`, und `GPU Core` schlägt `GPU Hot Spot` – der Hot Spot liegt ~15 K höher und sähe in der Chatbox alarmierend aus.

---

## Offener Punkt für Schritt 2b

`ui/pages/apps_page.py` (~Zeile 1437) schreibt fest verdrahtet:

```python
"GPU backend: " + ("NVIDIA (nvidia-smi)" if self.hw.has_nvidia
                   else ("AMD (sysfs)" if self.hw.amd_card ...
```

Auf Windows mit AMD-Karte steht dort dann „AMD (sysfs)", was es nicht gibt. Ich habe den Backends deshalb ein Attribut mitgegeben, das 2b einfach nehmen kann:

```python
label = getattr(self.hw, "gpu_backend_label", None) or <bisherige Logik>
```

Ebenso: Die Zeile „MangoHud folder" auf der Hardware-Karte ist auf Windows sinnlos (FPS kommt aus RTSS). `fps(folder)` ignoriert den Parameter dort, die Zeile sollte in 2b ausgeblendet oder umbenannt werden.

Kein CHANGELOG-Eintrag – die Version ist weiterhin nicht gebumpt.
