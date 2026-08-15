import json
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
from src.pages import monitor


def _model(name: str, *, disabled: bool = False):
    return SimpleNamespace(
        name=name,
        disabled=disabled,
        resolution="1920x1080",
        hz="60.000",
        x=0,
        y=0,
        scale=1.0,
        transform="0",
        bitdepth="",
        primary=False,
        bar_persistent=False,
    )


def _live(*entries):
    return [{"name": name, "disabled": disabled} for name, disabled in entries]


class LiveMonitorQueryTest(unittest.TestCase):
    def _result(self, payload):
        return SimpleNamespace(stdout=payload, returncode=0, stderr="")

    def test_uses_structured_all_monitor_query_and_disabled_field(self):
        result = self._result(json.dumps(_live(("DP-1", False), ("DP-2", True))))
        with mock.patch.object(monitor.subprocess, "run", return_value=result) as run_mock:
            active, known = monitor._live_monitor_name_sets()
        self.assertEqual(active, {"DP-1"})
        self.assertEqual(known, {"DP-1", "DP-2"})
        run_mock.assert_called_once_with(
            ["hyprctl", "-j", "monitors", "all"],
            capture_output=True,
            text=True,
            check=True,
            timeout=monitor.MONITOR_QUERY_TIMEOUT_SECONDS,
        )

    def test_query_failures_and_timeout_fail_closed(self):
        failures = (
            OSError("missing"),
            monitor.subprocess.CalledProcessError(1, ["hyprctl"]),
            monitor.subprocess.TimeoutExpired(["hyprctl"], 3),
        )
        for error in failures:
            with self.subTest(error=type(error).__name__), mock.patch.object(
                monitor.subprocess, "run", side_effect=error
            ), self.assertRaises(monitor.MonitorDisableSafetyError):
                monitor._query_hyprctl_monitors_all()

    def test_invalid_json_and_semantically_invalid_shapes_fail_closed(self):
        payloads = (
            "not-json",
            json.dumps({"name": "DP-1", "disabled": False}),
            json.dumps(["DP-1"]),
            json.dumps([{"name": "", "disabled": False}]),
            json.dumps([{"name": "DP-1"}]),
            json.dumps([{"name": "DP-1", "disabled": 0}]),
            json.dumps([{"name": "DP-1", "disabled": False}, {"name": "DP-1", "disabled": True}]),
        )
        for payload in payloads:
            with self.subTest(payload=payload), mock.patch.object(
                monitor.subprocess, "run", return_value=self._result(payload)
            ), self.assertRaises(monitor.MonitorDisableSafetyError):
                monitor._query_hyprctl_monitors_all()


class LastActiveGuardTest(unittest.TestCase):
    def _guard(self, provider, requested, live):
        with (
            mock.patch.object(hp, "load_provider", return_value=provider),
            mock.patch.object(monitor, "_query_hyprctl_monitors_all", return_value=live),
        ):
            monitor._ensure_safe_monitor_disable(requested)

    def test_missing_provider_blocks_before_live_query(self):
        with (
            mock.patch.object(hp, "load_provider", return_value=None),
            mock.patch.object(monitor, "_query_hyprctl_monitors_all") as query,
            self.assertRaises(hp.ProviderCapabilityError),
        ):
            monitor._ensure_safe_monitor_disable([_model("DP-1", disabled=True)])
        query.assert_not_called()

    def test_last_active_monitor_is_blocked_for_both_providers(self):
        for provider in (hp.Provider.HYPRLANG, hp.Provider.LUA):
            with self.subTest(provider=provider), self.assertRaises(
                monitor.MonitorDisableSafetyError
            ) as raised:
                self._guard(
                    provider,
                    [_model("DP-1", disabled=True)],
                    _live(("DP-1", False), ("DP-2", True)),
                )
            self.assertEqual(str(raised.exception), monitor.t("The last active monitor cannot be disabled."))

    def test_two_active_monitors_allow_disabling_one_for_both_providers(self):
        for provider in (hp.Provider.HYPRLANG, hp.Provider.LUA):
            with self.subTest(provider=provider):
                self._guard(
                    provider,
                    [_model("DP-1", disabled=True), _model("DP-2")],
                    _live(("DP-1", False), ("DP-2", False), ("DP-3", True)),
                )

    def test_disabling_every_active_monitor_is_blocked(self):
        with self.assertRaises(monitor.MonitorDisableSafetyError):
            self._guard(
                hp.Provider.LUA,
                [_model("DP-1", disabled=True), _model("DP-2", disabled=True)],
                _live(("DP-1", False), ("DP-2", False)),
            )

    def test_known_already_disabled_monitor_is_a_safe_noop(self):
        self._guard(
            hp.Provider.HYPRLANG,
            [_model("DP-2", disabled=True)],
            _live(("DP-1", False), ("DP-2", True)),
        )

    def test_no_active_or_unknown_target_fails_closed(self):
        with self.assertRaises(monitor.MonitorDisableSafetyError):
            self._guard(hp.Provider.LUA, [_model("DP-1", disabled=True)], [])


class WriterDefenseInDepthTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = Path(self._tmpdir.name)

    def test_blocked_writers_create_no_file_backup_temp_or_reload(self):
        cases = (
            (
                hp.Provider.LUA,
                mock.patch.dict(hp.LUA_PATHS, {"monitors": self.root / "monitors.lua"}),
                lambda models: monitor._save_monitors_lua_and_reload(models),
                "write_managed_lua_block_and_reload",
            ),
            (
                hp.Provider.HYPRLANG,
                mock.patch("src.config.HYPR_MONITORS_CONF", self.root / "monitors.conf"),
                lambda models: monitor._save_monitors_conf(models),
                "write_managed_legacy_block_and_reload",
            ),
        )
        for provider, path_patch, writer, managed_writer_name in cases:
            with (
                self.subTest(provider=provider),
                path_patch,
                mock.patch.object(hp, "load_provider", return_value=provider),
                mock.patch.object(
                    monitor, "_query_hyprctl_monitors_all", return_value=_live(("DP-1", False))
                ),
                mock.patch.object(monitor, managed_writer_name) as managed_writer,
                self.assertRaises(monitor.MonitorDisableSafetyError),
            ):
                writer([_model("DP-1", disabled=True)])
            managed_writer.assert_not_called()
            self.assertEqual(list(self.root.iterdir()), [])

    def test_direct_nontransactional_lua_writer_is_guarded(self):
        with (
            mock.patch.dict(hp.LUA_PATHS, {"monitors": self.root / "monitors.lua"}),
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(
                monitor, "_query_hyprctl_monitors_all", return_value=_live(("DP-1", False))
            ),
            mock.patch.object(monitor, "write_managed_lua_block") as writer,
            self.assertRaises(monitor.MonitorDisableSafetyError),
        ):
            monitor._save_monitors_lua([_model("DP-1", disabled=True)])
        writer.assert_not_called()

    def test_two_active_outputs_recheck_inside_lock_and_verify_after_reload(self):
        before = _live(("DP-1", False), ("DP-2", False), ("DP-3", True))
        after = _live(("DP-1", True), ("DP-2", False), ("DP-3", True))
        cases = (
            (
                hp.Provider.LUA,
                mock.patch.dict(hp.LUA_PATHS, {"monitors": self.root / "monitors.lua"}),
                lambda models: monitor._save_monitors_lua_and_reload(models),
                "write_managed_lua_block_and_reload",
            ),
            (
                hp.Provider.HYPRLANG,
                mock.patch("src.config.HYPR_MONITORS_CONF", self.root / "monitors.conf"),
                lambda models: monitor._save_monitors_conf(models),
                "write_managed_legacy_block_and_reload",
            ),
        )
        for provider, path_patch, writer, managed_writer_name in cases:
            managed_writer = mock.MagicMock()
            with (
                self.subTest(provider=provider),
                path_patch,
                mock.patch.object(hp, "load_provider", return_value=provider),
                mock.patch.object(
                    monitor, "_query_hyprctl_monitors_all", side_effect=(before, before, after)
                ) as query,
                mock.patch.object(monitor, managed_writer_name, managed_writer),
            ):
                models = [_model("DP-1", disabled=True), _model("DP-2")]
                writer(models)
                kwargs = managed_writer.call_args.kwargs
                kwargs["pre_write_check"]("current bytes")
                kwargs["verify"]()
            self.assertEqual(query.call_count, 3)

    def test_state_change_before_in_lock_check_aborts_writer(self):
        before = _live(("DP-1", False), ("DP-2", False))
        stale = _live(("DP-1", False), ("DP-2", True))

        def exercise_pre_write(_path, _block, _lines, **kwargs):
            kwargs["pre_write_check"]("current bytes")

        with (
            mock.patch.dict(hp.LUA_PATHS, {"monitors": self.root / "monitors.lua"}),
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(
                monitor, "_query_hyprctl_monitors_all", side_effect=(before, stale)
            ),
            mock.patch.object(
                monitor, "write_managed_lua_block_and_reload", side_effect=exercise_pre_write
            ),
            self.assertRaises(monitor.MonitorDisableSafetyError),
        ):
            monitor._save_monitors_lua_and_reload(
                [_model("DP-1", disabled=True), _model("DP-2")]
            )
        self.assertEqual(list(self.root.iterdir()), [])

    def test_provider_change_before_in_lock_check_aborts_writer(self):
        before = _live(("DP-1", False), ("DP-2", False))

        def exercise_pre_write(_path, _block, _lines, **kwargs):
            kwargs["pre_write_check"]("current bytes")

        with (
            mock.patch.dict(hp.LUA_PATHS, {"monitors": self.root / "monitors.lua"}),
            mock.patch.object(
                hp,
                "load_provider",
                side_effect=(hp.Provider.LUA, hp.Provider.LUA, hp.Provider.HYPRLANG),
            ),
            mock.patch.object(monitor, "_query_hyprctl_monitors_all", return_value=before),
            mock.patch.object(
                monitor, "write_managed_lua_block_and_reload", side_effect=exercise_pre_write
            ),
            self.assertRaises(hp.ProviderCapabilityError),
        ):
            monitor._save_monitors_lua_and_reload(
                [_model("DP-1", disabled=True), _model("DP-2")]
            )
        self.assertEqual(list(self.root.iterdir()), [])

    def test_successful_two_monitor_write_preserves_manual_bytes_for_both_providers(self):
        before = _live(("DP-1", False), ("DP-2", False))
        after = _live(("DP-1", True), ("DP-2", False))
        cases = (
            (
                hp.Provider.LUA,
                self.root / "monitors.lua",
                b"-- manual prefix\nlocal manual = true\n",
                mock.patch.dict(hp.LUA_PATHS, {"monitors": self.root / "monitors.lua"}),
                lambda models: monitor._save_monitors_lua_and_reload(models),
            ),
            (
                hp.Provider.HYPRLANG,
                self.root / "monitors.conf",
                b"# manual prefix\n$manual = true\n",
                mock.patch("src.config.HYPR_MONITORS_CONF", self.root / "monitors.conf"),
                lambda models: monitor._save_monitors_conf(models),
            ),
        )
        for provider, path, original, path_patch, writer in cases:
            path.write_bytes(original)
            with (
                self.subTest(provider=provider),
                path_patch,
                mock.patch.object(hp, "load_provider", return_value=provider),
                mock.patch.object(
                    monitor, "_query_hyprctl_monitors_all", side_effect=(before, before, after)
                ),
                mock.patch.object(hp, "reload_hyprland"),
            ):
                writer([_model("DP-1", disabled=True), _model("DP-2")])
            self.assertTrue(path.read_bytes().startswith(original))
            self.assertEqual(path.read_bytes().count(original), 1)

    def test_live_keyword_helper_rejects_last_monitor_before_keyword(self):
        query_result = SimpleNamespace(stdout=json.dumps(_live(("DP-1", False))), returncode=0, stderr="")
        with (
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch.object(monitor.subprocess, "run", return_value=query_result) as run_mock,
            self.assertRaises(monitor.MonitorDisableSafetyError),
        ):
            monitor._apply_to_hyprland([_model("DP-1", disabled=True)])
        self.assertEqual(run_mock.call_count, 1)
        self.assertEqual(run_mock.call_args.args[0], ["hyprctl", "-j", "monitors", "all"])

    def test_live_keyword_helper_allows_one_of_two_and_verifies_it_inactive(self):
        before = _live(("DP-1", False), ("DP-2", False))
        after = _live(("DP-1", True), ("DP-2", False))
        query_results = iter((before, after))

        def run(command, **_kwargs):
            if command == ["hyprctl", "-j", "monitors", "all"]:
                return SimpleNamespace(stdout=json.dumps(next(query_results)), returncode=0, stderr="")
            return SimpleNamespace(stdout="", returncode=0, stderr="")

        with (
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.HYPRLANG),
            mock.patch.object(monitor.subprocess, "run", side_effect=run) as run_mock,
        ):
            monitor._apply_to_hyprland(
                [_model("DP-1", disabled=True), _model("DP-2")]
            )
        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(commands.count(["hyprctl", "-j", "monitors", "all"]), 2)
        self.assertEqual(sum(command[:3] == ["hyprctl", "keyword", "monitor"] for command in commands), 2)


class MonitorDisableUiTest(unittest.TestCase):
    def _panel(self):
        panel = SimpleNamespace(
            _loading=False,
            _monitor=_model("DP-1"),
            _on_disable_error_cb=mock.MagicMock(),
        )
        return panel

    def test_ui_reverts_without_recursive_write_and_shows_error(self):
        panel = self._panel()
        row = mock.MagicMock()
        row.get_active.return_value = False
        row.set_active.side_effect = lambda _active: self.assertTrue(panel._loading)
        with mock.patch.object(
            monitor,
            "_ensure_safe_monitor_disable_names",
            side_effect=monitor.MonitorDisableSafetyError("blocked"),
        ):
            monitor.MonitorSettingsPanel._on_enabled_changed(panel, row, None)
        self.assertFalse(panel._monitor.disabled)
        row.set_active.assert_called_once_with(True)
        row.set_sensitive.assert_called_once_with(False)
        panel._on_disable_error_cb.assert_called_once_with("blocked")
        self.assertFalse(panel._loading)

    def test_stale_ui_hint_cannot_bypass_execution_guard(self):
        page = SimpleNamespace(_monitors=[_model("DP-1"), _model("DP-2")])
        self.assertTrue(monitor.MonitorPage._can_disable_monitor_hint(page, page._monitors[0]))

        panel = self._panel()
        row = mock.MagicMock()
        row.get_active.return_value = False
        with (
            mock.patch.object(hp, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(
                monitor, "_query_hyprctl_monitors_all", return_value=_live(("DP-1", False))
            ),
        ):
            monitor.MonitorSettingsPanel._on_enabled_changed(panel, row, None)
        self.assertFalse(panel._monitor.disabled)
        panel._on_disable_error_cb.assert_called_once()

    def test_ui_hint_disables_only_the_single_active_monitor_switch(self):
        only = _model("DP-1")
        inactive = _model("DP-2", disabled=True)
        page = SimpleNamespace(_monitors=[only, inactive])
        self.assertFalse(monitor.MonitorPage._can_disable_monitor_hint(page, only))
        self.assertTrue(monitor.MonitorPage._can_disable_monitor_hint(page, inactive))
        page._monitors.append(_model("DP-3"))
        self.assertTrue(monitor.MonitorPage._can_disable_monitor_hint(page, only))

    def test_apply_guard_error_has_no_success_or_followup_side_effects(self):
        page = monitor.MonitorPage.__new__(monitor.MonitorPage)
        page._monitors = [_model("DP-1", disabled=True)]
        page.main_window = mock.MagicMock()
        error = monitor.MonitorDisableSafetyError("last monitor")
        with (
            mock.patch.object(monitor, "load_provider", return_value=hp.Provider.LUA),
            mock.patch.object(monitor, "_save_monitors_lua_and_reload", side_effect=error),
            mock.patch.object(monitor, "_set_primary_monitor") as primary,
            mock.patch.object(monitor, "_set_bar_persistent") as bar,
            mock.patch.object(monitor.GLib, "timeout_add") as timeout,
        ):
            monitor.MonitorPage._on_apply(page, mock.MagicMock())
        primary.assert_not_called()
        bar.assert_not_called()
        timeout.assert_not_called()
        page.main_window.add_toast.assert_called_once()
        self.assertEqual(page.main_window.add_toast.call_args.args[0].get_title(), "last monitor")


class VerificationRollbackTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = Path(self._tmpdir.name)

    def _reloads(self):
        return [None, None]

    def test_lua_verification_failure_rolls_back_and_reloads(self):
        path = self.root / "monitors.lua"
        original = b"-- manual\n"
        path.write_bytes(original)
        reloads = self._reloads()
        ok = SimpleNamespace(returncode=0, stderr="")
        with (
            mock.patch.object(hp.shutil, "which", return_value="/usr/bin/luac"),
            mock.patch.object(hp.subprocess, "run", return_value=ok),
            mock.patch.object(hp, "reload_hyprland", side_effect=lambda: reloads.pop(0)) as reload_mock,
            self.assertRaisesRegex(RuntimeError, "rolled back and reloaded"),
        ):
            hp.write_managed_lua_block_and_reload(
                path, "monitors", ["hl.monitor({})"], verify=lambda: (_ for _ in ()).throw(ValueError("stale"))
            )
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(reload_mock.call_count, 2)

    def test_legacy_verification_failure_rolls_back_and_reloads(self):
        path = self.root / "monitors.conf"
        original = b"# manual\n"
        path.write_bytes(original)
        reloads = self._reloads()
        with (
            mock.patch.object(hp, "reload_hyprland", side_effect=lambda: reloads.pop(0)) as reload_mock,
            self.assertRaisesRegex(RuntimeError, "rolled back and reloaded"),
        ):
            hp.write_managed_legacy_block_and_reload(
                path, "monitors", ["monitor = DP-1,disable"], verify=lambda: (_ for _ in ()).throw(ValueError("stale"))
            )
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(reload_mock.call_count, 2)

    def test_rollback_reload_failure_is_reported_without_success(self):
        path = self.root / "monitors.conf"
        original = b"# manual\n"
        path.write_bytes(original)
        reloads = [None, RuntimeError("rollback reload failed")]
        with (
            mock.patch.object(hp, "reload_hyprland", side_effect=lambda: (_raise(reloads.pop(0)))),
            self.assertRaisesRegex(RuntimeError, "rollback reload also failed"),
        ):
            hp.write_managed_legacy_block_and_reload(
                path, "monitors", ["monitor = DP-1,disable"], verify=lambda: (_ for _ in ()).throw(ValueError("stale"))
            )
        self.assertEqual(path.read_bytes(), original)


def _raise(error):
    if error is not None:
        raise error


if __name__ == "__main__":
    unittest.main()
