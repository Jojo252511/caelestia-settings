from src.lang import t
import os
import json
from pathlib import Path

try:
    import caelestia_core
except ImportError:
    caelestia_core = None

# Pfade
CONFIG_DIR = Path(os.path.expanduser("~/.config/caelestia-settings"))
MONITOR_CONFIG_FILE = CONFIG_DIR / "monitors.json"
WINDOW_RULES_CONFIG_FILE = CONFIG_DIR / "window_rules.json"
APP_DATA_DIR = Path(os.path.expanduser("~/.local/share/caelestia-settings"))
HYPR_INPUT_CONF = Path(os.path.expanduser("~/.config/hypr/hyprland/input.conf"))
HYPR_MONITORS_CONF = Path(os.path.expanduser("~/.config/hypr/hyprland/monitors.conf"))
HYPR_RULES_CONF = Path(os.path.expanduser("~/.config/hypr/hyprland/rules.conf"))
HYPR_KEYBINDS_CONF = Path(os.path.expanduser("~/.config/hypr/hyprland/keybinds.conf"))

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

def load_window_rules_config():
    try:
        if WINDOW_RULES_CONFIG_FILE.exists():
            with open(WINDOW_RULES_CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {WINDOW_RULES_CONFIG_FILE}: {e}")
    return {}

def save_window_rules_config(config_data):
    try:
        get_config_dir().mkdir(parents=True, exist_ok=True)
        with open(WINDOW_RULES_CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=2)
        print(f"Window-Rules gespeichert in {WINDOW_RULES_CONFIG_FILE}")
    except Exception as e:
        print(f"Fehler beim Speichern von {WINDOW_RULES_CONFIG_FILE}: {e}")


def parse_monitors_conf() -> dict:
    """
    Liest ~/.config/hypr/hyprland/monitors.conf und gibt zurück:
    {
      "monitors":  [ {"name": "DP-1", "resolution": "2560x1440@179.95", ...}, ... ],
      "workspaces": [ {"number": 1, "monitor": "DP-1", "default": True}, ... ],
      "workspace_options": [ ("default", "Standard (keine Regel)"), ("1", "WS 1  –  DP-1  ★"), ... ]
    }
    """
    monitors  = []
    workspaces = []

    if not HYPR_MONITORS_CONF.exists():
        return {"monitors": [], "workspaces": [], "workspace_options": _fallback_ws_options()}

    try:
        if caelestia_core is not None:
            text = HYPR_MONITORS_CONF.read_text()
            rust_monitors, rust_workspaces = caelestia_core.parse_monitors_conf(text)
            monitors = [
                {
                    "name":       m.name,
                    "resolution": m.resolution,
                    "position":   m.position,
                    "scale":      m.scale,
                }
                for m in rust_monitors
            ]
            workspaces = [
                {"number": w.number, "monitor": w.monitor, "default": w.default}
                for w in rust_workspaces
            ]
        else:
            with open(HYPR_MONITORS_CONF, "r") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # monitor = DP-1,2560x1440@179.95,0x0,1, bitdepth, 10
                    if line.startswith("monitor"):
                        parts = [p.strip() for p in line.split("=", 1)[1].split(",")]
                        if parts:
                            monitors.append({
                                "name":       parts[0],
                                "resolution": parts[1] if len(parts) > 1 else "?",
                                "position":   parts[2] if len(parts) > 2 else "auto",
                                "scale":      parts[3] if len(parts) > 3 else "1",
                            })

                    # workspace = 1, monitor:DP-1, default:true
                    elif line.startswith("workspace"):
                        rest   = line.split("=", 1)[1]
                        tokens = [t.strip() for t in rest.split(",")]
                        if not tokens:
                            continue
                        try:
                            ws_num = int(tokens[0])
                        except ValueError:
                            continue
                        monitor_name = ""
                        is_default   = False
                        for tok in tokens[1:]:
                            if tok.startswith("monitor:"):
                                monitor_name = tok.split("monitor:")[1]
                            if "default:true" in tok:
                                is_default = True
                        workspaces.append({"number": ws_num, "monitor": monitor_name, "default": is_default})

    except Exception as e:
        print(f"Fehler beim Parsen von monitors.conf: {e}")

    workspaces.sort(key=lambda w: w["number"])

    ws_options = [("default", t("Standard (no rule)"))]
    for ws in workspaces:
        label = f"WS {ws['number']}  –  {ws['monitor']}" if ws["monitor"] else f"Workspace {ws['number']}"
        if ws["default"]:
            label += "  ★"
        ws_options.append((str(ws["number"]), label))

    for sp in ["sysmon", "music", "communication", "todo", "scratch"]:
        ws_options.append((f"special:{sp}", f"Special: {sp}"))

    return {"monitors": monitors, "workspaces": workspaces, "workspace_options": ws_options}


def _fallback_ws_options() -> list:
    opts = [("default", t("Standard (no rule)"))]
    for i in range(1, 21):
        opts.append((str(i), f"Workspace {i}"))
    for sp in ["sysmon", "music", "communication", "todo", "scratch"]:
        opts.append((f"special:{sp}", f"Special: {sp}"))
    return opts


def parse_rules_conf() -> list:
    """
    Liest rules.conf und gibt alle windowrule-Einträge strukturiert zurück.
    { "rule": "workspace special:music", "match_type": "class",
      "match_val": "feishin|Spotify", "raw": "...", "managed": False }
    """
    result = []
    if not HYPR_RULES_CONF.exists():
        return result

    if caelestia_core is not None:
        try:
            for r in caelestia_core.parse_rules_conf(HYPR_RULES_CONF.read_text()):
                result.append({
                    "rule":       r.rule,
                    "match_type": r.match_type,
                    "match_val":  r.match_val,
                    "raw":        r.raw,
                    "managed":    r.managed,
                })
        except Exception as e:
            print(f"Fehler beim Parsen von rules.conf: {e}")
        return result

    managed_marker = "# Auto-generated by Caelestia Settings – Fenster-Regeln"
    in_managed = False

    try:
        with open(HYPR_RULES_CONF, "r") as f:
            for raw_line in f:
                line = raw_line.strip()
                if line == managed_marker:
                    in_managed = True
                    continue
                if not line or line.startswith("#"):
                    continue
                if not line.startswith("windowrule"):
                    continue

                rest = line.split("=", 1)[1].strip()
                if ", match:" in rest:
                    rule_part, match_part = rest.rsplit(", match:", 1)
                    match_tokens = match_part.strip().split(None, 1)
                    match_type   = match_tokens[0] if match_tokens else "class"
                    match_val    = match_tokens[1] if len(match_tokens) > 1 else ""
                else:
                    rule_part  = rest.strip()
                    match_type = ""
                    match_val  = ""

                result.append({
                    "rule":       rule_part.strip(),
                    "match_type": match_type,
                    "match_val":  match_val,
                    "raw":        line,
                    "managed":    in_managed,
                })
    except Exception as e:
        print(f"Fehler beim Parsen von rules.conf: {e}")

    return result