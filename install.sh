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
# The canonical .desktop lives in ~/.config/OSC-DreamChatbox/desktop/ and is
# symlinked into the applications dir. Every freedesktop DE (KDE, GNOME, XFCE,
# LXQt, Cinnamon, MATE, Budgie, ...) reads the same location, so no real
# per-DE special casing is needed - we only report the detected DE.
DESKTOP_STORE_DIR="$HOME/.config/OSC-DreamChatbox/desktop"
STORE_FILE="$DESKTOP_STORE_DIR/osc-dreamchatbox.desktop"
LINK_FILE="$DESKTOP_DIR/osc-dreamchatbox.desktop"

if [ -f "/usr/share/applications/osc-dreamchatbox.desktop" ] \
   || [ -f "/usr/local/share/applications/osc-dreamchatbox.desktop" ]; then
    echo "-> System desktop entry already present (AUR) - skipping."
else
    echo "-> Detected desktop environment: ${XDG_CURRENT_DESKTOP:-unknown}"
    ICON_LINE=""
    if [ -f "$APP_DIR/assets/icon.png" ]; then
        ICON_LINE="Icon=$APP_DIR/assets/icon.png"
    elif [ -f "$APP_DIR/icon.png" ]; then
        ICON_LINE="Icon=$APP_DIR/icon.png"
    fi

    mkdir -p "$DESKTOP_STORE_DIR" "$DESKTOP_DIR"
    cat > "$STORE_FILE" <<DESK
[Desktop Entry]
Type=Application
Name=OSC DreamChatbox
GenericName=VRChat OSC Chatbox Companion
Comment=VRChat OSC chatbox companion for Linux
Exec=$BIN_DIR/osc-dreamchatbox
$ICON_LINE
Terminal=false
Categories=Utility;Network;Chat;
Keywords=VRChat;OSC;Chatbox;VR;
StartupNotify=true
StartupWMClass=osc-dreamchatbox
DESK
    chmod 755 "$STORE_FILE"
    ln -sf "$STORE_FILE" "$LINK_FILE"
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    echo "-> Desktop entry: $LINK_FILE -> $STORE_FILE"
fi

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
