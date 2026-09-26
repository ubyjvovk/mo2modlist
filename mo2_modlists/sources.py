"""Map installed content to pinned archives and reconstruct missing blobs.

Archive members are streamed, never extracted by a third-party tool into the
filesystem. Installed path mappings remain in the lock, preserving FOMOD output.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import urllib.parse
import urllib.request
import uuid
import zipfile

from .core import PackError, digest, entry_groups, export_profile, load_bundle, read_ini, safe_relative, safe_join, verify_bundle, write_json


def export_source_profile(mo2, game, profile, destination, archive_dirs, github_manifest=None,
                          progress=lambda text: None):
    if destination.exists():
        raise PackError("Export destination already exists")
    snapshot = destination.with_name(destination.name + ".snapshot-" + uuid.uuid4().hex)
    base_result = export_profile(mo2, game, profile, snapshot, progress=progress)
    try:
        result = compact_bundle(snapshot, destination, archive_dirs, github_manifest, progress)
        return {**base_result, **result, "bundle": str(destination)}
    finally:
        # Only the new UUID-owned snapshot created above is removed.
        shutil.rmtree(snapshot)


def seven_zip():
    candidate = shutil.which("7z")
    if candidate:
        return candidate
    candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "7-Zip/7z.exe"
    if candidate.is_file():
        return str(candidate)
    raise PackError("7-Zip is needed to read this .7z source archive")


def members(path: Path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            seen = set()
            for member in archive.infolist():
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise PackError("Archive links are unsupported")
                safe_relative(member.filename.rstrip("/"))
                if member.is_dir():
                    continue
                name = safe_relative(member.filename)
                if name.casefold() in seen:
                    raise PackError(f"Duplicate archive member: {name}")
                seen.add(name.casefold())
                yield name, member.file_size
        return
    command = [seven_zip(), "l", "-slt", "-ba", "-p-", "-sccUTF-8", "--", str(path)]
    result = subprocess.run(command, capture_output=True, encoding="utf-8", creationflags=0x08000000 if os.name == "nt" else 0)
    if result.returncode:
        raise PackError(f"Cannot list archive {path.name}")
    seen = set()
    for block in result.stdout.replace("\r\n", "\n").split("\n\n"):
        info = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if "Path" not in info:
            continue
        if "Symbolic Link" in info or "Hard Link" in info:
            raise PackError("Archive links are unsupported")
        name = safe_relative(info["Path"].replace("\\", "/"))
        if info.get("Folder") == "+" or info.get("Attributes", "").startswith("D"):
            continue
        if name.casefold() in seen:
            raise PackError(f"Duplicate archive member: {name}")
        seen.add(name.casefold())
        yield name, int(info["Size"])


def stream_member(path: Path, member: str, output=None, progress=lambda text: None):
    safe_relative(member)
    h = hashlib.sha256()
    def consume(stream):
        while chunk := stream.read(1024 * 1024):
            progress("Reading " + member)
            h.update(chunk)
            if output is not None:
                output.write(chunk)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive, archive.open(member) as stream:
            consume(stream)
    else:
        process = subprocess.Popen([seven_zip(), "x", "-so", "-spd", "-p-", "--", str(path), member],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   creationflags=0x08000000 if os.name == "nt" else 0)
        try:
            consume(process.stdout)
            if process.wait() != 0:
                raise PackError(f"Cannot read {member} from {path.name}")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()
    return h.hexdigest()


def github_source(url: str):
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.scheme != "https" or parsed.netloc != "github.com" or len(parts) != 6 or parts[2:4] != ["releases", "download"]:
        raise PackError("Expected an exact GitHub release asset URL")
    return {"type": "github-release", "repository": "/".join(parts[:2]),
            "tag": urllib.parse.unquote(parts[4]), "asset": urllib.parse.unquote(parts[5])}


def archive_source(path: Path, github_records: dict):
    if path.name in github_records:
        record = github_records[path.name]
        if digest(path) != record["SHA256"].lower():
            raise PackError(f"GitHub archive differs from its recorded digest: {path.name}")
        return github_source(record["Url"])
    metadata = read_ini(path.with_name(path.name + ".meta"))
    section = metadata["General"] if metadata.has_section("General") else {}
    if section.get("repository", "").lower() == "nexus" and section.get("fileID", "").isdigit():
        return {"type": "nexus", "game": section["gameName"],
                "modId": int(section["modID"]), "fileId": int(section["fileID"])}
    return {"type": "local-archive", "filename": path.name}


def compact_bundle(bundle: Path, destination: Path, archive_dirs: list[Path], github_manifest: Path | None = None,
                   progress=lambda text: None):
    lock = verify_bundle(bundle)
    if destination.exists():
        raise PackError("Compact bundle destination already exists")
    wanted = {entry["sha256"]: entry["size"] for group in entry_groups(lock) for entry in group}
    sizes = set(wanted.values())
    records = json.loads(github_manifest.read_text()) if github_manifest else []
    github_records = {urllib.parse.unquote(urllib.parse.urlparse(r["Url"]).path.split("/")[-1]): r for r in records}
    artifact_records, blob_sources = {}, {}
    for directory in archive_dirs:
        if not directory.is_dir():
            continue
        for archive in sorted(directory.iterdir()):
            if archive.suffix.lower() not in (".zip", ".7z"):
                continue
            if archive.name not in github_records and not archive.with_name(archive.name + ".meta").is_file():
                continue
            progress(f"Matching source archive {archive.name}")
            hits = {}
            for name, size in members(archive):
                if size not in sizes:
                    continue
                h = stream_member(archive, name)
                if h in wanted and h not in blob_sources:
                    hits[h] = name
            if hits:
                archive_hash = digest(archive)
                artifact_records[archive_hash] = {"sha256": archive_hash, "size": archive.stat().st_size,
                                                 "filename": archive.name, "source": archive_source(archive, github_records)}
                blob_sources.update({h: {"artifact": archive_hash, "member": member} for h, member in hits.items()})
    stage = destination.with_name(destination.name + ".partial-" + uuid.uuid4().hex)
    (stage / "blobs").mkdir(parents=True)
    shutil.copyfile(bundle / "modlist.json", stage / "modlist.json")
    lock["sourceArtifacts"] = artifact_records
    lock["blobSources"] = blob_sources
    for h in wanted.keys() - blob_sources.keys():
        shutil.copyfile(bundle / "blobs" / h, stage / "blobs" / h)
    write_json(stage / "modlist.lock.json", lock)
    stage.rename(destination)
    return {"artifacts": len(artifact_records), "sourceBackedFiles": len(blob_sources),
            "retainedBlobs": len(wanted) - len(blob_sources),
            "retainedBytes": sum(wanted[h] for h in wanted.keys() - blob_sources.keys()),
            "originalBytes": sum(wanted.values())}


def download_github(source: dict, destination: Path):
    repository = source["repository"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository):
        raise PackError("Invalid GitHub repository")
    url = "https://api.github.com/repos/" + repository + "/releases/tags/" + urllib.parse.quote(source["tag"], safe="")
    headers = {"User-Agent": "MO2-Modlists/0.1", "Accept": "application/vnd.github+json"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        release = json.load(response)
    candidates = [a for a in release["assets"] if a["name"] == source["asset"]]
    if len(candidates) != 1:
        raise PackError("Pinned GitHub release asset is unavailable or ambiguous")
    download_url = candidates[0]["browser_download_url"]
    if urllib.parse.urlparse(download_url).scheme != "https":
        raise PackError("GitHub returned a non-HTTPS asset URL")
    with urllib.request.urlopen(urllib.request.Request(download_url, headers={"User-Agent": headers["User-Agent"]}), timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def hydrate_bundle(bundle: Path, cache: Path, archive_dirs: list[Path], download=False,
                   progress=lambda text: None, nexus_fetcher=None):
    lock = load_bundle(bundle)
    artifacts = lock.get("sourceArtifacts", {})
    blob_sources = lock.get("blobSources", {})
    for group in entry_groups(lock):
        for entry in group:
            safe_relative(entry["path"])
            if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                raise PackError("Invalid installed-file digest")
    cache.mkdir(parents=True, exist_ok=True)
    (bundle / "blobs").mkdir(exist_ok=True)
    resolved, member_indexes = {}, {}
    needed = {h for group in entry_groups(lock) for e in group
              if not (bundle / "blobs" / (h := e["sha256"])).exists()}
    for h in sorted(needed):
        if h not in blob_sources:
            raise PackError(f"Missing local delta blob with no source recipe: {h}")
        mapping = blob_sources[h]
        artifact_hash = mapping["artifact"]
        if artifact_hash not in artifacts or not all(c in "0123456789abcdef" for c in artifact_hash) or len(artifact_hash) != 64:
            raise PackError("Invalid archive identity")
        record = artifacts[artifact_hash]
        if artifact_hash not in resolved:
            archive = safe_join(cache, artifact_hash)
            if not archive.is_file():
                name = safe_relative(record["filename"])
                if "/" in name:
                    raise PackError("Expected a source archive filename")
                candidates = [folder / name for folder in archive_dirs if (folder / name).is_file()]
                matched = next((p for p in candidates if digest(p) == artifact_hash), None)
                temporary = cache / (artifact_hash + ".partial-" + uuid.uuid4().hex)
                if matched:
                    shutil.copyfile(matched, temporary)
                elif download and record["source"]["type"] == "github-release":
                    progress(f"Downloading GitHub asset {name}")
                    download_github(record["source"], temporary)
                elif download and record["source"]["type"] == "nexus" and nexus_fetcher is not None:
                    progress(f"Waiting for MO2 to download {name}")
                    acquired = Path(nexus_fetcher(record["source"]))
                    if not acquired.is_file():
                        raise PackError("MO2 did not return a downloaded archive")
                    shutil.copyfile(acquired, temporary)
                else:
                    raise PackError(f"Supply exact archive '{name}' in a download directory. Source: {record['source']}")
                if digest(temporary) != artifact_hash:
                    temporary.unlink()
                    raise PackError(f"Source archive hash mismatch: {name}")
                os.replace(temporary, archive)
            if digest(archive) != artifact_hash:
                raise PackError(f"Cached archive hash mismatch: {record['filename']}")
            resolved[artifact_hash] = archive
            member_indexes[artifact_hash] = {name for name, _ in members(archive)}
        progress(f"Restoring {mapping['member']}")
        # Verify membership before -so so missing/wildcard members cannot silently match others.
        available = member_indexes[artifact_hash]
        if mapping["member"] not in available:
            raise PackError("Pinned member is missing from its source archive")
        temporary = safe_join(bundle, "blobs/" + h + ".partial-" + uuid.uuid4().hex)
        with temporary.open("wb") as output:
            actual = stream_member(resolved[artifact_hash], mapping["member"], output)
        if actual != h:
            temporary.unlink()
            raise PackError("Reconstructed installed file hash mismatch")
        os.replace(temporary, safe_join(bundle, "blobs/" + h))
    verify_bundle(bundle)
    return {"reconstructedBlobs": len(needed), "archivesUsed": len(resolved)}
