import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import hypr_provider as hp

HAS_LUAC = shutil.which("luac") is not None


class ManagedLuaBlockTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = Path(self._tmpdir.name) / "monitors.lua"

    def test_read_missing_file_returns_empty(self):
        self.assertEqual(hp.read_managed_lua_block(self.path, "monitors"), [])

    def test_write_creates_file_with_block(self):
        hp.write_managed_lua_block(self.path, "monitors", ['hl.monitor({ output = "DP-1" })'])
        self.assertTrue(self.path.exists())
        content = self.path.read_text()
        self.assertIn("-- BEGIN Caelestia Settings managed block: monitors", content)
        self.assertIn("-- END Caelestia Settings managed block: monitors", content)
        self.assertIn('hl.monitor({ output = "DP-1" })', content)

    def test_write_then_read_roundtrip(self):
        lines = ['hl.monitor({ output = "DP-1" })', 'hl.monitor({ output = "DP-2" })']
        hp.write_managed_lua_block(self.path, "monitors", lines)
        self.assertEqual(hp.read_managed_lua_block(self.path, "monitors"), lines)

    def test_rewrite_replaces_old_block_without_duplicating(self):
        hp.write_managed_lua_block(self.path, "monitors", ['hl.monitor({ output = "DP-1" })'])
        hp.write_managed_lua_block(self.path, "monitors", ['hl.monitor({ output = "DP-2" })'])
        content = self.path.read_text()
        self.assertEqual(content.count("-- BEGIN Caelestia Settings managed block: monitors"), 1)
        self.assertNotIn("DP-1", content)
        self.assertIn("DP-2", content)

    def test_preserves_manual_content_before_and_after_block(self):
        self.path.write_text("-- my manual header\nlocal x = 1\n")
        hp.write_managed_lua_block(self.path, "monitors", ['hl.monitor({ output = "DP-1" })'])
        content = self.path.read_text()
        self.assertIn("-- my manual header", content)
        self.assertIn("local x = 1", content)
        self.assertIn("hl.monitor", content)

        # A second write with different content must still preserve the
        # manual lines and not duplicate them.
        hp.write_managed_lua_block(self.path, "monitors", ['hl.monitor({ output = "DP-2" })'])
        content = self.path.read_text()
        self.assertEqual(content.count("-- my manual header"), 1)
        self.assertEqual(content.count("local x = 1"), 1)

    def test_independent_named_blocks_do_not_clobber_each_other(self):
        hp.write_managed_lua_block(self.path, "monitors", ['hl.monitor({ output = "DP-1" })'])
        hp.write_managed_lua_block(self.path, "workspaces", ['hl.workspace_rule({ workspace = "1" })'])
        self.assertEqual(
            hp.read_managed_lua_block(self.path, "monitors"), ['hl.monitor({ output = "DP-1" })']
        )
        self.assertEqual(
            hp.read_managed_lua_block(self.path, "workspaces"),
            ['hl.workspace_rule({ workspace = "1" })'],
        )
        # Rewriting one block must not disturb the other.
        hp.write_managed_lua_block(self.path, "monitors", ['hl.monitor({ output = "DP-2" })'])
        self.assertEqual(
            hp.read_managed_lua_block(self.path, "workspaces"),
            ['hl.workspace_rule({ workspace = "1" })'],
        )

    def test_creates_backup_of_previous_content(self):
        self.path.write_text("-- v1\n")
        hp.write_managed_lua_block(self.path, "monitors", ["hl.monitor({})"])
        backups = list(self.path.parent.glob("monitors.lua.bak_*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "-- v1\n")

    def test_no_backup_on_first_write_to_new_file(self):
        hp.write_managed_lua_block(self.path, "monitors", ["hl.monitor({})"])
        backups = list(self.path.parent.glob("monitors.lua.bak_*"))
        self.assertEqual(backups, [])

    def test_leaves_no_temp_files_behind_on_success(self):
        hp.write_managed_lua_block(self.path, "monitors", ["hl.monitor({})"])
        leftovers = list(self.path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_original_file_untouched_when_luac_reports_failure(self):
        self.path.write_text("-- original\n")
        fake_luac = mock.MagicMock()
        fake_luac.returncode = 1
        fake_luac.stderr = "syntax error near '('"
        with (
            mock.patch("src.hypr_provider.shutil.which", return_value="/usr/bin/luac"),
            mock.patch("src.hypr_provider.subprocess.run", return_value=fake_luac),
        ):
            with self.assertRaises(hp.LuaWriteError):
                hp.write_managed_lua_block(self.path, "monitors", ["hl.monitor({})"])
        self.assertEqual(self.path.read_text(), "-- original\n")
        leftovers = list(self.path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_skips_validation_when_luac_not_installed(self):
        with mock.patch("src.hypr_provider.shutil.which", return_value=None):
            hp.write_managed_lua_block(self.path, "monitors", ["hl.monitor({})"])
        self.assertTrue(self.path.exists())

    @unittest.skipUnless(HAS_LUAC, "luac not installed")
    def test_real_luac_accepts_valid_generated_lua(self):
        hp.write_managed_lua_block(
            self.path,
            "monitors",
            ['hl.monitor({ output = "DP-1", mode = "2560x1440@179.952", position = "0x0", scale = 1.0 })'],
        )
        result = subprocess.run(["luac", "-p", str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(HAS_LUAC, "luac not installed")
    def test_real_luac_rejects_broken_manual_content_around_block(self):
        # The whole file is validated, not just our fragment: a syntax
        # error in surrounding hand-written Lua must still abort the write.
        self.path.write_text("local x = (\n")
        with self.assertRaises(hp.LuaWriteError):
            hp.write_managed_lua_block(self.path, "monitors", ["hl.monitor({})"])
        self.assertEqual(self.path.read_text(), "local x = (\n")


class ManagedBlockByteRangeTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = Path(self._tmpdir.name) / "rules.lua"

    def test_none_when_file_missing(self):
        self.assertIsNone(hp.managed_block_byte_range(self.path, "window-rules"))

    def test_none_when_block_missing(self):
        self.path.write_text("-- just a comment\n")
        self.assertIsNone(hp.managed_block_byte_range(self.path, "window-rules"))

    def test_range_covers_exactly_the_content_lines(self):
        hp.write_managed_lua_block(self.path, "window-rules", ["hl.window_rule({ a = 1 })"])
        text = self.path.read_text()
        rng = hp.managed_block_byte_range(self.path, "window-rules")
        self.assertIsNotNone(rng)
        start, end = rng
        self.assertEqual(text[start:end], "hl.window_rule({ a = 1 })\n")

    def test_range_excludes_manual_content_before_and_after(self):
        self.path.write_text("-- manual header\n")
        hp.write_managed_lua_block(self.path, "window-rules", ["hl.window_rule({ a = 1 })"])
        text = self.path.read_text()
        text = text + "-- manual footer\n"
        self.path.write_text(text)
        start, end = hp.managed_block_byte_range(self.path, "window-rules")
        self.assertNotIn("manual header", text[start:end])
        self.assertNotIn("manual footer", text[start:end])
        self.assertIn("hl.window_rule", text[start:end])

    def test_range_for_empty_block(self):
        hp.write_managed_lua_block(self.path, "window-rules", [])
        start, end = hp.managed_block_byte_range(self.path, "window-rules")
        self.assertEqual(start, end)


class ReloadHyprlandTest(unittest.TestCase):
    def test_success_returns_none(self):
        ok = mock.MagicMock()
        ok.returncode = 0
        ok.stderr = ""
        with mock.patch("src.hypr_provider.subprocess.run", return_value=ok):
            self.assertIsNone(hp.reload_hyprland())

    def test_nonzero_exit_raises_with_stderr(self):
        failed = mock.MagicMock()
        failed.returncode = 1
        failed.stderr = "config has errors"
        with mock.patch("src.hypr_provider.subprocess.run", return_value=failed):
            with self.assertRaises(RuntimeError) as ctx:
                hp.reload_hyprland()
        self.assertIn("config has errors", str(ctx.exception))

    def test_hyprctl_missing_raises_instead_of_silently_passing(self):
        with mock.patch("src.hypr_provider.subprocess.run", side_effect=FileNotFoundError("no hyprctl")):
            with self.assertRaises(RuntimeError):
                hp.reload_hyprland()

    def test_timeout_raises_instead_of_silently_passing(self):
        with mock.patch(
            "src.hypr_provider.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="hyprctl", timeout=5),
        ):
            with self.assertRaises(RuntimeError):
                hp.reload_hyprland()


if __name__ == "__main__":
    unittest.main()
