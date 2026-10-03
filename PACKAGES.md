# One package format for mods and collections

MO2 Modlists 0.10 accepts npm-shaped `package.json` files. A mod and a collection
are the same kind of package. A mod supplies files; a collection can omit sources
and installation actions and only depend on other packages. Dependencies belong
to the package, not to a Nexus file ID. No separate author-maintained recipe is
needed.

```json
{
  "name": "my-cyberpunk-mod",
  "version": "1.0.0",
  "displayName": "My Cyberpunk Mod",
  "dependencies": {"appearance-menu-mod": "~2.1.0"},
  "mo2": {
    "schemaVersion": 1,
    "game": {"id": "cyberpunk2077", "dlc": []},
    "sources": [{"type": "local-archive", "path": "./my-mod.zip"}],
    "install": [{"from": "archive", "to": "archive", "class": "mo2-overlay"}],
    "packages": ["./appearance-menu-mod/package.json"]
  }
}
```

The example's dependency definition must exist and describe the real available
version(s). `mo2.packages` is a catalog: entries are inline package definitions
or local/public HTTPS references to the **same format**. A catalog package can
itself include other definitions. Multiple versions of a name are permitted;
conflicting definitions of the same name and version are rejected. A dependency
does not need a source in the requesting package. Its selected definition supplies
sources, or it is itself a collection. There is no implicit search of Nexus by
display name, and no implicit query of the public npm registry.

The editor-facing [JSON schema](mo2_modlists/package.schema.json) describes the
structure; the resolver also validates ranges, paths, and game constraints.

## npm compatibility

Use lowercase stable package names, optionally scoped (`@author/my-mod`), and
SemVer versions. Readable names go in `displayName`. Standard npm metadata such as
`description`, `repository`, `license`, `files`, and `scripts` is retained.
MO2 settings are namespaced under `mo2`, so no additional JSON is needed for npm
metadata later. This does not make npm itself an MO2 deployment engine or claim
that these mod names already exist on the npm registry.

`dependencies` maps names to npm ranges: exact versions, `~`, `^`, comparisons,
wildcards, hyphen ranges, and `||`. For example, `~2.1.0` means `>=2.1.0 <2.2.0`,
while `^2.1.0` means `>=2.1.0 <3.0.0`. Python's `~=2.1` is not npm syntax; use
`>=2.1.0 <3.0.0` for that meaning. Prereleases require a range that admits them.
Git URLs, dist-tags and npm alias dependency specifiers are not version ranges
and are not accepted here; put download locations in `mo2.sources`.

The solver intersects constraints across the graph and backtracks over available
versions, preferring newer compatible versions for a fresh install. Additions prefer compatible installed versions unless an upgrade is selected. Exactly one version of a named
package is selected per profile. Provider identities, exact assets, recipe bytes,
and SHA-256 hashes are still recorded in the generated lock.

## Sources and installation

`mo2.sources` is an ordered list of Nexus, GitHub-release, or local-archive source
objects. Each source records a provider location. These are
locations for a **declared package version**, not dependency identities. An
optional `mo2.integrity` pins `sha256:<digest>`. Mirror failures may try the next
source; integrity failures and authentication/manual choices never silently fall
back. A Nexus mod-page source without `fileId` must identify a unique file with
the package's declared version; independently installable files are not guessed.

`mo2.install` contains declarative `{from, to, class}` mappings. `class` is
`mo2-overlay` or `game-root`. Existing path validation, file-conflict review,
root-file backup, running-game checks, and rollback apply. Without mappings, the
game adapter recognizes standard layouts. `install: []` deliberately deploys no
files. Collections without sources generate no installed game files.

Other MO2 fields: `conflicts` contains package names; `fileOverrides` uses named
package winners/losers; `plugins` records New Vegas plugin order; `extensions`
retains provider/update-check provenance. Standard layouts and explicit mappings
cover ordinary archive mods, framework files, and chosen FOMOD file selections.
Most packages need no executable script.

## Optional executable installation

`scripts.install` is a standard npm command string. MO2 Modlists runs only that
lifecycle; other npm scripts are preserved but not automatically executed.
An install script needs an archive source. It runs in a temporary directory
containing the extracted source and the package definition, with
`MO2_PACKAGE_DIR`, `npm_package_name`, and `npm_package_version` available.
It can generate or transform files there; `mo2.install` maps its resulting files.

Scripts require an explicit UI trust decision or CLI `--allow-scripts`. Trust
requests include the command, package version, source digest, and definition
digest. Scripts run with the user's permissions, **not in a security sandbox**.
The game must be closed. There is a five-minute limit; failure leaves no finalized
installation plan. Filesystem links are rejected in the produced archive.

Preparation happens during resolution, before deployment review. Its resulting
archive is hashed and cached along with original source identity and script
provenance. Installation and offline reinstall deploy that verified result,
without executing the script again. A prepared-output cache is consequently
part of the offline requirements. Script side effects outside its working folder
cannot be rolled back by the file deployment transaction.

## Profiles and commands

`resolve`, `install`, `import`, `add`, `inspect`, `verify`, and `validate` accept
package definitions. Public package URLs support relative package references,
verified snapshots, offline snapshots, and update checks.

`add` starts with the currently enabled profile. It includes installed versions
as candidates and prefers compatible installed versions by default. `--upgrade`
(or the UI's upgrade choice) prefers newer compatible candidates. Required upgrades
are shown as replacements in the review; the solver still honors all version
constraints. Matching installed folders are reused. Manual installs need recorded
source identity and verified files before adoption; a similar folder name is not
proof that two mods are the same package.

Export writes one package definition with dependency metadata inline. Manually
assembled profiles require source resolution to obtain complete metadata. Nexus
and Collection conversion also publish this same format after preparation.
There is no migration command, source-only export, or separate author recipe.

```powershell
python -m mo2_modlists.cli validate package.json
python -m mo2_modlists.cli resolve --manifest package.json --lock package.lock.json --cache cache --game C:/Games/Cyberpunk
python -m mo2_modlists.cli install --manifest package.json --lock package.lock.json --cache cache --game C:/Games/Cyberpunk --mo2 C:/Modding/MO2 --profile MyMod --allow-root
python -m mo2_modlists.cli add --manifest package.json --cache cache --game C:/Games/Cyberpunk --mo2 C:/Modding/MO2 --profile MyMod
```

The implementation generates exact deployment plans and caches their data in
locks. These are internal records, not additional author-maintained formats.
