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

    def test_monitor_writer_migrates_single_marker_and_preserves_everything_else(self):
        self.path.write_bytes(
            b"# manual prefix\r\n"
            + monitor.MONITORS_LEGACY_MARKER.encode()
            + b"\r\n\r\nmonitor = OLD,preferred,auto,1\r\n"
            b"# manual suffix\r\nworkspace = 9, monitor:MANUAL\r\n"
        )
        mon = SimpleNamespace(
            name="DP-1", disabled=False, resolution="1920x1080", hz="60", x=0, y=0,
            scale=1, bitdepth="", transform="0",
        )
        with mock.patch.object(config, "HYPR_MONITORS_CONF", self.path):
            monitor._save_monitors_conf([mon])
        content = self.path.read_bytes()
        self.assertTrue(content.startswith(b"# manual prefix\r\n"))
        self.assertTrue(content.endswith(b"# manual suffix\r\nworkspace = 9, monitor:MANUAL\r\n"))
        self.assertEqual(content.count(b"BEGIN Caelestia Settings managed block: monitors"), 1)
        self.assertEqual(content.count(b"END Caelestia Settings managed block: monitors"), 1)
        self.assertNotIn(b"OLD", content)

    def test_workspace_writer_keeps_unmanaged_workspace_lines(self):
        self.path.write_text(
            "monitor = DP-1,preferred,auto,1\n"
            "workspace = 99, monitor:MANUAL\n"
            f"{workspaces.MANAGED_MARKER}\n"
            "workspace = 1, monitor:OLD\n"
            "# manual suffix\n"
        )
        values = [{"number": 2, "monitor": "DP-1", "default": False, "persistent": True}]
        with (
            mock.patch.object(workspaces, "HYPR_MONITORS_CONF", self.path),
            mock.patch.object(workspaces.subprocess, "run"),
        ):
            workspaces._save_workspaces_conf(values)
        content = self.path.read_text()
        self.assertIn("workspace = 99, monitor:MANUAL", content)
        self.assertIn("# manual suffix", content)
        self.assertNotIn("monitor:OLD", content)
        self.assertEqual(content.count("BEGIN Caelestia Settings managed block: workspaces"), 1)
        self.assertEqual(content.count("END Caelestia Settings managed block: workspaces"), 1)

    def test_rules_writer_keeps_manual_suffix_when_migrating(self):
        self.path.write_text(
            "windowrule = float true, match:class manual-before\n"
            f"{window_rules.MANAGED_MARKER}\n"
            "windowrule = float true, match:class old-generated\n"
            "# manual suffix\n"
            "windowrule = float true, match:class manual-after\n"
        )
        with mock.patch.object(window_rules, "HYPR_RULES_CONF", self.path):
            window_rules._write_rules_conf(["windowrule = float true, match:class new-generated"])
        content = self.path.read_text()
        self.assertIn("manual-before", content)
        self.assertIn("manual-after", content)
        self.assertIn("# manual suffix", content)
        self.assertNotIn("old-generated", content)
        self.assertEqual(content.count("BEGIN Caelestia Settings managed block: window-rules"), 1)
        self.assertEqual(content.count("END Caelestia Settings managed block: window-rules"), 1)

    def test_corrupt_legacy_file_aborts_instead_of_appending_second_block(self):
        original = "# BEGIN Caelestia Settings managed block: workspaces\nworkspace = 1\n"
        self.path.write_text(original)
        with (
            mock.patch.object(workspaces, "HYPR_MONITORS_CONF", self.path),
            self.assertRaises(hp.ManagedBlockError),
        ):
            workspaces._save_workspaces_conf([])
        self.assertEqual(self.path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
