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
from src.pages import window_rules as wr


def _rule(match_type="class", workspace="default", float_="default") -> dict:
    return {"match_type": match_type, "workspace": workspace, "float": float_}


class BuildWindowRuleLuaTablesTest(unittest.TestCase):
    def test_workspace_only_class(self):
        tables = wr._build_window_rule_lua_tables("kitty", _rule(workspace="2"))
        self.assertEqual(tables, [{"match": {"class": "kitty"}, "workspace": "2"}])

    def test_workspace_only_initial_title(self):
        tables = wr._build_window_rule_lua_tables(
            "Spotify( Free)?", _rule(match_type="initial_title", workspace="special:music")
        )
        self.assertEqual(
            tables,
            [{"match": {"initial_title": "Spotify( Free)?"}, "workspace": "special:music"}],
        )

    def test_special_workspace(self):
        tables = wr._build_window_rule_lua_tables("Spotify", _rule(workspace="special:music"))
        self.assertEqual(tables[0]["workspace"], "special:music")

    def test_float_true_is_real_bool(self):
        tables = wr._build_window_rule_lua_tables("kitty", _rule(float_="true"))
        self.assertEqual(tables, [{"match": {"class": "kitty"}, "float": True}])
        self.assertIs(tables[0]["float"], True)

    def test_float_false_is_real_bool(self):
        tables = wr._build_window_rule_lua_tables("kitty", _rule(float_="false"))
        self.assertEqual(tables, [{"match": {"class": "kitty"}, "float": False}])
        self.assertIs(tables[0]["float"], False)

    def test_workspace_and_float_combo_produces_two_tables(self):
        tables = wr._build_window_rule_lua_tables("kitty", _rule(workspace="2", float_="true"))
        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[0], {"match": {"class": "kitty"}, "workspace": "2"})
        self.assertEqual(tables[1], {"match": {"class": "kitty"}, "float": True})

    def test_default_default_produces_nothing(self):
        self.assertEqual(wr._build_window_rule_lua_tables("kitty", _rule()), [])


class RenderGoldenTest(unittest.TestCase):
    def test_class_workspace_matches_target_format(self):
        tables = wr._build_window_rule_lua_tables("kitty", _rule(workspace="2"))
        rendered = [wr.caelestia_core.render_lua_call("hl.window_rule", [t]) for t in tables]
        self.assertEqual(rendered, [r'hl.window_rule({ match = { class = "kitty" }, workspace = "2" })'])

    def test_special_workspace_matches_target_format(self):
        tables = wr._build_window_rule_lua_tables("Spotify", _rule(workspace="special:music"))
        rendered = wr.caelestia_core.render_lua_call("hl.window_rule", [tables[0]])
        self.assertEqual(
            rendered, r'hl.window_rule({ match = { class = "Spotify" }, workspace = "special:music" })'
        )

    def test_initial_title_matches_target_format(self):
        tables = wr._build_window_rule_lua_tables(
            "Spotify( Free)?", _rule(match_type="initial_title", workspace="special:music")
        )
        rendered = wr.caelestia_core.render_lua_call("hl.window_rule", [tables[0]])
        self.assertEqual(
            rendered,
            r'hl.window_rule({ match = { initial_title = "Spotify( Free)?" }, workspace = "special:music" })',
        )

    def test_float_true_matches_target_format(self):
        tables = wr._build_window_rule_lua_tables("kitty", _rule(float_="true"))
        rendered = wr.caelestia_core.render_lua_call("hl.window_rule", [tables[0]])
        self.assertEqual(rendered, r'hl.window_rule({ match = { class = "kitty" }, float = true })')

    def test_float_false_matches_target_format(self):
        tables = wr._build_window_rule_lua_tables("kitty", _rule(float_="false"))
        rendered = wr.caelestia_core.render_lua_call("hl.window_rule", [tables[0]])
        self.assertEqual(rendered, r'hl.window_rule({ match = { class = "kitty" }, float = false })')


class EscapingTest(unittest.TestCase):
    def test_backslash_and_quote_roundtrip(self):
        value = r'weird\class"name'
        tables = wr._build_window_rule_lua_tables(value, _rule(workspace="2"))
        rendered = wr.caelestia_core.render_lua_call("hl.window_rule", [tables[0]])
        parsed = wr._parse_window_rule_call(rendered, managed=True)
        self.assertEqual(parsed["match_val"], value)

    def test_unicode_roundtrip(self):
        value = "Bürö – 日本語 – ✨"
        tables = wr._build_window_rule_lua_tables(value, _rule(workspace="2"))
        rendered = wr.caelestia_core.render_lua_call("hl.window_rule", [tables[0]])
        parsed = wr._parse_window_rule_call(rendered, managed=True)
        self.assertEqual(parsed["match_val"], value)

    def test_regex_initial_title_roundtrip(self):
        value = "Spotify( Free)?"
        tables = wr._build_window_rule_lua_tables(value, _rule(match_type="initial_title", workspace="2"))
        rendered = wr.caelestia_core.render_lua_call("hl.window_rule", [tables[0]])
        parsed = wr._parse_window_rule_call(rendered, managed=True)
        self.assertEqual(parsed["match_val"], value)
        self.assertEqual(parsed["match_type"], "initial_title")


class ParseWindowRuleCallTest(unittest.TestCase):
    def test_workspace_rule_semantic_mapping(self):
        call = r'hl.window_rule({ match = { class = "kitty" }, workspace = "2" })'
        parsed = wr._parse_window_rule_call(call, managed=True)
        self.assertEqual(
            parsed,
            {
                "rule": "workspace 2",
                "match_type": "class",
                "match_val": "kitty",
                "raw": call,
                "managed": True,
            },
        )

    def test_special_workspace_semantic_mapping(self):
        call = r'hl.window_rule({ match = { class = "Spotify" }, workspace = "special:music" })'
        parsed = wr._parse_window_rule_call(call, managed=False)
        self.assertEqual(parsed["rule"], "workspace special:music")
        self.assertFalse(parsed["managed"])

    def test_float_true_semantic_mapping(self):
        call = r'hl.window_rule({ match = { class = "kitty" }, float = true })'
        parsed = wr._parse_window_rule_call(call, managed=True)
        self.assertEqual(parsed["rule"], "float true")

    def test_float_false_semantic_mapping(self):
        call = r'hl.window_rule({ match = { class = "kitty" }, float = false })'
        parsed = wr._parse_window_rule_call(call, managed=True)
        self.assertEqual(parsed["rule"], "float false")

    def test_initial_title_match_type(self):
        call = r'hl.window_rule({ match = { initial_title = "Spotify( Free)?" }, workspace = "special:music" })'
        parsed = wr._parse_window_rule_call(call, managed=True)
        self.assertEqual(parsed["match_type"], "initial_title")
        self.assertEqual(parsed["match_val"], "Spotify( Free)?")

    def test_dynamic_value_is_unsupported(self):
        call = 'hl.window_rule({ match = { class = vars.someVar }, workspace = "2" })'
        self.assertIsNone(wr._parse_window_rule_call(call, managed=False))

    def test_missing_workspace_and_float_is_unsupported(self):
        call = 'hl.window_rule({ match = { class = "kitty" } })'
        self.assertIsNone(wr._parse_window_rule_call(call, managed=False))

    def test_not_a_window_rule_call_is_unsupported(self):
        call = 'hl.monitor({ output = "DP-1" })'
        self.assertIsNone(wr._parse_window_rule_call(call, managed=False))

    def test_malformed_lua_is_unsupported_not_raising(self):
        call = 'hl.window_rule({ match = )'
        self.assertIsNone(wr._parse_window_rule_call(call, managed=False))


class SaveAndLoadWindowRulesLuaTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.lua_path = Path(self._tmpdir.name) / "rules.lua"
        patcher = mock.patch.dict(hp.LUA_PATHS, {"rules": self.lua_path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_then_load_roundtrip(self):
        rules = {"kitty": _rule(workspace="2"), "firefox": _rule(float_="true")}
        wr._save_window_rules_lua(rules)
        loaded = wr._load_window_rules_lua()
        self.assertEqual(len(loaded), 2)
        self.assertTrue(all(r["managed"] for r in loaded))
        by_class = {r["match_val"]: r for r in loaded}
        self.assertEqual(by_class["kitty"]["rule"], "workspace 2")
        self.assertEqual(by_class["firefox"]["rule"], "float true")

    def test_empty_ruleset_produces_valid_empty_block(self):
        wr._save_window_rules_lua({})
        self.assertEqual(hp.read_managed_lua_block(self.lua_path, wr.WINDOW_RULES_LUA_BLOCK), [])
        self.assertEqual(wr._load_window_rules_lua(), [])

    def test_resaving_produces_exactly_one_block(self):
        wr._save_window_rules_lua({"kitty": _rule(workspace="2")})
        wr._save_window_rules_lua({"firefox": _rule(workspace="3")})
        content = self.lua_path.read_text()
        self.assertEqual(content.count(f"-- BEGIN Caelestia Settings managed block: {wr.WINDOW_RULES_LUA_BLOCK}"), 1)
        loaded = wr._load_window_rules_lua()
        self.assertEqual([r["match_val"] for r in loaded], ["firefox"])

    def test_manual_rule_outside_block_is_read_as_unmanaged(self):
        self.lua_path.write_text(
            'hl.window_rule({ match = { class = "manual-app" }, workspace = "5" })\n'
        )
        wr._save_window_rules_lua({"kitty": _rule(workspace="2")})
        loaded = wr._load_window_rules_lua()
        by_class = {r["match_val"]: r for r in loaded}
        self.assertFalse(by_class["manual-app"]["managed"])
        self.assertTrue(by_class["kitty"]["managed"])

    def test_multiline_manual_rule_is_parsed(self):
        self.lua_path.write_text(
            "hl.window_rule({\n"
            '    match = { class = "multiline-app" },\n'
            '    workspace = "7",\n'
            "})\n"
        )
        loaded = wr._load_window_rules_lua()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["match_val"], "multiline-app")
        self.assertFalse(loaded[0]["managed"])

    def test_dynamic_manual_rule_does_not_crash_load_and_is_skipped(self):
        self.lua_path.write_text(
            'hl.window_rule({ match = { class = vars.dynamicClass }, workspace = "2" })\n'
            'hl.window_rule({ match = { class = "static-app" }, workspace = "3" })\n'
        )
        loaded = wr._load_window_rules_lua()
        self.assertEqual([r["match_val"] for r in loaded], ["static-app"])

    def test_unsupported_manual_rule_is_never_rewritten(self):
        manual_text = 'hl.window_rule({ match = { class = vars.dynamicClass }, workspace = "2" })\n'
        self.lua_path.write_text(manual_text)
        wr._save_window_rules_lua({"kitty": _rule(workspace="2")})
        content = self.lua_path.read_text()
        self.assertIn(manual_text.strip(), content)

    def test_content_before_and_after_block_preserved(self):
        self.lua_path.write_text("-- header\nlocal x = 1\n")
        wr._save_window_rules_lua({"kitty": _rule(workspace="2")})
        content = self.lua_path.read_text()
        content += "\n-- footer\n"
        self.lua_path.write_text(content)
        wr._save_window_rules_lua({"kitty": _rule(workspace="3")})
        final = self.lua_path.read_text()
        self.assertIn("-- header", final)
        self.assertIn("local x = 1", final)
        self.assertIn("-- footer", final)

    def test_second_named_block_preserved(self):
        hp.write_managed_lua_block(self.lua_path, "monitors", ['hl.monitor({ output = "DP-1" })'])
        wr._save_window_rules_lua({"kitty": _rule(workspace="2")})
        self.assertEqual(
            hp.read_managed_lua_block(self.lua_path, "monitors"), ['hl.monitor({ output = "DP-1" })']
        )

    def test_luac_failure_leaves_original_file_unchanged(self):
        self.lua_path.write_text("-- original\n")
        fake = mock.MagicMock()
        fake.returncode = 1
        fake.stderr = "syntax error"
        with (
            mock.patch("src.hypr_provider.shutil.which", return_value="/usr/bin/luac"),
            mock.patch("src.hypr_provider.subprocess.run", return_value=fake),
        ):
            with self.assertRaises(hp.LuaWriteError):
                wr._save_window_rules_lua({"kitty": _rule(workspace="2")})
        self.assertEqual(self.lua_path.read_text(), "-- original\n")

    def test_load_empty_when_no_file(self):
        self.assertEqual(wr._load_window_rules_lua(), [])


class LoadExistingRulesDispatchTest(unittest.TestCase):
    def test_routes_to_lua(self):
        with (
            mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.LUA),
            mock.patch("src.pages.window_rules._load_window_rules_lua", return_value=["x"]) as m,
        ):
            self.assertEqual(wr._load_existing_rules(), ["x"])
        m.assert_called_once()

    def test_routes_to_conf(self):
        with (
            mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch("src.pages.window_rules.parse_rules_conf", return_value=["y"]) as m,
        ):
            self.assertEqual(wr._load_existing_rules(), ["y"])
        m.assert_called_once()


class OnSaveClickedLuaTest(unittest.TestCase):
    """Exercises WindowRulesPage._on_save_clicked's provider-aware save
    path against a minimally constructed page (bypassing __init__/GTK
    widget construction) so the pure control-flow logic — cache-after-
    successful-write ordering, error toasting, reload gating — can be
    tested without a running desktop."""

    def _make_page(self, rows: dict) -> wr.WindowRulesPage:
        page = wr.WindowRulesPage.__new__(wr.WindowRulesPage)
        page.main_window = mock.MagicMock()
        page._conflicts = []
        page._rows = rows
        page._existing_rules = []
        page._existing_group = mock.MagicMock()
        page._existing_desc_label = mock.MagicMock()
        btn = mock.MagicMock()
        return page, btn

    def _row(self, key: str, settings: dict, user_modified: bool = True) -> SimpleNamespace:
        return SimpleNamespace(get_rule=lambda: (key, settings), is_user_modified=lambda: user_modified)

    def test_lua_write_failure_does_not_update_cache_or_reload(self):
        page, btn = self._make_page({"a": self._row("kitty", _rule(workspace="2"))})
        with (
            mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.LUA),
            mock.patch(
                "src.pages.window_rules._save_window_rules_lua",
                side_effect=hp.LuaWriteError("bad lua"),
            ),
            mock.patch("src.pages.window_rules.reload_hyprland") as reload_mock,
            mock.patch("src.pages.window_rules.save_window_rules_config") as cache_mock,
        ):
            wr.WindowRulesPage._on_save_clicked(page, btn)

        cache_mock.assert_not_called()
        reload_mock.assert_not_called()
        page.main_window.add_toast.assert_called_once()
        toast = page.main_window.add_toast.call_args[0][0]
        self.assertIn("bad lua", toast.get_title())
        btn.set_sensitive.assert_any_call(True)

    def test_reload_failure_after_successful_write_does_not_update_cache(self):
        page, btn = self._make_page({"a": self._row("kitty", _rule(workspace="2"))})
        with (
            mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.LUA),
            mock.patch("src.pages.window_rules._save_window_rules_lua"),
            mock.patch("src.pages.window_rules.reload_hyprland", side_effect=RuntimeError("hyprctl broke")),
            mock.patch("src.pages.window_rules.save_window_rules_config") as cache_mock,
        ):
            wr.WindowRulesPage._on_save_clicked(page, btn)

        cache_mock.assert_not_called()
        toast = page.main_window.add_toast.call_args[0][0]
        self.assertIn("hyprctl broke", toast.get_title())

    def test_success_updates_cache_after_write_and_reload(self):
        page, btn = self._make_page({"a": self._row("kitty", _rule(workspace="2"))})
        calls = []
        with (
            mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.LUA),
            mock.patch(
                "src.pages.window_rules._save_window_rules_lua",
                side_effect=lambda r: calls.append(("save", dict(r))),
            ),
            mock.patch(
                "src.pages.window_rules.reload_hyprland", side_effect=lambda: calls.append(("reload",))
            ),
            mock.patch(
                "src.pages.window_rules.save_window_rules_config",
                side_effect=lambda r: calls.append(("cache", dict(r))),
            ),
            mock.patch("src.pages.window_rules._load_existing_rules", return_value=[]),
        ):
            wr.WindowRulesPage._on_save_clicked(page, btn)

        self.assertEqual([c[0] for c in calls], ["save", "reload", "cache"])
        page.main_window.add_toast.assert_called_once()

    def test_legacy_reload_failure_now_surfaces_as_toast(self):
        # Regression guard: the old code called subprocess.run(["hyprctl",
        # "reload"]) directly and never checked its exit code, so a
        # failing reload silently "succeeded". reload_hyprland() must now
        # make that failure visible for the .conf provider too.
        page, btn = self._make_page({"a": self._row("kitty", _rule(workspace="2"))})
        with (
            mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch("src.pages.window_rules._write_rules_conf"),
            mock.patch("src.pages.window_rules.reload_hyprland", side_effect=RuntimeError("legacy fail")),
            mock.patch("src.pages.window_rules.save_window_rules_config") as cache_mock,
        ):
            wr.WindowRulesPage._on_save_clicked(page, btn)

        cache_mock.assert_not_called()
        toast = page.main_window.add_toast.call_args[0][0]
        self.assertIn("legacy fail", toast.get_title())

    def test_unmodified_manual_class_is_not_written(self):
        page, btn = self._make_page(
            {"a": self._row("manual-app", _rule(workspace="2"), user_modified=False)}
        )
        page._existing_rules = [
            {"rule": "workspace 5", "match_type": "class", "match_val": "manual-app", "raw": "", "managed": False}
        ]
        captured = {}
        with (
            mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.LUA),
            mock.patch(
                "src.pages.window_rules._save_window_rules_lua",
                side_effect=lambda r: captured.update(r),
            ),
            mock.patch("src.pages.window_rules.reload_hyprland"),
            mock.patch("src.pages.window_rules.save_window_rules_config"),
            mock.patch("src.pages.window_rules._load_existing_rules", return_value=[]),
        ):
            wr.WindowRulesPage._on_save_clicked(page, btn)

        self.assertNotIn("manual-app", captured)

    def test_user_modified_manual_class_is_written(self):
        page, btn = self._make_page(
            {"a": self._row("manual-app", _rule(workspace="2"), user_modified=True)}
        )
        page._existing_rules = [
            {"rule": "workspace 5", "match_type": "class", "match_val": "manual-app", "raw": "", "managed": False}
        ]
        captured = {}
        with (
            mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.LUA),
            mock.patch(
                "src.pages.window_rules._save_window_rules_lua",
                side_effect=lambda r: captured.update(r),
            ),
            mock.patch("src.pages.window_rules.reload_hyprland"),
            mock.patch("src.pages.window_rules.save_window_rules_config"),
            mock.patch("src.pages.window_rules._load_existing_rules", return_value=[]),
        ):
            wr.WindowRulesPage._on_save_clicked(page, btn)

        self.assertIn("manual-app", captured)


class ExistingTabProviderPathTest(unittest.TestCase):
    def _make_page(self) -> wr.WindowRulesPage:
        page = wr.WindowRulesPage.__new__(wr.WindowRulesPage)
        page._existing_group = mock.MagicMock()
        page._existing_group.get_parent.return_value = mock.MagicMock()
        page._existing_desc_label = mock.MagicMock()
        page._existing_rules = []
        return page

    def test_uses_lua_path_under_lua_provider(self):
        page = self._make_page()
        with mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.LUA):
            wr.WindowRulesPage._refresh_existing_tab(page)
        markup = page._existing_desc_label.set_markup.call_args[0][0]
        self.assertIn(str(hp.LUA_PATHS["rules"]), markup)
        self.assertIn("hl.window_rule", markup)

    def test_uses_conf_path_under_hyprlang_provider(self):
        page = self._make_page()
        with mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.HYPRLANG):
            wr.WindowRulesPage._refresh_existing_tab(page)
        markup = page._existing_desc_label.set_markup.call_args[0][0]
        self.assertIn(str(hp.LEGACY_PATHS["rules"]), markup)


class WorkspaceOptionsUnderLuaTest(unittest.TestCase):
    def test_options_come_from_lua_workspace_data(self):
        with (
            mock.patch("src.pages.window_rules.load_provider", return_value=hp.Provider.LUA),
            mock.patch(
                "src.pages.window_rules._load_workspaces_shared",
                return_value=[{"number": 4, "monitor": "DP-1", "default": False, "persistent": False}],
            ),
        ):
            if wr.load_provider() is wr.Provider.LUA:
                lua_workspaces = wr._load_workspaces_shared()
                options = (
                    wr.build_workspace_options(lua_workspaces)
                    if lua_workspaces
                    else wr._fallback_ws_options()
                )
        ids = [opt[0] for opt in options]
        self.assertIn("4", ids)

    def test_falls_back_to_generic_options_when_no_lua_workspaces(self):
        with mock.patch("src.pages.window_rules._load_workspaces_shared", return_value=[]):
            lua_workspaces = wr._load_workspaces_shared()
            options = (
                wr.build_workspace_options(lua_workspaces) if lua_workspaces else wr._fallback_ws_options()
            )
        ids = [opt[0] for opt in options]
        self.assertIn("1", ids)
        self.assertIn("20", ids)


class LegacyConfRegressionTest(unittest.TestCase):
    """Guards that the .conf provider path (rules.conf, MANAGED_MARKER,
    windowrule = ... lines) is untouched by the Lua work in this module."""

    def test_generate_rules_lines_workspace_and_float(self):
        rules = {"kitty": _rule(workspace="2", float_="true")}
        lines = wr._generate_rules_lines(rules)
        self.assertIn("windowrule = workspace 2, match:class kitty", lines)
        self.assertIn("windowrule = float true, match:class kitty", lines)

    def test_generate_rules_lines_skips_default_default(self):
        rules = {"kitty": _rule()}
        lines = wr._generate_rules_lines(rules)
        joined = "\n".join(lines)
        self.assertNotIn("kitty", joined)

    def test_write_rules_conf_preserves_prefix_and_writes_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.conf"
            path.write_text("# manual rule\nwindowrule = float, class:^(manual)$\n")
            with mock.patch("src.pages.window_rules.HYPR_RULES_CONF", path):
                wr._write_rules_conf(wr._generate_rules_lines({"kitty": _rule(workspace="2")}))
            content = path.read_text()
            self.assertIn("# manual rule", content)
            self.assertIn(wr.MANAGED_MARKER, content)
            self.assertIn("windowrule = workspace 2, match:class kitty", content)


if __name__ == "__main__":
    unittest.main()
