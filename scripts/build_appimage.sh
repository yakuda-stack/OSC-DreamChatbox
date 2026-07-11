#!/bin/bash
# OSC-DreamChatbox — AppImage Builder (bundled source)
# Benötigt: python3, pip (appimagetool wird automatisch geladen)
# Verwendung:  bash build_appimage.sh   (egal ob das Skript im
# Projekt-Root oder in scripts/ liegt und von wo du es aufrufst)

set -e

# immer vom Projekt-Root aus arbeiten: erst ins Skript-Verzeichnis,
# dann hochgehen bis core/constants.py gefunden ist
cd "$(dirname "$0")"
for _ in 1 2 3; do
    [ -f core/constants.py ] && break
    cd ..
done
if [ ! -f core/constants.py ]; then
    echo "FEHLER: Projekt-Root nicht gefunden (core/constants.py fehlt)."
    echo "        Bitte das Skript in den OSC-DreamChatbox-Ordner legen."
    exit 1
fi

APP="OSC-DreamChatbox"
# Version automatisch aus core/constants.py lesen (z.B. v1.0.2-alpha)
VERSION="$(grep -o 'VERSION = "[^"]*"' core/constants.py | cut -d'"' -f2)"
VERSION="${VERSION#v}"
ARCH="x86_64"
BUILD_DIR="$(pwd)/AppDir"
OUT="$(pwd)/${APP}-${VERSION}-${ARCH}.AppImage"
LIB="$BUILD_DIR/usr/lib/osc-dreamchatbox"

echo "=== OSC-DreamChatbox AppImage Builder ==="
echo "Version: $VERSION"
echo ""

# Sanity-Check: neue Projektstruktur vorhanden?
for f in osc_dreamchatbox.py core/constants.py ui/mainwindow.py assets/icon.png; do
    if [ ! -e "$f" ]; then
        echo "FEHLER: $f nicht gefunden — bitte aus dem Projekt-Root bauen."
        exit 1
    fi
done

# 1. appimagetool prüfen
if ! command -v appimagetool &>/dev/null; then
    echo "[Info] appimagetool nicht gefunden — lade herunter..."
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
        -O /tmp/appimagetool
    chmod +x /tmp/appimagetool
    APPIMAGETOOL="/tmp/appimagetool"
else
    APPIMAGETOOL="appimagetool"
fi

# FUSE-Workaround: appimagetool ohne FUSE ausführen
export APPIMAGE_EXTRACT_AND_RUN=1

# 2. AppDir Struktur anlegen
echo "[1/5] Erstelle AppDir Struktur..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$LIB"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps"

# 3. Programmdateien kopieren (neue Struktur: core/ + ui/ + assets/)
echo "[2/5] Kopiere Programmdateien..."
cp osc_dreamchatbox.py "$LIB/"
cp -r core ui "$LIB/"
mkdir -p "$LIB/assets"
cp assets/icon.png "$LIB/assets/"
# Python-Cache nicht mitschleppen
find "$LIB" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# Wrapper-Script in /usr/bin
cat > "$BUILD_DIR/usr/bin/osc-dreamchatbox" << 'WRAPPER'
#!/bin/bash
cd "$(dirname "$0")/../lib/osc-dreamchatbox"
exec python3 osc_dreamchatbox.py "$@"
WRAPPER
chmod +x "$BUILD_DIR/usr/bin/osc-dreamchatbox"

# 4. Icon und Desktop-Datei
echo "[3/5] Setze Icon und Desktop-Eintrag..."
cp assets/icon.png "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps/osc-dreamchatbox.png"
cp assets/icon.png "$BUILD_DIR/osc-dreamchatbox.png"

cat > "$BUILD_DIR/usr/share/applications/osc-dreamchatbox.desktop" << EOF
[Desktop Entry]
Name=OSC DreamChatbox
Comment=VRChat OSC chatbox companion
Exec=osc-dreamchatbox
Icon=osc-dreamchatbox
Terminal=false
Type=Application
Categories=Utility;Network;
StartupWMClass=osc-dreamchatbox
EOF

cp "$BUILD_DIR/usr/share/applications/osc-dreamchatbox.desktop" "$BUILD_DIR/osc-dreamchatbox.desktop"

# 5. Python-Abhängigkeiten ins AppDir bundeln
echo "[4/5] Bundele Python-Abhängigkeiten..."
mkdir -p "$BUILD_DIR/usr/lib/python3"
pip install --target="$BUILD_DIR/usr/lib/python3" \
    PyQt6 python-osc SpeechRecognition zeroconf deepl 2>/dev/null || \
    pip install --break-system-packages --target="$BUILD_DIR/usr/lib/python3" \
    PyQt6 python-osc SpeechRecognition zeroconf deepl || \
    echo "[Warn] Abhängigkeiten konnten nicht gebundelt werden — müssen auf dem System vorhanden sein."
pip install --target="$BUILD_DIR/usr/lib/python3" pyaudio 2>/dev/null || \
    pip install --break-system-packages --target="$BUILD_DIR/usr/lib/python3" pyaudio 2>/dev/null || \
    echo "[Info] pyaudio nicht gebundelt — Speech to Text braucht es vom System (pacman -S python-pyaudio)."

# AppRun Script
cat > "$BUILD_DIR/AppRun" << 'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export PYTHONPATH="$HERE/usr/lib/python3:$PYTHONPATH"
export PATH="$HERE/usr/bin:$PATH"
exec "$HERE/usr/bin/osc-dreamchatbox" "$@"
APPRUN
chmod +x "$BUILD_DIR/AppRun"

# 6. AppImage bauen
echo "[5/5] Baue AppImage..."
ARCH=x86_64 "$APPIMAGETOOL" "$BUILD_DIR" "$OUT"

echo ""
echo "✔ Fertig: $OUT"
echo "   Zum Starten: chmod +x $OUT && ./$OUT"
