# MO2 Modlists

Version 0.5 development preview exports **one `modlist.json`**, following [SPEC.md](SPEC.md), and implements a separate source resolver/importer. Export does not include locks, blobs or copied archives. The old installed-snapshot importer remains removed. Locks and caches are produced during resolution/import.

## Export in MO2

Deploy to a test instance, restart MO2, then choose **Tools → Modlists / Export or install**:

```powershell
.\.venv\Scripts\python.exe tools\deploy_plugin.py 'C:\Path\To\TestMO2'
```

Select the profile, click **Export modlist.json…**, and choose a new filename. Recorded Nexus mod/file IDs and explicitly configured GitHub provenance become dependencies. If a mod has no known source, the export dialog asks you to:

- Select an existing local ZIP/7z archive. The manifest stores its path and SHA-256; it is not copied.
- Provide a Nexus mod/file page URL or exact GitHub release asset URL.
- Explicitly skip that mod. The completion dialog lists skipped mods.

Cancel cancels the whole export. Existing export files are preserved. Other website URLs are not a source type in the agreed schema: download their archive and select it locally.

Additional archive directories and a GitHub source catalog can be configured in the plugin settings. A catalog is an array of `Name`, `Version`, `Url`, `SHA256` records. Sources are not guessed from mod names or archive filenames. GitHub catalog versions must match recorded installed versions when present.

Export includes enabled source dependencies and explicit file-conflict winners derived from the current profile. It does not copy local configuration edits, overwrite contents, root-only additions or saves. Unrecorded FOMOD choices need explicit recipes/options. A local archive path is portable only when that archive remains available or is supplied separately.

## Install in MO2

Choose **Install modlist.json or lock…**, select the source manifest, and name a new profile. Resolution acquires exact artifacts and expands declared recipe dependencies. Unknown dependency metadata prompts for a recipe; see [RECIPES.md](RECIPES.md). Git registries can supply supplemental recipes from a pinned commit. Required options, dependency alternatives and unresolved file winners are recorded before finalization.

Review the resulting components and physical game-folder writes, then install. The importer stages verified files, creates distinct mod directories and publishes the new profile last. Physical root files affect every profile using that game and changed originals are backed up under the instance's `.modlists` directory. Existing Overwrite content that would alter the imported setup blocks deployment. The game must be closed for installation; planning and downloads can run while it is open.

Retry the same manifest/lock and profile name after an interrupted operation. Verified cached archives and staging are reused. A completed profile is never overwritten. Restart MO2 to refresh its profile selector and select the new profile manually.

**Import Nexus Collection…** accepts a full downloaded package, saved review draft or Collection URL. Optional entries and supported ordering/dependency rules are retained; embedded archives are extracted and verified. Unhandled installer choices/patches can be supplied as a prepared archive plus recipe with an explicit handoff record. Other unresolved instructions produce a review draft, not a completed pack. Collection-level external steps require acknowledgement for each installation target. URL downloads use the optional stored Nexus API key when required; the downloaded-package route is also available. MO2's supported download manager handles individual Nexus mod archives.

## CLI

Python 3.12+. Commands are `export`, `validate`, `resolve`, `install`, `import`, `import-collection`, `inspect` and `verify`:

```powershell
.\.venv\Scripts\python.exe -m mo2_modlists.cli export `
  --mo2 'E:\Modding\Cyberpunk2077' --game 'E:\Games\Cyberpunk 2077' `
  --profile Play --output 'E:\Exports\modlist.json' `
  --github-manifest 'E:\Modding\downloads\base-mod-manifest.json' `
  --archives 'E:\Modding\downloads' --choices 'E:\Exports\choices.json'

.\.venv\Scripts\python.exe -m mo2_modlists.cli validate 'E:\Exports\modlist.json'
.\.venv\Scripts\python.exe -m mo2_modlists.cli resolve --manifest 'E:\Exports\modlist.json' --lock 'E:\Exports\modlist.lock.json' --cache 'E:\ModCache' --game 'E:\Games\Cyberpunk 2077'
.\.venv\Scripts\python.exe -m mo2_modlists.cli install --manifest 'E:\Exports\modlist.json' --lock 'E:\Exports\modlist.lock.json' --cache 'E:\ModCache' --game 'E:\Games\Cyberpunk 2077' --mo2 'E:\TestMO2' --profile 'Imported' --allow-root --offline
.\.venv\Scripts\python.exe -m mo2_modlists.cli inspect --manifest 'E:\Exports\modlist.json' --lock 'E:\Exports\modlist.lock.json'
.\.venv\Scripts\python.exe -m mo2_modlists.cli verify --manifest 'E:\Exports\modlist.json' --lock 'E:\Exports\modlist.lock.json' --game 'E:\Games\Cyberpunk 2077' --mo2 'E:\TestMO2' --profile 'Imported'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The optional CLI choices file maps exact MO2 mod names to dependency objects; `null` explicitly skips a mod. Unknown sources without a choice block export. Local paths inside dependency objects resolve relative to the exported manifest, not the working directory. The choices file is a CLI input, not an exported artifact. Use the MO2 dialog for interactive source selection.

`inspect` reports a validated lock's components, sources, ordering, physical game files and prerequisites without installing. `verify` checks the installed profile's managed initial files, component identities and enabled ordering against that lock, returning a nonzero exit status for differences. Runtime edits and extra files inside installed mod directories are reported; neither unmanaged game-folder files nor gameplay compatibility are covered. Verification never repairs or removes files.

## Status

Source export is implemented and tested in MO2 2.5.2, including Local archive, URL and Skip. The real Play test export contains 15 dependencies, with AMM referenced locally and DLSS explicitly skipped. Its output directory contains only `modlist.json`.

The source importer has passed a tiny real-MO2 test: source JSON plus recipe/archive -> inspected lock -> fresh profile, then a second profile from the lock/cache after removing the original recipe/archive. Dependency choice UI ran on the Qt owning thread. Existing profile contents were preserved. Core tests cover transitive dependencies, selected alternatives/variants, conflicts, rollback/retry, cache-only installs, registry commit/hash verification and Collection conversion.

Nexus native dependency domains are solved with vendored resolvelib 1.2.1. Shared constraints intersect and incompatible candidates backtrack, including alternatives across file lineages. Exact pack pins constrain the result. Candidate selection was exercised inside real MO2; fixture tests cover transitive incompatibilities, cycles, missing DLC and unsatisfiable reason chains.

**The full specification is not complete.** Live authenticated provider and representative Collection validation, broader crash recovery and root restoration, fresh-instance prerequisites and the real mixed-source game smoke test remain. The historical snapshot game's successful launch does not verify the new source importer.

Optional **Provider credentials…** stores a Nexus API key or GitHub token in Windows Credential Manager. A Nexus key enables the isolated v3 metadata adapter and Collection package requests. It enumerates file lineages and versions, retains raw and materialized dependency definitions, and locks the solver's selections. An ambiguous top-level mod page still requires an explicit file choice. Empty new-style requirements remain unknown because the current GET schema does not identify whether legacy page requirements apply. Optional GitHub authentication applies to release metadata requests. No credential is exported or read from MO2's private credential storage.

The manifest schema is [modlist.schema.json](mo2_modlists/modlist.schema.json). Recipe/registry and Collection details are in [RECIPES.md](RECIPES.md). The current acceptance tracker is at the top of [PROGRESS.md](PROGRESS.md).

The disposable integration helpers under `tools/` are not included in the plugin ZIP. Historical validation and current changes are recorded in [PROGRESS.md](PROGRESS.md).
