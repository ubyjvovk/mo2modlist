"""Deploy a resolved source lock to a fresh MO2 profile, with durable retry state."""
from __future__ import annotations

from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from .core import (PackError, digest, files, game_identity, json_digest, require_game_closed,
                   runtime_noise, safe_join, safe_relative, write_json)
from .manifest import validate_manifest, validate_source
from .sources import stream_member


@contextmanager
def installation_guard(mo2):
    guard = safe_join(mo2, ".modlists/install.guard")
    guard.parent.mkdir(parents=True, exist_ok=True)
    with guard.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise PackError("Another installation owns the instance lock") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def validate_lock(lock, manifest):
    validate_manifest(manifest)
    if lock.get("schemaVersion") != 1 or lock.get("kind") != "source-installation":
        raise PackError("Expected a finalized source-installation lock")
    if lock.get("manifestSha256") != json_digest(manifest):
        raise PackError("Manifest differs from lock; explicitly re-resolve before installing")
    if lock.get("adapterVersion") != "cp77-1":
        raise PackError("Unsupported game adapter in lock")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or sorted(lock.get("priority", [])) != sorted(packages):
        raise PackError("Invalid lock package priority")
    seen_priority = set(lock["priority"])
    if len(seen_priority) != len(lock["priority"]):
        raise PackError("Duplicate lock priority entry")
    for package in packages.values():
        artifact = package.get("artifact", {})
        validate_source(artifact.get("source"))
        if not re.fullmatch(r"[0-9a-f]{64}", artifact.get("sha256", "")) or type(artifact.get("size")) is not int or artifact["size"] < 0:
            raise PackError("Invalid locked artifact digest/size")
        source = artifact["source"]
        if source["type"] == "nexus" and "fileId" not in source:
            raise PackError("Lock requires exact Nexus file identity")
        if source["type"] == "github-release" and ("tag" not in source or any(type(artifact.get(k)) is not int for k in ("releaseId", "assetId"))):
            raise PackError("Lock requires exact GitHub release and asset identities")
        if package.get("recipe", {}).get("document", {}).get("artifact") != "sha256:" + artifact["sha256"]:
            raise PackError("Locked recipe and artifact identity differ")
        try:
            recipe_bytes = base64.b64decode(package["recipe"]["bytesBase64"], validate=True)
            if hashlib.sha256(recipe_bytes).hexdigest() != package["recipe"]["sha256"] or json.loads(recipe_bytes.decode("utf-8-sig")) != package["recipe"]["document"]:
                raise ValueError("recipe digest")
        except (KeyError, ValueError):
            raise PackError("Locked recipe bytes/digest/document differ") from None
        from .planning import validate_recipe
        validate_recipe(package["recipe"]["document"])
        seen = set()
        for entry in package["outputs"]:
            safe_relative(entry["path"])
            safe_relative(entry["member"])
            if entry["path"].casefold() in ("meta.ini", "modlists-source.json"):
                raise PackError("Archive output collides with MO2 management metadata")
            if type(entry.get("size")) is not int or entry["size"] < 0:
                raise PackError("Invalid locked output size")
            if entry["class"] not in ("mo2-overlay", "game-root") or entry["path"].casefold() in seen:
                raise PackError("Invalid or duplicate lock output")
            seen.add(entry["path"].casefold())
            if len(entry["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in entry["sha256"]):
                raise PackError("Invalid output digest")


def import_lock(manifest_path, lock_path, store, mo2, game, profile_name, *, allow_root=False,
                progress=lambda text: None, failure_hook=lambda phase: None):
    document = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    validate_lock(lock, document)
    require_game_closed()
    mo2, game = mo2.resolve(), game.resolve()
    profile = safe_join(mo2 / "profiles", profile_name)
    if "/" in safe_relative(profile_name):
        raise PackError("Choose one profile name")
    identity = game_identity(game)
    if "version" in lock["game"]:
        from .windows_version import product_version
        identity["version"] = product_version(game / "bin/x64/Cyberpunk2077.exe")
    if identity != lock["game"]:
        raise PackError("Target game executable/build/distribution/DLC differs from the resolved lock")
    packages = lock["packages"]
    root_files, effective = {}, {}
    for key in reversed(lock["priority"]):
        for entry in packages[key]["outputs"]:
            effective[entry["path"].casefold()] = entry["sha256"]
            if entry["class"] == "game-root":
                root_files[entry["path"].casefold()] = (key, entry)
    if root_files and not allow_root:
        raise PackError("Review and allow physical game-root deployment; it affects every profile using this game")
    for file in files(mo2 / "overwrite"):
        path = file.relative_to(mo2 / "overwrite").as_posix()
        if not runtime_noise(path) and digest(file) != effective.get(path.casefold()):
            raise PackError(f"Existing overwrite conflicts with this import: {path}")
    operation_id = json_digest({"lock": lock, "profile": profile_name, "game": str(game)})[:20]
    operation = safe_join(mo2, ".modlists/" + operation_id)
    journal_path = operation / "journal.json"
    with installation_guard(mo2):
        operation.mkdir(parents=True, exist_ok=True)
        journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {"status": "staging", "lockSha256": json_digest(lock), "root": {}, "mods": {}}
        if journal["lockSha256"] != json_digest(lock):
            raise PackError("Operation journal belongs to a different plan")
        if profile.exists():
            if journal_path.exists() and journal["status"] == "publishing" and (profile / "modlist.lock.json").is_file():
                published = json.loads((profile / "modlist.lock.json").read_text(encoding="utf-8"))
                names = [journal["mods"][key] for key in lock["priority"]]
                expected_profile = "# MO2 Modlists: highest priority first\n" + "".join("+" + name + "\n" for name in names)
                if published == lock and (profile / "modlist.txt").read_text(encoding="utf-8") == expected_profile:
                    for key, name in zip(lock["priority"], names):
                        for entry in packages[key]["outputs"]:
                            base = game if entry["class"] == "game-root" else mo2 / "mods" / name
                            target = safe_join(base, entry["path"])
                            expected = effective[entry["path"].casefold()] if entry["class"] == "game-root" else entry["sha256"]
                            if not target.is_file() or digest(target) != expected:
                                raise PackError("Published installation changed after interruption; inspect it before recovery")
                    journal["status"] = "complete"
                    write_json(journal_path, journal)
                    return {"profile": str(profile), "mods": names, "rootFiles": len(root_files), "journal": str(journal_path), "recovered": True}
            raise PackError("Target profile already exists; existing profiles are never replaced")
        names, stage_by_key = [], {}
        required = sum(e["size"] for p in packages.values() for e in p["outputs"])
        if shutil.disk_usage(mo2).free < required * 2:
            raise PackError("Not enough free space for staging and deployment")
        if shutil.disk_usage(game).free < sum(e["size"] for _, e in root_files.values()):
            raise PackError("Not enough free space for game-root deployment")
        write_json(operation / "plan.lock.json", lock)

        def checkpoint():
            write_json(journal_path, journal)

        try:
            for index, key in enumerate(lock["priority"]):
                package = packages[key]
                progress("Preparing " + package["component"])
                artifact = store.acquire({"source": package["artifact"]["source"]},
                    Path(package["sourceDocument"]), locked=package["artifact"])
                archive = store.path(artifact["sha256"])
                stage = operation / "s" / str(index)
                stage.mkdir(parents=True, exist_ok=True)
                stage_by_key[key] = stage
                for entry in package["outputs"]:
                    target = safe_join(stage, entry["path"])
                    if target.is_file() and target.stat().st_size == entry["size"] and digest(target) == entry["sha256"]:
                        continue
                    progress("Extracting " + entry["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + ".partial")
                    with temporary.open("wb") as output:
                        actual = stream_member(archive, entry["member"], output, progress=progress)
                    if actual != entry["sha256"] or temporary.stat().st_size != entry["size"]:
                        raise PackError("Extracted member differs from locked output")
                    os.replace(temporary, target)
                label = re.sub(r"[^a-zA-Z0-9 _-]", "-", package["component"])[:45].strip() or "mod"
                name = f"{label} [ML-{operation_id[:8]}-{index:03d}]"
                names.append(name)
                destination = safe_join(mo2 / "mods", name)
                if not destination.exists():
                    journal["mods"][key] = name
                    checkpoint()
                    destination.mkdir(parents=True)
                elif journal["mods"].get(key) != name:
                    raise PackError("Target mod directory is not owned by this operation")
                for entry in package["outputs"]:
                    if entry["class"] != "mo2-overlay":
                        continue
                    target = safe_join(destination, entry["path"])
                    if target.exists():
                        if digest(target) != entry["sha256"]:
                            raise PackError("Previously staged mod was modified; refusing to replace it")
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name(target.name + ".ml-partial")
                        shutil.copyfile(safe_join(stage, entry["path"]), temporary)
                        os.replace(temporary, target)
                write_json(safe_join(mo2, ".modlists/installed/" + name + ".json"),
                    {"artifact": artifact, "component": package["component"], "options": package["options"],
                     "sourceDocument": package["sourceDocument"], "recipe": package["recipe"]})
                (destination / "meta.ini").write_text("[General]\nnotes=Installed from a pinned source manifest\n", encoding="utf-8")
                failure_hook("mod-staged")
            journal["status"] = "deploying"
            checkpoint()
            require_game_closed()
            for canonical, (key, entry) in root_files.items():
                target = safe_join(game, entry["path"])
                if target.is_file() and digest(target) == entry["sha256"]:
                    continue
                if canonical not in journal["root"]:
                    backup = None
                    if target.exists():
                        backup_path = operation / "b" / str(len(journal["root"]))
                        backup_path.parent.mkdir(exist_ok=True)
                        shutil.copyfile(target, backup_path)
                        backup = {"path": str(backup_path), "sha256": digest(backup_path)}
                    journal["root"][canonical] = {"path": entry["path"], "backup": backup, "writtenSha256": entry["sha256"]}
                    checkpoint()
                else:
                    previous = journal["root"][canonical]["backup"]
                    if (target.exists() and (previous is None or digest(target) != previous["sha256"])) or (not target.exists() and previous is not None):
                        raise PackError("Game-root file changed since interruption; review before retrying")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".ml-" + operation_id)
                shutil.copyfile(safe_join(stage_by_key[key], entry["path"]), temporary)
                os.replace(temporary, target)
                failure_hook("root-written")
            stage_profile = operation / "profile"
            stage_profile.mkdir(exist_ok=True)
            (stage_profile / "modlist.txt").write_text("# MO2 Modlists: highest priority first\n" + "".join("+" + name + "\n" for name in names), encoding="utf-8")
            (stage_profile / "settings.ini").write_text("[General]\nLocalSaves=false\nLocalSettings=false\n", encoding="utf-8")
            write_json(stage_profile / "modlist.lock.json", lock)
            failure_hook("before-profile")
            profile.parent.mkdir(parents=True, exist_ok=True)
            journal["status"] = "publishing"
            checkpoint()
            stage_profile.rename(profile)
            failure_hook("profile-published")
            journal["status"] = "complete"
            checkpoint()
            return {"profile": str(profile), "mods": names, "rootFiles": len(root_files), "journal": str(journal_path)}
        except BaseException:
            if profile.is_dir():
                # Publication was the final mutation. Do not roll back root files
                # beneath a fully published profile if only the final journal write failed.
                raise
            # Restore only root files still containing this operation's bytes.
            # Staged mod directories remain disabled and can be verified/reused.
            for item in reversed(list(journal["root"].values())):
                target = safe_join(game, item["path"])
                if target.is_file() and digest(target) == item["writtenSha256"]:
                    if item["backup"]:
                        backup = Path(item["backup"]["path"])
                        if digest(backup) != item["backup"]["sha256"]:
                            raise PackError("Root backup changed; inspect the operation before retrying")
                        shutil.copyfile(backup, target)
                    else:
                        target.unlink()
            journal["status"] = "interrupted"
            checkpoint()
            raise
