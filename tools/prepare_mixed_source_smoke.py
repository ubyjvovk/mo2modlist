"""Build a real pinned acceptance pack; does not deploy or launch the game."""
import argparse
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mo2_modlists.core import digest, write_json

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--downloads", required=True, type=Path)
args = parser.parse_args()
output = args.output.resolve()
if output.exists():
    raise SystemExit("Choose a new acceptance output directory")
output.mkdir(parents=True)
catalog = json.loads((args.downloads / "base-mod-manifest.json").read_text())
recipes = output / "recipes"
recipes.mkdir()
deps = {}
for name, component, repository, asset in [
    ("RED4ext", "red4ext", "wopss/RED4ext", "red4ext-1.30.0.zip"),
    ("Cyber Engine Tweaks", "cet", "maximegmd/CyberEngineTweaks", "cet_1.37.1.zip"),
    ("redscript", "redscript", "jac3km4/redscript", "redscript-v0.5.31-windows.zip"),
]:
    record = next(item for item in catalog if item["Name"] == name)
    archive = args.downloads / asset
    if digest(archive) != record["SHA256"]:
        raise SystemExit("Known framework archive changed: " + name)
    recipe = recipes / (component + ".json")
    write_json(recipe, {"schemaVersion": 1, "component": component, "version": record["Version"],
        "revision": "1", "artifact": "sha256:" + record["SHA256"], "dependencies": {},
        "extensions": {"reviewedSource": "https://github.com/" + repository}})
    deps[component] = {"source": {"type": "github-release", "repository": repository,
        "tag": record["Version"], "asset": asset}, "recipe": recipe.as_posix(), "integrity": "sha256:" + record["SHA256"]}

# The Nexus page for file 161780 links this exact SHA-256 in its VirusTotal
# verification link. The already downloaded official GitHub archive matches it.
codeware_sha = "102989e199bad650fe6e53395c22bac53fdd7abecc6eeec3b0046886631591f0"
codeware_archive = (args.downloads / "Codeware-1.20.5.zip").resolve()
if digest(codeware_archive) != codeware_sha:
    raise SystemExit("Codeware archive differs from the Nexus-published digest")
write_json(recipes / "codeware.json", {"schemaVersion": 1, "component": "codeware", "version": "1.20.5",
    "revision": "1", "artifact": "sha256:" + codeware_sha, "dependencies": {"red4ext": deps["red4ext"]},
    "game": {"id": "cyberpunk2077", "version": "2.31", "dlc": []},
    "extensions": {"reviewedSource": "https://github.com/psiberx/cp2077-codeware",
        "nexusFile": "https://www.nexusmods.com/cyberpunk2077/mods/7780?tab=files&file_id=161780",
        "publishedHash": "https://www.virustotal.com/gui/file/" + codeware_sha}})
codeware = {"source": {"type": "nexus", "game": "cyberpunk2077", "modId": 7780, "fileId": 161780},
    "recipe": (recipes / "codeware.json").as_posix(), "integrity": "sha256:" + codeware_sha}
local_archive = output / "acceptance-observer.zip"
with zipfile.ZipFile(local_archive, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("bin/x64/plugins/cyber_engine_tweaks/mods/modlists_acceptance/init.lua", '''local seen = false
registerForEvent("onInit", function()
  print("MO2_MODLISTS_ACCEPTANCE_INIT")
end)
registerForEvent("onUpdate", function()
  if not seen and Game.GetPlayer() ~= nil then
    seen = true
    print("MO2_MODLISTS_ACCEPTANCE_WORLD_READY")
  end
end)
''')
write_json(recipes / "observer.json", {"schemaVersion": 1, "component": "acceptance-observer", "version": "1",
    "revision": "1", "artifact": "sha256:" + digest(local_archive),
    "dependencies": {"cet": deps["cet"], "codeware": codeware, "redscript": deps["redscript"]}})
write_json(output / "modlist.json", {"schemaVersion": 1, "name": "Mixed Source Acceptance",
    "game": {"id": "cyberpunk2077", "version": "2.31", "dlc": []}, "dependencies": {
        "observer": {"source": {"type": "local-archive", "path": local_archive.as_posix()},
                     "recipe": (recipes / "observer.json").as_posix()}}})
write_json(output / "manual-nexus-input.json", {"source": codeware["source"], "archive": str(codeware_archive),
    "sha256": codeware_sha, "evidence": "Exact Nexus file's published SHA-256 matches the existing official GitHub archive; no blocked CDN download retried."})
print(output / "modlist.json")
