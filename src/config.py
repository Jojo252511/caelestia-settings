import os
import json
from pathlib import Path

# Pfade
CONFIG_DIR = Path(os.path.expanduser("~/.config/caelestia-settings"))
MONITOR_CONFIG_FILE = CONFIG_DIR / "monitors.json"
APP_DATA_DIR = Path(os.path.expanduser("~/.local/share/caelestia-settings"))
HYPR_INPUT_CONF = Path(os.path.expanduser("~/.config/hypr/hyprland/input.conf"))
HYPR_MONITORS_CONF = Path(os.path.expanduser("~/.config/hypr/hyprland/monitors.conf"))

def get_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR

def load_monitor_config():
    try:
        if MONITOR_CONFIG_FILE.exists():
            with open(MONITOR_CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {MONITOR_CONFIG_FILE}: {e}")
    return {}

def save_monitor_config(config_data):
    try:
        get_config_dir().mkdir(parents=True, exist_ok=True)
        with open(MONITOR_CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=2)
        print(f"Monitor-Konfiguration gespeichert in {MONITOR_CONFIG_FILE}")
    except Exception as e:
        print(f"Fehler beim Speichern von {MONITOR_CONFIG_FILE}: {e}")