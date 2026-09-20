# Drop-in v1.5.1: GPU auswählen, zweite GPU

Über den Baum kopieren. Version ist auf **v1.5.1** gesetzt,
CHANGELOG.md und HIGHLIGHTS.md haben ihren Block oben.

## Geändert

    core/backends/hardware_linux.py    alle Karten aufzählen, pro Karte lesen
    core/backends/hardware_windows.py  dasselbe, nvidia-smi pro Index
    core/backends/hardware_null.py     list_gpus/select_gpus als Stub
    core/constants.py                  VERSION v1.5.1, GPU2_MODE_*
    core/nodegraph_eval.py             Quelle "hw_gpu2"
    core/textutils.py                  Aliase {gpu_2_temp}, {gpu2_watt}, {vram2}
    ui/nodegraph.py                    Block "GPU 2" in der Palette
    ui/config_mixin.py                 neue Keys + Normalisierung
    ui/mainwindow.py                   neue Widgets laden, _fill_gpu_combos()
    ui/pages/apps_page.py              Card-Dropdown, Sektion "Second GPU",
                                       {gpu2_*}-Werte, Zeilen-Layout
    ui/pages/placeholder_picker.py     Gruppe "GPU 2" im +-Menü
    tests/test_gpu2.py           NEU   26 Tests
    CHANGELOG.md + HIGHLIGHTS.md       Block v1.5.1
    README.md                          Hardware-Abschnitt
    packaging/windows/installer.iss, packaging/aur/PKGBUILD,
    .SRCINFO, osc_dreamchatbox.py      1.5.1

## Was neu ist

**„Select GPU"-Dropdown in der GPU-Box**, direkt unter dem Namensfeld,
immer sichtbar und mit dem gefüllt, was erkannt wurde — auch bei nur
einer Karte, weil man erst daran sieht, von welcher Karte die Werte
kommen. *Automatic* = die mit dem meisten VRAM, also genau das alte
Verhalten — eine bestehende `config.json` ändert sich nicht.

Auf Linux ist jede `/sys/class/drm/card*` mit `gpu_busy_percent` eine
Karte, dazu jeder Index von `nvidia-smi`. Die Namen kommen über die
PCI-Adresse der Karte aus `lspci`, damit zwei AMD-Karten sich am Namen
und nicht an der Nummer unterscheiden; für die erste bleibt der exakte
Mesa-Name aus `glxinfo` bevorzugt.

**Sektion „Second GPU"** über *Build my own layout*: Haken rein, Karte
wählen, eigene Haken (Usage / Temp / Power / Name / VRAM), eigener Name,
eigener Style. Der Kasten ist ein **GPU-2-Kasten im selben Rahmen und
derselben Spaltenbreite** wie GPU / VRAM / CPU / RAM — und er ist
**versteckt**, solange der Haken nicht drin ist, statt wie sonst nur
ausgegraut: auf einer Maschine mit einer Karte wären das neun Bedienteile,
die nie etwas tun. Ist nur eine Karte da und der Haken trotzdem gesetzt,
steht an der Stelle die Zeile, die sagt warum.
*Show as* entscheidet nur das generierte Layout —
eigene Zeile oder all in one hinter der ersten Karte. Im eigenen String,
in All in one und auf dem Node-Canvas (Block *GPU 2*) platzierst du es
selbst.

Neue Platzhalter: `{gpu2_name}` `{gpu2_usage}` `{gpu2_temp}`
`{gpu2_power}` `{vram2_usage}` `{vram2_pct}`. Sie existieren auch bei
ausgeschalteter Funktion und sind dann leer, fallen also mit ihren
Trennzeichen weg wie jeder andere leere Platzhalter.

Die beiden Dropdowns bieten nie dieselbe Karte an: die Karte der ersten
GPU-Box fehlt in der Liste der zweiten.

## Zwei Bugs, die dabei auffielen

    nvidia-smi --loop    behielt nur die Zeile mit "0," → eine zweite
                         NVIDIA-Karte war nicht lesbar, obwohl ihre Werte
                         schon in der Pipe standen
    amdgpu-hwmon-Cache   lag unter einem Schlüssel für „die" Karte →
                         Temperatur und Watt einer zweiten AMD-Karte wären
                         von der ersten gekommen. Jetzt pro Karte, und der
                         globale „irgendein Knoten namens amdgpu"-Fallback
                         nur noch für die Standardkarte

## Grenzen (stehen auch im Changelog)

* Windows: Werte pro Karte kommen von `nvidia-smi`. Die PDH-Zähler von
  Windows sind maschinenweit, nicht pro Adapter — eine zweite
  Nicht-NVIDIA-Karte lässt sich benennen und auswählen, liefert aber
  keine Werte. Der Dropdown-Eintrag sagt das selbst.
* Intel-GPUs haben unter Linux keinen Usage-Zähler in sysfs; sie
  erscheinen wie bisher nur als Name.

## Testen

    python3 -m pytest tests/test_gpu2.py -q     # 26 Tests
    python3 -m pytest -q                        # alles

Hier im Container liefen alle Tests außer `test_afk.py` und
`test_media_custom_mode.py` — die importieren `ui/mainwindow.py`, und
`ui/pages/options_page.py` + `ui/pages/plugins_page.py` enthalten
f-Strings mit Backslash, die erst ab Python 3.12 erlaubt sind (der
Container hat 3.11). Auf deinem Arch mit 3.13 ist das kein Thema.

## Noch von Hand

    python3 scripts/bump_version.py --check --expect 1.5.1
    git add -A && git commit  → Tag v1.5.1
    bash scripts/build_appimage.sh
