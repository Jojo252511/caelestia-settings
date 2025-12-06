import subprocess
import threading
from gi.repository import Gtk, Adw, GLib
from src.lang import t

class WifiPage(Gtk.Box):
    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.main_window = main_window
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        if not self.check_wifi_adapter():
            status_page = Adw.StatusPage()
            status_page.set_icon_name("network-wireless-disabled-symbolic")
            status_page.set_title(t("No Wi-Fi adapter found."))
            self.append(status_page)
            return

        header_group = Adw.PreferencesGroup()
        self.append(header_group)
        
        scan_row = Adw.ActionRow(title=t("Wi-Fi Networks"))
        scan_btn = Gtk.Button(label=t("Scan"))
        scan_btn.set_valign(Gtk.Align.CENTER)
        scan_btn.connect("clicked", self.on_scan_clicked)
        scan_row.add_suffix(scan_btn)
        header_group.add(scan_row)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.add_css_class("boxed-list")
        
        self.network_list = Gtk.ListBox()
        self.network_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.network_list.add_css_class("boxed-list")
        
        scroller.set_child(self.network_list)
        self.append(scroller)

        self.spinner = Gtk.Spinner()
        self.spinner.set_halign(Gtk.Align.CENTER)
        self.append(self.spinner)

        self.scan_networks()

    def check_wifi_adapter(self):
        try:
            res = subprocess.run("nmcli device | grep wifi", shell=True, capture_output=True)
            return res.returncode == 0
        except: return False

    def on_scan_clicked(self, btn):
        self.scan_networks()

    def scan_networks(self):
        self.spinner.start()
        child = self.network_list.get_first_child()
        while child:
            self.network_list.remove(child)
            child = self.network_list.get_first_child()

        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        networks = []
        try:
            cmd = ['nmcli', '-t', '-f', 'IN-USE,SSID,SECURITY,BARS', 'device', 'wifi', 'list', '--rescan', 'yes']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            
            seen_ssids = set()
            for line in res.stdout.splitlines():
                parts = line.replace('\\:', '__COLON__').split(':')
                if len(parts) < 4: continue
                
                in_use = parts[0] == '*'
                ssid = parts[1].replace('__COLON__', ':')
                security = parts[2]
                bars = parts[3]

                if not ssid: continue
                if ssid in seen_ssids: continue
                seen_ssids.add(ssid)

                networks.append({
                    "ssid": ssid,
                    "connected": in_use,
                    "security": security,
                    "bars": bars
                })
        except Exception as e: print(f"Scan Err: {e}")

        GLib.idle_add(self._update_ui, networks)

    def _update_ui(self, networks):
        self.spinner.stop()
        networks.sort(key=lambda x: not x["connected"])

        for net in networks:
            row = Adw.ActionRow(title=net["ssid"])
            row.set_subtitle(f"{net['bars']}  {net['security']}")
            
            if net["connected"]:
                icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
                row.add_suffix(icon)
                
                disconnect_btn = Gtk.Button(label=t("Disconnect"))
                disconnect_btn.set_valign(Gtk.Align.CENTER)
                disconnect_btn.add_css_class("destructive-action")
                disconnect_btn.connect("clicked", self.on_disconnect, net["ssid"])
                row.add_suffix(disconnect_btn)
            else:
                connect_btn = Gtk.Button(label=t("Connect"))
                connect_btn.set_valign(Gtk.Align.CENTER)
                connect_btn.connect("clicked", self.on_connect_clicked, net)
                row.add_suffix(connect_btn)

            self.network_list.append(row)

    def on_disconnect(self, btn, ssid):
        def _thread():
            subprocess.run(['nmcli', 'connection', 'down', 'id', ssid])
            GLib.idle_add(self.scan_networks)
        threading.Thread(target=_thread, daemon=True).start()

    def on_connect_clicked(self, btn, net_data):
        ssid = net_data["ssid"]
        security = net_data["security"]
        
        if not security or security == "--":
            self.connect_to(ssid, None)
        else:
            self.show_password_dialog(ssid)

    def show_password_dialog(self, ssid):
        dialog = Adw.MessageDialog(
            heading=t("Password Required"),
            body=f"{t('Please enter the password for')} '{ssid}'"
        )
        dialog.add_response("cancel", t("Cancel"))
        dialog.add_response("connect", t("Connect"))
        
        # Dialog ans Hauptfenster binden
        dialog.set_transient_for(self.main_window)
        
        pwd_entry = Gtk.PasswordEntry()
        pwd_entry.set_hexpand(True)
        
        # --- FIX: Manuelles Enter-Handling ---
        def on_entry_activate(entry):
            dialog.response("connect")
        pwd_entry.connect("activate", on_entry_activate)
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.append(pwd_entry)
        
        dialog.set_extra_child(box)
        dialog.set_default_response("connect")
        
        def response_cb(dlg, response):
            if response == "connect":
                password = pwd_entry.get_text()
                self.connect_to(ssid, password)
            
        dialog.connect("response", response_cb)
        dialog.present() 

    def connect_to(self, ssid, password):
        self.show_toast(f"{t('Scanning...')} {ssid}...")
        
        def _thread():
            cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]
            if password:
                cmd.extend(['password', password])
            
            res = subprocess.run(cmd, capture_output=True, text=True)
            
            success = res.returncode == 0
            # --- FIX: Lambda für Parameter-Übergabe ---
            GLib.idle_add(lambda: self.on_connect_finished(success, res.stderr))

        threading.Thread(target=_thread, daemon=True).start()

    def on_connect_finished(self, success, error_msg):
        if success:
            self.show_toast(t("Connection successful"))
            self.scan_networks()
        else:
            self.show_toast(f"{t('Connection failed')}: {error_msg.strip()}")
        # Wichtig: GLib Callback muss False zurückgeben, um zu stoppen
        return False 

    def show_toast(self, message):
        toast = Adw.Toast.new(message)
        # Jetzt rufen wir die neue Methode in MainWindow auf
        self.main_window.add_toast(toast)