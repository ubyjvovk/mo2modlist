"""The source manifest from SPEC.md. Export writes one JSON document only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import urllib.parse

from .core import (PackError, active_mods, digest, files, read_ini, runtime_noise,
                   safe_join, safe_relative, write_json)
from .sources import github_source


def fields(value, required, optional, where):
    if not isinstance(value, dict):
        raise PackError(f"{where}: expected an object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional) - {"extensions"}
    if missing or unknown:
        raise PackError(f"{where}: missing fields {sorted(missing)}; unknown fields {sorted(unknown)}")
    if "extensions" in value and not isinstance(value["extensions"], dict):
        raise PackError(f"{where}.extensions: expected an object")


def nonempty(value, where):
    if not isinstance(value, str) or not value.strip():
        raise PackError(f"{where}: expected a nonempty string")


def validate_source(source, where="source"):
    if not isinstance(source, dict):
        raise PackError(f"{where}: expected an object")
    kind = source.get("type")
    if kind == "nexus":
        fields(source, ("type", "game", "modId"), ("fileId",), where)
        nonempty(source["game"], where + ".game")
        for key in ("modId", "fileId"):
            if key in source and (type(source[key]) is not int or source[key] <= 0):
                raise PackError(f"{where}.{key}: expected a positive integer")
    elif kind == "github-release":
        fields(source, ("type", "repository", "asset"), ("tag", "channel"), where)
        if not isinstance(source["repository"], str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", source["repository"]):
            raise PackError(f"{where}.repository: expected owner/repo")
        nonempty(source["asset"], where + ".asset")
        if "/" in source["asset"] or "\\" in source["asset"]:
            raise PackError(f"{where}.asset: expected a filename")
        if ("tag" in source) == ("channel" in source):
            raise PackError(f"{where}: specify exactly one of tag or channel")
        if "tag" in source:
            nonempty(source["tag"], where + ".tag")
        elif source["channel"] != "stable":
            raise PackError(f"{where}.channel: only stable is supported")
    elif kind == "local-archive":
        fields(source, ("type", "path"), (), where)
        nonempty(source["path"], where + ".path")
        if "\\" in source["path"]:
            raise PackError(f"{where}.path: use forward slashes")
    else:
        raise PackError(f"{where}: unsupported source type {kind!r}")


def validate_manifest(document):
    fields(document, ("schemaVersion", "name", "game", "dependencies"),
           ("fileOverrides", "registries"), "manifest")
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise PackError("Unsupported manifest schemaVersion")
    nonempty(document["name"], "name")
    game = document["game"]
    fields(game, ("id", "dlc"), ("version",), "game")
    if game["id"] != "cyberpunk2077":
        raise PackError("Only cyberpunk2077 is supported")
    if "version" in game:
        nonempty(game["version"], "game.version")
    if not isinstance(game["dlc"], list) or any(not isinstance(x, str) or not x for x in game["dlc"]):
        raise PackError("game.dlc: expected an array of identifiers")
    if len(set(game["dlc"])) != len(game["dlc"]):
        raise PackError("game.dlc: duplicate identifiers")
    dependencies = document["dependencies"]
    if not isinstance(dependencies, dict):
        raise PackError("dependencies: expected an alias/object mapping")
    for alias, dep in dependencies.items():
        nonempty(alias, "dependency alias")
        fields(dep, ("source",), ("recipe", "options", "integrity"), f"dependencies.{alias}")
        validate_source(dep["source"], f"dependencies.{alias}.source")
        if "integrity" in dep and (not isinstance(dep["integrity"], str) or not re.fullmatch(
                r"sha256:[0-9a-fA-F]{64}", dep["integrity"])):
            raise PackError(f"{alias}.integrity: expected sha256:<64 hex characters>")
        if "recipe" in dep:
            nonempty(dep["recipe"], alias + ".recipe")
            if "\\" in dep["recipe"]:
                raise PackError(f"{alias}.recipe: use forward slashes")
        if "options" in dep and not isinstance(dep["options"], dict):
            raise PackError(f"{alias}.options: expected an object")
    rules = document.get("fileOverrides", [])
    if not isinstance(rules, list):
        raise PackError("fileOverrides: expected an array")
    for rule in rules:
        fields(rule, ("winner", "loser", "paths"), (), "fileOverrides rule")
        if rule["winner"] not in dependencies or rule["loser"] not in dependencies or rule["winner"] == rule["loser"]:
            raise PackError("fileOverrides: winner and loser must be distinct dependency aliases")
        if not isinstance(rule["paths"], list) or not rule["paths"]:
            raise PackError("fileOverrides.paths: expected a nonempty array")
        for path in rule["paths"]:
            safe_relative(path)
    registries = document.get("registries", {})
    if not isinstance(registries, dict):
        raise PackError("registries: expected a name/object mapping")
    for name, registry in registries.items():
        nonempty(name, "registry name")
        fields(registry, ("repository", "revision"), (), f"registries.{name}")
        for key in ("repository", "revision"):
            nonempty(registry[key], f"registries.{name}.{key}")
    return document


def source_from_url(url):
    """Recognize provider identity, never preserve expiring/authenticated URLs."""
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise PackError("Use a public HTTPS Nexus mod/file page or exact GitHub release asset URL")
    if parsed.netloc.lower() == "github.com":
        if parsed.query:
            raise PackError("GitHub release asset URL must not contain query parameters")
        return github_source(url.strip())
    if parsed.netloc.lower() in ("www.nexusmods.com", "nexusmods.com", "next.nexusmods.com"):
        match = re.fullmatch(r"/(?:games/)?([a-z0-9_-]+)/mods/([1-9][0-9]*)/?", parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        if match and set(query) <= {"tab", "file_id"}:
            source = {"type": "nexus", "game": match[1], "modId": int(match[2])}
            if "file_id" in query:
                if len(query["file_id"]) != 1 or not re.fullmatch(r"[1-9][0-9]*", query["file_id"][0]):
                    raise PackError("Nexus file_id must be a positive integer")
                source["fileId"] = int(query["file_id"][0])
            return source
    raise PackError("This schema supports Nexus page URLs and exact GitHub release assets. For other sites, download the archive and select Local archive.")


def local_dependency(archive: Path, manifest: Path):
    archive = archive.resolve()
    if not archive.is_file() or archive.suffix.lower() not in (".zip", ".7z"):
        raise PackError("Select an existing ZIP or 7z archive")
    try:
        reference = Path(os.path.relpath(archive, manifest.resolve().parent)).as_posix()
    except ValueError:  # Different Windows drives need an absolute path.
        reference = archive.as_posix()
    return {"source": {"type": "local-archive", "path": reference}, "integrity": "sha256:" + digest(archive)}


def profile_sources(mo2: Path, profile: str, archive_dirs=(), github_catalog=None):
    """Read explicit provenance only. Return None for unknown, never guess by name."""
    records = json.loads(github_catalog.read_text(encoding="utf-8-sig")) if github_catalog else []
    catalog = {r["Name"].casefold(): r for r in records}
    result = []
    for name in active_mods(safe_join(mo2 / "profiles", profile)):
        ini = read_ini(mo2 / "mods" / name / "meta.ini")
        general = ini["General"] if ini.has_section("General") else {}
        dependency = None
        provenance_path = safe_join(mo2, ".modlists/installed/" + name + ".json")
        if provenance_path.is_file():
            provenance = json.loads(provenance_path.read_text(encoding="utf-8-sig"))
            artifact = provenance["artifact"]
            source = dict(artifact["source"])
            validate_source(source)
            if source["type"] == "local-archive":
                hint = Path(source["path"])
                if not hint.is_absolute():
                    hint = Path(provenance["sourceDocument"]).parent / hint
                source["path"] = hint.resolve().as_posix()
            dependency = {"source": source, "integrity": "sha256:" + artifact["sha256"]}
            recipe_reference = provenance.get("recipeReference")
            if recipe_reference:
                recipe_path = Path(recipe_reference)
                if (recipe_path.is_absolute() and recipe_path.is_file()
                    and digest(recipe_path) == provenance["recipe"]["sha256"]):
                    dependency["recipe"] = recipe_path.resolve().as_posix()
            if provenance.get("options"):
                dependency["options"] = provenance["options"]
            result.append({"name": name, "dependency": dependency})
            continue
        record = catalog.get(name.casefold())
        def normalized_version(value):
            value = value.removeprefix("v")
            if re.fullmatch(r"[0-9.]+", value):
                parts = value.split(".")
                while len(parts) > 1 and parts[-1] == "0":
                    parts.pop()
                return ".".join(parts)
            return value
        if record and (not general.get("version") or normalized_version(general["version"]) == normalized_version(record["Version"])):
            # An explicitly supplied source catalog identifies this installed mod.
            dependency = {"source": github_source(record["Url"]), "integrity": "sha256:" + record["SHA256"].lower()}
        elif general.get("repository", "").lower() == "nexus" and general.get("modid", "").isdigit() and int(general["modid"]) > 0:
            source = {"type": "nexus", "game": general.get("gameName", "cyberpunk2077"), "modId": int(general["modid"])}
            if ini.has_section("installedFiles"):
                section = ini["installedFiles"]
                ids = {int(value) for key, value in section.items() if key.endswith("\\fileid") and value.isdigit() and int(value) > 0}
                if len(ids) == 1:
                    source["fileId"] = ids.pop()
            dependency = {"source": source}
            filename = general.get("installationFile", "").replace("\\", "/").split("/")[-1]
            if filename:
                for directory in archive_dirs:
                    archive = directory / filename
                    if archive.is_file():
                        dependency["integrity"] = "sha256:" + digest(archive)
                        break
        result.append({"name": name, "dependency": dependency})
    return result


def export_manifest(mo2: Path, game: Path, profile: str, destination: Path,
                    selections: dict, progress=lambda message: None):
    """Selections map each enabled mod name to its dependency, or explicit None=skip."""
    if destination.exists():
        raise PackError("Export file already exists; choose a new filename")
    profile_path = safe_join(mo2 / "profiles", profile)
    before = digest(profile_path / "modlist.txt")
    names = active_mods(profile_path)
    missing = set(names) - selections.keys()
    if missing:
        raise PackError("Choose a source or explicitly skip: " + ", ".join(sorted(missing)))
    dependencies, owners, overrides, skipped = {}, {}, {}, []
    for name in names:
        dependency = selections[name]
        if dependency is None:
            skipped.append(name)
            continue
        alias_base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "mod"
        alias, suffix = alias_base, 2
        while alias in dependencies:
            alias = f"{alias_base}-{suffix}"
            suffix += 1
        dependencies[alias] = dependency
        progress(f"Recording source and conflicts: {name}")
        root = mo2 / "mods" / name
        for path in files(root):
            relative = path.relative_to(root).as_posix()
            if relative.casefold() == "meta.ini" or runtime_noise(relative):
                continue
            safe_relative(relative)
            key = relative.casefold()
            if key in owners:
                winner, winning_path = owners[key]
                if digest(path) != digest(winning_path):
                    overrides.setdefault((winner, alias), []).append(relative)
            else:
                owners[key] = (alias, path)
    document = {"schemaVersion": 1, "name": profile,
                "game": {"id": "cyberpunk2077", "dlc": ["phantom-liberty"] if (game / "archive/pc/ep1").is_dir() else []},
                "dependencies": dependencies}
    if overrides:
        document["fileOverrides"] = [{"winner": winner, "loser": loser, "paths": sorted(paths)}
                                     for (winner, loser), paths in sorted(overrides.items())]
    validate_manifest(document)
    if digest(profile_path / "modlist.txt") != before:
        raise PackError("Profile changed during export; retry")
    write_json(destination, document)
    return {"manifest": str(destination), "dependencies": len(dependencies), "skipped": skipped,
            "notice": "Only source references and file conflict rules were exported. Local edits, overwrite/root-only files and unrecorded installer choices are not included."}
