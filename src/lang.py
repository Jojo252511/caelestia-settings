import locale

# Ermittle die System-Sprache (z.B. 'de_DE', 'en_US')
sys_lang = locale.getdefaultlocale()[0]
if not sys_lang:
    sys_lang = 'en'

IS_GERMAN = sys_lang.startswith('de')

# Das Wörterbuch: Englisch ist der Schlüssel, Deutsch der Wert.
# Wenn IS_GERMAN False ist, geben wir einfach den Schlüssel zurück.
TRANSLATIONS = {
    # Window
    "Caelestia Settings": "Caelestia Einstellungen",
    "Apply": "Anwenden",
    "General": "Allgemein",
    "Monitor": "Monitor",
    "Audio": "Audio",
    "Updates": "Updates",
    "About": "Über",
    
    # General Page
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

    # Monitor Page
    "Resolution and Refresh Rate": "Auflösung und Frequenz",
    "Arrangement": "Anordnung",
    "Automatic": "Automatisch",
    "Right of": "Rechts von",
    "Left of": "Links von",
    "Above": "Darüber",
    "Below": "Darunter",
    "Mirror": "Spiegeln",
    "Disable": "Deaktivieren",
    "Custom": "Benutzerdefiniert",
    "No active monitors.": "Keine aktiven Monitore.",
    
    # Audio Page
    "Audio Output": "Audio-Ausgabe",
    "Output Device": "Ausgabegerät",
    "Default Volume": "Standard-Lautstärke",
    "Error loading": "Fehler beim Laden",

    # WLAN Page (NEU)
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

    # Update Page
    "System Update": "System-Aktualisierung",
    "Start Update": "Update starten",
    "Opens Terminal": "Öffnet Terminal",
    "Update Now": "Jetzt aktualisieren",
    "Automatic Reboot": "Automatischer Neustart",
    
    # About Page
    "Version": "Version",
    "Author": "Autor",
    "Description": "Beschreibung",
    "App Management": "App-Verwaltung",
    "Update App": "App aktualisieren",
    "Downloads latest version...": "Lädt die neueste Version von Git...",
    "Check for Updates": "Update prüfen",
    "Manifest missing": "Manifest fehlt"
}

def t(text):
    """Übersetzt den Text ins Deutsche, falls System auf DE steht."""
    if IS_GERMAN:
        return TRANSLATIONS.get(text, text)
    return text