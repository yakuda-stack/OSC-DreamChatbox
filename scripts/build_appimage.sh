#!/bin/bash
# OSC-DreamChatbox — AppImage Builder (bundled source)
# Benötigt: python3, pip (appimagetool wird automatisch geladen)
# Verwendung:  bash scripts/build_appimage.sh   (egal von wo aus)
#
# Ergebnis:    build/OSC-DreamChatbox-<version>-x86_64.AppImage
#              build/ wird bei JEDEM Lauf komplett geleert — dort liegt
#              danach nur die frische AppImage, nie ein alter Stand.

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
# Version automatisch aus core/constants.py lesen (VERSION = "v1.4.8" -> 1.4.8).
# ^ am Anfang: sonst passt auch PLUGIN_API_VERSION = "..." o. Ae.
VERSION="$(grep -oP '^VERSION\s*=\s*"v?\K[^"]+' core/constants.py)"
if [ -z "$VERSION" ]; then
    echo "FEHLER: VERSION in core/constants.py nicht gefunden."
    exit 1
fi
ARCH="x86_64"
OUT_DIR="$(pwd)/build"                              # Ziel fuer die fertige AppImage
BUILD_DIR="$OUT_DIR/AppDir"                         # Zwischenstand, wird am Ende geloescht
OUT="$OUT_DIR/${APP}-${VERSION}-${ARCH}.AppImage"
LIB="$BUILD_DIR/usr/lib/osc-dreamchatbox"

echo "=== OSC-DreamChatbox AppImage Builder ==="
echo "Version: $VERSION"
echo ""

# Sanity-Check: neue Projektstruktur vorhanden?
for f in osc_dreamchatbox.py core/constants.py ui/mainwindow.py assets/icon.png \
         CHANGELOG.md HIGHLIGHTS.md; do
    if [ ! -e "$f" ]; then
        echo "FEHLER: $f nicht gefunden — bitte aus dem Projekt-Root bauen."
        exit 1
    fi
done

# 0. build/ frisch anlegen
echo "[0/5] Leere build/ ..."
rm -rf "$OUT_DIR"
rm -rf "$(pwd)/AppDir"          # Überbleibsel vom alten Build-Ort im Projekt-Root
mkdir -p "$OUT_DIR"

# 1. appimagetool besorgen
#
# Immer das aktuelle aus github.com/AppImage/appimagetool — NICHT das alte
# aus AppImageKit (wird nicht mehr gepflegt) und nicht ein zufällig
# installiertes: das aktuelle bringt zsyncmake selbst mit, erzeugt also
# die .zsync-Datei für Delta-Updates (siehe Schritt 6) ohne dass zsync auf
# dem System installiert sein muss. Wird einmal nach /tmp geladen.
# Eigenes Tool erzwingen: APPIMAGETOOL=/pfad/zum/appimagetool bash ...
if [ -z "${APPIMAGETOOL:-}" ]; then
    APPIMAGETOOL="/tmp/appimagetool-new-${ARCH}"
    if [ ! -s "$APPIMAGETOOL" ]; then
        echo "[Info] Lade appimagetool (github.com/AppImage/appimagetool)..."
        wget -q "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage" \
            -O "$APPIMAGETOOL" || {
            echo "FEHLER: appimagetool konnte nicht geladen werden."
            rm -f "$APPIMAGETOOL"
            exit 1
        }
    fi
    if ! head -c 4 "$APPIMAGETOOL" | grep -q "ELF"; then
        echo "FEHLER: $APPIMAGETOOL ist keine ELF-Datei — Download kaputt."
        rm -f "$APPIMAGETOOL"
        exit 1
    fi
    chmod +x "$APPIMAGETOOL"
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
# Optionen -> General: Highlights- und Changelog-Knopf (ui/docviewer.py)
cp CHANGELOG.md HIGHLIGHTS.md "$LIB/"

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
Categories=Network;Chat;
StartupWMClass=osc-dreamchatbox
EOF

cp "$BUILD_DIR/usr/share/applications/osc-dreamchatbox.desktop" "$BUILD_DIR/osc-dreamchatbox.desktop"

# 5. Python-Abhängigkeiten ins AppDir bundeln
echo "[4/5] Bundele Python-Abhängigkeiten..."
#
# PyQt6 selbst ist abi3 (läuft auf jedem Python 3.x), aber PyQt6.sip,
# zeroconf, setproctitle & Co. sind pro Python-Minor-Version kompiliert.
# Früher wurde nur für den Python DIESER Maschine gebundelt (Arch: 3.14)
# — auf Ubuntu 24.04 / Mint 22 (Python 3.12) lud dann PyQt6 nicht.
#
# Jetzt: für JEDE Version in PYVERS fertige Wheels laden (geht ohne dass
# der Interpreter installiert ist) und alles in EINEN Ordner legen. Die
# .so-Dateien tragen die Version im Namen (sip.cpython-312-...so,
# sip.cpython-314-...so) — Python lädt automatisch die passende, die
# reinen .py-Dateien sind für alle Versionen gleich. Kostet ~10 MB extra,
# die Qt-Bibliotheken selbst liegen nur einmal drin.
#
# 3.12 ist das Minimum (f-Strings mit Backslash in ui/pages/*).
# Andere Liste:  DCB_PYVERS="3.12 3.13" bash scripts/build_appimage.sh
PYVERS="${DCB_PYVERS:-3.12 3.13 3.14}"
DEPS=(PyQt6 python-osc SpeechRecognition zeroconf deepl setproctitle)
# --platform: pip nimmt dann NUR Wheels mit genau diesen Tags. Obergrenze
# glibc 2.35 hält die AppImage auf älteren Distros lauffähig.
PLAT_ARGS=()
for g in 17 24 27 28 31 34 35; do
    PLAT_ARGS+=(--platform "manylinux_2_${g}_${ARCH}")
done
PLAT_ARGS+=(--platform "manylinux2014_${ARCH}")

if python3 -m pip --version >/dev/null 2>&1; then
    PIP=(python3 -m pip)
else
    PIP=(pip)
fi

SITE="$BUILD_DIR/usr/lib/python3"
STAGE="$OUT_DIR/pystage"
mkdir -p "$SITE"
DONE_VERS=""
for V in $PYVERS; do
    echo "      → Python $V"
    rm -rf "$STAGE"
    XARGS=(--quiet --no-compile --target="$STAGE" --python-version "$V"
           --implementation cp --only-binary=:all: "${PLAT_ARGS[@]}")
    if "${PIP[@]}" install "${XARGS[@]}" "${DEPS[@]}" 2>"$OUT_DIR/pip-$V.log" \
       || "${PIP[@]}" install --break-system-packages "${XARGS[@]}" \
            "${DEPS[@]}" 2>>"$OUT_DIR/pip-$V.log"; then
        # pip wertet Marker wie python_version>="3.13" mit dem LAUFENDEN
        # Python aus, nicht mit --python-version — und manche pip-Versionen
        # prüfen auch Requires-Python gegen den laufenden. SpeechRecognition
        # braucht ab 3.13 diese Backports (aifc/audioop/chunk wurden aus der
        # Standardbibliothek entfernt), also gezielt ohne Abhängigkeitsprüfung.
        case "$V" in
            3.12) ;;
            *) "${PIP[@]}" install "${XARGS[@]}" --no-deps --ignore-requires-python \
                   standard-aifc standard-chunk audioop-lts 2>>"$OUT_DIR/pip-$V.log" \
               || "${PIP[@]}" install --break-system-packages "${XARGS[@]}" \
                   --no-deps --ignore-requires-python \
                   standard-aifc standard-chunk audioop-lts 2>>"$OUT_DIR/pip-$V.log" \
               || echo "[Warn] aifc/audioop-Backports für $V fehlen — Speech to Text könnte dort fehlen." ;;
        esac
        cp -a "$STAGE/." "$SITE/"
        DONE_VERS="$DONE_VERS $V"
        rm -f "$OUT_DIR/pip-$V.log"
    else
        echo "[Warn] Python $V übersprungen — keine passenden Wheels (Log: build/pip-$V.log)."
    fi
done
rm -rf "$STAGE"
DONE_VERS="${DONE_VERS# }"

if [ -z "$DONE_VERS" ]; then
    echo "FEHLER: Für keine Python-Version konnten Abhängigkeiten gebundelt werden."
    exit 1
fi
# pyaudio hat keine Linux-Wheels: wird (wenn überhaupt) nur für den
# Python dieser Maschine gebaut. Speech to Text geht sonst über
# sounddevice bzw. das pyaudio des Systems.
"${PIP[@]}" install --quiet --no-compile --target="$SITE" pyaudio 2>/dev/null || \
    "${PIP[@]}" install --quiet --no-compile --break-system-packages --target="$SITE" pyaudio 2>/dev/null || \
    echo "[Info] pyaudio nicht gebundelt — Speech to Text braucht es vom System (python3-pyaudio / python-pyaudio)."
find "$SITE" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# Liste der unterstützten Versionen für AppRun (eine Zeile, Leerzeichen)
echo "$DONE_VERS" > "$LIB/.python-versions"
echo "[Info] Gebundelt für Python: $DONE_VERS"

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

# Die gebundelten C-Module (PyQt6.sip, zeroconf, ...) liegen für mehrere
# Python-Versionen bei (.python-versions, z. B. "3.12 3.13 3.14").
# Erst python3 des Systems probieren, sonst ein passendes pythonX.Y
# (neueste zuerst) — sonst eine verständliche Meldung statt Traceback.
SUPPORTED="$(cat "$HERE/usr/lib/osc-dreamchatbox/.python-versions" 2>/dev/null)"
# ältere AppImages hatten nur eine Version in .python-version
[ -z "$SUPPORTED" ] && SUPPORTED="$(cat "$HERE/usr/lib/osc-dreamchatbox/.python-version" 2>/dev/null)"
pyver() { "$1" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null; }
HAVE="$(pyver python3)"
DREAMCHATBOX_PYTHON="python3"
if [ -n "$SUPPORTED" ]; then
    case " $SUPPORTED " in
        *" $HAVE "*) ;;
        *)
            DREAMCHATBOX_PYTHON=""
            for V in $(printf '%s\n' $SUPPORTED | sort -rV); do
                if command -v "python$V" >/dev/null 2>&1 \
                   && [ "$(pyver "python$V")" = "$V" ]; then
                    DREAMCHATBOX_PYTHON="python$V"
                    break
                fi
            done
            if [ -z "$DREAMCHATBOX_PYTHON" ]; then
                echo "OSC-DreamChatbox: diese AppImage läuft mit Python $SUPPORTED," >&2
                echo "  auf diesem System ist python3 = $HAVE." >&2
                echo "  This AppImage needs Python $SUPPORTED (you have $HAVE)." >&2
                echo "  Abhilfe / Fix:  eine davon installieren, z. B. python3.12" >&2
                exit 1
            fi
            ;;
    esac
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
#
# Update-Information für Delta-Updates (zsync). Sie wird IN die AppImage
# geschrieben und sagt Update-Tools (AppImageUpdate, AppImageLauncher,
# AM, AppManager, Gear Lever ...), wo die neue Version liegt:
#   gh-releases-zsync | Benutzer | Repo | latest | Dateimuster
# "latest" = das neueste GitHub-Release, das KEIN Pre-release ist.
# Daneben entsteht OSC-DreamChatbox-<version>-x86_64.AppImage.zsync: die
# Prüfsummen der Blöcke. Ein Tool vergleicht sie mit der alten AppImage
# und lädt nur die Blöcke, die sich geändert haben.
# BEIDE Dateien gehören ins GitHub-Release.
# Ohne zsync bauen: DCB_NO_ZSYNC=1 bash scripts/build_appimage.sh
UPDATE_INFO="gh-releases-zsync|yakuda-stack|OSC-DreamChatbox|latest|OSC-DreamChatbox-*${ARCH}.AppImage.zsync"
UPDATE_ARGS=()
if [ -z "${DCB_NO_ZSYNC:-}" ]; then
    UPDATE_ARGS=(-u "$UPDATE_INFO")
fi
echo "[5/5] Baue AppImage..."
# im build/-Ordner aufrufen: appimagetool legt die .zsync im AKTUELLEN
# Ordner ab, nicht neben der AppImage
(cd "$OUT_DIR" && ARCH="$ARCH" "$APPIMAGETOOL" --runtime-file "$RUNTIME" \
    "${UPDATE_ARGS[@]}" "$BUILD_DIR" "$OUT")

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

# 7b. Delta-Updates: .zsync da, Update-Info wirklich in der Datei?
if [ -z "${DCB_NO_ZSYNC:-}" ]; then
    # ohne APPIMAGE_EXTRACT_AND_RUN: damit würde die Runtime auspacken und
    # die App mit diesem Argument starten, statt es selbst zu beantworten
    EMBEDDED="$(env -u APPIMAGE_EXTRACT_AND_RUN "$OUT" \
        --appimage-updateinformation 2>/dev/null || true)"
    if [ "$EMBEDDED" = "$UPDATE_INFO" ]; then
        echo "✔ Update-Info eingebettet: $EMBEDDED"
    else
        echo "WARNUNG: Update-Info fehlt in der AppImage (gelesen: '$EMBEDDED')."
    fi
    if [ -s "$OUT.zsync" ]; then
        echo "✔ Delta-Update-Datei: build/$(basename "$OUT").zsync"
    else
        echo "WARNUNG: keine .zsync erzeugt — Delta-Updates gehen so nicht."
        echo "         Eigenes appimagetool benutzt? Dann zsync installieren"
        echo "         (pacman -S zsync) oder APPIMAGETOOL leer lassen."
    fi
fi

# 8. AppDir wegräumen — in build/ bleiben die AppImage und ihre .zsync
rm -rf "$BUILD_DIR"

echo "✔ Fertig: build/$(basename "$OUT")"
if [ -s "$OUT.zsync" ]; then
    echo "   Ins GitHub-Release: $(basename "$OUT") UND $(basename "$OUT").zsync"
fi
echo "   Zum Starten: chmod +x \"$OUT\" && \"$OUT\""
echo "   Ohne FUSE testen: APPIMAGE_EXTRACT_AND_RUN=1 \"$OUT\""
