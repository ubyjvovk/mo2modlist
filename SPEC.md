# Architecture

## Public packages

The only author-maintained input is an npm-shaped `package.json`. Mods,
collections, and installation metadata share this format. See [PACKAGES.md](PACKAGES.md)
for fields and [README.md](README.md) for installation and workflows.

A stable package name identifies a dependency; its version follows SemVer.
Sources are locations for that version, not alternate dependency identities.
`mo2.packages` supplies available definitions. The resolver intersects named
requirements and selects one version per name. A missing definition is an error.

For a fresh profile, newer compatible candidates are preferred. For an addition,
the active profile is captured first and compatible installed versions are
preferred. Explicit upgrades change that preference, not the version constraints.
Authored root requirements are retained. Manually enabled packages are included
once their provenance is established. Recorded source identity and output hashes
allow existing mod folders to be adopted; names alone never justify reuse.

## Preparation

Source adapters obtain exact Nexus files, GitHub release assets, or local
archives. Native provider metadata can contribute required dependencies.
Nexus and Collection conversion resolve provider preparation data before
publishing a package definition. Unknown metadata asks for a package definition.
There is no public source-only manifest or standalone recipe format.

Declarative mappings describe output paths and deployment classes. Optional
`scripts.install` preparation requires explicit trust and runs with the user's
permissions. Its output is hashed and cached. Locked deployment does not rerun
scripts. Preparation is separate from deployment and occurs before its review.

## Generated deployment records

The package compiler produces exact internal plans consumed by the deployment
engine. Internal records include selected sources, hashed archive identities,
installation mappings, dependency edges, file winners, and plugin order. Some
internal field and file names use `manifest` or `recipe`; these records are
machine-generated implementation details, not additional authoring formats.

The finalized lock records the game executable identity, distribution/build/DLC,
archive hashes, and required installation decisions. The public package's digest
binds it to the generated plan. Cached metadata and archived bytes are verified
before use. A supplied integrity pin is checked; an observed hash alone does not
establish independent authenticity.

## Review and deployment

Fresh imports create a new profile. Additions produce a review plan tied to a
snapshot of the existing profile, active files, Overwrite, relevant game files,
and other recorded root-file owners. Any intervening change invalidates review.

Unchanged packages reuse their existing directories. Replacements receive new
directories so other profiles retain their copies. Local edits to replaced files
need reconciliation. Unmanaged conflicts are not silently overwritten.
Disabled entries, settings, and saves are preserved during profile publication.

Overlay files go into MO2 mod directories. Physical game-root writes are shared
between profiles; ownership checks and original-file backups cover this instance.
Unmanaged consumers and other MO2 instances are outside the ownership record.
Journaled publication supports recovery from interruptions. Script side effects
outside preparation directories are outside deployment rollback.

`verify` reports differences without modifying files. Root restoration applies
only a reviewed plan and does not remove mod folders or saves.

## Offline behavior

A finalized lock plus every required cached archive is sufficient for offline
deployment, including prepared script output archives. Offline resolution also
needs complete package metadata and provider snapshots. Caching a public package
URL alone does not guarantee that its dependencies can be resolved offline.

## Game adapters

Cyberpunk adapters recognize standard game-relative layouts, bootstrap root
files, and CET runtime mappings. New Vegas adapters map `Data` into the MO2
virtual Data root, record plugin order independently of asset priority, and check
declared TES4 masters. Neither adapter proves gameplay compatibility.

See [ACCEPTANCE.md](ACCEPTANCE.md) for verification evidence. Automated resolution
and deployment checks, live MO2 behavior, and gameplay testing are distinct.
