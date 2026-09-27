import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mo2_modlists.acquisition import ArtifactStore, InputRequired
from mo2_modlists.core import PackError, digest, game_identity, game_running
from mo2_modlists.games import nexus_dlcs
from mo2_modlists.inspection import verify_installation
from mo2_modlists.install import import_lock, validate_lock
from mo2_modlists.manifest import export_manifest, profile_sources
from mo2_modlists.newvegas import profile_plugins, read_header
from mo2_modlists.planning import resolve_manifest
from mo2_modlists.url_manifest import nexus_url_kind
from mo2_modlists.collections import collection_reference


def plugin(*masters, master=False):
    records = b"".join(b"MAST" + struct.pack("<H", len(m.encode()) + 1) + m.encode() + b"\0" for m in masters)
    return b"TES4" + struct.pack("<IIIII", len(records), int(master), 0, 0, 0) + records


class NewVegasTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.game, self.mo2 = self.root / "game", self.root / "mo2"
        (self.game / "Data").mkdir(parents=True)
        self.mo2.mkdir()
        (self.game / "FalloutNV.exe").write_bytes(b"fnv")
        (self.game / "Data/FalloutNV.esm").write_bytes(plugin(master=True))
        self.manifest, self.lockfile = self.root / "modlist.json", self.root / "lock.json"
        self.store = ArtifactStore(self.root / "cache")
        closed = patch("mo2_modlists.core.game_running", return_value=False)
        closed.start()
        self.addCleanup(closed.stop)

    def dep(self, name, entries, **extra):
        archive = self.root / (name + ".zip")
        with zipfile.ZipFile(archive, "w") as z:
            for filename, data in entries.items():
                z.writestr(filename, data)
        recipe = self.root / (name + ".recipe.json")
        recipe.write_text(json.dumps({"schemaVersion": 1, "component": name, "version": "1", "revision": "1",
            "artifact": "sha256:" + digest(archive), "dependencies": {}, **extra}))
        return {"source": {"type": "local-archive", "path": archive.name}, "recipe": recipe.name}

    def resolve(self, deps, **extra):
        self.manifest.write_text(json.dumps({"schemaVersion": 1, "name": "NV", "game": {"id": "newvegas", "dlc": []},
                                            "dependencies": deps, **extra}))
        return resolve_manifest(self.manifest, self.store, self.game, self.lockfile)

    def test_data_mount_plugin_order_export_offline_and_verify(self):
        dep = self.dep("Mod", {"Data/Feature.esp": plugin("FalloutNV.esm", "Base.esm"),
                               "Data/Base.esm": plugin("FalloutNV.esm", master=True),
                               "Data/textures/test.dds": b"texture"})
        lock = self.resolve({"mod": dep})
        self.assertEqual(lock["plugins"], ["FalloutNV.esm", "Base.esm", "Feature.esp"])
        self.assertEqual(lock["adapterVersion"], "fnv-1")
        first = import_lock(self.manifest, self.lockfile, self.store, self.mo2, self.game, "First")
        self.assertEqual((self.mo2 / "mods/mod/textures/test.dds").read_bytes(), b"texture")
        self.assertFalse((self.mo2 / "mods/mod/Data").exists())
        self.assertTrue(verify_installation(self.manifest, self.lockfile, self.mo2, self.game, "First")["valid"])
        output = self.root / "export.json"
        sources = profile_sources(self.mo2, "First", game_id="newvegas")
        export_manifest(self.mo2, self.game, "First", output, {x["name"]: x["dependency"] for x in sources})
        self.assertEqual(json.loads(output.read_text())["plugins"], lock["plugins"])
        for p in self.root.glob("*.zip"):
            p.unlink()
        (self.root / "Mod.recipe.json").unlink()
        offline = ArtifactStore(self.root / "cache", offline=True)
        import_lock(self.manifest, self.lockfile, offline, self.mo2, self.game, "Second")
        self.assertTrue(verify_installation(self.manifest, self.lockfile, self.mo2, self.game, "Second")["valid"])
        profile = Path(first["profile"])
        (profile / "plugins.txt").write_text("FalloutNV.esm\nBase.esm\n")
        self.assertFalse(verify_installation(self.manifest, self.lockfile, self.mo2, self.game, "First")["valid"])

    def test_missing_master_blocks_resolution(self):
        dep = self.dep("Bad", {"Bad.esp": plugin("Missing.esm")})
        with self.assertRaisesRegex(PackError, "missing or disabled masters"):
            self.resolve({"bad": dep})
        self.assertFalse(self.lockfile.exists())

    def test_explicit_order_and_disabled_plugin_are_preserved(self):
        dep = self.dep("Pack", {"A.esp": plugin("FalloutNV.esm"), "B.esp": plugin("FalloutNV.esm"),
                                 "Disabled.esp": plugin("Missing.esm")})
        desired = ["FalloutNV.esm", "B.esp", "A.esp"]
        lock = self.resolve({"pack": dep}, plugins=desired)
        self.assertEqual(lock["plugins"], desired)
        import_lock(self.manifest, self.lockfile, self.store, self.mo2, self.game, "Explicit")
        self.assertEqual(profile_plugins(self.mo2 / "profiles/Explicit"), desired)

    def test_explicit_order_before_master_rejected(self):
        dep = self.dep("Pack", {"A.esp": plugin("B.esp"), "B.esp": plugin("FalloutNV.esm")})
        with self.assertRaisesRegex(PackError, "before a required master"):
            self.resolve({"pack": dep}, plugins=["FalloutNV.esm", "A.esp", "B.esp"])

    def test_cycle_rejected(self):
        dep = self.dep("Cycle", {"A.esp": plugin("B.esp"), "B.esp": plugin("A.esp")})
        with self.assertRaisesRegex(PackError, "Cyclic"):
            self.resolve({"pack": dep})

    def test_root_loader_requires_recipe_and_root_review(self):
        dep = self.dep("Loader", {"nvse_loader.exe": b"loader"})
        with self.assertRaises(InputRequired):
            self.resolve({"loader": dep})
        recipe = self.root / "Loader.recipe.json"
        doc = json.loads(recipe.read_text())
        doc["mappings"] = [{"from": "nvse_loader.exe", "to": "nvse_loader.exe", "class": "game-root"}]
        recipe.write_text(json.dumps(doc))
        self.resolve({"loader": dep})
        with self.assertRaisesRegex(PackError, "Review and allow"):
            import_lock(self.manifest, self.lockfile, self.store, self.mo2, self.game, "Root")
        import_lock(self.manifest, self.lockfile, self.store, self.mo2, self.game, "Root", allow_root=True)
        self.assertEqual((self.game / "nvse_loader.exe").read_bytes(), b"loader")

    def test_data_metadata_collision_rejected(self):
        with self.assertRaisesRegex(PackError, "management metadata"):
            self.resolve({"bad": self.dep("Bad", {"Data/meta.ini": b"bad"})})

    def test_data_relative_overwrite_conflict(self):
        self.resolve({"texture": self.dep("Texture", {"textures/a.dds": b"mod"})})
        (self.mo2 / "overwrite/textures").mkdir(parents=True)
        (self.mo2 / "overwrite/textures/a.dds").write_bytes(b"different")
        with self.assertRaisesRegex(PackError, "overwrite conflicts"):
            import_lock(self.manifest, self.lockfile, self.store, self.mo2, self.game, "Blocked")

    def test_wrong_game_target_rejected(self):
        self.manifest.write_text(json.dumps({"schemaVersion": 1, "name": "CP", "game": {"id": "cyberpunk2077", "dlc": []}, "dependencies": {}}))
        with self.assertRaisesRegex(PackError, "Manifest game differs"):
            resolve_manifest(self.manifest, self.store, self.game, self.lockfile)

    def test_tampered_automatic_plugin_lock_rejected(self):
        lock = self.resolve({"mod": self.dep("Mod", {"Feature.esp": plugin("FalloutNV.esm")})})
        lock["plugins"] = ["FalloutNV.esm"]
        self.lockfile.write_text(json.dumps(lock))
        with self.assertRaisesRegex(PackError, "Plugin order differs"):
            import_lock(self.manifest, self.lockfile, self.store, self.mo2, self.game, "Tampered")
        self.assertFalse((self.mo2 / "profiles/Tampered").exists())

    def test_nexus_dlc_ids_and_urls(self):
        for name in ("DeadMoney.esm", "CaravanPack.esm", "ClassicPack.esm", "MercenaryPack.esm", "TribalPack.esm"):
            (self.game / "Data" / name).write_bytes(plugin("FalloutNV.esm", master=True))
        self.assertEqual(nexus_dlcs(game_identity(self.game)), {"1", "6"})
        self.assertEqual(nexus_url_kind("https://www.nexusmods.com/newvegas/mods/62552"), "mod")
        self.assertEqual(collection_reference("https://www.nexusmods.com/games/newvegas/collections/abc")["game"], "newvegas")

    def test_header_rejects_truncation(self):
        with self.assertRaisesRegex(PackError, "Truncated"):
            read_header(io.BytesIO(plugin("FalloutNV.esm")[:-1]), "bad.esp")

    def test_extended_subrecord_preserves_following_masters(self):
        original = plugin("FalloutNV.esm", master=True)
        extended = b"XXXX" + struct.pack("<HI", 4, 70000) + b"ONAM\x00\x00" + bytes(70000)
        data = bytearray(original[:24] + extended + original[24:])
        struct.pack_into("<I", data, 4, len(data) - 24)
        self.assertEqual(read_header(io.BytesIO(data), "large.esm"), (True, ["falloutnv.esm"]))
        struct.pack_into("<I", data, 30, 100000)
        with self.assertRaisesRegex(PackError, "Truncated"):
            read_header(io.BytesIO(data), "bad.esm")


if __name__ == "__main__":
    unittest.main()
