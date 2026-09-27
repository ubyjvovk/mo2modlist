import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from mo2_modlists.core import PackError
from mo2_modlists.acquisition import InputRequired
from mo2_modlists.url_manifest import manifest_from_url, nexus_url_kind


class URLManifestTests(unittest.TestCase):
    def test_mod_pins_root_and_direct_requirements_without_flattening(self):
        source = lambda mod, file: dict(type='nexus', game='cyberpunk2077', modId=mod, fileId=file)
        root, child = source(10, 20), source(30, 40)
        calls = []
        def metadata(ref):
            calls.append(ref)
            return {'source': ref, 'complete': True, 'displayName': 'Root' if ref == root else 'Framework',
                'version': {'file': {'id': str(ref['modId'])}, 'version': '1'},
                'raw': {'dlc_dependency_definitions': [{'dlc_targets': [{'dlc_id': '1'}]}]},
                'materialized': {'dependencies': [{'id': 'requirement', 'candidate_mod_files': [{
                    'id': '30', 'mod': {'game_scoped_id': '30', 'game': {'domain_name': 'cyberpunk2077'}},
                    'candidate_versions': [{'id': '40', 'category': 'main', 'game_scoped_id': '40', 'position': '1'}]}]}]}}
        provider = SimpleNamespace(exact_source=lambda s,a: root if s['modId']==10 else child, metadata=metadata)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'modlist.json'
            doc = manifest_from_url('https://www.nexusmods.com/games/cyberpunk2077/mods/10', output, provider=provider)
            self.assertEqual(doc['dependencies'], {'Root': {'source': root}, 'Framework': {'source': child}})
            self.assertEqual(doc['game']['dlc'], ['phantom-liberty'])
            self.assertEqual(calls, [root, child])
            self.assertEqual([p.name for p in Path(temp).iterdir()], ['modlist.json'])
            with self.assertRaises(PackError):
                manifest_from_url('https://www.nexusmods.com/cyberpunk2077/mods/10', output, provider=provider)

    def test_unknown_metadata_does_not_publish_a_partial_manifest(self):
        provider = SimpleNamespace(exact_source=lambda s,a: {**s, 'fileId': 20}, metadata=lambda s: {'source': s, 'complete': False})
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'modlist.json'
            with self.assertRaises(InputRequired):
                manifest_from_url('https://www.nexusmods.com/cyberpunk2077/mods/10', output, provider=provider)
            self.assertFalse(output.exists())

    def test_collection_uses_full_package_conversion(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            package=folder/'collection.json'
            package.write_text(json.dumps({'info': {'name': 'Pack', 'domainName': 'cyberpunk2077'}, 'modRules': [],
                'mods': [{'name':'One','version':'1','optional':False,'domainName':'cyberpunk2077',
                    'source':{'type':'nexus','modId':10,'fileId':20}}]}))
            def fetch(url, cache, **kwargs): return package, None
            doc=manifest_from_url('https://www.nexusmods.com/games/cyberpunk2077/collections/abc',
                folder/'modlist.json',cache=folder/'cache',fetch=fetch)
            self.assertEqual(next(iter(doc['dependencies'].values()))['source']['fileId'],20)

    def test_rejects_foreign_or_authenticated_urls(self):
        for url in ['https://evil.example/cyberpunk2077/mods/10',
            'https://www.nexusmods.com/skyrim/mods/10',
            'https://www.nexusmods.com/cyberpunk2077/mods/10?key=secret']:
            with self.assertRaises(PackError): nexus_url_kind(url)
