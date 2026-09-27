"""Resolve pinned source manifests into inspected, immutable installation locks."""
from __future__ import annotations

from copy import deepcopy
import base64
import io
import json
from pathlib import Path
import re

from .acquisition import InputRequired, reference_path
from .core import PackError, digest, game_identity, json_digest, safe_relative, write_json
from .manifest import fields, validate_manifest
from .games import ADAPTERS, executable, installed_dlcs, nexus_dlcs, overlay_path
from .sources import members, stream_member


def validate_recipe(recipe):
    fields(recipe, ("schemaVersion", "component", "version", "revision", "artifact", "dependencies"),
           ("mappings", "conflicts", "game", "options", "variants", "alternatives"), "recipe")
    if type(recipe["schemaVersion"]) is not int or recipe["schemaVersion"] != 1 or any(not isinstance(recipe[k], str) or not recipe[k] for k in ("component", "version", "revision")):
        raise PackError("Invalid recipe identity/version/revision")
    if not isinstance(recipe["artifact"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", recipe["artifact"]):
        raise PackError("Recipe must bind to an exact artifact SHA-256")
    validate_manifest({"schemaVersion": 1, "name": "recipe dependencies", "game": {"id": "cyberpunk2077", "dlc": []}, "dependencies": recipe["dependencies"]})
    if "conflicts" in recipe and (not isinstance(recipe["conflicts"], list) or any(not isinstance(x, str) or not x for x in recipe["conflicts"])):
        raise PackError("Recipe conflicts must be component names")
    if "mappings" in recipe and not isinstance(recipe["mappings"], list):
        raise PackError("Recipe mappings must be an array")
    options = recipe.get("options", {})
    if not isinstance(options, dict):
        raise PackError("Recipe options must be an object")
    for key, definition in options.items():
        fields(definition, ("choices",), ("default",), "recipe option " + key)
        choices = definition["choices"]
        if not isinstance(choices, list) or not choices or any(not isinstance(value, str) or not value for value in choices) or len(set(choices)) != len(choices):
            raise PackError("Recipe option choices must be distinct nonempty strings")
        if "default" in definition and definition["default"] not in choices:
            raise PackError("Recipe option default is not one of its choices")
    for field in ("variants", "alternatives"):
        if not isinstance(recipe.get(field, {}), dict):
            raise PackError("Recipe " + field + " must be an object")
        for key, values in recipe.get(field, {}).items():
            if key not in options or not isinstance(values, dict) or values.keys() - set(options[key]["choices"]):
                raise PackError("Recipe " + field + " references unknown option choices")
            if field == "alternatives":
                if set(values) != set(options[key]["choices"]):
                    raise PackError("Every alternative option choice must have a dependency")
                validate_manifest({"schemaVersion": 1, "name": "alternatives", "game": {"id": "cyberpunk2077", "dlc": []}, "dependencies": values})
            else:
                for contribution in values.values():
                    fields(contribution, (), ("mappings", "dependencies", "conflicts"), "variant contribution")
                    if "mappings" in contribution and not isinstance(contribution["mappings"], list):
                        raise PackError("Variant mappings must be an array")
                    if "conflicts" in contribution and (not isinstance(contribution["conflicts"], list) or any(not isinstance(c, str) or not c for c in contribution["conflicts"])):
                        raise PackError("Variant conflicts must be component names")
                    validate_manifest({"schemaVersion": 1, "name": "variant", "game": {"id": "cyberpunk2077", "dlc": []}, "dependencies": contribution.get("dependencies", {})})
    return recipe


def load_recipe(path: Path):
    return validate_recipe(json.loads(path.read_text(encoding="utf-8-sig")))


def source_component(source):
    if source["type"] == "nexus":
        # Independent files on a page are distinct unless a recipe declares a lineage.
        return f"nexus:{source['game']}:{source['modId']}:{source['fileId']}"
    if source["type"] == "github-release":
        return f"github:{source['repository'].casefold()}:{source['asset']}"
    return "local:" + source["path"]


def selected_recipe(recipe, options, ask=None):
    result = deepcopy(recipe)
    declared = recipe.get("options", {})
    if options.keys() - declared.keys():
        raise PackError("Unknown recipe options: " + ", ".join(sorted(options.keys() - declared.keys())))
    chosen = {}
    for key, definition in declared.items():
        value = options.get(key, definition.get("default"))
        if value is None or value not in definition.get("choices", []):
            request = InputRequired("recipe-option", f"Choose {key} for {recipe['component']}", option=key, choices=definition.get("choices", []))
            if ask is None:
                raise request
            value = ask(request.request)
            if value not in definition.get("choices", []):
                raise PackError("Invalid recipe option selection")
        chosen[key] = value
        contribution = recipe.get("variants", {}).get(key, {}).get(str(value), {})
        for field in contribution.keys() - {"mappings", "dependencies", "conflicts"}:
            raise PackError(f"Unsupported variant contribution: {field}")
        if "mappings" in contribution:
            result.setdefault("mappings", []).extend(contribution["mappings"])
        result["dependencies"].update(contribution.get("dependencies", {}))
        result.setdefault("conflicts", []).extend(contribution.get("conflicts", []))
    for key, alternatives in recipe.get("alternatives", {}).items():
        alias = "alternative-" + key
        if alias in result["dependencies"]:
            raise PackError("Alternative alias collides with a required dependency")
        result["dependencies"][alias] = alternatives[chosen[key]]
    return result, chosen


def automatic_mappings(index, game_id="cyberpunk2077"):
    if game_id == "newvegas":
        from .games import fnv_mappings
        return fnv_mappings(index)
    names = [name for name, _ in index]
    if any("fomod/" in name.casefold() for name in names):
        raise InputRequired("installer-choice", "This archive has a FOMOD installer. Supply an explicit recipe mapping and record the selected options.")
    roots = ("archive/", "r6/", "engine/", "bin/", "red4ext/", "mods/")
    mapped = []
    for name in names:
        if name.lower().startswith(roots):
            mapped.append({"from": name, "to": name, "class": "game-root" if name.lower().startswith(("bin/", "red4ext/")) else "mo2-overlay"})
        elif "/" not in name and (name.lower().startswith(("readme", "license", "changelog")) or name.lower().endswith((".md", ".txt"))):
            continue
        else:
            raise InputRequired("archive-layout", "Archive layout requires an explicit recipe mapping", member=name)
    if not mapped:
        raise InputRequired("archive-layout", "Archive contains no recognized Cyberpunk game paths")
    return mapped


def outputs_for(archive, mappings, progress, *, hash_contents=True, game_id="cyberpunk2077"):
    index = list(members(archive))
    mappings = automatic_mappings(index, game_id) if mappings is None else mappings
    outputs = {}
    for mapping in mappings:
        fields(mapping, ("from", "to", "class"), (), "mapping")
        if mapping["class"] not in ("game-root", "mo2-overlay"):
            raise PackError("Unknown deployment class")
        source = mapping["from"]
        target = mapping["to"]
        if source != ".":
            source = safe_relative(source)
        if target:
            target = safe_relative(target)
        found = False
        for member, size in index:
            if member == source:
                destination = target
            elif source == "." or member.startswith(source + "/"):
                suffix = member if source == "." else member[len(source) + 1:]
                destination = target + "/" + suffix if target else suffix
            else:
                continue
            found = True
            destination = safe_relative(destination)
            if mapping["class"] == "mo2-overlay":
                overlay_path(game_id, destination)
            key = destination.casefold()
            progress(f"Inspecting {destination}")
            entry = {"member": member, "path": destination, "class": mapping["class"], "size": size}
            if hash_contents:
                entry["sha256"] = stream_member(archive, member, progress=progress)
            if key in outputs and outputs[key] != entry:
                raise PackError(f"Recipe maps incompatible files to {destination}")
            outputs[key] = entry
        if not found:
            raise PackError(f"Recipe source is absent from archive: {source}")
    validate_output_paths(outputs)
    return sorted(outputs.values(), key=lambda e: e["path"].casefold())


def validate_output_paths(paths):
    paths = set(path.casefold() for path in paths)
    for path in paths:
        parts = path.split("/")
        if any("/".join(parts[:index]) in paths for index in range(1, len(parts))):
            raise PackError("A managed file would also have to be a directory: " + path)
        if path in ("meta.ini", "modlists-source.json"):
            raise PackError("Archive output collides with MO2 management metadata")


def priority_for(packages, aliases, rules, ask=None, decisions=None, collection=None):
    by_path = {}
    edges = {key: set() for key in packages}
    declared = {}
    collection = collection or {}
    for rule in collection.get("rules", []):
        if rule["source"] not in aliases or rule["target"] not in aliases:
            raise PackError("Collection rule references an absent mod")
        source, target = aliases[rule["source"]], aliases[rule["target"]]
        if rule["type"] == "after":
            edges[source].add(target)
        elif rule["type"] == "before":
            edges[target].add(source)
        elif rule["type"] not in ("requires", "recommends"):
            raise PackError("Unsupported collection rule")
    for rule in rules:
        winner, loser = aliases[rule["winner"]], aliases[rule["loser"]]
        for path in rule["paths"]:
            key = (frozenset((winner, loser)), path.casefold())
            if key in declared and declared[key] != winner:
                raise PackError(f"Contradictory file winners for {path}")
            declared[key] = winner
    for key, package in packages.items():
        for entry in package["outputs"]:
            by_path.setdefault(entry["path"].casefold(), []).append((key, entry))
    validate_output_paths(by_path)
    for rule in collection.get("pathWinners", []):
        path = safe_relative(rule["path"]).casefold()
        winner = aliases[rule["winner"]]
        owners = by_path.get(path, [])
        if winner not in [key for key, entry in owners]:
            raise PackError("Collection file winner does not provide its declared file: " + path)
        for other, _ in owners:
            if other != winner:
                pair = (frozenset((winner, other)), path)
                if pair in declared and declared[pair] != winner:
                    raise PackError("Contradictory collection file winner for " + path)
                declared[pair] = winner
    collection_order = {key: set(values) for key, values in edges.items()}
    def precedes(winner, loser, visited=None):
        visited = set() if visited is None else visited
        if winner in visited:
            return False
        visited.add(winner)
        return loser in collection_order[winner] or any(precedes(next_key, loser, visited) for next_key in collection_order[winner])
    for path, owners in by_path.items():
        for i, (left, a) in enumerate(owners):
            for right, b in owners[i + 1:]:
                if a["sha256"] == b["sha256"]:
                    continue
                if a["class"] != b["class"]:
                    raise InputRequired("deployment-class", f"Conflicting root/overlay mappings for {path}", owners=[left, right])
                winner = declared.get((frozenset((left, right)), path))
                if winner is None:
                    winner = left if precedes(left, right) else right if precedes(right, left) else None
                if winner is None:
                    request = InputRequired("file-conflict", f"Choose a winner for {path}", owners=[left, right],
                                            labels=[packages[left]["component"], packages[right]["component"]], path=path)
                    if ask is None:
                        raise request
                    winner = ask(request.request)
                    if winner not in (left, right):
                        raise PackError("Invalid conflict winner")
                    if decisions is not None:
                        decisions.append({"path": path, "winner": winner, "loser": right if winner == left else left})
                loser = right if winner == left else left
                edges[winner].add(loser)
    ordered = []
    remaining = set(packages)
    while remaining:
        available = sorted(key for key in remaining if not any(key in edges[other] for other in remaining))
        if not available:
            raise PackError("File winner rules form an ordering cycle")
        ordered.extend(available)
        remaining.difference_update(available)
    return ordered


def resolve_manifest(manifest_path: Path, store, game: Path, lock_path: Path, *, progress=lambda text: None, ask=None):
    document = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8-sig")))
    if ask is not None:
        original_ask, answers = ask, {}
        def ask(request):
            key = json_digest(request)
            if key not in answers:
                answers[key] = original_ask(request)
            return answers[key]
    from .registry import snapshot_registry, registry_recipe
    registry_snapshots, registry_entries = {}, []
    for name, definition in sorted(document.get("registries", {}).items()):
        snapshot, entries = snapshot_registry(name, definition, store.root, offline=store.offline, progress=progress)
        registry_snapshots[name] = snapshot
        registry_entries.extend(entries)
    identity = game_identity(game)
    if identity["id"] != document["game"]["id"]:
        raise PackError("Manifest game differs from target game")
    from .windows_version import product_version
    observed_version = product_version(executable(game))
    fixed_version = product_version(executable(game), fixed=True)
    observed_versions = {value for value in (observed_version, fixed_version) if value}
    if observed_version:
        identity["version"] = observed_version
    if fixed_version:
        identity["fixedProductVersion"] = fixed_version
    if identity["id"] == "cyberpunk2077":
        identity["redmod"] = (game / "tools/redmod/bin/redMod.exe").is_file()
    def has_dlc(dlc):
        return dlc in installed_dlcs(identity)
    for dlc in document["game"]["dlc"]:
        if not has_dlc(dlc):
            raise PackError(f"Required DLC is unavailable: {dlc}")
    if document["game"].get("version"):
        version = observed_version
        if document["game"]["version"] not in observed_versions:
            raise PackError(f"Game version differs: required {document['game']['version']}, found {version}")
        identity["version"] = version
    packages, components, aliases, edges, active = {}, {}, {}, [], {}
    native_sources = {}

    def source_identity(source, declaring):
        source = dict(source)
        if source["type"] == "local-archive":
            source["path"] = reference_path(source["path"], declaring).as_posix()
        return json_digest(source)

    prepared_recipes, prepared_provenance, preparing = {}, {}, set()
    # A root's explicit recipe also serves references encountered before that
    # root's alias is traversed (for example a reviewed optional dependency).
    for dependency in document["dependencies"].values():
        if "recipe" in dependency:
            key = source_identity(dependency["source"], manifest_path)
            prepared_recipes.setdefault(key, {"recipe": reference_path(dependency["recipe"], manifest_path).as_posix(),
                                              "options": dependency.get("options", {})})
    native_solution = None
    if store.nexus_metadata is not None:
        from .candidates import solve_nexus
        def collect(dependency, declaring, chain, metadata=None):
            dependency = dict(dependency)
            source = dependency["source"]
            native = source["type"] == "nexus"
            if native and source["game"] != identity["id"]:
                raise PackError("Nexus dependency belongs to a different game")
            if native:
                source = store.nexus_metadata.exact_source(source, ask)
                dependency["source"] = source
                metadata = metadata or store.nexus_metadata.metadata(source)
            roots = [(source, chain)] if native else []
            scope = json_digest({"dependency": dependency, "declaring": str(declaring.resolve())})
            if scope in preparing:
                return roots
            preparing.add(scope)
            source_key = source_identity(source, declaring)
            if "recipe" not in dependency and source_key in prepared_recipes:
                dependency.update(prepared_recipes[source_key])
            if "recipe" not in dependency and (not native or not metadata["complete"]):
                supplement = registry_recipe(source, registry_entries, ask)
                if supplement:
                    dependency["recipe"] = supplement["path"].as_posix()
                    prepared_provenance[source_key] = supplement
                else:
                    request = InputRequired("dependency-metadata", "Required dependency metadata needs review; provide a recipe with an explicit dependency list", source=source, chain=chain,
                                            unresolvedRequirements=metadata.get("unresolvedRequirements", []) if native else [])
                    if ask is None:
                        raise request
                    dependency["recipe"] = ask(request.request)
            if "recipe" in dependency:
                recipe_path = reference_path(dependency["recipe"], declaring)
                recipe = load_recipe(recipe_path)
                selected, options = selected_recipe(recipe, dependency.get("options", {}), ask)
                prepared_recipes.setdefault(source_key, {"recipe": recipe_path.as_posix(), "options": options})
                for alias, required in sorted(selected["dependencies"].items()):
                    roots.extend(collect(required, recipe_path, chain + [alias]))
            return roots
        roots = []
        for alias, dependency in sorted(document["dependencies"].items()):
            roots.extend(collect(dependency, manifest_path, [alias]))
        def supplemental(source, metadata, chain):
            # Revisit an already prepared recipe's transitive references for the
            # solver. collect's recursion guard is per traversal, not a claim
            # that a prior traversal's dependency edges may be discarded.
            preparing.clear()
            return [(required, reason) for required, reason in collect({"source": source}, manifest_path, list(chain), metadata)
                    if required != source]
        if roots:
            native_solution = solve_nexus(roots, store.nexus_metadata, supplemental=supplemental, progress=progress, installed_dlcs=nexus_dlcs(identity))

    def visit(dependency, declaring, chain):
        progress("Resolving " + " -> ".join(chain))
        if dependency["source"]["type"] == "nexus" and dependency["source"]["game"] != identity["id"]:
            raise PackError("Nexus dependency belongs to a different game")
        supplement, native, acquired = None, None, None
        initial_source = source_identity(dependency["source"], declaring)
        if "recipe" not in dependency and not dependency.get("options") and initial_source in native_sources:
            previous_key = native_sources[initial_source]
            expected = dependency.get("integrity")
            if expected and expected.lower() != "sha256:" + packages[previous_key]["artifact"]["sha256"]:
                raise PackError("Different integrity constraints for the same source: " + " -> ".join(chain))
            return previous_key
        if dependency["source"]["type"] == "nexus" and store.nexus_metadata is not None:
            exact = store.nexus_metadata.exact_source(dependency["source"], ask)
            dependency = {**dependency, "source": exact}
            native = store.nexus_metadata.metadata(exact)
        prepared = prepared_recipes.get(source_identity(dependency["source"], declaring))
        if prepared and "recipe" not in dependency:
            dependency = {**prepared, **dependency}
            supplement = prepared_provenance.get(source_identity(dependency["source"], declaring))
        native_selections = native_solution["selections"].get(json_digest(dependency["source"])) if native_solution else None
        if "recipe" not in dependency and native and native["complete"]:
            from .nexus import recipe_from_metadata
            acquired = store.acquire(dependency, declaring)
            native_recipe = recipe_from_metadata(native, acquired["sha256"], ask=ask, selections=native_selections)
            recipe_path = store.root / "native-recipes" / (json_digest(native_recipe) + ".json")
            if recipe_path.exists():
                if json.loads(recipe_path.read_text(encoding="utf-8")) != native_recipe:
                    raise PackError("Cached native recipe was modified")
            else:
                write_json(recipe_path, native_recipe)
            dependency = {**dependency, "recipe": recipe_path.as_posix()}
        if "recipe" not in dependency:
            supplement = registry_recipe(dependency["source"], registry_entries, ask)
            if supplement:
                dependency = {**dependency, "recipe": supplement["path"].as_posix()}
        if "recipe" not in dependency:
            request = InputRequired("dependency-metadata", "Required dependency metadata is unknown; provide a recipe with an explicit dependency list", chain=chain, source=dependency["source"])
            if ask is None:
                raise request
            selected_path = ask(request.request)
            if not isinstance(selected_path, str) or not Path(selected_path).is_absolute():
                raise PackError("Recipe selection must be an absolute path")
            dependency = {**dependency, "recipe": selected_path}
        recipe_path = reference_path(dependency["recipe"], declaring)
        recipe = load_recipe(recipe_path)
        selected, options = selected_recipe(recipe, dependency.get("options", {}), ask)
        if native and acquired is None:
            from .nexus import recipe_from_metadata
            # Preserve native requirements alongside local installation recipes.
            # Supplemental metadata cannot silently delete provider constraints.
            native_requirements = recipe_from_metadata(native, recipe["artifact"].removeprefix("sha256:"), ask=ask, selections=native_selections, known_only=True)
            for alias, required in native_requirements["dependencies"].items():
                selected["dependencies"]["native-" + alias] = required
            for dlc in native_requirements.get("game", {}).get("dlc", []):
                if not has_dlc(dlc):
                    raise PackError("Required native DLC is unavailable: " + dlc + "; " + " -> ".join(chain))
        if "game" in selected:
            constraint_game = selected["game"]
            validate_manifest({"schemaVersion": 1, "name": "recipe game", "game": constraint_game, "dependencies": {}})
            if constraint_game.get("version") and constraint_game["version"] not in observed_versions:
                raise PackError("Recipe game version constraint failed: " + " -> ".join(chain))
            if any(not has_dlc(dlc) for dlc in constraint_game["dlc"]):
                raise PackError("Recipe DLC constraint failed: " + " -> ".join(chain))
        dependency = {**dependency, "integrity": recipe["artifact"]} if "integrity" not in dependency else dependency
        if dependency["integrity"].lower() != recipe["artifact"]:
            raise PackError("Recipe and manifest bind to different source artifacts: " + " -> ".join(chain))
        component = recipe["component"]
        constraint = (recipe["version"], recipe["artifact"], json_digest(options), digest(recipe_path))
        if component in components:
            previous, previous_chain, key = components[component]
            if constraint != previous:
                raise PackError(f"Conflicting component {component}: {' -> '.join(previous_chain)} versus {' -> '.join(chain)}")
            if dependency["source"] not in packages[key]["sourceReferences"]:
                packages[key]["sourceReferences"].append(dependency["source"])
            return key
        artifact = acquired or store.acquire(dependency, declaring)
        key = json_digest({"component": component, "constraint": constraint})
        components[component] = (constraint, chain, key)
        packages[key] = {"component": component, "version": recipe["version"], "artifact": artifact,
                         "displayName": dependency.get("extensions", {}).get("displayName") or (native or {}).get("displayName") or (native or {}).get("version", {}).get("name") or chain[-1],
                         "recipe": {"sha256": digest(recipe_path), "document": recipe,
                                    "bytesBase64": base64.b64encode(recipe_path.read_bytes()).decode("ascii")}, "options": options,
                         "selectedAlternatives": {name: options[name] for name in recipe.get("alternatives", {})},
                         "sourceDocument": str(declaring.resolve()), "reason": chain,
                         "recipeReference": recipe_path.resolve().as_posix(),
                         "sourceReferences": [dependency["source"]],
                         "nativeMetadata": native,
                         "metadataProvenance": {"kind": "registry", "registry": supplement["registry"], "commit": supplement["commit"], "reason": supplement["reason"]} if supplement else {"kind": native.get("provenance", "nexus-v3-file-requirements") if acquired else "explicit-local-recipe"},
                         "outputs": outputs_for(store.path(artifact["sha256"]), selected.get("mappings"), progress, game_id=identity["id"])}
        native_sources[source_identity(artifact["source"], declaring)] = key
        for alias, required in sorted(selected["dependencies"].items()):
            required_key = visit(required, recipe_path, chain + [alias])
            edges.append({"from": key, "to": required_key, "alias": alias})
        for conflict in selected.get("conflicts", []):
            active.setdefault(component, set()).add(conflict)
        return key

    for alias, dependency in sorted(document["dependencies"].items()):
        aliases[alias] = visit(dependency, manifest_path, [alias])
    for component, conflicts in active.items():
        for conflict in conflicts & components.keys():
            raise PackError(f"Incompatible components: {component} conflicts with {conflict}")
    choices = []
    collection = document.get("extensions", {}).get("nexusCollection", {})
    if collection and collection.get("schemaVersion") != 1:
        raise PackError("Unsupported Nexus collection metadata version")
    priority = priority_for(packages, aliases, document.get("fileOverrides", []), ask, choices, collection)
    for rule in collection.get("rules", []):
        if rule["type"] == "requires":
            edges.append({"from": aliases[rule["source"]], "to": aliases[rule["target"]], "alias": rule["target"], "provenance": "nexus-collection"})
    prerequisites = []
    if collection.get("externalInstructions"):
        instruction = collection["externalInstructions"]
        prerequisites.append({"id": json_digest(instruction), "kind": "manual-collection-instructions", "text": instruction,
            "notice": "Complete these external steps for this target installation; they are not performed by the importer."})
    lock = {"schemaVersion": 1, "kind": "source-installation", "manifestSha256": json_digest(document),
            "game": identity, "packages": packages, "aliases": aliases, "dependencyEdges": edges,
            "priority": priority, "fileChoices": choices, "adapterVersion": ADAPTERS[identity["id"]], "externalPrerequisites": prerequisites, "registries": registry_snapshots,
            "collection": collection, "candidateResolution": native_solution}
    if identity["id"] == "newvegas":
        from .newvegas import resolve_plugins
        lock["plugins"] = resolve_plugins(document, lock, store, game)
    if lock_path.exists():
        raise PackError("Lock destination exists; choose a new lockfile for explicit re-resolution")
    write_json(lock_path, lock)
    return lock
