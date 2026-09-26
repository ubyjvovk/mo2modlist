"""Prepare a small disposable fixture and launch its MO2 UI integration probe."""
import os
import argparse
from pathlib import Path
import shutil
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--run", default="v1")
args = parser.parse_args()
if not args.run.isalnum():
    raise SystemExit("Use an alphanumeric run label")
instance = root / "test-install/MO2"
profile = instance / "profiles/Manifest fixture"
profile.mkdir(parents=True, exist_ok=True)
names = ["ManifestKnown", "UnknownLocal", "UnknownUrl", "UnknownSkip"]
(profile / "modlist.txt").write_text("".join("+" + name + "\n" for name in names))
for name in names:
    mod = instance / "mods" / name
    mod.mkdir(parents=True, exist_ok=True)
    (mod / "fixture.txt").write_text(name)
(instance / "mods/ManifestKnown/meta.ini").write_text(
    "[General]\nrepository=Nexus\ngameName=cyberpunk2077\nmodid=1\n[installedFiles]\n1\\fileid=2\n")
with zipfile.ZipFile(root / "artifacts/fixture.zip", "w") as archive:
    archive.writestr("fixture.txt", "UnknownLocal")
shutil.copyfile(root / "tools/mo2_manifest_probe.py", instance / "plugins/mo2_manifest_probe.py")
output = root / ("artifacts/manifest-ui-probe-" + args.run)
if output.exists():
    raise SystemExit("Probe output exists; preserve it and choose a new output path")
environment = dict(os.environ, MO2_MANIFEST_PROBE_OUTPUT=str(output))
process = subprocess.Popen([str(instance / "ModOrganizer.exe"), "--multiple", "-p", "Manifest fixture"],
                           cwd=instance, env=environment)
print(f"Probe process: {process.pid}; result: {output / 'probe-result.json'}")
