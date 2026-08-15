import os
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
        import shlex as _shlex
        for name in self.DANGEROUS_NAMES:
            with self.subTest(name=name):
                cmd = monitor._xrandr_primary_cmd(name)
                tokens = _shlex.split(cmd)
                self.assertIn(name, tokens)
                self.assertEqual(monitor._extract_primary_from_cmd(cmd), name)

    def test_primary_monitor_cmd_survives_lua_render_roundtrip(self):
        for name in self.DANGEROUS_NAMES:
            with self.subTest(name=name):
                cmd = monitor._xrandr_primary_cmd(name)
                rendered = caelestia_core.render_autostart_cmd(cmd)
                recovered = caelestia_core.parse_autostart_cmd(rendered)
                self.assertEqual(monitor._extract_primary_from_cmd(recovered), name)


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
             mock.patch.object(monitor, "write_managed_lua_block_and_reload"):
            resolve_mock.return_value = Path(self._tmpdir.name) / "execs.lua"
            monitor._set_primary_monitor(None)
        resolve_mock.assert_called_once_with("execs", hp.Provider.LUA)

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
        p1, p2 = self._lua_ctx()
        with p1, p2:
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
        self.assertIn(["xrandr", "--output", "DP-1", "--primary"], dispatch.calls)

    def test_clear_does_not_invoke_xrandr(self):
        dispatch = _InterceptedRun()
        p1, p2 = self._lua_ctx()
        with p1, p2, mock.patch.object(hp.subprocess, "run", side_effect=dispatch):
            monitor._set_primary_monitor(None)
        self.assertFalse(any(call[0] == "xrandr" for call in dispatch.calls))


class PrimaryMonitorLegacyTest(_RealFileWriterTestBase):
    def test_set_switch_and_remove(self):
        p1, p2 = self._legacy_ctx()
        with p1, p2, mock.patch.object(monitor.subprocess, "run"):
            monitor._set_primary_monitor("DP-1")
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.HYPRLANG), "DP-1")
            monitor._set_primary_monitor(None)
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.HYPRLANG), "")

    def test_manual_xrandr_primary_line_outside_block_is_not_treated_as_app_owned(self):
        # A manual, pre-existing "--primary" line must never be read back
        # as this app's own value (no ownership-by-content-similarity),
        # nor be touched/removed by a write to the app's own block.
        self.execs_conf.write_text("exec-once = xrandr --output MANUAL --primary\n")
        p1, p2 = self._legacy_ctx()
        with p1, p2:
            self.assertEqual(monitor._get_primary_monitor(hp.Provider.HYPRLANG), "")
            with mock.patch.object(monitor.subprocess, "run"):
                monitor._set_primary_monitor("DP-1")
        text = self.execs_conf.read_text()
        self.assertIn("exec-once = xrandr --output MANUAL --primary", text)
        self.assertIn("DP-1", text)

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


if __name__ == "__main__":
    unittest.main()
