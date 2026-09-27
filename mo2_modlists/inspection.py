"""Read-only inspection of source locks and their managed installed files."""
import json
from pathlib import Path

from .core import active_mods, digest, files, game_identity, safe_join
from .install import validate_lock
from .games import executable, overlay_path


def inspect_lock(manifest_path, lock_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    validate_lock(lock, manifest)
    return {"name": manifest["name"], "game": lock["game"],
        "components": [{"key": key, "component": lock["packages"][key]["component"],
            "version": lock["packages"][key]["version"], "source": lock["packages"][key]["artifact"]["source"],
            "archiveSha256": lock["packages"][key]["artifact"]["sha256"],
            "files": len(lock["packages"][key]["outputs"]), "options": lock["packages"][key]["options"]}
            for key in lock["priority"]], "dependencyEdges": lock["dependencyEdges"],
        "physicalGameFiles": sorted({entry["path"] for package in lock["packages"].values()
            for entry in package["outputs"] if entry["class"] == "game-root"}),
        "externalPrerequisites": lock["externalPrerequisites"], "registries": lock["registries"],
        **({"plugins": lock["plugins"]} if "plugins" in lock else {})}


def verify_installation(manifest_path, lock_path, mo2, game, profile_name):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    validate_lock(lock, manifest)
    profile = safe_join(mo2, "profiles/" + profile_name)
    differences = []
    recorded = profile / "modlist.lock.json"
    if not recorded.is_file() or json.loads(recorded.read_text(encoding="utf-8-sig")) != lock:
        differences.append({"kind": "profile-lock", "path": str(recorded)})
    identity = game_identity(game)
    if "redmod" in lock["game"]:
        identity["redmod"] = (game / "tools/redmod/bin/redMod.exe").is_file()
    if "version" in lock["game"]:
        from .windows_version import product_version
        identity["version"] = product_version(executable(game))
    if "fixedProductVersion" in lock["game"]:
        from .windows_version import product_version
        identity["fixedProductVersion"] = product_version(executable(game), fixed=True)
    if identity != lock["game"]:
        differences.append({"kind": "game-identity"})
    if identity["id"] == "newvegas":
        from .newvegas import profile_plugins
        if profile_plugins(profile) != lock["plugins"]:
            differences.append({"kind": "plugin-order"})
    names = active_mods(profile)
    if len(names) != len(lock["priority"]):
        differences.append({"kind": "enabled-mod-count", "expected": len(lock["priority"]), "actual": len(names)})
    checked, root_outputs = 0, {}
    def check(base, entry):
        nonlocal checked
        path = safe_join(base, entry["path"])
        checked += 1
        if not path.is_file():
            differences.append({"kind": "missing-file", "path": str(path)})
        elif path.stat().st_size != entry["size"] or digest(path) != entry["sha256"]:
            differences.append({"kind": "changed-file", "path": str(path)})
    for key, name in zip(lock["priority"], names):
        package = lock["packages"][key]
        mod = safe_join(mo2, "mods/" + name)
        provenance_file = safe_join(mo2, ".modlists/installed/" + name + ".json")
        provenance = json.loads(provenance_file.read_text(encoding="utf-8-sig")) if provenance_file.is_file() else {}
        if (provenance.get("component") != package["component"] or provenance.get("recipe", {}).get("sha256") != package["recipe"]["sha256"]
            or provenance.get("artifact", {}).get("sha256") != package["artifact"]["sha256"] or provenance.get("options") != package["options"]):
            differences.append({"kind": "component-or-priority", "mod": name, "expected": package["component"]})
        expected_paths = set()
        for entry in package["outputs"]:
            if entry["class"] == "mo2-overlay":
                relative = overlay_path(identity["id"], entry["path"])
                expected_paths.add(relative.casefold())
                check(mod, {**entry, "path": relative})
            else:
                root_outputs.setdefault(entry["path"].casefold(), entry)
        for path in files(mod):
            relative = path.relative_to(mod).as_posix().casefold()
            if relative != "meta.ini" and relative not in expected_paths:
                differences.append({"kind": "extra-mod-file", "path": str(path)})
    for entry in root_outputs.values():
        check(game, entry)
    return {"valid": not differences, "profile": str(profile), "filesChecked": checked, "differences": differences,
        "scope": "Managed initial files, component identities, enabled ordering and game identity. Unmanaged game-root files and runtime compatibility are not verified."}
