"""Reviewed, resumable restoration of physical files owned by one import."""
import json
import os
from pathlib import Path
import re
import shutil

from .core import PackError, digest, json_digest, require_game_closed, safe_join, write_json
from .install import installation_guard


def _read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def restoration_plan(mo2, game, operation_id):
    mo2, game = mo2.resolve(), game.resolve()
    if not re.fullmatch(r"[0-9a-f]{20}", operation_id):
        raise PackError("Select an installation operation ID")
    operation = safe_join(mo2, ".modlists/" + operation_id)
    journal = _read(safe_join(operation, "journal.json"))
    lock = _read(safe_join(operation, "plan.lock.json"))
    if journal.get("lockSha256") != json_digest(lock):
        raise PackError("Operation lock and journal disagree")
    if journal.get("targetGame") != str(game) or not journal.get("profileName"):
        raise PackError("This journal does not identify this game target; automatic restoration is unavailable")
    if json_digest({"lock": lock, "profile": journal["profileName"], "game": str(game)})[:20] != operation_id:
        raise PackError("Operation identity differs from its target and plan")
    if journal.get("status") not in ("complete", "restoring-root", "root-restored"):
        raise PackError("Finish or recover the interrupted installation before restoring its root files")
    owned = journal.get("root", {})
    permitted = {}
    for key in reversed(lock["priority"]):
        for entry in lock["packages"][key]["outputs"]:
            if entry["class"] == "game-root":
                permitted[entry["path"].casefold()] = entry["sha256"]
    for entry in journal.get("update", {}).get("removeRoot", []):
        permitted[entry["path"].casefold()] = entry["restore"]["sha256"] if entry.get("restore") else None
    actions, blockers = [], []
    for canonical, item in owned.items():
        if canonical != item["path"].casefold() or canonical not in permitted or permitted[canonical] != item["writtenSha256"]:
            raise PackError("Journal root ownership differs from its installation plan")
        target = safe_join(game, item["path"])
        backup = item.get("backup")
        original = None
        if backup:
            backup_path = Path(backup["path"])
            if not backup_path.is_relative_to(operation / "b"):
                raise PackError("Backup is outside this operation")
            backup_path = safe_join(operation, backup_path.relative_to(operation).as_posix())
            if not backup_path.is_file() or digest(backup_path) != backup["sha256"]:
                raise PackError("Root backup is missing or changed: " + item["path"])
            original = backup["sha256"]
        current = digest(target) if target.is_file() else None
        if target.exists() and not target.is_file():
            blockers.append("Not a regular file: " + item["path"])
        elif current != item["writtenSha256"] and not (
            journal["status"] in ("restoring-root", "root-restored") and current == original
        ):
            blockers.append("File changed after installation: " + item["path"])
        actions.append({"path": item["path"], "action": "restore-backup" if backup else "remove-owned-file",
                        "currentSha256": current, "originalSha256": original})
    # Another fresh profile can adopt identical root bytes without writing them.
    # Inspect profile locks as well as write journals to catch those consumers.
    profiles = safe_join(mo2, "profiles")
    if profiles.exists():
        for profile in profiles.iterdir():
            if profile.name == journal["profileName"]:
                continue
            path = safe_join(mo2, "profiles/" + profile.name + "/modlist.lock.json")
            if not path.is_file():
                continue
            other = _read(path)
            for package in other.get("packages", {}).values():
                for entry in package.get("outputs", []):
                    if entry.get("class") == "game-root" and entry["path"].casefold() in owned:
                        blockers.append(f"Profile '{profile.name}' also requires {entry['path']}")
    return {"operation": operation_id, "profile": journal["profileName"], "game": str(game),
            "journalSha256": json_digest(journal), "files": actions, "blockers": sorted(set(blockers)),
            "notice": "Physical files affect every profile and instance using this game. The selected profile will no longer have its imported root files. Profile and mod folders remain. Other instances and unmanaged consumers cannot be detected."}


def restore_root(mo2, game, operation_id, *, reviewed_sha256, progress=lambda text: None,
                 failure_hook=lambda phase: None):
    mo2, game = mo2.resolve(), game.resolve()
    require_game_closed(game)
    with installation_guard(mo2):
        plan = restoration_plan(mo2, game, operation_id)
        if json_digest(plan) != reviewed_sha256:
            raise PackError("Restoration state changed; review the new plan")
        if plan["blockers"]:
            raise PackError("Root restoration blocked: " + "; ".join(plan["blockers"]))
        operation = safe_join(mo2, ".modlists/" + operation_id)
        journal_path = safe_join(operation, "journal.json")
        journal = _read(journal_path)
        journal["status"] = "restoring-root"
        write_json(journal_path, journal)
        for item in reversed(list(journal["root"].values())):
            progress("Restoring " + item["path"])
            target = safe_join(game, item["path"])
            original = item["backup"]["sha256"] if item["backup"] else None
            current = digest(target) if target.is_file() else None
            if current == original:
                continue
            if current != item["writtenSha256"]:
                raise PackError("Root file changed during restoration: " + item["path"])
            if item["backup"]:
                backup = safe_join(operation, Path(item["backup"]["path"]).relative_to(operation).as_posix())
                temporary = safe_join(game, item["path"] + ".ml-restore-" + operation_id)
                shutil.copyfile(backup, temporary)
                if digest(temporary) != original:
                    raise PackError("Backup changed during restoration")
                os.replace(temporary, target)
            else:
                target.unlink()
            failure_hook("root-restored")
        journal["status"] = "root-restored"
        write_json(journal_path, journal)
        return {"operation": operation_id, "restoredFiles": len(plan["files"]), "profilePreserved": plan["profile"]}
