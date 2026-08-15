import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from src import hypr_provider as hp
from src.pages import home, monitor


def _mon(**overrides) -> SimpleNamespace:
    defaults = dict(
        name="DP-1",
        resolution="2560x1440",
        hz="179.952",
        x=0,
        y=0,
        scale=1.0,
        transform="0",
        bitdepth="",
        disabled=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class BuildMonitorLuaTableTest(unittest.TestCase):
    def test_disabled_monitor_uses_mode_disable(self):
        table = monitor._build_monitor_lua_table(_mon(disabled=True))
        self.assertEqual(table, {"output": "DP-1", "mode": "disable"})

    def test_enabled_monitor_basic_fields(self):
        table = monitor._build_monitor_lua_table(_mon())
        self.assertEqual(table["output"], "DP-1")
        self.assertEqual(table["mode"], "2560x1440@179.952")
        self.assertEqual(table["position"], "0x0")
        self.assertEqual(table["scale"], 1.0)
        self.assertNotIn("bitdepth", table)
        self.assertNotIn("transform", table)

    def test_bitdepth_included_when_set(self):
        table = monitor._build_monitor_lua_table(_mon(bitdepth="10"))
        self.assertEqual(table["bitdepth"], 10)

    def test_transform_included_when_nonzero(self):
        table = monitor._build_monitor_lua_table(_mon(transform="3"))
        self.assertEqual(table["transform"], 3)

    def test_transform_zero_is_omitted(self):
        table = monitor._build_monitor_lua_table(_mon(transform="0"))
        self.assertNotIn("transform", table)

    def test_position_uses_integer_coordinates(self):
        table = monitor._build_monitor_lua_table(_mon(x=1920.0, y=-10.0))
        self.assertEqual(table["position"], "1920x-10")


class SaveAndParseMonitorsLuaTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.lua_path = Path(self._tmpdir.name) / "monitors.lua"
        patcher = mock.patch.dict(hp.LUA_PATHS, {"monitors": self.lua_path})
        patcher.start()
        self.addCleanup(patcher.stop)
        provider_patcher = mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA)
        provider_patcher.start()
        self.addCleanup(provider_patcher.stop)

    def test_save_renders_expected_call_syntax(self):
        monitor._save_monitors_lua([_mon(bitdepth="10")])
        lines = hp.read_managed_lua_block(self.lua_path, monitor.MONITORS_LUA_BLOCK)
        self.assertEqual(len(lines), 1)
        self.assertIn('output = "DP-1"', lines[0])
        self.assertIn('mode = "2560x1440@179.952"', lines[0])
        self.assertIn("bitdepth = 10", lines[0])
        self.assertTrue(lines[0].startswith("hl.monitor("))

    def test_extras_roundtrip_bitdepth(self):
        monitor._save_monitors_lua([_mon(bitdepth="10"), _mon(name="DP-2", bitdepth="")])
        extras = monitor._parse_monitors_lua_extras()
        self.assertEqual(extras["DP-1"]["bitdepth"], "10")
        self.assertEqual(extras["DP-2"]["bitdepth"], "")

    def test_resaving_does_not_duplicate_block(self):
        monitor._save_monitors_lua([_mon()])
        monitor._save_monitors_lua([_mon(name="DP-2")])
        content = self.lua_path.read_text()
        self.assertEqual(content.count("-- BEGIN Caelestia Settings managed block: monitors"), 1)
        self.assertNotIn("DP-1", content)
        self.assertIn("DP-2", content)

    def test_preserves_manual_content_outside_block(self):
        self.lua_path.write_text("-- user's own require chain\nlocal cfg = require('mycfg')\n")
        monitor._save_monitors_lua([_mon()])
        content = self.lua_path.read_text()
        self.assertIn("-- user's own require chain", content)
        self.assertIn("local cfg = require('mycfg')", content)

    def test_extras_empty_when_no_file(self):
        self.assertEqual(monitor._parse_monitors_lua_extras(), {})


class ProviderMissingMonitorTest(unittest.TestCase):
    def test_live_monitor_read_is_blocked_without_provider(self):
        with (
            mock.patch("src.pages.monitor.load_provider", return_value=None),
            mock.patch("src.pages.monitor.subprocess.run") as run_mock,
            mock.patch("src.pages.monitor._parse_monitors_lua_extras") as lua_mock,
            mock.patch("src.pages.monitor._parse_conf_extras") as conf_mock,
        ):
            self.assertEqual(monitor._get_live_monitors(), [])
        run_mock.assert_not_called()
        lua_mock.assert_not_called()
        conf_mock.assert_not_called()

    def test_page_is_locked_and_cleared_without_provider(self):
        page = monitor.MonitorPage.__new__(monitor.MonitorPage)
        page._apply_btn = mock.MagicMock()
        page._canvas = mock.MagicMock()
        page._settings_panel = mock.MagicMock()
        page._monitors = [_mon()]
        with (
            mock.patch("src.pages.monitor.load_provider", return_value=None),
            mock.patch("src.pages.monitor._get_live_monitors") as live_mock,
        ):
            monitor.MonitorPage.load_monitors(page)
        live_mock.assert_not_called()
        page._apply_btn.set_sensitive.assert_called_once_with(False)
        self.assertEqual(page._monitors, [])

    def test_home_does_not_read_legacy_monitors_without_provider(self):
        page = home.HomePage.__new__(home.HomePage)
        page._monitor_row = mock.MagicMock()
        with (
            mock.patch("src.pages.home.load_provider", return_value=None),
            mock.patch("src.pages.home.parse_monitors_conf") as conf_mock,
        ):
            home.HomePage._refresh_monitors(page)
        conf_mock.assert_not_called()
        subtitle = page._monitor_row.set_subtitle.call_args[0][0]
        self.assertEqual(subtitle, home.t("Hyprland configuration provider required"))


class OnApplyLuaErrorHandlingTest(unittest.TestCase):
    """MonitorPage._on_apply must surface Lua write/reload failures as a
    toast instead of crashing or silently discarding them."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.lua_path = Path(self._tmpdir.name) / "monitors.lua"
        patcher = mock.patch.dict(hp.LUA_PATHS, {"monitors": self.lua_path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reload_failure_shown_as_toast_not_raised(self):
        page = monitor.MonitorPage.__new__(monitor.MonitorPage)
        page._monitors = [_mon()]
        page.main_window = mock.MagicMock()

        with (
            mock.patch("src.pages.monitor.load_provider", return_value=hp.Provider.LUA),
            mock.patch("src.pages.monitor._save_monitors_lua_and_reload", side_effect=RuntimeError("boom")),
        ):
            monitor.MonitorPage._on_apply(page, mock.MagicMock())

        page.main_window.add_toast.assert_called_once()
        toast_arg = page.main_window.add_toast.call_args[0][0]
        self.assertIn("boom", toast_arg.get_title())

    def test_lock_timeout_is_shown_as_toast(self):
        page = monitor.MonitorPage.__new__(monitor.MonitorPage)
        page._monitors = [_mon()]
        page.main_window = mock.MagicMock()
        error = hp.LockTimeoutError("Timed out waiting for configuration write lock")
        with (
            mock.patch("src.pages.monitor.load_provider", return_value=hp.Provider.LUA),
            mock.patch("src.pages.monitor._save_monitors_lua_and_reload", side_effect=error),
        ):
            monitor.MonitorPage._on_apply(page, mock.MagicMock())
        toast = page.main_window.add_toast.call_args[0][0]
        self.assertIn("Timed out waiting", toast.get_title())


if __name__ == "__main__":
    unittest.main()
