# Caelestia Settings

> A native GTK4/Libadwaita control center for [Caelestia](https://github.com/caelestia-dots/caelestia) Hyprland setups.

![Version](https://img.shields.io/badge/version-1.3.0-blue)
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
- Rust-based parser for `monitors.conf` and `workspaces.conf`

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
- Rust-based parser for `keybinds.conf` and `variables.conf`

### Window Rules
- App scanner — reads all `.desktop` files from system and user applications
- Assign workspace per app (dynamically loaded from `monitors.conf`, including named special workspaces)
- Set float behavior and match type (`class` or `initial_title`)
- Handles Spotify Wayland and Chromium web apps automatically
- Reads and displays existing `rules.conf` — manual rules are preserved, never duplicated
- Conflict detection — warns before saving if the same class is assigned twice
- Rust-based parser for `rules.conf` for improved performance and reliability

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

For the application (Python UI + Rust parsing core):
```bash
sudo pacman -S --needed python-gobject libadwaita pamixer git python-psutil python-cairo rust
```

For Rust module development — linting/testing only, not required just to build/run the app (optional):
```bash
rustup component add clippy rust-analyzer
```

### Install

```bash
git clone https://github.com/Jojo252511/caelestia-settings.git
cd caelestia-settings
./install.sh
```

The installer will:
- Copy the app to `~/.local/share/caelestia-settings/`
- Build the `caelestia_core` Rust extension (via a throwaway venv + `maturin`) and install it alongside the app — this step compiles Rust code and can take a minute
- Create a `caelestia-settings` command in `~/.local/bin/`
- Add a `.desktop` entry to the app menu
- Add window rules and a `Super+I` keybind to your Hyprland config

### Run without installing

`caelestia_core` is a hard dependency — build it into your environment first. Use `--system-site-packages` so the venv can also see the system `python-gobject` (PyGI) install; a plain venv won't have it and `python main.py` will fail with `ModuleNotFoundError: No module named 'gi'`. Activate the venv (rather than calling `.venv/bin/maturin` by path) so `maturin develop` reliably targets it instead of some other `.venv` it might auto-detect elsewhere:
```bash
cd caelestia-settings/rust/caelestia-py
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install maturin && maturin develop
```

Then, from the same activated environment:
```bash
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
├── ruff.toml                 # Python linter configuration
├── rust/                     # Rust workspace for parser modules
│   ├── Cargo.toml            # Rust workspace root
│   ├── caelestia-core/       # Core parser modules (pure Rust)
│   │   ├── Cargo.toml        # Package configuration
│   │   └── src/
│   │       ├── lib.rs        # Module exports
│   │       ├── config.rs     # monitors.conf and workspaces.conf parsing
│   │       ├── keybinds.rs    # keybinds.conf and variables.conf parsing
│   │       ├── rules.rs       # rules.conf windowrule parsing
│   │       ├── window_rule_conflicts.rs  # Conflict detection for window rules
│   │       └── fans.rs       # PWM percent/raw conversion for fan control
│   └── caelestia-py/          # PyO3 bindings exposing caelestia-core to Python
│       ├── Cargo.toml        # Package configuration with PyO3
│       └── src/
│           └── lib.rs        # Python module registration (caelestia_core)
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

## Architecture

The application uses a hybrid Python + Rust architecture:

- **Python/GTK4**: The main application, UI, and all user interaction logic is written in Python using GTK4 and Libadwaita
- **Rust Core** (`caelestia-core`): Pure Rust crate containing all configuration file parsers (monitors.conf, workspaces.conf, keybinds.conf, variables.conf, rules.conf) and utility functions (PWM conversion, conflict detection)
- **PyO3 Bridge** (`caelestia-py`): Exposes `caelestia-core` to Python via PyO3, allowing the Python code to call Rust functions as if they were native Python extensions

This separation allows:
- Fast, reliable parsing of complex config files in Rust
- Full unit testing of parsing logic without Python dependencies
- Gradual migration of performance-critical components from Python to Rust

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
| English | Default |
| German | `LANG=de_*` |

To override, edit `src/lang.py`:
```python
IS_GERMAN = True   # force German
IS_GERMAN = False  # force English
```

---

## CI/CD

Automated testing and linting via GitHub Actions workflow (`.github/workflows/ci.yml`):

- **Python**: `ruff check` for linting (targets Python 3.12)
- **Rust**: `cargo fmt --check`, `cargo clippy --workspace --all-targets`, `cargo test --workspace` for both `caelestia-core` and `caelestia-py` crates
- **Security**: `gitleaks` for secret scanning

Triggers on push and pull request to `main` and `dev` branches.

---

## Requirements

- Arch Linux (or Arch-based distro)
- Hyprland
- [Caelestia](https://github.com/caelestia-dots/caelestia) rice
- Python 3.12+
- `python-gobject`, `libadwaita`, `pamixer`, `git`, `python-psutil`, `python-cairo`
- `rust` (required — `caelestia_core` is built from source at install time, see Installation above)
- `python-nvidia-ml-py` (optional — for GPU fan control: `yay -S python-nvidia-ml-py`)
- `yay` (for system updates)
- `nmcli` (for Wi-Fi)
- `ffmpeg` (for video wallpaper thumbnails, optional)
- `mpvpaper` (for video wallpapers, optional — `yay -S mpvpaper`)
- `clippy`, `rust-analyzer` (optional — for Rust module development only, via `rustup component add`)

---

## What's New in 1.3.0

- **Rust modules**: `window_rule_conflicts.rs` (conflict detection) and `fans.rs` (PWM percentage conversion) are now complete — fully tested (38/38 tests passing), clippy/fmt clean
- **PyO3 bindings**: New `caelestia-py` crate exposes all `caelestia-core` parsing and utility functions to Python as the `caelestia_core` extension module
- **Self-update fix**: `app_update.sh` now explicitly pins the `main` branch instead of following GitHub's default branch (previously pulled from `dev` by mistake)

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
- [x] Rust module for monitors.conf parsing
- [x] Rust module for keybinds.conf parsing
- [x] Rust module for rules.conf parsing
- [x] Rust module for window-rule conflict detection
- [x] Rust module for fan PWM percentage conversion
- [x] CI pipeline with Python and Rust linting/tests
- [x] PyO3 bindings for Rust to Python integration (via `caelestia-py`)
- [x] Integrate Rust parsers in fans.py, keybinds.py, config.py (monitors/rules parsing), window_rules.py
- [x] `caelestia_core` built and installed automatically by `install.sh` — no more optional Python fallback, Rust is a hard dependency
- [ ] Theming / accent color sync with Caelestia
- [ ] Keybind key-grabber (record shortcuts by pressing keys)

---

## Author

**Jojo252511** — [GitHub](https://github.com/Jojo252511) — [Ko-fi](https://ko-fi.com/jojo2511)

Made for the [Caelestia](https://github.com/caelestia-dots/caelestia) ecosystem.
