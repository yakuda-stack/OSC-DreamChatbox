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
# Version automatisch aus core/constants.py lesen (z.B. v1.0.6-alpha)
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

# FUSE-Workaround: appimagetool selbst ohne FUSE ausführen
export APPIMAGE_EXTRACT_AND_RUN=1

# 1b. Runtime besorgen — WICHTIG für FUSE 2 *und* FUSE 3
#
# Die Runtime ist der ausführbare Kopf jeder AppImage. Die alte aus
# AppImageKit lädt libfuse.so.2 per dlopen(). Ubuntu >= 22.04 und damit
# Linux Mint >= 21 liefern nur noch fuse3 aus — dort scheitert der Start
# mit "dlopen(): error loading libfuse.so.2", bevor auch nur eine Zeile
# Python läuft.
#
# type2-runtime ist statisch gegen musl+libfuse gelinkt und sucht sich
# zur Laufzeit ein passendes fusermount* im $PATH. Damit laufen dieselbe
# Datei auf fuse2- und fuse3-Systemen, ohne dass jemand libfuse2
# nachinstallieren muss.
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-${ARCH}"
RUNTIME="/tmp/appimage-runtime-${ARCH}"
if [ ! -s "$RUNTIME" ]; then
    echo "[Info] Lade statische AppImage-Runtime (fuse2+fuse3)..."
    wget -q "$RUNTIME_URL" -O "$RUNTIME" || {
        echo "FEHLER: Runtime konnte nicht geladen werden ($RUNTIME_URL)."
        exit 1
    }
fi
# Sanity-Check: bei einem 404 landet sonst eine HTML-Seite in der
# AppImage und das Ergebnis startet auf *keinem* System.
if ! head -c 4 "$RUNTIME" | grep -q "ELF"; then
    echo "FEHLER: $RUNTIME ist keine ELF-Datei — Download kaputt."
    rm -f "$RUNTIME"
    exit 1
fi
chmod +x "$RUNTIME"

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
# Plugin-Store-Katalog (core/constants.py: STORE_SOURCES_FILE)
if [ -d config ]; then cp -r config "$LIB/"; fi
# Python-Cache nicht mitschleppen
find "$LIB" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# Wrapper-Script in /usr/bin
cat > "$BUILD_DIR/usr/bin/osc-dreamchatbox" << 'WRAPPER'
#!/bin/bash
cd "$(dirname "$0")/../lib/osc-dreamchatbox"
# AppRun sucht den passenden Interpreter aus (siehe dort), Fallback python3
exec "${DREAMCHATBOX_PYTHON:-python3}" osc_dreamchatbox.py "$@"
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
    PyQt6 python-osc SpeechRecognition zeroconf deepl setproctitle 2>/dev/null || \
    pip install --break-system-packages --target="$BUILD_DIR/usr/lib/python3" \
    PyQt6 python-osc SpeechRecognition zeroconf deepl setproctitle || \
    echo "[Warn] Abhängigkeiten konnten nicht gebundelt werden — müssen auf dem System vorhanden sein."
pip install --target="$BUILD_DIR/usr/lib/python3" pyaudio 2>/dev/null || \
    pip install --break-system-packages --target="$BUILD_DIR/usr/lib/python3" pyaudio 2>/dev/null || \
    echo "[Info] pyaudio nicht gebundelt — Speech to Text braucht es vom System (pacman -S python-pyaudio)."

# Welche Python-Version brauchen die gebundelten Pakete?
#
# PyQt6 selbst ist abi3 (läuft auf jedem Python 3.x), aber PyQt6.sip,
# zeroconf & Co. werden pro Python-Minor-Version kompiliert. pip baut
# gegen den Python DIESER Maschine — auf einem System mit anderer
# Minor-Version scheitert dann schon "import PyQt6.QtWidgets".
PYVER="$(find "$BUILD_DIR/usr/lib/python3" -name '*.so' \
    | grep -oE 'cpython-3[0-9]+' | sort -u | grep -oE '3[0-9]+' | head -1)"
if [ -n "$PYVER" ]; then
    PYVER="3.${PYVER#3}"
    echo "$PYVER" > "$BUILD_DIR/usr/lib/osc-dreamchatbox/.python-version"
    echo "[Info] Gebundelte C-Module sind für Python $PYVER gebaut."
    echo "       Auf Systemen mit anderer Python-Minor-Version wird ein"
    echo "       passendes python$PYVER gesucht (siehe AppRun)."
fi

# AppRun Script
cat > "$BUILD_DIR/AppRun" << 'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export PYTHONPATH="$HERE/usr/lib/python3:$PYTHONPATH"
export PATH="$HERE/usr/bin:$PATH"

# Diese AppImage bundelt die Python-Pakete, benutzt aber den python3 des
# Systems. Fehlt der oder fehlen Qt-Systembibliotheken, ist die Qt-
# Fehlermeldung ("could not load the Qt platform plugin xcb") für die
# meisten Leute nicht zu gebrauchen — deshalb hier vorher klartext.
if ! command -v python3 >/dev/null 2>&1; then
    echo "OSC-DreamChatbox: python3 nicht gefunden." >&2
    echo "  Debian/Ubuntu/Mint:  sudo apt install python3" >&2
    echo "  Fedora:              sudo dnf install python3" >&2
    exit 1
fi

# Die gebundelten C-Module (PyQt6.sip, zeroconf) sind an eine
# Python-Minor-Version gebunden. Passt die des Systems nicht, erst nach
# einem passenden pythonX.Y suchen — sonst gibt es eine verständliche
# Meldung statt eines ImportError-Tracebacks.
NEED="$(cat "$HERE/usr/lib/osc-dreamchatbox/.python-version" 2>/dev/null)"
HAVE="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
DREAMCHATBOX_PYTHON="python3"
if [ -n "$NEED" ] && [ "$NEED" != "$HAVE" ]; then
    if command -v "python$NEED" >/dev/null 2>&1; then
        DREAMCHATBOX_PYTHON="python$NEED"
    else
        echo "OSC-DreamChatbox: diese AppImage wurde für Python $NEED gebaut," >&2
        echo "  auf diesem System läuft Python $HAVE." >&2
        echo "  Die mitgelieferten Qt-Module laden damit nicht." >&2
        echo "  Abhilfe:  sudo apt install python$NEED" >&2
        echo "  oder die AppImage auf einem System mit Python $HAVE bauen." >&2
        exit 1
    fi
fi
export DREAMCHATBOX_PYTHON

# Bibliotheken, die Qt6 braucht und die auf Mint/Ubuntu NICHT
# standardmäßig installiert sind. libxcb-cursor0 ist der Klassiker.
missing=""
if command -v ldconfig >/dev/null 2>&1; then
    libs="$(ldconfig -p 2>/dev/null)"
    case "$libs" in *libxcb-cursor.so.0*) ;; *) missing="$missing libxcb-cursor0";; esac
    case "$libs" in *libxkbcommon-x11.so.0*) ;; *) missing="$missing libxkbcommon-x11-0";; esac
    case "$libs" in *libEGL.so.1*) ;; *) missing="$missing libegl1";; esac
fi
if [ -n "$missing" ]; then
    echo "OSC-DreamChatbox: es fehlen Systembibliotheken für Qt6:$missing" >&2
    echo "  Debian/Ubuntu/Mint:  sudo apt install$missing" >&2
    echo "  (Paketnamen können je nach Distribution abweichen.)" >&2
    echo "Versuche trotzdem zu starten ..." >&2
fi

exec "$HERE/usr/bin/osc-dreamchatbox" "$@"
APPRUN
chmod +x "$BUILD_DIR/AppRun"

# 6. AppImage bauen (mit der statischen Runtime von oben)
echo "[5/5] Baue AppImage..."
ARCH="$ARCH" "$APPIMAGETOOL" --runtime-file "$RUNTIME" "$BUILD_DIR" "$OUT"

# 7. Gegenprobe: die fertige Datei darf libfuse.so.2 nicht mehr brauchen.
# Ohne diesen Check merkt man den Rückfall auf die alte Runtime erst,
# wenn sich der erste Mint-Nutzer meldet.
echo ""
if head -c 400000 "$OUT" | strings | grep -q "libfuse\.so\.2"; then
    echo "WARNUNG: Die AppImage verweist noch auf libfuse.so.2 —"
    echo "         die statische Runtime wurde offenbar nicht benutzt."
    echo "         Auf Mint/Ubuntu >= 22.04 startet sie so nicht."
else
    echo "✔ Runtime ist statisch (läuft mit fuse2 UND fuse3)"
fi

echo "✔ Fertig: $OUT"
echo "   Zum Starten: chmod +x $OUT && ./$OUT"
echo "   Ohne FUSE testen: APPIMAGE_EXTRACT_AND_RUN=1 $OUT"
