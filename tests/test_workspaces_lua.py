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

from src import hypr_provider as hp
from src.pages import workspaces


def _ws(number=1, monitor="DP-1", default=False, persistent=False) -> dict:
    return {"number": number, "monitor": monitor, "default": default, "persistent": persistent}


class BuildWorkspaceLuaTableTest(unittest.TestCase):
    def test_minimal_workspace(self):
        table = workspaces._build_workspace_lua_table(_ws(number=3, monitor=""))
        self.assertEqual(table, {"workspace": "3"})

    def test_full_workspace(self):
        table = workspaces._build_workspace_lua_table(_ws(default=True, persistent=True))
        self.assertEqual(table, {"workspace": "1", "monitor": "DP-1", "default": True, "persistent": True})

    def test_false_flags_are_omitted(self):
        table = workspaces._build_workspace_lua_table(_ws())
        self.assertNotIn("default", table)
        self.assertNotIn("persistent", table)


class SaveAndLoadWorkspacesLuaTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.lua_path = Path(self._tmpdir.name) / "monitors.lua"
        patcher = mock.patch.dict(hp.LUA_PATHS, {"monitors": self.lua_path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_then_load_roundtrip(self):
        data = [_ws(number=2, default=True), _ws(number=1, monitor="DP-2", persistent=True)]
        workspaces._save_workspaces_lua(data)
        loaded = workspaces._load_workspaces_lua()
        self.assertEqual(loaded, sorted(data, key=lambda w: w["number"]))

    def test_resaving_does_not_duplicate_block(self):
        workspaces._save_workspaces_lua([_ws(number=1)])
        workspaces._save_workspaces_lua([_ws(number=2)])
        content = self.lua_path.read_text()
        self.assertEqual(content.count("-- BEGIN Caelestia Settings managed block: workspaces"), 1)
        loaded = workspaces._load_workspaces_lua()
        self.assertEqual([w["number"] for w in loaded], [2])

    def test_independent_from_monitors_block(self):
        hp.write_managed_lua_block(self.lua_path, "monitors", ['hl.monitor({ output = "DP-1" })'])
        workspaces._save_workspaces_lua([_ws(number=1)])
        # The monitors block must survive workspaces.py's write untouched.
        self.assertEqual(
            hp.read_managed_lua_block(self.lua_path, "monitors"), ['hl.monitor({ output = "DP-1" })']
        )

    def test_load_empty_when_no_file(self):
        self.assertEqual(workspaces._load_workspaces_lua(), [])

    def test_load_ignores_malformed_entries(self):
        hp.write_managed_lua_block(
            self.lua_path,
            workspaces.WORKSPACES_LUA_BLOCK,
            ['hl.workspace_rule({ workspace = "not-a-number" })', 'hl.workspace_rule({ workspace = "5" })'],
        )
        loaded = workspaces._load_workspaces_lua()
        self.assertEqual([w["number"] for w in loaded], [5])


class LoadWorkspacesDispatchTest(unittest.TestCase):
    def test_returns_empty_without_provider_and_reads_no_config(self):
        with (
            mock.patch("src.pages.workspaces.load_provider", return_value=None),
            mock.patch("src.pages.workspaces._load_workspaces_lua") as lua_mock,
            mock.patch("src.pages.workspaces._load_workspaces_conf") as conf_mock,
        ):
            self.assertEqual(workspaces._load_workspaces(), [])
        lua_mock.assert_not_called()
        conf_mock.assert_not_called()

    def test_page_is_locked_and_empty_without_provider(self):
        page = workspaces.WorkspacesPage.__new__(workspaces.WorkspacesPage)
        page._content = mock.MagicMock()
        page._content.get_first_child.return_value = None
        page._rows = []
        page._provider_banner = mock.MagicMock()
        page._add_btn = mock.MagicMock()
        page._save_btn = mock.MagicMock()
        status = mock.MagicMock()
        with (
            mock.patch("src.pages.workspaces.load_provider", return_value=None),
            mock.patch("src.pages.workspaces._get_monitor_names") as monitors_mock,
            mock.patch("src.pages.workspaces._load_workspaces") as workspaces_mock,
            mock.patch("src.pages.workspaces.Adw.StatusPage", return_value=status),
        ):
            workspaces.WorkspacesPage._load(page)
        monitors_mock.assert_not_called()
        workspaces_mock.assert_not_called()
        page._add_btn.set_sensitive.assert_called_once_with(False)
        page._save_btn.set_sensitive.assert_called_once_with(False)
        page._content.append.assert_called_once_with(status)

    def test_dispatches_to_lua_when_provider_is_lua(self):
        with (
            mock.patch("src.pages.workspaces.load_provider", return_value=hp.Provider.LUA),
            mock.patch("src.pages.workspaces._load_workspaces_lua", return_value=[_ws()]) as m,
        ):
            result = workspaces._load_workspaces()
        m.assert_called_once()
        self.assertEqual(result, [_ws()])

    def test_monitor_names_are_empty_without_provider(self):
        with (
            mock.patch("src.pages.workspaces.load_provider", return_value=None),
            mock.patch("src.pages.workspaces.subprocess.run") as run_mock,
            mock.patch("src.pages.workspaces.parse_monitors_conf") as conf_mock,
        ):
            self.assertEqual(workspaces._get_monitor_names(), [])
        run_mock.assert_not_called()
        conf_mock.assert_not_called()

    def test_dispatches_to_conf_when_provider_is_hyprlang(self):
        with (
            mock.patch("src.pages.workspaces.load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch("src.pages.workspaces._load_workspaces_conf", return_value=[]) as m,
        ):
            workspaces._load_workspaces()
        m.assert_called_once()


class SaveWorkspacesErrorPropagationTest(unittest.TestCase):
    def test_lua_write_error_propagates_for_caller_to_toast(self):
        with (
            mock.patch("src.pages.workspaces.load_provider", return_value=hp.Provider.LUA),
            mock.patch(
                "src.pages.workspaces._save_workspaces_lua_and_reload",
                side_effect=hp.LuaWriteError("invalid"),
            ),
        ):
            with self.assertRaises(hp.LuaWriteError):
                workspaces._save_workspaces([_ws()])

    def test_transactional_writer_is_used_for_lua_save(self):
        calls = []
        with (
            mock.patch("src.pages.workspaces.load_provider", return_value=hp.Provider.LUA),
            mock.patch(
                "src.pages.workspaces._save_workspaces_lua_and_reload",
                side_effect=lambda d: calls.append("transaction"),
            ),
        ):
            workspaces._save_workspaces([_ws()])
        self.assertEqual(calls, ["transaction"])


if __name__ == "__main__":
    unittest.main()
