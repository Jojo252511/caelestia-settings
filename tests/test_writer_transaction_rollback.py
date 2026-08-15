"""M6.3 finding 2 — the rollback base for a `live_apply` failure (or a
`verify`/reload failure) must be exactly the bytes THIS write transaction
read as its starting point under its OWN lock, never a caller's pre-lock
snapshot: that snapshot can already be stale if another, fully-serialized
writer's own change landed on disk between the caller's read and this
transaction's lock acquisition. These tests exercise the shared writers
in `src/hypr_provider.py` directly (`write_managed_lua_block_and_reload`
/ `write_managed_legacy_block_and_reload`), independent of any page, so
the guarantee is proven at the layer that actually implements it.
"""

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


class _RaceHarness:
    """Wraps `_with_managed_write_lock` so a fake concurrent writer's
    change lands on disk at the exact moment our own transaction
    acquires the lock — deterministic, no sleeps, no threads. This
    reproduces "OLD -> CONCURRENT -> NEW" without needing two real
    processes: by the time our own transaction's `_with_managed_write_lock`
    call returns, the file already holds CONCURRENT, exactly as it would
    if a fully separate, already-finished writer had gotten there first
    (which is guaranteed by the same lock this harness wraps)."""

    def __init__(self, path: Path, concurrent_bytes: bytes):
        self.path = path
        self.concurrent_bytes = concurrent_bytes
        self.injected = False
        self._real_lock = hp._with_managed_write_lock

    def __call__(self, path):
        lock = self._real_lock(path)
        if not self.injected:
            self.injected = True
            self.path.write_bytes(self.concurrent_bytes)
        return lock


def _raise(exc):
    raise exc


class OldConcurrentNewRollbackTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.reload_patcher = mock.patch.object(hp, "reload_hyprland")
        self.reload_mock = self.reload_patcher.start()
        self.addCleanup(self.reload_patcher.stop)

    def test_legacy_writer_rolls_back_to_concurrent_not_stale_old(self):
        path = Path(self._tmpdir.name) / "config.conf"
        old = b"# OLD\nexec-once = old-thing\n"
        concurrent = b"# CONCURRENT\nexec-once = concurrent-thing\n"
        path.write_bytes(old)
        harness = _RaceHarness(path, concurrent)

        with mock.patch.object(hp, "_with_managed_write_lock", side_effect=harness), \
             self.assertRaises(RuntimeError):
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new-thing"],
                live_apply=lambda: _raise(RuntimeError("live apply boom")),
            )
        result = path.read_bytes()
        self.assertEqual(result, concurrent)
        self.assertNotIn(b"new-thing", result)
        self.assertNotIn(b"OLD", result)

    def test_lua_writer_rolls_back_to_concurrent_not_stale_old(self):
        path = Path(self._tmpdir.name) / "config.lua"
        old = b"-- OLD\n"
        concurrent = b"-- CONCURRENT\n"
        path.write_bytes(old)
        harness = _RaceHarness(path, concurrent)

        with mock.patch.object(hp, "_with_managed_write_lock", side_effect=harness), \
             self.assertRaises(RuntimeError):
            hp.write_managed_lua_block_and_reload(
                path, "test-block", ["-- new"],
                live_apply=lambda: _raise(RuntimeError("live apply boom")),
            )
        result = path.read_bytes()
        self.assertEqual(result, concurrent)
        self.assertNotIn(b"OLD", result)

    def test_verify_failure_also_rolls_back_to_concurrent(self):
        # The same guarantee applies to the pre-existing `verify` hook,
        # not just the new `live_apply` one — both share the same
        # rollback machinery.
        path = Path(self._tmpdir.name) / "verify.conf"
        old = b"# OLD\n"
        concurrent = b"# CONCURRENT\n"
        path.write_bytes(old)
        harness = _RaceHarness(path, concurrent)

        with mock.patch.object(hp, "_with_managed_write_lock", side_effect=harness), \
             self.assertRaises(RuntimeError):
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"],
                verify=lambda: _raise(ValueError("stale")),
            )
        self.assertEqual(path.read_bytes(), concurrent)

    def test_foreign_change_after_own_write_prevents_unsafe_rollback(self):
        # If the foreign write instead lands AFTER our own transaction's
        # commit (not before it, like the OLD/CONCURRENT/NEW scenario
        # above), the rollback must detect that its own `written` bytes
        # no longer match what's on disk and abort — never silently
        # overwrite that later foreign change either.
        path = Path(self._tmpdir.name) / "foreign_after.conf"
        path.write_text("# manual\n")
        real_atomic_replace = hp._atomic_replace_locked

        def racing_atomic_replace(path, new_content, original, validator):
            result = real_atomic_replace(path, new_content, original, validator)
            path.write_bytes(path.read_bytes() + b"# foreign edit after our own write\n")
            return result

        with mock.patch.object(hp, "_atomic_replace_locked", side_effect=racing_atomic_replace), \
             self.assertRaises(hp.ManagedBlockError) as ctx:
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"],
                live_apply=lambda: _raise(RuntimeError("live apply boom")),
            )
        self.assertIn("foreign edit after our own write", path.read_text())
        self.assertIn("live apply boom", str(ctx.exception))
        self.assertIn("concurrently", str(ctx.exception))

    def test_normal_live_apply_failure_without_concurrency_restores_exact_old(self):
        path = Path(self._tmpdir.name) / "no_race.conf"
        old = b"# OLD only\n"
        path.write_bytes(old)
        with self.assertRaises(RuntimeError):
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"],
                live_apply=lambda: _raise(RuntimeError("boom")),
            )
        self.assertEqual(path.read_bytes(), old)

    def test_second_reload_runs_on_live_apply_failure(self):
        path = Path(self._tmpdir.name) / "second_reload.conf"
        path.write_text("# manual\n")
        with self.assertRaises(RuntimeError):
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"],
                live_apply=lambda: _raise(RuntimeError("boom")),
            )
        self.assertEqual(self.reload_mock.call_count, 2)

    def test_second_reload_failure_surfaces_double_error_message(self):
        path = Path(self._tmpdir.name) / "second_reload_fails.conf"
        path.write_text("# manual\n")
        self.reload_mock.side_effect = [None, RuntimeError("rollback reload boom")]
        with self.assertRaises(RuntimeError) as ctx:
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"],
                live_apply=lambda: _raise(RuntimeError("live apply boom")),
            )
        message = str(ctx.exception)
        self.assertIn("live apply boom", message)
        self.assertIn("rollback reload boom", message)
        self.assertEqual(self.reload_mock.call_count, 2)

    def test_byte_exact_preservation_through_rollback_crlf_and_no_final_newline(self):
        path = Path(self._tmpdir.name) / "byteexact.conf"
        original = (
            b"# prefix line\r\n"
            b"# BEGIN Caelestia Settings managed block: test-block\r\n"
            b"# END Caelestia Settings managed block: test-block\r\n"
            b"# suffix, no trailing newline"
        )
        path.write_bytes(original)
        with self.assertRaises(RuntimeError):
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"],
                live_apply=lambda: _raise(RuntimeError("boom")),
            )
        self.assertEqual(path.read_bytes(), original)

    def test_lock_is_released_after_live_apply_failure(self):
        path = Path(self._tmpdir.name) / "lock_release.conf"
        path.write_text("# manual\n")
        with self.assertRaises(RuntimeError):
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"],
                live_apply=lambda: _raise(RuntimeError("boom")),
            )
        # If the lock were still held, this would block for up to
        # LOCK_TIMEOUT_SECONDS and then raise LockTimeoutError.
        lock_file = hp._with_managed_write_lock(path)
        lock_file.close()

    def test_lock_is_released_after_success(self):
        path = Path(self._tmpdir.name) / "lock_release_success.conf"
        path.write_text("# manual\n")
        hp.write_managed_legacy_block_and_reload(path, "test-block", ["exec-once = new"])
        lock_file = hp._with_managed_write_lock(path)
        lock_file.close()

    @staticmethod
    def _non_artifact_names(stem: str) -> set[str]:
        """Names a successful/rolled-back write may legitimately leave
        behind: the real file, its lock file (kept and reused, never
        deleted), and exactly one intentional `.bak_<random>` backup of
        whatever content existed before the write (see `_create_backup`
        — a deliberate safety copy, not a leaked temp file). Anything
        else (`.tmp`, `.rollback`, or an orphaned `mkstemp` name) would
        mean a temp file leaked."""
        return {stem, f".{stem}.caelestia.lock"}

    def test_no_temp_artifacts_remain_after_live_apply_failure(self):
        path = Path(self._tmpdir.name) / "artifacts.conf"
        path.write_text("# manual\n")
        with self.assertRaises(RuntimeError):
            hp.write_managed_legacy_block_and_reload(
                path, "test-block", ["exec-once = new"],
                live_apply=lambda: _raise(RuntimeError("boom")),
            )
        remaining = {p.name for p in Path(self._tmpdir.name).iterdir()}
        allowed = self._non_artifact_names("artifacts.conf")
        backups = {n for n in remaining if n.startswith("artifacts.conf.bak_")}
        self.assertEqual(remaining - backups, allowed)
        self.assertEqual(len(backups), 1)
        for name in remaining:
            self.assertFalse(name.endswith(".tmp"), name)
            self.assertFalse(name.endswith(".rollback"), name)

    def test_no_temp_artifacts_remain_after_success(self):
        path = Path(self._tmpdir.name) / "artifacts_ok.conf"
        path.write_text("# manual\n")
        hp.write_managed_legacy_block_and_reload(path, "test-block", ["exec-once = new"])
        remaining = {p.name for p in Path(self._tmpdir.name).iterdir()}
        allowed = self._non_artifact_names("artifacts_ok.conf")
        backups = {n for n in remaining if n.startswith("artifacts_ok.conf.bak_")}
        self.assertEqual(remaining - backups, allowed)
        self.assertEqual(len(backups), 1)
        for name in remaining:
            self.assertFalse(name.endswith(".tmp"), name)
            self.assertFalse(name.endswith(".rollback"), name)


if __name__ == "__main__":
    unittest.main()
