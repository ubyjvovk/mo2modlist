from copy import deepcopy
import unittest

from mo2_modlists.acquisition import InputRequired
from mo2_modlists.core import PackError
from mo2_modlists.nexus import NexusProvider, recipe_from_metadata


class NexusMetadataTests(unittest.TestCase):
    def test_premium_download_uses_exact_file_and_keeps_credentials_off_transfer(self):
        from pathlib import Path
        calls, transfers = [], []
        source = {"type": "nexus", "game": "cyberpunk2077", "modId": 10, "fileId": 20}
        def request(url, **kwargs):
            calls.append((url, kwargs))
            return {"is_premium": True} if url.endswith("validate.json") else [{"URI": "https://cdn.example/My Mod%20UI.zip?token=ephemeral"}]
        provider = NexusProvider({"apikey": "test-secret"}, request=request)
        target = provider.download_archive(source, Path("cache"), transfer=lambda *args: transfers.append(args))
        self.assertTrue(calls[1][0].endswith("/mods/10/files/20/download_link.json"))
        self.assertEqual(transfers[0][0], "https://cdn.example/My%20Mod%20UI.zip?token=ephemeral")
        self.assertEqual(transfers[0][1], target)
        self.assertNotIn("ephemeral", str(target))
        self.assertEqual(len(transfers[0]), 3)

    def test_non_premium_download_requests_website_archive_without_transfer(self):
        from pathlib import Path
        provider = NexusProvider({}, request=lambda *a, **k: {"is_premium": False})
        with self.assertRaises(InputRequired) as error:
            provider.download_archive({"type": "nexus", "game": "cyberpunk2077", "modId": 10, "fileId": 20}, Path("cache"),
                                      transfer=lambda *a: self.fail("must not download"))
        self.assertEqual(error.exception.request["kind"], "nexus-archive")

    def fixture(self):
        source = {"type": "nexus", "game": "cyberpunk2077", "modId": 10, "fileId": 20}
        version = {"id": "200", "file": {"id": "100"}, "game_scoped_id": "20", "name": "Feature", "version": "1", "position": "1", "category": "main"}
        candidate = {"id": "201", "file": {"id": "101"}, "game_scoped_id": "21", "name": "Base", "version": "2", "position": "2", "category": "main"}
        responses = {
            "/games/cyberpunk2077/mod-file-versions/20": {"data": version},
            "/games/cyberpunk2077/mods/10": {"data": {"id": "1000"}},
            "/mods/1000/files": {"data": {"mod_files": [{"id": "100", "is_active": True}]}},
            "/mod-files/100/versions": {"data": {"versions": [version]}},
            "/mod-file-versions/200/dependencies": {"dependency_definitions": [{"id": "range-1", "ranges": []}], "dlc_dependency_definitions": []},
            "/mod-file-versions/200/dependencies/ranges/materialized": {"dependencies": [{"id": "range-1", "candidate_mod_files": [
                {"id": "101", "mod": {"game_scoped_id": "11", "game": {"domain_name": "cyberpunk2077"}}, "candidate_versions": [candidate]}]}]}}
        provider = NexusProvider({}, legacy=False, request=lambda url, **kwargs: deepcopy(responses[url.removeprefix("https://api.nexusmods.com/v3")]))
        return source, provider, responses

    def test_materialized_file_dependency_normalizes_to_exact_source(self):
        source, provider, _ = self.fixture()
        metadata = provider.metadata(source)
        recipe = recipe_from_metadata(metadata, "a" * 64)
        self.assertEqual(recipe["component"], "nexus:cyberpunk2077:lineage:100")
        self.assertEqual(recipe["dependencies"]["nexus-definition-range-1"]["source"],
            {"type": "nexus", "game": "cyberpunk2077", "modId": 11, "fileId": 21})

    def test_empty_new_metadata_does_not_erase_unknown_legacy_requirements(self):
        source, provider, responses = self.fixture()
        responses["/mod-file-versions/200/dependencies"]["dependency_definitions"] = []
        responses["/mod-file-versions/200/dependencies/ranges/materialized"]["dependencies"] = []
        metadata = provider.metadata(source)
        self.assertFalse(metadata["complete"])
        with self.assertRaises(InputRequired):
            recipe_from_metadata(metadata, "a" * 64)

    def test_legacy_page_requirements_are_normalized_and_preserved(self):
        source, provider, responses = self.fixture()
        responses["/mod-file-versions/200/dependencies"]["dependency_definitions"] = []
        responses["/mod-file-versions/200/dependencies/ranges/materialized"]["dependencies"] = []
        provider.legacy = True
        snapshot = {'gameId': '3333', 'legacyModRequirementsEnabled': True, 'modRequirements': {
            'nexusRequirements': {'totalCount': 1, 'nodes': [{'modId':'11','gameId':'3333',
                'externalRequirement':False,'notes':'Required'}]},
            'dlcRequirements': [{'gameExpansion': {'name':'Phantom Liberty'}}]}}
        provider.legacy_requirements = lambda s: deepcopy(snapshot)
        provider.current_versions = lambda s: [{'file':{'id':'101'}, 'id':'201', 'name':'Framework',
            'game_scoped_id':'21','category':'main','position':'1','version':'2','is_primary':False}]
        metadata = provider.metadata(source)
        self.assertEqual(metadata['legacySnapshot'], snapshot)
        self.assertEqual(metadata['provenance'], 'nexus-legacy-page-requirements')
        recipe = recipe_from_metadata(metadata, 'a'*64)
        self.assertEqual(recipe['dependencies']['nexus-definition-legacy-11']['source']['fileId'],21)
        self.assertEqual(recipe['game']['dlc'],['phantom-liberty'])
        snapshot['modRequirements']['nexusRequirements']['nodes'][0]['notes']='Optional'
        with self.assertRaises(InputRequired): provider.metadata(source)
        snapshot['modRequirements']['nexusRequirements']['nodes'][0]['notes']='Required'
        snapshot['modRequirements']['nexusRequirements']['totalCount']=2
        with self.assertRaisesRegex(PackError,'truncated'): provider.metadata(source)

    def test_disabled_legacy_flag_proves_empty_native_requirements(self):
        source, provider, responses = self.fixture()
        responses["/mod-file-versions/200/dependencies"]["dependency_definitions"] = []
        responses["/mod-file-versions/200/dependencies/ranges/materialized"]["dependencies"] = []
        provider.legacy=True
        provider.legacy_requirements=lambda s: {'legacyModRequirementsEnabled':False}
        self.assertTrue(provider.metadata(source)['complete'])

    def test_page_selection_enumerates_and_checks_explicit_choice(self):
        source, provider, responses = self.fixture()
        page = {key: value for key, value in source.items() if key != "fileId"}
        self.assertEqual(provider.exact_source(page), source)
        provider.cache.clear()
        variants = responses["/mod-files/100/versions"]["data"]["versions"]
        variants.append({**variants[0], "id": "202", "game_scoped_id": "22", "name": "Variant"})
        requests = []
        selected = provider.exact_source(page, ask=lambda request: requests.append(request) or 20)
        self.assertEqual(selected, source)
        self.assertEqual(requests[0]["choices"], [20, 22])
        with self.assertRaisesRegex(PackError, "Invalid Nexus file"):
            provider.exact_source(page, ask=lambda request: 999)

    def test_changed_range_snapshot_does_not_finalize(self):
        source, provider, responses = self.fixture()
        responses["/mod-file-versions/200/dependencies/ranges/materialized"]["dependencies"] = []
        with self.assertRaisesRegex(PackError, "changed during resolution"):
            provider.metadata(source)

    def test_verified_cp77_dlc_ids_become_game_constraints(self):
        source, provider, responses = self.fixture()
        responses["/mod-file-versions/200/dependencies"]["dlc_dependency_definitions"] = [
            {"id": "dlc-1", "dlc_targets": [{"dlc_id": "1"}]}]
        recipe = recipe_from_metadata(provider.metadata(source), "a" * 64)
        self.assertEqual(recipe["game"]["dlc"], ["phantom-liberty"])
