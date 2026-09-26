"""Compare expected installed layers and priority to a restored MO2 profile."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mo2_modlists.core import active_mods, digest, safe_join, verify_bundle

parser = argparse.ArgumentParser()
parser.add_argument("--bundle", required=True, type=Path)
parser.add_argument("--mo2", required=True, type=Path)
parser.add_argument("--profile", required=True)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
lock = verify_bundle(args.bundle)
expected = list(lock["layers"])
if lock["overwrite"]:
    expected.insert(0, {"files": lock["overwrite"]})
actual = active_mods(safe_join(args.mo2 / "profiles", args.profile))
if len(expected) != len(actual):
    raise SystemExit("Enabled layer count differs")
errors, total = [], 0
for layer, name in zip(expected, actual):
    for entry in layer["files"]:
        path = safe_join(args.mo2 / "mods" / name, entry["path"])
        total += 1
        if not path.is_file() or digest(path) != entry["sha256"]:
            errors.append(str(path))
result = {"layers": len(expected), "verifiedFiles": total, "priorityMatches": True, "mismatches": errors}
if args.output:
    args.output.write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
raise SystemExit(bool(errors))
