"""Public HTTPS manifest snapshots and read-only upstream update checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from .core import PackError, digest, json_digest, safe_join, write_json
from .manifest import validate_manifest

MAX_JSON = 2 * 1024 * 1024
MAX_DOCUMENTS = 128


def manifest_url(value):
    value = str(value).strip()
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or any(ord(c) < 33 for c in value) or "\\" in value):
        raise PackError("Use a public HTTPS manifest URL without credentials or a fragment")
    if parsed.hostname.lower() == "github.com" and "/blob/" in parsed.path:
        if parsed.query not in ("", "raw=1", "raw=true"):
            raise PackError("Use a public GitHub file URL without query credentials")
        parts = parsed.path.split("/")
        if len(parts) < 6 or parts[3] != "blob":
            raise PackError("Invalid GitHub file URL")
        value = "https://raw.githubusercontent.com/" + "/".join(parts[1:3] + parts[4:])
        parsed = urllib.parse.urlsplit(value)
    if parsed.query:
        raise PackError("Manifest URLs must not contain query parameters; use a stable public file URL")
    return urllib.parse.urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", "", ""))


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Public release assets use temporary signed CDN redirects. Validate the
        # transport but never retain the query in snapshot metadata or origins.
        parsed = urllib.parse.urlsplit(newurl)
        manifest_url(urllib.parse.urlunsplit(parsed._replace(query="")))
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_json(url):
    url = manifest_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "MO2-Modlists/0.9", "Accept": "application/json", "Accept-Encoding": "identity"})
    try:
        with urllib.request.build_opener(HTTPSRedirects()).open(request, timeout=30) as response:
            redirected = urllib.parse.urlsplit(response.geturl())
            manifest_url(urllib.parse.urlunsplit(redirected._replace(query="")))
            final_url = url if redirected.query else manifest_url(response.geturl())
            if response.status != 200:
                raise PackError("Manifest server did not return a complete document")
            raw = response.read(MAX_JSON + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PackError("Cannot fetch manifest metadata: " + str(exc)) from None
    if len(raw) > MAX_JSON:
        raise PackError("Manifest/recipe exceeds the 2 MiB limit")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise PackError("URL did not return JSON; use the raw file URL, not a website page") from None
    if not isinstance(document, dict):
        raise PackError("Manifest/recipe URL must return a JSON object")
    return document, hashlib.sha256(raw).hexdigest(), final_url


def document_references(document, base):
    from .packages import validate_package
    validate_package(document)
    def visit(doc):
        config = doc['mo2']
        for source in config.get('sources', []):
            if source['type'] == 'local-archive':
                raise PackError('A remote package cannot read local archives')
        for i, item in enumerate(config.get('packages', [])):
            if isinstance(item, dict):
                yield from visit(item)
            else:
                if '\\' in item or re.match(r'^[A-Za-z]:', item):
                    raise PackError('Remote package references must be HTTPS URLs or URL-relative paths')
                yield config['packages'], i, manifest_url(urllib.parse.urljoin(base, item))
    yield from visit(document)


def verified_snapshot(root, identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise PackError("Invalid cached manifest snapshot identity")
    directory = safe_join(root, "snapshots/" + identifier)
    metadata = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
    for name, sha in metadata["files"].items():
        path = safe_join(directory, name)
        if not path.is_file() or digest(path) != sha:
            raise PackError("Cached manifest snapshot was modified")
    from .packages import validate_package
    validate_package(json.loads((directory / "modlist.json").read_text(encoding="utf-8")))
    return directory / "modlist.json"


def fetch_manifest(url, cache, *, offline=False, fetch=None, progress=lambda text: None):
    fetch = fetch or fetch_json
    url = manifest_url(url)
    root = Path(cache).resolve() / "manifest-urls"
    latest = safe_join(root, "latest/" + json_digest(url) + ".json")
    if offline:
        if not latest.is_file():
            raise PackError("No cached snapshot for this manifest URL")
        return verified_snapshot(root, json.loads(latest.read_text())["snapshot"])
    documents, active = {}, set()
    def collect(address, depth=0):
        if address in active:
            raise PackError("Cyclic remote package references")
        if address in documents:
            return
        if len(documents) >= MAX_DOCUMENTS or depth > 24:
            raise PackError("Remote manifest exceeds the package count/depth limit")
        active.add(address)
        progress("Fetching manifest metadata: " + address)
        document, sha, final_url = fetch(address)
        manifest_url(final_url)
        from .packages import validate_package
        validate_package(document)
        documents[address] = (deepcopy(document), sha, final_url)
        for _, _, reference in document_references(document, final_url):
            collect(reference, depth + 1)
        active.remove(address)
    collect(url)
    resources = {address: data[1] for address, data in documents.items()}
    identifier = json_digest({"format": 1, "url": url, "resources": resources,
                              "bases": {address: data[2] for address, data in documents.items()}})
    directory = safe_join(root, "snapshots/" + identifier)
    names = {address: "modlist.json" if address == url else "packages/" + json_digest(address) + ".json" for address in documents}
    for address, (document, _, final_url) in documents.items():
        for container, key, reference in document_references(document, final_url):
            container[key] = safe_join(directory, names[reference]).as_posix()
        if address == url:
            for definition in document.get("registries", {}).values():
                manifest_url(definition["repository"])
            from .packages import is_package
            config = document['mo2'] if is_package(document) else document
            config.setdefault("extensions", {})["remoteManifests"] = {
                url: {"url": url, "resources": resources, "name": document["name"]}}
        destination = safe_join(directory, names[address])
        if destination.exists():
            if json.loads(destination.read_text(encoding="utf-8")) != document:
                raise PackError("Cached manifest snapshot was modified")
        else:
            write_json(destination, document)
    write_json(directory / "snapshot.json", {"url": url, "resources": resources,
        "files": {name: digest(safe_join(directory, name)) for name in names.values()}})
    write_json(latest, {"snapshot": identifier})
    return verified_snapshot(root, identifier)


def manifest_reference(value, cache, *, offline=False, progress=lambda text: None):
    if str(value).strip().lower().startswith(("https:", "http:")):
        return fetch_manifest(str(value), cache, offline=offline, progress=progress)
    return Path(value).resolve()


def check_manifest_updates(profile, *, fetch=None, progress=lambda text: None):
    """Compare against installed metadata, never advance the installed baseline."""
    fetch = fetch or fetch_json
    path = Path(profile) / "modlist.json"
    if not path.is_file():
        return []
    document = validate_manifest(json.loads(path.read_text(encoding="utf-8-sig")))
    records = document.get("mo2", document).get("extensions", {}).get("remoteManifests", {})
    if not isinstance(records, dict) or len(records) > MAX_DOCUMENTS:
        raise PackError("Invalid tracked manifest sources")
    results = []
    for url, record in records.items():
        result = {"url": url, "name": record.get("name", url) if isinstance(record, dict) else url,
                  "status": "unchanged", "changedResources": [], "observed": {}}
        try:
            if (manifest_url(url) != url or not isinstance(record, dict) or not isinstance(record.get("resources"), dict)
                    or url not in record["resources"] or len(record["resources"]) > MAX_DOCUMENTS
                    or any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) for sha in record["resources"].values())):
                raise PackError("Invalid tracked manifest resource list")
            for resource in [url, *(r for r in record["resources"] if r != url)]:
                sha = record["resources"][resource]
                progress("Checking manifest metadata: " + resource)
                new, observed, _ = fetch(manifest_url(resource))
                result["observed"][resource] = observed
                from .packages import validate_package
                validate_package(new)
                if observed != sha:
                    result["changedResources"].append(resource)
                    if resource == url:
                        # The new graph may intentionally remove the old recipes.
                        # Do not misreport an obsolete recipe's 404 as a failed update.
                        break
            if result["changedResources"]:
                result["status"] = "available"
        except (PackError, OSError, ValueError, TypeError) as exc:
            result.update(status="error", error=str(exc))
        results.append(result)
    return results
