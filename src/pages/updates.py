import os
import subprocess
from pathlib import Path
from gi.repository import Gtk, Adw

UPDATE_SCRIPT_CONTENT = """#!/usr/bin/env bash
set -e
echo "### UPDATE-SKRIPT ###"
echo ">>> [1/2] System-Update..."
yay -Syu --needed hyprlock swww
echo ">>> [2/2] Audio-Restart..."
systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service
if [[ "$1" == "-r" ]]; then
    echo "!!! REBOOT in 15s !!!"
    sleep 15
    sudo reboot
fi
"""

class UpdatePage(Gtk.Box):
    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # Skript liegt im selben Ordner wie main.py (root)
        # Wir gehen davon aus, dass wir von main.py gestartet wurden
        self.update_script_path = Path.cwd() / "Update.sh"
        self.create_update_script()

        group = Adw.PreferencesGroup(title="System-Aktualisierung")
        self.append(group)

        update_row = Adw.ActionRow(title="Update starten", subtitle="Öffnet Terminal")
        update_btn = Gtk.Button(label="Jetzt aktualisieren")
        update_btn.connect("clicked", self.on_update_clicked)
        update_row.add_suffix(update_btn)
        group.add(update_row)
        
        self.reboot_switch = Adw.SwitchRow(title="Automatischer Neustart", subtitle="-r Flag")
        group.add(self.reboot_switch)

    def create_update_script(self):
        try:
            with open(self.update_script_path, 'w') as f:
                f.write(UPDATE_SCRIPT_CONTENT)
            os.chmod(self.update_script_path, 0o755)
        except Exception as e:
            print(f"Fehler Update-Skript: {e}")

    def on_update_clicked(self, button):
        cmd = [str(self.update_script_path)]
        if self.reboot_switch.get_active(): cmd.append("-r")
        try: subprocess.Popen(["kitty"] + cmd)
        except Exception as e: print(f"Fehler: {e}")