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
        self.assertEqual(set(result["mods"]), {"feature", "framework"})
        self.assertFalse(any("[ML-" in name for name in result["mods"]))
        for path in self.root.glob("*.zip"):
            path.unlink()
        for path in self.root.glob("*.recipe.json"):
            path.unlink()
        offline = ArtifactStore(self.root / "cache", offline=True, request=lambda *a, **k: self.fail("network"))
        repeated = import_lock(self.manifest, self.lock, offline, self.mo2, self.game, "Offline", allow_root=True)
        self.assertEqual(len(repeated["mods"]), 2)
        self.assertEqual(set(repeated['mods']), {'feature (Offline)', 'framework (Offline)'})

    def test_display_names_preserve_unicode_and_disambiguate_existing_mods(self):
        from mo2_modlists.install import installed_name
        (self.mo2/'mods'/'Éclairage').mkdir(parents=True)
        package={'component':'nexus:lineage:123','displayName':'Éclairage'}
        self.assertEqual(installed_name(self.mo2, package, 'New', []), 'Éclairage (New)')
        self.assertEqual(installed_name(self.mo2, package, 'New', ['éclairage (new)']), 'Éclairage (New 2)')
        package['displayName']='CON.txt'
        self.assertEqual(installed_name(self.mo2, package, 'New', []), 'Mod CON.txt')

    def test_nexus_published_hash_reuses_matching_archive_without_sidecar(self):
        self.dependency('cached', {'r6/scripts/cached.reds': b'cached'})
        archive=self.root/'cached.zip'
        sha=digest(archive)
        self.store.archives=[self.root]
        self.store.nexus_metadata=SimpleNamespace(artifact_integrity=lambda source: sha)
        self.store.nexus_fetch=lambda source: self.fail('Unnecessary download')
        source={'type':'nexus','game':'cyberpunk2077','modId':12,'fileId':34}
        artifact=self.store.acquire({'source':source},self.manifest)
        self.assertEqual(artifact['sha256'],sha)
        self.assertEqual(artifact['source'],source)
        self.assertEqual(artifact['integrityKind'],'nexus-published-scan-hash')

    def test_manual_nexus_archive_keeps_source_and_verifies_locked_hash(self):
        dep = self.dependency("manual", {"r6/scripts/manual.reds": b"script"})
        archive = self.root / "manual.zip"
        source = {"type": "nexus", "game": "cyberpunk2077", "modId": 123, "fileId": 456}
        requests = []
        def choose(request):
            requests.append(request)
            return str(archive)
        store = ArtifactStore(self.root / "manual-cache", offline=True, manual_fetch=choose)
        record = store.acquire({"source": source}, self.manifest)
        self.assertEqual(record["source"], source)
        self.assertEqual(record["integrityKind"], "locally-observed")
        self.assertEqual(requests[0]["kind"], "nexus-archive")
        self.assertEqual(requests[0]["source"], source)
        archive.write_bytes(b"wrong downloaded file")
        other_store = ArtifactStore(self.root / "empty-cache", offline=True, manual_fetch=choose)
        with self.assertRaisesRegex(PackError, "pinned SHA-256"):
            other_store.acquire({"source": source}, self.manifest, locked=record)
        self.assertEqual(requests[-1]["expectedSha256"], record["sha256"])

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

    def test_successful_root_restore_and_interruption_resume(self):
        from mo2_modlists.restoration import restoration_plan, restore_root
        from mo2_modlists.core import json_digest
        dep = self.dependency("mod", {"bin/x64/loader.dll": b"new", "bin/x64/other.dll": b"added", "r6/scripts/a.reds": b"a"})
        self.resolve({"mod": dep})
        original = self.game / "bin/x64/loader.dll"
        original.write_bytes(b"original")
        result = import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", allow_root=True)
        operation = Path(result["journal"]).parent.name
        profile = Path(result["profile"]) / "modlist.txt"
        before = profile.read_bytes()
        plan = restoration_plan(self.mo2, self.game, operation)
        self.assertFalse(plan["blockers"])
        def fail(phase):
            raise RuntimeError("restore interrupted")
        with self.assertRaisesRegex(RuntimeError, "restore interrupted"):
            restore_root(self.mo2, self.game, operation, reviewed_sha256=json_digest(plan), failure_hook=fail)
        resumed = restoration_plan(self.mo2, self.game, operation)
        restore_root(self.mo2, self.game, operation, reviewed_sha256=json_digest(resumed))
        self.assertEqual(original.read_bytes(), b"original")
        self.assertFalse((self.game / "bin/x64/other.dll").exists())
        self.assertEqual(profile.read_bytes(), before)
        self.assertTrue((self.mo2 / "mods" / result["mods"][0] / "r6/scripts/a.reds").is_file())
        with self.assertRaisesRegex(PackError, "restored"):
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", allow_root=True)

    def test_root_restore_blocks_other_profile_adoption_and_later_edits(self):
        from mo2_modlists.restoration import restoration_plan, restore_root
        from mo2_modlists.core import json_digest
        dep = self.dependency("mod", {"bin/x64/loader.dll": b"new"})
        self.resolve({"mod": dep})
        result = import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", allow_root=True)
        operation = Path(result["journal"]).parent.name
        plan = restoration_plan(self.mo2, self.game, operation)
        target = self.game / "bin/x64/loader.dll"
        target.write_bytes(b"user edit")
        with self.assertRaisesRegex(PackError, "state changed"):
            restore_root(self.mo2, self.game, operation, reviewed_sha256=json_digest(plan))
        plan = restoration_plan(self.mo2, self.game, operation)
        with self.assertRaisesRegex(PackError, "changed after installation"):
            restore_root(self.mo2, self.game, operation, reviewed_sha256=json_digest(plan))
        self.assertEqual(target.read_bytes(), b"user edit")
        target.write_bytes(b"new")
        import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "Other", allow_root=True)
        plan = restoration_plan(self.mo2, self.game, operation)
        with self.assertRaisesRegex(PackError, "Other.*also requires"):
            restore_root(self.mo2, self.game, operation, reviewed_sha256=json_digest(plan))
        self.assertEqual(target.read_bytes(), b"new")

    def test_root_restore_rejects_changed_backup_before_mutation(self):
        from mo2_modlists.restoration import restoration_plan
        dep = self.dependency("mod", {"bin/x64/loader.dll": b"new"})
        self.resolve({"mod": dep})
        target = self.game / "bin/x64/loader.dll"
        target.write_bytes(b"original")
        result = import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", allow_root=True)
        journal = Path(result["journal"])
        backup = next(iter(json.loads(journal.read_text())["root"].values()))["backup"]
        Path(backup["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(PackError, "backup is missing or changed"):
            restoration_plan(self.mo2, self.game, journal.parent.name)
        self.assertEqual(target.read_bytes(), b"new")

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
        self.assertEqual(sources[0]["dependency"]["recipe"], (self.root / "mod.recipe.json").as_posix())

    def test_profile_export_keeps_verified_recipe_for_fresh_import(self):
        from mo2_modlists.manifest import profile_sources, export_manifest
        dep = self.dependency("mod", {"wrapped/a.reds": b"a"}, mappings=[{"from": "wrapped", "to": "r6/scripts", "class": "mo2-overlay"}])
        self.resolve({"mod": dep})
        import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "First")
        entries = profile_sources(self.mo2, "First")
        exported = self.root / "exported/modlist.json"
        export_manifest(self.mo2, self.game, "First", exported, {e["name"]: e["dependency"] for e in entries})
        self.assertEqual([p.name for p in exported.parent.iterdir()], ["modlist.json"])
        new_lock = self.root / "exported.lock.json"
        resolve_manifest(exported, self.store, self.game, new_lock, ask=lambda request: self.fail("Lost recipe metadata"))
        result = import_lock(exported, new_lock, self.store, self.mo2, self.game, "Second")
        self.assertEqual((self.mo2 / "mods" / result["mods"][0] / "r6/scripts/a.reds").read_bytes(), b"a")
        (self.root / "mod.recipe.json").write_text('{"changed": true}')
        self.assertNotIn("recipe", profile_sources(self.mo2, "First")[0]["dependency"])

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

    def test_native_nexus_metadata_respects_shared_pin_without_manual_candidate_prompt(self):
        self.dependency("base", {"r6/scripts/base.reds": b"base"})
        self.dependency("feature", {"r6/scripts/feature.reds": b"feature"})
        feature_source = {"type": "nexus", "game": "cyberpunk2077", "modId": 1, "fileId": 2}
        base_source = {"type": "nexus", "game": "cyberpunk2077", "modId": 3, "fileId": 4}
        metadata = {"source": feature_source, "complete": True,
            "version": {"file": {"id": "feature-lineage"}, "version": "1"},
            "raw": {"dlc_dependency_definitions": []},
            "materialized": {"dependencies": [{"id": "base", "candidate_mod_files": [{"id": "base-lineage",
                "mod": {"game_scoped_id": "3", "game": {"domain_name": "cyberpunk2077"}},
                "candidate_versions": [{"id": "v-base", "name": "Base", "category": "main", "game_scoped_id": "4", "version": "1", "position": "1"},
                    {"id": "v-base-new", "name": "Base new", "category": "main", "game_scoped_id": "5", "version": "2", "position": "2"}]}]}]}}
        self.store.nexus_fetch = lambda source: self.root / ("feature.zip" if source["fileId"] == 2 else "base.zip")
        self.store.nexus_metadata = SimpleNamespace(exact_source=lambda source, ask: source,
            metadata=lambda source: metadata if source == feature_source else {"source": base_source, "complete": False,
                "version": {"file": {"id": "base-lineage"}, "version": "1", "position": "1"}})
        document = {"schemaVersion": 1, "name": "Native", "game": {"id": "cyberpunk2077", "dlc": []},
            "dependencies": {"feature": {"source": feature_source}, "base": {"source": base_source, "recipe": "base.recipe.json"}}}
        self.manifest.write_text(json.dumps(document))
        lock = resolve_manifest(self.manifest, self.store, self.game, self.lock,
            ask=lambda request: self.fail("Unexpected manual prompt: " + request["kind"]))
        self.assertEqual(len(lock["packages"]), 2)
        feature = lock["packages"][lock["aliases"]["feature"]]
        self.assertEqual(feature["artifact"]["integrityKind"], "locally-observed")
        self.assertEqual(feature["metadataProvenance"]["kind"], "nexus-v3-file-requirements")
        self.assertEqual(feature["nativeMetadata"], metadata)
        self.assertEqual(lock["candidateResolution"]["engine"], "resolvelib-1.2.1")
        self.assertEqual(lock["candidateResolution"]["components"]["nexus:cyberpunk2077:lineage:base-lineage"], base_source)
        import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "Native")

        # A local layout recipe must not erase the provider's requirements.
        self.lock.unlink()
        document["dependencies"]["feature"]["recipe"] = "feature.recipe.json"
        self.manifest.write_text(json.dumps(document))
        lock = resolve_manifest(self.manifest, self.store, self.game, self.lock)
        from copy import deepcopy
        from mo2_modlists.install import validate_lock
        validate_lock(lock, document)
        for mode in ("omitted", "redirected", "wrong-source", "missing-dlc"):
            with self.subTest(native_lock=mode):
                changed = deepcopy(lock)
                feature = changed["packages"][changed["aliases"]["feature"]]
                if mode == "omitted":
                    changed["dependencyEdges"] = []
                elif mode == "redirected":
                    changed["dependencyEdges"][0]["to"] = changed["aliases"]["feature"]
                elif mode == "wrong-source":
                    feature["nativeMetadata"]["source"] = base_source
                else:
                    feature["nativeMetadata"]["raw"]["dlc_dependency_definitions"] = [
                        {"dlc_targets": [{"dlc_id": "1"}]}]
                with self.assertRaisesRegex(PackError, "native dependency|different locked source|native DLC"):
                    validate_lock(changed, document)

    def test_collection_external_steps_require_fresh_target_acknowledgement(self):
        dep = self.dependency("mod", {"r6/scripts/a.reds": b"a"})
        self.resolve({"mod": dep})
        self.lock.unlink()
        document = json.loads(self.manifest.read_text())
        document["extensions"] = {"nexusCollection": {"schemaVersion": 1, "externalInstructions": "Complete the fixture's external setup."}}
        self.manifest.write_text(json.dumps(document))
        lock = resolve_manifest(self.manifest, self.store, self.game, self.lock)
        with self.assertRaises(InputRequired) as error:
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New")
        self.assertEqual(error.exception.request["kind"], "external-prerequisites")
        self.assertEqual(list(self.mo2.iterdir()), [])
        acknowledged = [lock["externalPrerequisites"][0]["id"]]
        import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", acknowledged=acknowledged)
        with self.assertRaises(InputRequired):
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "Another")

    def test_lock_cannot_omit_a_required_dependency_or_redirect_its_edge(self):
        from copy import deepcopy
        base = self.dependency("base", {"r6/scripts/base.reds": b"base"})
        feature = self.dependency("feature", {"r6/scripts/feature.reds": b"feature"}, {"base": base})
        lock = self.resolve({"feature": feature, "base": base})
        for mode in ("omitted", "redirected"):
            changed = deepcopy(lock)
            if mode == "omitted":
                changed["dependencyEdges"] = []
            else:
                changed["dependencyEdges"][0]["to"] = changed["aliases"]["feature"]
            self.lock.write_text(json.dumps(changed))
            with self.assertRaisesRegex(PackError, "omits required|does not satisfy"):
                import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "Bad")
            self.assertEqual(list(self.mo2.iterdir()), [])

    def test_lock_cannot_add_a_root_mapping_not_present_in_recipe(self):
        dependency = self.dependency("mod", {"r6/scripts/a.reds": b"script"})
        lock = self.resolve({"mod": dependency})
        package = next(iter(lock["packages"].values()))
        package["outputs"][0].update(path="bin/x64/unexpected.dll", **{"class": "game-root"})
        self.lock.write_text(json.dumps(lock))
        with self.assertRaisesRegex(PackError, "output mappings differ"):
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "Bad", allow_root=True)
        self.assertFalse((self.game / "bin/x64/unexpected.dll").exists())
        self.assertFalse((self.mo2 / "profiles/Bad").exists())

    def test_lock_priority_cannot_reverse_a_recorded_file_winner(self):
        a = self.dependency("a", {"r6/scripts/shared.reds": b"a"})
        b = self.dependency("b", {"r6/scripts/shared.reds": b"b"})
        lock = self.resolve({"a": a, "b": b}, [{"winner": "a", "loser": "b", "paths": ["r6/scripts/shared.reds"]}])
        lock["priority"].reverse()
        self.lock.write_text(json.dumps(lock))
        with self.assertRaisesRegex(PackError, "priority contradicts"):
            import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "Bad")
        self.assertEqual(list(self.mo2.iterdir()), [])

    def test_readonly_verifier_detects_runtime_edits_and_unexpected_files(self):
        from mo2_modlists.inspection import verify_installation, inspect_lock
        dependency = self.dependency("mod", {"r6/scripts/a.reds": b"script", "bin/x64/loader.dll": b"loader"})
        self.resolve({"mod": dependency})
        result = import_lock(self.manifest, self.lock, self.store, self.mo2, self.game, "New", allow_root=True)
        inspection = inspect_lock(self.manifest, self.lock)
        self.assertEqual(inspection["physicalGameFiles"], ["bin/x64/loader.dll"])
        verified = verify_installation(self.manifest, self.lock, self.mo2, self.game, "New")
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["filesChecked"], 2)
        mod = self.mo2 / "mods" / result["mods"][0]
        (mod / "r6/scripts/a.reds").write_bytes(b"runtime edit")
        (mod / "extra.txt").write_bytes(b"extra")
        verified = verify_installation(self.manifest, self.lock, self.mo2, self.game, "New")
        self.assertEqual({difference["kind"] for difference in verified["differences"]}, {"changed-file", "extra-mod-file"})
        self.assertEqual((mod / "r6/scripts/a.reds").read_bytes(), b"runtime edit")

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
    def test_changed_github_asset_id_gets_new_bytes_and_old_lock_cannot_substitute(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = {"type": "github-release", "repository": "owner/repo", "tag": "v1", "asset": "mod.zip"}
            release = {"id": 1, "tag_name": "v1", "assets": [{"id": 10, "name": "mod.zip", "browser_download_url": "https://example.org/old"}]}
            def transfer(url, target, progress):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(url.encode())
            store = ArtifactStore(root / "cache", request=lambda url: release, transfer=transfer)
            first = store.acquire({"source": source}, root / "manifest.json")
            release["assets"][0].update(id=11, browser_download_url="https://example.org/new")
            second = store.acquire({"source": source}, root / "manifest.json")
            self.assertNotEqual(first["sha256"], second["sha256"])
            store.path(first["sha256"]).unlink()
            with self.assertRaisesRegex(PackError, "identity changed"):
                store.acquire({"source": source}, root / "manifest.json", locked=first)

    def test_changed_remote_validator_restarts_partial_without_old_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "archive.bin"
            target.with_suffix(".partial").write_bytes(b"old bytes")
            target.with_suffix(".download.json").write_text(json.dumps({"validator": '"old"'}))
            class Response(io.BytesIO):
                status = 200
                headers = {"ETag": '"new"', "Content-Length": "3"}
            download("https://example.org/archive", target, opener=lambda *a, **k: Response(b"new"))
            self.assertEqual(target.read_bytes(), b"new")

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
