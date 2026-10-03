import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mo2_modlists.acquisition import ArtifactStore, InputRequired
from mo2_modlists.core import PackError, digest, write_json
from mo2_modlists.install import import_lock
from mo2_modlists.planning import resolve_manifest
from mo2_modlists.profile_add import prepare_add


class ProfileAddTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.mo2, self.game = self.root / "mo2", self.root / "game"
        self.mo2.mkdir()
        (self.game / "bin/x64").mkdir(parents=True)
        (self.game / "bin/x64/Cyberpunk2077.exe").write_bytes(b"game fixture")
        self.store = ArtifactStore(self.root / "cache")
        closed = patch("mo2_modlists.core.game_running", return_value=False)
        closed.start()
        self.addCleanup(closed.stop)
        self.profile = self.mo2 / "profiles/Play"

    def dep(self, name, version="1", dependencies=None, root=False):
        archive = self.root / f"{name}-{version}.zip"
        path = f"bin/x64/{name}.dll" if root else f"r6/scripts/{name}.reds"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(path, version.encode())
        recipe = self.root / f"{name}-{version}.recipe.json"
        write_json(recipe, {"schemaVersion": 1, "component": name, "version": version, "revision": "1",
            "artifact": "sha256:" + digest(archive), "dependencies": dependencies or {}})
        return {"source": {"type": "local-archive", "path": archive.as_posix()}, "recipe": recipe.as_posix()}

    def manifest(self, name, deps):
        definitions = {}
        def package(dep):
            recipe = json.loads(Path(dep['recipe']).read_text())
            children = [package(d) for d in recipe['dependencies'].values()]
            doc = {'name': recipe['component'], 'version': recipe['version'] + '.0.0',
                   'dependencies': {d['name']: d['version'] for d in children},
                   'mo2': {'schemaVersion': 1, 'game': {'id': 'cyberpunk2077', 'dlc': []},
                           'sources': [dep['source']], 'integrity': recipe['artifact']}}
            definitions[doc['name']] = doc
            return doc
        roots = [package(d) for d in deps.values()]
        if len(roots) == 1:
            doc = dict(roots[0])
            doc['mo2'] = dict(doc['mo2'])
            doc['mo2']['packages'] = [d for n, d in definitions.items() if n != doc['name']]
        else:
            doc = {'name': name, 'version': '1.0.0',
                   'dependencies': {d['name']: d['version'] for d in roots},
                   'mo2': {'schemaVersion': 1, 'game': {'id': 'cyberpunk2077', 'dlc': []},
                           'packages': list(definitions.values())}}
        path = self.root / f'{name}.json'
        write_json(path, doc)
        return path

    def initial(self, deps):
        manifest = self.manifest("initial", deps)
        lock = self.root / "initial.lock.json"
        resolve_manifest(manifest, self.store, self.game, lock)
        return import_lock(manifest, lock, self.store, self.mo2, self.game, "Play", allow_root=True)

    def apply(self, plan, **kw):
        return import_lock(Path(plan["manifest"]), Path(plan["lock"]), self.store, self.mo2, self.game, "Play",
                           update=plan, allow_root=True, **kw)

    def test_add_resolves_transitive_and_preserves_settings_edits_and_other_profile(self):
        self.initial({"base": self.dep("base")})
        (self.profile / "settings.ini").write_bytes(b"custom settings")
        (self.profile / "saves").mkdir()
        (self.profile / "saves/a.dat").write_bytes(b"save")
        edited = self.mo2 / "mods/base/r6/scripts/base.reds"
        edited.write_bytes(b"local edit")
        (self.profile / "modlist.txt").write_text("+base\n-disabled\n", encoding="utf-8")
        dep = self.dep("feature", dependencies={"framework": self.dep("framework")})
        plan = prepare_add(self.manifest("addition", {"feature": dep}), self.store, self.mo2, self.game, "Play")
        self.assertEqual(sum(bool(p["outputs"]) for p in json.loads(Path(plan["lock"]).read_text())["packages"].values()), 3)
        self.apply(plan)
        self.assertEqual(edited.read_bytes(), b"local edit")
        self.assertEqual((self.profile / "settings.ini").read_bytes(), b"custom settings")
        self.assertEqual((self.profile / "saves/a.dat").read_bytes(), b"save")
        self.assertIn("-disabled", (self.profile / "modlist.txt").read_text())
        self.assertEqual(set(json.loads((self.profile / "modlist.json").read_text())["extensions"]["packageRoot"]["dependencies"]), {"base", "feature"})

    def test_replace_creates_separate_folder_and_conflicting_graph_blocks(self):
        base = self.dep("base")
        self.initial({"base": base})
        updated = self.dep("base", "2")
        incoming = self.manifest("upgrade", {"base": updated})
        with self.assertRaises(InputRequired):
            prepare_add(incoming, self.store, self.mo2, self.game, "Play")
        plan = prepare_add(incoming, self.store, self.mo2, self.game, "Play", ask=lambda request: "replace")
        self.apply(plan)
        self.assertEqual((self.mo2 / "mods/base/r6/scripts/base.reds").read_bytes(), b"1")
        self.assertEqual((self.mo2 / "mods/base (Play)/r6/scripts/base.reds").read_bytes(), b"2")
        before = (self.profile / "modlist.txt").read_bytes()
        feature = self.dep("feature", dependencies={"old": base})
        with self.assertRaises(PackError):
            prepare_add(self.manifest("conflict", {"feature": feature}), self.store, self.mo2, self.game, "Play")
        self.assertEqual((self.profile / "modlist.txt").read_bytes(), before)

    def test_profile_mutation_invalidates_review(self):
        self.initial({"base": self.dep("base")})
        plan = prepare_add(self.manifest("add", {"feature": self.dep("feature")}), self.store, self.mo2, self.game, "Play")
        (self.profile / "modlist.txt").write_text("-base\n")
        with self.assertRaisesRegex(PackError, "changed since review"):
            self.apply(plan)

    def test_interrupted_publication_rolls_back_profile_and_root_then_retry(self):
        self.initial({"base": self.dep("base", root=True)})
        before = {p.name: p.read_bytes() for p in self.profile.iterdir() if p.is_file()}
        plan = prepare_add(self.manifest("add", {"base": self.dep("base", "2", root=True)}),
                           self.store, self.mo2, self.game, "Play", ask=lambda r: "replace")
        def fail(phase):
            if phase == "profile-file-written":
                raise RuntimeError("interruption")
        with self.assertRaises(RuntimeError):
            self.apply(plan, failure_hook=fail)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.profile.iterdir() if p.is_file()})
        self.assertEqual((self.game / "bin/x64/base.dll").read_bytes(), b"1")
        self.apply(plan)
        self.assertEqual((self.game / "bin/x64/base.dll").read_bytes(), b"2")

    def test_shared_root_upgrade_blocks(self):
        self.initial({"base": self.dep("base", root=True)})
        other = self.mo2 / "profiles/Other"
        other.mkdir()
        (other / "modlist.lock.json").write_bytes((self.profile / "modlist.lock.json").read_bytes())
        with self.assertRaisesRegex(PackError, "Other.*shared"):
            prepare_add(self.manifest("upgrade", {"base": self.dep("base", "2", root=True)}),
                        self.store, self.mo2, self.game, "Play", ask=lambda r: "replace")

    def test_edited_mod_upgrade_blocks(self):
        self.initial({"base": self.dep("base")})
        (self.mo2 / "mods/base/r6/scripts/base.reds").write_bytes(b"my edit")
        with self.assertRaisesRegex(PackError, "Locally edited mod"):
            prepare_add(self.manifest("upgrade", {"base": self.dep("base", "2")}),
                        self.store, self.mo2, self.game, "Play", ask=lambda r: "replace")

    def test_repeat_add_reuses_folders(self):
        self.initial({"base": self.dep("base")})
        incoming = self.manifest("addition", {"feature": self.dep("feature")})
        self.apply(prepare_add(incoming, self.store, self.mo2, self.game, "Play"))
        before = sorted(p.name for p in (self.mo2 / "mods").iterdir())
        self.apply(prepare_add(incoming, self.store, self.mo2, self.game, "Play"))
        self.assertEqual(before, sorted(p.name for p in (self.mo2 / "mods").iterdir()))

    def test_existing_manual_priority_is_preferred_after_resolving(self):
        self.initial({"one": self.dep("one"), "two": self.dep("two")})
        (self.profile / "modlist.txt").write_text("+two\n+one\n")
        plan = prepare_add(self.manifest("add", {"extra": self.dep("extra")}), self.store, self.mo2, self.game, "Play")
        self.apply(plan)
        from mo2_modlists.core import active_mods
        self.assertEqual([n for n in active_mods(self.profile) if n in ("two", "one", "extra")], ["two", "one", "extra"])

    def test_local_extra_file_cannot_be_silently_shadowed_by_new_mod(self):
        self.initial({"base": self.dep("base")})
        (self.mo2 / "mods/base/r6/scripts/extra.reds").write_bytes(b"custom")
        with self.assertRaisesRegex(PackError, "extra file conflicts"):
            prepare_add(self.manifest("add", {"extra": self.dep("extra")}), self.store, self.mo2, self.game, "Play")

    def test_profile_reconstructs_from_active_records_without_original_definition(self):
        self.initial({"feature": self.dep("feature", dependencies={"framework": self.dep("framework")})})
        (self.profile / "modlist.json").unlink()
        for recipe in self.root.glob("*.recipe.json"):
            recipe.unlink()
        plan = prepare_add(self.manifest("add", {"extra": self.dep("extra")}), self.store, self.mo2, self.game, "Play")
        self.assertIn("feature", json.loads(Path(plan["manifest"]).read_text())["extensions"]["packageRoot"]["dependencies"])
        self.apply(plan)
        self.assertEqual(sum(bool(p["outputs"]) for p in json.loads((self.profile / "modlist.lock.json").read_text())["packages"].values()), 3)

    def test_keep_unknown_unmanaged_and_adopt_matching_local_mod(self):
        self.profile.mkdir(parents=True)
        (self.profile / "modlist.txt").write_text("+Unknown\n+Known\n-disabled\n")
        unknown = self.mo2 / "mods/Unknown/custom.txt"
        unknown.parent.mkdir(parents=True)
        unknown.write_bytes(b"keep")
        known = self.mo2 / "mods/Known/r6/scripts/known.reds"
        known.parent.mkdir(parents=True)
        known.write_bytes(b"1")
        dependency = self.dep("known")
        def ask(request):
            if request["kind"] == "existing-source":
                return dependency if request["mod"] == "Known" else None
            self.fail(request)
        plan = prepare_add(self.manifest("add", {"extra": self.dep("extra")}), self.store, self.mo2, self.game, "Play", ask=ask)
        self.apply(plan)
        self.assertIn("+Unknown", (self.profile / "modlist.txt").read_text())
        self.assertIn("+Known", (self.profile / "modlist.txt").read_text())
        self.assertTrue((self.mo2 / ".modlists/installed/Known.json").is_file())
        self.assertEqual(unknown.read_bytes(), b"keep")
        from mo2_modlists.inspection import verify_installation
        self.assertTrue(verify_installation(Path(plan["manifest"]), Path(plan["lock"]), self.mo2, self.game, "Play")["valid"])

    def test_obsolete_transitive_root_restores_original_game_file(self):
        root = self.game / "bin/x64/framework.dll"
        root.write_bytes(b"game original")
        self.initial({"feature": self.dep("feature", dependencies={"framework": self.dep("framework", root=True)})})
        plan = prepare_add(self.manifest("add", {"feature": self.dep("feature", "2")}),
            self.store, self.mo2, self.game, "Play", ask=lambda r: "replace")
        self.assertEqual(len(plan["removeRoot"]), 1)
        self.apply(plan)
        self.assertEqual(root.read_bytes(), b"game original")

    def test_unmanaged_conflict_is_not_silently_overridden(self):
        self.profile.mkdir(parents=True)
        (self.profile / "modlist.txt").write_text("+Unknown\n")
        path = self.mo2 / "mods/Unknown/r6/scripts/extra.reds"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"different")
        with self.assertRaisesRegex(PackError, "Unmanaged mod conflicts"):
            prepare_add(self.manifest("add", {"extra": self.dep("extra")}), self.store, self.mo2, self.game, "Play", ask=lambda r: None)

    def test_cli_plan_and_apply(self):
        import subprocess
        import sys
        self.initial({"base": self.dep("base")})
        incoming = self.manifest("add", {"extra": self.dep("extra")})
        entry = "from unittest.mock import patch; from mo2_modlists.cli import main; " \
                "p=patch('mo2_modlists.core.game_running', return_value=False); p.start(); raise SystemExit(main())"
        args = [sys.executable, "-c", entry, "add", "--mo2", str(self.mo2), "--game", str(self.game),
                "--profile", "Play", "--cache", str(self.store.root), "--offline"]
        planned = subprocess.run([*args, "--manifest", str(incoming)], capture_output=True, text=True)
        self.assertEqual(planned.returncode, 0, planned.stderr)
        plan = json.loads(planned.stdout)
        applied = subprocess.run([*args, "--plan", plan["plan"], "--reviewed-sha256", plan["reviewedSha256"]], capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("+extra", (self.profile / "modlist.txt").read_text())

    def test_collections_merge_named_dependencies_and_instructions(self):
        from mo2_modlists.packages import merge_packages
        left_path = self.manifest('left-pack', {'left': self.dep('left'), 'one': self.dep('one')})
        right_path = self.manifest('right-pack', {'right': self.dep('right'), 'two': self.dep('two')})
        left, right = json.loads(left_path.read_text()), json.loads(right_path.read_text())
        left['mo2']['extensions'] = {'nexusCollection': {'schemaVersion': 1, 'rules': [], 'externalInstructions': 'left steps'}}
        right['mo2']['extensions'] = {'nexusCollection': {'schemaVersion': 1, 'rules': [], 'externalInstructions': 'right steps'}}
        merged = merge_packages(left, right, self.store, left_path, right_path)
        self.assertEqual(set(merged['dependencies']), {'left', 'one', 'right', 'two'})
        self.assertEqual(merged['mo2']['extensions']['nexusCollection']['externalInstructions'], 'left steps\n\nright steps')

    def test_hard_exit_during_publication_is_recovered_before_next_add(self):
        import subprocess
        import sys
        self.initial({"base": self.dep("base", root=True)})
        before = {p.name: p.read_bytes() for p in self.profile.iterdir() if p.is_file()}
        plan = prepare_add(self.manifest("upgrade", {"base": self.dep("base", "2", root=True)}),
            self.store, self.mo2, self.game, "Play", ask=lambda r: "replace")
        script = '''import json, os, sys
from pathlib import Path
from unittest.mock import patch
from mo2_modlists.acquisition import ArtifactStore
from mo2_modlists.install import import_lock
plan=json.loads(Path(sys.argv[1]).read_text())
def fail(phase):
    if phase == 'profile-file-written': os._exit(73)
with patch('mo2_modlists.core.game_running', return_value=False):
    import_lock(Path(plan['manifest']), Path(plan['lock']), ArtifactStore(Path(sys.argv[4])),
        Path(sys.argv[2]), Path(sys.argv[3]), 'Play', update=plan, allow_root=True, failure_hook=fail)
'''
        crashed = subprocess.run([sys.executable, "-c", script, str(Path(plan["manifest"]).with_name("update.json")),
            str(self.mo2), str(self.game), str(self.store.root)], capture_output=True, text=True)
        self.assertEqual(crashed.returncode, 73, crashed.stderr)
        prepare_add(self.manifest("next", {"extra": self.dep("extra")}), self.store, self.mo2, self.game, "Play")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.profile.iterdir() if p.is_file()})
        self.assertEqual((self.game / "bin/x64/base.dll").read_bytes(), b"1")

    def test_offline_add_with_cached_existing_archives_and_deleted_original_recipes(self):
        self.initial({"feature": self.dep("feature", dependencies={"framework": self.dep("framework")})})
        for file in [*self.root.glob("*.zip"), *self.root.glob("*.recipe.json")]:
            file.unlink()
        incoming = self.manifest("add", {"extra": self.dep("extra")})
        self.store.offline = True
        plan = prepare_add(incoming, self.store, self.mo2, self.game, "Play")
        self.apply(plan)
        self.assertEqual(sum(bool(p["outputs"]) for p in json.loads((self.profile / "modlist.lock.json").read_text())["packages"].values()), 3)


if __name__ == "__main__":
    unittest.main()
