"""Nexus v3 file-lineage metadata adapter (experimental upstream endpoints)."""
from copy import deepcopy
from decimal import Decimal
import urllib.parse

from .acquisition import InputRequired, json_request
from .core import PackError


ACTIVE = {"main", "update", "optional", "miscellaneous"}


class NexusProvider:
    def __init__(self, headers, request=json_request):
        self.headers = headers
        self.request = request
        self.cache = {}

    def get(self, path):
        if path not in self.cache:
            result = self.request("https://api.nexusmods.com/v3" + path, headers=self.headers)
            self.cache[path] = result.get("data", result)
        return deepcopy(self.cache[path])

    def exact_source(self, source, ask=None):
        if "fileId" in source:
            return source
        game = urllib.parse.quote(source["game"], safe="")
        mod = self.get(f"/games/{game}/mods/{source['modId']}")
        files = self.get(f"/mods/{mod['id']}/files")["mod_files"]
        candidates = []
        for file in files:
            if file["is_active"]:
                versions = self.get(f"/mod-files/{file['id']}/versions")["versions"]
                candidates.extend(v for v in versions if v["category"] in ACTIVE)
        candidates.sort(key=lambda v: (str(v["file"]["id"]), -Decimal(v["position"]), str(v["id"])))
        if not candidates:
            raise PackError("No eligible Nexus files are available for this mod page")
        request = InputRequired("nexus-file", "Select an exact Nexus file; main files, addons and variants are separate choices",
            source=source, choices=[int(v["game_scoped_id"]) for v in candidates],
            labels=[f"{v['name']} — {v['version']} ({v['category']})" for v in candidates])
        if ask is None:
            raise request
        choice = ask(request.request)
        if choice not in request.request["choices"]:
            raise PackError("Invalid Nexus file selection")
        return {**source, "fileId": choice}

    def metadata(self, source):
        game = urllib.parse.quote(source["game"], safe="")
        version = self.get(f"/games/{game}/mod-file-versions/{source['fileId']}")
        if int(version["game_scoped_id"]) != source["fileId"]:
            raise PackError("Nexus returned a different file version")
        # Verify this lineage belongs to the source page, rather than accepting
        # the caller's arbitrary modId with a globally game-scoped fileId.
        mod = self.get(f"/games/{game}/mods/{source['modId']}")
        files = self.get(f"/mods/{mod['id']}/files")["mod_files"]
        if str(version["file"]["id"]) not in {str(file["id"]) for file in files}:
            raise PackError("Nexus file does not belong to the requested mod page")
        raw = self.get(f"/mod-file-versions/{version['id']}/dependencies")
        if "dependency_definitions" not in raw or "dlc_dependency_definitions" not in raw:
            raise PackError("Nexus returned an incomplete dependency response")
        materialized = self.get(f"/mod-file-versions/{version['id']}/dependencies/ranges/materialized")
        if {d["id"] for d in raw["dependency_definitions"]} != {d["id"] for d in materialized.get("dependencies", [])}:
            raise PackError("Nexus dependency definitions changed during resolution; retry with a fresh metadata snapshot")
        # An empty new-style list is not proof that legacy page requirements are
        # disabled. The current API schema does not expose that flag on GET mod.
        complete = bool(raw["dependency_definitions"] or raw["dlc_dependency_definitions"])
        return {"source": source, "version": version, "raw": raw, "materialized": materialized,
                "complete": complete, "provenance": "nexus-v3-file-requirements"}


def candidate_groups(metadata, *, allow_empty=False):
    source = metadata["source"]
    for definition in metadata["materialized"]["dependencies"]:
        candidates = []
        for file in definition["candidate_mod_files"]:
            mod = file["mod"]
            if mod["game"]["domain_name"] != source["game"]:
                raise InputRequired("foreign-game-dependency", "A Nexus requirement belongs to another game", definition=definition["id"])
            if mod.get("status", "published") != "published":
                continue
            for candidate in file["candidate_versions"]:
                if candidate["category"] in ACTIVE:
                    candidates.append((str(file["id"]), candidate, {"type": "nexus", "game": source["game"],
                        "modId": int(mod["game_scoped_id"]), "fileId": int(candidate["game_scoped_id"])}))
        candidates.sort(key=lambda item: (item[0], -Decimal(item[1]["position"]), str(item[1]["id"])))
        if not candidates and not allow_empty:
            raise PackError("No eligible version satisfies Nexus dependency " + str(definition["id"]))
        yield str(definition["id"]), candidates


def recipe_from_metadata(metadata, sha256, *, ask=None, selections=None):
    if not metadata["complete"]:
        raise InputRequired("dependency-metadata", "Nexus file metadata is empty and legacy page requirements are unknown; supply a recipe", source=metadata["source"])
    version, source = metadata["version"], metadata["source"]
    recipe = {"schemaVersion": 1, "component": f"nexus:{source['game']}:lineage:{version['file']['id']}",
        "version": version["version"], "revision": "nexus-v3-1", "artifact": "sha256:" + sha256, "dependencies": {}}
    # Verified against Nexus /v3/games/cyberpunk2077/dlcs on 2026-09-26.
    dlc_mapping = {"1": "phantom-liberty", "2": "redmod"}
    required_dlcs = set()
    for definition in metadata["raw"]["dlc_dependency_definitions"]:
        candidates = sorted({dlc_mapping[target["dlc_id"]] for target in definition["dlc_targets"] if target["dlc_id"] in dlc_mapping})
        if not candidates:
            raise InputRequired("nexus-dlc", "This Nexus DLC is not mapped by the CP77 adapter", definition=definition)
        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            request = InputRequired("recipe-option", "Select a DLC that satisfies this alternative requirement", choices=candidates)
            if ask is None:
                raise request
            chosen = ask(request.request)
            if chosen not in candidates:
                raise PackError("Invalid DLC alternative")
        required_dlcs.add(chosen)
    if required_dlcs:
        recipe["game"] = {"id": "cyberpunk2077", "dlc": sorted(required_dlcs)}
    for definition_id, candidates in candidate_groups(metadata):
        if selections is not None:
            selected = next((item for item in candidates if item[2] == selections.get(definition_id)), None)
            if selected is None:
                raise PackError("Solved Nexus candidate no longer satisfies its snapshotted definition")
        elif len(candidates) == 1:
            selected = candidates[0]
        else:
            request = InputRequired("nexus-dependency", "Choose a candidate satisfying this Nexus dependency range",
                definition=definition_id, choices=[str(v["id"]) for _, v, _ in candidates],
                labels=[f"{v['name']} — {v['version']}" for _, v, _ in candidates])
            if ask is None:
                raise request
            choice = ask(request.request)
            selected = next((item for item in candidates if str(item[1]["id"]) == choice), None)
            if selected is None:
                raise PackError("Invalid Nexus dependency candidate")
        recipe["dependencies"]["nexus-definition-" + definition_id] = {"source": selected[2]}
    return recipe
