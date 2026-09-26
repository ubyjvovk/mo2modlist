import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from mo2_modlists.acquisition import InputRequired
from mo2_modlists.collections import collection_reference, convert_collection, read_collection, write_collection_manifest


class CollectionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
