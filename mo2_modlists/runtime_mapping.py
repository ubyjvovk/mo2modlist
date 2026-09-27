"""Expose physically deployed CET scripts to MO2's relative-path lookup."""
from pathlib import Path

from .core import PackError, safe_join


def cet_root_files(lock, game):
    """Return only locked CET mod data; native libraries must not self-map.

    USVFS can redirect CET's working directory into Overwrite once a mod
    creates its database/log. Explicit file mappings keep its physical Lua
    files visible to relative opens on subsequent launches.
    """
    if (lock.get("kind") != "source-installation" or lock.get("schemaVersion") != 1
            or lock.get("game", {}).get("id") != "cyberpunk2077"):
        raise PackError("Unsupported profile lock for CET runtime mappings")
    result, seen = [], set()
    for key in lock["priority"]:
        for entry in lock["packages"][key]["outputs"]:
            rel = entry["path"]
            canonical = rel.casefold()
            if entry["class"] != "game-root" or canonical in seen:
                continue
            seen.add(canonical)
            if not canonical.startswith("bin/x64/plugins/cyber_engine_tweaks/mods/"):
                continue
            target = safe_join(Path(game), rel)
            if target.suffix.lower() in (".dll", ".exe", ".asi", ".pyd"):
                continue
            if target.is_file():
                result.append((rel, target))
    return result
