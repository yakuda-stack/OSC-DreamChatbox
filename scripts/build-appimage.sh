#!/usr/bin/env bash
# Builds OSC-DreamChatbox.AppImage
# Run this on your Linux machine inside the repo:
#   ./build-appimage.sh
# Result: dist/OSC-DreamChatbox-<version>-x86_64.AppImage
set -e

# immer vom Repo-Root aus arbeiten (Script liegt in scripts/)
cd "$(dirname "$0")/.."

VERSION="1.0.0-alpha"
APP=OSC-DreamChatbox

echo "-> Preparing build venv ..."
python3 -m venv .build-venv
.build-venv/bin/pip install --quiet --upgrade pip
.build-venv/bin/pip install --quiet PyQt6 python-osc SpeechRecognition pyinstaller
.build-venv/bin/pip install --quiet pyaudio || \
    echo "   (pyaudio skipped - install portaudio to bundle Speech to Text)"

echo "-> Building single binary with PyInstaller ..."
.build-venv/bin/pyinstaller --noconfirm --clean --onefile --windowed \
    --name "$APP" \
    --hidden-import speech_recognition \
    --add-data "assets/icon.png:assets" \
    osc_dreamchatbox.py

echo "-> Assembling AppDir ..."
APPDIR="build/$APP.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp "dist/$APP" "$APPDIR/usr/bin/"
if [ -f assets/icon.png ]; then
    cp assets/icon.png "$APPDIR/$APP.png"
else
    # fallback 1x1 png so appimagetool doesn't complain
    printf '\x89PNG\r\n\x1a\n' > "$APPDIR/$APP.png" || true
fi
cat > "$APPDIR/$APP.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=OSC DreamChatbox
Exec=$APP
Icon=$APP
Categories=Utility;Network;
DESK
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/OSC-DreamChatbox" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

echo "-> Fetching appimagetool ..."
if [ ! -f appimagetool ]; then
    curl -sL -o appimagetool \
      "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x appimagetool
fi

echo "-> Building AppImage ..."
ARCH=x86_64 ./appimagetool --appimage-extract-and-run "$APPDIR" "dist/$APP-$VERSION-x86_64.AppImage"

echo ""
echo "Done: dist/$APP-$VERSION-x86_64.AppImage"
echo "Note: Speech to Text inside the AppImage still needs portaudio"
echo "installed on the target system (sudo pacman -S portaudio)."
