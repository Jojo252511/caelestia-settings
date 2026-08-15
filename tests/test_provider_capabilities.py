import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from src import config
from src import hypr_provider as hp
from src import window
from src.pages import general, keybinds, monitor, wallpaper, window_rules, workspaces


class ProviderPageAccessTest(unittest.TestCase):
    HYPR_PAGES = {
        "general",
        "wallpaper",
        "workspaces",
        "monitor",
        "window-rules",
        "keybinds",
    }

    def test_cancel_keeps_every_hyprland_page_locked(self):
        page = window.MainWindow.__new__(window.MainWindow)
        page._provider_page_guards = {
            name: mock.MagicMock() for name in self.HYPR_PAGES
        }
        window.MainWindow._apply_provider_page_locks(page, None)

        dialog = mock.MagicMock()
        response_callback = None

        def capture_callback(_signal, callback):
            nonlocal response_callback
            response_callback = callback

        dialog.connect.side_effect = capture_callback
        with mock.patch.object(hp.Adw, "MessageDialog", return_value=dialog):
            hp.prompt_provider_choice(page, page._on_provider_chosen)
        response_callback(dialog, "cancel")

        for guard in page._provider_page_guards.values():
            guard.set_provider.assert_called_once_with(None)

    def test_hyprlang_unlocks_all_legacy_pages(self):
        access = window.provider_page_access(hp.Provider.HYPRLANG)
        self.assertEqual(set(access), self.HYPR_PAGES)
        self.assertTrue(all(access.values()))

    def test_lua_unlocks_only_migrated_pages(self):
        access = window.provider_page_access(hp.Provider.LUA)
        self.assertEqual(
            {name for name, available in access.items() if available},
            {"monitor", "workspaces", "window-rules"},
        )
        self.assertFalse(access["general"])
        self.assertFalse(access["keybinds"])
        self.assertFalse(access["wallpaper"])

    def test_non_hyprland_pages_are_not_in_lock_matrix(self):
        for name in ("wifi", "audio", "updates", "fans", "about"):
            self.assertNotIn(name, window.PROVIDER_PAGE_CAPABILITIES)


class DefensiveWriterTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = Path(self._tmpdir.name) / "config.conf"

    def test_general_writer_without_provider_preserves_file(self):
        original = b"input {\n    kb_layout = us\n}\n"
        self.path.write_bytes(original)
        with mock.patch.object(general, "HYPR_INPUT_CONF", self.path):
            for provider in (None, hp.Provider.LUA):
                with self.subTest(provider=provider), mock.patch.object(
                    hp, "load_provider", return_value=provider
                ), self.assertRaises(hp.ProviderCapabilityError):
                    general._write_input_conf_key("kb_layout", "de")
                self.assertEqual(self.path.read_bytes(), original)

    def test_keybind_save_and_delete_without_provider_preserve_file(self):
        original = b"bind = SUPER, T, exec, kitty\n"
        self.path.write_bytes(original)
        data = {
            "bind_type": "bind",
            "modifier": "SUPER",
            "key": "Q",
            "dispatcher": "killactive",
        }
        with mock.patch.object(keybinds, "KEYBINDS_CONF", self.path):
            for provider in (None, hp.Provider.LUA):
                with self.subTest(provider=provider), mock.patch.object(
                    hp, "load_provider", return_value=provider
                ):
                    with self.assertRaises(hp.ProviderCapabilityError):
                        keybinds.save_keybind(data)
                    self.assertEqual(self.path.read_bytes(), original)
                    with self.assertRaises(hp.ProviderCapabilityError):
                        keybinds.delete_keybind(0)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("*.bak_*.conf")), [])

    def test_wallpaper_autostart_without_provider_preserves_file(self):
        original = b"exec-once = manual-command\n"
        self.path.write_bytes(original)
        with mock.patch.object(wallpaper, "_EXECS_CONF", self.path):
            for provider in (None, hp.Provider.LUA):
                with self.subTest(provider=provider), mock.patch.object(
                    hp, "load_provider", return_value=provider
                ), self.assertRaises(hp.ProviderCapabilityError):
                    wallpaper._write_mpvpaper_autostart(Path("/tmp/video.mp4"))
                self.assertEqual(self.path.read_bytes(), original)

    def test_legacy_managed_writers_under_lua_preserve_conf_files(self):
        original = b"# manual config\n"
        self.path.write_bytes(original)
        with mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA):
            cases = (
                (mock.patch.object(config, "HYPR_MONITORS_CONF", self.path), lambda: monitor._save_monitors_conf([])),
                (
                    mock.patch.object(workspaces, "HYPR_MONITORS_CONF", self.path),
                    lambda: workspaces._save_workspaces_conf([]),
                ),
                (
                    mock.patch.object(window_rules, "HYPR_RULES_CONF", self.path),
                    lambda: window_rules._write_rules_conf([]),
                ),
            )
            for path_patch, writer in cases:
                with self.subTest(writer=writer), path_patch:
                    with self.assertRaisesRegex(hp.ProviderCapabilityError, "Lua"):
                        writer()
                    self.assertEqual(self.path.read_bytes(), original)

    def test_primary_monitor_writer_is_protected_without_provider_and_under_lua(self):
        original = b"# Monitor Settings\nexec-once = manual\n"
        self.path.write_bytes(original)
        with mock.patch.object(monitor, "PRIMARY_MONITOR_EXECS_CONF", self.path):
            for provider in (None, hp.Provider.LUA):
                with self.subTest(provider=provider), mock.patch.object(
                    hp, "load_provider", return_value=provider
                ):
                    with self.assertRaises(hp.ProviderCapabilityError):
                        monitor._set_primary_monitor("DP-1")
                    self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
