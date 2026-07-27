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

# --- 1b) system libraries (distro-aware) ---
# PortAudio (microphone) + Qt xcb-cursor (otherwise Qt6 fails with
# "Could not load the Qt platform plugin xcb" on X11/non-KDE).
install_system_deps() {
    if [ ! -r /etc/os-release ]; then
        echo "-> Could not detect the distribution (no /etc/os-release)."
        return 0
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    local id="${ID:-}" like="${ID_LIKE:-}" installcmd="" pkgs="" mgr=""
    case " $id $like " in
        *debian*|*ubuntu*|*linuxmint*|*" pop "*|*" mint "*)
            mgr="apt"; installcmd="sudo apt-get install -y"
            pkgs="python3-venv python3-pip python3-dev portaudio19-dev libportaudio2 libxcb-cursor0 libxcb-xinerama0" ;;
        *fedora*|*rhel*|*" centos "*)
            mgr="dnf"; installcmd="sudo dnf install -y"
            pkgs="python3-devel portaudio-devel xcb-util-cursor" ;;
        *suse*|*opensuse*)
            mgr="zypper"; installcmd="sudo zypper install -y"
            pkgs="python3-devel portaudio-devel libportaudio2 libxcb-cursor0" ;;
        *arch*|*manjaro*|*cachyos*|*endeavouros*)
            mgr="pacman"; installcmd="sudo pacman -S --needed --noconfirm"
            pkgs="portaudio xcb-util-cursor" ;;
        *)
            echo "-> Unknown distribution '${PRETTY_NAME:-$id}'."
            echo "   If the app won't start or the microphone doesn't work,"
            echo "   install PortAudio and the Qt xcb-cursor library via your"
            echo "   package manager."
            return 0 ;;
    esac
    echo "-> Detected distribution: ${PRETTY_NAME:-$id} (package manager: $mgr)"
    echo "-> Recommended system libraries: $pkgs"
    if [ -t 0 ] && command -v sudo >/dev/null 2>&1; then
        printf "   Install them now via %s? [Y/n] " "$mgr"
        read -r answer
        case "$answer" in
            [Nn]*)
                echo "   Skipped. Install later with:"
                echo "     $installcmd $pkgs" ;;
            *)
                $installcmd $pkgs || \
                    echo "   (Some packages may already be present or need manual attention.)" ;;
        esac
    else
        echo "-> Running non-interactively, so not installed automatically."
        echo "   Run this once to be sure GUI + microphone work:"
        echo "     $installcmd $pkgs"
    fi
}
install_system_deps

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
echo "-> Installing dependencies (PyQt6, python-osc, SpeechRecognition, zeroconf) ..."
"$APP_DIR/venv/bin/pip" install --quiet PyQt6 python-osc SpeechRecognition zeroconf deepl setproctitle

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
# Canonical .desktop in ~/.config/OSC-DreamChatbox/desktop/, symlinked into
# the applications dir. Skipped if a system package (AUR) already provides it.
DESKTOP_STORE_DIR="$HOME/.config/OSC-DreamChatbox/desktop"
STORE_FILE="$DESKTOP_STORE_DIR/osc-dreamchatbox.desktop"
LINK_FILE="$DESKTOP_DIR/osc-dreamchatbox.desktop"

if [ -f "/usr/share/applications/osc-dreamchatbox.desktop" ] \
   || [ -f "/usr/local/share/applications/osc-dreamchatbox.desktop" ]; then
    echo "-> System desktop entry already present (AUR) - skipping."
else
    echo "-> Detected desktop environment: ${XDG_CURRENT_DESKTOP:-unknown}"

    # Install icon into the hicolor theme and reference by NAME (KDE/Wayland
    # taskbars often ignore absolute Icon= paths).
    ICON_THEME_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
    if [ -f "$APP_DIR/assets/icon.png" ]; then
        mkdir -p "$ICON_THEME_DIR"
        cp -f "$APP_DIR/assets/icon.png" "$ICON_THEME_DIR/osc-dreamchatbox.png"
    elif [ -f "$APP_DIR/icon.png" ]; then
        mkdir -p "$ICON_THEME_DIR"
        cp -f "$APP_DIR/icon.png" "$ICON_THEME_DIR/osc-dreamchatbox.png"
    fi

    mkdir -p "$DESKTOP_STORE_DIR" "$DESKTOP_DIR"
    # delete any old entry (symlink or real file) before adding the new one
    rm -f "$LINK_FILE" "$STORE_FILE" 2>/dev/null || true
    cat > "$STORE_FILE" <<DESK
[Desktop Entry]
Type=Application
Name=OSC DreamChatbox
GenericName=VRChat OSC Chatbox Companion
Comment=VRChat OSC chatbox companion for Linux
Exec=$BIN_DIR/osc-dreamchatbox
Icon=osc-dreamchatbox
Terminal=false
Categories=Utility;Network;Chat;
Keywords=VRChat;OSC;Chatbox;VR;
StartupNotify=true
StartupWMClass=osc-dreamchatbox
DESK
    chmod 755 "$STORE_FILE"
    ln -sf "$STORE_FILE" "$LINK_FILE"
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    gtk-update-icon-cache -f -t \
        "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
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
