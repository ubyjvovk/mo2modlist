from pathlib import Path
import hashlib
import zipfile
import tomllib

root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
output = root / f"artifacts/MO2-Modlists-{version}.zip"
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for source, prefix in ((root / "plugin/mo2_modlists_plugin", "plugins/mo2_modlists_plugin"),
                           (root / "mo2_modlists", "plugins/mo2_modlists_plugin/mo2_modlists")):
        for file in sorted(source.rglob("*.py")):
            if "__pycache__" not in file.parts:
                archive.write(file, prefix + "/" + file.relative_to(source).as_posix())
    archive.write(root / "README.md", "MO2-Modlists-README.md")
with output.open("rb") as stream:
    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
output.with_suffix(".zip.sha256").write_text(checksum + "  " + output.name + "\n")
print(f"{output}\nSHA256 {checksum}")
