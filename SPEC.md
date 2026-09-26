# MO2 Modlists: MVP specification

Status: implementation started, 2026-09-26. This document describes the broader source-resolved design; see PROGRESS.md for the implemented subset and its validation.

Export contract, clarified by the user: export only `modlist.json`, using Manifest v1 below. No snapshot lockfile, content blobs or copied archives are part of export. If a source is unknown, ask the user to select an existing local archive, provide a source URL, or explicitly skip the mod. Cancellation cancels the export. A local archive reference remains a reference, not an embedded payload. Lockfiles and caches are products of the resolution/import pipeline. The earlier installed-snapshot prototype is a legacy experiment, not fulfillment of this source-manifest contract.

## Outcome

An MO2 tool extension accepts `modlist.json`, resolves its dependencies across Nexus Mods, GitHub Releases and local archives, downloads the selected artifacts, and installs a reproducible Cyberpunk 2077 profile. A companion `modlist.lock.json` captures the complete installation plan. Existing profiles and their mod directories must remain unchanged.

The initial product is an extension, not a fork of MO2. Registry hosting, archive storage and resolver implementation remain independent choices. All selected archive contents are extracted before play; archive-backed filesystems are out of scope.

## MVP scope

- Windows x64, Cyberpunk 2077, initially the locally installed MO2 release; broader MO2 compatibility is established through testing rather than assumed.
- Mixed Nexus file references, GitHub release assets and local archive files in the same pack and dependency graph.
- Native source metadata where sufficient; explicit local recipes for missing dependencies or installation details. An optional Git-hosted supplemental registry uses the same recipe format.
- Dependency resolution with actionable explanations, exact locking, verified caching, resumable installation and a new named MO2 profile.
- Straightforward extraction with explicit file mappings, including common CP77 archive, REDmod and framework layouts when validated by the game adapter.
- Manual handoff for source download interactions or installer choices that cannot be automated. Such a plan stays incomplete until required inputs are recorded.
- Headless validation/resolution/inspection interfaces for development; MO2 deployment remains in the extension adapter.

Not in the MVP: building Git source checkouts, general-purpose executable installers, automatic FOMOD replay, arbitrary recipe scripts, inferred dependencies from prose, arbitrary config merge languages, automatic updates to existing profiles, non-CP77 games, or hosting mod binaries on npm/PyPI.

## Architecture

`manifest -> source adapters + recipe metadata -> resolver -> plan -> fetch/verify -> stage -> MO2 deployment`

1. **Python tool plugin:** `mobase.IPluginTool`; user interface, MO2 service access and deployment orchestration. UI calls stay on the owning Qt thread; long work is asynchronous and cancellable.
2. **Core library:** JSON models, graph resolution, metadata normalization, lock generation, cache and installation planning. No `mobase` imports. Prefer Python initially; select an established solver after exercising the required constraints. No custom SAT implementation as an MVP prerequisite.
3. **Source adapters:** enumerate candidates, retrieve dependency metadata, identify/download artifacts and emit actionable authentication or manual-download requests.
4. **CP77 adapter:** checks game/DLC prerequisites, recognizes supported layouts, classifies destinations and handles MO2 deployment limitations.
5. **Supplemental recipes:** declarative metadata supplied locally or from a pinned registry snapshot. Source-native packages do not require registration here.

The core may run in a worker process if dependency isolation or responsiveness requires it. That is an implementation decision, not a requirement to ship a separate runtime immediately.

## Manifest v1

JSON is the first supported syntax. Unknown schema versions fail before any installation; unknown fields fail validation except inside a reserved `extensions` object. Paths inside manifests/recipes use forward slashes. Relative local references resolve against the declaring document, never the process working directory.

Required top-level fields: `schemaVersion` (1), `name` (stable pack name), `game`, `dependencies`.

- `game.id`: `cyberpunk2077`; `game.version`: optional exact build string; `game.dlc`: required DLC identifiers. Game builds are not assumed to follow SemVer. Observed build and distribution are always recorded in the lock.
- `dependencies`: mapping of human-friendly aliases to dependency objects. Aliases are not global package identity.
- Dependency `source`: a tagged object, described below.
- Dependency `recipe`: optional local recipe path. Native metadata is used without it when sufficient.
- Dependency `options`: optional values defined by the selected recipe's option schema.
- `fileOverrides`: optional rules `{winner, loser, paths}` using aliases and explicit game-relative paths. These express overwrite intent, not dependency order.
- `registries`: optional named Git sources with repository URL and revision selector. Resolve the selector to a commit before reading any recipe. The MVP can work without a shared registry.

Source objects:

| Type | Fields | Selection |
| --- | --- | --- |
| `nexus` | `game`, `modId`, optional `fileId` | A file pin is exact; otherwise enumerate eligible files and require an explicit choice when metadata cannot distinguish variants. |
| `github-release` | `repository` (`owner/repo`), `tag` or `channel`, `asset` | Exactly one of an exact tag or `channel: stable`; exact asset filename. Never substitute a source-code archive. |
| `local-archive` | `path` | Read and hash the archive, then import it into the cache. |

Any dependency may additionally supply `integrity` as `sha256:<64 hex characters>`. A provided digest must match. Without one, the first download's digest is recorded as locally observed, not described as independent authenticity verification.

GitHub `channel: stable` excludes drafts/prereleases and uses the provider's stable-release selection; it is not a promise of game compatibility. The lock pins the actual release and asset IDs, tag and digest. SemVer ranges are deferred for arbitrary GitHub tags until an explicit version scheme is supplied.

## Package identity and versions

Nexus mod pages can contain independently installable main files, addons and patches. A Nexus mod ID is therefore not automatically a singleton package. Normalize candidates to a logical component/file lineage when the provider exposes it, or require a recipe to identify the component. The same applies to multiple independent GitHub release assets.

Each logical component has one selected version per profile; mutually exclusive variants conflict. Explicitly separate addons can coexist. References from different sources are equivalent only with an explicit identity mapping, never because their display names match. Provider IDs remain attached to every candidate for provenance and diagnostics.

Preserve upstream version labels. Apply ranges only with an identified comparison scheme; exact file/asset pins work without SemVer. Keep recipe revision separate from mod version.

## Metadata and recipes

Prefer Nexus file-level requirements over ambiguous page-level requirements when available. Normalize required dependencies, alternatives and version constraints into the graph. Recommendations are shown separately and are not silently required. Missing metadata is `unknown`, not an assertion that the mod has no dependencies.

GitHub releases do not inherently provide a mod dependency graph. Use an explicitly referenced machine-readable recipe or supplemental entry; never treat release notes as executable requirements. Git source manifests do not automatically apply to a binary release asset.

A recipe describes: schema version; logical package/component identity; upstream version and immutable recipe revision; applicable source artifact identities or hashes; dependency rules; game/DLC constraints; mutually exclusive variants; supported options; and declarative file mappings.

Supported mappings select an archive subtree/file and place it at a relative destination with a destination class (`mo2-overlay` or `game-root`). Simple layouts can use a deterministic, versioned game-adapter rule. Unsupported or ambiguous layouts require an explicit mapping. Archive format support follows the verified extraction backend; ZIP and 7z are initial compatibility targets.

Metadata precedence is explicit: source facts are preserved; applicable supplemental corrections are shown and recorded; pack choices constrain the result. Corrections must identify the exact source/component/version scope, reason and provenance. They do not silently erase conflicts.

The optional registry is files plus an index, e.g. `packages/<game>/<package>/<version>/<recipe-revision>.json`. Publishing is a commit/PR, not a GitHub Release per package. A client can use a checkout or a downloaded snapshot. Resolve against one commit; cache selected recipe bytes and hashes. Published revisions are immutable by project policy; clients verify hashes rather than trusting branch history to enforce it.

## Resolution contract

1. Validate the manifest and target environment; normalize identities and snapshot metadata.
2. Expand required dependencies recursively from all source types, retaining the full reason chain.
3. Intersect constraints for each component, model alternatives and selected options, and reject incompatibilities. Detect cycles; a satisfiable dependency cycle need not fail, but ordering cycles do.
4. Require explicit choices for ambiguous variants, unknown installation layout or missing essential dependency information. Never guess that a popular mod's metadata is complete.
5. Produce deterministic selections from the same inputs/snapshot using documented candidate ordering and stable ID tie-breakers.
6. Present the selected files, dependencies, required downloads, recipe corrections and outstanding choices. After staging, inspect actual file collisions before deployment.

Dependency relationships, MO2 overwrite priority and game resource/load order are separate. Do not derive one from another. New collisions need a recorded winner or resolution; an ordering cycle or incompatible per-file winner rules blocks deployment. Identical bytes can share a path without a content conflict. CP77 resource conflicts inside differently named `.archive` files may not be detected by path collision checks; the product must not claim complete runtime compatibility.

## Lockfile and reproducibility

The lock contains: schema version; canonical semantic manifest digest; target game/build/distribution/DLC; all selected component identities; exact source file/release/asset identities; archive sizes and SHA-256 hashes; complete dependency edges and selected alternatives; metadata snapshots and provenance; registry commits and recipe hashes/bytes; options; resolved file mappings; installer/game-adapter versions; file ownership and output digests; effective MO2 ordering; explicit external prerequisites.

Plan generation can produce a draft before downloading. A lock is finalized only once required archives, hashes, choices and installation outputs have been determined. Write it atomically; keep installation success/failure in a separate journal.

Installing a valid lock does not refresh constraints or choose newer artifacts. Manifest mismatch requires an explicit re-resolve. Missing exact artifacts can be supplied through the cache or a matching manual file; otherwise fail without substitution. Credentials and expiring download URLs are excluded. Stable source identity is recorded so a fresh download URL can be obtained.

Reproducibility means the managed initial files, selections and ordering match. It does not promise identical game runtime behaviour, cloud saves, GPU drivers or subsequent user edits. Full offline installation requires all locked artifacts, recipes and supported installer components in cache. Local paths are hints; content identity is authoritative.

## Downloads, extraction and deployment

- Reuse MO2's supported Nexus authentication/download services where exposed. Inspect installed bindings before choosing an integration. If direct API access is needed, keep credentials in local secure storage and follow source-supported user flows.
- For GitHub, retrieve release assets, support optional local authentication and handle rate limits. Resume only when validators establish the remote object is unchanged; otherwise restart. Deduplicate artifacts by digest across sources.
- Always verify supplied/locked hashes before using an archive. Treat cached artifacts as immutable. Keep temporary downloads separate from verified cache entries.
- Reject archive paths escaping staging, absolute paths, unsafe links/reparse points and ambiguous Windows path aliases. Validate expanded paths and space requirements before publishing files.
- Stage and inspect before enabling mods. New installation directories are identified by artifact, recipe, options and output identity; do not overwrite an existing shared MO2 directory.
- Use separate writable installed copies where runtime edits are possible. Do not hardlink writable configs or mod files into an immutable shared cache.
- Create a fresh profile and preserve existing profile contents and activation. Enable the pack only after all required steps succeed. Block deployment while the game is running; downloads/planning can proceed.
- Journal created objects and completed steps. Cancellation/failure leaves a resumable operation and does not activate a partial pack. Recovery removes only objects created by that operation; verified downloads may remain cached.
- Root-level bootstrap DLLs/frameworks require explicit handling. Verify whether the installed MO2/CP77 adapter or a compatible root-deployment extension can supply them reliably. If physical game-root writes are required, disclose their cross-profile effect, retain originals and track ownership/restoration. Never call those changes profile-isolated. Unsupported root deployment blocks that part of the plan rather than claiming success.

## User flow

Tools -> Install modlist -> select manifest or lock -> validate game/profile -> resolve or inspect lock -> resolve outstanding choices -> fetch/stage -> review final plan and collisions -> Install -> completion report.

The final action covers the concrete plan. Additional prompts occur only for newly discovered required choices or source interactions. Progress identifies the active component, phase and actionable errors. On success show created profile, installed components and any external prerequisites; game launch is a separate user action.

## Development setup and first feasibility checkpoint

Recommended: VS Code (or another editor), Git, Python matching MO2's embedded runtime, an isolated development environment managed with uv or venv, compatible `mobase` stubs and Qt bindings, pytest and a formatter/linter. Pin development dependencies after verifying target compatibility.

Local inspection on 2026-09-26 found `E:/Modding/Cyberpunk2077/plugins/plugin_python/dlls/python312.dll`: target Python 3.12 for this installed build. Determine its actual Qt binding/version from the installed plugin before selecting dependencies; older public documentation refers to PyQt5 and must not override installed-build evidence. `mobase` runs inside MO2; stubs only support editing/type checking, not standalone execution.

The executable reports MO2 2.5.2. Git and VS Code are already on PATH; `uv` was not found there. The default `python` command resolves to `C:/Python27/python.exe`, so development commands must explicitly select Python 3.12 rather than use bare `python`. This is a PATH check, not an exhaustive inventory of installed Python versions.

Use a separate portable MO2 test instance and disposable profiles. Never deploy development plugins into the user's stable instance by default. Python module plugins live under `plugins/<plugin-folder>/` with an entry point; package their runtime dependencies without pip-installing into MO2's embedded environment.

Visual Studio is not required for the Python-first extension. Native changes need the target release's C++/Qt toolchain. Current upstream `mob` instructions list Visual Studio 2022, Desktop C++, Windows SDK, CMake, Qt and vcpkg, with additional .NET/C++ CLI components for installer builds. Pin the MO2 release and follow that revision's build instructions; do not build current master and assume compatibility with the installed release.

Before implementation promises, prove on the test instance:

1. Load an `IPluginTool`, display a dialog and observe cancel/progress without blocking MO2.
2. Read game/profile context and inspect exposed download/install/profile APIs.
3. Download or import an archive, install it under a distinct identity, set priority and enable it in a new profile through supported integration points. If profile creation is not exposed, use a documented handoff or verified adapter rather than guessed API calls.
4. Verify CP77 root/framework behaviour with a representative dependency; establish whether an additional root adapter is necessary.
5. Reinstall a locked tiny pack without fetching dependency metadata and show that the original profile remains unchanged.

## Delivery stages and acceptance

Stage 1: integration feasibility checkpoint, schema and mixed-source fixture pack.

Stage 2: independent resolver/provider core, lock and cache; fixture-based tests for transitive dependencies, alternatives, conflicts, missing metadata, distinct components on one Nexus page, source aliases, changed assets and hash mismatches.

Stage 3: staged extraction and MO2 deployment; tests for traversal/path aliases, file conflicts, interrupted operations and existing-profile preservation.

Stage 4: end-to-end CP77 pack using at least one Nexus mod, one GitHub-only framework and a local mod archive, including a transitive dependency. Complete root handling for the chosen frameworks, reproduce it from the lock in a fresh profile and perform a game smoke check.

Acceptance additionally requires: a conflicting pack explains its dependency chain without altering profiles; an interrupted download/install resumes safely; an unavailable locked asset produces a clear error; cached locked installation works offline; unsupported installer choices cannot be marked complete; and changing a variant creates a separate installed output.

## Sources checked

- MO2 Python setup: https://www.modorganizer.org/python-plugins-doc/setup-tools.html
- MO2 Python module/tool plugins: https://www.modorganizer.org/python-plugins-doc/writing-plugins.html
- MO2 bindings: https://github.com/ModOrganizer2/modorganizer-plugin_python
- Native build instructions: https://github.com/ModOrganizer2/mob
- Nexus file-level requirements announcement: https://www.nexusmods.com/news/15591
- Nexus API: https://api-docs.nexusmods.com/
- CKAN metadata reference: https://github.com/KSP-CKAN/CKAN/blob/master/Spec.md

External API capabilities described here must be verified against the authenticated integration during the feasibility checkpoint. No source accounts, tools or SDKs have been installed or changed as part of writing this document.
