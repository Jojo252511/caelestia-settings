import os
import subprocess
from pathlib import Path
from gi.repository import Gtk, Adw
from src.lang import t

# Der Inhalt des Update-Skripts bleibt technisch, da es ein Terminal-Befehl ist.
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

        self.update_script_path = Path.cwd() / "Update.sh"
        self.create_update_script()

        group = Adw.PreferencesGroup(title=t("System Update"))
        self.append(group)

        update_row = Adw.ActionRow(title=t("Start Update"), subtitle=t("Opens Terminal"))
        update_btn = Gtk.Button(label=t("Update Now"))
        update_btn.connect("clicked", self.on_update_clicked)
        update_row.add_suffix(update_btn)
        group.add(update_row)
        
        self.reboot_switch = Adw.SwitchRow(title=t("Automatic Reboot"), subtitle="-r Flag")
        group.add(self.reboot_switch)

    def create_update_script(self):
        try:
            with open(self.update_script_path, 'w') as f:
                f.write(UPDATE_SCRIPT_CONTENT)
            os.chmod(self.update_script_path, 0o755)
        except Exception as e: print(f"Err: {e}")

    def on_update_clicked(self, button):
        cmd = [str(self.update_script_path)]
        if self.reboot_switch.get_active(): cmd.append("-r")
        try: subprocess.Popen(["kitty"] + cmd)
        except Exception as e: print(f"Err: {e}")