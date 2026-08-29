# Drop-in v1.4.7

Über den Baum kopieren. `AppDir/` ist bewusst nicht dabei.

## Versionsbump

    core/constants.py               VERSION = "v1.4.7"
    osc_dreamchatbox.py             Docstring
    packaging/aur/PKGBUILD          pkgver=1.4.7
    .SRCINFO                        pkgver + Source-URL
    packaging/windows/installer.iss AppVersion-Fallback + Kommentarbeispiel
    CHANGELOG.md                    neuer [v1.4.7]-Eintrag, 2026-08-29

`packaging/.SRCINFO` steht weiter auf 1.2.6 und ist damit schon vor
diesem Drop-in aus dem Tritt gewesen - die gepflegte Datei ist die im
Wurzelverzeichnis. Nicht angefasst, weil unklar ist, ob die Kopie noch
gebraucht wird.

`sha256sums` im PKGBUILD steht weiter auf SKIP, das macht `updpkgsums`
vor dem Upload wie immer.

## Inhalt

**Neu: AFK.** Zwei kleine Schalter unten im Preview-Feld. "Detect" liest
VRChats eigenen `AFK`-Avatar-Parameter, "I'm AFK" ist der manuelle
Schalter und schlägt die Erkennung. Drei umschaltbare Texte am Boden der
Personal-Status-Card, jeder mit eigenem Inhalt, dazu ein
Minuten-Timer (`{afk_time}`).

Kein Rahmen um den Text: VRChats Chatbox-Font ist proportional,
Box-Zeichen liegen dort nicht übereinander. Das Rahmen übernimmt die
Custom-Box-Card, und nur wenn sie an ist.

Detect braucht den OSC-Input (udp/9001) und fragt einmal nach, statt als
toter Schalter dazustehen.

**Neu: fünf weitere Lyrics-Quellen.** `core/lyrics_sources.py` -
LyricsPlus, Better Lyrics, Paxsenix, KuGou, Musixmatch neben LRCLIB.
Reihenfolge fest im Code, erster synchroner Treffer gewinnt, eine Quelle
weiter unten wird nur angefasst wenn alles darüber leer war. Die drei
ersten sind an, die drei unofficiellen aus. Endpunkte aus Meld
(github.com/FrancescoGrazioso/Meld, GPL-3.0).

Nur Stdlib: urllib, json, base64, ElementTree.

## Getestet

    117 Tests             grün  (davon 26 neu: AFK + Lyrics-Quellen)
    Headless-Smoke-Test   grün  (Presets, Timer, Custom Box, Migration)
    ruff                  nur I001 auf den neuen Dateien
    VERSION               v1.4.7

## Nicht getestet

Die sechs Lyrics-Endpunkte konnte ich **nicht live aufrufen** - die
Sandbox hier lässt nur github/pypi/npm raus. URLs, Parameternamen und
Response-Felder sind aus Melds Quellcode übernommen, das Format-Handling
(LRC-Zeitstempel, TTML in beiden Zeitschreibweisen, base64 bei KuGou)
ist mit Fixtures getestet. Ein echter Lauf mit laufender Musik steht
also noch aus - am ehesten bricht es an einem Feldnamen, den Meld
inzwischen anders liest.
