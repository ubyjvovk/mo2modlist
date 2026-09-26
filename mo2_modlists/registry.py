"""Read declarative recipe registries from one pinned Git commit, without checkout."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import urllib.parse

from .acquisition import InputRequired
from .core import PackError, digest, json_digest, safe_join, safe_relative
from .manifest import fields, validate_source


def git(directory, *arguments):
    result = subprocess.run(["git", "-c", "core.hooksPath=", "-c", "credential.helper=", "-c", "protocol.ext.allow=never",
        "-C", str(directory), *arguments], capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"},
        creationflags=0x08000000 if os.name == "nt" else 0)
    if result.returncode:
        raise PackError("Registry Git operation failed; check the repository URL and revision")
    return result.stdout


def snapshot_registry(name, definition, cache, *, offline=False, progress=lambda text: None):
    repository, revision = definition["repository"], definition["revision"]
    parsed = urllib.parse.urlparse(repository)
    if parsed.scheme == "https":
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PackError("Registry URL must not contain credentials or query parameters")
    elif not Path(repository).is_absolute() or not Path(repository).is_dir():
        raise PackError("Registry must be a public HTTPS Git repository or an absolute local repository path")
    if revision.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./-]+", revision) or ".." in revision:
        raise PackError("Invalid registry revision selector")
    directory = safe_join(cache, "registry-git/" + json_digest(repository))
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / "HEAD").exists():
        git(directory, "init", "--bare")
    progress("Pinning registry " + name)
    commit = None
    if re.fullmatch(r"[a-fA-F0-9]{40}", revision):
        try:
            commit = git(directory, "rev-parse", "--verify", revision + "^{commit}").decode().strip()
        except PackError:
            pass
    if commit is None:
        if offline:
            raise InputRequired("registry-cache", "Offline resolution requires a cached exact registry commit", registry=name)
        git(directory, "fetch", "--depth=1", "--no-tags", "--", repository, revision)
        commit = git(directory, "rev-parse", "--verify", "FETCH_HEAD^{commit}").decode().strip()
    index_bytes = git(directory, "show", commit + ":index.json")
    index = json.loads(index_bytes.decode("utf-8-sig"))
    fields(index, ("schemaVersion", "entries"), (), "registry index")
    if index["schemaVersion"] != 1 or not isinstance(index["entries"], list):
        raise PackError("Unsupported registry index")
    target = safe_join(cache, "registry-snapshots/" + json_digest(repository) + "/" + commit)
    entries = []
    paths = {}
    for entry in index["entries"]:
        fields(entry, ("source", "recipe", "sha256", "reason"), (), "registry entry")
        validate_source(entry["source"])
        path = safe_relative(entry["recipe"])
        if not isinstance(entry["reason"], str) or not entry["reason"].strip():
            raise PackError("Supplemental recipe requires a correction/supplement reason")
        if not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]):
            raise PackError("Registry recipe requires an exact SHA-256")
        if path.casefold() in paths and paths[path.casefold()] != entry["sha256"]:
            raise PackError("Registry contains conflicting recipe paths")
        paths[path.casefold()] = entry["sha256"]
        output = safe_join(target, path)
        if output.exists():
            if digest(output) != entry["sha256"]:
                raise PackError("Cached registry recipe was modified")
        else:
            raw = git(directory, "show", commit + ":" + path)
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise PackError("Registry recipe hash differs from its index")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(raw)
        entries.append({**entry, "path": output, "registry": name, "commit": commit})
    return {"repository": repository, "selector": revision, "commit": commit, "indexSha256": hashlib.sha256(index_bytes).hexdigest()}, entries


def registry_recipe(source, entries, ask=None):
    candidates = [entry for entry in entries if entry["source"] == source]
    # Duplicate identical corrections are equivalent; different ones need a choice.
    unique = {entry["sha256"]: entry for entry in candidates}
    if not unique:
        return None
    ordered = [unique[key] for key in sorted(unique)]
    if len(ordered) == 1:
        return ordered[0]
    request = InputRequired("registry-recipe", "Choose the supplemental correction to use", source=source,
        choices=[entry["sha256"] for entry in ordered], labels=[entry["registry"] + ": " + entry["reason"] for entry in ordered])
    if ask is None:
        raise request
    choice = ask(request.request)
    if choice not in unique:
        raise PackError("Invalid registry recipe selection")
    return unique[choice]
