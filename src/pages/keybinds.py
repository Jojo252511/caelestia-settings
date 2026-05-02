from gi.repository import Gtk, Adw

class KeybindsPage(Gtk.Box):
    """Platzhalter für Phase 3: Keybinds-Editor."""

    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.main_window = main_window
        self.set_orientation(Gtk.Orientation.VERTICAL)

        status = Adw.StatusPage()
        status.set_vexpand(True)
        status.set_icon_name("preferences-desktop-keyboard-symbolic")
        status.set_title("Keybinds")
        status.set_description(
            "Tastenkürzel-Editor — kommt später.\n"
            "Hier kannst du deine Hyprland-Shortcuts einsehen und neu belegen."
        )
        self.append(status)