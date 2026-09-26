import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from mo2_modlists.core import PackError, digest
from mo2_modlists.registry import snapshot_registry, registry_recipe


class RegistryTests(unittest.TestCase):
    def test_git_revision_is_pinned_and_recipe_cache_is_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout.decode().strip()
            git("init")
            recipe = repo / "recipe.json"
            recipe.write_text('{"fixture": true}', encoding="utf-8")
            source = {"type": "nexus", "game": "cyberpunk2077", "modId": 1, "fileId": 2}
            (repo / "index.json").write_text(json.dumps({"schemaVersion": 1, "entries": [
                {"source": source, "recipe": "recipe.json", "sha256": digest(recipe), "reason": "Test metadata"}]}))
            git("add", "index.json", "recipe.json")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "Registry fixture")
            commit = git("rev-parse", "HEAD")
            definition = {"repository": repo.as_posix(), "revision": commit}
            snapshot, entries = snapshot_registry("fixture", definition, root / "cache")
            self.assertEqual(snapshot["commit"], commit)
            self.assertEqual(registry_recipe(source, entries)["sha256"], digest(recipe))
            cached, _ = snapshot_registry("fixture", definition, root / "cache", offline=True)
            self.assertEqual(cached, snapshot)
            entries[0]["path"].write_text("tampered")
            with self.assertRaisesRegex(PackError, "modified"):
                snapshot_registry("fixture", definition, root / "cache", offline=True)
