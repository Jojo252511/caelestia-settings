#!/bin/bash
# Caelestia Settings — App Updater
set -e

# First argument is the PID of the running Python app
APP_PID=$1

# --- CONFIGURATION ---
GIT_REPO_URL="https://github.com/Jojo252511/caelestia-settings.git"
TEMP_DIR="/tmp/caelestia-settings-update"

echo "#######################################"
echo "###   Caelestia App Updater         ###"
echo "#######################################"
echo

# --- STEP 0: Stop the running app ---
if [ -n "$APP_PID" ]; then
    echo ">>> Stopping running app (PID: $APP_PID) for a clean update..."
    kill "$APP_PID" 2>/dev/null || true
    sleep 1
    echo "   ...App stopped."
    echo
fi

echo ">>> [1/3] Cleaning up temporary files..."
rm -rf "$TEMP_DIR"

echo ">>> [2/3] Downloading latest version from Git..."
echo "Repo: $GIT_REPO_URL"
if git clone "$GIT_REPO_URL" "$TEMP_DIR"; then
    echo "   ...Download successful."
else
    echo
    echo "ERROR: Git clone failed."
    echo "Please check your internet connection or GitHub server status."
    echo "Press Enter to exit."
    read
    exit 1
fi

echo ">>> [3/3] Running installer for the new version..."
echo
cd "$TEMP_DIR"

if [ -f "install.sh" ]; then
    chmod +x install.sh
    ./install.sh
else
    echo "ERROR: 'install.sh' not found in the downloaded repository!"
    echo "Press Enter to exit."
    read
    exit 1
fi

echo
echo "#######################################"
echo "   Update completed successfully!"
echo "#######################################"
echo "You can now restart the app."
echo
echo "Press Enter to close."
read