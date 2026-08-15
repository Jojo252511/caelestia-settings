# Caelestia Settings

> A native GTK4/Libadwaita control center for [Caelestia](https://github.com/caelestia-dots/caelestia) Hyprland setups.

![Version](https://img.shields.io/badge/version-1.3.2-blue)
![Platform](https://img.shields.io/badge/platform-Arch%20Linux-1793d1)
![License](https://img.shields.io/badge/license-MIT-green)
![Language](https://img.shields.io/badge/i18n-EN%20%2F%20DE-orange)

---

## Features

### Home

- System at a Glance overview: current wallpaper (thumbnail preview), monitors summary, active Wi-Fi connection, keyboard layout, CPU/GPU temperatures with fan speeds
- Quick Actions for one-click navigation to Wallpaper, Monitor, WLAN, Keybinds, and Updates pages

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
- Rust-based parsing for both Hyprlang and Lua monitor configuration

### Workspaces

- Visual editor grouped by monitor (physical order from `hyprctl monitors`)
- Add, remove and reorder workspaces
- Set monitor assignment, default workspace (★) and persistent flag per workspace
- Provider-aware live apply: legacy keywords for Hyprlang, safe file write plus reload for Lua

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
- Reads and displays existing Hyprlang or Lua rules — manual rules are preserved
- Conflict detection — warns before saving if the same class is assigned twice
- Rust-based parser for `rules.conf` for improved performance and reliability

### General

- Keyboard layout selector — ~90 XKB layouts with live Hyprland apply
- NumLock on startup toggle
- Provider-aware input configuration through `input.conf` or `input.lua`
- System language (via `localectl`, requires sudo)
- Timezone (via `timedatectl`, requires sudo)

### WLAN

- Scan and connect to Wi-Fi networks via NetworkManager D-Bus API
- Secure password handling — credentials are passed over D-Bus, never exposed in process arguments (fixes issue #44)
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

| Keybinds                                                                                                   | Wallpaper                                                                                                    | Monitor                                                                                                  |
| ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| ![Keybinds](https://raw.githubusercontent.com/Jojo252511/caelestia-settings/main/screenshots/keybinds.png) | ![Wallpaper](https://raw.githubusercontent.com/Jojo252511/caelestia-settings/main/screenshots/wallpaper.png) | ![Monitor](https://raw.githubusercontent.com/Jojo252511/caelestia-settings/main/screenshots/monitor.png) |

---

## Installation

### Dependencies

For the application (Python UI + Rust parsing/Lua core):

```bash
sudo pacman -S --needed python-gobject libadwaita pamixer git python-psutil python-cairo rust networkmanager lua
```

Optional Rust developer tooling (the Rust compiler itself is required above):

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

### Uninstall

```bash
./uninstall.sh
```

Removes the installed app, the `caelestia-settings` command, the `.desktop` entry, the
app's window rules, and the `Super+I` keybind. Asks before removing your saved settings
(`~/.config/caelestia-settings/`). Leaves installed packages, the `~/.local/bin` PATH
setup, and shared Hyprland config lines (rules.conf/monitors.conf sourcing, Polkit
autostart) untouched, since those aren't exclusive to this app. Pass `-y` to skip the
confirmation prompt.

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

| Shortcut    | Action                  |
| ----------- | ----------------------- |
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
├── uninstall.sh              # Uninstaller
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
│   │       ├── lua.rs        # Generic Lua value/call parsing and rendering
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
- **Rust Core** (`caelestia-core`): Configuration parsers, generic Lua call/table codec, data models, rendering, and utility functions (PWM conversion, conflict detection)
- **PyO3 Bridge** (`caelestia-py`): Exposes `caelestia-core` to Python via PyO3, allowing the Python code to call Rust functions as if they were native Python extensions

This separation allows:

- Fast, reliable parsing of complex config files in Rust
- Full unit testing of parsing logic without Python dependencies
- Complete migration of configuration parsers to Rust (mandatory backend)

Python owns the GTK UI, provider selection, file I/O, process execution, and user-visible errors. Lua syntax is parsed and rendered through the Rust core; there is no Python parser fallback.

### Hyprland configuration providers (v2.0.0 development)

Caelestia Settings is being migrated to support both the legacy Hyprlang provider (`.conf`) and Hyprland's Lua provider (`.lua`). During this transition, a temporary Yes/No prompt asks whether `hyprland.lua` is already active and stores that choice in `~/.config/caelestia-settings/hyprland_provider.json`. Closing the dialog does not guess a format and leaves provider-dependent pages locked. This prompt is explicitly transitional and will be removed once reliable automatic detection replaces it.

The current migration status on `feat/hyprland-lua-migration` is:

| Configuration area             |  Hyprlang |                                    Lua |
| ------------------------------ | --------: | -------------------------------------: |
| General / Input                | Supported | M5 complete and independently approved |
| Monitors                       | Supported |                              Supported |
| Workspaces                     | Supported |                              Supported |
| Window Rules                   | Supported |                              Supported |
| Keybinds / Variables           | Supported |                         Planned for M7 |
| Wallpaper autostart            | Supported |               M6 approved; not started |
| Execs / primary monitor        | Supported |               M6 approved; not started |
| Installer / Doctor integration | Supported |                         Planned for M8 |

Without an explicit provider choice, all provider-dependent configuration areas fail closed. Wi-Fi, Audio, Updates, Fans, and About remain provider-independent. The migration is tracked in [issue #51](https://github.com/Jojo252511/caelestia-settings/issues/51); v2.0.0 is not complete until the remaining milestones and release hardening are finished.

### Safe managed blocks

App-owned Lua output is isolated in named `BEGIN`/`END` managed blocks. Writes preserve content outside the selected block, reject missing or malformed ownership markers, serialize concurrent writers with a bounded lock, create a backup, validate the complete candidate file with `luac -p`, and replace it atomically. A successful write is followed by `hyprctl reload`; reload failures trigger a guarded rollback and a second reload. Manual Lua calls and other named blocks are not adopted as app-owned content.

---

## Config Files Modified

The selected provider determines which Hyprland file is read and written. Unsupported Lua areas stay locked instead of silently editing an inactive Hyprlang file.

| Area                        | Hyprlang path                           | Lua path                               | Current Lua status                     |
| --------------------------- | --------------------------------------- | -------------------------------------- | -------------------------------------- |
| Input                       | `~/.config/hypr/hyprland/input.conf`    | `~/.config/hypr/hyprland/input.lua`    | M5 complete and independently approved |
| Monitors + workspaces       | `~/.config/hypr/hyprland/monitors.conf` | `~/.config/hypr/hyprland/monitors.lua` | Supported                              |
| Window Rules                | `~/.config/hypr/hyprland/rules.conf`    | `~/.config/hypr/hyprland/rules.lua`    | Supported                              |
| Keybinds                    | `~/.config/hypr/hyprland/keybinds.conf` | `~/.config/hypr/hyprland/keybinds.lua` | Planned for M7                         |
| Variables                   | `~/.config/hypr/variables.conf`         | `~/.config/hypr/variables.lua`         | Planned for M7                         |
| Autostart / primary monitor | `~/.config/hypr/hyprland/execs.conf`    | `~/.config/hypr/hyprland/execs.lua`    | M6 approved; not started               |

Provider-independent Caelestia state is stored separately:

| File                                             | What changes                               |
| ------------------------------------------------ | ------------------------------------------ |
| `~/.config/caelestia/shell.json`                 | Desktop clock settings, taskbar visibility |
| `~/.config/caelestia-settings/window_rules.json` | Window Rules cache                         |

---

## Language Support

The app automatically detects your system language:

| Language | Detection   |
| -------- | ----------- |
| English  | Default     |
| German   | `LANG=de_*` |

To override, edit `src/lang.py`:

```python
IS_GERMAN = True   # force German
IS_GERMAN = False  # force English
```

---

## CI/CD

Automated testing and linting via GitHub Actions workflow (`.github/workflows/ci.yml`):

- **Python**: `ruff check main.py src/ tests/`; the test job builds and imports the real PyO3 extension before running `unittest` and an application-construction smoke test
- **Lua**: `lua5.4`/`luac` is installed for syntax-validation tests
- **Rust**: `cargo fmt --check`, `cargo clippy --locked --workspace --all-targets`, and `cargo test --locked --workspace` for both crates
- **Formatting**: Prettier for Markdown, JSON, and YAML via `npm run format:check` (`npm ci` to install, `npm run format` to auto-format)
- **Security**: `gitleaks` for secret scanning

Triggers on push and pull request to `main` and `dev` branches.

---

## Requirements

- Arch Linux (or Arch-based distro)
- Hyprland
- [Caelestia](https://github.com/caelestia-dots/caelestia) rice
- Python 3.12+
- `python-gobject`, `libadwaita`, `pamixer`, `git`, `python-psutil`, `python-cairo`, `lua`
- `rust` (required — `caelestia_core` is built from source at install time, see Installation above)
- `python-nvidia-ml-py` (optional — for GPU fan control: `yay -S python-nvidia-ml-py`)
- `yay` (for system updates)
- `nmcli` (for Wi-Fi)
- `ffmpeg` (for video wallpaper thumbnails, optional)
- `mpvpaper` (for video wallpapers, optional — `yay -S mpvpaper`)
- `clippy`, `rust-analyzer` (optional — for Rust module development only, via `rustup component add`)

---

## Roadmap

### v2.0.0 — Full Rust + Lua Support

- [x] M1: transitional provider selection and fail-closed capability gates
- [x] M2: Rust Lua codec with PyO3 bindings
- [x] M3: Lua monitor and workspace support
- [x] M4: Lua window-rule support
- [x] M5: Lua General/Input support, independently approved
- [ ] M6: Lua wallpaper/autostart and primary-monitor execs (approved; not started)
- [ ] M7: Lua keybinds and variables
- [ ] M8: provider-aware installer and doctor
- [ ] v2.0.0 release hardening and final validation

Hyprlang support remains available throughout the migration. The temporary provider prompt will be removed after a reliable automatic detection path is available.

### General roadmap

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
