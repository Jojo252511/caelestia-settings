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
    def test_dispatches_to_lua_when_provider_is_lua(self):
        with (
            mock.patch("src.pages.workspaces.load_provider", return_value=hp.Provider.LUA),
            mock.patch("src.pages.workspaces._load_workspaces_lua", return_value=[_ws()]) as m,
        ):
            result = workspaces._load_workspaces()
        m.assert_called_once()
        self.assertEqual(result, [_ws()])

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
                "src.pages.workspaces._save_workspaces_lua",
                side_effect=hp.LuaWriteError("invalid"),
            ),
        ):
            with self.assertRaises(hp.LuaWriteError):
                workspaces._save_workspaces([_ws()])

    def test_reload_runs_after_successful_lua_save(self):
        calls = []
        with (
            mock.patch("src.pages.workspaces.load_provider", return_value=hp.Provider.LUA),
            mock.patch("src.pages.workspaces._save_workspaces_lua", side_effect=lambda d: calls.append("save")),
            mock.patch("src.pages.workspaces.reload_hyprland", side_effect=lambda: calls.append("reload")),
        ):
            workspaces._save_workspaces([_ws()])
        self.assertEqual(calls, ["save", "reload"])


if __name__ == "__main__":
    unittest.main()
