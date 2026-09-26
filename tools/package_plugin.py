from pathlib import Path
import hashlib
import zipfile

root = Path(__file__).resolve().parents[1]
output = root / "artifacts/MO2-Modlists-0.1.0.zip"
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
