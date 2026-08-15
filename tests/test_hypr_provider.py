import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import hypr_provider as hp


class ProviderPersistenceTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_file = Path(self._tmpdir.name) / "hyprland_provider.json"
        patcher = mock.patch.object(hp, "PROVIDER_CONFIG_FILE", self.config_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_file_returns_none(self):
        self.assertIsNone(hp.load_provider())

    def test_valid_hyprlang_roundtrip(self):
        hp.save_provider(hp.Provider.HYPRLANG)
        self.assertEqual(hp.load_provider(), hp.Provider.HYPRLANG)

    def test_valid_lua_roundtrip(self):
        hp.save_provider(hp.Provider.LUA)
        self.assertEqual(hp.load_provider(), hp.Provider.LUA)

    def test_invalid_value_returns_none(self):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps({"hyprland_config_provider": "not_a_real_provider"}))
        self.assertIsNone(hp.load_provider())

    def test_missing_key_returns_none(self):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps({"some_other_key": "lua"}))
        self.assertIsNone(hp.load_provider())

    def test_corrupt_json_returns_none(self):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text("{not valid json")
        self.assertIsNone(hp.load_provider())

    def test_unexpected_json_shape_returns_none(self):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(["not", "a", "dict"]))
        self.assertIsNone(hp.load_provider())

    def test_boolean_value_is_rejected(self):
        # The spec explicitly forbids storing a bare boolean instead of a
        # named provider — this must not be silently accepted as "lua".
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps({"hyprland_config_provider": True}))
        self.assertIsNone(hp.load_provider())

    def test_save_creates_parent_dir(self):
        nested = Path(self._tmpdir.name) / "nested" / "dir" / "hyprland_provider.json"
        with mock.patch.object(hp, "PROVIDER_CONFIG_FILE", nested):
            hp.save_provider(hp.Provider.LUA)
            self.assertTrue(nested.exists())
            self.assertEqual(hp.load_provider(), hp.Provider.LUA)


class NeedsProviderPromptTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_file = Path(self._tmpdir.name) / "hyprland_provider.json"
        patcher = mock.patch.object(hp, "PROVIDER_CONFIG_FILE", self.config_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_true_when_unset(self):
        self.assertTrue(hp.needs_provider_prompt())

    def test_false_after_valid_save(self):
        hp.save_provider(hp.Provider.HYPRLANG)
        self.assertFalse(hp.needs_provider_prompt())

    def test_true_again_after_corruption(self):
        # Simulates a file that got corrupted after a previous valid save —
        # the dialog must come back rather than assume a provider.
        hp.save_provider(hp.Provider.LUA)
        self.config_file.write_text("{broken")
        self.assertTrue(hp.needs_provider_prompt())


class ResolvePathTest(unittest.TestCase):
    def test_same_domains_for_both_providers(self):
        self.assertEqual(set(hp.LEGACY_PATHS), set(hp.LUA_PATHS))

    def test_resolve_path_hyprlang(self):
        self.assertEqual(hp.resolve_path("monitors", hp.Provider.HYPRLANG), hp.LEGACY_PATHS["monitors"])

    def test_resolve_path_lua(self):
        self.assertEqual(hp.resolve_path("monitors", hp.Provider.LUA), hp.LUA_PATHS["monitors"])

    def test_resolve_path_all_domains(self):
        for domain in hp.LEGACY_PATHS:
            legacy = hp.resolve_path(domain, hp.Provider.HYPRLANG)
            lua = hp.resolve_path(domain, hp.Provider.LUA)
            self.assertTrue(str(legacy).endswith(".conf"))
            self.assertTrue(str(lua).endswith(".lua"))

    def test_unknown_domain_raises(self):
        with self.assertRaises(KeyError):
            hp.resolve_path("does-not-exist", hp.Provider.HYPRLANG)


if __name__ == "__main__":
    unittest.main()
