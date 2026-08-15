import json
import threading
import urllib.error
import urllib.request
from gi.repository import Gtk, Adw, GLib
from src.pages.home import HomePage
from src.pages.general import GeneralPage
from src.pages.monitor import MonitorPage
from src.pages.audio import AudioPage
from src.pages.wifi import WifiPage
from src.pages.updates import UpdatePage
from src.pages.about import AboutPage
from src.pages.fans import FansPage
from src.pages.window_rules import WindowRulesPage
from src.pages.keybinds import KeybindsPage
from src.pages.wallpaper import WallpaperPage
from src.pages.workspaces import WorkspacesPage
from src.lang import t
from src.hypr_provider import (
    ConfigCapability,
    Provider,
    capability_available,
    capability_error_message,
    load_provider,
    needs_provider_prompt,
    prompt_provider_choice,
)

# Source of truth for "is a newer version out": the manifest.json committed
# on main (the prod branch, see branching policy — dev is pre-release).
MANIFEST_URL = "https://raw.githubusercontent.com/Jojo252511/caelestia-settings/main/manifest.json"

PROVIDER_PAGE_CAPABILITIES = {
    "general": ConfigCapability.INPUT,
    "wallpaper": ConfigCapability.WALLPAPER_AUTOSTART,
    "workspaces": ConfigCapability.WORKSPACES,
    "monitor": ConfigCapability.MONITORS,
    "window-rules": ConfigCapability.WINDOW_RULES,
    "keybinds": ConfigCapability.KEYBINDS,
}


def provider_page_access(provider: Provider | None) -> dict[str, bool]:
    """Single UI source of truth for provider-gated Hyprland pages."""
    return {
        page_name: capability_available(provider, capability)
        for page_name, capability in PROVIDER_PAGE_CAPABILITIES.items()
    }


class _ProviderPageGuard(Gtk.Box):
    """Keeps the lock explanation usable while the guarded page is insensitive."""

    def __init__(self, child: Gtk.Widget, capability: ConfigCapability):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.capability = capability
        self.child = child
        self.banner = Adw.Banner()
        self.append(self.banner)
        child.set_vexpand(True)
        self.append(child)

    def set_provider(self, provider: Provider | None) -> None:
        available = capability_available(provider, self.capability)
        self.child.set_sensitive(available)
        self.banner.set_title(
            "" if available else capability_error_message(provider, self.capability)
        )
        self.banner.set_revealed(not available)


def _parse_version(version: str) -> tuple:
    """Turns "1.2.10" into (1, 2, 10) for numeric comparison.

    Plain string comparison would rank "1.10.0" below "1.9.0". Returns an
    empty tuple for anything that isn't dot-separated integers, which always
    compares as "not newer" against a real version.
    """
    try:
        return tuple(int(part) for part in version.split("."))
    except (ValueError, AttributeError):
        return ()


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
        self.workspaces_page = WorkspacesPage(self)
        self.window_rules_page = WindowRulesPage(self)
        self.general_page = GeneralPage(self)
        self.wallpaper_page = WallpaperPage(self)
        self.keybinds_page = KeybindsPage(self)
        self.about_page = AboutPage(self)
        self.home_page = HomePage(self)

        guarded_pages = {
            "general": self.general_page,
            "wallpaper": self.wallpaper_page,
            "workspaces": self.workspaces_page,
            "monitor": self.mon_page,
            "window-rules": self.window_rules_page,
            "keybinds": self.keybinds_page,
        }
        self._provider_page_guards = {
            name: _ProviderPageGuard(page, PROVIDER_PAGE_CAPABILITIES[name])
            for name, page in guarded_pages.items()
        }

        # ── Stack befüllen ──────────────────────────────────────────────────
        # HomePage reads about_page.local_version, so it is built after it.
        self.stack.add_titled(self.home_page,          "home",    t("Home"))
        self.stack.add_titled(self._provider_page_guards["general"], "gen", t("General"))
        self.stack.add_titled(self._provider_page_guards["wallpaper"], "wall", "Wallpaper")
        self.stack.add_titled(self._provider_page_guards["workspaces"], "ws", "Workspaces")
        self.stack.add_titled(self._provider_page_guards["monitor"], "mon", t("Monitor"))
        self.stack.add_titled(WifiPage(self),          "wifi",    "WLAN")
        self.stack.add_titled(AudioPage(self),         "audio",   t("Audio"))
        self.stack.add_titled(self._provider_page_guards["window-rules"], "rules", "Window Rules")
        self.stack.add_titled(self._provider_page_guards["keybinds"], "keys", "Keybinds")
        self.stack.add_titled(FansPage(self),          "fans",    t("Fans"))
        self.stack.add_titled(UpdatePage(self),        "upd",     t("Updates"))
        self.stack.add_titled(self.about_page,         "about",   t("About"))
        # ───────────────────────────────────────────────────────────────────

        self.stack.set_visible_child_name("home")

        self._apply_provider_page_locks(load_provider())

        threading.Thread(target=self._check_for_update, daemon=True).start()

        if needs_provider_prompt():
            prompt_provider_choice(self, self._on_provider_chosen)

    def _on_provider_chosen(self, provider):
        self._apply_provider_page_locks(provider)
        self.mon_page.on_provider_changed()
        self.workspaces_page.on_provider_changed()
        self.window_rules_page.on_provider_changed()
        self.home_page.on_provider_changed()
        self.add_toast(Adw.Toast.new(t("Hyprland configuration provider saved.")))

    def _apply_provider_page_locks(self, provider: Provider | None) -> None:
        for guard in self._provider_page_guards.values():
            guard.set_provider(provider)

    def add_toast(self, toast):
        self.toast_overlay.add_toast(toast)

    def _check_for_update(self):
        try:
            with urllib.request.urlopen(MANIFEST_URL, timeout=5) as resp:
                remote_manifest = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return  # No network, GitHub unreachable, etc. — check silently fails.

        remote_version = _parse_version(remote_manifest.get("version", ""))
        local_version = _parse_version(self.about_page.local_version)
        if remote_version > local_version:
            GLib.idle_add(self.update_btn.set_visible, True)

    def on_update_app(self, btn):
        # The header button is just a shortcut to the same update flow the
        # About page offers — no separate implementation to keep in sync.
        self.about_page.on_update_clicked(btn)
