import json
import os 
import subprocess
from gi.repository import Gtk, Adw
from src.config import APP_DATA_DIR
from src.lang import t

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
        
        info = {"name": "Caelestia", "version": "?", "author": "?", "beschreibung": t("Manifest missing")}

        try:
            if manifest_path.exists():
                with open(manifest_path, 'r') as f:
                    data = json.load(f)
                    info.update(data)
        except Exception as e: print(f"Err: {e}")

        # Info Group
        info_group = Adw.PreferencesGroup()
        self.append(info_group)
        
        info_group.add(Adw.ActionRow(title=t("Version"), subtitle=info["version"]))
        info_group.add(Adw.ActionRow(title=t("Author"), subtitle=info["author"]))
        info_group.add(Adw.ActionRow(title=t("Description"), subtitle=info["beschreibung"]))

        # App Mgmt Group
        update_group = Adw.PreferencesGroup(title=t("App Management"))
        self.append(update_group)

        update_row = Adw.ActionRow(title=t("Update App"), subtitle=t("Downloads latest version..."))
        update_btn = Gtk.Button(label=t("Check for Updates"))
        update_btn.add_css_class("suggested-action")
        update_btn.connect("clicked", self.on_update_clicked)
        
        update_row.add_suffix(update_btn)
        update_group.add(update_row)

    def on_update_clicked(self, button):
        if not self.update_script.exists():
            print(f"ERR: Script missing: {self.update_script}")
            return
        
        # Holen der eigenen Prozess-ID (PID)
        my_pid = str(os.getpid())
        print(f"Starte Update-Prozess (übergebe PID: {my_pid})...")
        
        try: 
            # Wir übergeben die PID als Argument an das Skript
            # Kitty Syntax: kitty [options] program [arguments...]
            subprocess.Popen(["kitty", str(self.update_script), my_pid])
        except Exception as e: print(f"Err: {e}")