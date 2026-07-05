#!/usr/bin/env bash
# OSC-DreamChatbox installer
# One-line install:
#   curl -sL https://raw.githubusercontent.com/yakuda-stack/OSC-DreamChatbox/main/install.sh | bash
set -e

REPO="https://github.com/yakuda-stack/OSC-DreamChatbox"
APP_DIR="$HOME/.local/share/OSC-DreamChatbox"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "==============================================="
echo "  OSC-DreamChatbox installer"
echo "==============================================="

# --- 1) check python ---
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install it first (e.g. sudo pacman -S python)."
    exit 1
fi

# --- 2) get the source ---
mkdir -p "$APP_DIR"
if command -v git >/dev/null 2>&1; then
    if [ -d "$APP_DIR/.git" ]; then
        echo "-> Updating existing installation ..."
        git -C "$APP_DIR" pull --ff-only
    else
        echo "-> Cloning $REPO ..."
        rm -rf "$APP_DIR"
        git clone --depth 1 "$REPO" "$APP_DIR"
    fi
else
    echo "-> git not found, downloading tarball ..."
    curl -sL "$REPO/archive/refs/heads/main.tar.gz" | tar xz -C "$APP_DIR" --strip-components=1
fi

# --- 3) virtual environment + dependencies ---
echo "-> Creating virtual environment ..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
echo "-> Installing dependencies (PyQt6, python-osc, SpeechRecognition) ..."
"$APP_DIR/venv/bin/pip" install --quiet PyQt6 python-osc SpeechRecognition

echo "-> Installing pyaudio (optional, for Speech to Text) ..."
if ! "$APP_DIR/venv/bin/pip" install --quiet pyaudio 2>/dev/null; then
    echo "   WARNING: pyaudio could not be built."
    echo "   Speech to Text will be unavailable until you install it, e.g.:"
    echo "     Arch:   sudo pacman -S portaudio  && $APP_DIR/venv/bin/pip install pyaudio"
    echo "     Debian: sudo apt install portaudio19-dev && $APP_DIR/venv/bin/pip install pyaudio"
fi

# --- 4) launcher command ---
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/osc-dreamchatbox" <<LAUNCH
#!/usr/bin/env bash
cd "$APP_DIR"
exec "$APP_DIR/venv/bin/python" "$APP_DIR/osc_dreamchatbox.py" "\$@"
LAUNCH
chmod +x "$BIN_DIR/osc-dreamchatbox"

# --- 5) desktop entry ---
mkdir -p "$DESKTOP_DIR"
ICON_LINE=""
[ -f "$APP_DIR/icon.png" ] && ICON_LINE="Icon=$APP_DIR/icon.png"
cat > "$DESKTOP_DIR/osc-dreamchatbox.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=OSC DreamChatbox
Comment=VRChat OSC chatbox companion
Exec=$BIN_DIR/osc-dreamchatbox
$ICON_LINE
Terminal=false
Categories=Utility;Network;
DESK
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo ""
echo "==============================================="
echo "  Done! Start it with:  osc-dreamchatbox"
echo "  (or from your application menu)"
echo "==============================================="
if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
    echo "NOTE: $BIN_DIR is not in your PATH."
    echo "      Add this to your ~/.bashrc or ~/.zshrc:"
    echo "      export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
echo "Don't forget: enable OSC in VRChat (Action Menu -> Options -> OSC)."
