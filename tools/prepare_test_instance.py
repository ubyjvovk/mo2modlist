"""Create a separate MO2 portable test instance; never copy credentials/settings wholesale."""
import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mo2_modlists.core import game_identity, read_ini, vanilla_paths


def prepare(source, target, game, clone_game=None):
    source, target, game = source.resolve(), target.resolve(), game.resolve()
    if target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("Target must be a new directory separate from source")
    target.mkdir(parents=True)
    allowed_dirs = {"dlls", "explorer++", "licenses", "loot", "platforms", "plugins", "qml",
                    "resources", "styles", "stylesheets", "translations", "tutorials"}
    for item in source.iterdir():
        if item.is_dir() and item.name in allowed_dirs:
            shutil.copytree(item, target / item.name)
        elif item.is_file() and item.suffix.lower() in (".exe", ".dll"):
            shutil.copy2(item, target / item.name)
    (target / "portable.txt").touch()
    if clone_game:
        clone_game = clone_game.resolve()
        if clone_game.exists() or clone_game.is_relative_to(game):
            raise ValueError("Game clone destination must be new and outside the source")
        clone_game.mkdir(parents=True)
        wanted = vanilla_paths(game)
        for item in game.rglob("*"):
            rel = item.relative_to(game)
            if item.is_file() and (rel.as_posix().casefold() in wanted or item.name.startswith("goggame-")):
                print(f"Copying base file {rel}", flush=True)
                dst = clone_game / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)
        if game_identity(game) != game_identity(clone_game):
            raise ValueError("Cloned base identity differs")
        game = clone_game
    # This is a test fixture, not an exported copy of the user's global INI.
    ini = f'''[General]
gameName=Cyberpunk 2077
gamePath={game.as_posix()}
selected_profile=@ByteArray(Default)

[Settings]
base_directory={target.as_posix()}

[customExecutables]
size=1
1\\title=Cyberpunk 2077
1\\binary={game.as_posix()}/bin/x64/Cyberpunk2077.exe
1\\workingDirectory={game.as_posix()}/bin/x64
1\\arguments=--launcher-skip
1\\ownicon=true

[Plugins]
Cyberpunk%202077%20Support%20Plugin\\disable_crashreporter=false
'''
    (target / "ModOrganizer.ini").write_text(ini, encoding="utf-8")
    profile = target / "profiles/Default"
    profile.mkdir(parents=True)
    (profile / "modlist.txt").write_text("# Empty test profile\n")
    (profile / "settings.ini").write_text("[General]\nLocalSaves=false\nLocalSettings=false\n")
    for name in ("mods", "overwrite", "downloads"):
        (target / name).mkdir(exist_ok=True)
    print(f"Test instance ready: {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for arg in ("source", "target", "game"):
        parser.add_argument("--" + arg, required=True, type=Path)
    parser.add_argument("--clone-game", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.target, args.game, args.clone_game)
