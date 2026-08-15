import json
import os
import shlex
import subprocess
import threading
from pathlib import Path
import caelestia_core
from src.hypr_provider import (
    ConfigCapability,
    ManagedBlockError,
    Provider,
    find_competing_lua_autostart_entries,
    find_lines_outside_managed_blocks,
    resolve_path,
    require_config_capability,
    write_managed_legacy_block_and_reload,
    write_managed_lua_block_and_reload,
)
from src.lang import t
from gi.repository import Gtk, Adw, GLib, GdkPixbuf

_SHELL_JSON = Path.home() / ".config" / "caelestia" / "shell.json"
_DEFAULT_IMAGE_DIR = Path.home() / "Bilder" / "Wallpapers"
VIDEO_DIR = Path.home() / "Videos" / "Wallpaper"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}

THUMB_SIZE    = 160
THUMB_CACHE   = Path.home() / ".cache" / "caelestia-settings" / "thumbs"
_MPV_PID_FILE = Path.home() / ".cache" / "caelestia-settings" / "mpvpaper.pid"
_MPVPAPER_MARKER = "# caelestia-settings: video-wallpaper"
_MPVPAPER_ARGS = "loop --no-audio --panscan=1.0"
WALLPAPER_AUTOSTART_BLOCK = "wallpaper-autostart"


def _get_image_dir() -> Path:
    """Liest wallpaperDir aus ~/.config/caelestia/shell.json."""
    try:
        if _SHELL_JSON.exists():
            data = json.loads(_SHELL_JSON.read_text())
            wall_dir = data.get("paths", {}).get("wallpaperDir", "")
            if wall_dir:
                return Path(wall_dir)
    except Exception as e:
        print(f"shell.json lesen fehler: {e}")
    return _DEFAULT_IMAGE_DIR


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_dirs():
    _get_image_dir().mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)


def _mpvpaper_shell_cmd(video_path: Path) -> str:
    """Builds the mpvpaper shell command line, shell-quoting the video
    path and mpv option string so paths/args with spaces, quotes,
    backslashes, unicode, `$()`, `;`, or newlines can never break out of
    the command mpvpaper is invoked with."""
    return f"mpvpaper '*' {shlex.quote(str(video_path))} -o {shlex.quote(_MPVPAPER_ARGS)}"


def _validate_media_path(path: Path, extensions: set[str], label: str) -> Path:
    """Strict, side-effect-free validation for a wallpaper/video path,
    run before ANY writer/lock/backup/process/PID/UI side effect.
    Rejects: anything that isn't already a `pathlib.Path` (never accepts
    a bare string, even one that "looks like" a path), a relative path, a
    filename starting with `-` (could be misread as an option by a
    program this app invokes with no shell involved, e.g.
    mpvpaper/caelestia — argv-level option injection, not just shell
    injection), anything that isn't an existing regular file, and an
    extension that doesn't match the requested media type."""
    if not isinstance(path, Path):
        raise ValueError(f"{label} path must be a pathlib.Path, got {type(path).__name__}")
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute: {path}")
    if path.name.startswith("-"):
        raise ValueError(f"{label} filename must not start with '-': {path.name}")
    if not path.is_file():
        raise ValueError(f"{label} path is not an existing regular file: {path}")
    if path.suffix.lower() not in extensions:
        raise ValueError(f"{label} path has an unexpected extension: {path.suffix!r}")
    return path


def _competing_wallpaper_autostart_lines(text: str, provider: Provider) -> list[str]:
    """Foreign (non-app-owned) content elsewhere in execs that plausibly
    also controls video-wallpaper autostart — see
    `find_competing_lua_autostart_entries`/`find_lines_outside_managed_blocks`
    in hypr_provider.py for the detection semantics."""
    if provider is Provider.LUA:
        return find_competing_lua_autostart_entries(
            text, [WALLPAPER_AUTOSTART_BLOCK], lambda cmd: "mpvpaper" in cmd
        )
    return [
        line
        for line in find_lines_outside_managed_blocks(text, [WALLPAPER_AUTOSTART_BLOCK], "#")
        if line.strip().startswith("exec-once") and "mpvpaper" in line
    ]


def _raise_if_competing_wallpaper_autostart(text: str, provider: Provider) -> None:
    if _competing_wallpaper_autostart_lines(text, provider):
        raise ManagedBlockError(
            t(
                "Another manually written video-wallpaper autostart entry exists outside "
                "the app-managed block; resolve the conflict manually before saving."
            )
        )


def _write_mpvpaper_autostart(video_path: Path | None, *, live_apply=None):
    """Persists (or clears, when `video_path` is None) the app-owned
    video-wallpaper autostart entry under the currently active provider.
    Only ever touches the "wallpaper-autostart" managed block — manually
    written execs content, and the app's own separate "primary-monitor"
    block, are always left untouched. Fails closed (no write at all) if
    another manually written entry outside the app-managed block also
    plausibly controls video-wallpaper autostart.

    `live_apply`, if given, is forwarded to the underlying writer and
    runs INSIDE its write lock, right after a successful reload — see
    `write_managed_lua_block_and_reload`/`write_managed_legacy_block_and_reload`
    for why this is what makes a live-apply-failure rollback use the
    correct (race-free) base content instead of a possibly-stale snapshot
    taken before the lock was even acquired."""
    provider = require_config_capability(ConfigCapability.WALLPAPER_AUTOSTART)
    path = resolve_path("execs", provider)

    def pre_write_check(text: str) -> None:
        _raise_if_competing_wallpaper_autostart(text, provider)

    if provider is Provider.LUA:
        lines = (
            [caelestia_core.render_autostart_cmd(_mpvpaper_shell_cmd(video_path))]
            if video_path is not None
            else []
        )
        write_managed_lua_block_and_reload(
            path,
            WALLPAPER_AUTOSTART_BLOCK,
            lines,
            pre_write_check=pre_write_check,
            live_apply=live_apply,
        )
        return

    lines = (
        [f"exec-once = {_mpvpaper_shell_cmd(video_path)}  {_MPVPAPER_MARKER}"]
        if video_path is not None
        else []
    )
    write_managed_legacy_block_and_reload(
        path,
        WALLPAPER_AUTOSTART_BLOCK,
        lines,
        legacy_predicate=lambda line: _MPVPAPER_MARKER in line,
        pre_write_check=pre_write_check,
        live_apply=live_apply,
    )


def get_current_wallpaper() -> str:
    p = Path.home() / ".local" / "state" / "caelestia" / "wallpaper" / "path.txt"
    try:
        return p.read_text().strip() if p.exists() else ""
    except Exception:
        return ""


def _get_current_scheme_mode() -> str:
    p = Path.home() / ".local" / "state" / "caelestia" / "scheme.json"
    try:
        return json.loads(p.read_text()).get("mode", "dark") if p.exists() else "dark"
    except Exception:
        return "dark"


def _scan(directory: Path, extensions: set) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        [f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in extensions],
        key=lambda p: p.name.lower()
    )


def _thumb_path(path: Path) -> Path:
    return THUMB_CACHE / f"{path.stem}_{path.stat().st_size}.jpg"


def _make_image_thumb(path: Path) -> GdkPixbuf.Pixbuf | None:
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), THUMB_SIZE, THUMB_SIZE, True)
    except Exception as e:
        print(f"Thumbnail fehler {path.name}: {e}")
        return None


def _make_video_thumb(path: Path) -> GdkPixbuf.Pixbuf | None:
    cache = _thumb_path(path)
    if not cache.exists():
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(path),
                "-ss", "00:00:02", "-vframes", "1",
                "-vf", f"scale={THUMB_SIZE * 2}:-1",
                str(cache)
            ], capture_output=True, timeout=15)
        except Exception as e:
            print(f"ffmpeg fehler {path.name}: {e}")
            return None
    if cache.exists():
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(cache), THUMB_SIZE, THUMB_SIZE, True)
        except Exception:
            pass
    return None


# ── Desktop Clock Helpers ────────────────────────────────────────────────────

_SHELL_CONFIG = Path.home() / ".config" / "caelestia" / "shell.json"

def _read_shell_json() -> dict:
    try:
        if _SHELL_CONFIG.exists():
            return json.loads(_SHELL_CONFIG.read_text())
    except Exception as e:
        print(f"shell.json lesen: {e}")
    return {}

def _write_shell_json(data: dict):
    try:
        _SHELL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        _SHELL_CONFIG.write_text(json.dumps(data, indent=4))
        # Caelestia neu laden damit Änderungen greifen
        subprocess.run(["caelestia", "shell", "reload"], capture_output=True, timeout=3)
    except Exception as e:
        print(f"shell.json schreiben: {e}")

def _get_clock_settings() -> dict:
    data = _read_shell_json()
    return data.get("background", {}).get("desktopClock", {
        "enabled": True,
        "position": "top-right",
        "scale": 1.0,
        "invertColors": False,
    })

def _save_clock_settings(settings: dict):
    data = _read_shell_json()
    data.setdefault("background", {})["desktopClock"] = settings
    _write_shell_json(data)


CLOCK_POSITIONS = [
    ("top-right",    t("Top right")),
    ("top-left",     t("Top left")),
    ("bottom-right", t("Bottom right")),
    ("bottom-left",  t("Bottom left")),
]


# ── Shared Grid ───────────────────────────────────────────────────────────────

class MediaGrid(Gtk.Box):
    def __init__(self, on_select_cb):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_select = on_select_cb

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scroller)

        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_max_children_per_line(20)
        self.flow.set_min_children_per_line(2)
        self.flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.flow.set_row_spacing(8)
        self.flow.set_column_spacing(8)
        self.flow.set_margin_top(8)
        self.flow.set_margin_bottom(12)
        self.flow.set_margin_start(12)
        self.flow.set_margin_end(12)
        self.flow.connect("child-activated", self._on_activated)
        scroller.set_child(self.flow)

        self.spinner = Gtk.Spinner()
        self.spinner.set_halign(Gtk.Align.CENTER)
        self.spinner.set_size_request(-1, 48)
        self.append(self.spinner)

        self.empty_label = Gtk.Label()
        self.empty_label.add_css_class("dim-label")
        self.empty_label.set_margin_top(32)
        self.empty_label.set_halign(Gtk.Align.CENTER)
        self.empty_label.set_visible(False)
        self.append(self.empty_label)

    def load(self, files: list[Path], current: str, thumb_fn, is_video: bool = False):
        while child := self.flow.get_first_child():
            self.flow.remove(child)
        self.empty_label.set_visible(False)
        self.spinner.set_visible(True)
        self.spinner.start()

        def _thread():
            GLib.idle_add(self._populate, files, current, thumb_fn, is_video)

        threading.Thread(target=_thread, daemon=True).start()

    def _populate(self, files, current, thumb_fn, is_video):
        self.spinner.stop()
        self.spinner.set_visible(False)

        if not files:
            self.empty_label.set_label(
                "Keine Videos gefunden.\nVideos in ~/Videos/Wallpaper/ ablegen."
                if is_video else
                "Keine Bilder gefunden.\nBilder in ~/Bilder/Wallpapers/ ablegen."
            )
            self.empty_label.set_visible(True)
            return

        for path in files:
            card = MediaCard(path, current, is_video)
            self.flow.append(card)

        threading.Thread(
            target=self._load_thumbs, args=(files, thumb_fn), daemon=True
        ).start()

    def _load_thumbs(self, files, thumb_fn):
        child = self.flow.get_first_child()
        for path in files:
            if child is None:
                break
            card = child.get_child()
            if isinstance(card, MediaCard):
                pixbuf = thumb_fn(path)
                if pixbuf:
                    GLib.idle_add(card.set_thumbnail, pixbuf)
            child = child.get_next_sibling()

    def _on_activated(self, _, child):
        card = child.get_child()
        if isinstance(card, MediaCard):
            self._on_select(card.path)

    def mark_current(self, path: str):
        child = self.flow.get_first_child()
        while child:
            card = child.get_child()
            if isinstance(card, MediaCard):
                if str(card.path) == path:
                    card.add_css_class("suggested-action")
                else:
                    card.remove_css_class("suggested-action")
            child = child.get_next_sibling()


# ── Media-Karte ───────────────────────────────────────────────────────────────

class MediaCard(Gtk.Box):
    def __init__(self, path: Path, current: str, is_video: bool = False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.path = path
        self.set_size_request(THUMB_SIZE, THUMB_SIZE + 30)

        is_current = (str(path) == current)

        self.image = Gtk.Image()
        self.image.set_pixel_size(THUMB_SIZE)
        self.image.set_from_icon_name(
            "video-x-generic-symbolic" if is_video else "image-x-generic-symbolic"
        )
        self.image.set_size_request(THUMB_SIZE, THUMB_SIZE)
        self.image.add_css_class("card")

        if is_current:
            overlay = Gtk.Overlay()
            overlay.set_child(self.image)
            check = Gtk.Image.new_from_icon_name("object-select-symbolic")
            check.set_halign(Gtk.Align.END)
            check.set_valign(Gtk.Align.END)
            check.set_margin_end(4)
            check.set_margin_bottom(4)
            overlay.add_overlay(check)
            self.append(overlay)
            self.add_css_class("suggested-action")
        else:
            self.append(self.image)

        if is_video:
            badge = Gtk.Label(label="▶ Video")
            badge.add_css_class("caption")
            badge.add_css_class("accent")
            self.append(badge)

        stem = path.stem
        name_label = Gtk.Label(label=stem[:22] + ("…" if len(stem) > 22 else ""))
        name_label.add_css_class("caption")
        name_label.set_ellipsize(3)
        self.append(name_label)

    def set_thumbnail(self, pixbuf: GdkPixbuf.Pixbuf):
        self.image.set_from_pixbuf(pixbuf)


# ── Haupt-Seite ───────────────────────────────────────────────────────────────

class WallpaperPage(Gtk.Box):
    def __init__(self, main_window, **kwargs):
        super().__init__(**kwargs)
        self.main_window = main_window
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(0)

        _ensure_dirs()

        self._current     = get_current_wallpaper()
        self._scheme_mode = _get_current_scheme_mode()
        self._mpv_proc: subprocess.Popen | None = None

        # ── Toolbar ──────────────────────────────────────────────────────
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_margin_top(10)
        bar.set_margin_bottom(6)
        bar.set_margin_start(12)
        bar.set_margin_end(12)

        # Tab-Buttons (linked)
        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_box.add_css_class("linked")

        self._tab_img = Gtk.ToggleButton(label=t("🖼 Images"))
        self._tab_img.set_active(True)
        self._tab_img.connect("toggled", self._on_tab_toggle)
        tab_box.append(self._tab_img)

        self._tab_vid = Gtk.ToggleButton(label=t("🎬 Videos"))
        self._tab_vid.set_group(self._tab_img)
        self._tab_vid.connect("toggled", self._on_tab_toggle)
        tab_box.append(self._tab_vid)

        bar.append(tab_box)

        self._random_btn = Gtk.Button(label=t("🔀 Random"))
        self._random_btn.set_tooltip_text("Zufälliges Bild aus ~/Bilder/Wallpapers/")
        self._random_btn.connect("clicked", self._on_random)
        bar.append(self._random_btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        # Light/Dark
        self._mode_btn = Gtk.ToggleButton()
        self._mode_btn.set_tooltip_text(t("Light / Dark Mode"))
        self._mode_btn.set_active(self._scheme_mode == "light")
        self._mode_btn.set_icon_name(
            "weather-clear-symbolic" if self._scheme_mode == "light"
            else "weather-clear-night-symbolic"
        )
        self._mode_btn.connect("toggled", self._on_mode_toggled)
        bar.append(self._mode_btn)

        reload_btn = Gtk.Button()
        reload_btn.set_icon_name("view-refresh-symbolic")
        reload_btn.set_tooltip_text(t("Reload"))
        reload_btn.connect("clicked", lambda _: self._reload())
        bar.append(reload_btn)

        self.append(bar)

        # ── Pfad-Label ───────────────────────────────────────────────────
        self._path_label = Gtk.Label()
        self._path_label.set_markup(
            f"<small><tt>{str(_get_image_dir()).replace(str(Path.home()), '~')}</tt></small>"
        )
        self._path_label.add_css_class("dim-label")
        self._path_label.set_halign(Gtk.Align.CENTER)
        self._path_label.set_margin_bottom(4)
        self.append(self._path_label)

        # ── Desktop-Uhr Einstellungen (Expander) ─────────────────────────
        clock_expander = Adw.ExpanderRow()
        clock_expander.set_title(t("Desktop clock"))
        clock_expander.set_subtitle(t("Position, size and visibility"))
        clock_expander.set_margin_start(12)
        clock_expander.set_margin_end(12)
        clock_expander.set_margin_bottom(6)

        # Wrapper da ExpanderRow kein direktes Widget-Child akzeptiert
        clock_box = Gtk.ListBox()
        clock_box.set_selection_mode(Gtk.SelectionMode.NONE)
        clock_box.add_css_class("boxed-list")

        clk = _get_clock_settings()

        # An/Aus
        self._clock_enabled = Adw.SwitchRow(title=t("Show clock"))
        self._clock_enabled.set_active(clk.get("enabled", True))
        self._clock_enabled.connect("notify::active", self._on_clock_changed)
        clock_expander.add_row(self._clock_enabled)

        # Position
        pos_row = Adw.ActionRow(title=t("Position"))
        self._clock_pos = Gtk.ComboBoxText()
        self._clock_pos.set_valign(Gtk.Align.CENTER)
        for pid, plabel in CLOCK_POSITIONS:
            self._clock_pos.append(pid, plabel)
        self._clock_pos.set_active_id(clk.get("position", "top-right"))
        self._clock_pos.connect("changed", self._on_clock_changed)
        pos_row.add_suffix(self._clock_pos)
        clock_expander.add_row(pos_row)

        # Größe
        scale_row = Adw.ActionRow(title=t("Size"))
        scale_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        scale_box.set_valign(Gtk.Align.CENTER)
        self._clock_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.5, 3.0, 0.1)
        self._clock_scale.set_value(clk.get("scale", 1.0))
        self._clock_scale.set_draw_value(True)
        self._clock_scale.set_size_request(160, -1)
        self._clock_scale.connect("value-changed", self._on_clock_changed)
        scale_box.append(self._clock_scale)
        scale_row.add_suffix(scale_box)
        clock_expander.add_row(scale_row)

        # Farben invertieren
        self._clock_invert = Adw.SwitchRow(title=t("Invert colors"))
        self._clock_invert.set_active(clk.get("invertColors", False))
        self._clock_invert.connect("notify::active", self._on_clock_changed)
        clock_expander.add_row(self._clock_invert)

        self.append(clock_expander)

        # ── Banner ───────────────────────────────────────────────────────
        self.banner = Adw.Banner()
        self.banner.set_revealed(False)
        self.append(self.banner)

        # ── Stack ─────────────────────────────────────────────────────────
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.append(self._stack)

        self._img_grid = MediaGrid(self._on_image_selected)
        self._vid_grid = MediaGrid(self._on_video_selected)
        self._stack.add_named(self._img_grid, "images")
        self._stack.add_named(self._vid_grid, "videos")

        self._load_images()

    # ── Tab-Wechsel ───────────────────────────────────────────────────────

    def _on_tab_toggle(self, btn):
        if not btn.get_active():
            return
        if btn is self._tab_img:
            self._stack.set_visible_child_name("images")
            self._random_btn.set_sensitive(True)
            self._path_label.set_markup(
                f"<small><tt>{str(_get_image_dir()).replace(str(Path.home()), '~')}</tt></small>"
            )
        else:
            self._stack.set_visible_child_name("videos")
            self._random_btn.set_sensitive(False)
            self._path_label.set_markup(
                f"<small><tt>{str(VIDEO_DIR).replace(str(Path.home()), '~')}</tt></small>"
            )
            # Lazy-load beim ersten Wechsel
            if self._vid_grid.flow.get_first_child() is None \
               and not self._vid_grid.spinner.get_spinning():
                self._load_videos()

    def _reload(self):
        if self._stack.get_visible_child_name() == "images":
            self._load_images()
        else:
            self._load_videos()

    # ── Laden ─────────────────────────────────────────────────────────────

    def _load_images(self):
        self._img_grid.load(_scan(_get_image_dir(), IMAGE_EXTENSIONS),
                            self._current, _make_image_thumb, is_video=False)

    def _load_videos(self):
        self._vid_grid.load(_scan(VIDEO_DIR, VIDEO_EXTENSIONS),
                            self._current, _make_video_thumb, is_video=True)

    # ── Auswahl ───────────────────────────────────────────────────────────

    def _run_wallpaper_action(self, action, *, missing_program_message: str | None = None):
        """Run a live wallpaper action only while its capability is available.

        A missing program (e.g. mpvpaper) is detected either as a direct
        `FileNotFoundError` (persistence never ran at all — capability/
        competing-content/validation failed before any live action) or,
        since `live_apply` now runs inside the writer's own transaction
        and any exception it raises gets wrapped by the writer's rollback
        path, as some other exception whose `__cause__` is the original
        `FileNotFoundError` — either way the same friendly message is
        shown instead of the raw wrapped error text."""
        try:
            action()
        except FileNotFoundError:
            message = missing_program_message or t("Required wallpaper program not found.")
            self.main_window.add_toast(Adw.Toast.new(message))
        except Exception as e:
            if isinstance(e.__cause__, FileNotFoundError) and missing_program_message is not None:
                self.main_window.add_toast(Adw.Toast.new(missing_program_message))
            else:
                self.main_window.add_toast(Adw.Toast.new(f"Fehler: {e}"))

    def _apply_wallpaper_change(self, *, new_autostart_video: Path | None, live_apply):
        """Persists `new_autostart_video` as the app's autostart entry
        FIRST — before any live process is stopped/started or any PID
        file touched — so a persistence failure (capability, competing
        content, luac, reload, ...) never has any live side effect at
        all. `live_apply` itself only ever runs INSIDE the writer's own
        write lock, immediately after a successful reload (see
        `_write_mpvpaper_autostart`'s `live_apply` forwarding) — so if it
        raises, the writer's own rollback restores exactly the bytes THIS
        transaction read as its starting point under that same lock
        (never a stale pre-lock snapshot this method might otherwise have
        taken), and re-raises. This method only adds a best-effort
        attempt to restore the previous live video process (if any) on
        top of that — the caller must never reach its own success path
        (UI state update, success toast) after this returns by raising."""
        previous_current = self._current
        try:
            _write_mpvpaper_autostart(new_autostart_video, live_apply=live_apply)
        except Exception:
            self._restore_live_video(previous_current)
            raise

    def _restore_live_video(self, previous_current: str) -> None:
        """Best-effort: re-spawns mpvpaper for the video that was showing
        before a failed switch already stopped it via `_stop_mpv()`. Never
        raises — this runs during already-failing error recovery and must
        not mask the original error with a new one, and must not be
        mistaken for success (no toast, no `_current`/grid update here)."""
        if not previous_current:
            return
        try:
            prev_path = Path(previous_current)
            if prev_path.suffix.lower() not in VIDEO_EXTENSIONS or not prev_path.is_file():
                return
            self._mpv_proc = subprocess.Popen(["mpvpaper", "*", str(prev_path), "-o", _MPVPAPER_ARGS])
            _MPV_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            _MPV_PID_FILE.write_text(str(self._mpv_proc.pid))
        except Exception:
            pass

    def _on_image_selected(self, path: Path):
        try:
            path = _validate_media_path(path, IMAGE_EXTENSIONS, "image")
        except ValueError as e:
            self.main_window.add_toast(Adw.Toast.new(str(e)))
            return

        def apply_image():
            def live_apply():
                self._stop_mpv()
                subprocess.Popen(["caelestia", "wallpaper", "-f", str(path)])

            self._apply_wallpaper_change(new_autostart_video=None, live_apply=live_apply)
            self._current = str(path)
            self._img_grid.mark_current(self._current)
            self._show_banner(f"Wallpaper: {path.name}")
            self.main_window.add_toast(Adw.Toast.new(f"Wallpaper: {path.name}"))

        self._run_wallpaper_action(apply_image)

    def _on_video_selected(self, path: Path):
        try:
            path = _validate_media_path(path, VIDEO_EXTENSIONS, "video")
        except ValueError as e:
            self.main_window.add_toast(Adw.Toast.new(str(e)))
            return

        def apply_video():
            def live_apply():
                self._stop_mpv()
                self._mpv_proc = subprocess.Popen([
                    "mpvpaper", "*", str(path),
                    "-o", _MPVPAPER_ARGS
                ])
                try:
                    _MPV_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                    _MPV_PID_FILE.write_text(str(self._mpv_proc.pid))
                except Exception:
                    pass

            self._apply_wallpaper_change(new_autostart_video=path, live_apply=live_apply)
            self._current = str(path)
            self._vid_grid.mark_current(self._current)
            self._show_banner(f"Video-Wallpaper: {path.name}")
            self.main_window.add_toast(Adw.Toast.new(f"Video: {path.name}"))

        self._run_wallpaper_action(
            apply_video,
            missing_program_message=t("mpvpaper not found — yay -S mpvpaper"),
        )

    def _stop_mpv(self):
        if self._mpv_proc is not None:
            if self._mpv_proc.poll() is None:
                self._mpv_proc.terminate()
            self._mpv_proc = None
        else:
            # Kein laufender Prozess verfolgt — PID aus vorheriger Sitzung prüfen
            try:
                if _MPV_PID_FILE.exists():
                    pid = int(_MPV_PID_FILE.read_text().strip())
                    os.kill(pid, 15)  # SIGTERM
            except Exception:
                pass
        try:
            _MPV_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    # ── Toolbar-Buttons ───────────────────────────────────────────────────

    def _on_random(self, _):
        def apply_random():
            def live_apply():
                self._stop_mpv()
                subprocess.Popen(["caelestia", "wallpaper", "-r", str(_get_image_dir())])

            self._apply_wallpaper_change(new_autostart_video=None, live_apply=live_apply)
            self._show_banner(t("Random wallpaper set"))
            self.main_window.add_toast(Adw.Toast.new(t("Random wallpaper set")))

        self._run_wallpaper_action(apply_random)

    def _on_mode_toggled(self, btn):
        mode = "light" if btn.get_active() else "dark"
        self._scheme_mode = mode
        btn.set_icon_name(
            "weather-clear-symbolic" if mode == "light"
            else "weather-clear-night-symbolic"
        )
        try:
            subprocess.Popen(["caelestia", "scheme", "set", "--notify", "-m", mode])
            self._show_banner(f"Farbschema: {mode.capitalize()}")
            self.main_window.add_toast(Adw.Toast.new(f"Farbschema: {mode.capitalize()}"))
        except Exception as e:
            self.main_window.add_toast(Adw.Toast.new(f"Fehler: {e}"))

    def _on_clock_changed(self, *_):
        settings = _get_clock_settings()
        settings["enabled"]      = self._clock_enabled.get_active()
        settings["position"]     = self._clock_pos.get_active_id() or "top-right"
        settings["scale"]        = round(self._clock_scale.get_value(), 1)
        settings["invertColors"] = self._clock_invert.get_active()
        _save_clock_settings(settings)

    def _show_banner(self, text: str):
        self.banner.set_title(text)
        self.banner.set_revealed(True)
