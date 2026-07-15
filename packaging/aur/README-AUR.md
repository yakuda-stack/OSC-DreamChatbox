# AUR-Wartung: osc-dreamchatbox

Veroeffentlicht: https://aur.archlinux.org/packages/osc-dreamchatbox
Installation fuer Nutzer: `yay -S osc-dreamchatbox` (oder paru).

## Setup (einmalig, bereits erledigt)
- AUR-Account + SSH-Key hinterlegt (Standard-Key ~/.ssh/id_ed25519 reicht).
- AUR-Repo liegt lokal unter ~/osc-dreamchatbox (Branch: master).

## Wichtige Regeln
- depends korrekt: `python-osc` (NICHT `python-python-osc` - existiert nicht!).
  Alle Abhaengigkeiten liegen im offiziellen extra-Repo, KEINE AUR-Dependency.
- pkgver ohne Bindestrich: `1.0.6_alpha`, der Tag `v1.0.6-alpha` wird via _tag gebaut.
- GitHub-Tag muss ZUERST existieren, sonst 404 bei updpkgsums.
- .SRCINFO ist Pflicht und muss bei JEDER Aenderung neu erzeugt werden.
- pkgrel: bei neuer App-Version auf 1 zurueck; bei reiner Packaging-Aenderung um 1 erhoehen.

## Update-Ablauf (neue App-Version)
1. Zuerst im Projekt-Repo: Version bumpen, committen, taggen, pushen
2. cd ~/osc-dreamchatbox
3. nano PKGBUILD  -> pkgver hoch, pkgrel=1
4. updpkgsums
5. makepkg -si    (testen: osc-dreamchatbox starten)
6. makepkg --printsrcinfo > .SRCINFO
7. git add PKGBUILD .SRCINFO && git commit -m "Update to vX" && git push origin master

## Stolperfallen
- .SRCINFO vergessen -> AUR lehnt Push ab.
- Build-Artefakte (src/, pkg/, *.pkg.tar.zst) nie committen (.gitignore).
- Ins AUR-Repo nur PKGBUILD + .SRCINFO (+ .gitignore), nie Quellcode.
- AUR-Push NUR aus ~/osc-dreamchatbox; das PKGBUILD im Projekt ist nur die Kopie.
- Branch: Projekt = main, AUR = master.
- Nach dem Push dauert `yay -Ss` teils Stunden (Cache-Index);
  `yay -S osc-dreamchatbox` funktioniert sofort.
