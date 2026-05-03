import subprocess
from gi.repository import Gtk, Adw, GLib
from src.config import APP_DATA_DIR
from src.pages.general import GeneralPage
from src.pages.monitor import MonitorPage
from src.pages.audio import AudioPage
from src.pages.wifi import WifiPage
from src.pages.updates import UpdatePage
from src.pages.about import AboutPage
from src.pages.window_rules import WindowRulesPage
from src.pages.keybinds import KeybindsPage
from src.pages.wallpaper import WallpaperPage
from src.pages.workspaces import WorkspacesPage
from src.lang import t

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(**kwargs)
        self.set_title(t("Caelestia Settings"))
        self.set_default_size(1100, 840)

        # --- ToastOverlay als Haupt-Container ---
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(root)

        header = Adw.HeaderBar()
        root.append(header)

        # --- BUTTONS ---
        self.update_btn = Gtk.Button(label=t("Update App"))
        self.update_btn.add_css_class("suggested-action")
        self.update_btn.set_visible(False)
        self.update_btn.connect("clicked", self.on_update_app)
        header.pack_end(self.update_btn)

        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        main_box.set_vexpand(True)
        root.append(main_box)

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.set_hexpand(True)

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)

        main_box.append(sidebar)
        main_box.append(self.stack)

        # Seiten instantiieren
        self.mon_page = MonitorPage(self)
        self.about_page = AboutPage(self)

        # ── Stack befüllen ──────────────────────────────────────────────────
        self.stack.add_titled(GeneralPage(self),      "gen",     t("General"))
        self.stack.add_titled(WallpaperPage(self),     "wall",    "Wallpaper")
        self.stack.add_titled(self.mon_page,           "mon",     t("Monitor"))
        self.stack.add_titled(WorkspacesPage(self),   "ws",      "Workspaces")
        self.stack.add_titled(WifiPage(self),          "wifi",    "WLAN")
        self.stack.add_titled(AudioPage(self),         "audio",   t("Audio"))
        self.stack.add_titled(WindowRulesPage(self),   "rules",   "Fenster-Regeln")
        self.stack.add_titled(KeybindsPage(self),      "keys",    "Keybinds")
        self.stack.add_titled(UpdatePage(self),        "upd",     t("Updates"))
        self.stack.add_titled(self.about_page,         "about",   t("About"))
        # ───────────────────────────────────────────────────────────────────

        self.stack.connect("notify::visible-child", self.on_page_change)

    def add_toast(self, toast):
        self.toast_overlay.add_toast(toast)

    def on_page_change(self, stack, _):
        child = stack.get_visible_child()
        self.update_btn.set_visible(child == self.about_page)

    def on_update_app(self, btn):
        script = APP_DATA_DIR / "app_update.sh"
        if script.exists():
            try:
                subprocess.Popen(["kitty", str(script)])
            except Exception as e:
                print(f"Err: {e}")
        else:
            print("Update-Skript nicht gefunden.")