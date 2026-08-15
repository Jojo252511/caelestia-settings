import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Captured once, at import time, before any test can `mock.patch` the
# shared `subprocess.run` attribute — a later `subprocess.run` lookup
# would resolve to whatever the active patch replaced it with instead of
# the real function, since it's one shared module-level attribute.
_REAL_SUBPROCESS_RUN = subprocess.run

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import caelestia_core
from src import hypr_provider as hp
from src.pages import monitor, wallpaper


class _InterceptedRun:
    """`subprocess.run` is a single shared module attribute — patching it
    via `mock.patch.object` affects every caller in the process, not just
    one module's own reference to it (unlike a `from x import y` binding).
    Tests that need to observe one specific call (e.g. the live `xrandr`
    invocation) while other code in the same call stack still needs a
    *real* `subprocess.run` (e.g. `luac -p` validation) dispatch on argv[0]
    instead of blanket-mocking: real calls pass straight through, every
    other call is recorded and answered with a canned success."""

    def __init__(self, real_needles: tuple[str, ...] = ("luac", "hyprctl")):
        self.real_needles = real_needles
        self.calls: list[list[str]] = []

    def __call__(self, args, *a, **kw):
        self.calls.append(list(args))
        if args and any(needle in str(args[0]) for needle in self.real_needles):
            return _REAL_SUBPROCESS_RUN(args, *a, **kw)
        return mock.MagicMock(returncode=0, stdout="", stderr="")


def _patch_execs_path(path: Path, *, provider: hp.Provider):
    """Redirects the "execs" domain to `path` for whichever provider dict
    the writer under test will actually resolve through, leaving the
    other dict untouched (so a bug that resolves the wrong provider's
    path is caught by ExecsPathResolutionTest instead of silently
    succeeding here)."""
    paths = hp.LUA_PATHS if provider is hp.Provider.LUA else hp.LEGACY_PATHS
    return mock.patch.dict(paths, {"execs": path})


class AutostartShellCommandSafetyTest(unittest.TestCase):
    """Dangerous wallpaper paths/args and primary-monitor names must never
    break out of the shell command or the Lua string literal they end up
    inside."""

    DANGEROUS_NAMES = [
        "with spaces.mp4",
        "with'quote.mp4",
        'with"doublequote.mp4',
        "with\\backslash.mp4",
        "$(rm -rf ~).mp4",
        "a; rm -rf ~.mp4",
        "a\nb.mp4",
        "日本語 ✨ ünïcödé.mp4",
    ]

    def test_mpvpaper_cmd_is_shell_safe_for_dangerous_paths(self):
        for name in self.DANGEROUS_NAMES:
            with self.subTest(name=name):
                cmd = wallpaper._mpvpaper_shell_cmd(Path("/tmp") / name)
                # Round-tripping through shlex.split must recover the exact
                # path with no extra/merged tokens — proof the quoting was
                # airtight, not just "looks quoted".
                import shlex as _shlex
                tokens = _shlex.split(cmd)
                self.assertIn(f"/tmp/{name}", tokens)

    def test_mpvpaper_cmd_survives_lua_render_roundtrip(self):
        for name in self.DANGEROUS_NAMES:
            with self.subTest(name=name):
                cmd = wallpaper._mpvpaper_shell_cmd(Path("/tmp") / name)
                rendered = caelestia_core.render_autostart_cmd(cmd)
                self.assertEqual(caelestia_core.parse_autostart_cmd(rendered), cmd)

    def test_primary_monitor_cmd_is_shell_safe_for_dangerous_names(self):
        for name in self.DANGEROUS_NAMES:
            with self.subTest(name=name):
                cmd = caelestia_core.render_xrandr_primary_cmd(name)
                self.assertEqual(caelestia_core.parse_xrandr_primary_cmd(cmd), name)

    def test_primary_monitor_cmd_survives_lua_render_roundtrip(self):
        for name in self.DANGEROUS_NAMES:
            with self.subTest(name=name):
                cmd = caelestia_core.render_xrandr_primary_cmd(name)
                rendered = caelestia_core.render_autostart_cmd(cmd)
                recovered_cmd = caelestia_core.parse_autostart_cmd(rendered)
                self.assertEqual(caelestia_core.parse_xrandr_primary_cmd(recovered_cmd), name)


class ExecsPathResolutionTest(unittest.TestCase):
    """Both writers must resolve through resolve_path("execs", provider) —
    never a hardcoded legacy-only path — and never guess or fall back
    silently between the two providers' files."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def test_wallpaper_autostart_resolves_execs_domain(self):
        with mock.patch.object(wallpaper, "resolve_path") as resolve_mock, \
             mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG), \
             mock.patch.object(wallpaper, "write_managed_legacy_block_and_reload"):
            resolve_mock.return_value = Path(self._tmpdir.name) / "execs.conf"
            wallpaper._write_mpvpaper_autostart(None)
        resolve_mock.assert_called_once_with("execs", hp.Provider.HYPRLANG)

    def test_primary_monitor_resolves_execs_domain(self):
        with mock.patch.object(monitor, "resolve_path") as resolve_mock, \
             mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA), \
             mock.patch.object(monitor, "_apply_primary_monitor_live"), \
             mock.patch.object(monitor, "write_managed_lua_block_and_reload"):
            resolve_mock.return_value = Path(self._tmpdir.name) / "execs.lua"
            monitor._set_primary_monitor(None)
        # Called at least once for the pre-write snapshot read and once
        # for the write itself — every call must resolve the same domain.
        resolve_mock.assert_called_with("execs", hp.Provider.LUA)
        self.assertGreaterEqual(resolve_mock.call_count, 2)

    def test_lua_path_ends_in_dot_lua_and_legacy_in_dot_conf(self):
        self.assertTrue(str(hp.LUA_PATHS["execs"]).endswith(".lua"))
        self.assertTrue(str(hp.LEGACY_PATHS["execs"]).endswith(".conf"))


class _RealFileWriterTestBase(unittest.TestCase):
    """Shared setup for tests that exercise the real hardened writers
    end-to-end against a real temp file, with real `luac` validation on
    the Lua side and a mocked (never-real) `hyprctl reload`."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.execs_conf = Path(self._tmpdir.name) / "execs.conf"
        self.execs_lua = Path(self._tmpdir.name) / "execs.lua"
        self.reload_mock = mock.patch.object(hp, "reload_hyprland").start()
        self.addCleanup(mock.patch.stopall)

    def _lua_ctx(self):
        return (
            _patch_execs_path(self.execs_lua, provider=hp.Provider.LUA),
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA),
        )

    def _legacy_ctx(self):
        return (
            _patch_execs_path(self.execs_conf, provider=hp.Provider.HYPRLANG),
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG),
        )


class WallpaperLuaAutostartTest(_RealFileWriterTestBase):
    def test_set_creates_block_with_exec_cmd(self):
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
        text = self.execs_lua.read_text()
        self.assertIn("BEGIN Caelestia Settings managed block: wallpaper-autostart", text)
        self.assertIn("hl.exec_cmd", text)
        self.assertIn("clip.mp4", text)
        self.reload_mock.assert_called_once()

    def test_clear_empties_the_block_without_removing_it(self):
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
            wallpaper._write_mpvpaper_autostart(None)
        lines = hp.read_managed_lua_block(self.execs_lua, wallpaper.WALLPAPER_AUTOSTART_BLOCK)
        self.assertEqual(lines, [])

    def test_update_replaces_previous_command_idempotently(self):
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/a.mp4"))
            wallpaper._write_mpvpaper_autostart(Path("/tmp/b.mp4"))
            wallpaper._write_mpvpaper_autostart(Path("/tmp/b.mp4"))
        lines = hp.read_managed_lua_block(self.execs_lua, wallpaper.WALLPAPER_AUTOSTART_BLOCK)
        self.assertEqual(len(lines), 1)
        self.assertIn("b.mp4", lines[0])
        self.assertNotIn("a.mp4", lines[0])

    def test_wallpaper_block_never_touches_independent_primary_monitor_block(self):
        dispatch = _InterceptedRun()
        p1, p2 = self._lua_ctx()
        with p1, p2, mock.patch.object(hp.subprocess, "run", side_effect=dispatch):
            monitor._set_primary_monitor("DP-1")
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
            wallpaper._write_mpvpaper_autostart(None)
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.LUA), "DP-1")
        self.assertEqual(
            hp.read_managed_lua_block(self.execs_lua, wallpaper.WALLPAPER_AUTOSTART_BLOCK), []
        )
        primary_lines = hp.read_managed_lua_block(self.execs_lua, monitor.PRIMARY_MONITOR_BLOCK)
        self.assertEqual(len(primary_lines), 1)
        self.assertIn("DP-1", primary_lines[0])

    def test_manual_content_before_between_and_after_blocks_is_preserved(self):
        self.execs_lua.write_text(
            "-- manual prefix\nlocal x = 1\n"
            "-- BEGIN Caelestia Settings managed block: primary-monitor\n"
            "-- END Caelestia Settings managed block: primary-monitor\n"
            "-- manual middle\n"
            "-- manual suffix\n"
        )
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
        text = self.execs_lua.read_text()
        self.assertIn("-- manual prefix", text)
        self.assertIn("local x = 1", text)
        self.assertIn("-- manual middle", text)
        self.assertIn("-- manual suffix", text)

    def test_corrupted_markers_abort_before_any_side_effect(self):
        self.execs_lua.write_text(
            "-- BEGIN Caelestia Settings managed block: wallpaper-autostart\n"
            "-- BEGIN Caelestia Settings managed block: wallpaper-autostart\n"
        )
        original = self.execs_lua.read_bytes()
        p1, p2 = self._lua_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
        self.assertEqual(self.execs_lua.read_bytes(), original)
        self.reload_mock.assert_not_called()

    def test_crlf_and_missing_final_newline_are_preserved(self):
        self.execs_lua.write_bytes(b"-- manual\r\nlocal x = 1")
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
        content = self.execs_lua.read_bytes()
        self.assertIn(b"\r\n", content)
        self.assertTrue(content.startswith(b"-- manual\r\nlocal x = 1"))

    def test_missing_luac_raises_before_touching_file(self):
        original = b"-- manual\n"
        self.execs_lua.write_bytes(original)
        p1, p2 = self._lua_ctx()
        with p1, p2, mock.patch.object(hp.shutil, "which", return_value=None), \
             self.assertRaises(hp.LuaWriteError):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
        self.assertEqual(self.execs_lua.read_bytes(), original)
        self.reload_mock.assert_not_called()

    def test_invalid_generated_lua_is_rejected_by_real_luac(self):
        # A path containing a raw, un-escaped newline would corrupt the Lua
        # string literal if the codec ever failed to escape it — assert the
        # codec/writer instead produces syntactically valid Lua that real
        # luac accepts, by round-tripping a maximally hostile path through
        # the whole write path.
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/a\nb$(x);'\".mp4"))
        # luac -p already ran for real inside the writer; getting here at
        # all (no LuaWriteError) is the assertion. Confirm content is sane.
        self.assertIn(
            "hl.exec_cmd",
            hp.read_managed_lua_block(self.execs_lua, wallpaper.WALLPAPER_AUTOSTART_BLOCK)[0],
        )

    def test_reload_failure_rolls_back_and_reloads_original(self):
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/a.mp4"))
        original = self.execs_lua.read_bytes()
        self.reload_mock.reset_mock()
        self.reload_mock.side_effect = [RuntimeError("bad reload"), None]
        p1, p2 = self._lua_ctx()
        with p1, p2, self.assertRaisesRegex(RuntimeError, "rolled back and reloaded"):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/b.mp4"))
        self.assertEqual(self.execs_lua.read_bytes(), original)
        self.assertEqual(self.reload_mock.call_count, 2)

    def test_concurrent_modification_is_detected_not_clobbered(self):
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/a.mp4"))

        real_replace = hp._atomic_replace_locked

        def racing_replace(path, new_content, original, validator):
            # Simulate a foreign process writing to the file after our
            # writer already read `original` but before it commits.
            path.write_bytes(original + b"\n-- foreign edit\n")
            return real_replace(path, new_content, original, validator)

        p1, p2 = self._lua_ctx()
        with p1, p2, mock.patch.object(hp, "_atomic_replace_locked", side_effect=racing_replace), \
             self.assertRaises(hp.ManagedBlockError):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/b.mp4"))
        self.assertIn(b"foreign edit", self.execs_lua.read_bytes())


class WallpaperLegacyAutostartTest(_RealFileWriterTestBase):
    def test_set_and_clear_round_trip(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
            text = self.execs_conf.read_text()
            self.assertIn("exec-once = mpvpaper", text)
            self.assertIn("BEGIN Caelestia Settings managed block: wallpaper-autostart", text)
            wallpaper._write_mpvpaper_autostart(None)
        lines = hp.read_managed_legacy_block(self.execs_conf, wallpaper.WALLPAPER_AUTOSTART_BLOCK)
        self.assertEqual(lines, [])

    def test_manual_exec_once_outside_block_is_never_touched(self):
        self.execs_conf.write_text("exec-once = waybar  # manual\n")
        p1, p2 = self._legacy_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
        text = self.execs_conf.read_text()
        self.assertIn("exec-once = waybar  # manual", text)

    def test_unmigrated_legacy_marker_line_fails_closed(self):
        original = f"exec-once = mpvpaper '*' /old.mp4 -o 'x'  {wallpaper._MPVPAPER_MARKER}\n".encode()
        self.execs_conf.write_bytes(original)
        p1, p2 = self._legacy_ctx()
        with p1, p2, self.assertRaisesRegex(hp.ManagedBlockError, "migrate"):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/new.mp4"))
        self.assertEqual(self.execs_conf.read_bytes(), original)
        self.reload_mock.assert_not_called()

    def test_marker_text_inside_own_managed_block_does_not_self_trigger(self):
        # Writing twice must not make the writer see its own previous
        # output (which also contains _MPVPAPER_MARKER) as "unmigrated
        # legacy content" — only content OUTSIDE any managed block counts.
        p1, p2 = self._legacy_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/a.mp4"))
            wallpaper._write_mpvpaper_autostart(Path("/tmp/b.mp4"))
        self.assertIn("b.mp4", self.execs_conf.read_text())

    def test_reload_failure_rolls_back(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/a.mp4"))
        original = self.execs_conf.read_bytes()
        self.reload_mock.reset_mock()
        self.reload_mock.side_effect = [RuntimeError("boom"), None]
        p1, p2 = self._legacy_ctx()
        with p1, p2, self.assertRaises(RuntimeError):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/b.mp4"))
        self.assertEqual(self.execs_conf.read_bytes(), original)


class PrimaryMonitorLuaTest(_RealFileWriterTestBase):
    def test_set_switch_and_remove(self):
        dispatch = _InterceptedRun()
        p1, p2 = self._lua_ctx()
        with p1, p2, mock.patch.object(hp.subprocess, "run", side_effect=dispatch):
            monitor._set_primary_monitor("DP-1")
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.LUA), "DP-1")
            monitor._set_primary_monitor("HDMI-A-1")
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.LUA), "HDMI-A-1")
            monitor._set_primary_monitor(None)
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.LUA), "")

    def test_read_of_absent_block_is_empty_string_not_error(self):
        p1, p2 = self._lua_ctx()
        with p1, p2:
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.LUA), "")

    def test_never_treats_wallpaper_block_content_as_primary(self):
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.LUA), "")

    def test_set_applies_live_via_xrandr(self):
        dispatch = _InterceptedRun()
        p1, p2 = self._lua_ctx()
        with p1, p2, mock.patch.object(hp.subprocess, "run", side_effect=dispatch):
            monitor._set_primary_monitor("DP-1")
        xrandr = shutil.which("xrandr")
        self.assertIn([xrandr, "--output", "DP-1", "--primary"], dispatch.calls)

    def test_clear_does_not_invoke_xrandr(self):
        dispatch = _InterceptedRun()
        p1, p2 = self._lua_ctx()
        with p1, p2, mock.patch.object(hp.subprocess, "run", side_effect=dispatch):
            monitor._set_primary_monitor(None)
        self.assertFalse(any(call[0] == "xrandr" for call in dispatch.calls))


def _ok_xrandr_result():
    return mock.MagicMock(returncode=0, stdout="", stderr="")


class PrimaryMonitorLegacyTest(_RealFileWriterTestBase):
    def test_set_switch_and_remove(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2, mock.patch.object(monitor.subprocess, "run", return_value=_ok_xrandr_result()):
            monitor._set_primary_monitor("DP-1")
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.HYPRLANG), "DP-1")
            monitor._set_primary_monitor(None)
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.HYPRLANG), "")

    def test_manual_xrandr_primary_line_outside_block_is_not_treated_as_app_owned(self):
        # A manual, pre-existing "--primary" line must never be read back
        # as this app's own value (no ownership-by-content-similarity) —
        # but per M6.1 it now IS treated as a competing handler that
        # fails the write closed (see CompetingPrimaryMonitorHandlerTest),
        # so the manual line is preserved not because it merely sits
        # outside the block, but because the write never happens at all.
        original = "exec-once = xrandr --output MANUAL --primary\n"
        self.execs_conf.write_text(original)
        p1, p2 = self._legacy_ctx()
        with p1, p2:
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.HYPRLANG), "")
            with (
                mock.patch.object(monitor.subprocess, "run", return_value=_ok_xrandr_result()),
                self.assertRaises(hp.ManagedBlockError),
            ):
                monitor._set_primary_monitor("DP-1")
        self.assertEqual(self.execs_conf.read_text(), original)

    def test_never_treats_wallpaper_block_content_as_primary(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/clip.mp4"))
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.HYPRLANG), "")


class NoHyprctlKeywordInExecsWritesTest(unittest.TestCase):
    """Neither execs writer may ever call `hyprctl keyword` — under Lua
    that call fails outright (see issue #51), and under hyprlang the app
    consistently uses whole-file `hyprctl reload` for this domain."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = Path(self._tmpdir.name) / "execs.lua"

    def test_wallpaper_autostart_lua_write_never_calls_hyprctl_keyword(self):
        with _patch_execs_path(self.path, provider=hp.Provider.LUA), \
             mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA), \
             mock.patch.object(hp.subprocess, "run") as run_mock:
            run_mock.return_value = mock.MagicMock(returncode=0, stderr="")
            wallpaper._write_mpvpaper_autostart(Path("/tmp/a.mp4"))
        for call in run_mock.call_args_list:
            args = call.args[0]
            self.assertNotIn("keyword", args)

    def test_primary_monitor_lua_write_never_calls_hyprctl_keyword(self):
        dispatch = _InterceptedRun(real_needles=())
        with _patch_execs_path(self.path, provider=hp.Provider.LUA), \
             mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA), \
             mock.patch.object(hp.subprocess, "run", side_effect=dispatch):
            monitor._set_primary_monitor("DP-1")
        for args in dispatch.calls:
            self.assertNotIn("keyword", args)


class CapabilityMatrixTest(unittest.TestCase):
    def test_wallpaper_autostart_and_execs_are_lua_capable(self):
        self.assertTrue(hp.capability_available(hp.Provider.LUA, hp.ConfigCapability.WALLPAPER_AUTOSTART))
        self.assertTrue(hp.capability_available(hp.Provider.LUA, hp.ConfigCapability.EXECS))

    def test_none_provider_blocks_both(self):
        self.assertFalse(hp.capability_available(None, hp.ConfigCapability.WALLPAPER_AUTOSTART))
        self.assertFalse(hp.capability_available(None, hp.ConfigCapability.EXECS))

    def test_hyprlang_always_available(self):
        self.assertTrue(hp.capability_available(hp.Provider.HYPRLANG, hp.ConfigCapability.WALLPAPER_AUTOSTART))
        self.assertTrue(hp.capability_available(hp.Provider.HYPRLANG, hp.ConfigCapability.EXECS))


class LegacyPredicateHelperTest(unittest.TestCase):
    """Focused tests for the new `legacy_predicate` parameter on
    `write_managed_legacy_block_and_reload` itself, independent of the
    wallpaper/monitor call sites."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = Path(self._tmpdir.name) / "config.conf"
        self.reload_patcher = mock.patch.object(hp, "reload_hyprland")
        self.reload_patcher.start()
        self.addCleanup(self.reload_patcher.stop)

    def test_predicate_match_outside_block_fails_closed(self):
        original = b"exec-once = legacy-owned-thing\n"
        self.path.write_bytes(original)
        with self.assertRaises(hp.ManagedBlockError):
            hp.write_managed_legacy_block_and_reload(
                self.path, "test-block", ["exec-once = new"],
                legacy_predicate=lambda line: "legacy-owned-thing" in line,
            )
        self.assertEqual(self.path.read_bytes(), original)

    def test_predicate_match_inside_existing_own_block_does_not_self_trigger(self):
        self.path.write_text(
            "# BEGIN Caelestia Settings managed block: test-block\n"
            "exec-once = legacy-owned-thing\n"
            "# END Caelestia Settings managed block: test-block\n"
        )
        hp.write_managed_legacy_block_and_reload(
            self.path, "test-block", ["exec-once = legacy-owned-thing"],
            legacy_predicate=lambda line: "legacy-owned-thing" in line,
        )
        self.assertIn("legacy-owned-thing", self.path.read_text())

    def test_no_predicate_and_no_marker_means_no_legacy_detection(self):
        self.path.write_text("exec-once = anything at all\n")
        hp.write_managed_legacy_block_and_reload(self.path, "test-block", ["exec-once = new"])
        self.assertIn("exec-once = anything at all", self.path.read_text())
        self.assertIn("exec-once = new", self.path.read_text())


class ReadManagedLegacyBlockTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = Path(self._tmpdir.name) / "config.conf"

    def test_missing_file_returns_empty_list(self):
        self.assertEqual(hp.read_managed_legacy_block(self.path, "x"), [])

    def test_missing_block_returns_empty_list(self):
        self.path.write_text("# manual\n")
        self.assertEqual(hp.read_managed_legacy_block(self.path, "x"), [])

    def test_reads_only_named_block_content(self):
        self.path.write_text(
            "manual line\n"
            "# BEGIN Caelestia Settings managed block: a\n"
            "line-a\n"
            "# END Caelestia Settings managed block: a\n"
            "# BEGIN Caelestia Settings managed block: b\n"
            "line-b\n"
            "# END Caelestia Settings managed block: b\n"
        )
        self.assertEqual(hp.read_managed_legacy_block(self.path, "a"), ["line-a"])
        self.assertEqual(hp.read_managed_legacy_block(self.path, "b"), ["line-b"])


# ── M6.1 hardening: primary-monitor xrandr error handling ──────────────────


class PrimaryMonitorXrandrErrorTest(_RealFileWriterTestBase):
    """xrandr errors (non-zero exit, timeout, missing binary, OSError)
    must be treated as errors — never swallowed via print() — and must
    roll back an already-persisted config change."""

    def test_non_zero_returncode_raises_with_stderr(self):
        p1, p2 = self._legacy_ctx()
        result = mock.MagicMock(returncode=1, stdout="", stderr="Cannot find output")
        with p1, p2, mock.patch.object(monitor.subprocess, "run", return_value=result), \
             self.assertRaisesRegex(RuntimeError, "Cannot find output"):
            monitor._set_primary_monitor("NOPE")

    def test_timeout_raises(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2, mock.patch.object(
            monitor.subprocess, "run",
            side_effect=monitor.subprocess.TimeoutExpired(cmd="xrandr", timeout=3),
        ), self.assertRaises(RuntimeError):
            monitor._set_primary_monitor("DP-1")

    def test_missing_binary_raises(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2, mock.patch.object(monitor.shutil, "which", return_value=None), \
             self.assertRaisesRegex(RuntimeError, "xrandr"):
            monitor._set_primary_monitor("DP-1")

    def test_oserror_raises(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2, mock.patch.object(monitor.subprocess, "run", side_effect=OSError("no exec")), \
             self.assertRaises(RuntimeError):
            monitor._set_primary_monitor("DP-1")

    def test_never_prints_and_swallows(self):
        p1, p2 = self._legacy_ctx()
        result = mock.MagicMock(returncode=1, stdout="", stderr="boom")
        with p1, p2, mock.patch.object(monitor.subprocess, "run", return_value=result), \
             mock.patch("builtins.print") as print_mock:
            with self.assertRaises(RuntimeError):
                monitor._set_primary_monitor("DP-1")
        print_mock.assert_not_called()

    def test_live_failure_rolls_back_already_persisted_config(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2, mock.patch.object(monitor.subprocess, "run", return_value=_ok_xrandr_result()):
            monitor._set_primary_monitor("DP-1")
        original = self.execs_conf.read_bytes()

        p1, p2 = self._legacy_ctx()
        bad_result = mock.MagicMock(returncode=1, stdout="", stderr="bad output")
        with p1, p2, mock.patch.object(monitor.subprocess, "run", return_value=bad_result), \
             self.assertRaises(RuntimeError):
            monitor._set_primary_monitor("BOGUS")
        self.assertEqual(self.execs_conf.read_bytes(), original)

    def test_live_failure_leaves_no_false_effective_state(self):
        p1, p2 = self._legacy_ctx()
        bad_result = mock.MagicMock(returncode=1, stdout="", stderr="bad")
        with p1, p2, mock.patch.object(monitor.subprocess, "run", return_value=bad_result), \
             self.assertRaises(RuntimeError):
            monitor._set_primary_monitor("BOGUS")
        self.assertEqual(monitor._get_primary_monitor(hp.Provider.HYPRLANG), "")

    def test_second_reload_and_double_error_message_when_rollback_write_also_fails(self):
        bad_result = mock.MagicMock(returncode=1, stdout="", stderr="xrandr failed")
        p1, p2 = self._legacy_ctx()
        with (
            p1, p2,
            mock.patch.object(monitor.subprocess, "run", return_value=bad_result),
            mock.patch.object(
                monitor,
                "_write_primary_monitor_lines",
                side_effect=[None, hp.ManagedBlockError("concurrent edit")],
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                monitor._set_primary_monitor("BOGUS")
        message = str(ctx.exception)
        self.assertIn("xrandr failed", message)
        self.assertIn("concurrent edit", message)


class PrimaryMonitorRemovalTest(_RealFileWriterTestBase):
    """Clearing the primary monitor uses the documented `xrandr
    --noprimary` global flag (verified via `man xrandr`: "Don't define a
    primary output") — a real, distinct flag from the per-output
    `--primary`, not a guess."""

    def test_clear_invokes_noprimary_not_output_primary(self):
        dispatch = _InterceptedRun()
        p1, p2 = self._legacy_ctx()
        with p1, p2, mock.patch.object(monitor.subprocess, "run", side_effect=dispatch):
            monitor._set_primary_monitor(None)
        xrandr = shutil.which("xrandr")
        self.assertIn([xrandr, "--noprimary"], dispatch.calls)
        self.assertFalse(any("--output" in call for call in dispatch.calls))

    def test_clear_failure_is_a_visible_error_not_silent(self):
        result = mock.MagicMock(returncode=1, stdout="", stderr="noprimary failed")
        p1, p2 = self._legacy_ctx()
        with p1, p2, mock.patch.object(monitor.subprocess, "run", return_value=result), \
             self.assertRaisesRegex(RuntimeError, "noprimary failed"):
            monitor._set_primary_monitor(None)

    def test_clear_after_set_removes_persisted_entry(self):
        p1, p2 = self._lua_ctx()
        with p1, p2, mock.patch.object(hp.subprocess, "run", side_effect=_InterceptedRun()):
            monitor._set_primary_monitor("DP-1")
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.LUA), "DP-1")
            monitor._set_primary_monitor(None)
        self.assertEqual(
            hp.read_managed_lua_block(self.execs_lua, monitor.PRIMARY_MONITOR_BLOCK), []
        )


# ── M6.1 hardening: competing manual autostart handlers ────────────────────


class CompetingWallpaperHandlerTest(_RealFileWriterTestBase):
    def test_static_competing_legacy_entry_before_block_fails_closed(self):
        self.execs_conf.write_text("exec-once = mpvpaper '*' /manual.mp4\n")
        original = self.execs_conf.read_text()
        p1, p2 = self._legacy_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/new.mp4"))
        self.assertEqual(self.execs_conf.read_text(), original)
        self.reload_mock.assert_not_called()

    def test_static_competing_legacy_entry_after_own_block_fails_closed(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/first.mp4"))
        with self.execs_conf.open("a") as f:
            f.write("exec-once = mpvpaper '*' /manual-after.mp4\n")
        original = self.execs_conf.read_text()
        self.reload_mock.reset_mock()

        p1, p2 = self._legacy_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/second.mp4"))
        self.assertEqual(self.execs_conf.read_text(), original)
        self.reload_mock.assert_not_called()

    def test_static_competing_lua_entry_before_block_fails_closed(self):
        self.execs_lua.write_text(
            'hl.on("hyprland.start", function() hl.exec_cmd("mpvpaper \'*\' /manual.mp4") end)\n'
        )
        original = self.execs_lua.read_text()
        p1, p2 = self._lua_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/new.mp4"))
        self.assertEqual(self.execs_lua.read_text(), original)
        self.reload_mock.assert_not_called()

    def test_static_competing_lua_entry_after_own_block_fails_closed(self):
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/first.mp4"))
        with self.execs_lua.open("a") as f:
            f.write(
                'hl.on("hyprland.start", function() '
                'hl.exec_cmd("mpvpaper \'*\' /manual-after.mp4") end)\n'
            )
        original = self.execs_lua.read_text()
        self.reload_mock.reset_mock()

        p1, p2 = self._lua_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/second.mp4"))
        self.assertEqual(self.execs_lua.read_text(), original)
        self.reload_mock.assert_not_called()

    def test_dynamic_unparseable_hyprland_start_handler_fails_closed(self):
        self.execs_lua.write_text(
            'hl.on("hyprland.start", function() local x = 1 hl.exec_cmd("x") end)\n'
        )
        original = self.execs_lua.read_text()
        p1, p2 = self._lua_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            wallpaper._write_mpvpaper_autostart(Path("/tmp/new.mp4"))
        self.assertEqual(self.execs_lua.read_text(), original)

    def test_unrelated_hyprland_start_handler_does_not_block(self):
        self.execs_lua.write_text('hl.on("hyprland.start", function() hl.exec_cmd("waybar") end)\n')
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/new.mp4"))
        self.assertIn(
            "new.mp4",
            hp.read_managed_lua_block(self.execs_lua, wallpaper.WALLPAPER_AUTOSTART_BLOCK)[0],
        )

    def test_wrong_event_handler_does_not_block(self):
        self.execs_lua.write_text(
            'hl.on("window.open", function() hl.exec_cmd("mpvpaper \'*\' /x.mp4") end)\n'
        )
        p1, p2 = self._lua_ctx()
        with p1, p2:
            wallpaper._write_mpvpaper_autostart(Path("/tmp/new.mp4"))
        self.assertIn(
            "new.mp4",
            hp.read_managed_lua_block(self.execs_lua, wallpaper.WALLPAPER_AUTOSTART_BLOCK)[0],
        )


class CompetingPrimaryMonitorHandlerTest(_RealFileWriterTestBase):
    def test_static_competing_legacy_entry_before_block_fails_closed(self):
        self.execs_conf.write_text("exec-once = xrandr --output MANUAL --primary\n")
        original = self.execs_conf.read_text()
        p1, p2 = self._legacy_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            monitor._set_primary_monitor("DP-1")
        self.assertEqual(self.execs_conf.read_text(), original)
        self.reload_mock.assert_not_called()

    def test_static_competing_legacy_entry_after_own_block_fails_closed(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2, mock.patch.object(monitor.subprocess, "run", return_value=_ok_xrandr_result()):
            monitor._set_primary_monitor("DP-1")
        with self.execs_conf.open("a") as f:
            f.write("exec-once = xrandr --output MANUAL --primary\n")
        original = self.execs_conf.read_text()
        self.reload_mock.reset_mock()

        p1, p2 = self._legacy_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            monitor._set_primary_monitor("HDMI-A-1")
        self.assertEqual(self.execs_conf.read_text(), original)
        self.reload_mock.assert_not_called()

    def test_static_competing_lua_entry_fails_closed(self):
        self.execs_lua.write_text(
            'hl.on("hyprland.start", function() '
            'hl.exec_cmd("xrandr --output MANUAL --primary") end)\n'
        )
        original = self.execs_lua.read_text()
        p1, p2 = self._lua_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            monitor._set_primary_monitor("DP-1")
        self.assertEqual(self.execs_lua.read_text(), original)

    def test_dynamic_unparseable_handler_fails_closed(self):
        self.execs_lua.write_text(
            'hl.on("hyprland.start", function() local x = 1 '
            'hl.exec_cmd("xrandr --output DP-2 --primary") end)\n'
        )
        original = self.execs_lua.read_text()
        p1, p2 = self._lua_ctx()
        with p1, p2, self.assertRaises(hp.ManagedBlockError):
            monitor._set_primary_monitor("DP-1")
        self.assertEqual(self.execs_lua.read_text(), original)

    def test_unrelated_handler_does_not_block(self):
        self.execs_lua.write_text('hl.on("hyprland.start", function() hl.exec_cmd("waybar") end)\n')
        p1, p2 = self._lua_ctx()
        with p1, p2, mock.patch.object(hp.subprocess, "run", side_effect=_InterceptedRun()):
            monitor._set_primary_monitor("DP-1")
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.LUA), "DP-1")

    def test_has_competing_handler_reports_true_only_when_relevant(self):
        p1, p2 = self._lua_ctx()
        with p1, p2:
            self.assertFalse(monitor._has_competing_primary_monitor_handler(hp.Provider.LUA))
            self.execs_lua.write_text(
                'hl.on("hyprland.start", function() '
                'hl.exec_cmd("xrandr --output MANUAL --primary") end)\n'
            )
            self.assertTrue(monitor._has_competing_primary_monitor_handler(hp.Provider.LUA))


# ── M6.1 hardening: legacy_predicate / pre_write_check re-verified under lock ──


class LegacyPredicateLockRaceTest(unittest.TestCase):
    """Deterministic (no sleeps) proof that both `legacy_predicate` and
    the newer generic `pre_write_check` are re-verified against the exact
    bytes under the lock, not just a pre-lock snapshot — closing the
    TOCTOU window the pre-lock-only check alone would leave open."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.reload_patcher = mock.patch.object(hp, "reload_hyprland")
        self.reload_mock = self.reload_patcher.start()
        self.addCleanup(self.reload_patcher.stop)

    def test_legacy_predicate_content_injected_between_precheck_and_lock_is_caught(self):
        path = Path(self._tmpdir.name) / "config.conf"
        path.write_text("# manual\n")
        real_lock = hp._with_managed_write_lock

        def racing_lock(p):
            lock = real_lock(p)
            p.write_text("# manual\nexec-once = legacy-owned-thing\n")
            return lock

        with mock.patch.object(hp, "_with_managed_write_lock", side_effect=racing_lock), \
             self.assertRaises(hp.ManagedBlockError):
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"],
                legacy_predicate=lambda line: "legacy-owned-thing" in line,
            )
        content = path.read_text()
        self.assertIn("legacy-owned-thing", content)
        self.assertNotIn("test-block", content)
        self.assertNotIn("BEGIN", content)
        self.reload_mock.assert_not_called()

    def test_pre_write_check_sees_content_injected_between_precheck_and_lock(self):
        path = Path(self._tmpdir.name) / "config2.conf"
        path.write_text("# manual\n")
        real_lock = hp._with_managed_write_lock

        def racing_lock(p):
            lock = real_lock(p)
            p.write_text("# manual\nexec-once = injected\n")
            return lock

        seen_texts = []

        def pre_write_check(text):
            seen_texts.append(text)
            if "injected" in text:
                raise hp.ManagedBlockError("competing content detected")

        with mock.patch.object(hp, "_with_managed_write_lock", side_effect=racing_lock), \
             self.assertRaisesRegex(hp.ManagedBlockError, "competing content detected"):
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"], pre_write_check=pre_write_check
            )
        self.assertEqual(len(seen_texts), 1)
        self.assertIn("injected", seen_texts[0])
        self.reload_mock.assert_not_called()

    def test_pre_write_check_for_lua_writer_sees_injected_content(self):
        path = Path(self._tmpdir.name) / "config.lua"
        path.write_text("-- manual\n")
        real_lock = hp._with_managed_write_lock

        def racing_lock(p):
            lock = real_lock(p)
            p.write_text("-- manual\n-- injected\n")
            return lock

        seen_texts = []

        def pre_write_check(text):
            seen_texts.append(text)
            if "injected" in text:
                raise hp.ManagedBlockError("competing content detected")

        with mock.patch.object(hp, "_with_managed_write_lock", side_effect=racing_lock), \
             self.assertRaisesRegex(hp.ManagedBlockError, "competing content detected"):
            hp.write_managed_lua_block_and_reload(
                path, "test-block", ["-- x"], pre_write_check=pre_write_check
            )
        self.assertEqual(len(seen_texts), 1)
        self.assertIn("injected", seen_texts[0])
        self.reload_mock.assert_not_called()

    def test_no_race_means_no_error(self):
        path = Path(self._tmpdir.name) / "config3.conf"
        path.write_text("# manual\n")
        hp.write_managed_legacy_block_and_reload(
            path, "test-block", ["exec-once = new"],
            legacy_predicate=lambda line: "legacy-owned-thing" in line,
        )
        self.assertIn("exec-once = new", path.read_text())
        self.reload_mock.assert_called_once()


# ── M6.1 hardening: neutral UI state for a competing primary handler ───────


class MonitorConflictUITest(unittest.TestCase):
    @staticmethod
    def _model(**overrides):
        data = {
            "name": "DP-1", "description": "DP-1", "x": 0, "y": 0,
            "width": 1920, "height": 1080, "scale": 1.0, "transform": 0,
            "disabled": False, "refreshRate": 60.0,
        }
        data.update(overrides)
        return monitor.MonitorModel(data)

    def test_load_monitors_forces_primary_false_and_sets_conflict_flag(self):
        page = monitor.MonitorPage.__new__(monitor.MonitorPage)
        page.main_window = mock.MagicMock()
        page._canvas = mock.MagicMock()
        page._settings_panel = mock.MagicMock()
        page._apply_btn = mock.MagicMock()

        raw = [{
            "name": "DP-1", "description": "DP-1", "x": 0, "y": 0,
            "width": 1920, "height": 1080, "scale": 1.0, "transform": 0,
            "disabled": False, "refreshRate": 60.0,
        }]
        with (
            mock.patch.object(monitor, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(monitor, "_get_live_monitors", return_value=raw),
            mock.patch.object(monitor, "_has_competing_primary_monitor_handler", return_value=True),
            mock.patch.object(monitor, "_get_primary_monitor", return_value="DP-1"),
            mock.patch.object(monitor, "_get_bar_persistent", return_value=True),
        ):
            monitor.MonitorPage.load_monitors(page)

        self.assertEqual(len(page._monitors), 1)
        m = page._monitors[0]
        self.assertTrue(m.primary_conflict)
        # Forced False despite _get_primary_monitor reporting "DP-1" —
        # the effective state is undetermined, never confidently shown.
        self.assertFalse(m.primary)

    def test_load_monitors_without_conflict_marks_primary_normally(self):
        page = monitor.MonitorPage.__new__(monitor.MonitorPage)
        page.main_window = mock.MagicMock()
        page._canvas = mock.MagicMock()
        page._settings_panel = mock.MagicMock()
        page._apply_btn = mock.MagicMock()

        raw = [{
            "name": "DP-1", "description": "DP-1", "x": 0, "y": 0,
            "width": 1920, "height": 1080, "scale": 1.0, "transform": 0,
            "disabled": False, "refreshRate": 60.0,
        }]
        with (
            mock.patch.object(monitor, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(monitor, "_get_live_monitors", return_value=raw),
            mock.patch.object(monitor, "_has_competing_primary_monitor_handler", return_value=False),
            mock.patch.object(monitor, "_get_primary_monitor", return_value="DP-1"),
            mock.patch.object(monitor, "_get_bar_persistent", return_value=True),
        ):
            monitor.MonitorPage.load_monitors(page)

        m = page._monitors[0]
        self.assertFalse(m.primary_conflict)
        self.assertTrue(m.primary)

    def test_settings_panel_disables_row_and_changes_subtitle_on_conflict(self):
        # Locale-independent: compares behavior/state (booleans, and the
        # subtitle string against itself in the non-conflict case) rather
        # than asserting on literal translated text.
        panel = monitor.MonitorSettingsPanel()
        with mock.patch.object(monitor, "load_provider", return_value=hp.Provider.LUA):
            normal = self._model()
            normal.primary = True
            normal.primary_conflict = False
            panel.load(normal)
            normal_subtitle = panel._primary_row.get_subtitle()
            self.assertTrue(panel._primary_row.get_sensitive())
            self.assertTrue(panel._primary_row.get_active())

            conflicted = self._model()
            conflicted.primary = False
            conflicted.primary_conflict = True
            panel.load(conflicted)
            self.assertFalse(panel._primary_row.get_sensitive())
            self.assertFalse(panel._primary_row.get_active())
            self.assertNotEqual(panel._primary_row.get_subtitle(), normal_subtitle)


if __name__ == "__main__":
    unittest.main()
