import os
import re
import subprocess
from gi.repository import Gtk, Adw, GLib
from src.config import HYPR_INPUT_CONF
from src.lang import t

class GeneralPage(Gtk.Box):
    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.main_window = main_window
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        self.is_loading = False

        # --- EINGABE ---
        input_group = Adw.PreferencesGroup(title=t("Input"))
        self.append(input_group)

        self.config_file = HYPR_INPUT_CONF
        current_layout = self.get_current_layout()

        layout_row = Adw.ActionRow(title=t("Keyboard Layout"))
        layout_row.set_subtitle(t("Live change in Hyprland"))
        input_group.add(layout_row)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        btn_box.add_css_class("linked")
        layout_row.add_suffix(btn_box)

        self.btn_de = Gtk.ToggleButton(label="DE")
        self.btn_de.connect("toggled", self.on_layout_toggled, "de")
        btn_box.append(self.btn_de)

        self.btn_us = Gtk.ToggleButton(label="US")
        self.btn_us.set_group(self.btn_de) 
        self.btn_us.connect("toggled", self.on_layout_toggled, "us")
        btn_box.append(self.btn_us)
        
        if current_layout == "de": self.btn_de.set_active(True)
        else: self.btn_us.set_active(True)

        # --- REGION ---
        system_group = Adw.PreferencesGroup(title=t("Region & Language"))
        self.append(system_group)

        # Sprache
        lang_row = Adw.ActionRow(title=t("System Language"))
        lang_row.set_subtitle(t("Requires password"))
        self.lang_combo = Gtk.ComboBoxText()
        self.lang_combo.append("de_DE.UTF-8", "Deutsch (Deutschland)")
        self.lang_combo.append("en_US.UTF-8", "English (US)")
        self.lang_combo.append("en_GB.UTF-8", "English (UK)")
        
        lang_row.add_suffix(self.lang_combo)
        system_group.add(lang_row)

        # Zeitzone
        time_row = Adw.ActionRow(title=t("Timezone"))
        self.time_combo = Gtk.ComboBoxText()
        self.time_combo.append("Europe/Berlin", "Berlin (CET/CEST)")
        self.time_combo.append("Europe/London", "London (GMT/BST)")
        self.time_combo.append("America/New_York", "New York (EST/EDT)")
        self.time_combo.append("UTC", "UTC")
        
        time_row.add_suffix(self.time_combo)
        system_group.add(time_row)

        self.load_system_settings()
        self.lang_combo.connect("changed", self.on_language_changed)
        self.time_combo.connect("changed", self.on_timezone_changed)

    def get_current_layout(self):
        try:
            with open(self.config_file, 'r') as f:
                content = f.read()
            match = re.search(r"^\s*kb_layout\s*=\s*(\w+)", content, re.MULTILINE)
            if match: return match.group(1).lower()
        except: pass
        return "us"

    def on_layout_toggled(self, button, lang):
        if not button.get_active(): return
        try:
            subprocess.run(["hyprctl", "keyword", "input:kb_layout", lang], check=True)
            if self.config_file.exists():
                with open(self.config_file, 'r') as f: content = f.read()
                new_content = re.sub(r"(^\s*kb_layout\s*=\s*).*", r"\g<1>" + lang, content, flags=re.MULTILINE)
                with open(self.config_file, 'w') as f: f.write(new_content)
        except Exception as e: print(f"Err: {e}")

    def load_system_settings(self):
        self.is_loading = True
        try:
            res = subprocess.run(['localectl', 'status'], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if "LANG=" in line:
                    lang = line.split("LANG=")[1].strip()
                    if not self.lang_combo.set_active_id(lang):
                        self.lang_combo.append(lang, f"{t('Current')}: {lang}")
                        self.lang_combo.set_active_id(lang)
        except Exception as e: print(f"Err Lang: {e}")

        try:
            res = subprocess.run(['timedatectl', 'show', '-p', 'Timezone', '--value'], capture_output=True, text=True)
            tz = res.stdout.strip()
            if not self.time_combo.set_active_id(tz):
                self.time_combo.append(tz, f"{t('Current')}: {tz}")
                self.time_combo.set_active_id(tz)
        except Exception as e: print(f"Err Time: {e}")
        
        self.is_loading = False

    def on_language_changed(self, combo):
        if self.is_loading: return
        lang = combo.get_active_id()
        if not lang: return
        try:
            subprocess.run(['pkexec', 'localectl', 'set-locale', f'LANG={lang}'], check=True)
            print(t("Language set successfully (reboot needed)."))
        except subprocess.CalledProcessError:
            print(t("Language change cancelled."))
            self.load_system_settings()

    def on_timezone_changed(self, combo):
        if self.is_loading: return
        tz = combo.get_active_id()
        if not tz: return
        try:
            subprocess.run(['pkexec', 'timedatectl', 'set-timezone', tz], check=True)
            print(t("Timezone set successfully."))
        except subprocess.CalledProcessError:
            print(t("Timezone change cancelled."))
            self.load_system_settings()