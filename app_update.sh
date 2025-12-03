#!/bin/bash
# Caelestia App Updater
set -e

# Das erste Argument ist die PID der Python-App
APP_PID=$1

# --- KONFIGURATION ---
GIT_REPO_URL="https://github.com/Jojo252511/caelestia-settings.git"
TEMP_DIR="/tmp/caelestia-settings-update"

echo "#######################################"
echo "###   Caelestia App Updater         ###"
echo "#######################################"
echo

# --- SCHRITT 0: App beenden ---
if [ -n "$APP_PID" ]; then
    echo ">>> Beende laufende App (PID: $APP_PID) für sauberes Update..."
    # Versuche den Prozess zu beenden. 
    # '2>/dev/null' versteckt Fehler, falls der Prozess schon weg ist.
    # '|| true' verhindert, dass das Skript abbricht, falls kill fehlschlägt.
    kill "$APP_PID" 2>/dev/null || true
    sleep 1
    echo "   ...App beendet."
    echo
fi

echo ">>> [1/3] Bereinige temporäre Dateien..."
rm -rf "$TEMP_DIR"

echo ">>> [2/3] Lade neueste Version von Git..."
echo "Repo: $GIT_REPO_URL"
if git clone "$GIT_REPO_URL" "$TEMP_DIR"; then
    echo "   ...Download erfolgreich."
else
    echo
    echo "FEHLER: Git Clone fehlgeschlagen."
    echo "Bitte prüfe die Internetverbindung oder GitHub Server Status"
    echo "Drücke Enter zum Beenden."
    read
    exit 1
fi

echo ">>> [3/3] Starte Installer der neuen Version..."
echo
cd "$TEMP_DIR"

if [ -f "install.sh" ]; then
    chmod +x install.sh
    ./install.sh
else
    echo "FEHLER: 'install.sh' im heruntergeladenen Repository nicht gefunden!"
    echo "Drücke Enter zum Beenden."
    read
    exit 1
fi

echo
echo "#######################################"
echo "   Update erfolgreich abgeschlossen!"
echo "#######################################"
echo "Du kannst die App jetzt neu starten."
echo
echo "Drücke Enter zum Schließen."
read