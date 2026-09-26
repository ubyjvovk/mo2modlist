import argparse
import json
from pathlib import Path
import sys

from .core import PackError, export_profile, import_profile, verify_bundle


def main():
    parser = argparse.ArgumentParser(description="Export/import a private, verified MO2 profile bundle")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("export", "import"):
        p = sub.add_parser(command)
        p.add_argument("--mo2", required=True, type=Path)
        p.add_argument("--game", required=True, type=Path)
        p.add_argument("--profile", required=True)
        p.add_argument("--bundle", required=True, type=Path)
        p.add_argument("--user-settings", type=Path)
        if command == "import":
            p.add_argument("--allow-root", action="store_true")
            p.add_argument("--archives", nargs="*", default=[], type=Path)
            p.add_argument("--download-sources", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("bundle", type=Path)
    p = sub.add_parser("compact")
    p.add_argument("--bundle", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--archives", nargs="+", required=True, type=Path)
    p.add_argument("--github-manifest", type=Path)
    p = sub.add_parser("hydrate")
    p.add_argument("--bundle", required=True, type=Path)
    p.add_argument("--cache", required=True, type=Path)
    p.add_argument("--archives", nargs="*", default=[], type=Path)
    p.add_argument("--download", action="store_true")
    args = parser.parse_args()
    progress = lambda message: print(message, file=sys.stderr, flush=True)
    try:
        if args.command == "export":
            result = export_profile(args.mo2, args.game, args.profile, args.bundle, args.user_settings, progress)
        elif args.command == "import":
            from .sources import hydrate_bundle
            hydrate_bundle(args.bundle, args.mo2 / ".modlists/source-cache", args.archives, args.download_sources, progress)
            result = import_profile(args.bundle, args.mo2, args.game, args.profile,
                                    args.allow_root, args.user_settings, progress)
        elif args.command == "compact":
            from .sources import compact_bundle
            result = compact_bundle(args.bundle, args.output, args.archives, args.github_manifest, progress)
        elif args.command == "hydrate":
            from .sources import hydrate_bundle
            result = hydrate_bundle(args.bundle, args.cache, args.archives, args.download, progress)
        else:
            lock = verify_bundle(args.bundle)
            result = {"verified": True, "mods": len(lock["layers"])}
        print(json.dumps(result, indent=2))
    except (PackError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
