#!/bin/bash
#
# Installer for the Caelestia Settings App
#
set -e

echo "#######################################"
echo "###   Caelestia Settings Installer  ###"
echo "#######################################"
echo

# --- 1. Find source directory ---
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
MAIN_APP_SRC="$SCRIPT_DIR/main.py"
SRC_FOLDER="$SCRIPT_DIR/src"
UPDATE_SCRIPT_SRC="$SCRIPT_DIR/app_update.sh"
UNINSTALL_SCRIPT_SRC="$SCRIPT_DIR/uninstall.sh"
MANIFEST_SRC="$SCRIPT_DIR/manifest.json"

if [ ! -f "$MAIN_APP_SRC" ] || [ ! -d "$SRC_FOLDER" ]; then
    echo "ERROR: 'main.py' or 'src/' folder not found!"
    echo "Please make sure 'install.sh', 'main.py' and 'src/' are in the same directory."
    exit 1
fi
echo ">>> Source code found in: $SCRIPT_DIR"
echo

# --- 2. Install system dependencies ---
echo ">>> STEP 1: Installing system dependencies..."
echo "The script requires 'python-gobject', 'libadwaita', 'pamixer', 'git' and 'rust'."
echo "Please enter your sudo password:"
sudo pacman -S --needed --noconfirm python-gobject libadwaita pamixer git python-psutil python-cairo rust
echo "--- Dependencies installed."
echo

# --- 3. Define user paths ---
APP_DATA_DIR="$HOME/.local/share/caelestia-settings"
BIN_DIR="$HOME/.local/bin"
APP_LAUNCHER_DIR="$HOME/.local/share/applications"

APP_TARGET_MAIN="$APP_DATA_DIR/main.py"
APP_TARGET_BIN="$BIN_DIR/caelestia-settings"
APP_TARGET_DESKTOP="$APP_LAUNCHER_DIR/org.caelestia.settings.desktop"

# --- 4. Create directories & clean old installation ---
echo ">>> STEP 2: Preparing installation directory..."
mkdir -p "$BIN_DIR"
mkdir -p "$APP_LAUNCHER_DIR"

if [ -d "$APP_DATA_DIR" ]; then
    echo "   ...Removing old installation at $APP_DATA_DIR"
    rm -rf "$APP_DATA_DIR"
fi
mkdir -p "$APP_DATA_DIR"
echo "--- Directories ready."
echo

# --- 5. Install the application ---
echo ">>> STEP 3: Installing the application..."
echo "   ...Copying 'main.py' to $APP_DATA_DIR"
cp "$MAIN_APP_SRC" "$APP_DATA_DIR/"
chmod +x "$APP_TARGET_MAIN"

echo "   ...Copying 'src/' folder to $APP_DATA_DIR"
cp -r "$SRC_FOLDER" "$APP_DATA_DIR/"

# --- 5b. Build the caelestia_core Rust extension ---
echo "   ...Building the caelestia_core Rust extension (this can take a minute)"
RUST_DIR="$SCRIPT_DIR/rust/caelestia-py"
if [ -d "$RUST_DIR" ]; then
    BUILD_VENV=$(mktemp -d)
    WHEEL_OUT=$(mktemp -d)
    trap 'rm -rf "$BUILD_VENV" "$WHEEL_OUT"' EXIT

    python3 -m venv "$BUILD_VENV"
    "$BUILD_VENV/bin/pip" install --quiet maturin
    ( cd "$RUST_DIR" && "$BUILD_VENV/bin/maturin" build --release --out "$WHEEL_OUT" )

    WHEEL_FILE=$(find "$WHEEL_OUT" -name '*.whl' -print -quit)
    if [ -z "$WHEEL_FILE" ]; then
        echo "ERROR: caelestia_core build produced no wheel."
        exit 1
    fi
    UNPACK_DIR=$(mktemp -d)
    trap 'rm -rf "$BUILD_VENV" "$WHEEL_OUT" "$UNPACK_DIR"' EXIT
    python3 -m zipfile -e "$WHEEL_FILE" "$UNPACK_DIR"
    rm -rf "$APP_DATA_DIR/caelestia_core"
    cp -r "$UNPACK_DIR/caelestia_core" "$APP_DATA_DIR/"

    rm -rf "$BUILD_VENV" "$WHEEL_OUT" "$UNPACK_DIR"
    trap - EXIT
    echo "   ...caelestia_core built and installed to $APP_DATA_DIR/caelestia_core"
else
    echo "ERROR: 'rust/caelestia-py' not found — cannot build the caelestia_core extension."
    exit 1
fi

# Copy update script
if [ -f "$UPDATE_SCRIPT_SRC" ]; then
    echo "   ...Copying 'app_update.sh' to $APP_DATA_DIR"
    cp "$UPDATE_SCRIPT_SRC" "$APP_DATA_DIR/"
    chmod +x "$APP_DATA_DIR/app_update.sh"
else
    echo "WARNING: 'app_update.sh' not found. The update function will not be available."
fi

# Copy uninstall script
if [ -f "$UNINSTALL_SCRIPT_SRC" ]; then
    echo "   ...Copying 'uninstall.sh' to $APP_DATA_DIR"
    cp "$UNINSTALL_SCRIPT_SRC" "$APP_DATA_DIR/"
    chmod +x "$APP_DATA_DIR/uninstall.sh"
else
    echo "WARNING: 'uninstall.sh' not found. The in-app uninstall button will not be available."
fi

# Copy manifest
if [ -f "$MANIFEST_SRC" ]; then
    echo "   ...Copying 'manifest.json' to $APP_DATA_DIR"
    cp "$MANIFEST_SRC" "$APP_DATA_DIR/"
else
    echo "WARNING: 'manifest.json' not found in source directory!"
    echo "Creating dummy manifest so the app can start."
    echo '{"version": "unknown"}' > "$APP_DATA_DIR/manifest.json"
fi

echo "   ...Creating command alias (symlink) at $APP_TARGET_BIN"
ln -sf "$APP_TARGET_MAIN" "$APP_TARGET_BIN"
echo "--- Application installed."
echo

# --- 6. Make sure ~/.local/bin is in PATH ---
echo ">>> STEP 4: Ensuring ~/.local/bin is in PATH..."

FISH_CONFIG_DIR="$HOME/.config/fish"
FISH_CONFIG="$FISH_CONFIG_DIR/config.fish"
FISH_PATH_CMD="fish_add_path $HOME/.local/bin"
if [ -d "$FISH_CONFIG_DIR" ]; then
    mkdir -p "$FISH_CONFIG_DIR" && touch "$FISH_CONFIG"
    if ! grep -q -F "$FISH_PATH_CMD" "$FISH_CONFIG"; then
        echo "   ...Adding PATH to Fish config."
        echo "" >> "$FISH_CONFIG"
        echo "# Caelestia Settings PATH" >> "$FISH_CONFIG"
        echo "$FISH_PATH_CMD" >> "$FISH_CONFIG"
    fi
fi

PROFILE_CONFIG="$HOME/.profile"
PROFILE_PATH_CMD='export PATH="$HOME/.local/bin:$PATH"'
if ! grep -q -F "$PROFILE_PATH_CMD" "$PROFILE_CONFIG" 2>/dev/null; then
    echo "   ...Adding PATH to fallback profile ($PROFILE_CONFIG)."
    echo "" >> "$PROFILE_CONFIG"
    echo "# Caelestia Settings PATH" >> "$PROFILE_CONFIG"
    echo "$PROFILE_PATH_CMD" >> "$PROFILE_CONFIG"
fi
echo "--- PATH configuration done."
echo

# --- 7. Create app menu entry ---
echo ">>> STEP 5: Creating app menu entry..."
cat > "$APP_TARGET_DESKTOP" <<- EOM
[Desktop Entry]
Version=1.0.0
Name=Caelestia Settings
Comment=Manage Hyprland, monitor and audio settings
Exec=caelestia-settings
Icon=preferences-system-symbolic
Terminal=false
Type=Application
Categories=Settings;System;
EOM
echo "--- App menu entry created."
echo

# --- 8. Configure Hyprland ---
echo ">>> STEP 6: Configuring Hyprland..."

HYPR_CONFIG_DIR="$HOME/.config/hypr"
HYPR_CONFIG_FILE="$HYPR_CONFIG_DIR/hyprland.conf"
HYPR_INCLUDES_DIR="$HYPR_CONFIG_DIR/hyprland"
RULES_CONFIG_FILE="$HYPR_INCLUDES_DIR/rules.conf"

# The bind/source/polkit checks below used to be duplicated here; they now
# live in doctor.sh so a standalone `./doctor.sh` run can repair them too.
source "$SCRIPT_DIR/doctor.sh"
run_hyprland_doctor

NEW_RULES_TAG="# Caelestia Settings Rules"
if ! grep -q -F "$NEW_RULES_TAG" "$RULES_CONFIG_FILE"; then
    echo "   ...Writing window rules to $RULES_CONFIG_FILE."
    cat >> "$RULES_CONFIG_FILE" <<- EOM

$NEW_RULES_TAG
windowrule = float true, match:class org\.caelestia\.settings
windowrule = center 1, match:class org\.caelestia\.settings
EOM
else
    echo "   ...Window rules already exist in rules.conf."
fi

echo "--- Hyprland configuration done."
echo

# --- 9. Done ---
echo "#######################################"
echo "###      INSTALLATION COMPLETE     ###"
echo "#######################################"
echo
echo "Caelestia Settings is now installed!"
echo
echo "!!! IMPORTANT: Please log out and back in (or restart your PC). !!!"
echo
echo "After restarting you can launch the app:"
echo "1. From the app menu as 'Caelestia Settings'"
echo "2. From the terminal with 'caelestia-settings'"
echo "3. With 'Super + I'"
echo
echo "--- Optional: Remove the Super+I shortcut ---"
echo "To disable the Super+I keybind, remove the following line"
echo "from your '~/.config/hypr/hyprland.conf':"
echo
echo "bind = SUPER, I, exec, caelestia-settings"