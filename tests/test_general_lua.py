import json
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


# ── hyprctl getoption plumbing ──────────────────────────────────────────────
#
# Every test in this file that touches an "effective value" read or a write
# verification MUST mock hyprctl (directly or via the typed wrappers) —
# this dev/CI environment may have a real Hyprland session reachable via
# `hyprctl`, and letting a test depend on that would make results
# nondeterministic across machines. See VALIDATION notes in the M5.1 report
# for the one-off manual real-`hyprctl -j getoption` sanity check instead.


class HyprctlGetoptionTest(unittest.TestCase):
    def test_missing_binary_returns_none(self):
        with mock.patch.object(general.shutil, "which", return_value=None):
            self.assertIsNone(general._hyprctl_getoption("input:kb_layout"))

    def test_nonzero_exit_returns_none(self):
        fake = mock.MagicMock(returncode=1, stdout="")
        with (
            mock.patch.object(general.shutil, "which", return_value="/usr/bin/hyprctl"),
            mock.patch.object(general.subprocess, "run", return_value=fake),
        ):
            self.assertIsNone(general._hyprctl_getoption("input:kb_layout"))

    def test_timeout_returns_none(self):
        with (
            mock.patch.object(general.shutil, "which", return_value="/usr/bin/hyprctl"),
            mock.patch.object(
                general.subprocess, "run", side_effect=general.subprocess.TimeoutExpired("hyprctl", 3)
            ),
        ):
            self.assertIsNone(general._hyprctl_getoption("input:kb_layout"))

    def test_oserror_returns_none(self):
        with (
            mock.patch.object(general.shutil, "which", return_value="/usr/bin/hyprctl"),
            mock.patch.object(general.subprocess, "run", side_effect=OSError("boom")),
        ):
            self.assertIsNone(general._hyprctl_getoption("input:kb_layout"))

    def test_invalid_json_returns_none(self):
        fake = mock.MagicMock(returncode=0, stdout="not json{{{")
        with (
            mock.patch.object(general.shutil, "which", return_value="/usr/bin/hyprctl"),
            mock.patch.object(general.subprocess, "run", return_value=fake),
        ):
            self.assertIsNone(general._hyprctl_getoption("input:kb_layout"))

    def test_json_array_instead_of_object_returns_none(self):
        fake = mock.MagicMock(returncode=0, stdout="[1, 2, 3]")
        with (
            mock.patch.object(general.shutil, "which", return_value="/usr/bin/hyprctl"),
            mock.patch.object(general.subprocess, "run", return_value=fake),
        ):
            self.assertIsNone(general._hyprctl_getoption("input:kb_layout"))

    def test_valid_object_is_returned(self):
        fake = mock.MagicMock(returncode=0, stdout=json.dumps({"option": "input:kb_layout", "str": "de"}))
        with (
            mock.patch.object(general.shutil, "which", return_value="/usr/bin/hyprctl"),
            mock.patch.object(general.subprocess, "run", return_value=fake),
        ):
            self.assertEqual(general._hyprctl_getoption("input:kb_layout"), {"option": "input:kb_layout", "str": "de"})


class EffectiveKbLayoutTest(unittest.TestCase):
    def test_known_value(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value={"str": "de"}):
            self.assertEqual(general._get_effective_kb_layout(), "de")

    def test_unreachable_is_none(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value=None):
            self.assertIsNone(general._get_effective_kb_layout())

    def test_missing_str_key_is_none(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value={"option": "input:kb_layout"}):
            self.assertIsNone(general._get_effective_kb_layout())

    def test_wrong_type_is_none(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value={"str": 42}):
            self.assertIsNone(general._get_effective_kb_layout())

    def test_empty_string_is_none(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value={"str": ""}):
            self.assertIsNone(general._get_effective_kb_layout())

    def test_whitespace_only_is_none(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value={"str": "   "}):
            self.assertIsNone(general._get_effective_kb_layout())


class EffectiveNumlockTest(unittest.TestCase):
    def test_int_zero_is_false(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value={"int": 0}):
            self.assertIs(general._get_effective_numlock(), False)

    def test_int_one_is_true(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value={"int": 1}):
            self.assertIs(general._get_effective_numlock(), True)

    def test_unreachable_is_none(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value=None):
            self.assertIsNone(general._get_effective_numlock())

    def test_other_int_value_is_none(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value={"int": 5}):
            self.assertIsNone(general._get_effective_numlock())

    def test_missing_int_key_is_none(self):
        with mock.patch.object(general, "_hyprctl_getoption", return_value={"option": "input:numlock_by_default"}):
            self.assertIsNone(general._get_effective_numlock())


# ── _merge_static_input_calls (own-managed-block parsing only) ─────────────

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

    def test_numlock_is_real_bool_not_string(self):
        fields = general._merge_static_input_calls("hl.config({ input = { numlock_by_default = true } })")
        self.assertIs(fields["numlock_by_default"], True)

    def test_multiple_calls_last_static_field_wins(self):
        text = (
            'hl.config({ input = { kb_layout = "de", numlock_by_default = false } })\n'
            'hl.config({ input = { kb_layout = "us" } })\n'
        )
        fields = general._merge_static_input_calls(text)
        self.assertEqual(fields, {"kb_layout": "us", "numlock_by_default": False})

    def test_extra_input_fields_are_ignored(self):
        text = 'hl.config({ input = { kb_layout = "de", touchpad = { natural_scroll = true } } })'
        self.assertEqual(general._merge_static_input_calls(text), {"kb_layout": "de"})

    def test_dynamic_call_contributes_nothing_even_for_its_static_fields(self):
        # A dynamic value anywhere in the call means the WHOLE call fails
        # to parse (no partial-parse recovery — see lua.rs), so it must
        # not be treated as if only the dynamic field were missing.
        text = 'hl.config({ input = { kb_layout = "de", numlock_by_default = vars.x } })'
        self.assertEqual(general._merge_static_input_calls(text), {})

    def test_malformed_call_is_skipped_not_raising(self):
        text = 'hl.config({ input = )\nhl.config({ input = { kb_layout = "de" } })\n'
        self.assertEqual(general._merge_static_input_calls(text), {"kb_layout": "de"})

    def test_no_calls_returns_empty(self):
        self.assertEqual(general._merge_static_input_calls(""), {})


# ── Effective-value read (_read_input_lua): the actual M5.1 bug fix ────────

class ReadInputLuaTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.lua_path = Path(self._tmpdir.name) / "input.lua"
        patcher = mock.patch.dict(hp.LUA_PATHS, {"input": self.lua_path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _mock_effective(self, layout=None, numlock=None):
        return (
            mock.patch.object(general, "_get_effective_kb_layout", return_value=layout),
            mock.patch.object(general, "_get_effective_numlock", return_value=numlock),
        )

    def test_static_then_static_second_wins(self):
        # File content is irrelevant to the *effective* value now — only
        # hyprctl's own live-resolved state is trusted, which is the whole
        # fix: no more guessing which of possibly many static/dynamic
        # calls "won".
        self.lua_path.write_text(
            'hl.config({ input = { kb_layout = "de" } })\n'
            'hl.config({ input = { kb_layout = "us" } })\n'
        )
        p1, p2 = self._mock_effective(layout="us")
        with p1, p2:
            self.assertEqual(general._read_input_lua(), {"kb_layout": "us"})

    def test_dynamic_then_static_treats_later_value_as_known(self):
        self.lua_path.write_text(
            "hl.config({ input = { kb_layout = vars.x } })\n"
            'hl.config({ input = { kb_layout = "us" } })\n'
        )
        p1, p2 = self._mock_effective(layout="us")
        with p1, p2:
            self.assertEqual(general._read_input_lua(), {"kb_layout": "us"})

    def test_static_then_dynamic_override_of_same_field_is_not_shown_as_the_earlier_value(self):
        # This is the exact example from the M5.1 spec: the file has a
        # static "de" followed by a dynamic override. Since the effective
        # value now always comes from hyprctl (unmocked here means
        # unreachable in a bare unit test), "de" must never leak through.
        self.lua_path.write_text(
            'hl.config({ input = { kb_layout = "de" } })\n'
            "hl.config({ input = { kb_layout = vars.layout } })\n"
        )
        p1, p2 = self._mock_effective(layout=None)
        with p1, p2:
            self.assertNotIn("kb_layout", general._read_input_lua())

    def test_only_dynamic_value_is_unknown(self):
        self.lua_path.write_text("hl.config({ input = { kb_layout = vars.x } })\n")
        p1, p2 = self._mock_effective(layout=None)
        with p1, p2:
            self.assertEqual(general._read_input_lua(), {})

    def test_no_value_present_anywhere_is_absent(self):
        p1, p2 = self._mock_effective(layout=None, numlock=None)
        with p1, p2:
            self.assertEqual(general._read_input_lua(), {})

    def test_static_target_plus_irrelevant_dynamic_value_in_same_call(self):
        # kb_layout is static and known; a sibling dynamic field
        # (touchpad.natural_scroll, say) must not block it — but since
        # this codec has no partial-parse recovery, a genuinely dynamic
        # value ANYWHERE in the call means the whole call is unparsable.
        # The effective-value source (hyprctl) sidesteps this entirely by
        # construction: it doesn't parse the file at all.
        self.lua_path.write_text(
            'hl.config({ input = { kb_layout = "de", sensitivity = vars.s } })\n'
        )
        p1, p2 = self._mock_effective(layout="de")
        with p1, p2:
            self.assertEqual(general._read_input_lua(), {"kb_layout": "de"})

    def test_getoption_known_value_is_returned(self):
        p1, p2 = self._mock_effective(layout="de", numlock=True)
        with p1, p2:
            self.assertEqual(general._read_input_lua(), {"kb_layout": "de", "numlock_by_default": "true"})

    def test_getoption_unreachable_is_absent_not_guessed(self):
        p1, p2 = self._mock_effective(layout=None, numlock=None)
        with p1, p2:
            result = general._read_input_lua()
        self.assertNotIn("kb_layout", result)
        self.assertNotIn("numlock_by_default", result)

    def test_result_does_not_depend_on_file_existing(self):
        # The .lua file doesn't even need to exist — hyprctl is asked
        # directly.
        self.assertFalse(self.lua_path.exists())
        p1, p2 = self._mock_effective(layout="de")
        with p1, p2:
            self.assertEqual(general._read_input_lua(), {"kb_layout": "de"})

    def test_corrupted_managed_block_fails_closed(self):
        self.lua_path.write_text(
            "-- BEGIN Caelestia Settings managed block: input\n"
            'hl.config({ input = { kb_layout = "de" } })\n'
            "-- BEGIN Caelestia Settings managed block: input\n"
            "-- END Caelestia Settings managed block: input\n"
        )
        p1, p2 = self._mock_effective(layout="de")
        with p1, p2:
            with self.assertRaises(hp.ManagedBlockError):
                general._read_input_lua()

    def test_home_dashboard_does_not_guess_a_default(self):
        page = types.SimpleNamespace(_layout_row=mock.MagicMock())
        p1, p2 = self._mock_effective(layout=None)
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            p1,
            p2,
        ):
            home.HomePage._refresh_layout(page)
        subtitle = page._layout_row.set_subtitle.call_args[0][0]
        self.assertNotIn("us", subtitle.lower())

    def test_home_dashboard_shows_known_effective_value(self):
        page = types.SimpleNamespace(_layout_row=mock.MagicMock())
        p1, p2 = self._mock_effective(layout="fr")
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            p1,
            p2,
        ):
            home.HomePage._refresh_layout(page)
        subtitle = page._layout_row.set_subtitle.call_args[0][0]
        self.assertIn("fr", subtitle.lower())


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


# ── Strict helper validation (section 4) ────────────────────────────────────

class ValidateInputFieldTest(unittest.TestCase):
    def test_valid_kb_layout(self):
        general._validate_input_field("kb_layout", "de")  # must not raise

    def test_valid_numlock(self):
        general._validate_input_field("numlock_by_default", True)
        general._validate_input_field("numlock_by_default", False)

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("touchpad", "x")

    def test_kb_layout_bool_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("kb_layout", True)

    def test_kb_layout_empty_string_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("kb_layout", "")

    def test_kb_layout_whitespace_only_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("kb_layout", "   ")

    def test_numlock_string_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("numlock_by_default", "true")

    def test_numlock_int_one_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("numlock_by_default", 1)

    def test_numlock_int_zero_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("numlock_by_default", 0)

    def test_numlock_float_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("numlock_by_default", 1.0)

    def test_kb_layout_none_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("kb_layout", None)

    def test_kb_layout_int_rejected(self):
        with self.assertRaises(ValueError):
            general._validate_input_field("kb_layout", 5)


class WriteRejectsBeforeAnySideEffectTest(unittest.TestCase):
    """Invalid input must never resolve the target path, touch the lock,
    backup, temp file, luac, or reload — verified by mocking every one of
    those and asserting none of them were even called."""

    def _assert_no_side_effects(self, key, value):
        with (
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "resolve_path") as resolve_mock,
            mock.patch.object(general, "require_config_capability") as cap_mock,
            mock.patch.object(general, "update_managed_lua_block_and_reload") as update_mock,
        ):
            with self.assertRaises(ValueError):
                general._write_input_lua_field(key, value)
        resolve_mock.assert_not_called()
        cap_mock.assert_not_called()
        update_mock.assert_not_called()

    def test_unknown_key(self):
        self._assert_no_side_effects("touchpad", "x")

    def test_kb_layout_bool(self):
        self._assert_no_side_effects("kb_layout", True)

    def test_kb_layout_empty(self):
        self._assert_no_side_effects("kb_layout", "")

    def test_kb_layout_whitespace(self):
        self._assert_no_side_effects("kb_layout", "   ")

    def test_numlock_string(self):
        self._assert_no_side_effects("numlock_by_default", "true")

    def test_numlock_int(self):
        self._assert_no_side_effects("numlock_by_default", 1)


# ── Write: lock-scoped partial merge, verification, rollback ───────────────

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

        # By default, simulate hyprctl faithfully reporting whatever the
        # app's own managed block currently says post-reload — the happy
        # path for every test that isn't specifically about verification
        # mismatches. Individual tests override these to simulate a
        # later-override-wins scenario.
        layout_patcher = mock.patch.object(
            general, "_get_effective_kb_layout",
            side_effect=lambda: general._read_own_managed_input_fields().get("kb_layout"),
        )
        self.layout_effective_mock = layout_patcher.start()
        self.addCleanup(layout_patcher.stop)
        numlock_patcher = mock.patch.object(
            general, "_get_effective_numlock",
            side_effect=lambda: general._read_own_managed_input_fields().get("numlock_by_default"),
        )
        self.numlock_effective_mock = numlock_patcher.start()
        self.addCleanup(numlock_patcher.stop)

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
        self.assertNotIn("numlock_by_default", self.lua_path.read_text())

    def test_boolean_stays_a_real_lua_boolean_not_a_string(self):
        general._write_input_lua_field("numlock_by_default", True)
        content = self.lua_path.read_text()
        self.assertIn("numlock_by_default = true", content)
        self.assertNotIn('numlock_by_default = "true"', content)

    def test_string_escaping_via_rust_renderer(self):
        general._write_input_lua_field("kb_layout", 'weird"layout\\name')
        self.assertEqual(
            general._read_own_managed_input_fields()["kb_layout"], 'weird"layout\\name'
        )

    def test_unicode_roundtrip(self):
        general._write_input_lua_field("kb_layout", "Bürö – 日本語 – ✨")
        self.assertEqual(
            general._read_own_managed_input_fields()["kb_layout"], "Bürö – 日本語 – ✨"
        )

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
        manual = (
            'hl.config({ input = { touchpad = { natural_scroll = true } }, '
            'binds = { workspace_back_and_forth = true }, '
            'cursor = { no_hardware_cursors = true } })\n'
        )
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
        self.assertIn("-- header, no trailing newline", self.lua_path.read_text())

    def test_idempotent_resave_produces_exactly_one_block(self):
        general._write_input_lua_field("kb_layout", "de")
        general._write_input_lua_field("kb_layout", "de")
        content = self.lua_path.read_text()
        self.assertEqual(
            content.count(f"-- BEGIN Caelestia Settings managed block: {general.INPUT_LUA_BLOCK}"), 1
        )

    def test_luac_syntax_failure_leaves_original_file_unchanged(self):
        self.lua_path.write_text("-- original\n")
        fake = mock.MagicMock(returncode=1, stderr="syntax error")
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
        self.assertEqual(self.reload_mock.call_count, 2)

    def test_corrupted_managed_block_raises_before_any_change(self):
        self.lua_path.write_text(
            "-- BEGIN Caelestia Settings managed block: input\n"
            "-- BEGIN Caelestia Settings managed block: input\n"
            "-- END Caelestia Settings managed block: input\n"
        )
        original = self.lua_path.read_bytes()
        with self.assertRaises(hp.ManagedBlockError):
            general._write_input_lua_field("kb_layout", "de")
        self.assertEqual(self.lua_path.read_bytes(), original)
        self.reload_mock.assert_not_called()

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

    # ── Post-reload verification (section 2) ────────────────────────────

    def test_kb_layout_verification_uses_kb_layout_getter(self):
        self.layout_effective_mock.side_effect = None
        self.layout_effective_mock.return_value = "us"  # later override wins
        with self.assertRaises(RuntimeError):
            general._write_input_lua_field("kb_layout", "de")

    def test_numlock_verification_uses_numlock_getter(self):
        self.numlock_effective_mock.side_effect = None
        self.numlock_effective_mock.return_value = False  # later override wins
        with self.assertRaises(RuntimeError):
            general._write_input_lua_field("numlock_by_default", True)

    def test_verification_only_checks_the_field_being_changed(self):
        # numlock's effective getter is deliberately "wrong"/unmocked-
        # default here; only kb_layout is being changed, so only
        # kb_layout's verification result should matter.
        self.numlock_effective_mock.side_effect = None
        self.numlock_effective_mock.return_value = None
        general._write_input_lua_field("kb_layout", "de")  # must not raise

    def test_verification_mismatch_is_treated_as_apply_failure_not_success(self):
        # First write has no baseline to roll back to, so the file simply
        # wouldn't exist afterward — assert that instead of "us" ever
        # having been written and left in place.
        self.layout_effective_mock.side_effect = None
        self.layout_effective_mock.return_value = "us"
        with self.assertRaises(RuntimeError):
            general._write_input_lua_field("kb_layout", "de")
        self.assertFalse(self.lua_path.exists())

    def test_verification_mismatch_rolls_back_and_reloads_twice(self):
        general._write_input_lua_field("kb_layout", "us")  # establish a baseline
        self.reload_mock.reset_mock()
        self.layout_effective_mock.side_effect = None
        self.layout_effective_mock.return_value = "fr"  # never matches "de"
        with self.assertRaises(RuntimeError):
            general._write_input_lua_field("kb_layout", "de")
        self.assertEqual(self.reload_mock.call_count, 2)
        self.assertEqual(general._read_own_managed_input_fields().get("kb_layout"), "us")

    def test_unreachable_verification_is_not_confirmed_as_success(self):
        self.layout_effective_mock.side_effect = None
        self.layout_effective_mock.return_value = None  # hyprctl unreachable
        with self.assertRaises(RuntimeError):
            general._write_input_lua_field("kb_layout", "de")

    # ── Lock-scoped partial merge / TOCTOU race (section 3) ─────────────

    def test_transform_reads_fresh_state_under_lock_not_a_stale_pre_lock_read(self):
        general._write_input_lua_field("kb_layout", "de")

        real_lock = hp._with_managed_write_lock

        def racing_lock(path):
            # A foreign writer's change becomes visible exactly as our own
            # transaction's critical section begins — i.e. strictly AFTER
            # any hypothetical pre-lock read the app might have performed
            # (the M5.1 bug), and strictly BEFORE the app decides what to
            # write. A stale pre-lock read would silently discard this.
            lock_file = real_lock(path)
            content = path.read_text().replace(
                'hl.config({ input = { kb_layout = "de" } })',
                'hl.config({ input = { kb_layout = "de", numlock_by_default = true } })',
            )
            path.write_text(content)
            return lock_file

        with mock.patch.object(hp, "_with_managed_write_lock", side_effect=racing_lock):
            general._write_input_lua_field("kb_layout", "us")

        self.assertEqual(
            general._read_own_managed_input_fields(),
            {"kb_layout": "us", "numlock_by_default": True},
        )

    def test_concurrent_modification_during_critical_section_aborts_visibly(self):
        general._write_input_lua_field("kb_layout", "de")
        real_render = hp._render_managed_content

        def racing_render(*args, **kwargs):
            # An external, lock-naive writer mutates the file after our
            # own lock-scoped read but before our atomic replace.
            self.lua_path.write_text(self.lua_path.read_text() + "\n-- raced\n")
            return real_render(*args, **kwargs)

        with mock.patch.object(hp, "_render_managed_content", side_effect=racing_render):
            with self.assertRaises(hp.ManagedBlockError):
                general._write_input_lua_field("kb_layout", "us")


class RealLuacValidationTest(unittest.TestCase):
    """The mandatory positive syntax path: at least one write is validated
    against the real system `luac`, not a mock. hyprctl itself is still
    mocked (see module docstring above)."""

    def test_written_file_is_valid_lua_per_real_luac(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_path = Path(tmp) / "input.lua"
            with (
                mock.patch.dict(hp.LUA_PATHS, {"input": lua_path}),
                mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA),
                mock.patch("src.hypr_provider.reload_hyprland"),
                mock.patch.object(general, "_get_effective_kb_layout", return_value="de"),
                mock.patch.object(general, "_get_effective_numlock", return_value=True),
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


# ── Page callbacks: provider-aware write + live apply + error recovery ─────

class GeneralPageCallbackLuaTest(unittest.TestCase):
    """Exercises GeneralPage's provider-aware write callbacks against a
    minimally constructed page (bypassing __init__/GTK widget
    construction)."""

    def _make_page(self):
        page = types.SimpleNamespace()
        page.main_window = mock.MagicMock()
        page.is_loading = False
        page.layout_combo = mock.MagicMock()
        page.numlock_row = mock.MagicMock()
        page.show_toast = types.MethodType(general.GeneralPage.show_toast, page)
        page._apply_layout_and_numlock = types.MethodType(general.GeneralPage._apply_layout_and_numlock, page)
        page._revert_input_display = types.MethodType(general.GeneralPage._revert_input_display, page)
        return page

    def _trigger_layout(self, page, value="de"):
        combo = mock.MagicMock()
        combo.get_active_id.return_value = value
        general.GeneralPage._on_layout_changed(page, combo)

    def _trigger_numlock(self, page, value=True):
        row = mock.MagicMock()
        row.get_active.return_value = value
        general.GeneralPage._on_numlock_changed(page, row, None)

    def test_lua_layout_change_never_calls_hyprctl_keyword(self):
        page = self._make_page()
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_write_input_lua_field") as write_mock,
            mock.patch.object(general.subprocess, "run") as run_mock,
        ):
            self._trigger_layout(page, "de")
        write_mock.assert_called_once_with("kb_layout", "de")
        run_mock.assert_not_called()
        page.main_window.add_toast.assert_called_once()

    def test_lua_numlock_change_never_calls_hyprctl_keyword(self):
        page = self._make_page()
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_write_input_lua_field") as write_mock,
            mock.patch.object(general.subprocess, "run") as run_mock,
        ):
            self._trigger_numlock(page, True)
        write_mock.assert_called_once_with("numlock_by_default", True)
        run_mock.assert_not_called()
        page.main_window.add_toast.assert_called_once()

    def test_hyprlang_layout_change_keeps_existing_live_behavior(self):
        page = self._make_page()
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch.object(general, "_write_input_conf_key") as write_mock,
            mock.patch.object(general.subprocess, "run") as run_mock,
        ):
            self._trigger_layout(page, "de")
        write_mock.assert_called_once_with("kb_layout", "de")
        run_mock.assert_called_once_with(["hyprctl", "keyword", "input:kb_layout", "de"], check=True)

    def test_write_failure_shows_error_toast_never_success_for_both_fields(self):
        for field, trigger, exc_message in (
            ("kb_layout", self._trigger_layout, "luac rejected"),
            ("numlock_by_default", self._trigger_numlock, "hyprctl broke"),
        ):
            with self.subTest(field=field):
                page = self._make_page()
                with (
                    mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
                    mock.patch.object(general, "_write_input_lua_field", side_effect=RuntimeError(exc_message)),
                    mock.patch.object(general, "read_input_conf", return_value={}),
                ):
                    trigger(page)
                self.assertEqual(page.main_window.add_toast.call_count, 1)
                toast = page.main_window.add_toast.call_args[0][0]
                self.assertIn(exc_message, toast.get_title())
                self.assertFalse(page.is_loading)

    def test_failed_write_reverts_to_neutral_when_no_safe_value_known(self):
        page = self._make_page()
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_write_input_lua_field", side_effect=RuntimeError("bad")),
            mock.patch.object(general, "read_input_conf", return_value={}),
        ):
            self._trigger_layout(page, "de")
        page.layout_combo.set_active.assert_called_once_with(-1)
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_write_input_lua_field", side_effect=RuntimeError("bad")),
            mock.patch.object(general, "read_input_conf", return_value={}),
        ):
            page2 = self._make_page()
            self._trigger_numlock(page2, True)
        page2.numlock_row.set_active.assert_called_with(False)

    def test_failed_write_reverts_to_previous_safe_value_when_known(self):
        page = self._make_page()
        page.layout_combo.set_active_id.return_value = True
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_write_input_lua_field", side_effect=RuntimeError("bad")),
            mock.patch.object(general, "read_input_conf", return_value={"kb_layout": "us", "numlock_by_default": "false"}),
        ):
            self._trigger_layout(page, "de")
        page.layout_combo.set_active_id.assert_called_with("us")
        page.numlock_row.set_active.assert_called_with(False)

    def test_success_does_not_trigger_revert(self):
        page = self._make_page()
        with (
            mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(general, "_write_input_lua_field"),
            mock.patch.object(general, "read_input_conf") as read_mock,
        ):
            self._trigger_layout(page, "de")
        read_mock.assert_not_called()  # revert path never entered
        page.main_window.add_toast.assert_called_once()

    def test_revert_suppresses_recursive_writes_via_is_loading(self):
        page = self._make_page()
        observed_layout = []
        observed_numlock = []
        page.layout_combo.set_active.side_effect = lambda v: observed_layout.append(page.is_loading)
        page.numlock_row.set_active.side_effect = lambda v: observed_numlock.append(page.is_loading)
        with mock.patch.object(general, "read_input_conf", return_value={}):
            general.GeneralPage._revert_input_display(page)
        self.assertTrue(observed_layout and all(observed_layout))
        self.assertTrue(observed_numlock and all(observed_numlock))
        self.assertFalse(page.is_loading)

    def test_revert_read_failure_falls_back_to_neutral_without_raising(self):
        page = self._make_page()
        with mock.patch.object(general, "read_input_conf", side_effect=RuntimeError("also broken")):
            general.GeneralPage._revert_input_display(page)  # must not raise
        page.layout_combo.set_active.assert_called_once_with(-1)
        self.assertFalse(page.is_loading)

    def test_corrupted_managed_block_end_to_end_via_real_write_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_path = Path(tmp) / "input.lua"
            lua_path.write_text(
                "-- BEGIN Caelestia Settings managed block: input\n"
                "-- BEGIN Caelestia Settings managed block: input\n"
                "-- END Caelestia Settings managed block: input\n"
            )
            page = self._make_page()
            with (
                mock.patch.dict(hp.LUA_PATHS, {"input": lua_path}),
                mock.patch.object(general, "load_provider", return_value=hp.Provider.LUA),
                mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA),
                mock.patch.object(general, "read_input_conf", return_value={}),
            ):
                self._trigger_layout(page, "de")
            page.main_window.add_toast.assert_called_once()
            self.assertFalse(page.is_loading)
            page.layout_combo.set_active.assert_called_once_with(-1)


# ── _load_all: language/timezone regression + exception safety ─────────────

class LoadAllRegressionAndSafetyTest(unittest.TestCase):
    def _make_page(self):
        page = types.SimpleNamespace(
            layout_combo=mock.MagicMock(),
            numlock_row=mock.MagicMock(),
            lang_combo=mock.MagicMock(),
            time_combo=mock.MagicMock(),
            is_loading=False,
        )
        page.show_toast = types.MethodType(general.GeneralPage.show_toast, page)
        page.main_window = mock.MagicMock()
        page._apply_layout_and_numlock = types.MethodType(general.GeneralPage._apply_layout_and_numlock, page)
        page._set_neutral_state = types.MethodType(general.GeneralPage._set_neutral_state, page)
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

    def test_unknown_fields_show_neutral_not_a_guessed_default(self):
        page = self._make_page()
        page.layout_combo.set_active_id.return_value = False
        with (
            mock.patch.object(general, "read_input_conf", return_value={}),
            mock.patch.object(general.subprocess, "run", side_effect=Exception("no localectl")),
        ):
            general.GeneralPage._load_all(page, hp.Provider.LUA)
        page.layout_combo.set_active.assert_called_once_with(-1)
        page.numlock_row.set_active.assert_called_once_with(False)
        page.layout_combo.set_active_id.assert_not_called()
        self.assertFalse(page.is_loading)

    def test_read_input_conf_raising_shows_neutral_state_and_toast_not_exception(self):
        page = self._make_page()
        with (
            mock.patch.object(general, "read_input_conf", side_effect=hp.ManagedBlockError("corrupt")),
            mock.patch.object(general.subprocess, "run", side_effect=Exception("no localectl")),
        ):
            general.GeneralPage._load_all(page, hp.Provider.LUA)  # must not raise
        page.layout_combo.set_active.assert_called_once_with(-1)
        page.main_window.add_toast.assert_called_once()
        self.assertFalse(page.is_loading)

    def test_unexpected_exception_in_load_all_never_escapes(self):
        page = self._make_page()
        with mock.patch.object(general, "read_input_conf", side_effect=RuntimeError("boom")):
            page._apply_layout_and_numlock = mock.MagicMock(side_effect=RuntimeError("boom"))
            general.GeneralPage._load_all(page, hp.Provider.LUA)  # must not raise
        self.assertFalse(page.is_loading)

    def test_load_if_available_never_raises_even_if_load_all_does(self):
        page = self._make_page()
        page._set_neutral_state = types.MethodType(general.GeneralPage._set_neutral_state, page)
        with mock.patch.object(general.GeneralPage, "_load_all", side_effect=RuntimeError("boom")):
            loaded = general.GeneralPage.load_if_available(page, hp.Provider.LUA)  # must not raise
        self.assertFalse(loaded)
        self.assertFalse(page.is_loading)
        page.main_window.add_toast.assert_called_once()


if __name__ == "__main__":
    unittest.main()
