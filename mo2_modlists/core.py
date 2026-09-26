"""Private local bundles reproduce installed outputs, including installer choices.

Source credentials and the full ModOrganizer.ini are not collected. Files nested
inside captured directories may include personal data or save copies. Export is
a lock operation over an existing installation, not a new dependency solve.
Bundles are intended for private personal backup/transfer.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import uuid


class PackError(Exception):
    pass


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PackError(f"Invalid relative path: {value!r}")
    parts = value.split("/")
    for part in parts:
        if (part in ("", ".", "..") or part.rstrip(" .") != part
                or re.search(r'[<>:"|?*\x00-\x1f]', part)
                or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)):
            raise PackError(f"Unsafe Windows path: {value!r}")
    return PurePosixPath(*parts).as_posix()


def safe_join(root: Path, relative: str) -> Path:
    relative = safe_relative(relative)
    root = root.resolve()
    target = root.joinpath(*relative.split("/"))
    for parent in (target, *target.parents):
        if parent == root:
            break
        if parent.is_symlink() or (parent.exists() and parent.is_junction()):
            raise PackError(f"Links/junctions are not supported: {parent}")
    if not target.resolve().is_relative_to(root):
        raise PackError(f"Path escapes destination: {relative}")
    return target


def files(root: Path):
    if not root.exists():
        return
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in sorted(dirs + names):
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise PackError(f"Cannot snapshot linked path: {path}")
        for name in sorted(names):
            path = Path(directory) / name
            if path.is_file():
                yield path


def game_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Cyberpunk2077.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise PackError("Could not check running game processes")
    return '"cyberpunk2077.exe"' in result.stdout.lower()


def require_game_closed():
    if game_running():
        raise PackError("Close Cyberpunk before snapshotting or installing; its configuration files may be changing.")


def read_ini(path: Path):
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.optionxform = str
    ini.read(path, encoding="utf-8-sig")
    return ini


def active_mods(profile: Path) -> list[str]:
    # MO2 persists highest priority first. Retain this order verbatim.
    result = []
    for line in (profile / "modlist.txt").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("+"):
            name = safe_relative(line[1:])
            if "/" in name:
                raise PackError(f"Invalid mod directory name: {name}")
            if name.casefold() in {x.casefold() for x in result}:
                raise PackError(f"Duplicate enabled mod: {name}")
            result.append(name)
    return result


def vanilla_paths(game: Path) -> set[str]:
    manifest = game / "goggame-galaxyFileList.ini"
    if not manifest.exists():
        raise PackError("Root inventory currently requires GOG's installed file list. Steam baseline support is pending.")
    ini = read_ini(manifest)
    return {value.replace("\\", "/").casefold()
            for section in ini.sections() for key, value in ini[section].items()
            if re.fullmatch(r"F\d+", key) and not re.fullmatch(r"[0-9a-f]{32}", value)}


def game_identity(game: Path):
    exe = game / "bin/x64/Cyberpunk2077.exe"
    if not exe.is_file():
        raise PackError(f"Cyberpunk executable missing in {game}")
    info_path = game / "goggame-1423049311.info"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    return {"id": "cyberpunk2077", "executableSha256": digest(exe),
            "distribution": "gog" if info else "unknown", "buildId": info.get("buildId"),
            "phantomLiberty": (game / "archive/pc/ep1").is_dir()}


def runtime_noise(relative: str) -> bool:
    p = relative.casefold()
    return (p.endswith((".log", ".dmp")) or "/logs/" in p
            or bool(re.search(r"\.exe-\d{8}-\d+.*\.txt$", p)))


def root_inventory(game: Path, managed_paths: set[str]):
    vanilla = vanilla_paths(game)
    for path in files(game):
        rel = path.relative_to(game).as_posix()
        key = rel.casefold()
        if runtime_noise(rel):
            continue
        # Installer bookkeeping is not a game modification.
        if "/" not in rel and (key.startswith(("goggame-", "unins"))
                                or key.endswith(".lnk") or key in ("goglog.ini",)):
            continue
        if key not in vanilla or key in managed_paths:
            yield path


def provenance(mod: Path):
    ini = read_ini(mod / "meta.ini")
    general = dict(ini["General"]) if ini.has_section("General") else {}
    allowed = ("modid", "version", "repository", "gameName", "installationFile")
    # Never blindly copy arbitrary metadata/URLs which may carry credentials.
    return {key: Path(value).name if key == "installationFile" else value
            for key in allowed if (value := general.get(key))}


def mo2_game_settings(mo2: Path):
    ini = read_ini(mo2 / "ModOrganizer.ini")
    prefix = "Cyberpunk%202077%20Support%20Plugin\\"
    return {key[len(prefix):]: value for key, value in ini.items("Plugins")
            if key.startswith(prefix)} if ini.has_section("Plugins") else {}


def patched_game_settings(path: Path, settings: dict) -> str:
    """Patch just our game's plugin entries, preserving other Qt INI data."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    prefix = "Cyberpunk%202077%20Support%20Plugin\\"
    additions = {}
    for key, value in settings.items():
        if not re.fullmatch(r"[A-Za-z0-9_]+", key) or not isinstance(value, str) or "\n" in value or "\r" in value:
            raise PackError("Invalid CP77 plugin setting")
        additions[prefix + key] = value
    result, in_section, found = [], False, False
    for line in lines:
        if line.startswith("["):
            if in_section:
                result.extend(f"{k}={v}" for k, v in additions.items())
                additions.clear()
            in_section = line.strip() == "[Plugins]"
            found = found or in_section
        if in_section and line.partition("=")[0] in additions:
            continue
        result.append(line)
    if not found:
        result.extend(["", "[Plugins]"])
    result.extend(f"{k}={v}" for k, v in additions.items())
    return "\n".join(result) + "\n"


def export_profile(mo2: Path, game: Path, profile_name: str, bundle: Path,
                   user_settings: Path | None = None, progress=lambda message: None):
    require_game_closed()
    mo2, game, bundle = mo2.resolve(), game.resolve(), bundle.resolve()
    if bundle.exists():
        raise PackError(f"Export destination already exists: {bundle}")
    for source in (mo2, game):
        if bundle.is_relative_to(source):
            raise PackError("Export destination must be outside the source installation")
    profile = safe_join(mo2 / "profiles", profile_name)
    profile_digest = digest(profile / "modlist.txt")
    mods = active_mods(profile)
    identity = game_identity(game)
    work = bundle.with_name(bundle.name + ".export-" + uuid.uuid4().hex)
    work.mkdir(parents=True)
    layers, managed = [], set()

    def snapshot(root: Path, selected):
        entries = []
        seen = set()
        for path in selected:
            rel = safe_relative(path.relative_to(root).as_posix())
            if rel.casefold() in seen:
                raise PackError(f"Case-insensitive file collision in {root}: {rel}")
            seen.add(rel.casefold())
            if len(entries) % 32 == 0:
                progress(f"Reading {root.name}: {rel}")
            before = path.stat()
            h = digest(path)
            dst = work / "blobs" / h
            if not dst.exists():
                dst.parent.mkdir(exist_ok=True)
                shutil.copyfile(path, dst)
                if digest(dst) != h:
                    raise PackError(f"Source changed while copying: {path}")
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise PackError(f"Source changed during export: {path}")
            entries.append({"path": rel, "sha256": h, "size": before.st_size})
        return sorted(entries, key=lambda e: e["path"].casefold())

    try:
        for name in mods:
            progress(f"Snapshotting {name}")
            root = safe_join(mo2 / "mods", name)
            if not root.is_dir():
                raise PackError(f"Enabled mod is missing: {name}")
            entries = snapshot(root, (p for p in files(root) if p.name != "meta.ini" and not runtime_noise(p.relative_to(root).as_posix())))
            managed.update(e["path"].casefold() for e in entries)
            layers.append({"name": name, "kind": "mod", "provenance": provenance(root), "files": entries})
        progress("Snapshotting overwrite and physical game-root modifications")
        root = mo2 / "overwrite"
        overwrite = snapshot(root, (p for p in files(root) if not runtime_noise(p.relative_to(root).as_posix())))
        root_entries = snapshot(game, root_inventory(game, managed))
        profile_entries = snapshot(profile, (p for p in files(profile) if p.name in ("settings.ini", "initweaks.ini", "lockedorder.txt")))
        settings = []
        if user_settings is not None and user_settings.is_file():
            settings = snapshot(user_settings.parent, [user_settings])
        manifest = {"schemaVersion": 1, "name": profile_name, "game": identity,
                    "mode": "installed-snapshot", "dependencies": {
                        f"mod-{i:03d}": {"installedName": layer["name"], "provenance": layer["provenance"]}
                        for i, layer in enumerate(layers)}}
        lock = {"schemaVersion": 1, "mode": "installed-snapshot", "manifestSha256": json_digest(manifest),
                "game": identity, "profile": profile_name, "priority": "highest-first",
                "layers": layers, "overwrite": overwrite, "root": root_entries,
                "profileFiles": profile_entries, "userSettings": settings,
                "mo2GameSettings": mo2_game_settings(mo2),
                "limitations": ["Requires an independently installed matching base game and DLC.",
                    "Stock files modified outside enabled mod paths cannot be detected from GOG's path-only baseline.",
                    "User settings are a private snapshot; saves and machine drivers are not included." ]}
        write_json(work / "modlist.json", manifest)
        write_json(work / "modlist.lock.json", lock)
        verify_bundle(work)
        if digest(profile / "modlist.txt") != profile_digest:
            raise PackError("The profile changed during export; retry after MO2 has finished editing it")
        work.rename(bundle)
        progress(f"Export ready: {bundle}")
        return {"bundle": str(bundle), "mods": len(layers), "rootFiles": len(root_entries),
                "overwriteFiles": len(overwrite), "blobs": len(list((bundle / "blobs").iterdir()))}
    except BaseException:
        # Preserve incomplete work for diagnosis; never label it a completed bundle.
        write_json(work / "incomplete.json", {"status": "failed"})
        raise


def load_bundle(bundle: Path):
    manifest = json.loads((bundle / "modlist.json").read_text(encoding="utf-8"))
    lock = json.loads((bundle / "modlist.lock.json").read_text(encoding="utf-8"))
    if lock.get("schemaVersion") != 1 or lock.get("mode") != "installed-snapshot":
        raise PackError("Unsupported lock schema or mode")
    if json_digest(manifest) != lock.get("manifestSha256"):
        raise PackError("Manifest differs from the lock")
    if lock.get("game") != manifest.get("game"):
        raise PackError("Manifest/lock game identity differs")
    return lock


def entry_groups(lock):
    yield from (layer["files"] for layer in lock["layers"])
    for key in ("overwrite", "root", "profileFiles", "userSettings"):
        yield lock[key]


def verify_bundle(bundle: Path):
    bundle = bundle.resolve()
    lock = load_bundle(bundle)
    checked = set()
    for entries in entry_groups(lock):
        seen = set()
        for entry in entries:
            rel = safe_relative(entry["path"])
            if rel.casefold() in seen:
                raise PackError(f"Duplicate target path: {rel}")
            seen.add(rel.casefold())
            h = entry["sha256"]
            if not isinstance(h, str) or not re.fullmatch("[0-9a-f]{64}", h):
                raise PackError("Invalid blob digest")
            path = safe_join(bundle, "blobs/" + h)
            if not path.is_file() or path.stat().st_size != entry["size"]:
                raise PackError(f"Missing or incorrect-size blob: {h} ({rel})")
            if h not in checked and digest(path) != h:
                raise PackError(f"Hash mismatch: {h} ({rel})")
            checked.add(h)
    return lock
