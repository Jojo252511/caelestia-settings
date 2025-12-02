#!/bin/bash
#
# Installer für die modulare Caelestia Settings App
# Version 5 (mit app_update.sh Support)
#
set -e

echo "#######################################"
echo "###   Caelestia Settings Installer  ###"
echo "#######################################"
echo

# --- 1. Finde das Quellverzeichnis ---
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
MAIN_APP_SRC="$SCRIPT_DIR/main.py"
SRC_FOLDER="$SCRIPT_DIR/src"
UPDATE_SCRIPT_SRC="$SCRIPT_DIR/app_update.sh"
MANIFEST_SRC="$SCRIPT_DIR/manifest.json"

if [ ! -f "$MAIN_APP_SRC" ] || [ ! -d "$SRC_FOLDER" ]; then
    echo "FEHLER: 'main.py' oder 'src/' Ordner nicht gefunden!"
    echo "Bitte stelle sicher, dass 'install.sh', 'main.py' und 'src/' im selben Ordner liegen."
    exit 1
fi
echo ">>> Quellcode gefunden in: $SCRIPT_DIR"
echo

# --- 2. Installiere System-Abhängigkeiten ---
echo ">>> SCHRITT 1: Installiere System-Abhängigkeiten..."
echo "Das Skript benötigt 'python-gobject', 'libadwaita', 'pamixer' und 'git'."
echo "Bitte gib dein Passwort für sudo ein:"
sudo pacman -S --needed --noconfirm python-gobject libadwaita pamixer git
echo "--- Abhängigkeiten sind installiert."
echo

# --- 3. Definiere Benutzer-Pfade ---
APP_DATA_DIR="$HOME/.local/share/caelestia-settings"
BIN_DIR="$HOME/.local/bin"
APP_LAUNCHER_DIR="$HOME/.local/share/applications"

APP_TARGET_MAIN="$APP_DATA_DIR/main.py"
APP_TARGET_BIN="$BIN_DIR/caelestia-settings"
APP_TARGET_DESKTOP="$APP_LAUNCHER_DIR/org.caelestia.settings.desktop"

# --- 4. Erstelle Verzeichnisse & Bereinige alte Installation ---
echo ">>> SCHRITT 2: Bereite Installationsordner vor..."
mkdir -p "$BIN_DIR"
mkdir -p "$APP_LAUNCHER_DIR"

if [ -d "$APP_DATA_DIR" ]; then
    echo "   ...Entferne alte Installation in $APP_DATA_DIR"
    rm -rf "$APP_DATA_DIR"
fi
mkdir -p "$APP_DATA_DIR"
echo "--- Verzeichnisse bereit."
echo

# --- 5. Installiere die Anwendung (Kopieren) ---
echo ">>> SCHRITT 3: Installiere die Anwendung..."
echo "   ...Kopiere 'main.py' nach $APP_DATA_DIR"
cp "$MAIN_APP_SRC" "$APP_DATA_DIR/"
chmod +x "$APP_TARGET_MAIN"

echo "   ...Kopiere 'src/' Ordner nach $APP_DATA_DIR"
cp -r "$SRC_FOLDER" "$APP_DATA_DIR/"

# NEU: Update-Skript kopieren
if [ -f "$UPDATE_SCRIPT_SRC" ]; then
    echo "   ...Kopiere 'app_update.sh' nach $APP_DATA_DIR"
    cp "$UPDATE_SCRIPT_SRC" "$APP_DATA_DIR/"
    chmod +x "$APP_DATA_DIR/app_update.sh"
else
    echo "WARNUNG: 'app_update.sh' nicht gefunden. Update-Funktion wird nicht verfügbar sein."
fi

if [ -f "$MANIFEST_SRC" ]; then
    echo "   ...Kopiere 'manifest.json' nach $APP_DATA_DIR"
    cp "$MANIFEST_SRC" "$APP_DATA_DIR/"
else
    echo "WARNUNG: 'manifest.json' nicht im Quellordner gefunden!"
    echo "Erstelle Dummy-Manifest, damit die App starten kann."
    echo '{"version": "unknown"}' > "$APP_DATA_DIR/manifest.json"
fi

echo "   ...Erstelle Befehl-Alias (Symlink) in $APP_TARGET_BIN"
ln -sf "$APP_TARGET_MAIN" "$APP_TARGET_BIN"
echo "--- Anwendung installiert."
echo

# --- 6. Stelle sicher, dass ~/.local/bin im PATH ist ---
echo ">>> SCHRITT 4: Stelle sicher, dass ~/.local/bin im PATH ist..."

FISH_CONFIG_DIR="$HOME/.config/fish"
FISH_CONFIG="$FISH_CONFIG_DIR/config.fish"
FISH_PATH_CMD="fish_add_path $HOME/.local/bin"
if [ -d "$FISH_CONFIG_DIR" ]; then 
    mkdir -p "$FISH_CONFIG_DIR" && touch "$FISH_CONFIG"
    if ! grep -q -F "$FISH_PATH_CMD" "$FISH_CONFIG"; then
        echo "   ...Füge PATH zur Fish-Konfiguration hinzu."
        echo "" >> "$FISH_CONFIG"
        echo "# Caelestia Settings PATH" >> "$FISH_CONFIG"
        echo "$FISH_PATH_CMD" >> "$FISH_CONFIG"
    fi
fi

PROFILE_CONFIG="$HOME/.profile"
PROFILE_PATH_CMD='export PATH="$HOME/.local/bin:$PATH"'
if ! grep -q -F "$PROFILE_PATH_CMD" "$PROFILE_CONFIG" 2>/dev/null; then
    echo "   ...Füge PATH zur Fallback-Datei hinzu ($PROFILE_CONFIG)."
    echo "" >> "$PROFILE_CONFIG"
    echo "# Caelestia Settings PATH" >> "$PROFILE_CONFIG"
    echo "$PROFILE_PATH_CMD" >> "$PROFILE_CONFIG"
fi
echo "--- PATH-Konfiguration abgeschlossen."
echo

# --- 7. Erstelle den App-Menü-Eintrag ---
echo ">>> SCHRITT 5: Erstelle Eintrag im App-Menü..."
cat > "$APP_TARGET_DESKTOP" <<- EOM
[Desktop Entry]
Version=1.0.2
Name=Caelestia Einstellungen
Comment=Hyprland-, Monitor- und Audio-Einstellungen verwalten
Exec=caelestia-settings
Icon=preferences-system-symbolic
Terminal=false
Type=Application
Categories=Settings;System;
EOM
echo "--- App-Menü-Eintrag erstellt."
echo

# --- 8. Füge Hyprland-Konfiguration hinzu ---
echo ">>> SCHRITT 6: Konfiguriere Hyprland..."

HYPR_CONFIG_DIR="$HOME/.config/hypr"
HYPR_CONFIG_FILE="$HYPR_CONFIG_DIR/hyprland.conf"
HYPR_INCLUDES_DIR="$HYPR_CONFIG_DIR/hyprland"

mkdir -p "$HYPR_CONFIG_DIR"
mkdir -p "$HYPR_INCLUDES_DIR"
touch "$HYPR_CONFIG_FILE"

RULE_TAG="# Caelestia Settings Rule"
if ! grep -q -F "$RULE_TAG" "$HYPR_CONFIG_FILE"; then
    echo "   ...Füge 'floating' Fenster-Regel hinzu."
    cat >> "$HYPR_CONFIG_FILE" <<- EOM

$RULE_TAG
windowrule = float, class:(org.caelestia.settings)
windowrule = center, class:(org.caelestia.settings)
EOM
fi

MONITOR_CONFIG_FILE_PATH="$HYPR_INCLUDES_DIR/monitors.conf"
SOURCE_LINE="source = $MONITOR_CONFIG_FILE_PATH"
if ! grep -q -F "$SOURCE_LINE" "$HYPR_CONFIG_FILE"; then
    echo "   ...Füge 'source' Regel für Monitore hinzu."
    cat >> "$HYPR_CONFIG_FILE" <<- EOM

# Caelestia Monitor Config
$SOURCE_LINE
EOM
fi

echo "--- Hyprland-Konfiguration abgeschlossen."
echo

# --- 9. Fertig ---
echo "#######################################"
echo "###      INSTALLATION FERTIG      ###"
echo "#######################################"
echo
echo "Die Caelestia Settings App ist jetzt installiert!"
echo "Bitte logge dich neu ein."
echo