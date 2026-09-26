import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from mo2_modlists.acquisition import ArtifactStore, InputRequired, download
from mo2_modlists.core import PackError, digest
from mo2_modlists.install import import_lock
from mo2_modlists.planning import resolve_manifest
from mo2_modlists.sources import members


class SourceInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mo2 = self.root / "mo2"
        self.mo2.mkdir()
        self.game = self.root / "game"
        (self.game / "bin/x64").mkdir(parents=True)
        (self.game / "bin/x64/Cyberpunk2077.exe").write_bytes(b"game fixture")
        self.store = ArtifactStore(self.root / "cache")
        self.manifest = self.root / "modlist.json"
        self.lock = self.root / "modlist.lock.json"
        self.closed = patch("mo2_modlists.core.game_running", return_value=False)
        self.closed.start()
        self.addCleanup(self.closed.stop)

    def dependency(self, name, files, dependencies=None, **recipe_extra):
        archive = self.root / (name + ".zip")
        with zipfile.ZipFile(archive, "w") as file:
            for path, content in files.items():
                file.writestr(path, content)
        recipe = {"schemaVersion": 1, "component": name, "version": "1", "revision": "1",
                  "artifact": "sha256:" + digest(archive), "dependencies": dependencies or {}, **recipe_extra}
        recipe_path = self.root / (name + ".recipe.json")
        recipe_path.write_text(json.dumps(recipe))
        return {"source": {"type": "local-archive", "path": archive.name}, "recipe": recipe_path.name}

    def resolve(self, dependencies, overrides=None):
        manifest = {"schemaVersion": 1, "name": "Fixture", "game": {"id": "cyberpunk2077", "dlc": []}, "dependencies": dependencies}
        if overrides:
            manifest["fileOverrides"] = overrides
        self.manifest.write_text(json.dumps(manifest))
        return resolve_manifest(self.manifest, self.store, self.game, self.lock)

    def test_transitive_source_install_and_offline_reinstall(self):
        base = self.dependency("base", {"bin/x64/loader.dll": b"loader"})
        feature = self.dependency("feature", {"r6/scripts/test.reds": b"script"}, {"framework": base})
        lock = self.resolve({"feature": feature})
        self.assertEqual(len(lock["packages"]), 2)
        self.assertEqual(len(lock["dependencyEdges"]), 1)
        result = import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", allow_root=True)
        self.assertEqual((self.game / "bin/x64/loader.dll").read_bytes(), b"loader")
        self.assertTrue((Path(result["profile"]) / "modlist.txt").exists())
        for path in self.root.glob("*.zip"):
            path.unlink()
        for path in self.root.glob("*.recipe.json"):
            path.unlink()
        offline = ArtifactStore(self.root / "cache", offline=True, request=lambda *a, **k: self.fail("network"))
        repeated = import_lock(self.manifest, self.lock, offline, self.mo2, self.game, "Offline", allow_root=True)
        self.assertEqual(len(repeated["mods"]), 2)

    def test_failure_restores_root_and_retry_reuses_disabled_stage(self):
        dependency = self.dependency("mod", {"bin/x64/loader.dll": b"new", "r6/scripts/test.reds": b"script"})
        self.resolve({"mod": dependency})
        root_file = self.game / "bin/x64/loader.dll"
        root_file.write_bytes(b"original")
        def fail(phase):
            if phase == "root-written":
                raise RuntimeError("simulated interruption")
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", allow_root=True, failure_hook=fail)
        self.assertEqual(root_file.read_bytes(), b"original")
        self.assertFalse((self.mo2 / "profiles/New").exists())
        import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", allow_root=True)
        self.assertEqual(root_file.read_bytes(), b"new")

    def test_publication_journal_failure_recovers_without_replacing_profile(self):
        dep = self.dependency("mod", {"r6/scripts/a.reds": b"a"})
        self.resolve({"mod": dep})
        def fail(phase):
            if phase == "profile-published":
                raise RuntimeError("journal interruption")
        with self.assertRaisesRegex(RuntimeError, "journal interruption"):
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", failure_hook=fail)
        profile = self.mo2 / "profiles/New/modlist.txt"
        before = profile.read_bytes()
        result = import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New")
        self.assertTrue(result["recovered"])
        self.assertEqual(profile.read_bytes(), before)
        with self.assertRaisesRegex(PackError, "already exists"):
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New")

    def test_imported_source_reexports_without_asking_for_source(self):
        from mo2_modlists.manifest import profile_sources
        dep = self.dependency("mod", {"r6/scripts/a.reds": b"a"})
        self.resolve({"mod": dep})
        import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New")
        sources = profile_sources(self.mo2, "New")
        self.assertEqual(sources[0]["dependency"]["source"]["path"], (self.root / "mod.zip").as_posix())
        self.assertEqual(sources[0]["dependency"]["integrity"], "sha256:" + digest(self.root / "mod.zip"))

    def test_tampered_recipe_bytes_and_reserved_output_fail_before_deployment(self):
        dep = self.dependency("mod", {"r6/scripts/a.reds": b"a"})
        lock = self.resolve({"mod": dep})
        package = next(iter(lock["packages"].values()))
        package["recipe"]["bytesBase64"] = "e30="
        self.lock.write_text(json.dumps(lock))
        with self.assertRaisesRegex(PackError, "recipe bytes"):
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New")
        self.assertEqual(list(self.mo2.iterdir()), [])

    def test_variant_options_create_separate_output_identity(self):
        dep = self.dependency("mod", {"a/file.txt": b"a", "b/file.txt": b"b"}, mappings=[],
            options={"look": {"choices": ["a", "b"]}}, variants={"look": {
                "a": {"mappings": [{"from": "a", "to": "r6", "class": "mo2-overlay"}]},
                "b": {"mappings": [{"from": "b", "to": "r6", "class": "mo2-overlay"}]}}})
        dep["options"] = {"look": "a"}
        a = self.resolve({"mod": dep})
        self.lock = self.root / "b.lock.json"
        dep["options"] = {"look": "b"}
        b = self.resolve({"mod": dep})
        self.assertNotEqual(a["priority"], b["priority"])
        self.assertNotEqual(next(iter(a["packages"].values()))["outputs"], next(iter(b["packages"].values()))["outputs"])

    def test_selected_alternative_expands_only_chosen_dependency(self):
        a = self.dependency("base-a", {"r6/scripts/a.reds": b"a"})
        b = self.dependency("base-b", {"r6/scripts/b.reds": b"b"})
        feature = self.dependency("feature", {"r6/scripts/f.reds": b"f"},
            options={"base": {"choices": ["a", "b"]}}, alternatives={"base": {"a": a, "b": b}})
        feature["options"] = {"base": "b"}
        lock = self.resolve({"feature": feature})
        self.assertEqual({p["component"] for p in lock["packages"].values()}, {"feature", "base-b"})
        self.assertEqual(lock["packages"][lock["aliases"]["feature"]]["selectedAlternatives"], {"base": "b"})
        self.assertTrue(lock["packages"][lock["aliases"]["feature"]]["outputs"])

    def test_hard_process_exit_releases_guard_and_resumes_root_deployment(self):
        dep = self.dependency("mod", {"bin/x64/loader.dll": b"new"})
        self.resolve({"mod": dep})
        (self.game / "bin/x64/loader.dll").write_bytes(b"original")
        script = '''import os, sys
from pathlib import Path
from mo2_modlists.acquisition import ArtifactStore
from mo2_modlists.install import import_lock
import mo2_modlists.core as core
core.game_running = lambda: False
root = Path(sys.argv[1])
def fail(phase):
    if phase == "root-written": os._exit(17)
import_lock(root / "modlist.json", root / "modlist.lock.json", ArtifactStore(root / "cache"), root / "mo2", root / "game", "New", allow_root=True, failure_hook=fail)
'''
        result = subprocess.run([sys.executable, "-c", script, str(self.root)], capture_output=True)
        self.assertEqual(result.returncode, 17, result.stderr.decode())
        self.assertFalse((self.mo2 / "profiles/New").exists())
        self.assertEqual((self.game / "bin/x64/loader.dll").read_bytes(), b"new")
        result = import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", allow_root=True)
        journal = json.loads(Path(result["journal"]).read_text())
        backup = next(iter(journal["root"].values()))["backup"]
        self.assertEqual(Path(backup["path"]).read_bytes(), b"original")

    def test_file_directory_collision_is_rejected_during_plan(self):
        dep = self.dependency("mod", {"r6/alias": b"file", "r6/alias/child": b"child"})
        with self.assertRaisesRegex(PackError, "also have to be a directory"):
            self.resolve({"mod": dep})
        self.assertFalse(self.lock.exists())

    def test_native_nexus_metadata_expands_into_recipe_backed_transitive_source(self):
        self.dependency("base", {"r6/scripts/base.reds": b"base"})
        self.dependency("feature", {"r6/scripts/feature.reds": b"feature"})
        feature_source = {"type": "nexus", "game": "cyberpunk2077", "modId": 1, "fileId": 2}
        base_source = {"type": "nexus", "game": "cyberpunk2077", "modId": 3, "fileId": 4}
        metadata = {"source": feature_source, "complete": True,
            "version": {"file": {"id": "feature-lineage"}, "version": "1"},
            "raw": {"dlc_dependency_definitions": []},
            "materialized": {"dependencies": [{"id": "base", "candidate_mod_files": [{"id": "base-lineage",
                "mod": {"game_scoped_id": "3", "game": {"domain_name": "cyberpunk2077"}},
                "candidate_versions": [{"id": "v-base", "name": "Base", "category": "main", "game_scoped_id": "4", "version": "1", "position": "1"}]}]}]}}
        self.store.nexus_fetch = lambda source: self.root / ("feature.zip" if source["fileId"] == 2 else "base.zip")
        self.store.nexus_metadata = SimpleNamespace(exact_source=lambda source, ask: source,
            metadata=lambda source: metadata if source == feature_source else {"source": base_source, "complete": False})
        document = {"schemaVersion": 1, "name": "Native", "game": {"id": "cyberpunk2077", "dlc": []},
            "dependencies": {"feature": {"source": feature_source}}}
        self.manifest.write_text(json.dumps(document))
        lock = resolve_manifest(self.manifest, self.store, self.game, self.lock,
            ask=lambda request: (self.root / "base.recipe.json").as_posix())
        self.assertEqual(len(lock["packages"]), 2)
        feature = lock["packages"][lock["aliases"]["feature"]]
        self.assertEqual(feature["artifact"]["integrityKind"], "locally-observed")
        self.assertEqual(feature["metadataProvenance"]["kind"], "nexus-v3-file-requirements")
        self.assertEqual(feature["nativeMetadata"], metadata)
        import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "Native")

    def test_conflicting_components_show_both_reason_chains(self):
        left = self.dependency("left", {"r6/scripts/a.reds": b"a"}, component="shared")
        right = self.dependency("right", {"r6/scripts/b.reds": b"b"}, component="shared")
        with self.assertRaisesRegex(PackError, "left.*versus right"):
            self.resolve({"left": left, "right": right})
        self.assertFalse(self.lock.exists())
        self.assertEqual(list(self.mo2.iterdir()), [])

    def test_unresolved_collision_requires_winner(self):
        left = self.dependency("left", {"r6/scripts/a.reds": b"a"})
        right = self.dependency("right", {"r6/scripts/a.reds": b"b"})
        with self.assertRaises(InputRequired) as error:
            self.resolve({"left": left, "right": right})
        self.assertEqual(error.exception.request["kind"], "file-conflict")
        lock = self.resolve({"left": left, "right": right}, [{"winner": "left", "loser": "right", "paths": ["r6/scripts/a.reds"]}])
        self.assertEqual(lock["priority"][0], lock["aliases"]["left"])

    def test_unknown_metadata_and_fomod_are_not_marked_complete(self):
        dependency = self.dependency("mod", {"fomod/ModuleConfig.xml": b"installer", "r6/scripts/a.reds": b"a"})
        with self.assertRaises(InputRequired) as error:
            self.resolve({"mod": dependency})
        self.assertEqual(error.exception.request["kind"], "installer-choice")
        del dependency["recipe"]
        with self.assertRaises(InputRequired) as error:
            self.resolve({"mod": dependency})
        self.assertEqual(error.exception.request["kind"], "dependency-metadata")

    def test_changed_manifest_cannot_use_lock(self):
        dependency = self.dependency("mod", {"r6/scripts/a.reds": b"a"})
        self.resolve({"mod": dependency})
        document = json.loads(self.manifest.read_text())
        document["name"] = "Changed"
        self.manifest.write_text(json.dumps(document))
        with self.assertRaisesRegex(PackError, "Manifest differs"):
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New")
        self.assertEqual(list(self.mo2.iterdir()), [])

    def test_links_and_windows_aliases_in_archives_rejected(self):
        for mode in ("link", "alias"):
            archive = self.root / (mode + ".zip")
            with zipfile.ZipFile(archive, "w") as output:
                if mode == "link":
                    info = zipfile.ZipInfo("link")
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    output.writestr(info, "outside")
                else:
                    output.writestr("File.txt", "a")
                    output.writestr("file.txt", "b")
            with self.assertRaises(PackError):
                list(members(archive))


class DownloadTests(unittest.TestCase):
    def test_resume_requires_matching_validator_and_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "archive.bin"
            target.with_suffix(".partial").write_bytes(b"abc")
            target.with_suffix(".download.json").write_text(json.dumps({"validator": '"v1"'}))
            class Response(io.BytesIO):
                status = 206
                headers = {"ETag": '"v1"', "Content-Range": "bytes 3-5/6", "Content-Length": "3"}
            def opener(request, **kwargs):
                self.assertEqual(request.get_header("Range"), "bytes=3-")
                self.assertEqual(request.get_header("If-range"), '"v1"')
                return Response(b"def")
            download("https://example.org/archive", target, opener=opener)
            self.assertEqual(target.read_bytes(), b"abcdef")


if __name__ == "__main__":
    unittest.main()
