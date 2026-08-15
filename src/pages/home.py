from pathlib import Path

from gi.repository import Adw, GdkPixbuf, GLib, Gtk

from src.config import parse_monitors_conf
from src.hypr_provider import Provider, load_provider
from src.lang import t
from src.pages.fans import read_cpu_temp, read_gpu_stats
from src.pages.general import KEYBOARD_LAYOUTS, read_input_conf
from src.pages.wallpaper import get_current_wallpaper
from src.pages.wifi import get_active_wifi_connection, has_wifi_adapter

_THUMB_WIDTH = 96
_THUMB_HEIGHT = 54

# (stack name, icon, title, subtitle) — stack names must match src/window.py.
_QUICK_ACTIONS = [
    ("wall", "preferences-desktop-wallpaper-symbolic",
     "Wallpaper", "Change wallpaper and color scheme"),
    ("mon", "video-display-symbolic",
     "Monitor", "Arrange displays and resolutions"),
    ("wifi", "network-wireless-symbolic",
     "WLAN", "Scan and connect to networks"),
    ("keys", "preferences-desktop-keyboard-symbolic",
     "Keybinds", "View and edit shortcuts"),
    ("upd", "software-update-available-symbolic",
     "Updates", "Check for system updates"),
]


def _layout_display_name(code: str) -> str:
    for xkb_code, label in KEYBOARD_LAYOUTS:
        if xkb_code == code:
            return f"{label}  ({code})"
    return code


def _load_thumbnail(path: Path) -> GdkPixbuf.Pixbuf | None:
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(
            str(path), _THUMB_WIDTH, _THUMB_HEIGHT, True
        )
    except Exception:
        # Video wallpapers and unreadable files land here; the caller hides
        # the preview instead of showing a broken image.
        return None


class HomePage(Gtk.Box):
    def __init__(self, win, **kwargs):
        super().__init__(**kwargs)
        self.main_window = win
        self.set_orientation(Gtk.Orientation.VERTICAL)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.append(scroll)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        scroll.set_child(box)

        box.append(self._build_header())
        box.append(self._build_status_group())
        box.append(self._build_quick_actions())

        self.refresh()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_header(self) -> Gtk.Widget:
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header.set_halign(Gtk.Align.CENTER)

        title = Gtk.Label(label=t("Caelestia Settings"))
        title.add_css_class("title-1")
        header.append(title)

        version = Gtk.Label(
            label=f"{t('Version')} {self.main_window.about_page.local_version}"
        )
        version.add_css_class("dim-label")
        header.append(version)

        return header

    def _build_status_group(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title=t("System at a Glance"))

        refresh_btn = Gtk.Button(label=t("Refresh"))
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.connect("clicked", lambda _btn: self.refresh())
        group.set_header_suffix(refresh_btn)

        self._wallpaper_row = Adw.ActionRow(title=t("Wallpaper"))
        self._wallpaper_thumb = Gtk.Picture()
        self._wallpaper_thumb.set_size_request(_THUMB_WIDTH, _THUMB_HEIGHT)
        self._wallpaper_thumb.set_valign(Gtk.Align.CENTER)
        self._wallpaper_row.add_prefix(self._wallpaper_thumb)
        group.add(self._wallpaper_row)

        self._monitor_row = Adw.ActionRow(title=t("Monitors"))
        group.add(self._monitor_row)

        self._wifi_row = Adw.ActionRow(title="WLAN")
        group.add(self._wifi_row)

        self._layout_row = Adw.ActionRow(title=t("Keyboard Layout"))
        group.add(self._layout_row)

        self._cpu_row = Adw.ActionRow(title=t("CPU Temperature"))
        group.add(self._cpu_row)

        self._gpu_row = Adw.ActionRow(title=t("GPU Temperature"))
        group.add(self._gpu_row)

        return group

    def _build_quick_actions(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title=t("Quick Actions"))

        for page_name, icon, title, subtitle in _QUICK_ACTIONS:
            row = Adw.ActionRow(title=t(title), subtitle=t(subtitle))
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.set_activatable(True)
            row.connect("activated", self._on_nav_activated, page_name)
            group.add(row)

        return group

    def _on_nav_activated(self, _row, page_name: str):
        self.main_window.stack.set_visible_child_name(page_name)

    # ── Data ──────────────────────────────────────────────────────────────────

    def refresh(self):
        self._refresh_wallpaper()
        self._refresh_monitors()
        self._refresh_wifi()
        self._refresh_layout()
        self._refresh_temperatures()

    def _refresh_wallpaper(self):
        current = get_current_wallpaper()
        if not current:
            self._wallpaper_thumb.set_visible(False)
            self._wallpaper_row.set_subtitle(t("Not available"))
            return

        path = Path(current)
        self._wallpaper_row.set_subtitle(GLib.markup_escape_text(path.name))

        pixbuf = _load_thumbnail(path)
        self._wallpaper_thumb.set_pixbuf(pixbuf)
        self._wallpaper_thumb.set_visible(pixbuf is not None)

    def _refresh_monitors(self):
        provider = load_provider()
        if provider is None:
            self._monitor_row.set_subtitle(t("Hyprland configuration provider required"))
            return
        if provider is Provider.LUA:
            from src.pages.monitor import _get_live_monitors

            monitors = _get_live_monitors()
        else:
            monitors = parse_monitors_conf()["monitors"]
        if not monitors:
            self._monitor_row.set_subtitle(t("No monitors configured"))
            return

        summaries = []
        for monitor in monitors:
            resolution = monitor.get("resolution", "")
            if not resolution and monitor.get("width") and monitor.get("height"):
                resolution = f"{monitor['width']}x{monitor['height']}"
            summaries.append(
                f"{monitor['name']} · {resolution}" if resolution else monitor["name"]
            )
        summary = "  |  ".join(summaries)
        self._monitor_row.set_subtitle(GLib.markup_escape_text(summary))

    def on_provider_changed(self):
        self._refresh_monitors()

    def _refresh_wifi(self):
        if not has_wifi_adapter():
            self._wifi_row.set_subtitle(t("No Wi-Fi adapter found."))
            return

        ssid = get_active_wifi_connection()
        self._wifi_row.set_subtitle(
            GLib.markup_escape_text(ssid) if ssid else t("Not connected")
        )

    def _refresh_layout(self):
        layout = read_input_conf().get("kb_layout", "").lower()
        self._layout_row.set_subtitle(
            _layout_display_name(layout) if layout else t("Not available")
        )

    def _refresh_temperatures(self):
        cpu = read_cpu_temp()
        self._cpu_row.set_subtitle(f"{cpu} °C" if cpu is not None else t("Not available"))

        gpu = read_gpu_stats()
        if gpu is None:
            self._gpu_row.set_subtitle(t("No supported GPU detected"))
            return

        parts = [f"{gpu['temp']} °C"]
        if gpu["fan_pct"] is not None:
            parts.append(f"{t('Fan')}: {gpu['fan_pct']} %")
        self._gpu_row.set_subtitle("  |  ".join(parts))
