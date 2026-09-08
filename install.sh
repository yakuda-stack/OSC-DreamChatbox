#!/usr/bin/env bash
# OSC-DreamChatbox installer
# One-line install:
#   curl -sL https://raw.githubusercontent.com/yakuda-stack/OSC-DreamChatbox/main/install.sh | bash
#
# Environment variables:
#   DREAMCHATBOX_SKIP_SYSDEPS=1   don't touch system packages at all
#   DREAMCHATBOX_ASSUME_YES=1     install system packages without asking
set -e

REPO="https://github.com/yakuda-stack/OSC-DreamChatbox"
APP_DIR="$HOME/.local/share/OSC-DreamChatbox"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

SKIP_SYSDEPS="${DREAMCHATBOX_SKIP_SYSDEPS:-0}"
ASSUME_YES="${DREAMCHATBOX_ASSUME_YES:-0}"

# filled in by detect_distro()
PKG_MGR=""
PKG_INSTALL=""
PKG_LIST=""

echo "==============================================="
echo "  OSC-DreamChatbox installer"
echo "==============================================="

# --- 1) check python ---
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install it first (e.g. sudo pacman -S python)."
    exit 1
fi

# ---------------------------------------------------------------------------
# system libraries
#
# Qt 6.5+ needs a handful of xcb helper libraries that most distributions do
# NOT install by default. Without them Qt aborts before the first window with
#   "From 6.5.0, xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb
#    platform plugin"
# which nobody can act on without googling. So: install them up front, and
# verify afterwards that they actually resolve.
# ---------------------------------------------------------------------------
detect_distro() {
    if [ ! -r /etc/os-release ]; then
        echo "-> Could not detect the distribution (no /etc/os-release)."
        return 1
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    local id="${ID:-}" like="${ID_LIKE:-}"
    case " $id $like " in
        *debian*|*ubuntu*|*linuxmint*|*" pop "*|*" mint "*)
            PKG_MGR="apt"
            PKG_INSTALL="apt-get install -y"
            PKG_LIST="python3-venv python3-pip python3-dev \
portaudio19-dev libportaudio2 \
libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-xkb1 \
libxkbcommon-x11-0 libegl1" ;;
        *fedora*|*rhel*|*" centos "*)
            PKG_MGR="dnf"
            PKG_INSTALL="dnf install -y"
            PKG_LIST="python3-devel portaudio-devel \
xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms \
xcb-util-renderutil libxkbcommon-x11 libglvnd-egl" ;;
        *suse*)
            PKG_MGR="zypper"
            PKG_INSTALL="zypper install -y"
            PKG_LIST="python3-devel portaudio-devel libportaudio2 \
libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
libxcb-render-util0 libxkbcommon-x11-0 libEGL1" ;;
        *arch*|*manjaro*|*cachyos*|*endeavouros*)
            PKG_MGR="pacman"
            PKG_INSTALL="pacman -S --needed --noconfirm"
            PKG_LIST="portaudio xcb-util-cursor xcb-util-wm xcb-util-image \
xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11" ;;
        *)
            echo "-> Unknown distribution '${PRETTY_NAME:-$id}'."
            return 1 ;;
    esac
    echo "-> Detected distribution: ${PRETTY_NAME:-$id} (package manager: $PKG_MGR)"
    return 0
}

# How do we get root? Not everyone has sudo, and in a container we may
# already BE root.
root_prefix() {
    if [ "$(id -u)" = "0" ]; then
        echo ""
    elif command -v sudo >/dev/null 2>&1; then
        echo "sudo"
    else
        echo "NONE"
    fi
}

# Ask the user, even when the script itself arrived through a pipe.
#
# THIS is what used to break: with "curl -sL ... | bash" stdin is the pipe,
# so [ -t 0 ] was never true and the whole dependency install was silently
# skipped - on exactly the install path the README recommends. /dev/tty is
# still the terminal in that case, so ask there instead.
confirm() {
    local prompt="$1" answer=""
    [ "$ASSUME_YES" = "1" ] && return 0
    if [ -r /dev/tty ] && [ -t 1 ]; then
        printf "%s [Y/n] " "$prompt" > /dev/tty
        read -r answer < /dev/tty || answer=""
    elif [ -t 0 ]; then
        printf "%s [Y/n] " "$prompt"
        read -r answer || answer=""
    else
        # genuinely no terminal (CI, docker build): installing is the more
        # useful default for an installer - skipping only moves the failure
        # to the user's first launch
        echo "-> No terminal available, installing system libraries by default."
        echo "   (set DREAMCHATBOX_SKIP_SYSDEPS=1 to prevent this)"
        return 0
    fi
    case "$answer" in
        [Nn]*) return 1 ;;
        *)     return 0 ;;
    esac
}

install_system_deps() {
    if [ "$SKIP_SYSDEPS" = "1" ]; then
        echo "-> DREAMCHATBOX_SKIP_SYSDEPS=1, skipping system libraries."
        return 0
    fi
    if ! detect_distro; then
        echo "   If the app won't start or the microphone doesn't work, install"
        echo "   PortAudio plus the Qt xcb helper libraries (xcb-util-cursor,"
        echo "   xcb-util-wm, xcb-util-image, xcb-util-keysyms,"
        echo "   xcb-util-renderutil, libxkbcommon-x11) via your package manager."
        return 0
    fi

    local sudo_cmd
    sudo_cmd="$(root_prefix)"
    if [ "$sudo_cmd" = "NONE" ]; then
        echo "-> No sudo and not running as root. Please install manually:"
        echo "     $PKG_INSTALL $PKG_LIST"
        return 0
    fi

    echo "-> Required system libraries:"
    echo "     $(echo "$PKG_LIST" | tr -s ' \\')"
    if confirm "   Install them now via $PKG_MGR?"; then
        # shellcheck disable=SC2086
        $sudo_cmd $PKG_INSTALL $PKG_LIST || \
            echo "   (Some packages may already be present or need manual attention.)"
    else
        echo "   Skipped. Install later with:"
        echo "     $sudo_cmd $PKG_INSTALL $PKG_LIST"
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
if ! python3 -m venv "$APP_DIR/venv" 2>/tmp/dreamchatbox-venv.log; then
    cat /tmp/dreamchatbox-venv.log >&2
    echo "" >&2
    echo "ERROR: could not create the virtual environment." >&2
    echo "  Debian/Ubuntu/Mint:  sudo apt install python3-venv" >&2
    echo "  Fedora:              sudo dnf install python3-virtualenv" >&2
    exit 1
fi
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

# ---------------------------------------------------------------------------
# 3b) verify the Qt platform plugin can actually load
#
# ldd on libqxcb.so lists every missing soname without needing a display, so
# this works over SSH too. Catching it here turns a cryptic Qt abort on first
# launch into one concrete apt/pacman line.
# ---------------------------------------------------------------------------
soname_key() {
    case "$1" in
        libxcb-cursor.so*)      echo cursor ;;
        libxcb-icccm.so*)       echo icccm ;;
        libxcb-image.so*)       echo image ;;
        libxcb-keysyms.so*)     echo keysyms ;;
        libxcb-render-util.so*) echo renderutil ;;
        libxcb-xinerama.so*)    echo xinerama ;;
        libxcb-shape.so*)       echo shape ;;
        libxcb-xkb.so*)         echo xcbxkb ;;
        libxkbcommon-x11.so*)   echo xkbx11 ;;
        libxkbcommon.so*)       echo xkb ;;
        libEGL.so*)             echo egl ;;
        libGL.so*)              echo gl ;;
        *)                      echo "" ;;
    esac
}

pkg_for_key() {
    case "$PKG_MGR" in
        apt) case "$1" in
                cursor) echo libxcb-cursor0 ;; icccm) echo libxcb-icccm4 ;;
                image) echo libxcb-image0 ;; keysyms) echo libxcb-keysyms1 ;;
                renderutil) echo libxcb-render-util0 ;;
                xinerama) echo libxcb-xinerama0 ;; shape) echo libxcb-shape0 ;;
                xcbxkb) echo libxcb-xkb1 ;; xkbx11) echo libxkbcommon-x11-0 ;;
                xkb) echo libxkbcommon0 ;; egl) echo libegl1 ;; gl) echo libgl1 ;;
             esac ;;
        pacman) case "$1" in
                cursor) echo xcb-util-cursor ;; icccm) echo xcb-util-wm ;;
                image) echo xcb-util-image ;; keysyms) echo xcb-util-keysyms ;;
                renderutil) echo xcb-util-renderutil ;;
                xinerama|shape|xcbxkb) echo libxcb ;;
                xkbx11) echo libxkbcommon-x11 ;; xkb) echo libxkbcommon ;;
                egl|gl) echo libglvnd ;;
             esac ;;
        dnf) case "$1" in
                cursor) echo xcb-util-cursor ;; icccm) echo xcb-util-wm ;;
                image) echo xcb-util-image ;; keysyms) echo xcb-util-keysyms ;;
                renderutil) echo xcb-util-renderutil ;;
                xinerama|shape|xcbxkb) echo libxcb ;;
                xkbx11) echo libxkbcommon-x11 ;; xkb) echo libxkbcommon ;;
                egl) echo libglvnd-egl ;; gl) echo libglvnd-glx ;;
             esac ;;
        zypper) case "$1" in
                cursor) echo libxcb-cursor0 ;; icccm) echo libxcb-icccm4 ;;
                image) echo libxcb-image0 ;; keysyms) echo libxcb-keysyms1 ;;
                renderutil) echo libxcb-render-util0 ;;
                xinerama) echo libxcb-xinerama0 ;; shape) echo libxcb-shape0 ;;
                xcbxkb) echo libxcb-xkb1 ;; xkbx11) echo libxkbcommon-x11-0 ;;
                xkb) echo libxkbcommon0 ;; egl) echo libEGL1 ;; gl) echo libGL1 ;;
             esac ;;
    esac
}

verify_qt_plugin() {
    local plugin missing pkgs key pkg report soname
    if ! command -v ldd >/dev/null 2>&1; then
        return 0
    fi
    plugin="$(find -L "$APP_DIR/venv/lib" -path '*plugins/platforms*' \
        -name 'libqxcb.so' 2>/dev/null | head -1)"
    if [ -z "$plugin" ]; then
        return 0
    fi
    missing="$(ldd "$plugin" 2>/dev/null | awk '/not found/ {print $1}' \
        | sort -u || true)"
    if [ -z "$missing" ]; then
        echo "-> Qt xcb plugin: all libraries resolve."
        return 0
    fi

    # Only report sonames we can map to a distribution package. Qt ships
    # its own libQt6*.so inside the wheel and resolves them relatively;
    # depending on the layout ldd can list those as "not found" too, and
    # warning about them would send people chasing packages that do not
    # exist for their distro.
    pkgs=""
    report=""
    for soname in $missing; do
        key="$(soname_key "$soname")"
        [ -z "$key" ] && continue
        pkg="$(pkg_for_key "$key")"
        [ -z "$pkg" ] && continue
        report="$report $soname"
        case " $pkgs " in *" $pkg "*) ;; *) pkgs="$pkgs $pkg" ;; esac
    done
    if [ -z "$pkgs" ]; then
        return 0
    fi

    echo ""
    echo "WARNING: the Qt xcb plugin is missing system libraries:"
    for soname in $report; do
        echo "     $soname"
    done
    echo ""
    echo "  Without these the app aborts on start with"
    echo "  \"Could not load the Qt platform plugin xcb\"."
    if [ -n "$PKG_INSTALL" ]; then
        local sudo_cmd
        sudo_cmd="$(root_prefix)"
        [ "$sudo_cmd" = "NONE" ] && sudo_cmd=""
        echo "  Fix it with:"
        echo "     $sudo_cmd $PKG_INSTALL$pkgs"
    else
        echo "  Install these packages via your package manager:$pkgs"
    fi
    if [ -n "${WAYLAND_DISPLAY:-}" ]; then
        echo "  You are on Wayland, so this also works right now:"
        echo "     QT_QPA_PLATFORM=wayland osc-dreamchatbox"
    fi
    echo ""
}
verify_qt_plugin

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
