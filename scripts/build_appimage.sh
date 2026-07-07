#!/bin/bash
# OSC-DreamChatbox — AppImage Builder
# Benötigt: python3, pip (appimagetool wird automatisch geladen)
# Verwendung: bash build_appimage.sh

set -e

# immer vom Repo-Root aus arbeiten (Script liegt in scripts/)
cd "$(dirname "$0")/.."

APP="OSC-DreamChatbox"
VERSION="1.0.0-alpha"
ARCH="x86_64"
BUILD_DIR="$(pwd)/AppDir"
OUT="$(pwd)/${APP}-${VERSION}-${ARCH}.AppImage"

echo "=== OSC-DreamChatbox AppImage Builder ==="
echo "Version: $VERSION"
echo ""

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
mkdir -p "$BUILD_DIR/usr/lib/osc-dreamchatbox"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps"

# 3. Programmdateien kopieren
echo "[2/5] Kopiere Programmdateien..."
cp osc_dreamchatbox.py "$BUILD_DIR/usr/lib/osc-dreamchatbox/"
cp -r core ui assets "$BUILD_DIR/usr/lib/osc-dreamchatbox/"
find "$BUILD_DIR/usr/lib/osc-dreamchatbox" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

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
    PyQt6 python-osc SpeechRecognition 2>/dev/null || \
    pip install --break-system-packages --target="$BUILD_DIR/usr/lib/python3" \
    PyQt6 python-osc SpeechRecognition || \
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
