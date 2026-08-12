# Watt-Anzeige: Fixes + Diagnose

Drop-in für **v1.3.3**, über den Projektordner entpacken.

## Was ich gefunden habe

Die UI-Seite ist **nicht** der Fehler. Ich habe dein Template aus dem
Screenshot mit beiden Platzhaltern nachgestellt und beide Reihenfolgen
durchgespielt – `{gpu_power}` und `{cpu_power}` rendern beide, immer,
unabhängig davon welchen Haken man zuerst setzt. Der Fehler sitzt eine
Ebene tiefer: einer der beiden Werte kommt als `None` aus dem Sensor.

Dabei sind mir zwei echte Bugs in `hardware_linux.py` aufgefallen.

### 1 · Zwei Karten heißen `amdgpu`

Dein 9700X bringt eine eigene Radeon mit. Damit stehen in
`/sys/class/hwmon` **zwei** Knoten namens `amdgpu`: die iGPU und die
9070 XT.

* `_find_amd_card()` nahm „die erste Karte mit `gpu_busy_percent`" –
  das ist genauso oft die iGPU wie die echte Karte. Jetzt gewinnt die mit
  mehr VRAM. Eine iGPU schneidet sich ein paar hundert MB aus dem
  System-RAM ab, eine dedizierte Karte hat Gigabytes; die Kartennummer
  ändert sich dagegen mit der Boot-Reihenfolge.
* Watt und Temperatur wurden danach über `/sys/class/hwmon` gesucht und
  der erste Treffer genommen. Dieser `glob()` läuft in
  **Dateisystem-Reihenfolge, nicht sortiert** – welcher der beiden Knoten
  antwortet, war also über Neustarts hinweg nicht stabil. Genau das
  erzeugt das „hängt davon ab, in welcher Reihenfolge ich was anschalte".
  Beide lesen jetzt den hwmon-Knoten, der zur ausgewählten Karte gehört.

### 2 · CPU-Watt gibt es auf Zen meist gar nicht

`k10temp` steht zwar in der Sensorliste, liefert auf Zen aber **nur
Temperaturen**. Die Package-Watt hängen an den SVI2-Rails, und die liest
nur `zenpower3` (bzw. `zenergy`). Ohne das Modul bleibt als einzige
Quelle RAPL – und das ist seit Kernel 5.10 root-only (CVE-2020-8694).

Auf einem Standard-CachyOS ohne `zenpower3` ist `{cpu_power}` also
**dauerhaft leer**, und zwar völlig unabhängig von den neuen Haken.

Das war bisher stumm. Jetzt steht einmalig im Log, warum der Wert leer
bleibt. `zenergy` und `amd_energy` habe ich zusätzlich in die Sensorliste
aufgenommen.

## Bitte einmal laufen lassen

```
./watt-diagnose.sh
```

Damit sehen wir schwarz auf weiß, ob deine Maschine zwei `amdgpu`-Knoten
hat und ob überhaupt irgendein CPU-Power-Sensor existiert. Erst danach
weiß ich, ob die zwei Fixes oben *dein* Problem treffen oder ob noch
etwas anderes dahintersteckt – ich kann deine Hardware hier nicht
nachbilden, alles oben ist an einem nachgebauten sysfs getestet.

Falls die Diagnose kein CPU-Power-Modul zeigt:

```
paru -S zenpower3-dkms
sudo modprobe zenpower3
```

(zenpower3 kollidiert mit `k10temp` – ist bekannt, das DKMS-Paket blockt
k10temp per modprobe-Config. Temperaturen kommen danach aus zenpower.)

## Getestet

* Nachgebautes sysfs mit iGPU (card0, 512MB, 5W) + RX 9070 XT (card1,
  16GB, 213W): es wird card1 gewählt, 213W und 61°C kommen aus deren
  eigenem Knoten, die 5W der iGPU tauchen nirgends auf
* CPU ohne Power-Sensor → `None` **plus** Log-Zeile mit dem Grund
* Template mit beiden Platzhaltern, beide Haken-Reihenfolgen: beide Werte
  erscheinen
* Alle bisherigen Tests (AIO mehrzeilig, Custom Time, Watt-Haken) laufen
  unverändert durch
