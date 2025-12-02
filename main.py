#!/usr/bin/env python
import sys
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw
from src.config import get_config_dir
from src.window import MainWindow

class SettingsApp(Adw.Application):
    def __init__(self, **kwargs):
        get_config_dir()
        super().__init__(application_id="org.caelestia.settings", **kwargs)
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = MainWindow(application=app)
        self.win.present()

if __name__ == "__main__":
    app = SettingsApp()
    sys.exit(app.run(sys.argv))