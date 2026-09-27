"""Source-manifest command line interface. No bundle-import command."""
import argparse
import json
from pathlib import Path
import sys

from .core import PackError
from .manifest import export_manifest, profile_sources, validate_manifest


def main():
    parser = argparse.ArgumentParser(description="MO2 source manifests")
    sub = parser.add_subparsers(dest="command", required=True)
    from_url = sub.add_parser("from-url", help="Create a source manifest from a Nexus mod or Collection URL")
    from_url.add_argument("url")
    from_url.add_argument("--output", required=True, type=Path)
    from_url.add_argument("--name")
    from_url.add_argument("--cache", type=Path)
    from_url.add_argument("--decisions", type=Path)
    export = sub.add_parser("export", help="Export only modlist.json")
    export.add_argument("--mo2", required=True, type=Path)
    export.add_argument("--game", required=True, type=Path)
    export.add_argument("--profile", required=True)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--archives", nargs="*", default=[], type=Path)
    export.add_argument("--github-manifest", type=Path)
    export.add_argument("--choices", type=Path, help="Mod-name to dependency mapping; null explicitly skips a mod")
    validate = sub.add_parser("validate", help="Validate an agreed-schema source manifest")
    validate.add_argument("manifest", type=Path)
    restore = sub.add_parser("restore-root", help="Review or restore physical game files owned by an import")
    restore.add_argument("--mo2", required=True, type=Path)
    restore.add_argument("--game", required=True, type=Path)
    restore.add_argument("--operation", required=True)
    restore.add_argument("--reviewed-sha256", help="Apply the exact plan digest returned by the read-only invocation")
    for command in ("inspect", "verify"):
        action = sub.add_parser(command, help="Inspect a lock or verify its managed installed files without changing them")
        action.add_argument("--manifest", required=True, type=Path)
        action.add_argument("--lock", required=True, type=Path)
        if command == "verify":
            action.add_argument("--mo2", required=True, type=Path)
            action.add_argument("--game", required=True, type=Path)
            action.add_argument("--profile", required=True)
    for command in ("resolve", "install", "import"):
        action = sub.add_parser(command, help="Resolve sources or deploy a verified source lock")
        action.add_argument("--manifest", required=True, type=Path)
        action.add_argument("--lock", required=True, type=Path)
        action.add_argument("--cache", required=True, type=Path)
        action.add_argument("--archives", nargs="*", default=[], type=Path)
        action.add_argument("--game", required=True, type=Path)
        action.add_argument("--offline", action="store_true")
        if command != "resolve":
            action.add_argument("--mo2", required=True, type=Path)
            action.add_argument("--profile", required=True)
            action.add_argument("--allow-root", action="store_true")
            action.add_argument("--acknowledge", action="append", default=[], help="ID of an external prerequisite completed for this target")
    collection = sub.add_parser("import-collection", help="Convert a Nexus Collection package or URL; unresolved choices block finalization")
    origin = collection.add_mutually_exclusive_group(required=True)
    origin.add_argument("--file", type=Path)
    origin.add_argument("--url")
    collection.add_argument("--output", required=True, type=Path)
    collection.add_argument("--cache", type=Path)
    collection.add_argument("--decisions", type=Path)
    args = parser.parse_args()
    progress = lambda message: print(message, file=sys.stderr, flush=True)
    try:
        if args.command == "from-url":
            from .url_manifest import manifest_from_url
            from .credentials import headers
            decisions = json.loads(args.decisions.read_text(encoding="utf-8-sig")) if args.decisions else {}
            document = manifest_from_url(args.url, args.output, name=args.name, cache=args.cache,
                headers=headers("nexus"), decisions=decisions, progress=progress)
            result = {"manifest": str(args.output), "dependencies": len(document["dependencies"])}
        elif args.command == "export":
            candidates = profile_sources(args.mo2, args.profile, [args.mo2 / "downloads"] + args.archives, args.github_manifest)
            choices = json.loads(args.choices.read_text(encoding="utf-8-sig")) if args.choices else {}
            selections = {item["name"]: item["dependency"] for item in candidates if item["dependency"] is not None}
            selections.update(choices)
            result = export_manifest(args.mo2, args.game, args.profile, args.output, selections, progress)
        elif args.command == "restore-root":
            from .restoration import restoration_plan, restore_root
            from .core import json_digest
            if args.reviewed_sha256:
                result = restore_root(args.mo2, args.game, args.operation,
                    reviewed_sha256=args.reviewed_sha256, progress=progress)
            else:
                result = restoration_plan(args.mo2, args.game, args.operation)
                result = {"plan": result, "reviewedSha256": json_digest(result)}
        elif args.command == "validate":
            document = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8-sig")))
            result = {"valid": True, "dependencies": len(document["dependencies"])}
        elif args.command in ("inspect", "verify"):
            from .inspection import inspect_lock, verify_installation
            result = inspect_lock(args.manifest, args.lock) if args.command == "inspect" else verify_installation(
                args.manifest, args.lock, args.mo2, args.game, args.profile)
        elif args.command == "import-collection":
            from .collections import fetch_collection, read_collection, convert_collection, write_collection_manifest, bundled_dependency
            path, identity = args.file, None
            if args.url:
                if args.cache is None:
                    raise PackError("--cache is required for collection URL downloads")
                from .credentials import headers
                path, identity = fetch_collection(args.url, args.cache, progress=progress, headers=headers("nexus"))
            decisions = json.loads(args.decisions.read_text(encoding="utf-8-sig")) if args.decisions else {}
            document = read_collection(path)
            if args.cache and path.suffix.lower() != ".json":
                for index, mod in enumerate(document["mods"], 1):
                    decision = decisions.setdefault(f"mod-{index:04d}", {})
                    if (mod.get("source", {}).get("type") == "bundle" and "source" not in decision
                        and (not mod.get("optional") or decision.get("include") is True)):
                        decision.update(bundled_dependency(path, mod, args.cache, progress))
            draft = convert_collection(document, identity=identity, decisions=decisions)
            write_collection_manifest(draft, args.output)
            result = {"manifest": str(args.output), "dependencies": len(draft["manifest"]["dependencies"]), "notes": draft["notes"]}
        else:
            from .acquisition import ArtifactStore
            from .acquisition import json_request
            from .credentials import headers
            from .nexus import NexusProvider
            from .planning import resolve_manifest
            from .install import import_lock
            nexus_headers, github_headers = headers("nexus"), headers("github")
            store = ArtifactStore(args.cache, args.archives, offline=args.offline, progress=progress,
                nexus_metadata=NexusProvider(nexus_headers) if nexus_headers and not args.offline else None,
                request=lambda url: json_request(url, headers=github_headers))
            if args.command == "resolve" or (args.command == "import" and not args.lock.exists()):
                lock = resolve_manifest(args.manifest, store, args.game, args.lock, progress=progress)
                result = {"lock": str(args.lock), "packages": len(lock["packages"])}
            if args.command != "resolve":
                result = import_lock(args.manifest, args.lock, store, args.mo2, args.game, args.profile,
                                     allow_root=args.allow_root, progress=progress, acknowledged=args.acknowledge)
        print(json.dumps(result, indent=2))
        if args.command == "verify" and not result["valid"]:
            return 1
    except (PackError, OSError, ValueError) as exc:
        if hasattr(exc, "request"):
            print(json.dumps({"inputRequired": exc.request}, indent=2), file=sys.stderr)
            return 2
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
