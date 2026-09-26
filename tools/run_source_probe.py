"""Create a tiny archive fixture and start the disposable MO2 host probe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--run", required=True)
parser.add_argument("--collection", action="store_true")
parser.add_argument("--restore", action="store_true")
args = parser.parse_args()
if not args.run.isalnum():
    raise SystemExit("Use an alphanumeric run label")
output = root / ("artifacts/source-ui-probe-" + args.run)
if output.exists():
    raise SystemExit("Probe output exists; choose a new run label")
output.mkdir(parents=True)
with zipfile.ZipFile(output / "fixture.zip", "w") as archive:
    archive.writestr("r6/scripts/modlists_probe.txt", "source importer fixture")
    if args.restore:
        archive.writestr("bin/x64/modlists-probe-" + args.run + ".txt", "physical root fixture")
sha = hashlib.sha256((output / "fixture.zip").read_bytes()).hexdigest()
(output / "fixture.recipe.json").write_text(json.dumps({"schemaVersion": 1, "component": "mo2-source-probe",
    "version": "1", "revision": "1", "artifact": "sha256:" + sha, "dependencies": {}}), encoding="utf-8")
if args.collection:
    collection = {"info": {"name": "Source Collection fixture", "domainName": "cyberpunk2077",
        "installInstructions": "Fixture only: no external action is required."}, "modRules": [], "mods": [
        {"name": "Bundled fixture", "version": "1", "optional": False, "domainName": "cyberpunk2077",
         "source": {"type": "bundle", "fileExpression": "fixture.zip"}},
        {"name": "Optional omitted fixture", "version": "1", "optional": True, "domainName": "cyberpunk2077", "source": {"type": "manual"}}]}
    with zipfile.ZipFile(output / "collection.zip", "w") as archive:
        archive.writestr("collection.json", json.dumps(collection))
        archive.write(output / "fixture.zip", "bundled/fixture.zip")
else:
    (output / "modlist.json").write_text(json.dumps({"schemaVersion": 1, "name": "Source fixture",
        "game": {"id": "cyberpunk2077", "dlc": []}, "dependencies": {
            "fixture": {"source": {"type": "local-archive", "path": "fixture.zip"}}}}), encoding="utf-8")
instance = root / "test-install/MO2"
shutil.copyfile(root / "tools/mo2_source_probe.py", instance / "plugins/mo2_source_probe.py")
environment = dict(os.environ, MO2_SOURCE_PROBE_OUTPUT=str(output))
if args.collection:
    environment["MO2_SOURCE_PROBE_COLLECTION"] = "1"
if args.restore:
    environment["MO2_SOURCE_PROBE_RESTORE"] = args.run
process = subprocess.Popen([str(instance / "ModOrganizer.exe"), "--multiple", "-p", "Manifest fixture"], cwd=instance, env=environment)
print(f"Probe process: {process.pid}; result: {output / 'probe-result.json'}")
