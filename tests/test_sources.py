import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mo2_modlists.core import PackError, export_profile, verify_bundle
from mo2_modlists.sources import compact_bundle, hydrate_bundle, members, export_source_profile


class SourceRoundtrip(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mo2, game = self.root / "mo2", self.root / "game"
        def put(path, data):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        put(mo2 / "profiles/Test/modlist.txt", b"+Selected\n")
        put(mo2 / "mods/Selected/shared.txt", b"selected variant")
        put(mo2 / "overwrite/settings.json", b'{"local":true}')
        put(game / "bin/x64/Cyberpunk2077.exe", b"game")
        put(game / "goggame-galaxyFileList.ini", b"[base]\nF0=bin\\x64\\Cyberpunk2077.exe\n")
        self.bundle = self.root / "bundle"
        with patch("mo2_modlists.core.game_running", return_value=False):
            export_profile(mo2, game, "Test", self.bundle)
        self.archives = self.root / "downloads"
        self.archives.mkdir()
        with zipfile.ZipFile(self.archives / "mod.zip", "w") as archive:
            archive.writestr("fomod/variant-a/shared.txt", b"not selected")
            archive.writestr("fomod/variant-b/shared.txt", b"selected variant")
        (self.archives / "mod.zip.meta").write_text("[General]\nrepository=Nexus\ngameName=cyberpunk2077\nmodID=1\nfileID=2\n")

    def test_source_export_wrapper_cleans_snapshot_and_reconstructs(self):
        destination = self.root / "source-export"
        with patch("mo2_modlists.core.game_running", return_value=False):
            result = export_source_profile(self.root / "mo2", self.root / "game", "Test",
                                           destination, [self.archives])
        self.assertEqual(result["mods"], 1)
        self.assertEqual(result["sourceBackedFiles"], 1)
        self.assertEqual(list(self.root.glob("source-export.snapshot-*")), [])
        hydrate_bundle(destination, self.root / "cache", [self.archives])
        verify_bundle(destination)

    def test_reconstructs_selected_variant_and_retains_local_delta(self):
        compact = self.root / "compact"
        result = compact_bundle(self.bundle, compact, [self.archives])
        self.assertEqual(result["sourceBackedFiles"], 1)
        lock = json.loads((compact / "modlist.lock.json").read_text())
        source = next(iter(lock["sourceArtifacts"].values()))
        self.assertEqual(source["source"]["fileId"], 2)
        mapping = next(iter(lock["blobSources"].values()))
        self.assertEqual(mapping["member"], "fomod/variant-b/shared.txt")
        hydrated = hydrate_bundle(compact, self.root / "cache", [self.archives])
        self.assertEqual(hydrated["reconstructedBlobs"], 1)
        verify_bundle(compact)

    def test_changed_archive_is_not_silently_accepted(self):
        compact = self.root / "compact"
        compact_bundle(self.bundle, compact, [self.archives])
        (self.archives / "mod.zip").write_bytes(b"changed")
        with self.assertRaisesRegex(PackError, "Supply exact archive"):
            hydrate_bundle(compact, self.root / "cache", [self.archives])

    def test_unsafe_archive_member_rejected(self):
        archive_path = self.root / "bad.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("../escape", b"bad")
        with self.assertRaises(PackError):
            list(members(archive_path))

    def test_nexus_fetcher_result_is_verified(self):
        compact = self.root / "compact"
        compact_bundle(self.bundle, compact, [self.archives])
        calls = []
        def fetch(source):
            calls.append(source)
            return self.archives / "mod.zip"
        result = hydrate_bundle(compact, self.root / "cache", [], download=True, nexus_fetcher=fetch)
        self.assertEqual(calls[0]["fileId"], 2)
        self.assertEqual(result["reconstructedBlobs"], 1)
        verify_bundle(compact)
