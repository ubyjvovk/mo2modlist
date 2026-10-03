# MO2 Modlists

**Describe a mod setup once. Install it, share it, and recreate it in Mod Organizer 2.**

MO2 Modlists adds dependency resolution and reproducible installation to MO2. One `package.json` describes a mod or a whole collection: its name, version, dependencies, download sources, and installation instructions. The extension resolves those requirements, prepares a reviewable installation, and records exactly what it installed.

**Development preview · 0.10.0 · Windows · Cyberpunk 2077 and Fallout: New Vegas**

## Why this exists

Installing a mod often means installing several other mods first. Each has its own download page, version requirements, archive layout, and instructions. Sharing a working setup usually means asking someone else to repeat that work—and hoping they make the same choices.

MO2 Modlists makes those choices explicit and reusable:

- **Dependencies have names and versions.** Ask for `appearance-menu-mod: ~2.1.0`; its package definition says where to get it. A Nexus file ID identifies a download, not the dependency itself.
- **A mod and a modlist use the same format.** A mod supplies files and may have dependencies. A collection can simply depend on other packages. Installation instructions live in that same definition.
- **Ordinary installs are declarative.** Recognize an archive layout or describe which files go where. Most packages need no executable installer.
- **Sharing does not require redistributing archives.** Commit the definition to Git or publish its URL; each user obtains the files from their original sources.
- **A working result can be locked.** Keep the lock and cached archives to recreate the managed installation without selecting versions again.

The format follows npm's `package.json` conventions, with MO2-specific fields under `mo2`. It leaves room for ordinary npm metadata without adding another author-maintained JSON file. MO2 Modlists handles game deployment; public npm registry downloads are not implemented.

## How it works

1. **Load a package.** Open a local definition or a public HTTPS URL. Dependencies refer to named packages in its catalog, which can include other local or remote definitions.
2. **Resolve the graph.** Select compatible versions across all requirements, obtain their archives, and determine installation paths. Missing metadata, installer choices, and unresolved conflicts need a decision before the plan can be finalized.
3. **Lock the result.** Record exact artifacts, SHA-256 hashes, dependency selections, installation mappings, file winners, and the target game's identity. Cache the verified archives.
4. **Review and install.** Create a fresh MO2 profile or review an addition to an existing one. Stage verified files and deploy them to MO2 mod folders or, where necessary, the physical game directory.

| Item | Purpose |
| --- | --- |
| `package.json` | The editable definition: what you want and how its packages are installed. |
| Generated lock | The resolved result: exact versions, artifacts, hashes, and installation decisions. |
| Archive cache | The bytes needed to install that result again. |
| MO2 profile | The deployed setup you select and launch through MO2. |

“One package file” means one **author-maintained definition**, not the absence of generated state. Locks and caches let the installer reproduce a result even after a download page changes. A finalized lock can be installed offline when all its archives are cached.

This covers managed mod files. Saves, local configuration edits, and MO2's Overwrite contents need their own backup. Files deployed to the physical game directory are shared by every profile using that game.

## Installation

### Requirements

- Windows and Mod Organizer 2 with Python plugin support enabled. The tested MO2 version is **2.5.2, 64-bit**.
- A supported game: **Cyberpunk 2077** or **Fallout: New Vegas**.
- For this preview, an MO2 instance with `mods`, `profiles`, and `overwrite` directly inside the same instance directory. Custom external mods/Overwrite paths are not supported.
- **Python 3.12 or newer** to build from source or use the standalone CLI. The packaged MO2 plugin includes its core and vendored Python dependencies.
- **7-Zip** for archives that need the external extractor. The CLI looks for `7z` on `PATH`, then in the standard Windows 7-Zip installation directory.

Start with a test MO2 instance while the project is in development preview.

### Install a built plugin ZIP

1. Close MO2.
2. Extract `MO2-Modlists-0.10.0.zip` into the **MO2 installation directory**, beside `ModOrganizer.exe`, preserving the ZIP's directory structure.
3. Confirm that `plugins\mo2_modlists_plugin\plugin.py` exists under that directory.
4. Start MO2 and open **Tools → Modlists / Export or install**.

This is an MO2 extension: extract it beside MO2 rather than installing it as a game mod in the left pane. If you do not have a built ZIP, build one from source below.

### Install from source

In PowerShell:

```powershell
git clone https://github.com/ubyjvovk/mo2modlist.git
cd mo2modlist
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

With MO2 closed, deploy into the directory containing its executable:

```powershell
.\.venv\Scripts\python.exe tools\deploy_plugin.py 'C:\Modding\TestMO2'
```

Alternatively, produce the distributable ZIP:

```powershell
.\.venv\Scripts\python.exe tools\package_plugin.py
```

The build writes `artifacts\MO2-Modlists-0.10.0.zip` and its SHA-256 file. Restart MO2 after deploying or replacing the plugin.

The editable Python install applies to the CLI in this virtual environment. MO2 loads its deployed copy of the plugin, so source changes require another deployment and restart. Likewise, changing a mod's source directory does not update an already installed archive in MO2.

## Your first install

1. Close the game and open **Tools → Modlists / Export or install** in MO2.
2. Choose **Install package.json or lock…** for a local file, or **Install manifest from URL…** for a public package URL.
3. Choose a fresh profile and complete any source, download, or installer choices.
4. Review the selected packages, conflicts, and any files destined for the physical game directory. Approve the installation when the plan is correct.
5. Refresh or restart MO2, select the imported profile, and launch the game through MO2.

Public GitHub file links are accepted and normalized to their raw JSON URLs. A remote package's relative references are resolved relative to that document.

For a real package definition, see [Cassel Twins Survive](https://github.com/ubyjvovk/cassel-twins-survive/blob/main/package.json). It is a quest-mod prototype for Cyberpunk 2077 2.31 with Phantom Liberty, with named framework dependencies and declarative installation. Its [raw package URL](https://raw.githubusercontent.com/ubyjvovk/cassel-twins-survive/main/package.json) can be used in the URL installer when those game requirements match.

## Writing a package

Here is a mod with one dependency and an explicit file mapping:

```json
{
  "name": "my-cyberpunk-mod",
  "version": "1.0.0",
  "displayName": "My Cyberpunk Mod",
  "dependencies": {
    "appearance-menu-mod": "~2.1.0"
  },
  "mo2": {
    "schemaVersion": 1,
    "game": { "id": "cyberpunk2077", "dlc": [] },
    "sources": [
      { "type": "local-archive", "path": "./my-mod.zip" }
    ],
    "install": [
      { "from": "archive", "to": "archive", "class": "mo2-overlay" }
    ],
    "packages": ["./appearance-menu-mod/package.json"]
  }
}
```

The archive and referenced dependency definition must actually exist. The dependency definition supplies its own version, sources, and installation instructions; the installer does not search Nexus by display name.

`mo2.packages` is the available package catalog. Entries can be inline definitions or references to other files in this same format, including multiple versions of a package. The resolver selects one compatible version of each named package per profile. Conflicting definitions with the same name and version are rejected.

A collection uses this same structure but can omit sources and installation actions and only declare dependencies. Standard npm fields such as `description`, `repository`, `license`, `files`, and `scripts` can live alongside `mo2`.

| Range | Meaning |
| --- | --- |
| `2.1.0` | Exactly 2.1.0 |
| `~2.1.0` | At least 2.1.0, below 2.2.0 |
| `^2.1.0` | At least 2.1.0, below 3.0.0 |
| `>=2.1.0 <3.0.0` | An explicit compatible interval |

Use npm range syntax; Python's `~=2.1` is not accepted. Prerelease versions require a range that admits them. Git URLs, npm aliases, and dist-tags are not supported dependency ranges.

Without `mo2.install`, the game adapter recognizes standard layouts. Explicit mappings handle wrapped archives and selected installer outputs. `"install": []` deliberately deploys no files. Mapping classes are `mo2-overlay` for virtualized mod files and `game-root` for physical game-directory files.

See [the package reference](PACKAGES.md) for sources, integrity pins, conflicts, plugin order, scripts, and profile resolution.

## Working with profiles

### Add a mod or collection

Choose **Add mod/modlist to current profile…**. The extension starts from the profile's **currently enabled mods**, combines their requirements with the incoming package, and resolves the graph once. Compatible installed versions are preferred and their existing folders are reused. A manually installed dependency can be adopted when its recorded source and files match; folder names alone do not establish identity.

Choose **Reuse compatible installed versions** (the default) or **Upgrade to newer compatible versions**. If a new requirement needs a newer dependency, the resolver can select it and show the replacement in the review. Exactly one version of a named package is selected. Existing exact pins and incompatible requirements must be reconciled.

Unchanged mods reuse their folders. Replacements get separate folders, and old folders remain available to other profiles. Settings, saves, disabled entries, and separators are preserved. Local modifications to files being replaced, unresolved file conflicts, or incompatible recorded ownership of game-root files block the update until resolved.

The reviewed plan is tied to the profile state. If that state changes before application, the plan must be reviewed again. Close the game for deployment and restart MO2 afterward to reload the profile state.

### Export a setup

Choose **Export package.json…**. A resolved, managed profile supplies the selected versions and dependency definitions, which are exported inline in one package file. There are no separate cache-local recipe files for the recipient to maintain.

An export does not contain mod archives, saves, local edits, Overwrite contents, or unrecorded game-root additions. Local archive references remain local paths; make those archives available separately or publish suitable sources. Unknown sources and unrecorded installer choices need explicit metadata rather than guesses.

For a manually assembled profile, export resolves recorded sources to obtain package versions and dependency metadata. Missing metadata requires a package definition. The exported result uses the same `package.json` format.

### Check for updates

**Check manifest updates…** compares a remotely installed definition and its referenced metadata with the publisher's current versions. **Review changed manifest…** opens the normal resolution and review workflow. A check never installs anything by itself.

Automatic checks run at startup and hourly, observing a minimum 24-hour interval per active profile. Disable them with the `check-manifest-updates` plugin setting. A newer upstream archive alone does not change a pinned package: its published definition or requested version must change.

Applying a changed definition through the addition workflow adds or replaces requests. It does not automatically remove requests the publisher has deleted.

## Command-line use

The CLI uses the same core as the MO2 extension. After the source installation above, run it from the repository directory:

```powershell
# Validate the definition, then resolve it against your game.
.\.venv\Scripts\python.exe -m mo2_modlists.cli validate package.json
.\.venv\Scripts\python.exe -m mo2_modlists.cli resolve --manifest package.json --lock package.lock.json --cache C:\ModCache --game C:\Games\Cyberpunk2077

# Inspect the resolved result before deployment.
.\.venv\Scripts\python.exe -m mo2_modlists.cli inspect --manifest package.json --lock package.lock.json

# Install into a fresh profile. Close the game first.
.\.venv\Scripts\python.exe -m mo2_modlists.cli install --manifest package.json --lock package.lock.json --cache C:\ModCache --game C:\Games\Cyberpunk2077 --mo2 C:\Modding\TestMO2 --profile MySetup

# Compare installed managed files with the lock, without changing them.
.\.venv\Scripts\python.exe -m mo2_modlists.cli verify --manifest package.json --lock package.lock.json --cache C:\ModCache --game C:\Games\Cyberpunk2077 --mo2 C:\Modding\TestMO2 --profile MySetup
```

Replace the example paths with your game and MO2 **instance data** directories. Deployment into the physical game directory additionally requires `--allow-root`; review those files before supplying it. Existing output files are preserved, so use a new lock path when resolving a new result.

The installed console command is also available as `.\.venv\Scripts\mo2-modlists.exe`. Run any command with `--help` for its arguments. Provider conversion and export need `--game` and `--cache` because they resolve source metadata before publishing the package.

| Command | Purpose |
| --- | --- |
| `validate` | Validate a local package definition. |
| `resolve` | Resolve dependencies, prepare archives, and write a lock. |
| `inspect` | Read the locked installation without deploying it. |
| `install` | Deploy a finalized lock. |
| `import` | Resolve when a lock is missing, then install. |
| `verify` | Report differences in managed installed files; never repair or delete them. |
| `add` | Prepare an addition/update plan, then apply its reviewed digest. |
| `export` | Export a profile's package definition. |
| `check-updates` | Check remotely sourced definitions without changing the installation. |
| `from-url` | Prepare a package definition from a Nexus mod or Collection URL. |
| `import-collection` | Convert a Nexus Collection package or URL. |
| `restore-root` | Review and restore physical game files owned by an import. |

`resolve`, `import`, `install`, `add`, `inspect`, and `verify` accept public URLs through `--manifest`; URL inspection and verification also need `--cache`.

For `add`, first pass `--manifest` to create a plan. Installed compatible versions are preferred; add `--upgrade` to prefer newer compatible candidates. Review the returned changes, then apply using `--plan` and the returned `--reviewed-sha256`. `restore-root` similarly starts with a read-only plan and requires its digest to apply. These commands bind approval to the reviewed state.

### Offline installation

Add `--offline` to `install` with a finalized lock and a complete archive cache. Installation uses the locked mappings and verified archives, including any prepared script outputs, without needing the original recipe paths or rerunning scripts.

Offline **resolution** is a different operation: it still needs the package definitions, metadata snapshots, and artifacts required to select versions. A cached URL snapshot alone does not guarantee that dependency resolution can finish offline.

## Sources, downloads, and credentials

Packages can declare ordered sources from **Nexus Mods**, **GitHub releases**, and **local ZIP/7z archives**. Sources identify where to obtain a declared version. An optional `mo2.integrity` pins its expected SHA-256; the lock always records the actual archive hash. An observed hash provides repeatable identity, but without a trusted expected hash it is not independent proof of authenticity.

Use **Optional provider credentials…** to configure provider access. The UI stores credentials in Windows Credential Manager; package definitions and locks do not contain them.

- **Nexus:** metadata and Collection requests can require a Nexus API key. Archive acquisition follows the supported MO2 download/login flow or the provider's direct-download entitlement. A key does not bypass Premium requirements; manual downloads remain available where required.
- **GitHub:** an optional token can be used for release metadata requests. Public release assets are supported.
- **Local archives:** point to an existing file. Configure additional download locations with the semicolon-separated `archive-directories` plugin setting.

Public package URLs must use HTTPS. GitHub file links and relative remote package references are supported. Private/authenticated manifest URLs and URLs with query parameters are not. Remote definitions cannot read local archives or local Git registries. Failed mirrors may allow another source; integrity failures do not silently fall back.

## Executable installers

Most packages should use recognized archive layouts or declarative file mappings. Those cover ordinary archive mods, framework files, and explicitly selected FOMOD output files without running publisher-supplied commands.

For packages that must generate or transform files, `scripts.install` is available with explicit trust:

- The UI shows the command, package version, source digest, and definition digest. The CLI requires `--allow-scripts`.
- Preparation runs **during resolution, before deployment review**, in a temporary extracted source directory. The game must be closed.
- The command runs with your account's permissions, **not in a security sandbox**, and has a five-minute timeout. External tools it needs must be available.
- Resulting files are packaged, hashed, and cached. Installation and offline reinstall use that prepared archive without rerunning the command.

Only `scripts.install` runs automatically after authorization; other npm scripts are retained as metadata. A failed script produces no finalized installation plan. Side effects outside its working directory cannot be undone by the file deployment rollback. See [script behavior and environment variables](PACKAGES.md#optional-executable-installation).

## Game-specific behavior and limits

### Cyberpunk 2077

The adapter recognizes standard archive, script, framework, and REDmod layouts. Files that need physical placement, such as bootstrap DLLs, use tracked game-root deployment. CET runtime mappings keep Lua content available when Overwrite files are present; keep the extension enabled when launching imported profiles.

Locks bind the game executable and recorded build/distribution/DLC identity. Resolve against the game installation you intend to use; a lock is not a promise of compatibility with another game update.

### Fallout: New Vegas

Game-relative `Data/...` mappings mount at MO2's Data root. Root loaders require physical deployment. ESM/ESP order is recorded separately from asset priorities, and declared TES4 master dependencies are checked. This does not replace LOOT or broader mod compatibility testing.

Apply external executable patches, such as the 4GB patch, **before resolution**, because the lock records the executable hash. Required DLC and regional language plugins must be supplied explicitly rather than borrowed silently from unmanaged files.

### Physical game files and recovery

Game-root deployment backs up replaced files and records ownership under the instance's `.modlists` directory. Incompatible ownership by another recorded profile blocks deployment. Other MO2 instances and unmanaged consumers of the same game directory are outside that ownership record.

Use **Restore imported game-root files…** to review and restore owned physical files. Restoration does not remove mod folders or saves, and a profile may need its framework files reinstalled before it can run again. File deployment rollback covers tracked writes, not arbitrary executable-script side effects.

### Installer coverage

Nexus conversion and Collection import support declared requirements, ordering, optional entries, and supported bundled content. Unresolved installer choices, manual configuration, or executable patching can require explicit mappings or reviewed external steps. General-purpose FOMOD replay and arbitrary executable installers are not automatically reproduced.

A fresh MO2 profile also does not imply a pristine game directory. Existing unmanaged files, Overwrite conflicts, and local modifications may require reconciliation before a reproducible install is possible.

## One public format

Mods, collections, exports, Nexus conversions, and installer metadata all use `package.json`. Source-only manifests, standalone recipe files, migration commands, and compatibility switches are not public formats.

Locks, archive caches, and deployment records are generated state. Profiles may contain internal files called `modlist.json` and `modlist.lock.json`; these are not additional documents for authors to maintain. Share a package definition or use **Export package.json…** rather than editing those records.

## Development and reference

Run the core tests and build the plugin from the source checkout:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\package_plugin.py
```

The MO2 UI lives in `plugin/mo2_modlists_plugin`; resolution, acquisition, and deployment live in `mo2_modlists`. The core and CLI can be exercised without loading MO2. Actual virtual-filesystem behavior and gameplay still need testing in MO2 with the target game.

- [Package reference](PACKAGES.md): authoring format, version ranges, sources, scripts, and profile resolution.
- [Acceptance record](ACCEPTANCE.md): verification performed and the limits of that evidence.
- [Implementation progress](PROGRESS.md): development history and outstanding work.
- [Architecture](SPEC.md): package resolution, generated deployment records, and installation boundaries.

This is a development preview, not a claim that every mod or Collection for the supported games can already be installed automatically. Package-resolution tests, live MO2 checks, and gameplay validation cover different parts of the system; consult the acceptance record for what has actually been exercised.
