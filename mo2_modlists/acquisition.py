"""Pinned source acquisition and a hash-addressed archive cache."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .core import PackError, digest, json_digest, read_ini, safe_join, write_json
from .manifest import validate_source


class InputRequired(PackError):
    def __init__(self, kind, message, **context):
        super().__init__(message)
        self.request = {"kind": kind, "message": message, **context}


def json_request(url, *, data=None, headers=None, opener=urllib.request.urlopen):
    request_headers = {"User-Agent": "MO2-Modlists/0.4", "Accept": "application/json", **(headers or {})}
    payload = None if data is None else json.dumps(data).encode()
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    try:
        with opener(urllib.request.Request(url, data=payload, headers=request_headers), timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise InputRequired("authentication", "The provider requires an authenticated supported download/metadata flow.") from None
        if exc.code == 429:
            raise InputRequired("rate-limit", "Provider rate limit reached. Retry after its reset; cached archives remain available.", retryAfter=exc.headers.get("Retry-After")) from None
        raise PackError(f"Provider request failed (HTTP {exc.code})") from None


def download(url, target: Path, progress=lambda text: None, opener=urllib.request.urlopen):
    """Resume only with a server validator. Never persist expiring download URLs."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise PackError("Download requires a public HTTPS URL without embedded credentials")
    target.parent.mkdir(parents=True, exist_ok=True)
    part, state_file = target.with_suffix(".partial"), target.with_suffix(".download.json")
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    offset = part.stat().st_size if part.exists() else 0
    validator = state.get("validator")
    headers = {"User-Agent": "MO2-Modlists/0.4", "Accept-Encoding": "identity"}
    if offset and validator:
        headers.update(Range=f"bytes={offset}-", **{"If-Range": validator})
    else:
        offset = 0
    try:
        response = opener(urllib.request.Request(url, headers=headers), timeout=45)
    except urllib.error.HTTPError as exc:
        # A completed/changed partial cannot be trusted merely because Range failed.
        if exc.code == 416 and offset:
            response = opener(urllib.request.Request(url, headers={"User-Agent": headers["User-Agent"]}), timeout=45)
            offset = 0
        else:
            raise PackError(f"Archive download failed (HTTP {exc.code}); verified cache is preserved") from None
    with response:
        status = response.status
        etag = response.headers.get("ETag")
        new_validator = etag if etag and not etag.startswith("W/") else response.headers.get("Last-Modified")
        if status == 206:
            content_range = response.headers.get("Content-Range", "")
            if not offset or not content_range.startswith(f"bytes {offset}-") or new_validator != validator:
                raise PackError("Server returned an unverifiable partial response; retry from a new download")
        elif status == 200:
            offset = 0
        else:
            raise PackError(f"Unexpected download response {status}")
        if not offset:
            # Truncate old bytes before publishing a new validator. A process
            # crash between these writes must never relabel an old partial.
            with part.open("wb") as output:
                output.flush()
                os.fsync(output.fileno())
        write_json(state_file, {"validator": new_validator})
        length = response.headers.get("Content-Length")
        received = 0
        with part.open("ab") as output:
            while chunk := response.read(1024 * 1024):
                progress(f"Downloading archive: {(offset + received) // 1048576} MiB")
                output.write(chunk)
                received += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        if length is not None and received != int(length):
            raise PackError("Incomplete download; its validated partial is retained for resume")
    os.replace(part, target)
    state_file.unlink(missing_ok=True)


def reference_path(path: str, declaring_file: Path):
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (declaring_file.resolve().parent / candidate).resolve()


class ArtifactStore:
    def __init__(self, root: Path, archives=(), *, offline=False, nexus_fetch=None,
                 nexus_metadata=None, manual_fetch=None, request=json_request, transfer=download, progress=lambda text: None):
        self.root = root.resolve()
        self.archives = [p.resolve() for p in archives]
        self.offline = offline
        self.nexus_fetch, self.nexus_metadata = nexus_fetch, nexus_metadata
        self.manual_fetch = manual_fetch
        self.request, self.transfer, self.progress = request, transfer, progress

    def path(self, sha256):
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise PackError("Invalid archive digest")
        return safe_join(self.root, "archives/" + sha256)

    def verified(self, record):
        path = self.path(record["sha256"])
        if not path.is_file():
            return None
        if path.stat().st_size != record["size"] or digest(path) != record["sha256"]:
            raise PackError("Cached archive was modified; supply the exact original archive")
        return path

    def store(self, source_path, source, expected=None, **metadata):
        self.progress("Verifying source archive")
        actual = digest(source_path)
        if expected and actual != expected:
            raise PackError("Source archive differs from the pinned SHA-256")
        target = self.path(actual)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if digest(target) != actual:
                raise PackError("Cached archive was modified")
        else:
            temporary = target.with_name(target.name + ".copy-" + uuid.uuid4().hex)
            try:
                shutil.copyfile(source_path, temporary)
                if digest(temporary) != actual:
                    raise PackError("Archive changed while copying")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return {"source": source, "sha256": actual, "size": target.stat().st_size,
                "integrityKind": "provided" if expected else "locally-observed", **metadata}

    def local_nexus(self, source):
        for directory in self.archives:
            if not directory.is_dir():
                continue
            for sidecar in sorted(directory.glob("*.meta")):
                ini = read_ini(sidecar)
                general = ini["General"] if ini.has_section("General") else {}
                # Read only stable provider identities. Never return sidecar download URLs.
                if (general.get("gameName", "").casefold() == source["game"].casefold()
                    and general.get("modID") == str(source["modId"])
                    and general.get("fileID") == str(source.get("fileId"))):
                    archive = sidecar.with_suffix("")
                    if archive.is_file():
                        return archive
        return None

    def acquire(self, dependency, declaring_file: Path, locked=None):
        source = dict(locked["source"] if locked else dependency["source"])
        validate_source(source)
        expected = locked["sha256"] if locked else dependency.get("integrity", "").removeprefix("sha256:").lower() or None
        if locked:
            available = self.verified(locked)
            if available:
                return locked
        if source["type"] == "local-archive":
            path = reference_path(source["path"], declaring_file)
            if not path.is_file() and expected and self.path(expected).is_file():
                path = self.path(expected)
            if not path.is_file():
                request = InputRequired("local-archive", "Supply the referenced local archive", source=source, expectedSha256=expected)
                if self.manual_fetch is None:
                    raise request
                path = Path(self.manual_fetch(request.request))
            result = self.store(path, source, expected)
        elif source["type"] == "nexus":
            if "fileId" not in source:
                raise InputRequired("nexus-file", "Select an exact Nexus file; a mod page may contain independent variants/addons", source=source)
            provider_integrity = False
            if not expected and not self.offline and hasattr(self.nexus_metadata, "artifact_integrity"):
                expected = self.nexus_metadata.artifact_integrity(source)
                provider_integrity = bool(expected)
            path = self.local_nexus(source)
            if path is None and expected:
                cached = self.path(expected)
                if cached.is_file() and digest(cached) == expected:
                    path = cached
                else:
                    for directory in self.archives:
                        if not directory.is_dir():
                            continue
                        for archive in sorted(directory.iterdir()):
                            if archive.is_file() and archive.suffix.lower() in ('.zip', '.7z') and digest(archive) == expected:
                                path = archive
                                break
                        if path is not None:
                            break
            if path is None:
                if self.offline or self.nexus_fetch is None:
                    request = InputRequired("nexus-archive", "Supply the exact downloaded Nexus archive", source=source, expectedSha256=expected)
                    if self.manual_fetch is None:
                        raise request
                    path = Path(self.manual_fetch(request.request))
                else:
                    path = Path(self.nexus_fetch(source))
            result = self.store(path, source, expected)
            if provider_integrity:
                result['integrityKind'] = 'nexus-published-scan-hash'
        else:
            if self.offline:
                raise InputRequired("offline-cache", "This locked GitHub archive is not cached", source=source, expectedSha256=expected)
            repository = source["repository"]
            selector = "tags/" + urllib.parse.quote(source["tag"], safe="") if "tag" in source else "latest"
            release = self.request(f"https://api.github.com/repos/{repository}/releases/{selector}")
            if release.get("draft") or (source.get("channel") == "stable" and release.get("prerelease")):
                raise PackError("GitHub returned an ineligible release")
            candidates = [asset for asset in release.get("assets", []) if asset["name"] == source["asset"]]
            if len(candidates) != 1:
                raise PackError("Exact GitHub release asset is unavailable or ambiguous")
            asset = candidates[0]
            identities = {"releaseId": release["id"], "assetId": asset["id"]}
            if locked and any(locked.get(k) != v for k, v in identities.items()):
                raise PackError("Locked GitHub release or asset identity changed")
            pinned = {"type": "github-release", "repository": repository, "tag": release["tag_name"], "asset": asset["name"]}
            target = self.root / "downloads" / (json_digest({"source": pinned, **identities}) + ".archive")
            if not target.is_file() or (expected and digest(target) != expected):
                self.transfer(asset["browser_download_url"], target, self.progress)
            result = self.store(target, pinned, expected, **identities)
        if locked and (result["sha256"] != locked["sha256"] or result["size"] != locked["size"]):
            raise PackError("Locked archive changed")
        return locked or result
