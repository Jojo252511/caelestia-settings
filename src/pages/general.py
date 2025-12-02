import os
import re
import subprocess
from gi.repository import Gtk, Adw, GLib
from src.config import HYPR_INPUT_CONF

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

        # --- GRUPPE 1: EINGABE (Tastatur) ---
        input_group = Adw.PreferencesGroup(title="Eingabe")
        self.append(input_group)

        # Tastatur-Layout (Logik von vorher)
        self.config_file = HYPR_INPUT_CONF
        current_layout = self.get_current_layout()

        layout_row = Adw.ActionRow(title="Tastaturbelegung")
        layout_row.set_subtitle("Live-Änderung in Hyprland")
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

        # --- GRUPPE 2: REGION & SPRACHE ---
        system_group = Adw.PreferencesGroup(title="Region & Sprache")
        self.append(system_group)

        # 1. Sprache (Locale)
        lang_row = Adw.ActionRow(title="Systemsprache")
        lang_row.set_subtitle("Erfordert Passwort zur Änderung")
        self.lang_combo = Gtk.ComboBoxText()
        # Wir bieten hier die gängigsten Optionen an.
        # ID ist der Locale-Code, Text ist die Anzeige.
        self.lang_combo.append("de_DE.UTF-8", "Deutsch (Deutschland)")
        self.lang_combo.append("en_US.UTF-8", "English (US)")
        self.lang_combo.append("en_GB.UTF-8", "English (UK)")
        
        lang_row.add_suffix(self.lang_combo)
        system_group.add(lang_row)

        # 2. Zeitzone
        time_row = Adw.ActionRow(title="Zeitzone")
        self.time_combo = Gtk.ComboBoxText()
        # Kuratierte Liste der wichtigsten Zeitzonen
        self.time_combo.append("Europe/Berlin", "Berlin (CET/CEST)")
        self.time_combo.append("Europe/London", "London (GMT/BST)")
        self.time_combo.append("America/New_York", "New York (EST/EDT)")
        self.time_combo.append("UTC", "UTC (Weltzeit)")
        
        time_row.add_suffix(self.time_combo)
        system_group.add(time_row)

        # Werte laden und Signale verbinden
        self.load_system_settings()
        self.lang_combo.connect("changed", self.on_language_changed)
        self.time_combo.connect("changed", self.on_timezone_changed)

    # --- TASTATUR LOGIK ---
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
        print(f"Setze Layout: {lang}")
        try:
            subprocess.run(["hyprctl", "keyword", "input:kb_layout", lang], check=True)
            if self.config_file.exists():
                with open(self.config_file, 'r') as f: content = f.read()
                new_content = re.sub(r"(^\s*kb_layout\s*=\s*).*", r"\g<1>" + lang, content, flags=re.MULTILINE)
                with open(self.config_file, 'w') as f: f.write(new_content)
        except Exception as e: print(f"Fehler Tastatur: {e}")

    # --- SYSTEM LOGIK ---
    def load_system_settings(self):
        self.is_loading = True
        try:
            # Sprache laden (localectl status)
            res = subprocess.run(['localectl', 'status'], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if "LANG=" in line:
                    lang = line.split("LANG=")[1].strip()
                    # Wenn die aktuelle Sprache in unserer Liste ist, setze sie
                    if not self.lang_combo.set_active_id(lang):
                        # Falls wir z.B. de_AT haben, aber nur de_DE anbieten,
                        # fügen wir es temporär hinzu, damit es angezeigt wird
                        self.lang_combo.append(lang, f"Aktuell: {lang}")
                        self.lang_combo.set_active_id(lang)
        except Exception as e: print(f"Fehler beim Laden der Sprache: {e}")

        try:
            # Zeitzone laden (timedatectl show)
            res = subprocess.run(['timedatectl', 'show', '-p', 'Timezone', '--value'], capture_output=True, text=True)
            tz = res.stdout.strip()
            if not self.time_combo.set_active_id(tz):
                self.time_combo.append(tz, f"Aktuell: {tz}")
                self.time_combo.set_active_id(tz)
        except Exception as e: print(f"Fehler beim Laden der Zeitzone: {e}")
        
        self.is_loading = False

    def on_language_changed(self, combo):
        if self.is_loading: return
        lang = combo.get_active_id()
        if not lang: return
        print(f"Setze Sprache auf: {lang}")
        
        # Wir nutzen pkexec für Root-Rechte (öffnet Passwort-Dialog)
        try:
            subprocess.run(['pkexec', 'localectl', 'set-locale', f'LANG={lang}'], check=True)
            print("Sprache erfolgreich gesetzt (Neustart erforderlich für volle Wirkung).")
        except subprocess.CalledProcessError:
            print("Änderung der Sprache abgebrochen (Passwort falsch oder abgebrochen).")
            # Setze UI zurück auf alten Wert (einfacher Reload)
            self.load_system_settings()

    def on_timezone_changed(self, combo):
        if self.is_loading: return
        tz = combo.get_active_id()
        if not tz: return
        print(f"Setze Zeitzone auf: {tz}")

        try:
            subprocess.run(['pkexec', 'timedatectl', 'set-timezone', tz], check=True)
            print("Zeitzone erfolgreich gesetzt.")
        except subprocess.CalledProcessError:
            print("Änderung der Zeitzone abgebrochen.")
            self.load_system_settings()