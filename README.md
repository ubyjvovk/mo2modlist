# MO2 Modlists

MO2 Modlists is a Mod Organizer 2 extension for describing and recreating a mod setup from **one readable `modlist.json`**. Its aim is to make mod installation work more like a software package manager: record the mods you want and their sources, resolve their dependencies, then install a reproducible setup without repeating the same manual download and configuration steps.

The manifest describes mods and pinned versions from Nexus Mods, GitHub release assets, or local archives. It can be shared and versioned without bundling the mod files themselves. Version 0.7 is a development preview supporting **Cyberpunk 2077** and **Fallout: New Vegas**; the agreed manifest format is documented in [SPEC.md](SPEC.md).

## How it works

1. **Describe the setup.** Export an existing MO2 profile, convert a Nexus mod or Collection URL, or write a manifest yourself. A mod URL includes its direct requirements; resolution expands transitive dependencies.
2. **Resolve and review.** The resolver selects exact artifacts and uses dependency metadata and installation recipes to determine what to install and where. Missing metadata, required installer choices, and unresolved file conflicts need review before the installation can be finalized.
3. **Lock and cache.** Resolution produces a lock recording the exact artifacts, hashes, recipes, and selections, and downloads verified archives into a reusable cache. A finalized lock can be installed fully offline when all its archives are cached.
4. **Install a fresh profile.** The importer stages the resolved files and creates a new MO2 profile with the recorded priorities and choices. The manifest remains the editable description; the lock and cache provide the concrete inputs for repeatable installation.

This reproduces the managed mod installation, not a complete backup of saves, local configuration edits, or MO2 overwrite contents. Local archive and recipe references must remain available on the importing machine. Frameworks that require files in the game directory use tracked physical deployment, so those files are shared between profiles. See the workflows below for these boundaries and the required review steps.

## Create a manifest from a Nexus URL

In MO2 choose **Create manifest from Nexus URL…** and paste a Cyberpunk or New Vegas mod or Collection URL. Mod conversion pins the selected mod and its immediate requirements to exact Nexus file IDs. Transitive requirements are expanded during resolution, not flattened into this manifest. An ambiguous file choice requires selection. Metadata needs the optional Nexus API credential; unknown requirements do not produce a silently incomplete manifest. Collection URLs use the existing full-package conversion and review workflow.

New Vegas uses game-relative `Data/...` recipe paths, mounted at the Data directory by MO2. Root loaders and wrapped or ambiguous archives require explicit recipes. Active ESM/ESP order is recorded separately from asset priorities; TES4 master dependencies are checked before installation. Automatic ordering satisfies declared masters only and does not replace LOOT or compatibility review. The executable hash, distribution and installed DLC are bound to each lock, so apply an external 4GB patch before resolution. Regional language plugins must be supplied explicitly if needed; they are not silently imported from unmanaged game files.

Collection conversion supports bundled directories and hash-bound review records for external steps or obsolete rules. Unhandled entries still block finalization. Patching executables, installing runtimes and configuring profile INIs are external handoffs, not automatic installer actions; record completion before acknowledging their prerequisites.

```powershell
.\.venv\Scripts\python.exe -m mo2_modlists.cli from-url 'https://www.nexusmods.com/cyberpunk2077/mods/32203' --output modlist.json
```

For Collection URLs also supply `--cache <directory>` and, when needed, `--decisions <json>`. Existing output files are preserved. Installing the resulting finalized lock with `install --offline` requires all locked archives in the cache; recipes and selections are already embedded in that lock. It does not refresh metadata or select new files.

New installations use Nexus names, Collection names, or manifest aliases. Independent copies with the same name get a readable profile suffix rather than an internal hash in their displayed name. Internal component IDs and ownership journals remain separate.

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

Re-exporting a profile installed by this extension retains its original recipe reference when that file still exists and matches the recorded recipe hash. It remains a local reference, just like a local archive, and must be accessible on the importing machine. Changed/missing recipes are not silently reused; resolution will need replacement metadata. Export still writes only `modlist.json`.

## Install in MO2

Choose **Install modlist.json or lock…**, select the source manifest, and name a new profile. Resolution acquires exact artifacts and expands declared recipe dependencies. Unknown dependency metadata prompts for a recipe; see [RECIPES.md](RECIPES.md). Git registries can supply supplemental recipes from a pinned commit. Required options, dependency alternatives and unresolved file winners are recorded before finalization.

Review the resulting components and physical game-folder writes, then install. The importer stages verified files, creates distinct mod directories and publishes the new profile last. Physical root files affect every profile using that game and changed originals are backed up under the instance's `.modlists` directory. Existing Overwrite content that would alter the imported setup blocks deployment. The game must be closed for installation; planning and downloads can run while it is open.

Retry the same manifest/lock and profile name after an interrupted operation. Verified cached archives and staging are reused. A completed profile is never overwritten. Restart MO2 to refresh its profile selector and select the new profile manually.

Keep the extension enabled when launching imported profiles. Version 0.6.3 supplies explicit virtual mappings for physically deployed CET mod data, so Lua files remain visible after CET creates runtime files in Overwrite. Existing enabled-mod and Overwrite mappings retain priority. Bootstrap DLLs remain physically deployed; this does not make root changes profile-isolated.

**Restore imported game-root files…** reviews the physical changes owned by an installation, restores verified backups and removes files that installation added. Mod/profile folders remain, but the selected profile will no longer have those root files. Changed files, damaged backups and other imported profiles requiring the same paths block restoration. Interrupted restoration can be reviewed and resumed. This tracks consumers within this MO2 instance; other instances and unmanaged consumers are not detectable. Older journals without recorded game/profile targets require manual recovery from their backups.

**Import Nexus Collection…** accepts a full downloaded package, saved review draft or Collection URL. Optional entries and supported ordering/dependency rules are retained; embedded archives are extracted and verified. Unhandled installer choices/patches can be supplied as a prepared archive plus recipe with an explicit handoff record. Other unresolved instructions produce a review draft, not a completed pack. Collection-level external steps require acknowledgement for each installation target. URL downloads use the optional stored Nexus API key when required; the downloaded-package route is also available. MO2's supported download manager handles individual Nexus mod archives.

If MO2 cannot start or complete a Nexus download, the importer offers an explicit manual-archive handoff showing the exact mod/file URL. The artifact keeps its Nexus identity; provided and locked hashes are still mandatory. A first download without a supplied digest remains labelled locally observed.

## CLI

Python 3.12+. Commands are `export`, `validate`, `resolve`, `install`, `import`, `import-collection`, `inspect`, `verify` and `restore-root`:

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

`restore-root --mo2 <instance> --game <game> --operation <operation-id>` prints a read-only restoration plan and `reviewedSha256`. Repeat with `--reviewed-sha256 <digest>` to apply that exact reviewed state. The operation ID is the journal's parent directory under `.modlists`. Any intervening change requires a new review.

## Status

Source export is implemented and tested in MO2 2.5.2, including Local archive, URL and Skip. The real Play test export contains 15 dependencies, with AMM referenced locally and DLSS explicitly skipped. Its output directory contains only `modlist.json`.

The source importer has passed a tiny real-MO2 test: source JSON plus recipe/archive -> inspected lock -> fresh profile, then a second profile from the lock/cache after removing the original recipe/archive. Dependency choice UI ran on the Qt owning thread. Existing profile contents were preserved. Core tests cover transitive dependencies, selected alternatives/variants, conflicts, rollback/retry, cache-only installs, registry commit/hash verification and Collection conversion.

Nexus native dependency domains are solved with vendored resolvelib 1.2.1. Shared constraints intersect and incompatible candidates backtrack, including alternatives across file lineages. Exact pack pins constrain the result. Candidate selection was exercised inside real MO2; fixture tests cover transitive incompatibilities, cycles, missing DLC and unsatisfiable reason chains.

**The full specification is not complete.** Authenticated Nexus resolution now works against Immersive Third Person and its transitive frameworks. Representative Collection validation, fresh-instance runtime verification and the real source-import game smoke test remain. The historical snapshot game's successful launch does not verify the new source importer.

Optional **Provider credentials…** stores a Nexus API key or GitHub token in Windows Credential Manager. Nexus metadata combines v3 file lineages/requirements with the supported GraphQL `mod.modRequirements` and `legacyModRequirementsEnabled` fields. Legacy requirements and their notes are snapshotted; conditional requirements and external dependencies require review. A single eligible file can be pinned automatically; multiple candidates require selection. Optional GitHub authentication applies to release metadata requests. No credential is exported or read from MO2's private credential storage.

MO2 2.5.2 downloads use its bound `startDownloadNexusFile(modId, fileId)` method for the managed game. Newer bindings may offer a game-qualified method. CLI resolution/import can download exact files using the configured Nexus API key when the account has Premium. Non-Premium accounts still need Nexus's website flow for archives; an API key enables metadata but does not remove that restriction. When Nexus publishes an archive SHA-256 through its scan reference, matching cached/local bytes can be reused without downloading again, preserving Nexus source identity.

The manifest schema is [modlist.schema.json](mo2_modlists/modlist.schema.json). Recipe/registry and Collection details are in [RECIPES.md](RECIPES.md). The current acceptance tracker is at the top of [PROGRESS.md](PROGRESS.md).

The disposable integration helpers under `tools/` are not included in the plugin ZIP. Historical validation and current changes are recorded in [PROGRESS.md](PROGRESS.md).
