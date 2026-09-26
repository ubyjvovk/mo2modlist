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
    args = parser.parse_args()
    progress = lambda message: print(message, file=sys.stderr, flush=True)
    try:
        if args.command == "export":
            candidates = profile_sources(args.mo2, args.profile, [args.mo2 / "downloads"] + args.archives, args.github_manifest)
            choices = json.loads(args.choices.read_text(encoding="utf-8-sig")) if args.choices else {}
            selections = {item["name"]: item["dependency"] for item in candidates if item["dependency"] is not None}
            selections.update(choices)
            result = export_manifest(args.mo2, args.game, args.profile, args.output, selections, progress)
        else:
            document = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8-sig")))
            result = {"valid": True, "dependencies": len(document["dependencies"])}
        print(json.dumps(result, indent=2))
    except (PackError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
