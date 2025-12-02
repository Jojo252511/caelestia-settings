import json
import subprocess
from gi.repository import Gtk, Adw
from src.config import APP_DATA_DIR

class AboutPage(Gtk.Box):
    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        manifest_path = APP_DATA_DIR / "manifest.json"
        self.update_script = APP_DATA_DIR / "app_update.sh"
        
        info = {"name": "Caelestia", "version": "?", "author": "?", "beschreibung": "Manifest fehlt"}

        try:
            if manifest_path.exists():
                with open(manifest_path, 'r') as f:
                    data = json.load(f)
                    info.update(data)
        except Exception as e: print(f"Fehler Manifest: {e}")

        # --- Gruppe 1: Informationen ---
        info_group = Adw.PreferencesGroup()
        self.append(info_group)
        
        info_group.add(Adw.ActionRow(title="Version", subtitle=info["version"]))
        info_group.add(Adw.ActionRow(title="Autor", subtitle=info["author"]))
        info_group.add(Adw.ActionRow(title="Beschreibung", subtitle=info["beschreibung"]))

        # --- Gruppe 2: App-Verwaltung ---
        update_group = Adw.PreferencesGroup(title="App-Verwaltung")
        self.append(update_group)

        update_row = Adw.ActionRow(title="App aktualisieren", subtitle="Lädt die neueste Version von Git und installiert sie neu")
        
        update_btn = Gtk.Button(label="Update prüfen")
        update_btn.add_css_class("suggested-action") # Macht den Knopf blau
        update_btn.connect("clicked", self.on_update_clicked)
        
        update_row.add_suffix(update_btn)
        update_group.add(update_row)

    def on_update_clicked(self, button):
        if not self.update_script.exists():
            print(f"FEHLER: Update-Skript nicht gefunden unter: {self.update_script}")
            return

        print("Starte Update-Prozess...")
        try:
            # Startet das Skript in einem neuen Terminal (Kitty)
            subprocess.Popen(["kitty", str(self.update_script)])
        except Exception as e:
            print(f"Fehler beim Starten des Updates: {e}")