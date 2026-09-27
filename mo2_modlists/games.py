"""Game-specific identities and canonical game-relative deployment paths."""
from .core import PackError, safe_relative

EXECUTABLES = {"cyberpunk2077": "bin/x64/Cyberpunk2077.exe", "newvegas": "FalloutNV.exe"}
ADAPTERS = {"cyberpunk2077": "cp77-1", "newvegas": "fnv-1"}
FNV_DLCS = {
    "dead-money": "DeadMoney.esm", "honest-hearts": "HonestHearts.esm",
    "old-world-blues": "OldWorldBlues.esm", "lonesome-road": "LonesomeRoad.esm",
    "gun-runners-arsenal": "GunRunnersArsenal.esm", "caravan-pack": "CaravanPack.esm",
    "classic-pack": "ClassicPack.esm", "mercenary-pack": "MercenaryPack.esm",
    "tribal-pack": "TribalPack.esm",
}
# Nexus's game-scoped identifiers were verified against the v3 DLC endpoints
# (CP77 2026-09-26, New Vegas 2026-09-27).
# Unknown provider identifiers must continue to require review.
NEXUS_DLCS = {"cyberpunk2077": {"1": "phantom-liberty", "2": "redmod"}, "newvegas": {"1": "dead-money", "2": "honest-hearts", "3": "old-world-blues", "4": "lonesome-road", "5": "gun-runners-arsenal", "6": "couriers-stash"}}


def detect_game(game):
    found = [key for key, exe in EXECUTABLES.items() if (game / exe).is_file()]
    if len(found) != 1:
        raise PackError(f"Expected one supported game executable in {game}")
    return found[0]


def executable(game):
    return game / EXECUTABLES[detect_game(game)]


def installed_dlcs(identity):
    if identity["id"] == "newvegas":
        result = set(identity["dlc"])
        if {"caravan-pack", "classic-pack", "mercenary-pack", "tribal-pack"} <= result:
            result.add("couriers-stash")
        return result
    return {key for key, present in (("phantom-liberty", identity["phantomLiberty"]),
                                    ("redmod", identity.get("redmod", False))) if present}


def nexus_dlcs(identity):
    installed = installed_dlcs(identity)
    return {key for key, value in NEXUS_DLCS[identity["id"]].items() if value in installed}


def overlay_path(game_id, path):
    """MO2 mounts New Vegas mod directories at Data, CP77 at the game root."""
    safe_relative(path)
    if game_id == "newvegas":
        if not path.casefold().startswith("data/"):
            raise PackError("New Vegas overlay outputs must be game-relative Data/... paths")
        path = path[5:]
        safe_relative(path)
    if path.casefold() in ("meta.ini", "modlists-source.json"):
        raise PackError("Archive output collides with MO2 management metadata")
    return path


def game_path(game_id, overlay):
    return "Data/" + overlay if game_id == "newvegas" else overlay


def fnv_mappings(index):
    from .acquisition import InputRequired
    result = []
    data_dirs = ("textures/", "meshes/", "sound/", "music/", "menus/", "shaders/",
                 "strings/", "video/", "nvse/", "scripts/", "config/", "seq/", "lodsettings/")
    for name, _ in index:
        lower = name.casefold()
        if lower.startswith("data/"):
            result.append({"from": name, "to": "Data/" + name[5:], "class": "mo2-overlay"})
        elif lower.startswith(data_dirs) or ("/" not in name and lower.endswith((".esm", ".esp", ".bsa"))):
            result.append({"from": name, "to": "Data/" + name, "class": "mo2-overlay"})
        elif "/" not in name and (lower.startswith(("readme", "license", "changelog")) or lower.endswith((".md", ".txt"))):
            continue
        else:
            raise InputRequired("archive-layout", "New Vegas archive needs an explicit recipe mapping (root loaders, FOMODs and wrapped layouts are not guessed)", member=name)
    if not result:
        raise InputRequired("archive-layout", "Archive contains no recognized New Vegas Data files")
    return result
