#!/bin/bash
#
# Uninstaller for the Caelestia Settings App
#
# Reverses everything install.sh does, EXCEPT:
#   - System packages (pacman -S ...) — shared with the rest of the system,
#     not safe to remove automatically.
#   - The `~/.local/bin` PATH additions in fish/profile — a general-purpose
#     directory other tools may also rely on.
#   - The rules.conf/monitors.conf `source` lines and the Polkit autostart
#     line in hyprland.conf — these are generic Hyprland integration points
#     (rules.conf/monitors.conf hold the user's actual monitor layout and
#     window rules, not just this app's), not exclusive to this app.
#
set -e

echo "#########################################"
echo "###  Caelestia Settings Uninstaller   ###"
echo "#########################################"
echo

# --- 1. Define user paths (must match install.sh) ---
APP_DATA_DIR="$HOME/.local/share/caelestia-settings"
BIN_DIR="$HOME/.local/bin"
APP_LAUNCHER_DIR="$HOME/.local/share/applications"
USER_CONFIG_DIR="$HOME/.config/caelestia-settings"

APP_TARGET_BIN="$BIN_DIR/caelestia-settings"
APP_TARGET_DESKTOP="$APP_LAUNCHER_DIR/org.caelestia.settings.desktop"

HYPR_CONFIG_DIR="$HOME/.config/hypr"
HYPR_CONFIG_FILE="$HYPR_CONFIG_DIR/hyprland.conf"
HYPR_INCLUDES_DIR="$HYPR_CONFIG_DIR/hyprland"
RULES_CONFIG_FILE="$HYPR_INCLUDES_DIR/rules.conf"
KEYBINDS_CONFIG_FILE="$HYPR_INCLUDES_DIR/keybinds.conf"

# --- 2. Confirm ---
SKIP_CONFIRM=false
for arg in "$@"; do
    case "$arg" in
        -y|--yes) SKIP_CONFIRM=true ;;
    esac
done

if [ "$SKIP_CONFIRM" = false ]; then
    echo "This will remove:"
    echo "  - $APP_DATA_DIR"
    echo "  - $APP_TARGET_BIN"
    echo "  - $APP_TARGET_DESKTOP"
    echo "  - The Caelestia Settings window rules in $RULES_CONFIG_FILE"
    echo "  - The Super+I keybind (if present in hyprland.conf/keybinds.conf)"
    echo
    read -r -p "Continue? [y/N] " REPLY
    case "$REPLY" in
        [yY][eE][sS]|[yY]) ;;
        *) echo "Aborted."; exit 0 ;;
    esac
    echo
fi

# --- 3. Remove the command symlink ---
echo ">>> STEP 1: Removing command alias..."
if [ -L "$APP_TARGET_BIN" ] || [ -f "$APP_TARGET_BIN" ]; then
    rm -f "$APP_TARGET_BIN"
    echo "--- Removed $APP_TARGET_BIN"
else
    echo "--- Not found, skipping."
fi
echo

# --- 4. Remove the app menu entry ---
echo ">>> STEP 2: Removing app menu entry..."
if [ -f "$APP_TARGET_DESKTOP" ]; then
    rm -f "$APP_TARGET_DESKTOP"
    echo "--- Removed $APP_TARGET_DESKTOP"
else
    echo "--- Not found, skipping."
fi
echo

# --- 5. Remove the installed application (incl. caelestia_core, app_update.sh) ---
echo ">>> STEP 3: Removing installed application..."
if [ -d "$APP_DATA_DIR" ]; then
    rm -rf "$APP_DATA_DIR"
    echo "--- Removed $APP_DATA_DIR"
else
    echo "--- Not found, skipping."
fi
echo

# --- 6. Remove app-specific Hyprland window rules ---
echo ">>> STEP 4: Removing Hyprland window rules..."
RULES_TAG="# Caelestia Settings Rules"
if [ -f "$RULES_CONFIG_FILE" ] && grep -q -F "$RULES_TAG" "$RULES_CONFIG_FILE"; then
    sed -i \
        -e "/^${RULES_TAG//\//\\/}\$/d" \
        -e '/^windowrule = float true, match:class org\\.caelestia\\.settings$/d' \
        -e '/^windowrule = center 1, match:class org\\.caelestia\\.settings$/d' \
        "$RULES_CONFIG_FILE"
    echo "--- Removed window rules from $RULES_CONFIG_FILE"
else
    echo "--- Not found, skipping."
fi
echo

# --- 7. Remove the Super+I keybind ---
echo ">>> STEP 5: Removing Super+I keybind..."
BIND_REMOVED=false
for f in "$HYPR_CONFIG_FILE" "$KEYBINDS_CONFIG_FILE"; do
    if [ -f "$f" ] && grep -q -F "exec, caelestia-settings" "$f"; then
        sed -i '/exec, caelestia-settings/d' "$f"
        echo "--- Removed keybind from $f"
        BIND_REMOVED=true
    fi
done
if [ "$BIND_REMOVED" = false ]; then
    echo "--- Not found, skipping."
fi
echo

# --- 8. Optionally remove user config/data ---
echo ">>> STEP 6: User configuration..."
if [ -d "$USER_CONFIG_DIR" ]; then
    if [ "$SKIP_CONFIRM" = true ]; then
        echo "--- Keeping $USER_CONFIG_DIR (pass no -y flag to be asked, or remove it manually)."
    else
        read -r -p "Also remove saved settings at $USER_CONFIG_DIR? [y/N] " REPLY
        case "$REPLY" in
            [yY][eE][sS]|[yY])
                rm -rf "$USER_CONFIG_DIR"
                echo "--- Removed $USER_CONFIG_DIR"
                ;;
            *)
                echo "--- Keeping $USER_CONFIG_DIR"
                ;;
        esac
    fi
else
    echo "--- Not found, skipping."
fi
echo

# --- 9. Done ---
echo "#########################################"
echo "###      UNINSTALL COMPLETE           ###"
echo "#########################################"
echo
echo "Not touched (shared with the rest of the system, remove manually if you want):"
echo "  - Installed packages (python-gobject, libadwaita, pamixer, rust, ...)"
echo "  - ~/.local/bin PATH additions in ~/.config/fish/config.fish and ~/.profile"
echo "  - The rules.conf/monitors.conf 'source' lines and Polkit autostart line in"
echo "    $HYPR_CONFIG_FILE"
echo
echo "Run 'hyprctl reload' or restart Hyprland to apply the config changes."
