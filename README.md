# Caelestia Settings

> A native GTK4/Libadwaita settings app for [Caelestia](https://github.com/caelestia-dots/caelestia) Hyprland setups.

![Version](https://img.shields.io/badge/version-0.0.5-blue)
![Platform](https://img.shields.io/badge/platform-Arch%20Linux-1793d1)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

### 🖥️ Monitor
- Interactive drag-and-drop canvas — arrange monitors visually like in Windows/GNOME
- Per-monitor settings: resolution, refresh rate, rotation, bit depth (8/10-bit HDR), scale
- Set primary monitor (`xrandr --primary` via `execs.conf`)
- Toggle taskbar visibility per monitor (`shell.json: bar.persistent`)

### ⌨️ General
- Keyboard layout selector — ~90 XKB layouts with live Hyprland apply
- NumLock on startup toggle
- System language (via `localectl`, requires sudo)
- Timezone (via `timedatectl`, requires sudo)

### 🪟 Window Rules
- App scanner — reads all `.desktop` files from `/usr/share/applications/` and `~/.local/share/applications/`
- Assign workspace per app (dynamically loaded from your `monitors.conf`, including named special workspaces)
- Set float behavior per app
- `match:class` or `match:initial_title` — handles Spotify Wayland and Chromium web apps
- Reads and displays existing `rules.conf` entries (manual rules are preserved, never duplicated)
- Conflict detection — warns before saving if the same class is assigned twice

### 🔊 Audio
- Output device selector
- Default volume control

### 📶 WLAN
- Scan and connect to Wi-Fi networks
- Password dialog for secured networks
- Disconnect from active network

### 🔄 Updates
- In-app system update with live progress output — no terminal popup
- Password dialog (sudo via `SUDO_ASKPASS`)
- Optional automatic reboot after update
- App self-update from GitHub

### ℹ️ About
- App version from `manifest.json`
- One-click app update

---

## Screenshots

> *Coming soon*

---

## Installation

### Dependencies

```bash
sudo pacman -S --needed python-gobject libadwaita pamixer git
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
├── main.py                  # App entry point
├── install.sh               # Installer
├── app_update.sh            # Self-updater (called by the app)
├── manifest.json            # Version info
└── src/
    ├── config.py            # Paths and config helpers
    ├── lang.py              # i18n (DE/EN)
    ├── window.py            # Main window
    └── pages/
        ├── general.py       # Keyboard, language, timezone
        ├── monitor.py       # Monitor canvas and settings
        ├── audio.py         # Audio output
        ├── wifi.py          # Wi-Fi
        ├── window_rules.py  # App → workspace assignment
        ├── updates.py       # System update UI
        ├── keybinds.py      # Keybinds (coming in v0.0.6)
        └── about.py         # About page
```

---

## Config Files Modified

| File | What changes |
|------|-------------|
| `~/.config/hypr/hyprland/input.conf` | Keyboard layout, NumLock |
| `~/.config/hypr/hyprland/monitors.conf` | Monitor resolution, position, rotation, scale |
| `~/.config/hypr/hyprland/rules.conf` | Window rules (managed block at bottom) |
| `~/.config/hypr/hyprland/execs.conf` | Primary monitor (`xrandr --primary`) |
| `~/.config/caelestia/monitors/<name>/shell.json` | Taskbar visibility |
| `~/.config/caelestia-settings/monitors.json` | Monitor settings cache |
| `~/.config/caelestia-settings/window_rules.json` | Window rules cache |

---

## Roadmap

- [x] Monitor canvas with drag-and-drop
- [x] Window rules app scanner
- [x] In-app update UI
- [x] Full keyboard layout dropdown
- [ ] Keybinds editor (v0.0.6)
- [ ] Workspace editor
- [ ] English language support
- [ ] Theming / accent color sync with Caelestia

---

## Requirements

- Arch Linux (or Arch-based distro)
- Hyprland
- [Caelestia](https://github.com/caelestia-dots/caelestia) rice
- Python 3.11+
- `python-gobject`, `libadwaita`, `pamixer`, `git`
- `yay` (for system updates)
- `nmcli` (for Wi-Fi)

---

## Author

**Jojo252511** — [GitHub](https://github.com/Jojo252511)

Made for the [Caelestia](https://github.com/caelestia-dots/caelestia) ecosystem.