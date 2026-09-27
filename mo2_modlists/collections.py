"""Convert Nexus Collections to source manifests without losing required choices.

Field names follow Nexus-Mods/extension-collections src/types/ICollection.ts.
Collection packages are data only; tools/scripts in them are never executed.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import shutil
import urllib.parse

from .acquisition import InputRequired, json_request, download
from .core import PackError, digest, json_digest, safe_join, safe_relative, write_json
from .manifest import local_dependency, source_from_url, validate_manifest
from .sources import members, stream_member


def collection_reference(value):
    parsed = urllib.parse.urlparse(value.strip())
    revision = None
    if parsed.scheme == "nxm":
        game = parsed.netloc
        match = re.fullmatch(r"/collections/([a-zA-Z0-9]+)/revisions/([1-9][0-9]*)/?", parsed.path)
        if not match:
            raise PackError("Expected nxm://game/collections/slug/revisions/number")
        slug, revision = match[1], int(match[2])
    elif parsed.scheme == "https" and parsed.netloc in ("www.nexusmods.com", "nexusmods.com", "next.nexusmods.com"):
        match = re.fullmatch(r"/(?:games/)?([a-z0-9_-]+)/collections/([a-zA-Z0-9]+)(?:/revisions/([1-9][0-9]*))?/?", parsed.path)
        if not match:
            raise PackError("Expected a Nexus Collection page URL")
        game, slug = match[1], match[2]
        query = urllib.parse.parse_qs(parsed.query)
        if set(query) - {"tab", "revision"}:
            raise PackError("Unsupported collection URL parameters")
        raw_revision = match[3] or query.get("revision", [None])[0]
        if raw_revision is not None:
            if not re.fullmatch(r"[1-9][0-9]*", raw_revision):
                raise PackError("Collection revision must be positive")
            revision = int(raw_revision)
    else:
        raise PackError("Use a Nexus Collection URL, NXM collection link, or downloaded package")
    if game != "cyberpunk2077":
        raise PackError("Only Cyberpunk 2077 collections are supported")
    return {"game": game, "slug": slug, "revision": revision}


def fetch_collection(value, cache: Path, *, headers=None, request=json_request, transfer=download, progress=lambda text: None):
    """Use Nexus's GraphQL revision and supported collection download-link endpoints."""
    reference = collection_reference(value)
    variables = {"slug": reference["slug"]}
    declaration, argument = "", ""
    if reference["revision"] is not None:
        variables["revision"] = reference["revision"]
        declaration, argument = ", $revision: Int!", ", revision: $revision"
    query = "query Collection($slug: String!" + declaration + ") { collectionRevision(slug: $slug" + argument + ") { id revisionNumber downloadLink collection { id slug name } } }"
    data = request("https://api.nexusmods.com/v2/graphql", data={"query": query, "variables": variables}, headers=headers)
    if data.get("errors") or not data.get("data", {}).get("collectionRevision"):
        codes = [error.get("extensions", {}).get("code", "UNKNOWN") for error in data.get("errors", [])]
        raise InputRequired("collection-download", "Nexus did not provide this revision. Use the supported Nexus account/content flow or supply the downloaded collection package.", reference=reference, providerCodes=codes)
    revision = data["data"]["collectionRevision"]
    if revision["collection"]["slug"] != reference["slug"] or (reference["revision"] is not None and revision["revisionNumber"] != reference["revision"]):
        raise PackError("Nexus returned a different collection revision")
    link = revision["downloadLink"]
    if not isinstance(link, str) or not link.startswith("/") or link.startswith("//"):
        raise PackError("Invalid Nexus collection download endpoint")
    resolved = request("https://api.nexusmods.com" + link, headers=headers)
    links = resolved.get("download_links") or [resolved.get("download_link")]
    if not links or not isinstance(links[0], dict) or "URI" not in links[0]:
        raise InputRequired("collection-download", "Nexus did not supply a collection archive URL", reference=reference)
    output = cache / "collections" / f"{reference['slug']}-{revision['revisionNumber']}-{revision['id']}.archive"
    if not output.exists():
        transfer(links[0]["URI"], output, progress)
    identity = {"slug": reference["slug"], "revision": revision["revisionNumber"], "revisionId": revision["id"],
                "collectionId": revision["collection"]["id"], "archiveSha256": digest(output)}
    return output, identity


def read_collection(path: Path):
    if path.suffix.lower() == ".json":
        data = path.read_bytes()
        if len(data) > 16 * 1024 * 1024:
            raise PackError("Collection JSON exceeds the metadata size limit")
    else:
        candidates = [(name, size) for name, size in members(path) if name.casefold().split("/")[-1] == "collection.json"]
        if len(candidates) != 1:
            raise PackError("Collection package must contain exactly one collection.json")
        name, size = candidates[0]
        if size > 16 * 1024 * 1024:
            raise PackError("Collection JSON exceeds the metadata size limit")
        buffer = io.BytesIO()
        stream_member(path, name, buffer)
        data = buffer.getvalue()
    document = json.loads(data.decode("utf-8-sig"))
    if not isinstance(document, dict) or not isinstance(document.get("info"), dict) or not isinstance(document.get("mods"), list):
        raise PackError("Expected the full Nexus collection info/mods document")
    return document


def match_reference(reference, mods):
    """Resolve only explicit provider identities or exact archive metadata.

    Vortex's fuzzy filename and version-range matching needs a separate candidate
    resolver. Ambiguous references are deliberately not matched by display name.
    """
    if not isinstance(reference, dict):
        return None
    allowed = {"repo", "fileMD5", "fileSize", "gameId", "versionMatch", "logicalFileName",
               "tag", "idHint", "md5Hint", "description", "instructions"}
    if reference.keys() - allowed:
        return None
    identifiers = set(reference) & {"repo", "fileMD5", "logicalFileName", "tag"}
    if not identifiers:
        return None
    result = []
    for alias, mod in mods.items():
        source = mod.get("source", {})
        if "repo" in reference:
            repo = reference["repo"]
            if repo.get("repository", "").casefold() != "nexus" or source.get("type") != "nexus":
                continue
            if not repo.get("fileId") or str(repo["fileId"]) != str(source.get("fileId")):
                continue
            if "modId" in repo and str(repo["modId"]) != str(source.get("modId")):
                continue
            if "gameId" in repo and repo["gameId"] != mod.get("domainName"):
                continue
        comparable = {"fileMD5": source.get("md5"), "fileSize": source.get("fileSize"),
                      "logicalFileName": source.get("logicalFilename"), "tag": source.get("tag"), "gameId": mod.get("domainName")}
        if any(reference[key] != value for key, value in comparable.items() if key in reference):
            continue
        if reference.get("versionMatch", "*") not in ("*", mod.get("version"), "=" + mod.get("version", "")):
            continue
        result.append(alias)
    return result[0] if len(result) == 1 else None


def bundled_dependency(package, mod, cache, progress=lambda text: None):
    """Extract an exact embedded source archive; never execute bundled content."""
    expression = mod.get("source", {}).get("fileExpression")
    if not isinstance(expression, str):
        raise InputRequired("collection-bundle", "Bundled mod has no exact archive filename")
    relative = safe_relative(expression.replace("\\", "/"))
    index = list(members(package))
    documents = [name for name, _ in index if name.casefold().split("/")[-1] == "collection.json"]
    if len(documents) != 1:
        raise PackError("Expected one collection.json to locate bundled sources")
    prefix = documents[0].rsplit("/", 1)[0] + "/" if "/" in documents[0] else ""
    wanted = (prefix + "bundled/" + relative).casefold()
    matches = [(name, size) for name, size in index if name.casefold() == wanted]
    if len(matches) != 1:
        raise InputRequired("collection-bundle", "Exact bundled archive is absent", member=wanted)
    member, size = matches[0]
    suffix = Path(member).suffix.lower()
    if suffix not in (".zip", ".7z"):
        raise InputRequired("collection-bundle", "Bundled source is not a supported ZIP/7z archive", member=member)
    package_sha = digest(package)
    destination = safe_join(cache, "collection-bundles/" + json_digest({"package": package_sha, "member": member}) + suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = stream_member(package, member, progress=progress)
    if destination.exists():
        if destination.stat().st_size != size or digest(destination) != expected:
            raise PackError("Cached bundled archive was modified")
    else:
        if shutil.disk_usage(destination.parent).free < size:
            raise PackError("Not enough space for bundled source archive")
        temporary = destination.with_name(destination.name + ".partial")
        with temporary.open("wb") as output:
            actual = stream_member(package, member, output, progress=progress)
        if actual != expected or temporary.stat().st_size != size:
            raise PackError("Bundled archive changed during extraction")
        os.replace(temporary, destination)
    return {"source": {"type": "local-archive", "path": destination.resolve().as_posix()},
        "integrity": "sha256:" + expected,
        "extensions": {"nexusBundledArtifact": {"collectionArchiveSha256": package_sha, "member": member}}}


def installer_fields(mod):
    fields = [key for key in ("choices", "patches", "instructions", "hashes") if mod.get(key)]
    if mod.get("details", {}).get("type"):
        fields.append("details")
    if mod.get("source", {}).get("instructions"):
        fields.append("source")
    return fields


def entry_source(mod, decision, game):
    if decision.get("source") is not None:
        return decision["source"]
    raw = mod.get("source", {})
    if raw.get("type") == "nexus" and raw.get("modId") and raw.get("fileId"):
        return {"type": "nexus", "game": mod.get("domainName", game), "modId": int(raw["modId"]), "fileId": int(raw["fileId"])}
    if raw.get("type") in ("direct", "browse") and raw.get("url"):
        try:
            return source_from_url(raw["url"])
        except PackError:
            pass
    return None


def handoff_complete(decision, source, required_fields, collection_sha):
    handoff = decision.get("handoff", {})
    return bool(source and source.get("type") == "local-archive" and "recipe" in decision and "integrity" in decision
        and handoff.get("collectionSha256") == collection_sha and handoff.get("method") == "prepared-archive"
        and set(handoff.get("handled", [])) == set(required_fields)
        and isinstance(handoff.get("note"), str) and handoff["note"].strip())


def convert_collection(document, *, identity=None, decisions=None):
    """Return a review draft. Nonempty pending means no installable manifest yet.

Decisions are keyed by stable collection index alias (`mod-0001` etc). Sources
may be replaced and optional mods included/excluded. Installer data is never
silently discarded; its explicit recipe handoff is part of later resolution.
"""
    decisions = decisions or {}
    collection_sha = json_digest(document)
    info = document["info"]
    game = info.get("domainName")
    if game != "cyberpunk2077":
        raise PackError("Collection game is not Cyberpunk 2077")
    pending, notes, dependencies, retained = [], [], {}, {}
    normalized_rules, path_winners, handoffs = [], [], {}
    all_mods = {f"mod-{index:04d}": mod for index, mod in enumerate(document["mods"], 1)}
    manifest = {"schemaVersion": 1, "name": info["name"], "game": {"id": game, "dlc": []}, "dependencies": dependencies}
    versions = info.get("gameVersions") or []
    if len(versions) == 1:
        manifest["game"]["version"] = versions[0]
    elif len(versions) > 1:
        selected_version = decisions.get("_collection", {}).get("gameVersion")
        if selected_version in versions:
            manifest["game"]["version"] = selected_version
        else:
            pending.append({"kind": "game-version", "choices": versions})
    for index, mod in enumerate(document["mods"], 1):
        alias = f"mod-{index:04d}"
        decision = decisions.get(alias, {})
        if mod.get("optional"):
            if "include" not in decision:
                pending.append({"kind": "optional-mod", "alias": alias, "name": mod.get("name", alias)})
                continue
            if not decision["include"]:
                notes.append(f"Excluded optional mod: {mod.get('name', alias)}")
                continue
        elif decision.get("include") is False:
            pending.append({"kind": "required-mod", "alias": alias, "message": "A required collection entry cannot be silently skipped"})
            continue
        retained[alias] = mod
        raw = mod.get("source", {})
        source = entry_source(mod, decision, game)
        if raw.get("type") == "nexus" and raw.get("updatePolicy", "exact") != "exact":
            notes.append(f"{alias}: using collection's exact recorded file; updates require an explicit re-resolve")
        if source is None:
            pending.append({"kind": "source", "alias": alias, "name": mod.get("name", alias), "sourceType": raw.get("type"), "message": "Provide a supported source or a local archive"})
            continue
        dep = {"source": source}
        for field in ("integrity", "recipe", "options", "extensions"):
            if field in decision:
                dep[field] = decision[field]
        if isinstance(mod.get("name"), str) and mod["name"].strip():
            dep["extensions"] = {**dep.get("extensions", {}), "displayName": mod["name"]}
        dependencies[alias] = dep
        for path in mod.get("fileOverrides", []):
            path_winners.append({"winner": alias, "path": safe_relative(path.replace("\\", "/"))})
        unsupported = installer_fields(mod)
        if unsupported:
            handoff = decision.get("handoff", {})
            if handoff_complete(decision, source, unsupported, collection_sha):
                handoffs[alias] = {**handoff, "originalEntrySha256": json_digest(mod)}
                notes.append(f"{alias}: installer output supplied through an explicit prepared-archive handoff")
            else:
                pending.append({"kind": "installer-data", "alias": alias, "fields": unsupported,
                                "message": "Supply an archive/recipe containing the chosen installer and patch outputs, with an explicit manual-handoff record"})
        if mod.get("domainName", game) != game:
            pending.append({"kind": "foreign-game", "alias": alias})
    for rule in document.get("modRules", []):
        source = match_reference(rule.get("source"), all_mods)
        target = match_reference(rule.get("reference"), all_mods)
        kind = rule.get("type")
        if source is None or target is None or kind not in ("before", "after", "requires", "conflicts", "recommends"):
            pending.append({"kind": "collection-rules", "rule": rule, "message": "Rule identity/version is ambiguous or unsupported"})
        elif source not in dependencies:
            notes.append(f"Rule source {source} is excluded or unresolved")
        elif target not in dependencies:
            if kind == "requires":
                pending.append({"kind": "required-mod", "alias": target, "requiredBy": source})
            else:
                notes.append(f"{source}: {kind} references an excluded/unresolved mod {target}")
        elif kind == "conflicts":
            pending.append({"kind": "collection-conflict", "source": source, "target": target})
        else:
            normalized_rules.append({"source": source, "target": target, "type": kind})
    if "modRules" not in document:
        pending.append({"kind": "full-package", "message": "This may be the filtered website preview. Supply the full collection package to preserve installer and ordering information."})
    config = document.get("collectionConfig", {})
    if (not isinstance(config, dict) or set(config) - {"recommendNewProfile"}
            or ("recommendNewProfile" in config and type(config["recommendNewProfile"]) is not bool)):
        pending.append({"kind": "collection-extension", "field": "collectionConfig",
                        "message": "Unknown Collection configuration requires review"})
    elif config:
        notes.append("Collection profile recommendation retained; MO2 Modlists always imports into a new profile")
    known = {"info", "mods", "modRules", "collectionConfig"}
    for key in sorted(document.keys() - known):
        if document[key]:
            pending.append({"kind": "collection-extension", "field": key})
    manifest["extensions"] = {"nexusCollection": {"schemaVersion": 1, "identity": identity or {},
        "metadataSha256": collection_sha, "collectionConfig": config, "rules": normalized_rules, "pathWinners": path_winners,
        "manualHandoffs": handoffs, "externalInstructions": info.get("installInstructions") or ""}}
    validate_manifest(manifest)
    return {"manifest": manifest, "pending": pending, "notes": notes,
            "collectionSha256": collection_sha, "retainedInstructions": document, "decisions": decisions,
            "complete": not pending}


def write_collection_manifest(draft, destination: Path):
    if draft["pending"]:
        raise InputRequired("collection-review", "Collection conversion has unresolved choices; nothing has been installed", pending=draft["pending"])
    if destination.exists():
        raise PackError("Manifest destination exists")
    write_json(destination, validate_manifest(draft["manifest"]))
    return destination
