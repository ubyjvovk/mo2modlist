import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from mo2_modlists.acquisition import InputRequired
from mo2_modlists.collections import collection_reference, convert_collection, read_collection, write_collection_plan as write_collection_manifest


class CollectionTests(unittest.TestCase):
    def test_bundled_directory_becomes_reproducible_archive(self):
        from mo2_modlists.collections import bundled_dependency
        from mo2_modlists.core import digest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "pack.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("collection.json", json.dumps(self.fixture()))
                output.writestr("bundled/Settings (v1)/NVSE/Plugins/NVTF.ini", "[Main]\nx=1\n")
            mod = {"source": {"fileExpression": "Settings (v1)"}}
            first = bundled_dependency(archive, mod, root / "cache")
            second = bundled_dependency(archive, mod, root / "cache")
            self.assertEqual(first, second)
            path = Path(first["source"]["path"])
            self.assertEqual(first["integrity"], "sha256:" + digest(path))
            with zipfile.ZipFile(path) as output:
                self.assertEqual(output.namelist(), ["NVSE/Plugins/NVTF.ini"])

    def test_reviewed_external_handoff_is_bound_to_original_document(self):
        from mo2_modlists.core import json_digest
        document = self.fixture()
        document["tools"] = [{"name": "Optional tool", "exe": "tool.exe"}]
        decision = {"_collection": {"reviews": {"tools": {"collectionSha256": json_digest(document),
            "sha256": json_digest(document["tools"]), "note": "Excluded optional tool; do not execute."}}}}
        draft = convert_collection(document, decisions=decision)
        self.assertTrue(draft["complete"])
        self.assertIn("tools", draft["manifest"]["extensions"]["nexusCollection"]["reviewedHandoffs"])
        document["tools"][0]["exe"] = "changed.exe"
        self.assertFalse(convert_collection(document, decisions=decision)["complete"])

    def test_file_expression_requires_strong_identity(self):
        from mo2_modlists.collections import match_reference
        mod = self.fixture()["mods"][0]
        mod["source"].update(md5="a" * 32, logicalFilename="Base")
        self.assertEqual(match_reference({"fileExpression": "Base-*", "fileMD5": "a" * 32}, {"base": mod}), "base")
        self.assertIsNone(match_reference({"fileExpression": "Base-*", "logicalFileName": "Base"}, {"base": mod}))

    def fixture(self):
        return {"info": {"name": "CP77 fixture", "domainName": "cyberpunk2077"}, "mods": [
            {"name": "Base", "version": "1", "optional": False, "domainName": "cyberpunk2077",
             "source": {"type": "nexus", "modId": 1, "fileId": 2, "updatePolicy": "exact"}}
        ], "modRules": []}

    def test_exact_file_collection_converts_from_package(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "collection.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("collection.json", json.dumps(self.fixture()))
            draft = convert_collection(read_collection(archive))
            self.assertTrue(draft["complete"])
            self.assertEqual(draft["manifest"]["dependencies"]["mod-0001"]["source"]["fileId"], 2)
            destination = Path(directory) / "modlist.json"
            write_collection_manifest(draft, destination)
            self.assertTrue(destination.exists())

    def test_profile_recommendation_is_advisory_and_preserved(self):
        for recommendation in (True, False):
            collection = self.fixture()
            collection["collectionConfig"] = {"recommendNewProfile": recommendation}
            draft = convert_collection(collection)
            self.assertTrue(draft["complete"])
            self.assertEqual(draft["manifest"]["extensions"]["nexusCollection"]["collectionConfig"],
                             collection["collectionConfig"])

    def test_unknown_or_malformed_collection_config_requires_review(self):
        for config in (None, [], "", {"recommendNewProfile": 1}, {"recommendNewProfile": "false"},
                       {"futureOption": False}):
            collection = self.fixture()
            collection["collectionConfig"] = config
            draft = convert_collection(collection)
            self.assertFalse(draft["complete"])
            self.assertIn({"kind": "collection-extension", "field": "collectionConfig",
                           "message": "Unknown Collection configuration requires review"}, draft["pending"])

    def test_optional_and_installer_data_remain_pending(self):
        collection = self.fixture()
        collection["mods"][0].update(optional=True, choices={"fomod": "selected"}, patches={"config.ini": "patch"})
        draft = convert_collection(collection)
        self.assertEqual(draft["pending"][0]["kind"], "optional-mod")
        draft = convert_collection(collection, decisions={"mod-0001": {"include": True}})
        self.assertEqual(draft["pending"][0]["kind"], "installer-data")
        with self.assertRaises(InputRequired):
            write_collection_manifest(draft, Path("must-not-exist.json"))

    def test_filtered_preview_and_rules_are_not_silently_lost(self):
        collection = self.fixture()
        del collection["modRules"]
        self.assertFalse(convert_collection(collection)["complete"])
        collection["modRules"] = [{"type": "after", "source": {}, "reference": {}}]
        self.assertEqual(convert_collection(collection)["pending"][0]["kind"], "collection-rules")

    def test_url_and_nxm_pin_revision(self):
        for url in ("nxm://cyberpunk2077/collections/abc123/revisions/4", "https://www.nexusmods.com/games/cyberpunk2077/collections/abc123?revision=4"):
            self.assertEqual(collection_reference(url), {"game": "cyberpunk2077", "slug": "abc123", "revision": 4})

    def test_exact_collection_order_and_dependencies_survive_conversion(self):
        from mo2_modlists.planning import priority_for
        collection = self.fixture()
        collection["mods"].append({"name": "Addon", "version": "1", "optional": False, "domainName": "cyberpunk2077",
            "source": {"type": "nexus", "modId": 1, "fileId": 3}})
        left = {"repo": {"repository": "nexus", "gameId": "cyberpunk2077", "modId": "1", "fileId": "2"}}
        right = {"repo": {"repository": "nexus", "gameId": "cyberpunk2077", "modId": "1", "fileId": "3"}}
        collection["modRules"] = [{"type": "after", "source": right, "reference": left},
            {"type": "requires", "source": right, "reference": left}]
        draft = convert_collection(collection)
        self.assertTrue(draft["complete"])
        metadata = draft["manifest"]["extensions"]["nexusCollection"]
        packages = {"base": {"outputs": [{"path": "r6/test.reds", "sha256": "a", "class": "mo2-overlay"}]},
                    "addon": {"outputs": [{"path": "r6/test.reds", "sha256": "b", "class": "mo2-overlay"}]}}
        self.assertEqual(priority_for(packages, {"mod-0001": "base", "mod-0002": "addon"}, [], collection=metadata), ["addon", "base"])
        collection["mods"][0]["optional"] = True
        draft = convert_collection(collection, decisions={"mod-0001": {"include": False}})
        self.assertIn("required-mod", [p["kind"] for p in draft["pending"]])

    def test_revision_query_pins_nonnullable_revision_and_propagates_access_requirements(self):
        from mo2_modlists.collections import fetch_collection
        calls = []
        def request(url, **kwargs):
            calls.append(kwargs["data"])
            return {"errors": [{"extensions": {"code": "ADULT_CONTENT_BLOCKED"}}], "data": None}
        with self.assertRaises(InputRequired) as error:
            fetch_collection("nxm://cyberpunk2077/collections/abc123/revisions/4", Path("cache"), request=request)
        self.assertIn("$revision: Int!", calls[0]["query"])
        self.assertEqual(error.exception.request["providerCodes"], ["ADULT_CONTENT_BLOCKED"])

    def test_prepared_archive_handoff_must_bind_to_exact_collection_instructions(self):
        from mo2_modlists.core import json_digest
        collection = self.fixture()
        collection["mods"][0].update(choices={"option": "A"}, patches={"r6/config.ini": "AABBCCDD"})
        decision = {"source": {"type": "local-archive", "path": "prepared.zip"}, "recipe": "prepared.recipe.json",
            "integrity": "sha256:" + "a" * 64,
            "handoff": {"method": "prepared-archive", "collectionSha256": json_digest(collection),
                "handled": ["choices", "patches"], "note": "Applied option A and author patches, then archived the installed output."}}
        draft = convert_collection(collection, decisions={"mod-0001": decision})
        self.assertTrue(draft["complete"])
        self.assertEqual(draft["manifest"]["extensions"]["nexusCollection"]["manualHandoffs"]["mod-0001"]["method"], "prepared-archive")
        collection["mods"][0]["choices"]["option"] = "B"
        self.assertFalse(convert_collection(collection, decisions={"mod-0001": decision})["complete"])

    def test_bundled_source_is_extracted_hashed_and_used_without_losing_provenance(self):
        import io
        from mo2_modlists.collections import bundled_dependency
        from mo2_modlists.core import digest
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w") as archive:
                archive.writestr("r6/test.ini", "config")
            collection = self.fixture()
            collection["mods"][0]["source"] = {"type": "bundle", "fileExpression": "bundle.zip"}
            package = root / "collection.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("collection.json", json.dumps(collection))
                archive.writestr("bundled/bundle.zip", inner.getvalue())
            dependency = bundled_dependency(package, collection["mods"][0], root / "cache")
            archive = Path(dependency["source"]["path"])
            self.assertEqual(dependency["integrity"], "sha256:" + digest(archive))
            draft = convert_collection(collection, decisions={"mod-0001": dependency})
            self.assertTrue(draft["complete"])
            self.assertEqual(draft["manifest"]["dependencies"]["mod-0001"]["extensions"]["nexusBundledArtifact"]["member"], "bundled/bundle.zip")


if __name__ == "__main__":
    unittest.main()
