import locale

sys_lang = locale.getdefaultlocale()[0]
if not sys_lang:
    sys_lang = 'en'

# Set to True to force German, False to force English
# Remove this override for automatic language detection
# IS_GERMAN = False
IS_GERMAN = sys_lang.startswith('de')

TRANSLATIONS = {
    # ── Window ────────────────────────────────────────────────────────────
    "Caelestia Settings": "Caelestia Einstellungen",
    "Update App": "App aktualisieren",

    # ── Home ──────────────────────────────────────────────────────────────
    "Home": "Startseite",
    "System at a Glance": "System auf einen Blick",
    "Quick Actions": "Schnellzugriff",
    "Refresh": "Aktualisieren",
    "Monitors": "Monitore",
    "CPU Temperature": "CPU-Temperatur",
    "GPU Temperature": "GPU-Temperatur",
    "Not available": "Nicht verfügbar",
    "Not connected": "Nicht verbunden",
    "No monitors configured": "Keine Monitore konfiguriert",
    "No supported GPU detected": "Keine unterstützte GPU erkannt",
    "Change wallpaper and color scheme": "Wallpaper und Farbschema ändern",
    "Arrange displays and resolutions": "Bildschirme und Auflösungen anordnen",
    "Scan and connect to networks": "Netzwerke suchen und verbinden",
    "View and edit shortcuts": "Tastenkürzel ansehen und bearbeiten",
    "Check for system updates": "Nach System-Updates suchen",

    # ── General ───────────────────────────────────────────────────────────
    "General": "Allgemein",
    "Input": "Eingabe",
    "Keyboard Layout": "Tastaturbelegung",
    "Live change in Hyprland": "Live-Änderung in Hyprland",
    "Region and Language": "Region und Sprache",
    "System Language": "Systemsprache",
    "Requires password": "Erfordert Passwort",
    "Timezone": "Zeitzone",
    "Current": "Aktuell",
    "Language set successfully (reboot needed).": "Sprache erfolgreich gesetzt (Neustart nötig).",
    "Language change cancelled.": "Sprachänderung abgebrochen.",
    "Timezone set successfully.": "Zeitzone erfolgreich gesetzt.",
    "Timezone change cancelled.": "Zeitzonenänderung abgebrochen.",
    "NumLock on startup": "NumLock beim Start aktivieren",
    "numlock_by_default in input.conf": "numlock_by_default in input.conf",

    # ── Monitor ───────────────────────────────────────────────────────────
    "Monitor": "Monitor",
    "Click to select  •  Drag to move": "Klicken zum Auswählen  •  Ziehen zum Verschieben",
    "No monitor selected": "Kein Monitor ausgewählt",
    "Click on a monitor in the preview.": "Klicke auf einen Monitor in der Vorschau.",
    "Resolution": "Auflösung",
    "Refresh rate": "Bildwiederholrate",
    "Rotation": "Drehung",
    "Normal (0°)": "Normal (0°)",
    "90° right": "90° rechts",
    "180°": "180°",
    "270° right / 90° left": "270° rechts / 90° links",
    "Bit depth": "Farbtiefe",
    "Standard (8 bit)": "Standard (8 bit)",
    "10 bit (HDR)": "10 bit (HDR)",
    "Scale": "Skalierung",
    "Monitor enabled": "Monitor aktiviert",
    "Primary monitor": "Hauptmonitor",
    "xrandr --primary (for X11 apps and tray)": "xrandr --primary (für X11-Apps und Tray)",
    "Always show taskbar": "Taskleiste immer anzeigen",
    "shell.json: bar.persistent": "shell.json: bar.persistent",
    "Reload": "Neu laden",
    "Apply": "Anwenden",
    "Monitor configuration saved and applied.": "Monitor-Konfiguration gespeichert und angewendet.",

    # ── Wallpaper ─────────────────────────────────────────────────────────
    "Wallpaper": "Wallpaper",
    "🖼 Images": "🖼 Bilder",
    "🎬 Videos": "🎬 Videos",
    "🔀 Random": "🔀 Zufällig",
    "Light / Dark Mode": "Light / Dark Mode",
    "Desktop clock": "Desktop-Uhr",
    "Position, size and visibility": "Position, Größe und Sichtbarkeit",
    "Show clock": "Uhr anzeigen",
    "Position": "Position",
    "Size": "Größe",
    "Invert colors": "Farben invertieren",
    "Top right": "Oben rechts",
    "Top left": "Oben links",
    "Bottom right": "Unten rechts",
    "Bottom left": "Unten links",
    "No images found.\nPlace images in the wallpaper folder.": "Keine Bilder gefunden.\nBilder in ~/Bilder/Wallpapers/ ablegen.",
    "No videos found.\nPlace videos in ~/Videos/Wallpaper/": "Keine Videos gefunden.\nVideos in ~/Videos/Wallpaper/ ablegen.",
    "Color scheme: ": "Farbschema: ",
    "Random wallpaper set": "Zufälliger Wallpaper gesetzt",
    "mpvpaper not found — yay -S mpvpaper": "mpvpaper nicht gefunden — yay -S mpvpaper",

    # ── Workspaces ────────────────────────────────────────────────────────
    "Workspaces": "Workspaces",
    "+ Add": "+ Hinzufügen",
    "Save & Apply": "Speichern & Anwenden",
    "Saving...": "Speichern…",
    "No workspaces found": "Keine Workspaces gefunden",
    "Add a workspace or check your monitors.conf": "Füge einen Workspace hinzu oder prüfe deine monitors.conf",
    "No.": "Nr.",
    "Default ★": "Standard ★",
    "Always visible": "Immer sichtbar",
    "Workspace stays visible even without windows": "Workspace bleibt auch ohne Fenster sichtbar",
    "Workspaces saved and applied.": "Workspaces gespeichert und angewendet.",

    # ── Keybinds ──────────────────────────────────────────────────────────
    "Keybinds": "Keybinds",
    "Search: SUPER, exec, kitty...": "Suche: SUPER, exec, kitty…",
    "All types": "Alle Typen",
    "+ New": "+ Neu",
    "No keybinds found": "Keine Keybinds gefunden",
    "Check your keybinds.conf or add a new keybind.": "Prüfe deine keybinds.conf oder füge eine neue Keybind hinzu.",
    "Edit keybind": "Keybind bearbeiten",
    "New keybind": "Neue Keybind",
    "Bind type": "Bind-Typ",
    "Modifier": "Modifier",
    "Key": "Taste",
    "Dispatcher": "Dispatcher",
    "Argument": "Argument",
    "Comment": "Kommentar",
    "Save": "Speichern",
    "Cancel": "Abbrechen",
    "Yes": "Ja",
    "No": "Nein",
    "Error:": "Fehler:",

    # ── Hyprland config-provider transition (temporary, see issue #51) ──────
    "Hyprland configuration format": "Hyprland-Konfigurationsformat",
    (
        "Do you already use Hyprland's Lua configuration (hyprland.lua)? "
        "This is a temporary compatibility question and will be removed "
        "in a future release."
    ): (
        "Verwendest du bereits Hyprlands Lua-Konfiguration (hyprland.lua)? "
        "Diese vorübergehende Kompatibilitätsabfrage wird in einer "
        "zukünftigen Version entfernt."
    ),
    "Hyprland configuration provider saved.": "Hyprland-Konfigurationsformat gespeichert.",
    "Choose a Hyprland configuration provider to unlock this page.": (
        "Wähle ein Hyprland-Konfigurationsformat, um diese Seite freizuschalten."
    ),
    "Hyprland configuration provider required": "Hyprland-Konfigurationsformat erforderlich",
    "Choose Yes or No in the provider dialog before editing configuration.": (
        "Wähle im Provider-Dialog Ja oder Nein, bevor du die Konfiguration bearbeitest."
    ),
    "Choose Yes or No in the provider dialog before reading configuration.": (
        "Wähle im Provider-Dialog Ja oder Nein, bevor die Konfiguration gelesen wird."
    ),
    "Choose a Hyprland configuration provider first.": (
        "Wähle zuerst ein Hyprland-Konfigurationsformat."
    ),
    "Lua compiler (luac) is required; changes were not applied.": (
        "Der Lua-Compiler (luac) ist erforderlich; Änderungen wurden nicht übernommen."
    ),
    "Generated Lua is invalid, changes were not applied:": (
        "Generiertes Lua ist ungültig, Änderungen wurden nicht übernommen:"
    ),
    "Delete keybind?": "Keybind löschen?",
    "Delete": "Löschen",
    "Keybind saved and Hyprland reloaded.": "Keybind gespeichert und Hyprland neu geladen.",
    "Keybind deleted.": "Keybind gelöscht.",
    "Key and dispatcher are required.": "Taste und Dispatcher sind erforderlich.",

    # ── Window Rules ──────────────────────────────────────────────────────
    "Window Rules": "Fenster-Regeln",
    "Search app...": "App suchen…",
    "App rules": "App-Regeln",
    "Existing rules": "Bestehende Regeln",
    "conflicts detected": "Konflikt(e) erkannt",
    "Details": "Details",
    "Conflicts": "Konflikte",
    "Match": "Match",
    "Workspace": "Workspace",
    "Behavior": "Verhalten",
    "Standard (no rule)": "Standard (keine Regel)",
    "Float": "Float",
    "No float": "Kein Float",
    "Rules saved and Hyprland reloaded.": "Regeln gespeichert und Hyprland neu geladen.",
    "Web app": "Web-App",
    "Unknown class": "Unbekannte Klasse",
    "No windowrule entries found.": "Keine windowrule-Einträge gefunden.",
    (
        "All windowrule entries from {path}  –  🔒 manual  /  ⚙ managed by this app"
    ): (
        "Alle windowrule-Einträge aus {path}  –  🔒 manuell  /  ⚙ von dieser App verwaltet"
    ),
    (
        "All hl.window_rule(...) entries from {path}  –  🔒 manual  /  ⚙ managed by this app"
    ): (
        "Alle hl.window_rule(...)-Einträge aus {path}  –  🔒 manuell  /  ⚙ von dieser App verwaltet"
    ),

    # ── WLAN ──────────────────────────────────────────────────────────────
    "WLAN": "WLAN",
    "Wi-Fi Networks": "WLAN-Netzwerke",
    "Scan": "Suchen",
    "No Wi-Fi adapter found.": "Kein WLAN-Adapter gefunden.",
    "Connected": "Verbunden",
    "Connect": "Verbinden",
    "Disconnect": "Trennen",
    "Password Required": "Passwort erforderlich",
    "Please enter the password for": "Bitte gib das Passwort ein für",
    "Connection failed": "Verbindung fehlgeschlagen",
    "Connection successful": "Verbindung erfolgreich",
    "Scanning...": "Suche...",
    "NetworkManager is not available.": "NetworkManager ist nicht verfügbar.",
    "Network not found.": "Netzwerk nicht gefunden.",
    "Enterprise networks are not supported.": "Unternehmensnetzwerke (802.1X) werden nicht unterstützt.",
    "Incorrect password": "Falsches Passwort",
    "Connection timed out.": "Zeitüberschreitung bei der Verbindung.",

    # ── Audio ─────────────────────────────────────────────────────────────
    "Audio": "Audio",
    "Audio Output": "Audio-Ausgabe",
    "Output Device": "Ausgabegerät",
    "Default Volume": "Standard-Lautstärke",
    "Error loading": "Fehler beim Laden",

    # ── Updates ───────────────────────────────────────────────────────────
    "Updates": "Updates",
    "System Update": "System-Aktualisierung",
    "Update Now": "Jetzt aktualisieren",
    "Automatic Reboot": "Automatischer Neustart",
    "Restarts system automatically after update": "Startet das System nach dem Update automatisch neu",
    "Password required": "Passwort erforderlich",
    "Enter your sudo password to start the system update.": "Bitte gib dein sudo-Passwort ein, um das System-Update zu starten.",
    "No password entered.": "Kein Passwort eingegeben.",
    "Running...": "Läuft…",
    "Starting update...": "Starte Update…",
    "Done!": "Fertig!",
    "Update successful.": "Update erfolgreich abgeschlossen.",

    "Conflicts detected": "Konflikte erkannt",

    # ── Fans ──────────────────────────────────────────────────────────────
    "Fans": "Lüfter",
    "Fan": "Lüfter",
    "Fan & Temperature": "Lüfter & Temperaturen",
    "GPU Fan Control": "GPU-Lüftersteuerung",
    "System Fan Control": "System-Lüftersteuerung",
    "Auto Fan Curve": "Automatische Lüfterkurve",
    "Fan Speed": "Lüftergeschwindigkeit",
    "Presets": "Voreinstellungen",
    "Fan settings applied.": "Lüftereinstellungen angewendet.",
    "Enter your sudo password to write fan settings.": "Bitte gib dein sudo-Passwort ein, um die Lüftereinstellungen zu schreiben.",
    "GPU fan: enable Coolbits — sudo nvidia-xconfig --cool-bits=4": "GPU-Lüfter: Coolbits aktivieren — sudo nvidia-xconfig --cool-bits=4",
    "GPU fan: manual control not supported (Zero-RPM mode?)": "GPU-Lüfter: Manuelle Steuerung nicht unterstützt (Zero-RPM aktiv?)",

    # ── About ─────────────────────────────────────────────────────────────
    "About": "Über",
    "Version": "Version",
    "Author": "Autor",
    "Description": "Beschreibung",
    "App Management": "App-Verwaltung",
    "Downloads latest version...": "Lädt die neueste Version von Git...",
    "Check for Updates": "Update prüfen",
    "Uninstall App": "App deinstallieren",
    "Removes the app and its Hyprland integration...": "Entfernt die App und ihre Hyprland-Integration...",
    "Uninstall": "Deinstallieren",
    "Manifest missing": "Manifest fehlt",
}


def t(text: str) -> str:
    """Returns German translation if system language is German, otherwise English."""
    if IS_GERMAN:
        return TRANSLATIONS.get(text, text)
    return text
