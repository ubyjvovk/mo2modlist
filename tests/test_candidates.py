import unittest

from mo2_modlists.acquisition import InputRequired
from mo2_modlists.candidates import solve_nexus
from mo2_modlists.core import PackError, json_digest


class World:
    """Explicitly complete metadata fixture for testing graph solving only."""
    def __init__(self):
        self.nodes = {}

    def add(self, file_id, lineage, position, groups=()):
        source = {"type": "nexus", "game": "cyberpunk2077", "modId": lineage, "fileId": file_id}
        self.nodes[file_id] = (source, lineage, position, groups)
        return source

    def metadata(self, source):
        _, lineage, position, groups = self.nodes[source["fileId"]]
        definitions = []
        for index, choices in enumerate(groups):
            by_lineage = {}
            for choice in choices:
                selected, file_lineage, file_position, _ = self.nodes[choice]
                file = by_lineage.setdefault(file_lineage, {"id": str(file_lineage), "mod": {
                    "game_scoped_id": str(file_lineage), "game": {"domain_name": "cyberpunk2077"}}, "candidate_versions": []})
                file["candidate_versions"].append({"id": str(choice), "game_scoped_id": str(choice), "version": str(file_position),
                    "position": str(file_position), "category": "main", "name": "Candidate " + str(choice)})
            definitions.append({"id": str(index), "candidate_mod_files": list(by_lineage.values())})
        return {"source": source, "complete": True, "version": {"file": {"id": str(lineage)}, "version": str(position), "position": str(position)},
                "materialized": {"dependencies": definitions}, "raw": {"dlc_dependency_definitions": []}}


class CandidateTests(unittest.TestCase):
    def test_shared_ranges_intersect_without_manual_candidate_prompt(self):
        world = World()
        a = world.add(11, 1, 1, [[31, 32]])
        b = world.add(21, 2, 1, [[31]])
        v1 = world.add(31, 3, 1)
        world.add(32, 3, 2)
        result = solve_nexus([(a, ["A"]), (b, ["B"])], world)
        self.assertEqual(result["components"]["nexus:cyberpunk2077:lineage:3"], v1)
        self.assertEqual(result["selections"][json_digest(a)]["0"], v1)

    def test_backtracks_from_newer_version_with_incompatible_transitive_requirement(self):
        world = World()
        a = world.add(11, 1, 1, [[31, 32]])
        b = world.add(21, 2, 1, [[41]])
        v1 = world.add(31, 3, 1, [[41]])
        world.add(32, 3, 2, [[42]])
        world.add(41, 4, 1)
        world.add(42, 4, 2)
        result = solve_nexus([(a, ["A"]), (b, ["B"])], world)
        self.assertEqual(result["components"]["nexus:cyberpunk2077:lineage:3"], v1)
        self.assertGreater(result["backtracks"], 0)

    def test_alternative_components_choose_compatible_branch(self):
        world = World()
        a = world.add(11, 1, 1, [[31, 41]])
        b = world.add(21, 2, 1, [[51]])
        world.add(31, 3, 1, [[52]])
        selected = world.add(41, 4, 1, [[51]])
        world.add(51, 5, 1)
        world.add(52, 5, 2)
        result = solve_nexus([(a, ["A"]), (b, ["B"])], world)
        self.assertNotIn("nexus:cyberpunk2077:lineage:3", result["components"])
        self.assertEqual(result["selections"][json_digest(a)]["0"], selected)

    def test_impossible_ranges_explain_both_root_chains(self):
        world = World()
        a = world.add(11, 1, 1, [[31]])
        b = world.add(21, 2, 1, [[32]])
        world.add(31, 3, 1)
        world.add(32, 3, 2)
        with self.assertRaisesRegex(PackError, "A.*versus B"):
            solve_nexus([(a, ["A"]), (b, ["B"])], world)

    def test_satisfiable_cycle_and_unknown_metadata_remain_distinct(self):
        world = World()
        a = world.add(11, 1, 1, [[21]])
        world.add(21, 2, 1, [[11]])
        self.assertEqual(len(solve_nexus([(a, ["A"])], world)["components"]), 2)
        original = world.metadata
        world.metadata = lambda source: {**original(source), "complete": False}
        with self.assertRaises(InputRequired):
            solve_nexus([(a, ["A"])], world)

    def test_unsatisfiable_newer_dependency_and_dlc_backtrack_to_older_candidate(self):
        for failure in ("empty", "dlc"):
            world = World()
            root = world.add(11, 1, 1, [[31, 32]])
            older = world.add(31, 3, 1)
            world.add(32, 3, 2, [[]] if failure == "empty" else [])
            original = world.metadata
            def metadata(source):
                result = original(source)
                if failure == "dlc" and source["fileId"] == 32:
                    result["raw"]["dlc_dependency_definitions"] = [{"id": "1", "dlc_targets": [{"dlc_id": "1"}]}]
                return result
            world.metadata = metadata
            result = solve_nexus([(root, ["root"])], world, installed_dlcs=set())
            self.assertEqual(result["components"]["nexus:cyberpunk2077:lineage:3"], older)
