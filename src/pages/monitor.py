import subprocess
import json
from gi.repository import Gtk, Adw, GLib
from src.config import load_monitor_config
from src.lang import t

class MonitorPage(Gtk.ScrolledWindow):
    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.main_window = main_window
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.monitor_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.set_child(self.monitor_list_box)
        self.load_monitors()

    def load_monitors(self):
        child = self.monitor_list_box.get_first_child()
        while child:
            self.monitor_list_box.remove(child)
            child = self.monitor_list_box.get_first_child()
            
        try:
            self.saved_config = load_monitor_config()
            res = subprocess.run(['hyprctl', 'monitors', 'all', '-j'], capture_output=True, text=True, check=True, timeout=2)
            live_monitors = json.loads(res.stdout)
            # Nur aktive Monitore
            active_mons = [m for m in live_monitors if not m.get('disabled', False)]
            all_names = [m['name'] for m in active_mons]
            
            if not active_mons:
                self.monitor_list_box.append(Gtk.Label(label=t("No active monitors.")))
                return

            for m_data in active_mons:
                settings = self.saved_config.get(m_data['name'], {})
                widget = MonitorWidget(m_data, settings, all_names, self)
                self.monitor_list_box.append(widget)

        except Exception as e:
            self.monitor_list_box.append(Gtk.Label(label=f"Error: {e}"))
            
    def get_all_widget_settings(self):
        config_data = {}
        child = self.monitor_list_box.get_first_child()
        while child:
            if isinstance(child, MonitorWidget):
                name, settings = child.get_settings()
                config_data[name] = settings
            child = child.get_next_sibling()
        return config_data

class MonitorWidget(Adw.PreferencesGroup):
    def __init__(self, monitor_data, saved_settings, all_names, parent_page):
        super().__init__()
        self.monitor_data = monitor_data
        self.name = monitor_data['name']
        self.set_title(f"{t('Monitor')}: {self.name} ({monitor_data['description']})")
        
        # 1. Auflösung (Immer sichtbar)
        res_row = Adw.ActionRow(title=t("Resolution and Refresh Rate"))
        self.res_combo = Gtk.ComboBoxText()
        
        modes = monitor_data.get('availableModes', [])
        cur_refresh = round(monitor_data['refreshRate'], 3)
        cur_mode = f"{monitor_data['width']}x{monitor_data['height']}@{cur_refresh:.3f}Hz"
        
        if not modes: modes.append(cur_mode)
        for m in modes: self.res_combo.append(m, m)
        
        saved_res = saved_settings.get("resolution")
        if not saved_res or not self.res_combo.set_active_id(saved_res):
            if not self.res_combo.set_active_id(cur_mode):
                self.res_combo.set_active(0)
        
        res_row.add_suffix(self.res_combo)
        self.add(res_row)

        # 2. Anordnung & 3. Ziel (Nur bei > 1 Monitor)
        arrange_row = Adw.ActionRow(title=t("Arrangement"))
        arrange_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        arrange_row.add_suffix(arrange_box)
        self.add(arrange_row)

        self.arrange_combo = Gtk.ComboBoxText()
        # Option für aktuellen Status hinzufügen
        self.cur_pos_id = "current_pos"
        self.cur_pos_str = f"{t('Custom')} ({monitor_data['x']}x{monitor_data['y']})"
        self.arrange_combo.append(self.cur_pos_id, self.cur_pos_str)

        opts = [("auto", t("Automatic")), ("rechts", t("Right of")), ("links", t("Left of")), 
                ("darueber", t("Above")), ("darunter", t("Below")), ("spiegeln", t("Mirror")), ("deaktivieren", t("Disable"))]
        for k, v in opts: self.arrange_combo.append(k, v)
        
        arrange_box.append(self.arrange_combo)

        # Ziel-Monitor Dropdown
        self.target_combo = Gtk.ComboBoxText()
        others = [n for n in all_names if n != self.name]
        
        if others:
            for n in others: self.target_combo.append(n, n)
        else:
            self.target_combo.append("...", "...") # Fallback, sollte unsichtbar sein
        
        arrange_box.append(self.target_combo)

        # --- LOGIK: Sichtbarkeit steuern ---
        if len(all_names) < 2:
            # Nur 1 Monitor: Verstecke die Anordnungs-Zeile
            arrange_row.set_visible(False)
            # Setze sicherheitshalber auf "current_pos", damit sich nichts verschiebt
            self.arrange_combo.set_active_id(self.cur_pos_id)
        else:
            # Mehrere Monitore: Zeige alles und lade Einstellungen
            saved_arrange = saved_settings.get("arrange")
            if saved_arrange: self.arrange_combo.set_active_id(saved_arrange)
            else: self.arrange_combo.set_active_id(self.cur_pos_id)
            
            saved_target = saved_settings.get("target")
            if not saved_target or not self.target_combo.set_active_id(saved_target):
                self.target_combo.set_active(0)

            self.arrange_combo.connect("changed", self.on_arrange_changed)
            self.on_arrange_changed(self.arrange_combo)

    def on_arrange_changed(self, combo):
        active = combo.get_active_id()
        vis = active in ["rechts", "links", "darueber", "darunter", "spiegeln"]
        self.target_combo.set_visible(vis)

    def get_settings(self):
        return self.name, {
            "resolution": self.res_combo.get_active_id(),
            "arrange": self.arrange_combo.get_active_id(),
            "target": self.target_combo.get_active_id()
        }