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
            mock.patch.object(wallpaper, "_EXECS_CONF", self.execs_file),
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

    def test_none_and_lua_block_image_video_and_random_before_side_effects(self):
        for provider in (None, hp.Provider.LUA):
            for callback_name in ("_on_image_selected", "_on_video_selected", "_on_random"):
                with self.subTest(provider=provider, callback=callback_name):
                    self._assert_blocked_callback(provider, callback_name)

    def test_delayed_execution_rechecks_provider(self):
        page = self._page()
        action = mock.MagicMock()
        with mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA):
            wallpaper.WallpaperPage._run_wallpaper_action(page, action)
        action.assert_not_called()
        page.main_window.add_toast.assert_called_once()

    def test_hyprlang_image_path_keeps_existing_live_behavior(self):
        page = self._page()
        path = Path(self._tmpdir.name) / "wall.png"
        with (
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
            mock.patch.object(wallpaper, "_write_mpvpaper_autostart") as write_autostart,
        ):
            wallpaper.WallpaperPage._on_image_selected(page, path)

        page._stop_mpv.assert_called_once()
        popen.assert_called_once_with(["caelestia", "wallpaper", "-f", str(path)])
        write_autostart.assert_called_once_with(None)
        self.assertEqual(page._current, str(path))
        page._img_grid.mark_current.assert_called_once_with(str(path))

    def test_hyprlang_video_path_keeps_existing_live_behavior(self):
        page = self._page()
        path = Path(self._tmpdir.name) / "wall.mp4"
        process = mock.MagicMock(pid=1234)
        with (
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch.object(wallpaper, "_MPV_PID_FILE", self.pid_file),
            mock.patch.object(wallpaper.subprocess, "Popen", return_value=process) as popen,
            mock.patch.object(wallpaper, "_write_mpvpaper_autostart") as write_autostart,
        ):
            wallpaper.WallpaperPage._on_video_selected(page, path)

        page._stop_mpv.assert_called_once()
        popen.assert_called_once_with([
            "mpvpaper", "*", str(path), "-o", "loop --no-audio --panscan=1.0"
        ])
        write_autostart.assert_called_once_with(path)
        self.assertEqual(self.pid_file.read_text(), "1234")
        self.assertEqual(page._current, str(path))

    def test_hyprlang_random_path_keeps_existing_live_behavior(self):
        page = self._page()
        image_dir = Path(self._tmpdir.name) / "images"
        with (
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch.object(wallpaper, "_get_image_dir", return_value=image_dir),
            mock.patch.object(wallpaper.subprocess, "Popen") as popen,
            mock.patch.object(wallpaper, "_write_mpvpaper_autostart") as write_autostart,
        ):
            wallpaper.WallpaperPage._on_random(page, None)

        page._stop_mpv.assert_called_once()
        popen.assert_called_once_with(["caelestia", "wallpaper", "-r", str(image_dir)])
        write_autostart.assert_called_once_with(None)


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
