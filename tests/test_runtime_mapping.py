import tempfile
import unittest
from pathlib import Path

from mo2_modlists.core import PackError
from mo2_modlists.runtime_mapping import cet_root_files


class RuntimeMappingTests(unittest.TestCase):
    def test_cet_relative_lookup_without_native_library_self_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory)
            prefix = "bin/x64/plugins/cyber_engine_tweaks/mods/example/"
            names = [prefix + "init.lua", prefix + "data/settings.json",
                     prefix + "native.dll", "bin/x64/version.dll",
                     "r6/scripts/example.reds"]
            for name in names:
                target = game / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fixture")
            outputs = [{"class": "game-root", "path": name} for name in names]
            lock = {"schemaVersion": 1, "kind": "source-installation",
                    "game": {"id": "cyberpunk2077"}, "priority": ["a", "b"],
                    "packages": {"a": {"outputs": outputs}, "b": {"outputs": outputs}}}
            self.assertEqual([rel for rel, _ in cet_root_files(lock, game)], names[:2])
            (game / names[0]).unlink()
            self.assertEqual([rel for rel, _ in cet_root_files(lock, game)], names[1:2])
            lock["packages"]["a"]["outputs"] = [
                {"class": "game-root", "path": prefix + "../escape.lua"}]
            with self.assertRaises(PackError):
                cet_root_files(lock, game)
