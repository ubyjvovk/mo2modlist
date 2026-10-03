"""Deploy resolved locks to fresh or reviewed existing profiles, with recovery."""
from __future__ import annotations

from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from .core import (PackError, digest, files, game_identity, json_digest, require_game_closed,
                   runtime_noise, safe_join, safe_relative, write_json)
from .manifest import validate_manifest, validate_source
from .sources import stream_member
from .games import ADAPTERS, executable, overlay_path, game_path, nexus_dlcs


def mod_label(value):
    """Keep readable Unicode names while avoiding Windows and MO2 aliases."""
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip().rstrip(". ")[:100].rstrip(". ")
    if not label or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", label):
        label = "Mod " + label
    return label


def installed_name(mo2, package, profile_name, reserved):
    label = mod_label(package.get("displayName") or package["component"])
    occupied = {path.name.casefold() for path in (mo2 / "mods").iterdir()} if (mo2 / "mods").exists() else set()
    occupied.update(name.casefold() for name in reserved)
    candidate, number = label, 1
    while candidate.casefold() in occupied:
        suffix = "" if number == 1 else f" {number}"
        candidate = f"{label} ({mod_label(profile_name)[:40]}{suffix})"
        number += 1
    return candidate


@contextmanager
def installation_guard(mo2):
    guard = safe_join(mo2, ".modlists/install.guard")
    guard.parent.mkdir(parents=True, exist_ok=True)
    with guard.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise PackError("Another installation owns the instance lock") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def validate_lock(lock, manifest):
    try:
        _validate_lock(lock, manifest)
    except (KeyError, TypeError, AttributeError, ValueError):
        raise PackError("Malformed source lock: check required fields and value types") from None


def _validate_lock(lock, manifest):
    from .packages import locked_manifest
    manifest = locked_manifest(lock, manifest)
    validate_manifest(manifest)
    if not isinstance(lock, dict):
        raise PackError("Expected a source-installation lock object")
    if lock.get("schemaVersion") != 1 or lock.get("kind") != "source-installation":
        raise PackError("Expected a finalized source-installation lock")
    if lock.get("manifestSha256") != json_digest(manifest):
        raise PackError("Manifest differs from lock; explicitly re-resolve before installing")
    if lock.get("adapterVersion") != ADAPTERS[manifest["game"]["id"]]:
        raise PackError("Unsupported game adapter in lock")
    game = lock.get("game")
    if (not isinstance(game, dict) or game.get("id") != manifest["game"]["id"]
        or not isinstance(game.get("executableSha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", game["executableSha256"])
        or not isinstance(game.get("distribution"), str)
        or (game["id"] == "cyberpunk2077" and type(game.get("phantomLiberty")) is not bool)
        or (game["id"] == "newvegas" and (not isinstance(game.get("dlc"), list) or any(not isinstance(d, str) for d in game["dlc"])))):
        raise PackError("Invalid locked game identity")
    if game["id"] == "newvegas":
        from .newvegas import validate_plugins
        validate_plugins(lock.get("plugins"))
        if "plugins" in manifest and lock["plugins"] != manifest["plugins"]:
            raise PackError("Locked plugin order differs from manifest")
    prerequisites = lock.get("externalPrerequisites", [])
    if not isinstance(prerequisites, list):
        raise PackError("Invalid external prerequisites")
    for item in prerequisites:
        if (item.get("kind") != "manual-collection-instructions" or not isinstance(item.get("text"), str)
            or item.get("id") != json_digest(item["text"])):
            raise PackError("Invalid or unsupported external prerequisite")
    packages = lock.get("packages")
    if (not isinstance(packages, dict) or not isinstance(lock.get("priority"), list)
        or any(not isinstance(key, str) for key in lock["priority"]) or sorted(lock["priority"]) != sorted(packages)):
        raise PackError("Invalid lock package priority")
    seen_priority = set(lock["priority"])
    if len(seen_priority) != len(lock["priority"]):
        raise PackError("Duplicate lock priority entry")
    aliases = lock.get("aliases")
    if (not isinstance(aliases, dict) or set(aliases) != set(manifest["dependencies"])
        or any(not isinstance(key, str) or key not in packages for key in aliases.values())):
        raise PackError("Locked aliases must cover every manifest dependency")
    edges = lock.get("dependencyEdges")
    if not isinstance(edges, list):
        raise PackError("Invalid locked dependency edges")
    edge_keys = set()
    for edge in edges:
        if (not isinstance(edge, dict) or not isinstance(edge.get("from"), str) or not isinstance(edge.get("to"), str)
            or edge["from"] not in packages or edge["to"] not in packages
            or not isinstance(edge.get("alias"), str) or not edge["alias"]):
            raise PackError("Dangling or invalid locked dependency edge")
        identity = (edge["from"], edge["alias"], edge.get("provenance"))
        if identity in edge_keys:
            raise PackError("Duplicate locked dependency edge")
        edge_keys.add(identity)
    reachable, pending = set(), list(aliases.values())
    while pending:
        key = pending.pop()
        if key not in reachable:
            reachable.add(key)
            pending.extend(edge["to"] for edge in edges if edge["from"] == key)
    if reachable != set(packages):
        raise PackError("Lock contains packages not reachable from the manifest")
    components, all_paths = set(), set()
    def matches_dependency(dependency, package):
        if dependency.get("integrity") and dependency["integrity"].lower() != "sha256:" + package["artifact"]["sha256"]:
            return False
        wanted = dependency["source"]
        for source in [package["artifact"]["source"], *package.get("sourceReferences", [])]:
            if source.get("type") != wanted["type"]:
                continue
            if all(source.get(field) == value for field, value in wanted.items() if field not in ("channel", "extensions")):
                return True
        return wanted["type"] == "local-archive" and bool(dependency.get("integrity"))

    for package_key, package in packages.items():
        if not isinstance(package, dict) or not isinstance(package.get("component"), str) or not package["component"]:
            raise PackError("Invalid locked component")
        if package["component"] in components:
            raise PackError("Multiple locked assignments for one component")
        components.add(package["component"])
        if "displayName" in package and (not isinstance(package["displayName"], str) or not package["displayName"].strip()):
            raise PackError("Invalid locked display name")
        artifact = package.get("artifact", {})
        validate_source(artifact.get("source"))
        if (not isinstance(artifact.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
            or type(artifact.get("size")) is not int or artifact["size"] < 0):
            raise PackError("Invalid locked artifact digest/size")
        source = artifact["source"]
        if source.get("type") == "nexus" and source.get("game") != game["id"]:
            raise PackError("Locked Nexus source belongs to a different game")
        if source["type"] == "nexus" and "fileId" not in source:
            raise PackError("Lock requires exact Nexus file identity")
        if source["type"] == "github-release" and ("tag" not in source or any(type(artifact.get(k)) is not int for k in ("releaseId", "assetId"))):
            raise PackError("Lock requires exact GitHub release and asset identities")
        if package.get("recipe", {}).get("document", {}).get("artifact") != "sha256:" + artifact["sha256"]:
            raise PackError("Locked recipe and artifact identity differ")
        try:
            recipe_bytes = base64.b64decode(package["recipe"]["bytesBase64"], validate=True)
            if hashlib.sha256(recipe_bytes).hexdigest() != package["recipe"]["sha256"] or json.loads(recipe_bytes.decode("utf-8-sig")) != package["recipe"]["document"]:
                raise ValueError("recipe digest")
        except (KeyError, ValueError):
            raise PackError("Locked recipe bytes/digest/document differ") from None
        from .planning import validate_recipe
        validate_recipe(package["recipe"]["document"])
        recipe = package["recipe"]["document"]
        if package.get("version") != recipe["version"] or package["component"] != recipe["component"]:
            raise PackError("Locked component/version differs from its recipe")
        if not isinstance(package.get("options"), dict):
            raise PackError("Invalid locked options")
        from .planning import selected_recipe
        selected, options = selected_recipe(recipe, package["options"])
        if options != package["options"]:
            raise PackError("Lock must record every selected recipe option")
        native = package.get("nativeMetadata")
        if native:
            from .nexus import candidate_groups
            if native["source"] != source:
                raise PackError("Native metadata belongs to a different locked source")
            prefix = "" if package["metadataProvenance"]["kind"] in ("nexus-v3-file-requirements", "nexus-legacy-page-requirements") else "native-"
            selections = (lock.get("candidateResolution") or {}).get("selections", {}).get(json_digest(source), {})
            for definition, candidates in candidate_groups(native):
                alias = prefix + "nexus-definition-" + definition
                required_edge = next((edge for edge in edges if edge["from"] == package_key
                    and edge["alias"] == alias and edge.get("provenance") is None), None)
                if required_edge is None:
                    raise PackError("Lock omits required native dependency: " + alias)
                target = packages[required_edge["to"]]
                eligible = [candidate for _, _, candidate in candidates
                    if definition not in selections or candidate == selections[definition]]
                if not any(matches_dependency({"source": candidate}, target) for candidate in eligible):
                    raise PackError("Locked edge does not satisfy its native dependency: " + alias)
            installed_dlcs = nexus_dlcs(game)
            for definition in native["raw"]["dlc_dependency_definitions"]:
                if not any(target["dlc_id"] in installed_dlcs for target in definition["dlc_targets"]):
                    raise PackError("Locked game does not satisfy a native DLC requirement")
        for alias in selected["dependencies"]:
            if (package_key, alias, None) not in edge_keys:
                raise PackError("Lock omits required recipe dependency: " + alias)
            target = next(edge["to"] for edge in edges if edge["from"] == package_key and edge["alias"] == alias and edge.get("provenance") is None)
            if not matches_dependency(selected["dependencies"][alias], packages[target]):
                raise PackError("Locked edge does not satisfy its recipe dependency: " + alias)
        if not isinstance(package.get("outputs"), list):
            raise PackError("Invalid locked outputs")
        seen = set()
        for entry in package["outputs"]:
            safe_relative(entry["path"])
            safe_relative(entry["member"])
            if entry["class"] == "mo2-overlay":
                overlay_path(game["id"], entry["path"])
            if entry["path"].casefold() in ("meta.ini", "modlists-source.json"):
                raise PackError("Archive output collides with MO2 management metadata")
            if type(entry.get("size")) is not int or entry["size"] < 0:
                raise PackError("Invalid locked output size")
            if entry["class"] not in ("mo2-overlay", "game-root") or entry["path"].casefold() in seen:
                raise PackError("Invalid or duplicate lock output")
            seen.add(entry["path"].casefold())
            all_paths.add(entry["path"].casefold())
            if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                raise PackError("Invalid output digest")
    from .planning import validate_output_paths
    validate_output_paths(all_paths)
    for alias, dependency in manifest["dependencies"].items():
        if not matches_dependency(dependency, packages[aliases[alias]]):
            raise PackError("Locked component does not satisfy manifest source: " + alias)
    definitions = manifest.get('extensions', {}).get('packageDefinitions', {})
    if definitions:
        from .packages import validate_package, version, spec
        by_name = {p['component']: p for p in packages.values()}
        for name, definition in definitions.items():
            validate_package(definition)
            if name != definition['name'] or name not in by_name or by_name[name]['version'] != definition['version']:
                raise PackError('Locked named package differs from its definition: ' + name)
            for required, constraint in definition['dependencies'].items():
                if required not in by_name or not spec(constraint).match(version(by_name[required]['version'])):
                    raise PackError('Locked package violates named dependency: ' + required + ' ' + constraint)
    collection = manifest.get("extensions", {}).get("nexusCollection", {})
    if lock.get("collection", {}) != collection:
        raise PackError("Locked Collection constraints differ from the manifest")
    winners = {}
    for choice in lock.get("fileChoices", []):
        if (not isinstance(choice, dict) or choice.get("winner") not in packages
            or choice.get("loser") not in packages or choice["winner"] == choice["loser"]):
            raise PackError("Invalid locked file winner")
        path = safe_relative(choice["path"]).casefold()
        pair = (frozenset((choice["winner"], choice["loser"])), path)
        if pair in winners:
            raise PackError("Duplicate locked file choice")
        winners[pair] = choice["winner"]
    def locked_winner(request):
        winner = winners.get((frozenset(request["owners"]), request["path"].casefold()))
        if winner is None:
            raise PackError("Lock has an unresolved file conflict: " + request["path"])
        return winner
    from .planning import priority_for
    priority = priority_for(packages, aliases, manifest.get("fileOverrides", []), ask=locked_winner, collection=collection,
                            preferred=manifest.get("extensions", {}).get("profilePriority", []))
    if priority != lock["priority"]:
        raise PackError("Locked priority contradicts the recorded file/Collection rules")


def import_lock(manifest_path, lock_path, store, mo2, game, profile_name, *, allow_root=False,
                progress=lambda text: None, failure_hook=lambda phase: None, acknowledged=(), update=None):
    document = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    validate_lock(lock, document)
    from .packages import locked_manifest
    document = locked_manifest(lock, document)
    if update is not None and (update["profileName"] != profile_name or update["lockSha256"] != json_digest(lock)):
        raise PackError("Profile update review belongs to a different target or lock")
    required = {item["id"] for item in lock.get("externalPrerequisites", [])}
    if not required.issubset(set(acknowledged)):
        from .acquisition import InputRequired
        raise InputRequired("external-prerequisites", "Complete and acknowledge the external instructions for this target before installing",
                            requirements=lock["externalPrerequisites"])
    require_game_closed(game)
    mo2, game = mo2.resolve(), game.resolve()
    profile = safe_join(mo2, "profiles/" + profile_name)
    if "/" in safe_relative(profile_name):
        raise PackError("Choose one profile name")
    identity = game_identity(game)
    if "redmod" in lock["game"]:
        identity["redmod"] = (game / "tools/redmod/bin/redMod.exe").is_file()
    if "version" in lock["game"]:
        from .windows_version import product_version
        identity["version"] = product_version(executable(game))
    if "fixedProductVersion" in lock["game"]:
        from .windows_version import product_version
        identity["fixedProductVersion"] = product_version(executable(game), fixed=True)
    if identity != lock["game"]:
        raise PackError("Target game executable/build/distribution/DLC differs from the resolved lock")
    packages = lock["packages"]
    root_files, effective = {}, {}
    for key in reversed(lock["priority"]):
        for entry in packages[key]["outputs"]:
            effective[entry["path"].casefold()] = entry["sha256"]
            if entry["class"] == "game-root":
                root_files[entry["path"].casefold()] = (key, entry)
    if (root_files or (update and update.get("removeRoot"))) and not allow_root:
        raise PackError("Review and allow physical game-root deployment; it affects every profile using this game")
    for file in files(mo2 / "overwrite"):
        path = file.relative_to(mo2 / "overwrite").as_posix()
        canonical = game_path(identity["id"], path).casefold()
        if update is not None and canonical not in effective:
            continue
        if not runtime_noise(path) and digest(file) != effective.get(canonical):
            raise PackError(f"Existing overwrite conflicts with this import: {path}")
    operation_id = json_digest({"lock": lock, "profile": profile_name, "game": str(game)})[:20]
    operation = safe_join(mo2, ".modlists/" + operation_id)
    journal_path = operation / "journal.json"
    with installation_guard(mo2):
        operation.mkdir(parents=True, exist_ok=True)
        journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {"status": "staging", "lockSha256": json_digest(lock), "root": {}, "mods": {}}
        journal["acknowledgedPrerequisites"] = sorted(required)
        if journal["lockSha256"] != json_digest(lock):
            raise PackError("Operation journal belongs to a different plan")
        if journal["status"] in ("restoring-root", "root-restored"):
            raise PackError("This operation's root files are being restored or have been restored; install into a new profile")
        journal["targetGame"] = str(game)
        journal["profileName"] = profile_name
        if update is not None:
            from .profile_add import assert_review_current
            assert_review_current(update, mo2, game)
            journal["update"] = update
        if profile.exists() and update is None:
            if journal_path.exists() and journal["status"] == "publishing" and (profile / "modlist.lock.json").is_file():
                published = json.loads((profile / "modlist.lock.json").read_text(encoding="utf-8"))
                names = [journal["mods"][key] for key in lock["priority"]]
                expected_profile = "# MO2 Modlists: highest priority first\n" + "".join("+" + name + "\n" for name in names)
                if published == lock and (profile / "modlist.txt").read_text(encoding="utf-8") == expected_profile:
                    if identity["id"] == "newvegas":
                        from .newvegas import profile_plugins
                        if profile_plugins(profile) != lock["plugins"]:
                            raise PackError("Published plugin order changed after interruption")
                    for key, name in zip(lock["priority"], names):
                        for entry in packages[key]["outputs"]:
                            base = game if entry["class"] == "game-root" else mo2 / "mods" / name
                            target = safe_join(base, entry["path"] if entry["class"] == "game-root" else overlay_path(identity["id"], entry["path"]))
                            expected = effective[entry["path"].casefold()] if entry["class"] == "game-root" else entry["sha256"]
                            if not target.is_file() or digest(target) != expected:
                                raise PackError("Published installation changed after interruption; inspect it before recovery")
                    journal["status"] = "complete"
                    write_json(journal_path, journal)
                    return {"profile": str(profile), "mods": names, "rootFiles": len(root_files), "journal": str(journal_path), "recovered": True}
            raise PackError("Target profile already exists; existing profiles are never replaced")
        names, stage_by_key = [], {}
        required = sum(e["size"] for p in packages.values() for e in p["outputs"])
        if shutil.disk_usage(mo2).free < required * 2:
            raise PackError("Not enough free space for staging and deployment")
        if shutil.disk_usage(game).free < sum(e["size"] for _, e in root_files.values()):
            raise PackError("Not enough free space for game-root deployment")
        write_json(operation / "plan.lock.json", lock)

        def checkpoint():
            write_json(journal_path, journal)

        try:
            for index, key in enumerate(lock["priority"]):
                package = packages[key]
                if update is not None and key in update["reuse"]:
                    name = update["reuse"][key]
                    names.append(name)
                    journal["mods"][key] = name
                    provenance_path = safe_join(mo2, ".modlists/installed/" + name + ".json")
                    if not provenance_path.is_file():
                        write_json(provenance_path, {"artifact": package["artifact"], "component": package["component"],
                            "options": package["options"], "sourceDocument": package["sourceDocument"],
                            "recipe": package["recipe"], "recipeReference": package.get("recipeReference")})
                    # Root entries may still need staging (for example after a
                    # different instance restored its shared game files).
                    if not any(e["class"] == "game-root" for e in package["outputs"]):
                        checkpoint()
                        continue
                progress("Preparing " + package["component"])
                artifact = store.acquire({"source": package["artifact"]["source"]},
                    Path(package["sourceDocument"]), locked=package["artifact"])
                archive = store.path(artifact["sha256"])
                from .planning import outputs_for, selected_recipe
                selected, _ = selected_recipe(package["recipe"]["document"], package["options"])
                expected_outputs = outputs_for(archive, selected.get("mappings"), progress, hash_contents=False, game_id=identity["id"])
                locked_outputs = [{field: entry[field] for field in ("member", "path", "class", "size")} for entry in package["outputs"]]
                if sorted(expected_outputs, key=lambda entry: entry["path"].casefold()) != sorted(locked_outputs, key=lambda entry: entry["path"].casefold()):
                    raise PackError("Locked output mappings differ from the recipe and archive inventory")
                stage = safe_join(mo2, ".modlists/" + operation_id + "/s/" + str(index))
                stage.mkdir(parents=True, exist_ok=True)
                stage_by_key[key] = stage
                for entry in package["outputs"]:
                    target = safe_join(stage, entry["path"])
                    if target.is_file() and target.stat().st_size == entry["size"] and digest(target) == entry["sha256"]:
                        continue
                    progress("Extracting " + entry["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + ".partial")
                    with temporary.open("wb") as output:
                        actual = stream_member(archive, entry["member"], output, progress=progress)
                    if actual != entry["sha256"] or temporary.stat().st_size != entry["size"]:
                        raise PackError("Extracted member differs from locked output")
                    os.replace(temporary, target)
                reused = update is not None and key in update["reuse"]
                name = journal["mods"].get(key) or installed_name(mo2, package, profile_name, names)
                if not reused:
                    names.append(name)
                if reused:
                    continue
                destination = safe_join(mo2, "mods/" + name)
                if not destination.exists():
                    journal["mods"][key] = name
                    checkpoint()
                    destination.mkdir(parents=True)
                elif journal["mods"].get(key) != name:
                    raise PackError("Target mod directory is not owned by this operation")
                for entry in package["outputs"]:
                    if entry["class"] != "mo2-overlay":
                        continue
                    target = safe_join(destination, overlay_path(identity["id"], entry["path"]))
                    if target.exists():
                        if digest(target) != entry["sha256"]:
                            raise PackError("Previously staged mod was modified; refusing to replace it")
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name(target.name + ".ml-partial")
                        shutil.copyfile(safe_join(stage, entry["path"]), temporary)
                        os.replace(temporary, target)
                write_json(safe_join(mo2, ".modlists/installed/" + name + ".json"),
                    {"artifact": artifact, "component": package["component"], "options": package["options"],
                     "sourceDocument": package["sourceDocument"], "recipe": package["recipe"],
                     "recipeReference": package.get("recipeReference")})
                (destination / "meta.ini").write_text("[General]\nnotes=Installed from a pinned source manifest\n", encoding="utf-8")
                failure_hook("mod-staged")
            if identity["id"] == "newvegas":
                from .newvegas import resolve_plugins
                if resolve_plugins(document, lock, store, game) != lock["plugins"]:
                    raise PackError("Plugin order differs from the resolved archive/master plan")
            journal["status"] = "deploying"
            if update is not None:
                assert_review_current(update, mo2, game)
            checkpoint()
            require_game_closed(game)
            for entry in update.get("removeRoot", []) if update else []:
                target = safe_join(game, entry["path"])
                canonical = entry["path"].casefold()
                if canonical not in journal["root"]:
                    backup_path = safe_join(operation, "b/" + str(len(journal["root"])))
                    backup_path.parent.mkdir(exist_ok=True)
                    shutil.copyfile(target, backup_path)
                    journal["root"][canonical] = {"path": entry["path"], "backup": {"path": str(backup_path), "sha256": digest(backup_path)},
                                                 "writtenSha256": entry["restore"]["sha256"] if entry.get("restore") else None}
                    checkpoint()
                if entry.get("restore"):
                    original = Path(entry["restore"]["path"])
                    if digest(original) != entry["restore"]["sha256"]:
                        raise PackError("Obsolete root file backup changed")
                    temporary = target.with_name(target.name + ".ml-" + operation_id)
                    shutil.copyfile(original, temporary)
                    os.replace(temporary, target)
                else:
                    target.unlink(missing_ok=True)
                failure_hook("root-written")
            for canonical, (key, entry) in root_files.items():
                target = safe_join(game, entry["path"])
                if target.is_file() and digest(target) == entry["sha256"]:
                    continue
                if canonical not in journal["root"]:
                    backup = None
                    if target.exists():
                        backup_path = safe_join(mo2, ".modlists/" + operation_id + "/b/" + str(len(journal["root"])))
                        backup_path.parent.mkdir(exist_ok=True)
                        shutil.copyfile(target, backup_path)
                        backup = {"path": str(backup_path), "sha256": digest(backup_path)}
                    journal["root"][canonical] = {"path": entry["path"], "backup": backup, "writtenSha256": entry["sha256"]}
                    checkpoint()
                else:
                    previous = journal["root"][canonical]["backup"]
                    if (target.exists() and (previous is None or digest(target) != previous["sha256"])) or (not target.exists() and previous is not None):
                        raise PackError("Game-root file changed since interruption; review before retrying")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".ml-" + operation_id)
                shutil.copyfile(safe_join(stage_by_key[key], entry["path"]), temporary)
                os.replace(temporary, target)
                failure_hook("root-written")
            stage_profile = safe_join(mo2, ".modlists/" + operation_id + "/profile")
            stage_profile.mkdir(exist_ok=True)
            if update is not None:
                from .profile_add import updated_modlist
                content = updated_modlist(profile, update, names)
            else:
                content = "# MO2 Modlists: highest priority first\n" + "".join("+" + name + "\n" for name in names)
                (stage_profile / "settings.ini").write_text("[General]\nLocalSaves=false\nLocalSettings=false\n", encoding="utf-8")
            (stage_profile / "modlist.txt").write_text(content, encoding="utf-8")
            if identity["id"] == "newvegas":
                from .newvegas import write_plugins
                write_plugins(stage_profile, lock["plugins"])
            write_json(stage_profile / "modlist.lock.json", lock)
            write_json(stage_profile / "modlist.json", document)
            write_json(stage_profile / "modlist.origin.json", {"path": manifest_path.resolve().as_posix()})
            write_json(stage_profile / "modlist.state.json", {"lockSha256": json_digest(lock),
                "mods": dict(zip(lock["priority"], names)), "unmanaged": update["unmanaged"] if update else []})
            failure_hook("before-profile")
            profile.parent.mkdir(parents=True, exist_ok=True)
            journal["status"] = "publishing"
            checkpoint()
            if update is None:
                stage_profile.rename(profile)
            else:
                journal["profileFiles"] = {}
                for staged in stage_profile.iterdir():
                    target = safe_join(profile, staged.name)
                    backup = safe_join(operation, "profile-backup/" + staged.name)
                    if target.is_file():
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(target, backup)
                    journal["profileFiles"][staged.name] = {"before": digest(target) if target.is_file() else None,
                                                          "after": digest(staged)}
                checkpoint()
                for staged in stage_profile.iterdir():
                    target = safe_join(profile, staged.name)
                    temporary = target.with_name(target.name + ".ml-update")
                    shutil.copyfile(staged, temporary)
                    os.replace(temporary, target)
                    failure_hook("profile-file-written")
            failure_hook("profile-published")
            journal["status"] = "complete"
            checkpoint()
            return {"profile": str(profile), "mods": names, "rootFiles": len(root_files), "journal": str(journal_path)}
        except BaseException:
            if profile.is_dir() and update is None:
                # Publication was the final mutation. Do not roll back root files
                # beneath a fully published profile if only the final journal write failed.
                raise
            if update is not None:
                rollback_profile_files(operation, profile, journal)
            # Restore only root files still containing this operation's bytes.
            # Staged mod directories remain disabled and can be verified/reused.
            for item in reversed(list(journal["root"].values())):
                target = safe_join(game, item["path"])
                if (digest(target) if target.is_file() else None) == item["writtenSha256"]:
                    if item["backup"]:
                        backup = Path(item["backup"]["path"])
                        if digest(backup) != item["backup"]["sha256"]:
                            raise PackError("Root backup changed; inspect the operation before retrying")
                        temporary = target.with_name(target.name + ".ml-rollback")
                        shutil.copyfile(backup, temporary)
                        os.replace(temporary, target)
                    else:
                        target.unlink()
            journal["status"] = "interrupted"
            checkpoint()
            raise


def rollback_profile_files(operation, profile, journal):
    for name, hashes in journal.get("profileFiles", {}).items():
        target = safe_join(profile, name)
        current = digest(target) if target.is_file() else None
        if current == hashes["before"]:
            continue
        if current != hashes["after"]:
            raise PackError("Profile was edited during interrupted update; preserve and reconcile: " + name)
        if hashes["before"] is None:
            target.unlink()
        else:
            backup = safe_join(operation, "profile-backup/" + name)
            if digest(backup) != hashes["before"]:
                raise PackError("Profile update backup changed: " + name)
            temporary = target.with_name(target.name + ".ml-rollback")
            shutil.copyfile(backup, temporary)
            os.replace(temporary, target)


def recover_profile_update(mo2, game, profile_name):
    """Roll back interrupted profile publications before preparing another add."""
    require_game_closed(game)
    with installation_guard(mo2):
        for path in (mo2 / ".modlists").glob("*/journal.json"):
            journal = json.loads(path.read_text(encoding="utf-8-sig"))
            if (not journal.get("update") or journal.get("profileName") != profile_name
                    or journal.get("targetGame") != str(game.resolve())
                    or journal["status"] in ("complete", "interrupted", "root-restored", "restoring-root")):
                continue
            operation = path.parent
            rollback_profile_files(operation, safe_join(mo2, "profiles/" + profile_name), journal)
            for item in reversed(list(journal.get("root", {}).values())):
                target = safe_join(game, item["path"])
                current = digest(target) if target.is_file() else None
                original = item["backup"]["sha256"] if item["backup"] else None
                if current == original:
                    continue
                if current != item["writtenSha256"]:
                    raise PackError("Game-root file changed during interrupted update: " + item["path"])
                if item["backup"]:
                    backup = safe_join(operation, Path(item["backup"]["path"]).relative_to(operation).as_posix())
                    if digest(backup) != original:
                        raise PackError("Root update backup changed")
                    temporary = target.with_name(target.name + ".ml-rollback")
                    shutil.copyfile(backup, temporary)
                    os.replace(temporary, target)
                else:
                    target.unlink()
            journal["status"] = "interrupted"
            write_json(path, journal)
