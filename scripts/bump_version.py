#!/usr/bin/env python3
"""
scripts/bump_version.py — Version an allen Stellen gleichzeitig setzen
=====================================================================
Gegenstueck zu Dream-VoiceTraining, hier fuer OSC-DreamChatbox.
Der Ablauf drumherum steht in update_dreambox.txt.

    python3 scripts/bump_version.py 1.4.9                   # Version setzen
    python3 scripts/bump_version.py 1.5.0-alpha             # Vorabversion
    python3 scripts/bump_version.py --check                 # nur pruefen
    python3 scripts/bump_version.py --check --expect 1.4.9

Welche Dateien gepflegt werden, steht unten in ZIELE. Das ist die einzige
Stelle, die du anfassen musst, wenn eine Datei umzieht oder dazukommt.

Unterschiede zur VoiceTraining-Version:
  * Ein Muster pro Ziel reicht fuer Lesen UND Schreiben: ersetzt wird genau
    das, was im Muster in (Klammern) steht.
  * Erst wird alles im Speicher geaendert. Geschrieben wird nur, wenn alle
    Pflicht-Ziele gefunden wurden — kein halb aktualisierter Stand mehr.
  * --check prueft zusaetzlich, ob ueberall der aktuelle Discord-Link steht.

Was das Skript NICHT tut (bewusst):
  * keinen Git-Tag setzen und nichts pushen
  * die .SRCINFO im AUR-Repo erzeugen — das macht  makepkg --printsrcinfo
    (die Kopie im Projekt bekommt nur pkgver + Source-URL nachgezogen)
  * CHANGELOG.md / HIGHLIGHTS.md nicht schreiben — der Text kommt von dir; das Skript
    erinnert nur daran, wenn der Block fehlt
"""
import argparse
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# =========================================================================== #
#  EINSTELLUNGEN — hier anpassen
# =========================================================================== #
# Das ERSTE Ziel ist die Quelle der Wahrheit, alle anderen muessen dazu passen.
#   datei    Pfad relativ zum Projektordner
#   muster   Regex; was in (Klammern) steht, ist die Version und wird ersetzt
#   alle     False = nur den ersten Treffer ersetzen, True = alle Treffer
#   pflicht  True  = fehlt Datei oder Treffer -> Abbruch, nichts wird geschrieben
#            False = wird uebersprungen, wenn Datei oder Treffer fehlt
#   pkg      True  = 1.4.9_alpha (PKGBUILD), False = 1.4.9-alpha (wie der Git-Tag)

ZIELE = [
    # Quelle der Wahrheit. Steht mit "v" davor drin, ersetzt wird nur der Teil danach.
    dict(datei="core/constants.py",
         muster=r'^VERSION\s*=\s*"v?([^"]+)"',
         alle=False, pflicht=True, pkg=False),

    # pkg=True: Unterstrich-Form (1.4.9_alpha), pkgver verbietet Bindestriche.
    # Der PKGBUILD macht daraus selbst wieder den Tag v1.4.9-alpha.
    dict(datei="packaging/aur/PKGBUILD",
         muster=r"^pkgver=(\S+)",
         alle=False, pflicht=True, pkg=True),

    # Fallback-Version + Beispiel im Kommentar. make-release.ps1 reicht die
    # Version zwar per /D rein, aber beim Bauen von Hand zaehlt der Fallback.
    dict(datei="packaging/windows/installer.iss",
         muster=r'(?:#define\s+AppVersion\s+"|/DAppVersion=)([^"\s]+)',
         alle=True, pflicht=True, pkg=False),

    # Kopie der .SRCINFO im Projekt: pkgver + Dateiname (Unterstrich-Form) ...
    dict(datei=".SRCINFO",
         muster=r"(?:^\s*pkgver = |osc-dreamchatbox-)(\d[^\s:]*?)(?=\s*$|\.tar\.gz)",
         alle=True, pflicht=False, pkg=True),
    # ... und der Tag in der Source-URL (Bindestrich-Form)
    dict(datei=".SRCINFO",
         muster=r"/tags/v(\d[^\s]*?)\.tar\.gz",
         alle=True, pflicht=False, pkg=False),

    # Docstring ganz oben — nur Kosmetik, daher kein Pflichtziel
    dict(datei="osc_dreamchatbox.py",
         muster=r"^OSC-DreamChatbox v(\S+)",
         alle=False, pflicht=False, pkg=False),
]

# Liest die Version schon selbst aus core/constants.py, brauchen also KEIN Ziel:
#   scripts/build_appimage.sh, packaging/windows/make-release.ps1,
#   packaging/windows/build-exe.ps1, packaging/windows/osc-dreamchatbox.spec

CHANGELOG = ROOT / "CHANGELOG.md"
HIGHLIGHTS = ROOT / "HIGHLIGHTS.md"

# Aktueller Einladungscode (Server-Einstellungen -> Einladungen)
DISCORD_CODE = "ShNKvvZu74"
DISCORD_RE = re.compile(r"discord(?:app)?\.(?:gg|com/invite)/([A-Za-z0-9-]+)")
DISCORD_ENDUNGEN = {".py", ".md", ".json", ".txt", ".html", ".iss", ".desktop"}
IGNORIERTE_ORDNER = {".git", ".github", ".venv", "venv", ".build-venv", "__pycache__", "build",
                     "dist", "AppDir", ".pytest_cache", ".ruff_cache"}

# 1.4.9, 1.4.9-alpha oder 1.4.9_alpha — das Skript schreibt jede Datei in
# ihrer eigenen Form (siehe pkg oben).
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-_][A-Za-z0-9]+)?$")


def form(version, ziel):
    """Version so, wie sie in diese Datei gehoert."""
    return version.replace("-", "_") if ziel["pkg"] else version.replace("_", "-")


def gleich(a, b):
    """1.4.9-alpha und 1.4.9_alpha gelten als dieselbe Version."""
    return a.replace("_", "-") == b.replace("_", "-")


# --------------------------------------------------------------------------- #
#  Hilfsfunktionen
# --------------------------------------------------------------------------- #
def lesen(ziel):
    """Alle Versionen, die das Muster in der Datei findet.
    None = Datei fehlt, [] = Datei da, aber Muster passt nicht."""
    pfad = ROOT / ziel["datei"]
    if not pfad.exists():
        return None
    gefunden = set()
    for m in re.finditer(ziel["muster"], pfad.read_text(encoding="utf-8"), re.M):
        gefunden.update(g for g in m.groups() if g)
    return sorted(gefunden)


def ersetzen(ziel, text, neu):
    """Ersetzt in jedem Treffer alle (Klammer-Gruppen) durch `neu`.
    Gibt (neuer_text, anzahl_treffer) zurueck."""
    def tausche(m):
        s, start = m.group(0), m.start()
        # Von hinten nach vorne, sonst verrutschen die Positionen der
        # vorderen Gruppen, sobald eine hintere laenger/kuerzer wird.
        for g in range(len(m.groups()), 0, -1):
            if m.group(g) is not None:
                a, b = m.start(g) - start, m.end(g) - start
                s = s[:a] + neu + s[b:]
        return s

    return re.subn(ziel["muster"], tausche, text,
                   count=0 if ziel["alle"] else 1, flags=re.M)


def pkgrel_lesen():
    for ziel in ZIELE:
        pfad = ROOT / ziel["datei"]
        if pfad.name == "PKGBUILD" and pfad.exists():
            m = re.search(r"^pkgrel=(\S+)", pfad.read_text(encoding="utf-8"), re.M)
            return m.group(1) if m else None
    return None


def discord_pruefen():
    """(falsche_links, richtiger_link_gefunden)
    falsche_links = {datei: [codes]} fuer Einladungen mit anderem Code."""
    falsch, richtig = {}, False
    for ordner, unterordner, dateien in os.walk(ROOT):
        # Liste an Ort und Stelle kuerzen -> os.walk geht da gar nicht erst rein
        unterordner[:] = [d for d in unterordner if d not in IGNORIERTE_ORDNER]
        for name in dateien:
            pfad = pathlib.Path(ordner) / name
            if pfad.suffix not in DISCORD_ENDUNGEN:
                continue
            try:
                codes = set(DISCORD_RE.findall(pfad.read_text(encoding="utf-8")))
            except (UnicodeDecodeError, OSError):
                continue
            if DISCORD_CODE in codes:
                richtig = True
            codes.discard(DISCORD_CODE)
            if codes:
                falsch[str(pfad.relative_to(ROOT))] = sorted(codes)
    return falsch, richtig


def top_block(path, pattern):
    """Version der obersten ##-Ueberschrift, oder None."""
    if not path.exists():
        return None
    m = re.search(pattern, path.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
#  Pruefen
# --------------------------------------------------------------------------- #
def check(expect=None):
    """0 = alles stimmig, 1 = Abweichung."""
    probleme, hinweise = [], []
    quelle = None

    for i, ziel in enumerate(ZIELE):
        name = ziel["datei"]
        versionen = lesen(ziel)
        liste = probleme if ziel["pflicht"] else hinweise

        if versionen is None:
            print(f"{name:<34} (Datei fehlt)")
            if ziel["pflicht"]:
                probleme.append(f"{name}: Datei nicht gefunden — Pfad in ZIELE anpassen")
            continue

        print(f"{name:<34} {', '.join(versionen) or '-'}")
        if not versionen:
            liste.append(f"{name}: Muster passt nicht (Datei ist da)")
            continue

        if i == 0:
            if len(versionen) > 1:
                probleme.append(f"{name}: mehrere Versionen gefunden ({', '.join(versionen)})")
            quelle = versionen[0]
        elif quelle and not (len(versionen) == 1 and gleich(versionen[0], quelle)):
            probleme.append(f"{name}: steht auf {', '.join(versionen)}, "
                            f"{ZIELE[0]['datei']} auf {quelle}")

    pkgrel = pkgrel_lesen()
    if pkgrel:
        print(f"{'':<34} (pkgrel={pkgrel})")

    if expect and quelle and not gleich(quelle, expect.lstrip("v")):
        probleme.append(f"Erwartet wurde {expect}, im Code steht {quelle}")

    c_top = top_block(CHANGELOG, r"^## \[?v?(\d+\.\d+\.\d+[^\]\s]*)")
    if quelle and CHANGELOG.exists() and not (c_top and gleich(c_top, quelle)):
        hinweise.append(f"CHANGELOG.md hat oben noch keinen Block [v{quelle}] (oben steht {c_top})")
    h_top = top_block(HIGHLIGHTS, r"^## v?(\d+\.\d+\.\d+\S*)")
    if quelle and HIGHLIGHTS.exists() and not (h_top and gleich(h_top, quelle)):
        hinweise.append(f"HIGHLIGHTS.md hat oben noch keinen Block v{quelle} (oben steht {h_top})")

    falsch, richtig = discord_pruefen()
    for datei, codes in falsch.items():
        hinweise.append(f"{datei}: Discord-Link mit anderem Code ({', '.join(codes)}) "
                        f"— aktuell ist {DISCORD_CODE}")
    if not richtig:
        hinweise.append(f"Discord-Link discord.gg/{DISCORD_CODE} kommt nirgends vor")

    if hinweise:
        print("\nHinweise:")
        for h in hinweise:
            print(f"  - {h}")

    if probleme:
        print("\nFEHLER:")
        for p in probleme:
            print(f"  - {p}")
        return 1

    print("\nAlle Versionsangaben stimmen ueberein.")
    return 0


# --------------------------------------------------------------------------- #
#  Setzen
# --------------------------------------------------------------------------- #
def bump(neu):
    if not VERSION_RE.match(neu):
        print(f"Ungueltige Version: {neu}")
        print("Erwartet: 1.2.3 oder 1.2.3-alpha (ohne v davor)")
        return 1

    neu = neu.replace("_", "-")          # Grundform wie der Git-Tag
    alt = lesen(ZIELE[0])
    print(f"Version {', '.join(alt) if alt else '?'} -> {neu}\n")

    texte = {}          # pfad -> geaenderter Text (erst am Ende geschrieben)
    fehler = False

    for ziel in ZIELE:
        name = ziel["datei"]
        pfad = ROOT / name

        if not pfad.exists():
            if ziel["pflicht"]:
                print(f"  !! {name}: Datei fehlt")
                fehler = True
            else:
                print(f"  -- {name}: gibt es nicht, uebersprungen")
            continue

        # get(): falls dieselbe Datei in mehreren Zielen steht
        text = texte.get(pfad) or pfad.read_text(encoding="utf-8")
        text, n = ersetzen(ziel, text, form(neu, ziel))

        if n == 0:
            if ziel["pflicht"]:
                print(f"  !! {name}: Muster nicht gefunden")
                fehler = True
            else:
                print(f"  -- {name}: Muster nicht gefunden, uebersprungen")
            continue

        # pkgrel IMMER auf 1: neue Upstream-Version = neuer Build.
        if pfad.name == "PKGBUILD":
            text = re.sub(r"^pkgrel=\S+", "pkgrel=1", text, count=1, flags=re.M)
            name += " (+ pkgrel=1)"

        texte[pfad] = text
        print(f"  ok {name}" + (f" ({n}x)" if ziel["alle"] else ""))

    if fehler:
        print("\nNICHTS geschrieben. Pfad oder Muster oben in ZIELE pruefen.")
        return 1

    for pfad, text in texte.items():
        pfad.write_text(text, encoding="utf-8")

    print(f"""
{len(texte)} Datei(en) geschrieben.

Naechste Schritte (siehe update_dreambox.txt):

  1. CHANGELOG.md:  "## [v{neu}] – <Datum>" GANZ OBEN
     HIGHLIGHTS.md: "## v{neu} – <Datum>"   GANZ OBEN (2-3 Punkte, fuer normale Nutzer)
  2. python3 scripts/bump_version.py --check --expect {neu}
  3. Tests, git commit, push, Tag v{neu}
  4. bash scripts/build_appimage.sh   -> build/OSC-DreamChatbox-{neu}-x86_64.AppImage
  5. Release anlegen, AUR aktualisieren
""")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Version an allen Stellen setzen/pruefen")
    ap.add_argument("version", nargs="?", help="neue Version, z. B. 1.4.9")
    ap.add_argument("--check", action="store_true", help="nur pruefen, nichts aendern")
    ap.add_argument("--expect", help="zusaetzlich gegen diese Version pruefen (Tag-Name)")
    args = ap.parse_args()

    if args.check or not args.version:
        return check(expect=args.expect)
    return bump(args.version)


if __name__ == "__main__":
    sys.exit(main())
