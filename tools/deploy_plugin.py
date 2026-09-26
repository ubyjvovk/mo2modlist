import argparse
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("mo2", type=Path)
args = parser.parse_args()
target = args.mo2.resolve() / "plugins/mo2_modlists_plugin"
target.mkdir(parents=True, exist_ok=True)
shutil.copytree(root / "plugin/mo2_modlists_plugin", target, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(root / "mo2_modlists", target / "mo2_modlists", dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"))
print(target)
