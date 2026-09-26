import json
from pathlib import Path
import tempfile
import unittest

from mo2_modlists.core import PackError
from mo2_modlists.manifest import (export_manifest, validate_manifest, source_from_url,
                                  profile_sources, local_dependency)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mo2, self.game = self.root / "mo2", self.root / "game"
        (self.mo2 / "profiles/Play").mkdir(parents=True)
        (self.mo2 / "profiles/Play/modlist.txt").write_text("+Patch\n+Base\n+Unknown\n-Disabled\n")
        for name in ("Patch", "Base", "Unknown"):
            mod = self.mo2 / "mods" / name
            mod.mkdir(parents=True)
            (mod / "same.ini").write_text(name)
        (self.mo2 / "mods/Base/meta.ini").write_text("[General]\nrepository=Nexus\ngameName=cyberpunk2077\nmodid=1\n[installedFiles]\n1\\fileid=2\n")
        self.output = self.root / "output/modlist.json"
        self.selections = {"Patch": {"source": {"type": "github-release", "repository": "owner/mod", "tag": "v1", "asset": "mod.zip"}},
                           "Base": {"source": {"type": "nexus", "game": "cyberpunk2077", "modId": 1, "fileId": 2}}, "Unknown": None}

    def test_exports_only_agreed_manifest_and_explicit_conflicts(self):
        result = export_manifest(self.mo2, self.game, "Play", self.output, self.selections)
        self.assertEqual(result["skipped"], ["Unknown"])
        self.assertEqual([p.name for p in self.output.parent.iterdir()], ["modlist.json"])
        doc = validate_manifest(json.loads(self.output.read_text()))
        self.assertEqual(set(doc), {"schemaVersion", "name", "game", "dependencies", "fileOverrides"})
        self.assertEqual(doc["fileOverrides"], [{"winner": "patch", "loser": "base", "paths": ["same.ini"]}])

    def test_unknown_source_never_silently_skipped(self):
        del self.selections["Unknown"]
        with self.assertRaisesRegex(PackError, "explicitly skip: Unknown"):
            export_manifest(self.mo2, self.game, "Play", self.output, self.selections)
        self.assertFalse(self.output.exists())

    def test_metadata_does_not_invent_provenance(self):
        entries = {x["name"]: x["dependency"] for x in profile_sources(self.mo2, "Play")}
        self.assertIsNone(entries["Patch"])
        self.assertIsNone(entries["Unknown"])
        self.assertEqual(entries["Base"]["source"]["fileId"], 2)
        self.assertNotIn("Disabled", entries)

    def test_local_reference_copies_no_archive(self):
        archive = self.root / "original.zip"
        archive.write_bytes(b"fixture")
        dependency = local_dependency(archive, self.output)
        self.assertEqual(dependency["source"]["path"], "../original.zip")
        self.assertTrue(dependency["integrity"].startswith("sha256:"))
        self.assertFalse(self.output.parent.exists())

    def test_source_url_is_identity_not_download_credentials(self):
        self.assertEqual(source_from_url("https://www.nexusmods.com/cyberpunk2077/mods/1?tab=files&file_id=2"),
                         {"type": "nexus", "game": "cyberpunk2077", "modId": 1, "fileId": 2})
        self.assertEqual(source_from_url("https://github.com/owner/mod/releases/download/v1/mod.zip")["tag"], "v1")
        for url in ("https://github.com/owner/mod/releases/download/v1/mod.zip?token=secret", "https://example.org/a.zip", "https://nexusmods.com/cyberpunk2077/mods/1?api_key=secret"):
            with self.assertRaises(PackError):
                source_from_url(url)

    def test_unknown_fields_and_ambiguous_github_selector_fail(self):
        document = {"schemaVersion": 1, "name": "test", "game": {"id": "cyberpunk2077", "dlc": []}, "dependencies": {"a": self.selections["Patch"]}}
        validate_manifest(document)
        document["mode"] = "installed-snapshot"
        with self.assertRaises(PackError):
            validate_manifest(document)
        del document["mode"]
        document["dependencies"]["a"]["source"]["channel"] = "stable"
        with self.assertRaises(PackError):
            validate_manifest(document)

    def test_existing_export_preserved(self):
        self.output.parent.mkdir()
        self.output.write_text("keep")
        with self.assertRaises(PackError):
            export_manifest(self.mo2, self.game, "Play", self.output, self.selections)
        self.assertEqual(self.output.read_text(), "keep")

    def test_stale_github_catalog_is_not_exported_as_installed_version(self):
        (self.mo2 / "mods/Patch/meta.ini").write_text("[General]\nversion=1.10\n")
        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps([{"Name": "Patch", "Version": "v1.1", "Url": "https://github.com/owner/mod/releases/download/v1.1/mod.zip", "SHA256": "a" * 64}]))
        entries = {x["name"]: x["dependency"] for x in profile_sources(self.mo2, "Play", github_catalog=catalog)}
        self.assertIsNone(entries["Patch"])


if __name__ == "__main__":
    unittest.main()
