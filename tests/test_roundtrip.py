import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mo2_modlists.core import PackError, digest, export_profile, import_profile, safe_relative, verify_bundle, patched_game_settings

REAL_REPLACE = os.replace


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.game = self.root / "game"
        self.target = self.root / "target"
        self.new_game = self.root / "new-game"
        self.bundle = self.root / "bundle"
        for game in (self.game, self.new_game):
            put(game, "bin/x64/Cyberpunk2077.exe", b"same original game")
            put(game, "goggame-galaxyFileList.ini", b"[base]\nF0=bin\\x64\\Cyberpunk2077.exe\nF1=stock.dat\n")
            put(game, "stock.dat", b"original stock")
        put(self.source, "profiles/Play/modlist.txt", b"+Patch\n-Disabled\n+Base\n")
        put(self.source, "profiles/Play/settings.ini", b"[General]\nLocalSaves=false\n")
        put(self.source, "ModOrganizer.ini", b"[Plugins]\nCyberpunk%202077%20Support%20Plugin\\disable_crashreporter=false\n")
        put(self.source, "mods/Base/shared.txt", b"base")
        put(self.source, "mods/Patch/shared.txt", b"patch selected by FOMOD")
        put(self.source, "mods/Patch/meta.ini", b"[General]\nmodid=123\nversion=1.2\n")
        put(self.source, "mods/Disabled/dont-copy.txt", b"disabled")
        put(self.source, "overwrite/config.json", b'{"userChoice":42}')
        put(self.game, "bin/x64/version.dll", b"bootstrap")
        self.running = patch("mo2_modlists.core.game_running", return_value=False)
        self.running.start()
        self.addCleanup(self.running.stop)

    def export(self):
        return export_profile(self.source, self.game, "Play", self.bundle)

    def test_round_trip_preserves_priority_outputs_and_root(self):
        source_hash = digest(self.source / "profiles/Play/modlist.txt")
        result = self.export()
        self.assertEqual(result["mods"], 2)
        lock = verify_bundle(self.bundle)
        self.assertEqual([l["name"] for l in lock["layers"]], ["Patch", "Base"])
        self.assertNotIn("stock.dat", [e["path"] for e in lock["root"]])
        restored = import_profile(self.bundle, self.target, self.new_game, "Restored", allow_root=True)
        names = restored["mods"]
        self.assertEqual((self.target / "mods" / names[0] / "config.json").read_bytes(), b'{"userChoice":42}')
        self.assertEqual((self.target / "mods" / names[1] / "shared.txt").read_bytes(), b"patch selected by FOMOD")
        self.assertEqual((self.new_game / "bin/x64/version.dll").read_bytes(), b"bootstrap")
        self.assertEqual(source_hash, digest(self.source / "profiles/Play/modlist.txt"))
        self.assertEqual((self.new_game / "stock.dat").read_bytes(), b"original stock")
        self.assertIn("disable_crashreporter=false", (self.target / "ModOrganizer.ini").read_text())

    def test_tamper_rejected_before_target_mutation(self):
        self.export()
        blob = next((self.bundle / "blobs").iterdir())
        blob.write_bytes(b"X" * blob.stat().st_size)
        with self.assertRaisesRegex(PackError, "Hash mismatch"):
            import_profile(self.bundle, self.target, self.new_game, "Restored", allow_root=True)
        self.assertFalse(self.target.exists())

    def test_existing_profile_never_overwritten(self):
        self.export()
        put(self.target, "profiles/Restored/modlist.txt", b"keep me")
        with self.assertRaisesRegex(PackError, "already exists"):
            import_profile(self.bundle, self.target, self.new_game, "Restored", allow_root=True)
        self.assertEqual((self.target / "profiles/Restored/modlist.txt").read_bytes(), b"keep me")

    def test_manifest_change_requires_new_lock(self):
        self.export()
        path = self.bundle / "modlist.json"
        value = json.loads(path.read_text())
        value["name"] = "changed"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(PackError, "differs from the lock"):
            verify_bundle(self.bundle)

    def test_failed_root_deployment_rolls_back_created_mods(self):
        self.export()
        with patch("mo2_modlists.core.os.replace", side_effect=self.fail_bootstrap_replace):
            with self.assertRaisesRegex(OSError, "simulated"):
                import_profile(self.bundle, self.target, self.new_game, "Restored", allow_root=True)
        self.assertFalse((self.target / "profiles/Restored").exists())
        self.assertEqual(list((self.target / "mods").iterdir()), [])

    @staticmethod
    def fail_bootstrap_replace(source, target):
        if Path(target).name == "version.dll":
            raise OSError("simulated write failure")
        REAL_REPLACE(source, target)

    def test_unsafe_windows_paths(self):
        for name in ("../x", "/x", "a//b", "a/../b", "C:/x", "a:stream", "NUL.txt", "x. ", "a\\b"):
            with self.subTest(name=name), self.assertRaises(PackError):
                safe_relative(name)

    def test_game_settings_preserve_other_qt_sections(self):
        ini = put(self.target, "ModOrganizer.ini", b"[Plugins]\nOther\\setting=@ByteArray(abc)\nCyberpunk%202077%20Support%20Plugin\\disable_crashreporter=true\n[Servers]\nuntouched=hello\n")
        result = patched_game_settings(ini, {"disable_crashreporter": "false"})
        self.assertIn("Other\\setting=@ByteArray(abc)", result)
        self.assertIn("[Servers]\nuntouched=hello", result)
        self.assertEqual(result.count("disable_crashreporter="), 1)
        self.assertIn("disable_crashreporter=false\n[Servers]", result)

    def test_matching_overwrite_allowed_and_conflicting_overwrite_rejected(self):
        self.export()
        put(self.target, "overwrite/config.json", b'{"userChoice":42}')
        import_profile(self.bundle, self.target, self.new_game, "Matching", allow_root=True)
        put(self.target, "overwrite/config.json", b'{"userChoice":99}')
        with self.assertRaisesRegex(PackError, "overwrite would alter"):
            import_profile(self.bundle, self.target, self.new_game, "Conflicting", allow_root=True)
        self.assertFalse((self.target / "profiles/Conflicting").exists())

    def test_failure_after_root_write_restores_prior_file(self):
        self.export()
        put(self.new_game, "bin/x64/version.dll", b"prior bootstrap")
        real_write = Path.write_text
        def fail_ini(path, *args, **kwargs):
            if path.name == "updated-MO2.ini":
                raise OSError("simulated INI failure")
            return real_write(path, *args, **kwargs)
        with patch.object(Path, "write_text", fail_ini):
            with self.assertRaisesRegex(OSError, "simulated INI failure"):
                import_profile(self.bundle, self.target, self.new_game, "Restored", allow_root=True)
        self.assertEqual((self.new_game / "bin/x64/version.dll").read_bytes(), b"prior bootstrap")
        self.assertFalse((self.target / "profiles/Restored").exists())


if __name__ == "__main__":
    unittest.main()
