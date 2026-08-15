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
from src.pages import general, home


# ── _merge_static_input_calls (pure parsing/merge logic) ────────────────────

class MergeStaticInputCallsTest(unittest.TestCase):
    def test_single_line_call(self):
        text = 'hl.config({ input = { kb_layout = "de", numlock_by_default = false } })'
        fields = general._merge_static_input_calls(text)
        self.assertEqual(fields, {"kb_layout": "de", "numlock_by_default": False})

    def test_multiline_call(self):
        text = (
            "hl.config({\n"
            "    input = {\n"
            '        kb_layout = "de",\n'
            "        numlock_by_default = true,\n"
            "    },\n"
            "})\n"
        )
        fields = general._merge_static_input_calls(text)
        self.assertEqual(fields, {"kb_layout": "de", "numlock_by_default": True})

    def test_kb_layout_is_real_string(self):
        fields = general._merge_static_input_calls('hl.config({ input = { kb_layout = "us" } })')
        self.assertIsInstance(fields["kb_layout"], str)
        self.assertEqual(fields["kb_layout"], "us")

    def test_numlock_is_real_bool_not_string(self):
        fields = general._merge_static_input_calls("hl.config({ input = { numlock_by_default = true } })")
        self.assertIs(fields["numlock_by_default"], True)
        fields = general._merge_static_input_calls("hl.config({ input = { numlock_by_default = false } })")
        self.assertIs(fields["numlock_by_default"], False)

    def test_multiple_calls_last_static_field_wins(self):
        text = (
            'hl.config({ input = { kb_layout = "de", numlock_by_default = false } })\n'
            'hl.config({ input = { kb_layout = "us" } })\n'
        )
        fields = general._merge_static_input_calls(text)
        # kb_layout was reasserted by the second call ("us" wins); the
        # second call never mentions numlock_by_default at all, so the
        # first call's static assignment for that field still stands.
        self.assertEqual(fields, {"kb_layout": "us", "numlock_by_default": False})

    def test_extra_input_fields_are_ignored(self):
        text = 'hl.config({ input = { kb_layout = "de", sensitivity = 0.5, touchpad = { natural_scroll = true } } })'
        fields = general._merge_static_input_calls(text)
        self.assertEqual(fields, {"kb_layout": "de"})

    def test_extra_top_level_sections_are_ignored(self):
        text = (
            "hl.config({\n"
            '    general = { border_size = 2 },\n'
            '    input = { kb_layout = "de" },\n'
            "    decoration = { rounding = 10 },\n"
            "})\n"
        )
        fields = general._merge_static_input_calls(text)
        self.assertEqual(fields, {"kb_layout": "de"})

    def test_comments_and_whitespace_are_tolerated(self):
        text = (
            "-- user config\n"
            "hl.config({\n"
            "    input = {\n"
            '        kb_layout = "de", -- inline comment\n'
            "        --[[ block comment ]] numlock_by_default = true,\n"
            "    },\n"
            "})\n"
        )
        fields = general._merge_static_input_calls(text)
        self.assertEqual(fields, {"kb_layout": "de", "numlock_by_default": True})

    def test_dynamic_value_is_not_guessed(self):
        # A dynamic value makes that whole call unparseable (this codec has
        # no partial-parse recovery within a single call — see
        # rust/caelestia-core/src/lua.rs), so it contributes nothing at
        # all; a separate call's static assignment is unaffected.
        text = (
            "hl.config({ input = { numlock_by_default = true } })\n"
            "hl.config({ input = { kb_layout = vars.myLayout } })\n"
        )
        fields = general._merge_static_input_calls(text)
        self.assertNotIn("kb_layout", fields)
        self.assertEqual(fields["numlock_by_default"], True)

    def test_malformed_call_is_skipped_not_raising(self):
        text = 'hl.config({ input = )\nhl.config({ input = { kb_layout = "de" } })\n'
        fields = general._merge_static_input_calls(text)
        self.assertEqual(fields, {"kb_layout": "de"})

    def test_not_an_hl_config_call_is_ignored(self):
        fields = general._merge_static_input_calls('hl.monitor({ output = "DP-1" })')
        self.assertEqual(fields, {})

    def test_no_calls_returns_empty(self):
        self.assertEqual(general._merge_static_input_calls(""), {})
        self.assertEqual(general._merge_static_input_calls("local x = 1"), {})


# ── Read (whole-file effective value + own-managed-block value) ────────────

class ReadInputLuaTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.lua_path = Path(self._tmpdir.name) / "input.lua"
        patcher = mock.patch.dict(hp.LUA_PATHS, {"input": self.lua_path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_file_returns_empty(self):
        self.assertEqual(general._read_input_lua(), {})

    def test_managed_block_present_is_read(self):
        hp.write_managed_lua_block(
            self.lua_path,
            general.INPUT_LUA_BLOCK,
            [general.caelestia_core.render_lua_call("hl.config", [{"input": {"kb_layout": "de"}}])],
        )
        self.assertEqual(general._read_input_lua(), {"kb_layout": "de"})

    def test_no_managed_block_but_manual_call_is_read(self):
        self.lua_path.write_text('hl.config({ input = { kb_layout = "gb" } })\n')
        self.assertEqual(general._read_input_lua(), {"kb_layout": "gb"})

    def test_returns_string_values_matching_legacy_contract(self):
        self.lua_path.write_text(
            'hl.config({ input = { kb_layout = "de", numlock_by_default = true } })\n'
        )
        result = general._read_input_lua()
        self.assertEqual(result, {"kb_layout": "de", "numlock_by_default": "true"})
        self.assertIsInstance(result["numlock_by_default"], str)

    def test_dynamic_values_are_absent_not_guessed(self):
        self.lua_path.write_text("hl.config({ input = { kb_layout = vars.dynamicLayout } })\n")
        self.assertEqual(general._read_input_lua(), {})

    def test_corrupted_managed_block_fails_closed(self):
        self.lua_path.write_text(
            "-- BEGIN Caelestia Settings managed block: input\n"
            'hl.config({ input = { kb_layout = "de" } })\n'
            "-- BEGIN Caelestia Settings managed block: input\n"
            "-- END Caelestia Settings managed block: input\n"
        )
        with self.assertRaises(hp.ManagedBlockError):
            general._read_input_lua()

    def test_home_dashboard_does_not_read_legacy_input_conf_under_lua(self):
        self.lua_path.write_text('hl.config({ input = { kb_layout = "fr" } })\n')
        page = types.SimpleNamespace(_layout_row=mock.MagicMock())
        with mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA):
            home.HomePage._refresh_layout(page)
        page._layout_row.set_subtitle.assert_called_once()
        self.assertIn("fr", page._layout_row.set_subtitle.call_args[0][0].lower())


class ReadOwnManagedInputFieldsTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.lua_path = Path(self._tmpdir.name) / "input.lua"
        patcher = mock.patch.dict(hp.LUA_PATHS, {"input": self.lua_path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ignores_manual_calls_outside_own_block(self):
        self.lua_path.write_text('hl.config({ input = { kb_layout = "manual-only" } })\n')
        self.assertEqual(general._read_own_managed_input_fields(), {})

    def test_reads_only_own_block_content(self):
        self.lua_path.write_text('hl.config({ input = { kb_layout = "manual" } })\n')
        hp.write_managed_lua_block(
            self.lua_path,
            general.INPUT_LUA_BLOCK,
            [general.caelestia_core.render_lua_call("hl.config", [{"input": {"kb_layout": "de"}}])],
        )
        self.assertEqual(general._read_own_managed_input_fields(), {"kb_layout": "de"})


# ── Write (partial-update managed-block writer) ─────────────────────────────

class WriteInputLuaFieldTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.lua_path = Path(self._tmpdir.name) / "input.lua"
        lua_patcher = mock.patch.dict(hp.LUA_PATHS, {"input": self.lua_path})
        lua_patcher.start()
        self.addCleanup(lua_patcher.stop)
        provider_patcher = mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA)
        provider_patcher.start()
        self.addCleanup(provider_patcher.stop)
        reload_patcher = mock.patch("src.hypr_provider.reload_hyprland")
        self.reload_mock = reload_patcher.start()
        self.addCleanup(reload_patcher.stop)

    def test_first_write_creates_block_with_only_that_field(self):
        general._write_input_lua_field("kb_layout", "de")
        self.assertEqual(hp.read_managed_lua_block(self.lua_path, general.INPUT_LUA_BLOCK), [
            'hl.config({ input = { kb_layout = "de" } })'
        ])
        self.reload_mock.assert_called_once()

    def test_changing_only_layout_preserves_existing_numlock(self):
        general._write_input_lua_field("numlock_by_default", True)
        general._write_input_lua_field("kb_layout", "de")
        self.assertEqual(
            general._read_own_managed_input_fields(),
            {"kb_layout": "de", "numlock_by_default": True},
        )

    def test_changing_only_numlock_preserves_existing_layout(self):
        general._write_input_lua_field("kb_layout", "de")
        general._write_input_lua_field("numlock_by_default", False)
        self.assertEqual(
            general._read_own_managed_input_fields(),
            {"kb_layout": "de", "numlock_by_default": False},
        )

    def test_no_unchecked_default_written_for_untouched_field_on_first_write(self):
        general._write_input_lua_field("kb_layout", "de")
        content = self.lua_path.read_text()
        self.assertNotIn("numlock_by_default", content)

    def test_boolean_stays_a_real_lua_boolean_not_a_string(self):
        general._write_input_lua_field("numlock_by_default", True)
        content = self.lua_path.read_text()
        self.assertIn("numlock_by_default = true", content)
        self.assertNotIn('numlock_by_default = "true"', content)

    def test_string_escaping_via_rust_renderer(self):
        general._write_input_lua_field("kb_layout", 'weird"layout\\name')
        fields = general._read_own_managed_input_fields()
        self.assertEqual(fields["kb_layout"], 'weird"layout\\name')

    def test_unicode_roundtrip(self):
        general._write_input_lua_field("kb_layout", "Bürö – 日本語 – ✨")
        fields = general._read_own_managed_input_fields()
        self.assertEqual(fields["kb_layout"], "Bürö – 日本語 – ✨")

    def test_manual_prefix_and_suffix_preserved_byte_exact(self):
        self.lua_path.write_text("-- header\nlocal x = 1\n")
        general._write_input_lua_field("kb_layout", "de")
        content = self.lua_path.read_text()
        content += "\n-- footer\n"
        self.lua_path.write_text(content)
        general._write_input_lua_field("kb_layout", "us")
        final = self.lua_path.read_text()
        self.assertIn("-- header", final)
        self.assertIn("local x = 1", final)
        self.assertIn("-- footer", final)

    def test_other_hl_config_calls_are_preserved(self):
        manual = 'hl.config({ general = { border_size = 2 } })\n'
        self.lua_path.write_text(manual)
        general._write_input_lua_field("kb_layout", "de")
        self.assertIn(manual.strip(), self.lua_path.read_text())

    def test_touchpad_binds_cursor_and_unknown_fields_preserved(self):
        manual = 'hl.config({ input = { touchpad = { natural_scroll = true } }, binds = { workspace_back_and_forth = true }, cursor = { no_hardware_cursors = true } })\n'
        self.lua_path.write_text(manual)
        general._write_input_lua_field("kb_layout", "de")
        self.assertIn(manual.strip(), self.lua_path.read_text())

    def test_other_named_managed_block_preserved(self):
        hp.write_managed_lua_block(self.lua_path, "monitors", ['hl.monitor({ output = "DP-1" })'])
        general._write_input_lua_field("kb_layout", "de")
        self.assertEqual(
            hp.read_managed_lua_block(self.lua_path, "monitors"), ['hl.monitor({ output = "DP-1" })']
        )

    def test_crlf_preserved(self):
        self.lua_path.write_bytes(b"-- header\r\nlocal x = 1\r\n")
        general._write_input_lua_field("kb_layout", "de")
        self.assertIn(b"\r\n", self.lua_path.read_bytes())

    def test_missing_final_newline_in_prefix_preserved_before_block(self):
        self.lua_path.write_text("-- header, no trailing newline")
        general._write_input_lua_field("kb_layout", "de")
        content = self.lua_path.read_text()
        self.assertIn("-- header, no trailing newline", content)

    def test_idempotent_resave_produces_exactly_one_block(self):
        general._write_input_lua_field("kb_layout", "de")
        general._write_input_lua_field("kb_layout", "de")
        content = self.lua_path.read_text()
        self.assertEqual(
            content.count(f"-- BEGIN Caelestia Settings managed block: {general.INPUT_LUA_BLOCK}"), 1
        )

    def test_luac_syntax_failure_leaves_original_file_unchanged(self):
        self.lua_path.write_text("-- original\n")
        fake = mock.MagicMock()
        fake.returncode = 1
        fake.stderr = "syntax error"
        with (
            mock.patch("src.hypr_provider.shutil.which", return_value="/usr/bin/luac"),
            mock.patch("src.hypr_provider.subprocess.run", return_value=fake),
        ):
            with self.assertRaises(hp.LuaWriteError):
                general._write_input_lua_field("kb_layout", "de")
        self.assertEqual(self.lua_path.read_text(), "-- original\n")

    def test_missing_luac_raises_and_leaves_file_unchanged(self):
        self.lua_path.write_text("-- original\n")
        with mock.patch("src.hypr_provider.shutil.which", return_value=None):
            with self.assertRaises(hp.LuaWriteError):
                general._write_input_lua_field("kb_layout", "de")
        self.assertEqual(self.lua_path.read_text(), "-- original\n")

    def test_reload_failure_rolls_back_and_reloads_again(self):
        general._write_input_lua_field("kb_layout", "de")
        original = self.lua_path.read_bytes()
        self.reload_mock.reset_mock()
        self.reload_mock.side_effect = RuntimeError("hyprctl broke")
        with self.assertRaises(RuntimeError):
            general._write_input_lua_field("kb_layout", "us")
        self.assertEqual(self.lua_path.read_bytes(), original)
        # Once for the failed write's own reload, once more for the
        # rollback's reload.
        self.assertEqual(self.reload_mock.call_count, 2)

    def test_write_without_lua_provider_is_rejected(self):
        with mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG):
            with self.assertRaises(hp.ProviderCapabilityError):
                general._write_input_lua_field("kb_layout", "de")
        self.assertFalse(self.lua_path.exists())

    def test_write_without_any_provider_is_rejected(self):
        with mock.patch.object(hp, "load_provider", return_value=None):
            with self.assertRaises(hp.ProviderCapabilityError):
                general._write_input_lua_field("kb_layout", "de")
        self.assertFalse(self.lua_path.exists())


class RealLuacValidationTest(unittest.TestCase):
    """The mandatory positive syntax path: at least one write is validated
    against the real system `luac`, not a mock."""

    def test_written_file_is_valid_lua_per_real_luac(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_path = Path(tmp) / "input.lua"
            with (
                mock.patch.dict(hp.LUA_PATHS, {"input": lua_path}),
                mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA),
                mock.patch("src.hypr_provider.reload_hyprland"),
            ):
                general._write_input_lua_field("kb_layout", "de")
                general._write_input_lua_field("numlock_by_default", True)
            self.assertTrue(lua_path.exists())


# ── read_input_conf() provider dispatch ─────────────────────────────────────

class ReadInputConfDispatchTest(unittest.TestCase):
    def test_routes_to_lua(self):
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_read_input_lua", return_value={"kb_layout": "de"}) as m,
        ):
            self.assertEqual(general.read_input_conf(), {"kb_layout": "de"})
        m.assert_called_once()

    def test_routes_to_hyprlang(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.conf"
            path.write_text("input {\n    kb_layout = us\n}\n")
            with mock.patch.object(general, "HYPR_INPUT_CONF", path):
                result = general.read_input_conf(hp.Provider.HYPRLANG)
        self.assertEqual(result["kb_layout"], "us")

    def test_none_provider_reads_nothing(self):
        with mock.patch.object(general, "_read_input_lua") as lua_mock:
            self.assertEqual(general.read_input_conf(None), {})
        lua_mock.assert_not_called()


# ── Page callbacks: provider-aware write + live apply ───────────────────────

class GeneralPageCallbackLuaTest(unittest.TestCase):
    """Exercises GeneralPage's provider-aware write callbacks against a
    minimally constructed page (bypassing __init__/GTK widget
    construction), mirroring the pattern used for WindowRulesPage."""

    def _make_page(self):
        page = types.SimpleNamespace()
        page.main_window = mock.MagicMock()
        page.is_loading = False
        page.show_toast = types.MethodType(general.GeneralPage.show_toast, page)
        return page

    def test_lua_layout_change_never_calls_hyprctl_keyword(self):
        page = self._make_page()
        combo = mock.MagicMock()
        combo.get_active_id.return_value = "de"
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_write_input_lua_field") as write_mock,
            mock.patch.object(general.subprocess, "run") as run_mock,
        ):
            general.GeneralPage._on_layout_changed(page, combo)
        write_mock.assert_called_once_with("kb_layout", "de")
        run_mock.assert_not_called()
        page.main_window.add_toast.assert_called_once()

    def test_lua_numlock_change_never_calls_hyprctl_keyword(self):
        page = self._make_page()
        row = mock.MagicMock()
        row.get_active.return_value = True
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_write_input_lua_field") as write_mock,
            mock.patch.object(general.subprocess, "run") as run_mock,
        ):
            general.GeneralPage._on_numlock_changed(page, row, None)
        write_mock.assert_called_once_with("numlock_by_default", True)
        run_mock.assert_not_called()
        page.main_window.add_toast.assert_called_once()

    def test_lua_write_failure_shows_error_toast_not_success(self):
        page = self._make_page()
        combo = mock.MagicMock()
        combo.get_active_id.return_value = "de"
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_write_input_lua_field", side_effect=hp.LuaWriteError("bad lua")),
        ):
            general.GeneralPage._on_layout_changed(page, combo)
        page.main_window.add_toast.assert_called_once()
        toast = page.main_window.add_toast.call_args[0][0]
        self.assertIn("bad lua", toast.get_title())

    def test_hyprlang_layout_change_keeps_existing_live_behavior(self):
        page = self._make_page()
        combo = mock.MagicMock()
        combo.get_active_id.return_value = "de"
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.HYPRLANG),
            # require_config_capability() (called by the unmocked HYPRLANG
            # write path below) reads the provider via hp's own module-level
            # load_provider, a separate binding from general's imported one
            # — both must agree for this real capability check to pass.
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch.object(general, "_write_input_conf_key") as write_mock,
            mock.patch.object(general.subprocess, "run") as run_mock,
        ):
            general.GeneralPage._on_layout_changed(page, combo)
        write_mock.assert_called_once_with("kb_layout", "de")
        run_mock.assert_called_once_with(["hyprctl", "keyword", "input:kb_layout", "de"], check=True)


# ── _load_all: language/timezone regression under the now-unlocked Lua path ─

class LoadAllLanguageTimezoneRegressionTest(unittest.TestCase):
    def _make_page(self):
        page = types.SimpleNamespace(
            layout_combo=mock.MagicMock(),
            numlock_row=mock.MagicMock(),
            lang_combo=mock.MagicMock(),
            time_combo=mock.MagicMock(),
            is_loading=False,
        )
        page.layout_combo.set_active_id.return_value = True
        page.lang_combo.set_active_id.return_value = True
        page.time_combo.set_active_id.return_value = True
        return page

    def test_language_and_timezone_still_populate_under_lua(self):
        page = self._make_page()
        localectl_result = mock.MagicMock(stdout="LANG=de_DE.UTF-8\n")
        timedatectl_result = mock.MagicMock(stdout="Europe/Berlin\n")
        with (
            mock.patch.object(general, "read_input_conf", return_value={"kb_layout": "de"}),
            mock.patch.object(
                general.subprocess, "run", side_effect=[localectl_result, timedatectl_result]
            ),
        ):
            general.GeneralPage._load_all(page, hp.Provider.LUA)
        page.lang_combo.set_active_id.assert_called_once_with("de_DE.UTF-8")
        page.time_combo.set_active_id.assert_called_once_with("Europe/Berlin")
        self.assertFalse(page.is_loading)

    def test_undeterminable_fields_do_not_raise_under_lua(self):
        page = self._make_page()
        page.layout_combo.set_active_id.return_value = False
        with (
            mock.patch.object(general, "read_input_conf", return_value={}),
            mock.patch.object(general.subprocess, "run", side_effect=Exception("no localectl")),
        ):
            general.GeneralPage._load_all(page, hp.Provider.LUA)
        page.numlock_row.set_active.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
