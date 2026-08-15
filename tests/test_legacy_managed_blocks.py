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

from src import config
from src import hypr_provider as hp
from src.pages import monitor, window_rules, workspaces


class LegacyWriterProtectionTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = Path(self._tmpdir.name) / "config.conf"
        provider_patcher = mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG)
        provider_patcher.start()
        self.addCleanup(provider_patcher.stop)

    def test_monitor_writer_rejects_single_marker_even_at_eof(self):
        original = (
            b"# manual prefix\r\n"
            + monitor.MONITORS_LEGACY_MARKER.encode()
            + b"\r\n\r\nmonitor = OLD,preferred,auto,1\r\n"
        )
        self.path.write_bytes(original)
        mon = SimpleNamespace(
            name="DP-1", disabled=False, resolution="1920x1080", hz="60", x=0, y=0,
            scale=1, bitdepth="", transform="0",
        )
        with (
            mock.patch.object(config, "HYPR_MONITORS_CONF", self.path),
            self.assertRaisesRegex(hp.ManagedBlockError, "explicitly migrate"),
        ):
            monitor._save_monitors_conf([mon])
        self.assertEqual(self.path.read_bytes(), original)

    def test_monitor_writer_rejects_ambiguous_single_marker(self):
        original = (
            monitor.MONITORS_LEGACY_MARKER.encode()
            + b"\nmonitor = OLD,preferred,auto,1\n"
            b"monitor = MANUAL,preferred,auto,1\n"
        )
        self.path.write_bytes(original)
        with (
            mock.patch.object(config, "HYPR_MONITORS_CONF", self.path),
            self.assertRaisesRegex(hp.ManagedBlockError, "explicitly migrate"),
        ):
            monitor._save_monitors_conf([])
        self.assertEqual(self.path.read_bytes(), original)

    def test_genuine_block_preserves_crlf_prefix_and_suffix_exactly(self):
        original = (
            b"# manual prefix\r\n"
            b"# BEGIN Caelestia Settings managed block: window-rules\r\n"
            b"windowrule = float true, match:class old-generated\r\n"
            b"# END Caelestia Settings managed block: window-rules\r\n"
            b"# manual suffix\r\nwindowrule = float true, match:class manual-after\r\n"
        )
        self.path.write_bytes(original)
        with (
            mock.patch.object(window_rules, "HYPR_RULES_CONF", self.path),
            mock.patch.object(hp, "reload_hyprland"),
        ):
            window_rules._write_rules_conf(["windowrule = float true, match:class new-generated"])
        content = self.path.read_bytes()
        self.assertTrue(content.startswith(b"# manual prefix\r\n"))
        self.assertTrue(
            content.endswith(
                b"# manual suffix\r\nwindowrule = float true, match:class manual-after\r\n"
            )
        )
        self.assertIn(b"new-generated", content)
        self.assertNotIn(b"old-generated", content)

    def test_workspace_writer_rejects_ambiguous_single_marker(self):
        original = (
            workspaces.MANAGED_MARKER.encode()
            + b"\nworkspace = 1, monitor:OLD\n"
            b"workspace = 99, monitor:MANUAL\n"
        )
        self.path.write_bytes(original)
        values = [{"number": 2, "monitor": "DP-1", "default": False, "persistent": True}]
        with (
            mock.patch.object(workspaces, "HYPR_MONITORS_CONF", self.path),
            self.assertRaisesRegex(hp.ManagedBlockError, "explicitly migrate"),
        ):
            workspaces._save_workspaces_conf(values)
        self.assertEqual(self.path.read_bytes(), original)

    def test_rules_writer_rejects_ambiguous_single_marker(self):
        original = (
            window_rules.MANAGED_MARKER.encode()
            + b"\nwindowrule = float true, match:class old-generated\n"
            b"windowrule = float true, match:class manual-after\n"
        )
        self.path.write_bytes(original)
        with (
            mock.patch.object(window_rules, "HYPR_RULES_CONF", self.path),
            self.assertRaisesRegex(hp.ManagedBlockError, "explicitly migrate"),
        ):
            window_rules._write_rules_conf(["windowrule = float true, match:class new-generated"])
        self.assertEqual(self.path.read_bytes(), original)

    def test_single_marker_fails_before_backup_temp_or_lock_creation(self):
        original = monitor.MONITORS_LEGACY_MARKER.encode() + b"\nmonitor = MANUAL,preferred,auto,1\n"
        self.path.write_bytes(original)
        with (
            mock.patch.object(config, "HYPR_MONITORS_CONF", self.path),
            mock.patch.object(hp, "_create_backup") as backup_mock,
            mock.patch.object(hp.tempfile, "mkstemp") as temp_mock,
            self.assertRaises(hp.ManagedBlockError),
        ):
            monitor._save_monitors_conf([])
        backup_mock.assert_not_called()
        temp_mock.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.path.with_name(f".{self.path.name}.caelestia.lock").exists())

    def test_corrupt_legacy_file_aborts_instead_of_appending_second_block(self):
        original = "# BEGIN Caelestia Settings managed block: workspaces\nworkspace = 1\n"
        self.path.write_text(original)
        with (
            mock.patch.object(workspaces, "HYPR_MONITORS_CONF", self.path),
            self.assertRaises(hp.ManagedBlockError),
        ):
            workspaces._save_workspaces_conf([])
        self.assertEqual(self.path.read_text(), original)

    def test_reload_failure_rolls_back_and_reloads_original(self):
        original = (
            "# manual prefix\n"
            "# BEGIN Caelestia Settings managed block: workspaces\n"
            "workspace = 1, monitor:OLD\n"
            "# END Caelestia Settings managed block: workspaces\n"
            "# manual suffix\n"
        )
        self.path.write_text(original)
        reloads = [RuntimeError("bad generated config"), None]

        def reload_side_effect():
            result = reloads.pop(0)
            if result is not None:
                raise result

        with (
            mock.patch.object(workspaces, "HYPR_MONITORS_CONF", self.path),
            mock.patch.object(hp, "reload_hyprland", side_effect=reload_side_effect) as reload_mock,
            self.assertRaisesRegex(RuntimeError, "rolled back and reloaded"),
        ):
            workspaces._save_workspaces_conf(
                [{"number": 2, "monitor": "DP-1", "default": False, "persistent": False}]
            )
        self.assertEqual(self.path.read_text(), original)
        self.assertEqual(reload_mock.call_count, 2)
        backups = list(self.path.parent.glob("config.conf.bak_*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original)


if __name__ == "__main__":
    unittest.main()
