# AUR-Veroeffentlichung: osc-dreamchatbox

## Einmalige Vorbereitung
1. AUR-Account anlegen: https://aur.archlinux.org (Register)
2. SSH-Key hinterlegen: `ssh-keygen -t ed25519 -f ~/.ssh/aur`,
   den Inhalt von `~/.ssh/aur.pub` im AUR-Account unter
   "My Account -> SSH Public Key" eintragen.
3. In `~/.ssh/config`:
   ```
   Host aur.archlinux.org
       User aur
       IdentityFile ~/.ssh/aur
   ```

## Vor jedem Release beachten
- GitHub-Release/Tag MUSS existieren (z.B. v1.0.3-alpha), sonst laeuft
  die source=()-URL ins Leere.
- pkgver darf KEINEN Bindestrich enthalten -> im PKGBUILD steht
  `1.0.3_alpha`, der echte Tag wird via `_tag` daraus gebaut.
- Maintainer-Zeile: echte E-Mail eintragen.
- python-python-osc, python-speechrecognition und python-deepl kommen
  selbst aus dem AUR -> voellig ok, AUR-Pakete duerfen von AUR-Paketen
  abhaengen (Nutzer bauen mit yay/paru).

## Ablauf (auf deinem Arch/CachyOS)
```bash
# 1) leeres AUR-Repo klonen (existiert nach dem ersten Push)
git clone ssh://aur@aur.archlinux.org/osc-dreamchatbox.git aur-osc-dreamchatbox
cd aur-osc-dreamchatbox
cp /pfad/zum/projekt/packaging/aur/PKGBUILD .

# 2) Checksumme eintragen (ersetzt das SKIP)
updpkgsums                       # aus pacman-contrib: pacman -S pacman-contrib

# 3) lokal bauen & testen
makepkg -si                      # baut, installiert, prueft Abhaengigkeiten
osc-dreamchatbox                 # Start testen (Menue-Eintrag + Icon pruefen)
namcap PKGBUILD                  # optional: Lint (pacman -S namcap)
namcap osc-dreamchatbox-*.pkg.tar.zst

# 4) .SRCINFO erzeugen (PFLICHT fuer das AUR)
makepkg --printsrcinfo > .SRCINFO

# 5) veroeffentlichen
git add PKGBUILD .SRCINFO
git commit -m "Initial release v1.0.3-alpha"
git push origin master           # AUR nutzt 'master'
```

## Bei jedem Update spaeter
1. pkgver anpassen, pkgrel auf 1 zuruecksetzen
2. `updpkgsums && makepkg -si` (testen!)
3. `makepkg --printsrcinfo > .SRCINFO`
4. committen + pushen

## Haeufige Stolperfallen
- `.SRCINFO` vergessen -> AUR lehnt den Push ab.
- Build-Artefakte (src/, pkg/, *.pkg.tar.zst) NIE committen ->
  `.gitignore` im AUR-Repo anlegen.
- Nur PKGBUILD/.SRCINFO (+ evtl. .install/Patches) gehoeren ins
  AUR-Repo, NICHT der Quellcode.
- Erster Push legt das Paket automatisch an; der Name ist dann fuer
  deinen Account reserviert.
