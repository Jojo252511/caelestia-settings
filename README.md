# Caelestia Settings

> A native GTK4/Libadwaita control center for [Caelestia](https://github.com/caelestia-dots/caelestia) Hyprland setups.

![Version](https://img.shields.io/badge/version-1.2.0-blue)
![Platform](https://img.shields.io/badge/platform-Arch%20Linux-1793d1)
![License](https://img.shields.io/badge/license-MIT-green)
![Language](https://img.shields.io/badge/i18n-EN%20%2F%20DE-orange)

---

## Features

### Wallpaper
- Image and video tabs — browse `~/Pictures/Wallpapers/` and `~/Videos/Wallpaper/`
- Thumbnails generated via ffmpeg for videos, cached for fast reloads
- Wallpaper folder dynamically read from `~/.config/caelestia/shell.json`
- One-click random wallpaper via `caelestia wallpaper -r`
- Light / Dark mode toggle (`caelestia scheme set -m light/dark`)
- Desktop clock settings — toggle, position, scale and invert colors (written to `shell.json`)

### Monitor
- Interactive drag-and-drop canvas — arrange monitors visually like Windows/GNOME
- Per-monitor settings: resolution, refresh rate, rotation, bit depth (8/10-bit HDR), scale
- Set primary monitor (`xrandr --primary` via `execs.conf`)
- Toggle taskbar visibility per monitor (`shell.json: bar.persistent`)

### Workspaces
- Visual editor grouped by monitor (physical order from `hyprctl monitors`)
- Add, remove and reorder workspaces
- Set monitor assignment, default workspace (★) and persistent flag per workspace
- Live apply via `hyprctl keyword workspace`

### Keybinds
- Full keybind editor — parser migrated from [HyprKeys](https://github.com/Jojo252511/hyprkeys)
- `$variable` resolution (reads `variables.conf`)
- Search and filter by bind type (`bind`, `binde`, `bindl` etc.)
- Create, edit and delete keybinds with automatic backup before every change
- Live reload via `hyprctl reload`

### Window Rules
- App scanner — reads all `.desktop` files from system and user applications
- Assign workspace per app (dynamically loaded from `monitors.conf`, including named special workspaces)
- Set float behavior and match type (`class` or `initial_title`)
- Handles Spotify Wayland and Chromium web apps automatically
- Reads and displays existing `rules.conf` — manual rules are preserved, never duplicated
- Conflict detection — warns before saving if the same class is assigned twice

### General
- Keyboard layout selector — ~90 XKB layouts with live Hyprland apply
- NumLock on startup toggle
- System language (via `localectl`, requires sudo)
- Timezone (via `timedatectl`, requires sudo)

### WLAN
- Scan and connect to Wi-Fi networks
- Password dialog for secured networks
- Disconnect from active network

### Audio
- Output device selector
- Default volume control

### Updates
- In-app system update with live progress output — no terminal popup
- Sudo password dialog (via `SUDO_ASKPASS`)
- Optional automatic reboot after update
- swaync notification on completion
- App self-update from GitHub

### Fans
- CPU and GPU temperature readout (via psutil / NVML), updated every 2 seconds
- GPU fan control: manual slider, presets (25 / 50 / 75 / 100 %), auto curve (temp-based)
- System fan PWM control via hwmon — writes directly or via sudo password dialog
- Graceful fallback when psutil or pynvml are not installed

### About
- App version from `manifest.json`
- One-click app self-update

---

## Screenshots

| Keybinds | Wallpaper | Monitor |
|----------|-----------|---------|
| ![Keybinds](https://raw.githubusercontent.com/Jojo252511/caelestia-settings/main/screenshots/keybinds.png) | ![Wallpaper](https://raw.githubusercontent.com/Jojo252511/caelestia-settings/main/screenshots/wallpaper.png) | ![Monitor](https://raw.githubusercontent.com/Jojo252511/caelestia-settings/main/screenshots/monitor.png) |

---

## Installation

### Dependencies

```bash
sudo pacman -S --needed python-gobject libadwaita pamixer git python-psutil
```

### Install

```bash
git clone https://github.com/Jojo252511/caelestia-settings.git
cd caelestia-settings
./install.sh
```

The installer will:
- Copy the app to `~/.local/share/caelestia-settings/`
- Create a `caelestia-settings` command in `~/.local/bin/`
- Add a `.desktop` entry to the app menu
- Add window rules and a `Super+I` keybind to your Hyprland config

### Run without installing

```bash
git clone https://github.com/Jojo252511/caelestia-settings.git
cd caelestia-settings
python main.py
```

---

## Keyboard Shortcut

| Shortcut | Action |
|----------|--------|
| `Super + I` | Open Caelestia Settings |

To remove this shortcut, delete the following line from `~/.config/hypr/hyprland.conf`:
```
bind = SUPER, I, exec, caelestia-settings
```

---

## File Overview

```
caelestia-settings/
├── main.py                   # App entry point
├── install.sh                # Installer
├── app_update.sh             # Self-updater (called by the About page)
├── manifest.json             # Version info
└── src/
    ├── config.py             # Paths and config helpers
    ├── lang.py               # i18n (EN / DE — auto-detected from system locale)
    ├── window.py             # Main window
    └── pages/
        ├── general.py        # Keyboard layout, language, timezone
        ├── wallpaper.py      # Wallpaper browser, video support, desktop clock
        ├── monitor.py        # Monitor canvas and settings
        ├── workspaces.py     # Workspace editor
        ├── wifi.py           # Wi-Fi
        ├── audio.py          # Audio output
        ├── window_rules.py   # App → workspace / float assignment
        ├── keybinds.py       # Keybind editor
        ├── updates.py        # System update UI
        ├── fans.py           # Fan & temperature monitoring and control
        └── about.py          # About page
```

---

## Config Files Modified

| File | What changes |
|------|-------------|
| `~/.config/hypr/hyprland/input.conf` | Keyboard layout, NumLock |
| `~/.config/hypr/hyprland/monitors.conf` | Monitor resolution, position, rotation, scale + workspace assignments |
| `~/.config/hypr/hyprland/rules.conf` | Window rules (managed block, manual rules preserved) |
| `~/.config/hypr/hyprland/keybinds.conf` | Keybinds (with automatic `.bak` before every change) |
| `~/.config/hypr/hyprland/execs.conf` | Primary monitor (`xrandr --primary`) |
| `~/.config/caelestia/shell.json` | Desktop clock settings, taskbar visibility |
| `~/.config/caelestia-settings/window_rules.json` | Window rules cache |

---

## Language Support

The app automatically detects your system language:

| Language | Detection |
|----------|-----------|
| 🇬🇧 English | Default |
| 🇩🇪 German | `LANG=de_*` |

To override, edit `src/lang.py`:
```python
IS_GERMAN = True   # force German
IS_GERMAN = False  # force English
```

---

## Requirements

- Arch Linux (or Arch-based distro)
- Hyprland
- [Caelestia](https://github.com/caelestia-dots/caelestia) rice
- Python 3.11+
- `python-gobject`, `libadwaita`, `pamixer`, `git`, `python-psutil`
- `python-nvidia-ml-py` (optional — for GPU fan control: `yay -S python-nvidia-ml-py`)
- `yay` (for system updates)
- `nmcli` (for Wi-Fi)
- `ffmpeg` (for video wallpaper thumbnails, optional)
- `mpvpaper` (for video wallpapers, optional — `yay -S mpvpaper`)

---

## Roadmap

- [x] Monitor canvas with drag-and-drop
- [x] Workspace editor
- [x] Keybind editor
- [x] Window rules app scanner
- [x] Wallpaper browser with video support
- [x] Desktop clock settings
- [x] In-app update UI
- [x] English / German language support
- [x] Fan & temperature monitoring with GPU fan control
- [ ] Theming / accent color sync with Caelestia
- [ ] Keybind key-grabber (record shortcuts by pressing keys)

---

## Author

**Jojo252511** — [GitHub](https://github.com/Jojo252511) — [Ko-fi](https://ko-fi.com/jojo2511)

Made for the [Caelestia](https://github.com/caelestia-dots/caelestia) ecosystem.
