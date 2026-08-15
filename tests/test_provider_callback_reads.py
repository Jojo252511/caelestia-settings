import contextlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from src import hypr_provider as hp
from src import window
from src.pages import general, keybinds, wallpaper


def _write_autostart_calling_live_apply(_video_path, *, live_apply=None, **_kwargs):
    """Test double for `_write_mpvpaper_autostart` used whenever a test
    needs the page's `live_apply` wiring (Popen/_stop_mpv) exercised
    without touching a real config file — mirrors what the real writer
    does: invoke `live_apply` once persistence succeeds. A bare
    `mock.patch.object(..., "_write_mpvpaper_autostart")` (no side
    effect) never calls `live_apply` at all, since that invocation now
    happens INSIDE the real writer, not in the page-level caller."""
    if live_apply is not None:
        live_apply()


class WallpaperCallbackCapabilityTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        self.pid_file = root / "mpvpaper.pid"
        self.execs_file = root / "execs.conf"
        self.pid_file.write_bytes(b"4242\n")
        self.execs_file.write_bytes(b"exec-once = manual\n")
        self.pid_original = self.pid_file.read_bytes()
        self.execs_original = self.execs_file.read_bytes()

    @staticmethod
    def _page():
        page = types.SimpleNamespace()
        page.main_window = mock.MagicMock()
        page._current = "unchanged"
        page._mpv_proc = None
        page._img_grid = mock.MagicMock()
        page._vid_grid = mock.MagicMock()
        page.banner = mock.MagicMock()
        page._run_wallpaper_action = types.MethodType(wallpaper.WallpaperPage._run_wallpaper_action, page)
        page._apply_wallpaper_change = types.MethodType(
            wallpaper.WallpaperPage._apply_wallpaper_change, page
        )
        page._restore_live_video = types.MethodType(wallpaper.WallpaperPage._restore_live_video, page)
        page._stop_mpv = mock.MagicMock()
        page._show_banner = mock.MagicMock()
        return page

    def _assert_blocked_callback(self, provider, callback_name):
        page = self._page()
        path = Path(self._tmpdir.name) / ("wall.mp4" if callback_name == "_on_video_selected" else "wall.png")
        callback_arg = None if callback_name == "_on_random" else path

        with (
            mock.patch.object(hp, "load_provider", return_value=provider),
            mock.patch.object(wallpaper, "_MPV_PID_FILE", self.pid_file),
            mock.patch.dict(hp.LEGACY_PATHS, {"execs": self.execs_file}),
            mock.patch.dict(hp.LUA_PATHS, {"execs": self.execs_file}),
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
            mock.patch.object(wallpaper.subprocess, "run") as run,
            mock.patch.object(wallpaper.os, "kill") as kill,
        ):
            getattr(wallpaper.WallpaperPage, callback_name)(page, callback_arg)

        popen.assert_not_called()
        run.assert_not_called()
        kill.assert_not_called()
        page._stop_mpv.assert_not_called()
        page._img_grid.mark_current.assert_not_called()
        page._vid_grid.mark_current.assert_not_called()
        page._show_banner.assert_not_called()
        page.main_window.add_toast.assert_called_once()
        self.assertEqual(page._current, "unchanged")
        self.assertIsNone(page._mpv_proc)
        self.assertEqual(self.pid_file.read_bytes(), self.pid_original)
        self.assertEqual(self.execs_file.read_bytes(), self.execs_original)

    def test_no_provider_blocks_image_video_and_random_before_side_effects(self):
        # Lua unlocked WALLPAPER_AUTOSTART in M6 — only "no provider chosen
        # yet" still blocks these callbacks; see
        # WallpaperLuaAutostartTest for the now-supported Lua path.
        for callback_name in ("_on_image_selected", "_on_video_selected", "_on_random"):
            with self.subTest(callback=callback_name):
                self._assert_blocked_callback(None, callback_name)

    @contextlib.contextmanager
    def _provider_ctx(self, provider):
        """Standard context for tests that exercise a full callback:
        provider fixed, execs redirected to the (harmless, non-competing)
        setUp fixture file so the real writer (now genuinely called, not
        mocked, by `_apply_wallpaper_change` via `_write_mpvpaper_autostart`)
        never touches a real user config."""
        with (
            mock.patch.object(hp, "load_provider", return_value=provider),
            mock.patch.dict(hp.LEGACY_PATHS, {"execs": self.execs_file}),
            mock.patch.dict(hp.LUA_PATHS, {"execs": self.execs_file}),
        ):
            yield

    def test_delayed_execution_rechecks_provider(self):
        # The capability check now lives in _apply_wallpaper_change (run
        # persistence-first), not in _run_wallpaper_action itself — verify
        # it re-checks the provider fresh on every call rather than using
        # a cached/stale result.
        page = self._page()
        live_apply = mock.MagicMock()
        with (
            mock.patch.object(hp, "load_provider", return_value=None),
            self.assertRaises(hp.ProviderCapabilityError),
        ):
            wallpaper.WallpaperPage._apply_wallpaper_change(
                page, new_autostart_video=None, live_apply=live_apply
            )
        page._stop_mpv.assert_not_called()
        live_apply.assert_not_called()

    def test_hyprlang_image_path_keeps_existing_live_behavior(self):
        page = self._page()
        path = Path(self._tmpdir.name) / "wall.png"
        path.write_bytes(b"fake")
        with (
            self._provider_ctx(hp.Provider.HYPRLANG),
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
            mock.patch.object(
                wallpaper, "_write_mpvpaper_autostart", side_effect=_write_autostart_calling_live_apply
            ) as write_autostart,
        ):
            wallpaper.WallpaperPage._on_image_selected(page, path)

        page._stop_mpv.assert_called_once()
        popen.assert_called_once_with(["caelestia", "wallpaper", "-f", str(path)])
        write_autostart.assert_called_once_with(None, live_apply=mock.ANY)
        self.assertEqual(page._current, str(path))
        page._img_grid.mark_current.assert_called_once_with(str(path))

    def test_hyprlang_video_path_keeps_existing_live_behavior(self):
        page = self._page()
        path = Path(self._tmpdir.name) / "wall.mp4"
        path.write_bytes(b"fake")
        process = mock.MagicMock(pid=1234)
        with (
            self._provider_ctx(hp.Provider.HYPRLANG),
            mock.patch.object(wallpaper, "_MPV_PID_FILE", self.pid_file),
            mock.patch.object(wallpaper.subprocess, "Popen", return_value=process) as popen,
            mock.patch.object(
                wallpaper, "_write_mpvpaper_autostart", side_effect=_write_autostart_calling_live_apply
            ) as write_autostart,
        ):
            wallpaper.WallpaperPage._on_video_selected(page, path)

        page._stop_mpv.assert_called_once()
        popen.assert_called_once_with([
            "mpvpaper", "*", str(path), "-o", "loop --no-audio --panscan=1.0"
        ])
        write_autostart.assert_called_once_with(path, live_apply=mock.ANY)
        self.assertEqual(self.pid_file.read_text(), "1234")
        self.assertEqual(page._current, str(path))

    def test_hyprlang_random_path_keeps_existing_live_behavior(self):
        page = self._page()
        image_dir = Path(self._tmpdir.name) / "images"
        with (
            self._provider_ctx(hp.Provider.HYPRLANG),
            mock.patch.object(wallpaper, "_get_image_dir", return_value=image_dir),
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
            mock.patch.object(
                wallpaper, "_write_mpvpaper_autostart", side_effect=_write_autostart_calling_live_apply
            ) as write_autostart,
        ):
            wallpaper.WallpaperPage._on_random(page, None)

        page._stop_mpv.assert_called_once()
        popen.assert_called_once_with(["caelestia", "wallpaper", "-r", str(image_dir)])
        write_autostart.assert_called_once_with(None, live_apply=mock.ANY)

    def test_lua_image_path_is_no_longer_blocked(self):
        # WALLPAPER_AUTOSTART became Lua-available in M6 — same callback
        # behavior as hyprlang, just routed through the Lua writer
        # internally (see WallpaperLuaAutostartTest for that writer).
        page = self._page()
        path = Path(self._tmpdir.name) / "wall.png"
        path.write_bytes(b"fake")
        with (
            self._provider_ctx(hp.Provider.LUA),
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
            mock.patch.object(
                wallpaper, "_write_mpvpaper_autostart", side_effect=_write_autostart_calling_live_apply
            ) as write_autostart,
        ):
            wallpaper.WallpaperPage._on_image_selected(page, path)

        page._stop_mpv.assert_called_once()
        popen.assert_called_once_with(["caelestia", "wallpaper", "-f", str(path)])
        write_autostart.assert_called_once_with(None, live_apply=mock.ANY)
        self.assertEqual(page._current, str(path))
        page.main_window.add_toast.assert_called_once()

    def test_lua_video_path_is_no_longer_blocked(self):
        page = self._page()
        path = Path(self._tmpdir.name) / "wall.mp4"
        path.write_bytes(b"fake")
        process = mock.MagicMock(pid=1234)
        with (
            self._provider_ctx(hp.Provider.LUA),
            mock.patch.object(wallpaper, "_MPV_PID_FILE", self.pid_file),
            mock.patch.object(wallpaper.subprocess, "Popen", return_value=process) as popen,
            mock.patch.object(
                wallpaper, "_write_mpvpaper_autostart", side_effect=_write_autostart_calling_live_apply
            ) as write_autostart,
        ):
            wallpaper.WallpaperPage._on_video_selected(page, path)

        page._stop_mpv.assert_called_once()
        popen.assert_called_once()
        write_autostart.assert_called_once_with(path, live_apply=mock.ANY)
        self.assertEqual(self.pid_file.read_text(), "1234")
        self.assertEqual(page._current, str(path))

    def test_lua_random_path_is_no_longer_blocked(self):
        page = self._page()
        image_dir = Path(self._tmpdir.name) / "images"
        with (
            self._provider_ctx(hp.Provider.LUA),
            mock.patch.object(wallpaper, "_get_image_dir", return_value=image_dir),
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
            mock.patch.object(
                wallpaper, "_write_mpvpaper_autostart", side_effect=_write_autostart_calling_live_apply
            ) as write_autostart,
        ):
            wallpaper.WallpaperPage._on_random(page, None)

        page._stop_mpv.assert_called_once()
        popen.assert_called_once_with(["caelestia", "wallpaper", "-r", str(image_dir)])
        write_autostart.assert_called_once_with(None, live_apply=mock.ANY)

    def test_write_failure_under_lua_shows_error_toast_not_success(self):
        page = self._page()
        path = Path(self._tmpdir.name) / "wall.mp4"
        path.write_bytes(b"fake")
        with (
            self._provider_ctx(hp.Provider.LUA),
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
            mock.patch.object(
                wallpaper, "_write_mpvpaper_autostart", side_effect=hp.LuaWriteError("invalid lua")
            ),
        ):
            wallpaper.WallpaperPage._on_video_selected(page, path)

        popen.assert_not_called()
        page._stop_mpv.assert_not_called()
        page._show_banner.assert_not_called()
        page.main_window.add_toast.assert_called_once()
        toast = page.main_window.add_toast.call_args.args[0]
        self.assertIn("invalid lua", toast.get_title())
        self.assertEqual(page._current, "unchanged")
        page._vid_grid.mark_current.assert_not_called()
        self.assertIsNone(page._mpv_proc)

    def test_image_write_failure_has_zero_live_side_effects(self):
        # Persistence fails BEFORE any live action for the image path too
        # — not just video (see test_write_failure_under_lua_shows_error_toast_not_success).
        page = self._page()
        path = Path(self._tmpdir.name) / "wall.png"
        path.write_bytes(b"fake")
        with (
            self._provider_ctx(hp.Provider.LUA),
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
            mock.patch.object(
                wallpaper, "_write_mpvpaper_autostart", side_effect=hp.LuaWriteError("bad")
            ),
        ):
            wallpaper.WallpaperPage._on_image_selected(page, path)

        popen.assert_not_called()
        page._stop_mpv.assert_not_called()
        page.main_window.add_toast.assert_called_once()
        self.assertEqual(page._current, "unchanged")
        page._img_grid.mark_current.assert_not_called()

    def test_video_live_apply_failure_rolls_back_config_and_restores_previous_video(self):
        page = self._page()
        old_path = Path(self._tmpdir.name) / "old.mp4"
        old_path.write_bytes(b"fake")
        page._current = str(old_path)
        new_path = Path(self._tmpdir.name) / "new.mp4"
        new_path.write_bytes(b"fake")

        restore_process = mock.MagicMock(pid=999)
        popen_calls = []

        def popen_side_effect(args, *a, **kw):
            popen_calls.append(list(args))
            if len(popen_calls) == 1:
                raise OSError("mpvpaper crashed")
            return restore_process

        with (
            self._provider_ctx(hp.Provider.HYPRLANG),
            mock.patch.object(hp, "reload_hyprland"),
            mock.patch.object(wallpaper, "_MPV_PID_FILE", self.pid_file),
            mock.patch.object(wallpaper.subprocess, "Popen", side_effect=popen_side_effect),
        ):
            wallpaper.WallpaperPage._on_video_selected(page, new_path)

        # Real writer ran for real (not mocked): the new entry was
        # persisted, then rolled back to the previous (empty) content
        # after the live-apply failure.
        self.assertEqual(
            hp.read_managed_legacy_block(self.execs_file, wallpaper.WALLPAPER_AUTOSTART_BLOCK), []
        )
        self.assertEqual(len(popen_calls), 2)
        self.assertIn(str(old_path), popen_calls[1])
        self.assertEqual(self.pid_file.read_text(), "999")
        page.main_window.add_toast.assert_called_once()
        toast_text = page.main_window.add_toast.call_args.args[0].get_title()
        self.assertIn("mpvpaper crashed", toast_text)
        self.assertEqual(page._current, str(old_path))
        page._vid_grid.mark_current.assert_not_called()

    def test_live_apply_failure_when_no_previous_video_does_not_restore_anything(self):
        page = self._page()
        page._current = "unchanged"
        new_path = Path(self._tmpdir.name) / "new.mp4"
        new_path.write_bytes(b"fake")

        with (
            self._provider_ctx(hp.Provider.HYPRLANG),
            mock.patch.object(hp, "reload_hyprland"),
            mock.patch.object(wallpaper, "_MPV_PID_FILE", self.pid_file),
            mock.patch.object(wallpaper.subprocess, "Popen", side_effect=OSError("boom")) as popen,
        ):
            wallpaper.WallpaperPage._on_video_selected(page, new_path)

        self.assertEqual(popen.call_count, 1)  # no restore attempt — nothing to restore
        self.assertEqual(
            hp.read_managed_legacy_block(self.execs_file, wallpaper.WALLPAPER_AUTOSTART_BLOCK), []
        )
        self.assertEqual(page._current, "unchanged")

    def test_concurrent_config_change_during_live_apply_failure_prevents_unsafe_rollback(self):
        # A foreign write landing between this transaction's own commit
        # and its live-apply failure must abort the rollback (never
        # silently clobber the foreign change) while still surfacing a
        # full, non-silent error — never a success toast.
        page = self._page()
        page._current = "unchanged"
        new_path = Path(self._tmpdir.name) / "new.mp4"
        new_path.write_bytes(b"fake")

        def popen_side_effect(*_a, **_kw):
            # Simulate another process racing in and modifying the
            # config file after our own write already committed, but
            # before this live-apply failure triggers a rollback
            # attempt.
            self.execs_file.write_bytes(self.execs_file.read_bytes() + b"# foreign edit\n")
            raise OSError("popen boom")

        with (
            self._provider_ctx(hp.Provider.HYPRLANG),
            mock.patch.object(hp, "reload_hyprland"),
            mock.patch.object(wallpaper.subprocess, "Popen", side_effect=popen_side_effect),
        ):
            wallpaper.WallpaperPage._on_video_selected(page, new_path)

        page.main_window.add_toast.assert_called_once()
        toast_text = page.main_window.add_toast.call_args.args[0].get_title()
        self.assertIn("popen boom", toast_text)
        self.assertIn("concurrently", toast_text)
        self.assertIn("# foreign edit", self.execs_file.read_text())
        self.assertEqual(page._current, "unchanged")


class MediaPathValidationTest(unittest.TestCase):
    """`_validate_media_path` must run before ANY side effect — no
    capability check, writer, lock, backup, process, PID file, or UI
    state change — for input this app itself would never produce (a bare
    string, a relative path, a wrong-type/missing file, a leading-dash
    filename)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    @staticmethod
    def _page():
        page = types.SimpleNamespace()
        page.main_window = mock.MagicMock()
        page._current = "unchanged"
        page._mpv_proc = None
        page._img_grid = mock.MagicMock()
        page._vid_grid = mock.MagicMock()
        page._stop_mpv = mock.MagicMock()
        page._show_banner = mock.MagicMock()
        return page

    def _assert_zero_side_effects(self, callback_name, callback_arg):
        page = self._page()
        with (
            mock.patch.object(hp, "load_provider") as load_provider,
            mock.patch.object(
                wallpaper, "_write_mpvpaper_autostart", side_effect=_write_autostart_calling_live_apply
            ) as write_autostart,
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
        ):
            getattr(wallpaper.WallpaperPage, callback_name)(page, callback_arg)
        load_provider.assert_not_called()
        write_autostart.assert_not_called()
        popen.assert_not_called()
        page._stop_mpv.assert_not_called()
        page.main_window.add_toast.assert_called_once()
        self.assertEqual(page._current, "unchanged")
        self.assertIsNone(page._mpv_proc)

    def test_rejects_bare_string_even_if_it_looks_like_a_path(self):
        real_file = Path(self._tmpdir.name) / "wall.png"
        real_file.write_bytes(b"fake")
        self._assert_zero_side_effects("_on_image_selected", str(real_file))

    def test_rejects_relative_path(self):
        real_file = Path(self._tmpdir.name) / "wall.png"
        real_file.write_bytes(b"fake")
        cwd = os.getcwd()
        try:
            os.chdir(self._tmpdir.name)
            self._assert_zero_side_effects("_on_image_selected", Path("wall.png"))
        finally:
            os.chdir(cwd)

    def test_rejects_nonexistent_file(self):
        self._assert_zero_side_effects(
            "_on_image_selected", Path(self._tmpdir.name) / "missing.png"
        )

    def test_rejects_directory(self):
        directory = Path(self._tmpdir.name) / "adir.png"
        directory.mkdir()
        self._assert_zero_side_effects("_on_image_selected", directory)

    def test_rejects_wrong_media_type_for_image_callback(self):
        # A .txt file masquerading as an image via a renamed extension
        # check would still be rejected — this is a real file, wrong type.
        wrong = Path(self._tmpdir.name) / "notes.txt"
        wrong.write_bytes(b"fake")
        self._assert_zero_side_effects("_on_image_selected", wrong)

    def test_rejects_wrong_media_type_for_video_callback(self):
        wrong = Path(self._tmpdir.name) / "wall.png"
        wrong.write_bytes(b"fake")
        self._assert_zero_side_effects("_on_video_selected", wrong)

    def test_rejects_leading_dash_filename(self):
        # A leading '-' filename must never be interpretable as an option
        # by a program this app invokes with no shell involved.
        dashed = Path(self._tmpdir.name) / "-rf.png"
        dashed.write_bytes(b"fake")
        self._assert_zero_side_effects("_on_image_selected", dashed)

    def test_accepts_genuine_absolute_existing_matching_file(self):
        path = Path(self._tmpdir.name) / "wall.png"
        path.write_bytes(b"fake")
        validated = wallpaper._validate_media_path(path, wallpaper.IMAGE_EXTENSIONS, "image")
        self.assertEqual(validated, path)

    def test_validator_rejects_all_dangerous_forms_directly(self):
        real_dir = Path(self._tmpdir.name)
        cases = [
            ("not a Path", "bare string"),
            (Path("relative.png"), "relative"),
            (real_dir / "-dash.png", "leading dash"),
            (real_dir / "missing.png", "missing"),
        ]
        (real_dir / "-dash.png").touch()
        for value, label in cases:
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    wallpaper._validate_media_path(value, wallpaper.IMAGE_EXTENSIONS, "image")


class ProviderDependentReadTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        self.input_conf = root / "input.conf"
        self.keybinds_conf = root / "keybinds.conf"
        self.variables_conf = root / "variables.conf"
        self.input_conf.write_text("input {\n    kb_layout = de\n}\n")
        self.keybinds_conf.write_text("bind = SUPER, T, exec, kitty\n")
        self.variables_conf.write_text("$mainMod = SUPER\n")

    def test_none_read_path_does_not_touch_any_config(self):
        with mock.patch.object(Path, "exists") as exists, mock.patch.object(Path, "read_text") as read_text:
            self.assertEqual(general.read_input_conf(None), {})
            self.assertEqual(keybinds.parse_keybinds(None), [])
        exists.assert_not_called()
        read_text.assert_not_called()

    def test_lua_read_path_never_touches_legacy_input_conf(self):
        # kb_layout/numlock_by_default became Lua-available as of M5, so
        # under Provider.LUA the app's own (real, but nonexistent, so
        # harmless) input.lua path IS checked for existence — but the
        # legacy .conf format (read via Path.read_text) must never be
        # touched by any provider, including Lua. The effective value
        # itself comes from `hyprctl -j getoption` as of M5.1, not file
        # parsing, so that's mocked here too for a deterministic result
        # regardless of whether this machine has a real Hyprland session.
        lua_input_path = Path(self._tmpdir.name) / "input.lua"
        with (
            mock.patch.dict(hp.LUA_PATHS, {"input": lua_input_path}),
            mock.patch.object(Path, "read_text") as read_text,
            mock.patch.object(general, "_get_effective_kb_layout", return_value=None),
            mock.patch.object(general, "_get_effective_numlock", return_value=None),
        ):
            self.assertEqual(general.read_input_conf(hp.Provider.LUA), {})
            self.assertEqual(keybinds.parse_keybinds(hp.Provider.LUA), [])
        read_text.assert_not_called()

    def test_hyprlang_read_paths_load_legacy_values(self):
        with (
            mock.patch.object(general, "HYPR_INPUT_CONF", self.input_conf),
            mock.patch.object(keybinds, "KEYBINDS_CONF", self.keybinds_conf),
            mock.patch.object(keybinds, "VARIABLES_CONF", self.variables_conf),
        ):
            self.assertEqual(general.read_input_conf(hp.Provider.HYPRLANG)["kb_layout"], "de")
            binds = keybinds.parse_keybinds(hp.Provider.HYPRLANG)
        self.assertEqual(len(binds), 1)
        self.assertEqual(binds[0]["key_raw"], "T")

    def test_keybinds_page_stays_neutral_for_none_and_lua(self):
        # Keybinds are not Lua-available until M7, so both providers must
        # still leave this page neutral.
        for provider in (None, hp.Provider.LUA):
            with self.subTest(provider=provider):
                keybind_page = types.SimpleNamespace(_all_binds=[{"stale": True}], _filter=mock.MagicMock())
                keybind_page._load = mock.MagicMock()
                loaded = keybinds.KeybindsPage.load_if_available(keybind_page, provider)
                self.assertFalse(loaded)
                self.assertEqual(keybind_page._all_binds, [])
                keybind_page._load.assert_not_called()

    def test_general_page_stays_neutral_without_a_provider(self):
        general_page = types.SimpleNamespace(
            layout_combo=mock.MagicMock(),
            numlock_row=mock.MagicMock(),
            lang_combo=mock.MagicMock(),
            time_combo=mock.MagicMock(),
            is_loading=False,
            _load_all=mock.MagicMock(),
        )
        general_page._set_neutral_state = types.MethodType(general.GeneralPage._set_neutral_state, general_page)
        loaded = general.GeneralPage.load_if_available(general_page, None)
        self.assertFalse(loaded)
        general_page._load_all.assert_not_called()
        general_page.layout_combo.set_active.assert_called_once_with(-1)

    def test_general_page_loads_under_lua_as_of_m5(self):
        # input.kb_layout / input.numlock_by_default became Lua-available
        # in M5, so unlike the None case above, Provider.LUA now unlocks
        # and loads the General page instead of staying neutral.
        general_page = types.SimpleNamespace(
            layout_combo=mock.MagicMock(),
            numlock_row=mock.MagicMock(),
            lang_combo=mock.MagicMock(),
            time_combo=mock.MagicMock(),
            is_loading=False,
            _load_all=mock.MagicMock(),
        )
        general_page._set_neutral_state = types.MethodType(general.GeneralPage._set_neutral_state, general_page)
        loaded = general.GeneralPage.load_if_available(general_page, hp.Provider.LUA)
        self.assertTrue(loaded)
        general_page._load_all.assert_called_once_with(hp.Provider.LUA)
        general_page.layout_combo.set_active.assert_not_called()

    def test_hyprlang_page_refreshes_load_both_legacy_areas(self):
        general_page = types.SimpleNamespace(_load_all=mock.MagicMock())
        keybind_page = types.SimpleNamespace(_load=mock.MagicMock())
        self.assertTrue(general.GeneralPage.load_if_available(general_page, hp.Provider.HYPRLANG))
        self.assertTrue(keybinds.KeybindsPage.load_if_available(keybind_page, hp.Provider.HYPRLANG))
        general_page._load_all.assert_called_once_with(hp.Provider.HYPRLANG)
        keybind_page._load.assert_called_once_with(hp.Provider.HYPRLANG)

    def test_explicit_provider_choice_refreshes_both_pages_only_safely(self):
        main_window = window.MainWindow.__new__(window.MainWindow)
        main_window._apply_provider_page_locks = mock.MagicMock()
        main_window.general_page = mock.MagicMock()
        main_window.keybinds_page = mock.MagicMock()
        main_window.mon_page = mock.MagicMock()
        main_window.workspaces_page = mock.MagicMock()
        main_window.window_rules_page = mock.MagicMock()
        main_window.home_page = mock.MagicMock()
        main_window.add_toast = mock.MagicMock()

        for provider in (hp.Provider.HYPRLANG, hp.Provider.LUA):
            with self.subTest(provider=provider):
                window.MainWindow._on_provider_chosen(main_window, provider)
                main_window.general_page.on_provider_changed.assert_called_with(provider)
                main_window.keybinds_page.on_provider_changed.assert_called_with(provider)

    def test_cancel_does_not_trigger_general_or_keybind_refresh(self):
        main_window = window.MainWindow.__new__(window.MainWindow)
        main_window.general_page = mock.MagicMock()
        main_window.keybinds_page = mock.MagicMock()
        callback = mock.MagicMock(wraps=main_window._on_provider_chosen)
        dialog = mock.MagicMock()
        response_callback = None

        def capture_callback(_signal, connected_callback):
            nonlocal response_callback
            response_callback = connected_callback

        dialog.connect.side_effect = capture_callback
        with mock.patch.object(hp.Adw, "MessageDialog", return_value=dialog):
            hp.prompt_provider_choice(main_window, callback)
        response_callback(dialog, "cancel")

        callback.assert_not_called()
        main_window.general_page.on_provider_changed.assert_not_called()
        main_window.keybinds_page.on_provider_changed.assert_not_called()

    def test_persisted_provider_routes_initial_reads(self):
        # input.lua is patched to a nonexistent temp path, and the
        # effective-value getters (hyprctl -j getoption as of M5.1) are
        # mocked to "unreachable", so the LUA case deterministically
        # resolves "not known" (-> None) instead of depending on whatever
        # real Hyprland session/config happens to be reachable on the
        # machine running this test.
        lua_input_path = Path(self._tmpdir.name) / "input.lua"
        with (
            mock.patch.object(general, "HYPR_INPUT_CONF", self.input_conf),
            mock.patch.object(keybinds, "KEYBINDS_CONF", self.keybinds_conf),
            mock.patch.object(keybinds, "VARIABLES_CONF", self.variables_conf),
            mock.patch.dict(hp.LUA_PATHS, {"input": lua_input_path}),
            mock.patch.object(general, "_get_effective_kb_layout", return_value=None),
            mock.patch.object(general, "_get_effective_numlock", return_value=None),
        ):
            for provider, expected_layout, expected_bind_count in (
                (None, None, 0),
                (hp.Provider.LUA, None, 0),
                (hp.Provider.HYPRLANG, "de", 1),
            ):
                with (
                    self.subTest(provider=provider),
                    mock.patch.object(general, "load_provider", return_value=provider),
                    mock.patch.object(keybinds, "load_provider", return_value=provider),
                ):
                    self.assertEqual(general.read_input_conf().get("kb_layout"), expected_layout)
                    self.assertEqual(len(keybinds.parse_keybinds()), expected_bind_count)


if __name__ == "__main__":
    unittest.main()
