import subprocess
from gi.repository import Gtk, Adw

class AudioPage(Gtk.Box):
    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        
        self.is_loading = False 
        
        group = Adw.PreferencesGroup(title="Audio-Ausgabe")
        self.append(group)

        device_row = Adw.ActionRow(title="Ausgabegerät")
        self.device_combo = Gtk.ComboBoxText()
        device_row.add_suffix(self.device_combo)
        group.add(device_row)
        
        volume_row = Adw.ActionRow(title="Standard-Lautstärke")
        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume_scale.set_hexpand(True)
        self.volume_scale.set_draw_value(True)
        volume_row.add_suffix(self.volume_scale)
        group.add(volume_row)
        
        self.load_audio_state()
        
        self.device_combo.connect("changed", self.on_device_changed)
        self.volume_scale.connect("value-changed", self.on_volume_changed)

    def load_audio_state(self):
        self.is_loading = True
        self.device_combo.remove_all()
        sinks = {}
        try:
            res = subprocess.run(['pactl', 'get-default-sink'], capture_output=True, text=True, check=True, timeout=2)
            default_sink = res.stdout.strip()

            res = subprocess.run(['pactl', 'list', 'sinks'], capture_output=True, text=True, check=True, timeout=2)
            current_sink = None
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("Name:"): current_sink = line.split("Name:")[1].strip()
                if line.startswith("Description:"):
                    desc = line.split("Description:")[1].strip()
                    if current_sink: sinks[desc] = current_sink
            
            active_index = 0
            for i, (desc, name) in enumerate(sinks.items()):
                self.device_combo.append(name, desc)
                if name == default_sink: active_index = i
            self.device_combo.set_active(active_index)

        except Exception as e:
            print(f"Fehler Audio-Geräte: {e}")
            self.device_combo.append("error", "Fehler beim Laden")
            
        try:
            res = subprocess.run(['pamixer', '--get-volume'], capture_output=True, text=True, check=True, timeout=2)
            self.volume_scale.set_value(int(res.stdout.strip()))
        except Exception as e:
            print(f"Fehler Lautstärke: {e}")

        self.is_loading = False

    def on_device_changed(self, combo):
        if self.is_loading: return
        sink = combo.get_active_id()
        if sink:
            try:
                subprocess.run(['pactl', 'set-default-sink', sink], check=True, timeout=2)
                self.load_audio_state()
            except Exception as e: print(f"Fehler: {e}")

    def on_volume_changed(self, scale):
        if self.is_loading: return
        try:
            subprocess.run(['pamixer', '--set-volume', str(int(scale.get_value()))], check=True, timeout=1)
        except Exception as e: print(f"Fehler: {e}")