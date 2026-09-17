# Drop-in v1.4.9: Release-Blocker, schnellerer Start, Optionen in Tabs, Highlights

Über den Baum kopieren. Version ist auf **v1.4.9** gesetzt,
CHANGELOG.md und HIGHLIGHTS.md haben ihren Block oben.

## Geändert

    ui/pages/options_page.py         Tabs General / OSC / Design
    ui/docviewer.py            NEU   Fenster für Highlights + Changelog
    HIGHLIGHTS.md              NEU   Kurzfassung jeder Version für Nutzer
    CHANGELOG.md                     fehlende Überschrift [v1.4.5] wieder da
    tests/test_docs.py         NEU   5 Tests für die beiden Dateien
    scripts/bump_version.py    NEU   Version an allen Stellen setzen/prüfen
    scripts/build_appimage.sh        build/ leeren -> AppImage nach build/,
                                     CHANGELOG + HIGHLIGHTS mit in die AppImage
    packaging/aur/PKGBUILD           CHANGELOG + HIGHLIGHTS neben die App
    packaging/windows/osc-dreamchatbox.spec   dasselbe für Windows
    core/constants.py                VERSION v1.4.9,
                                     DISCORD_URL -> discord.gg/ShNKvvZu74
    CHANGELOG.md + HIGHLIGHTS.md     Block v1.4.9
    packaging/windows/installer.iss  1.4.9
    .SRCINFO, osc_dreamchatbox.py    1.4.9
    README.md                        Discord-Badge + Link -> ShNKvvZu74

## Release-Blocker

    ui/pages/options_page.py   Update-Check vergleicht Zahlen statt !=
    core/atomicfile.py   NEU   write_text_atomic(): .tmp + os.replace
    ui/config_mixin.py         Config atomar schreiben
    core/plugins.py            Plugin-Config atomar schreiben
    core/plugin_store.py       Katalog-Cache atomar, tarball ohne refs/heads
    config/plugins.json        Gray-Gaming auf Commit 2150604c gepinnt,
                               Katalog-Version 1.1.1 -> 1.1.2
    tests/test_atomicfile.py   NEU 4 Tests
    pytest.ini                 NEU Warnungen von standard-aifc/audioop aus
    packaging/*.desktop, install.sh, core/desktop_integration.py,
    scripts/build_appimage.sh        Categories=Network;Chat;
    tests/test_wintemp_cache.py      Reset-Stempel unabhängig von der Uptime

**Update-Check:** nutzt `compare_versions()` aus dem Plugin-Store. Neuer
Fall: lokal neuer als das letzte Release -> "You are ahead of the latest
release" statt einer Update-Meldung auf eine ältere Version.

**Plugin-Store:** `Source.tarball` hieß `tar.gz/refs/heads/<ref>` und
konnte damit nur Branches. Jetzt `tar.gz/<ref>` — Branch, Tag und Commit
funktionieren (alle drei gegen codeload getestet). Das fremde Plugin
zeigt jetzt auf einen Commit statt auf `main`, ein Push dort erreicht
also niemanden mehr automatisch. Kehrseite: Updates von Gray-Gaming
kommen erst an, wenn du die SHA im Katalog änderst. Deine eigenen
Plugins stehen weiter auf `main`.

**Noch von Hand (ZIP kann nichts löschen):**

    git rm tests/test_plugin_osc.py core/oscbridge.py

## Performance: nvidia-smi als Dauerprozess

    core/backends/hardware_linux.py   _NvidiaSmiLoop + _parse_nvsmi
    ui/mainwindow.py                  closeEvent ruft hw.close()

Statt alle 2 s einen neuen Prozess läuft ein `nvidia-smi --loop=2`, ein
Thread hält die neueste CSV-Zeile. Nur Karte 0 (neue Spalte `index`).
Ende des Prozesses: `hw.close()` beim Schließen, nach 15 s ohne Poll
(Hardware-Karte aus), und bei einem Absturz über SIGPIPE, weil niemand
mehr aus der Pipe liest. Gibt `--loop` dreimal keine Zeile (alter
Treiber), schaltet es dauerhaft auf den alten Weg zurück.

Mit einem Fake-nvidia-smi getestet: erster Poll sofort, weitere Polls
ohne messbaren Aufwand, Idle-Stop, Neustart danach, Fallback, Waise nach
`kill -9`. **Auf echter NVIDIA-Karte nicht getestet** — bitte einmal
Hardware-Karte an/aus und Werte prüfen.

## Performance: Start 3,9 s -> 0,3 s

    core/oscquery.py     mDNS-Anmeldung im Hintergrund-Thread
    ui/config_mixin.py   save_config() pausiert beim Laden
    ui/mainwindow.py     apply_config_to_ui() schreibt die Config 1x statt 23x
    ui/pages/options_page.py   Statuszeile "announcing via mDNS ..."

**OSCQuery:** `register_service()` blockierte ~1,5 s pro Dienst im
UI-Thread. Ports + HTTP-Server entstehen weiter sofort, nur die
Anmeldung läuft in `_announce()`. Die VRChat-Suche startet sofort.
Kein `run_async`: core/ bleibt ohne Qt. Stop während der Anmeldung ist
abgefangen (alter Thread gibt still auf).

**Config:** `_loading_config`-Flag, am Ende ein `_write_config()`.

Gemessen (offscreen): Fenster nach 0,33 s statt 3,87 s, 1 statt 23
Schreibvorgänge, Leerlauf unverändert 0,1 % CPU. Stop direkt nach
Start + Neustart getestet: keine Fehlermeldung, nur eine Anmeldung.

## Optionen in Tabs

Drei Knöpfe unter dem Titel, gleiche Optik wie Installed / Store:

    General   drei Karten:
                Updates    Check for updates, Highlights, Changelog, Version
                Community  Discord, Ko-fi, VRChat Group
                Fixes      App Tray Fix, VRC Picture Folder Fix
                           (ganze Karte nur unter Linux, wie vorher die Zeile)
    OSC       OSCQuery-Karte (OSCQuery, OSC input, externes Ziel, Hotkeys,
              Fix OSCQuery) und die Karte mit Slim Chatbox, Intervall,
              Instant send, OSC-Ziel
    Design    Customization-Karte

Keine Einstellung wurde umbenannt, nur auf Tabs und Karten verteilt.
Karten und Knöpfe auf dem General-Tab kommen aus zwei kleinen Helfern,
`_opt_card()` und `_opt_button()`, statt jeden Knopf sechs Zeilen lang
von Hand zu bauen.
Alle `self.*`-Namen bleiben gleich, `apps_page.py` greift weiter auf
`toggle_osc_in` zu.

Absichtlich kein QStackedWidget: der ist immer so hoch wie seine längste
Seite (auch über heightForWidth bei umbrechenden Labels), der kurze
General-Tab hätte dann in leeren Platz gescrollt. Stattdessen liegen alle
drei Tabs im Layout, nur einer ist sichtbar — versteckte Widgets nehmen
keinen Platz.

## Highlights + Changelog

`ui/docviewer.py` zeigt die Markdown-Datei mit Qts eigenem Markdown
(`QTextBrowser.setMarkdown`), keine neue Abhängigkeit. Gesucht wird neben
der App (Quelltext, AppImage, AUR, Windows) und unter
`/usr/share/doc/osc-dreamchatbox`. Fehlt die Datei, öffnet sie GitHub.
Im Highlights-Fenster führt "Full changelog" zum langen.

`HIGHLIGHTS.md` hat 2-3 Punkte pro Version von v1.4.9 bis v1.2.0, in
Nutzersprache. Beim Schreiben ist aufgefallen, dass in CHANGELOG.md die
Überschrift `## [v1.4.5]` fehlte (seit Commit "v1.4.6") — v1.4.5 stand
als Teil von v1.4.6 da. Aus der Git-Historie wiederhergestellt.

## Getestet

    Tests                 181 grün, ohne tests/test_plugin_osc.py
    bump 1.4.9 + --check  grün, AppImage baut als 1.4.9
    Gegenprobe            ohne [v1.4.5]-Überschrift wird test_docs rot
    App offscreen         alle 3 Tabs + neue General-Karten gerendert, General/Design ohne
                          Scrollbalken, OSC scrollt wie vorher
    Dialoge               Highlights + Changelog gerendert
    AppImage-Build        grün, HIGHLIGHTS.md liegt in usr/lib/osc-dreamchatbox
    bump --check          grün, meldet jetzt auch fehlenden HIGHLIGHTS-Block

## Nicht getestet

Windows-Build und AUR-Paket nicht gebaut — nur die Kopierzeilen ergänzt.
Nicht auf echtem Desktop angesehen, nur offscreen: Farben unter anderen
Themes als Default bitte einmal durchklicken.

## Altlasten — nicht angefasst

    git rm tests/test_plugin_osc.py core/oscbridge.py scripts/build-appimage.sh \
           packaging/.SRCINFO PATCH-README.md PATCH-AIO-README.md
