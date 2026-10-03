import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mo2_modlists.acquisition import ArtifactStore, InputRequired
from mo2_modlists.core import PackError, digest, json_digest
from mo2_modlists.install import import_lock, validate_lock
from mo2_modlists.inspection import verify_installation
from mo2_modlists.packages import validate_package, definitions, solve_packages
from mo2_modlists.planning import resolve_manifest
from mo2_modlists.remote_manifests import fetch_manifest


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'game'
        (self.game / 'bin/x64').mkdir(parents=True)
        (self.game / 'bin/x64/Cyberpunk2077.exe').write_bytes(b'game')
        self.mo2 = self.root / 'mo2'
        self.mo2.mkdir()
        self.store = ArtifactStore(self.root / 'cache')
        self.path, self.lock = self.root / 'package.json', self.root / 'lock.json'
        self.closed = patch('mo2_modlists.core.game_running', return_value=False)
        self.closed.start()
        self.addCleanup(self.closed.stop)

    def package(self, name, version='1.0.0', dependencies=None, files=None):
        config = {'schemaVersion': 1, 'game': {'id': 'cyberpunk2077', 'dlc': []}}
        if files is not None:
            archive = self.root / (name + '-' + version + '.zip')
            with zipfile.ZipFile(archive, 'w') as z:
                for path, data in files.items():
                    z.writestr(path, data)
            config['sources'] = [{'type': 'local-archive', 'path': archive.name}]
            config['integrity'] = 'sha256:' + digest(archive)
        return {'name': name, 'version': version, 'dependencies': dependencies or {}, 'mo2': config}

    def resolve(self, doc, **kwargs):
        self.path.write_text(json.dumps(doc))
        return resolve_manifest(self.path, self.store, self.game, self.lock, **kwargs)

    def test_single_mod_installs_itself_and_named_dependency_offline(self):
        base = self.package('framework', '2.1.4', files={'r6/scripts/base.reds': b'base'})
        mod = self.package('my-mod', dependencies={'framework': '~2.1.0'}, files={'archive/pc/mod/mod.archive': b'mod'})
        mod['mo2']['packages'] = [base]
        lock = self.resolve(mod)
        self.assertEqual({p['component']: p['version'] for p in lock['packages'].values()}, {'my-mod': '1.0.0', 'framework': '2.1.4'})
        validate_lock(lock, mod)
        result = import_lock(self.path, self.lock, self.store, self.mo2, self.game, 'Clean')
        self.assertEqual(len(result['mods']), 2)
        self.assertTrue(verify_installation(self.path, self.lock, self.mo2, self.game, 'Clean')['valid'])
        for archive in self.root.glob('*.zip'):
            archive.unlink()
        offline = ArtifactStore(self.store.root, offline=True, request=lambda *a: self.fail('network'))
        import_lock(self.path, self.lock, offline, self.mo2, self.game, 'Offline')

    def test_collection_and_mod_share_format_with_backtracking(self):
        lib1 = self.package('lib', '1.5.0')
        lib2 = self.package('lib', '2.0.0')
        a1 = self.package('feature', '1.0.0', {'lib': '^1.0.0'})
        a2 = self.package('feature', '1.1.0', {'lib': '^2.0.0'})
        root = self.package('collection', dependencies={'feature': '^1.0.0', 'lib': '^1.0.0'})
        root['mo2']['packages'] = [lib1, lib2, a1, a2]
        lock = self.resolve(root)
        selected = {p['component']: p['version'] for p in lock['packages'].values()}
        self.assertEqual(selected['feature'], '1.0.0')
        self.assertEqual(selected['lib'], '1.5.0')
        self.assertTrue(all(not p['outputs'] for p in lock['packages'].values()))

    def test_range_conflict_names_requirements_before_download(self):
        root = self.package('collection', dependencies={'lib': '~2.1.0', 'feature': '*'})
        root['mo2']['packages'] = [self.package('lib', '2.1.0'), self.package('feature', dependencies={'lib': '^3.0.0'})]
        with patch.object(self.store, 'acquire', side_effect=AssertionError('download before solve')):
            with self.assertRaisesRegex(PackError, 'lib.*2.1.0'):
                self.resolve(root)
        self.assertFalse(self.lock.exists())

    def test_prereleases_are_not_selected_by_stable_range(self):
        root = self.package('collection', dependencies={'lib': '^2.1.0'})
        root['mo2']['packages'] = [self.package('lib', '2.1.1'), self.package('lib', '2.2.0-beta.1')]
        records, token = definitions(root, self.path, self.store, lambda _: None)
        self.assertEqual(solve_packages(records, token)['lib']['version'], '2.1.1')

    def test_exact_prerelease_root_and_standard_npm_fields(self):
        root = self.package('@author/mod', '0.1.2-prototype')
        root.update(description='mod', license='MIT', repository={'type': 'git', 'url': 'https://example.org/repo.git'}, scripts={'test': 'echo ok'})
        lock = self.resolve(root)
        self.assertEqual(next(iter(lock['packages'].values()))['version'], '0.1.2-prototype')

    def test_conflicting_identity_and_unsupported_range_fail(self):
        root = self.package('collection')
        one, two = self.package('lib'), self.package('lib')
        two['dependencies'] = {'other': '*'}
        root['mo2']['packages'] = [one, two]
        with self.assertRaisesRegex(PackError, 'Conflicting definitions'):
            self.resolve(root)
        root['dependencies'] = {'lib': '~=2.1'}
        with self.assertRaisesRegex(PackError, 'npm version range'):
            validate_package(root)

    def test_modified_input_is_rejected_by_lock(self):
        root = self.package('mod')
        lock = self.resolve(root)
        root['version'] = '2.0.0'
        with self.assertRaisesRegex(PackError, 'differs from lock'):
            validate_lock(lock, root)

    def test_script_requires_explicit_trust_and_prepares_managed_outputs(self):
        script = "from pathlib import Path; Path('r6/scripts').mkdir(parents=True); Path('r6/scripts/generated.reds').write_text('generated')"
        root = self.package('scripted', files={'setup.py': script})
        root['scripts'] = {'install': '"' + sys.executable + '" setup.py'}
        root['mo2']['install'] = [{'from': 'r6', 'to': 'r6', 'class': 'mo2-overlay'}]
        with self.assertRaises(InputRequired) as error:
            self.resolve(root)
        self.assertEqual(error.exception.request['kind'], 'install-script')
        self.assertFalse(self.lock.exists())
        lock = self.resolve(root, ask=lambda r: r['approvalId'])
        self.assertEqual(next(iter(lock['packages'].values()))['outputs'][0]['path'], 'r6/scripts/generated.reds')
        import_lock(self.path, self.lock, ArtifactStore(self.store.root, offline=True), self.mo2, self.game, 'Scripted')
        self.assertEqual((self.mo2 / 'mods/scripted/r6/scripts/generated.reds').read_text(), 'generated')

    def test_script_failure_does_not_publish_a_plan_or_game_files(self):
        root = self.package('broken', files={'fail.py': 'raise SystemExit(7)'})
        root['scripts'] = {'install': '"' + sys.executable + '" fail.py'}
        with self.assertRaisesRegex(PackError, 'exit 7'):
            self.resolve(root, ask=lambda r: r['approvalId'])
        self.assertFalse(self.lock.exists())
        self.assertFalse((self.game / 'r6').exists())

    def test_remote_package_reference_snapshot_and_offline_reuse(self):
        root = self.package('collection', dependencies={'lib': '^1.0.0'})
        root['mo2']['packages'] = ['./lib.json']
        lib = self.package('lib')
        documents = {'https://example.org/package.json': root, 'https://example.org/lib.json': lib}
        def fetch(url):
            return copy.deepcopy(documents[url]), json_digest(documents[url]), url
        path = fetch_manifest('https://example.org/package.json', self.store.root, fetch=fetch)
        self.assertTrue(Path(json.loads(path.read_text())['mo2']['packages'][0]).is_file())
        lock = resolve_manifest(path, self.store, self.game, self.lock)
        self.assertEqual(len(lock['packages']), 2)
        self.assertEqual(fetch_manifest('https://example.org/package.json', self.store.root, offline=True), path)

    def test_remote_package_rejects_local_archive_sources(self):
        root = self.package('mod', files={'r6/script.reds': 'x'})
        with self.assertRaisesRegex(PackError, 'cannot read local'):
            fetch_manifest('https://example.org/package.json', self.store.root,
                           fetch=lambda u: (root, json_digest(root), u))

    def test_export_is_one_package_without_recipe_or_cache_references(self):
        from mo2_modlists.manifest import export_manifest, profile_sources
        root = self.package('mod', files={'r6/scripts/mod.reds': 'mod'})
        self.resolve(root)
        import_lock(self.path, self.lock, self.store, self.mo2, self.game, 'Export')
        source = profile_sources(self.mo2, 'Export')
        output = self.root / 'export.package.json'
        export_manifest(self.mo2, self.game, 'Export', output, {s['name']: s['dependency'] for s in source})
        exported = json.loads(output.read_text())
        self.assertIn('mo2', exported)
        self.assertNotIn('recipe', output.read_text())
        self.assertNotIn('package-plans', output.read_text())
        lock = self.root / 'export.lock.json'
        resolve_manifest(output, self.store, self.game, lock)
        import_lock(output, lock, self.store, self.mo2, self.game, 'Reimport')
        self.assertTrue(verify_installation(output, lock, self.mo2, self.game, 'Reimport')['valid'])

    def test_add_re_resolves_combined_named_constraints_and_installs(self):
        from mo2_modlists.profile_add import prepare_add
        lib1 = self.package('lib', '1.0.0', files={'r6/scripts/lib.reds': '1'})
        lib2 = self.package('lib', '1.1.0', files={'r6/scripts/lib.reds': '2'})
        base = self.package('base', dependencies={'lib': '^1.0.0'}, files={'r6/scripts/base.reds': 'base'})
        base['mo2']['packages'] = [lib1]
        self.resolve(base)
        import_lock(self.path, self.lock, self.store, self.mo2, self.game, 'Add')
        incoming = self.package('feature', dependencies={'lib': '^1.1.0'}, files={'r6/scripts/feature.reds': 'feature'})
        incoming['mo2']['packages'] = [lib2]
        path = self.root / 'feature.json'
        path.write_text(json.dumps(incoming))
        plan = prepare_add(path, self.store, self.mo2, self.game, 'Add')
        lock = json.loads(Path(plan['lock']).read_text())
        self.assertEqual(next(p for p in lock['packages'].values() if p['component'] == 'lib')['version'], '1.1.0')
        import_lock(Path(plan['manifest']), Path(plan['lock']), self.store, self.mo2, self.game, 'Add', update=plan)
        self.assertTrue(verify_installation(Path(plan['manifest']), Path(plan['lock']), self.mo2, self.game, 'Add')['valid'])

    def test_named_and_url_source_mirrors_share_identity(self):
        root = self.package('mod', files={'r6/scripts/mod.reds': 'mod'})
        local_source = root['mo2']['sources'][0]
        github = {'type': 'github-release', 'repository': 'author/mod', 'tag': 'v1.0.0', 'asset': 'mod.zip'}
        root['mo2']['sources'].insert(0, github)
        self.store.request = lambda u: (_ for _ in ()).throw(OSError('provider unavailable'))
        lock = self.resolve(root)
        selected = next(iter(lock['packages'].values()))
        self.assertEqual(selected['component'], 'mod')
        self.assertEqual(selected['artifact']['source']['type'], 'local-archive')

    def test_add_prefers_installed_dependency_and_explicit_upgrade_replaces_it(self):
        from mo2_modlists.profile_add import prepare_add
        from mo2_modlists.core import active_mods
        lib1 = self.package('amm', '2.1.0', files={'r6/scripts/amm.reds': 'old'})
        lib2 = self.package('amm', '2.1.1', files={'r6/scripts/amm.reds': 'new'})
        base = self.package('base', dependencies={'amm': '~2.1.0'}, files={'r6/scripts/base.reds': 'base'})
        base['mo2']['packages'] = [lib1]
        self.resolve(base)
        import_lock(self.path, self.lock, self.store, self.mo2, self.game, 'Reuse')
        before = set(active_mods(self.mo2 / 'profiles/Reuse'))
        feature = self.package('feature', dependencies={'amm': '~2.1.0'}, files={'r6/scripts/feature.reds': 'feature'})
        feature['mo2']['packages'] = [lib2]
        path = self.root / 'feature.json'
        path.write_text(json.dumps(feature))
        plan = prepare_add(path, self.store, self.mo2, self.game, 'Reuse')
        lock = json.loads(Path(plan['lock']).read_text())
        amm = next(k for k, p in lock['packages'].items() if p['component'] == 'amm')
        self.assertEqual(lock['packages'][amm]['version'], '2.1.0')
        self.assertIn(plan['reuse'][amm], before)
        self.assertFalse(plan['replaced'])
        upgraded = prepare_add(path, self.store, self.mo2, self.game, 'Reuse', upgrade=True)
        new_lock = json.loads(Path(upgraded['lock']).read_text())
        self.assertEqual(next(p['version'] for p in new_lock['packages'].values() if p['component'] == 'amm'), '2.1.1')
        self.assertEqual(len(upgraded['replaced']), 1)
        import_lock(Path(plan['manifest']), Path(plan['lock']), self.store, self.mo2, self.game, 'Reuse', update=plan)
        enabled = active_mods(self.mo2 / 'profiles/Reuse')
        self.assertEqual(sum(n.startswith('amm') for n in enabled), 1)
        repeated = prepare_add(path, self.store, self.mo2, self.game, 'Reuse')
        self.assertFalse(repeated['replaced'])
        self.assertFalse(repeated['added'])

    def test_add_adopts_manual_dependency_by_archive_and_preserves_folder(self):
        from mo2_modlists.profile_add import prepare_add
        from mo2_modlists.core import active_mods
        lib = self.package('appearance-menu-mod', '2.1.0', files={'r6/scripts/amm.reds': 'amm'})
        feature = self.package('feature', dependencies={'appearance-menu-mod': '~2.1.0'}, files={'r6/scripts/feature.reds': 'feature'})
        feature['mo2']['packages'] = [lib]
        self.path.write_text(json.dumps(feature))
        profile = self.mo2 / 'profiles/Manual'
        profile.mkdir(parents=True)
        (profile / 'modlist.txt').write_text('+AMM manually installed\n')
        folder = self.mo2 / 'mods/AMM manually installed/r6/scripts'
        folder.mkdir(parents=True)
        (folder / 'amm.reds').write_text('amm')
        source = {'source': {'type': 'local-archive', 'path': str(self.root / lib['mo2']['sources'][0]['path'])},
                  'integrity': lib['mo2']['integrity']}
        plan = prepare_add(self.path, self.store, self.mo2, self.game, 'Manual', ask=lambda request: source)
        self.assertIn('AMM manually installed', plan['reuse'].values())
        self.assertFalse(plan['unmanaged'])
        import_lock(Path(plan['manifest']), Path(plan['lock']), self.store, self.mo2, self.game, 'Manual', update=plan)
        enabled = active_mods(profile)
        self.assertIn('AMM manually installed', enabled)
        self.assertNotIn('appearance-menu-mod', enabled)

        newer = self.package('appearance-menu-mod', '2.1.1', files={'r6/scripts/amm.reds': 'new amm'})
        extra = self.package('extra', dependencies={'appearance-menu-mod': '~2.1.0'}, files={'r6/scripts/extra.reds': 'extra'})
        extra['mo2']['packages'] = [newer]
        path = self.root / 'extra.json'
        path.write_text(json.dumps(extra))
        upgraded = prepare_add(path, self.store, self.mo2, self.game, 'Manual', upgrade=True)
        self.assertIn('AMM manually installed', upgraded['replaced'])
        import_lock(Path(upgraded['manifest']), Path(upgraded['lock']), self.store, self.mo2, self.game, 'Manual', update=upgraded)
        self.assertNotIn('AMM manually installed', active_mods(profile))
        self.assertEqual((folder / 'amm.reds').read_text(), 'amm')

    def test_public_boundaries_reject_source_only_documents(self):
        import subprocess
        from mo2_modlists.profile_add import prepare_add
        doc = {'schemaVersion': 1, 'name': 'old input', 'game': {'id': 'cyberpunk2077', 'dlc': []}, 'dependencies': {}}
        self.path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(PackError, 'Expected package.json'):
            resolve_manifest(self.path, self.store, self.game, self.lock)
        with self.assertRaisesRegex(PackError, 'Expected package.json'):
            prepare_add(self.path, self.store, self.mo2, self.game, 'Unused')
        with self.assertRaisesRegex(PackError, 'Expected package.json'):
            fetch_manifest('https://example.test/package.json', self.store.root,
                           fetch=lambda url: (doc, json_digest(doc), url))
        for args in (['validate', str(self.path)], ['migrate'], ['export', '--legacy']):
            result = subprocess.run([sys.executable, '-m', 'mo2_modlists.cli', *args], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.lock.exists())

    def test_add_captures_manual_mod_enabled_after_managed_install(self):
        from mo2_modlists.profile_add import prepare_add
        root = self.package('base', files={'r6/scripts/base.reds': 'base'})
        self.resolve(root)
        import_lock(self.path, self.lock, self.store, self.mo2, self.game, 'Mixed')
        manual = self.package('amm', '2.1.0', files={'r6/scripts/amm.reds': 'amm'})
        profile = self.mo2 / 'profiles/Mixed'
        with (profile / 'modlist.txt').open('a') as stream:
            stream.write('+My AMM\n')
        folder = self.mo2 / 'mods/My AMM/r6/scripts'
        folder.mkdir(parents=True)
        (folder / 'amm.reds').write_text('amm')
        feature = self.package('feature', dependencies={'amm': '~2.1.0'})
        feature['mo2']['packages'] = [manual]
        path = self.root / 'feature.json'
        path.write_text(json.dumps(feature))
        source = {'source': {'type': 'local-archive', 'path': str(self.root / manual['mo2']['sources'][0]['path'])},
                  'integrity': manual['mo2']['integrity']}
        plan = prepare_add(path, self.store, self.mo2, self.game, 'Mixed', ask=lambda request: source)
        lock = json.loads(Path(plan['lock']).read_text())
        self.assertIn('My AMM', plan['reuse'].values())
        base = next(p for p in lock['packages'].values() if p['component'] == 'base')
        self.assertEqual(base['recipe']['document']['extensions']['package']['dependencies'], {})
        self.assertEqual(sum(p['component'] == 'amm' for p in lock['packages'].values()), 1)

    def test_provider_conversion_publishes_the_same_package_format(self):
        from mo2_modlists.packages import compile_package
        from mo2_modlists.collections import write_collection_manifest
        root = self.package('provider-mod', files={'r6/scripts/provider.reds': 'provider'})
        self.path.write_text(json.dumps(root))
        generated = compile_package(self.path, self.store, game=self.game)
        destination = self.root / 'converted-package.json'
        write_collection_manifest({'pending': [], 'manifest': json.loads(generated.read_text())}, destination,
                                  store=self.store, game=self.game)
        package = validate_package(json.loads(destination.read_text()))
        self.assertIn('provider-mod', package['dependencies'])
        converted_lock = resolve_manifest(destination, self.store, self.game, self.root / 'converted.lock.json')
        self.assertTrue(any(p['component'] == 'provider-mod' for p in converted_lock['packages'].values()))

    def test_tampered_named_range_fails_locked_validation(self):
        root = self.package('collection', dependencies={'lib': '^1.0.0'})
        root['mo2']['packages'] = [self.package('lib')]
        lock = self.resolve(root)
        lock['resolvedManifest']['extensions']['packageDefinitions']['collection']['dependencies']['lib'] = '^2.0.0'
        lock['manifestSha256'] = json_digest(lock['resolvedManifest'])
        with self.assertRaisesRegex(PackError, 'violates named dependency'):
            validate_lock(lock, root)


if __name__ == '__main__':
    unittest.main()
