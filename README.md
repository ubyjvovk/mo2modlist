# MO2 Modlists

Version 0.3 exports **one `modlist.json`**, following the source-manifest schema in [SPEC.md](SPEC.md). It does not export a lockfile, blobs or copied archives. The old bundle importer has been removed from the UI, CLI and core.

## Export in MO2

Deploy to a test instance, restart MO2, then choose **Tools → Modlists / Export modlist.json**:

```powershell
.\.venv\Scripts\python.exe tools\deploy_plugin.py 'C:\Path\To\TestMO2'
```

Select the profile, click **Export modlist.json…**, and choose a new filename. Recorded Nexus mod/file IDs and explicitly configured GitHub provenance become dependencies. If a mod has no known source, the export dialog asks you to:

- Select an existing local ZIP/7z archive. The manifest stores its path and SHA-256; it is not copied.
- Provide a Nexus mod/file page URL or exact GitHub release asset URL.
- Explicitly skip that mod. The completion dialog lists skipped mods.

Cancel cancels the whole export. Existing export files are preserved. Other website URLs are not a source type in the agreed schema: download their archive and select it locally.

Additional archive directories and a GitHub source catalog can be configured in the plugin settings. A catalog is an array of `Name`, `Version`, `Url`, `SHA256` records. Sources are not guessed from mod names or archive filenames. GitHub catalog versions must match recorded installed versions when present.

Export includes enabled source dependencies and explicit file-conflict winners derived from the current profile. It does not copy local configuration edits, overwrite contents, root-only additions or saves. Unrecorded FOMOD choices cannot be reconstructed from source references alone; the future importer must request them or use recipes/options. A local archive path is portable only when that archive remains available or is supplied separately.

## CLI

Python 3.12+. `export` and `validate` are the current commands:

```powershell
.\.venv\Scripts\python.exe -m mo2_modlists.cli export `
  --mo2 'E:\Modding\Cyberpunk2077' --game 'E:\Games\Cyberpunk 2077' `
  --profile Play --output 'E:\Exports\modlist.json' `
  --github-manifest 'E:\Modding\downloads\base-mod-manifest.json' `
  --archives 'E:\Modding\downloads' --choices 'E:\Exports\choices.json'

.\.venv\Scripts\python.exe -m mo2_modlists.cli validate 'E:\Exports\modlist.json'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The optional CLI choices file maps exact MO2 mod names to dependency objects; `null` explicitly skips a mod. Unknown sources without a choice block export. Local paths inside dependency objects resolve relative to the exported manifest, not the working directory. The choices file is a CLI input, not an exported artifact. Use the MO2 dialog for interactive source selection.

## Status

Source export is implemented and tested in MO2 2.5.2, including Local archive, URL and Skip. The real Play test export contains 15 dependencies, with AMM referenced locally and DLSS explicitly skipped. Its output directory contains only `modlist.json`.

**The agreed source-manifest resolver/installer is not yet implemented.** The earlier snapshot round trip demonstrated game deployment but did not satisfy the source-manifest workflow. Version 0.3 deliberately exposes no import action until that workflow exists. No claim is made that the new JSON alone has passed an install/gameplay test.

The machine-readable schema is [modlist.schema.json](mo2_modlists/modlist.schema.json). Runtime validation additionally checks dependency cross-references and Windows path rules. New dependency resolution, recipes, native metadata acquisition, cache/lock generation and source-based deployment remain the next implementation work described in [SPEC.md](SPEC.md).

The disposable integration helpers under `tools/` are not included in the plugin ZIP. Historical validation and current changes are recorded in [PROGRESS.md](PROGRESS.md).
