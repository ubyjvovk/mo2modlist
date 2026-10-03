from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mo2_modlists.core import PackError, digest, json_digest, write_json
from mo2_modlists.remote_manifests import (fetch_manifest, check_manifest_updates, manifest_url,
                                          fetch_json, HTTPSRedirects, MAX_JSON)
from mo2_modlists.packages import merge_packages
from mo2_modlists.acquisition import ArtifactStore


class RemoteManifestTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.url = "https://example.test/packs/overhaul.json"
        self.document = {'name': 'overhaul', 'version': '1.0.0', 'dependencies': {'mod': '*'},
                         'mo2': {'schemaVersion': 1, 'game': {'id': 'cyberpunk2077', 'dlc': []},
                                 'packages': ['recipes/mod.json']}}
        self.recipe_url = 'https://example.test/packs/recipes/mod.json'
        self.recipe = {'name': 'mod', 'version': '1.0.0', 'dependencies': {},
                       'mo2': {'schemaVersion': 1, 'game': {'id': 'cyberpunk2077', 'dlc': []},
                               'sources': [{'type': 'nexus', 'game': 'cyberpunk2077', 'modId': 1, 'fileId': 2}]}}
        self.docs = {self.url: self.document, self.recipe_url: self.recipe}
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        value = self.docs[url]
        return deepcopy(value), json_digest(value), url

    def install_metadata(self):
        source = fetch_manifest(self.url, self.root / "cache", fetch=self.fetch)
        profile = self.root / "profile"
        profile.mkdir()
        (profile / "modlist.json").write_bytes(source.read_bytes())
        return profile

    def test_relative_recipes_snapshot_offline_and_tamper_detection(self):
        source = fetch_manifest(self.url, self.root / "cache", fetch=self.fetch)
        document = json.loads(source.read_text())
        recipe = Path(document["mo2"]["packages"][0])
        self.assertEqual(json.loads(recipe.read_text()), self.recipe)
        self.assertEqual(document["mo2"]["extensions"]["remoteManifests"][self.url]["resources"],
                         {self.url: json_digest(self.document), self.recipe_url: json_digest(self.recipe)})
        self.assertEqual(fetch_manifest(self.url, self.root / "cache", fetch=lambda u: self.fail("network"), offline=True), source)
        recipe.write_text("{}")
        with self.assertRaisesRegex(PackError, "modified"):
            fetch_manifest(self.url, self.root / "cache", offline=True)

    def test_recipe_only_update_and_error_do_not_advance_installed_baseline(self):
        profile = self.install_metadata()
        before = digest(profile / "modlist.json")
        self.assertEqual(check_manifest_updates(profile, fetch=self.fetch)[0]["status"], "unchanged")
        self.recipe["version"] = "1.0.1"
        result = check_manifest_updates(profile, fetch=self.fetch)[0]
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["changedResources"], [self.recipe_url])
        self.assertEqual(digest(profile / "modlist.json"), before)
        def failed(url):
            raise PackError("Unavailable")
        self.assertEqual(check_manifest_updates(profile, fetch=failed)[0]["status"], "error")
        self.assertEqual(digest(profile / "modlist.json"), before)

    def test_remote_local_archives_and_local_registries_are_rejected(self):
        self.recipe["mo2"]["sources"] = [{"type": "local-archive", "path": "C:/private/file.zip"}]
        with self.assertRaisesRegex(PackError, "local archives"):
            fetch_manifest(self.url, self.root / "cache", fetch=self.fetch)
        self.document["dependencies"] = {}
        self.document["mo2"]["packages"] = []
        self.document["mo2"]["registries"] = {"bad": {"repository": "C:/private", "revision": "main"}}
        with self.assertRaises(PackError):
            fetch_manifest(self.url, self.root / "cache", fetch=self.fetch)

    def test_github_file_normalization_and_unsafe_urls(self):
        self.assertEqual(manifest_url("https://github.com/owner/repo/blob/main/my-pack.json?raw=1"),
                         "https://raw.githubusercontent.com/owner/repo/main/my-pack.json")
        for url in ("http://example.test/a.json", "file:///C:/secret.json", "https://user:secret@example.test/a.json",
                    "https://example.test/a.json?token=secret", "https://example.test/a.json#fragment"):
            with self.subTest(url=url), self.assertRaises(PackError):
                manifest_url(url)
        with self.assertRaises(PackError):
            HTTPSRedirects().redirect_request(None, None, 302, "", {}, "http://example.test/a.json")

    def test_cycle_and_invalid_schema_leave_no_usable_snapshot(self):
        self.recipe["mo2"]["packages"] = ["mod.json"]
        with self.assertRaisesRegex(PackError, "Cyclic"):
            fetch_manifest(self.url, self.root / "cache", fetch=self.fetch)
        with self.assertRaisesRegex(PackError, "No cached"):
            fetch_manifest(self.url, self.root / "cache", offline=True)
        self.document["mo2"]["schemaVersion"] = 99
        with self.assertRaisesRegex(PackError, "schemaVersion"):
            fetch_manifest(self.url, self.root / "cache", fetch=self.fetch)

    def test_new_snapshot_keeps_old_recipe_and_merges_multiple_tracked_urls(self):
        first = fetch_manifest(self.url, self.root / "cache", fetch=self.fetch)
        initial = json.loads(first.read_text())
        old_hash = digest(first)
        self.recipe["version"] = "1.0.1"
        second = fetch_manifest(self.url, self.root / "cache", fetch=self.fetch)
        self.assertNotEqual(first, second)
        self.assertEqual(digest(first), old_hash)
        current = json.loads(second.read_text())
        merged = merge_packages(initial, current, ArtifactStore(self.root / "cache"), first, second, ask=lambda r: "replace")
        self.assertEqual(merged["mo2"]["extensions"]["remoteManifests"][self.url]["resources"][self.recipe_url], json_digest(self.recipe))
        third = deepcopy(current)
        third["mo2"]["extensions"]["remoteManifests"] = {"https://else.test/pack.json": {"resources": {}}}
        self.assertEqual(len(merge_packages(merged, third, ArtifactStore(self.root / "cache"), second, second)["mo2"]["extensions"]["remoteManifests"]), 2)

    def test_transport_rejects_html_and_oversized_json(self):
        class Response(io.BytesIO):
            status = 200
            def geturl(self): return "https://example.test/a.json"
        for raw in (b"<html>Not JSON</html>", b" " * (MAX_JSON + 1)):
            with patch("urllib.request.build_opener") as opener:
                opener.return_value.open.return_value = Response(raw)
                with self.assertRaises(PackError):
                    fetch_json("https://example.test/a.json")

    def test_redirect_relative_recipes_use_final_url_directory(self):
        def redirected(url):
            doc, sha, _ = self.fetch(url)
            return doc, sha, "https://cdn.test/release/overhaul.json" if url == self.url else url
        self.docs["https://cdn.test/release/recipes/mod.json"] = self.recipe
        fetch_manifest(self.url, self.root / "cache", fetch=redirected)
        self.assertIn("https://cdn.test/release/recipes/mod.json", self.calls)

    def test_changed_root_does_not_fetch_a_removed_recipe(self):
        profile = self.install_metadata()
        self.document["dependencies"] = {}
        self.document["mo2"]["packages"] = []
        self.docs.pop(self.recipe_url)
        self.calls.clear()
        self.assertEqual(check_manifest_updates(profile, fetch=self.fetch)[0]["status"], "available")
        self.assertEqual(self.calls, [self.url])

    def test_signed_redirect_is_not_persisted_as_origin(self):
        class Response(io.BytesIO):
            status = 200
            def geturl(self): return "https://release-assets.githubusercontent.com/asset?token=temporary"
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = Response(json.dumps(self.document).encode())
            _, _, base = fetch_json(self.url)
            self.assertEqual(base, self.url)

    def test_cli_resolves_cached_url_offline(self):
        import subprocess
        import sys
        self.document["dependencies"] = {}
        self.document["mo2"]["packages"] = []
        fetch_manifest(self.url, self.root / "cache", fetch=self.fetch)
        game = self.root / "game"
        (game / "bin/x64").mkdir(parents=True)
        (game / "bin/x64/Cyberpunk2077.exe").write_bytes(b"fixture")
        result = subprocess.run([sys.executable, "-m", "mo2_modlists.cli", "resolve", "--manifest", self.url,
            "--offline", "--lock", str(self.root / "lock.json"), "--cache", str(self.root / "cache"), "--game", str(game)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["packages"], 1)

    def test_invalid_tracking_is_a_failed_check(self):
        profile = self.install_metadata()
        document = json.loads((profile / "modlist.json").read_text())
        document["mo2"]["extensions"]["remoteManifests"][self.url] = {"resources": {}}
        write_json(profile / "modlist.json", document)
        result = check_manifest_updates(profile, fetch=lambda u: self.fail("invalid tracking must not fetch"))
        self.assertEqual(result[0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
