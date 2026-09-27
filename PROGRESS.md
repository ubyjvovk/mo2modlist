# Progress: 2026-09-26

## 0.6.3 — autonomous gameplay acceptance, 2026-09-27

- Used the explicitly authorized local foreground-only capture/input helpers to playtest both disposable installations. The previous computer-use availability blocker no longer applies. Helpers and screenshots remain private under ignored artifacts.
- The machine's Saved Games known-folder location still pointed to the failed `F:/Saved Games`. Repaired it through `SHSetKnownFolderPath` to `C:/Users/d/Saved Games` and copied the preserved test `AutoSave-0` and `user.gls` there without overwriting an existing save. The original setting and backup location are recorded in `artifacts/mixed-itp-test/saved-games-repair.json`. This is an environment repair, not a shipped plugin operation.
- Found a real second-launch problem: once CET had created per-mod runtime folders in Overwrite, physical Lua files were absent from USVFS relative lookup. CET reported `cannot open init.lua`, despite earlier successful startup. Added an `IPluginFileMapper` interface to the extension that exposes locked physical CET mod data explicitly and preserves existing virtual overrides. Native libraries are excluded: an initial broader mapping experiment crashed; the focused implementation passed subsequent launches and gameplay. The previous startup-only loading claim must not be read as evidence of successful later reloads.
- `ITP - Mixed Offline`: opened the Immersive Third Person settings through the Mods menu, loaded the restored Dog Eat Dog save, moved forward and crouched with visible world/HUD/camera changes. Final implementation evidence: `artifacts/mixed-itp-test/fixed-{mods,world,moved-crouched}.png`. The observer's `Game.GetPlayer()` marker can fire before a save loads and is not treated as gameplay proof.
- `CET Essentials - Collection`: opened Mod Settings, observed Browser Extension and Virtual Atelier, loaded the same save, and verified forward movement and crouching. Evidence: `artifacts/live-collection-20260927/playtest-{modsettings,world,moved}.png`. Both final game sessions were closed normally; no new crash report followed the focused fix. These are smoke checks, not exhaustive testing of every mod feature.
- Re-exported the mixed-source profile to one JSON with 12 dependencies and no skipped sources. Re-resolution produced the same component/output hashes (`reexport-verification.json`). Re-resolution used provider access; offline installation of an existing finalized lock was already demonstrated with network connections blocked. Offline resolution of a new GitHub manifest is not claimed.
- All 78 automated tests pass. Stable MO2/game directories were not changed; stable Play's modlist hash still matches `27d1909d8348a8c7e76004d77ef15a64fced0968a7ae27a84aa134516fe63e56`. Version 0.6.3 is deployed to both disposable instances only.

## Mixed-source reproduction — 2026-09-27

- Installed `artifacts/mixed-itp-test/modlist.json` into `ITP - Mixed Sources` and reproduced the same lock into `ITP - Mixed Offline`. Both contain the 12 resolved components across Nexus, GitHub release and local archive sources. The offline reproduction replaced socket connection functions with failures; no network attempt occurred. Both profiles verified 99 managed files with zero differences before launch. All original ITP root hashes were preserved; the passive acceptance observer adds one Lua file.
- The initial install correctly refused conflicting runtime `overwrite/bin/x64/CD Projekt Red/Cyberpunk 2077/user.gls`. With both game and MO2 closed, preserved the complete 20-file overwrite folder as `test-install/MO2/overwrite-before-mixed-itp`, then retried with an empty overwrite. No runtime files were deleted.
- Deployed current 0.6.2 plugin to the stopped test MO2 and launched `ITP - Mixed Offline`. Current logs confirm redscript compilation and loading of ITP, Native Settings and the local acceptance observer. Loaded-world/input behavior is not yet verified for this profile.
- User requested autonomous computer-use playtesting. Re-read the installed computer-use skill and searched the current tool inventory: neither `node_repl` nor desktop/browser control tools are exposed. The skill requires `@oai/sky` through that runtime and prohibits a custom helper protocol client. No additional user playtest was requested; hands-on Collection/mixed-source acceptance awaits that capability. Startup logs are not substituted for gameplay evidence.
- Stable Play modlist hash still matches the recorded September 27 baseline. Artifacts: `artifacts/mixed-itp-test/{install-result.json,offline-install-result.json,verify-first.json,verify-offline.json,compatibility.json}`.

## Real Collection installation — 2026-09-27

- After Cyberpunk closed, installed the resolved CET+Essentials revision 49 into the separate `test-collection/MO2` profile `CET Essentials - Collection`, targeting `C:/Users/d/Documents/MO2-Modlists-Collection-Game`. Installation used the verified cache with `--offline`; all 11 original pins were retained, with 72 physical root files.
- Verification passed for 138 managed files, component identities and enabled ordering, with zero differences. Launched via MO2: ArchiveXL, Codeware 1.20.3, Mod Settings 0.2.21 and TweakXL 1.11.3 loaded; redscript compilation completed successfully. Loaded-save/UI confirmation is pending with the user. Evidence: `artifacts/live-collection-20260927/{install-result.json,verify-install.json}` and the separate test game's logs.
- Prepared a current mixed-source ITP manifest/lock under `artifacts/mixed-itp-test`: 12 components using Nexus, GitHub releases and a local passive acceptance-observer archive, including transitive dependencies. Its root plan preserves all 76 ITP root file hashes and adds only the passive observer Lua file. This permits the remaining mixed-source test on the original disposable target without changing its working framework versions. Installation/reproduction/gameplay are pending the Collection game closing.
- Stable Play modlist hash remains `27d1909d8348a8c7e76004d77ef15a64fced0968a7ae27a84aa134516fe63e56`.

## Follow-up acceptance preparation — 2026-09-27

- Re-resolved the real mixed-source acceptance manifest with current code and authenticated native metadata. `artifacts/mixed-source-smoke1/current-source.lock.json` contains six components, five dependency edges, and GitHub release, Nexus and local-archive sources. This is a planning result; current-version mixed-source reinstall/gameplay remains pending.
- Fixed MO2 account-status caching: Premium status is now cached only within one acquisition operation. A new import refreshes it, so an account upgrade does not require restarting MO2 or re-entering the key. No credentials are exported.
- Corrected recipe documentation that incorrectly listed unsupported `extensions` among recipe fields. Manifest extensions remain supported.
- Cyberpunk PID 4376 was still running when checked; deployment remains blocked as required by SPEC.md. The existing close-game request is pending; no repeated prompt or forced shutdown was issued.

## 0.6.2 — historical Collection pins and ITP gameplay confirmation

- User confirmed the third-person mod works in the launched ITP test. This completes its loaded-game mod-function check, following the verified install, offline reproduction and profile export/re-import.
- Fixed unversioned legacy page requirements excluding explicitly pinned historical files. Solver roots seed exact pins; the adapter verifies each file belongs to its requested mod page before adding an `old_version` candidate. Unpinned selection still uses active versions. File-level native ranges are not expanded. Explicit legacy pins are retained in metadata for lock validation. Tests cover old-pin eligibility, page ownership and isolation from native ranges.
- Real CET+Essentials revision 49 now resolves to a complete 11-component lock with every original source/file pin preserved. Three reviewed recipe decisions from the previous turn remain explicit. Evidence: `artifacts/live-collection-20260927/reviewed-modlist.lock.json`. All 77 tests pass.
- Prepared a separate `test-collection/MO2` and `C:/Users/d/Documents/MO2-Modlists-Collection-Game` from the disposable game using the GOG installed-file inventory. Copy completed successfully; the new game's identity matches the resolved lock, and plugin 0.6.2 is deployed to this new instance. This isolates the Collection's older framework binaries from the working ITP profiles. Installation/gameplay remain pending while the user finishes the running ITP game; a close-game request is outstanding.

## Collection review pipeline fixes — 2026-09-27

- Conditional and external legacy requirements now produce incomplete metadata with explicit unresolved entries, allowing the existing recipe-selection workflow to run. Previously the adapter raised before a recipe could be supplied. Known mandatory native requirements and DLC remain enforced by the solver, planning and lock validation, even with incomplete metadata and a reviewed local recipe. Regression coverage checks the prompt, successful review and rejection of missing known edges.
- Explicit root recipes are registered before recursive traversal, so references to a later root reuse its selected recipe instead of prompting again. This was encountered with Virtual Atelier referencing Browser Extension, both included in the real Collection.
- The installed executable's actual Windows resources expose string ProductVersion `2.31` and fixed numeric ProductVersion `2.3.1.0`. Both exact observed values now satisfy game-version constraints; there is no string-normalization guess. New locks retain the fixed value alongside the string, and installation/verification recheck it. Regression coverage rejects an unobserved `2.3.2.0`.
- Reviewed the Collection's three conditional requirements by including the exact optional dependencies already selected by the Collection (Virtual Atelier -> Browser Extension, Browser Extension -> Mod Settings, No Intro redscript variant -> redscript). Separate review decisions and archive-bound recipes are under `artifacts/live-collection-20260927`; original generated manifest remains intact.
- Retrying the real Collection now reaches a solver conflict between Virtual Atelier's legacy ArchiveXL candidates and the Collection's explicitly pinned older ArchiveXL. Current legacy enumeration uses active versions only. No pins were silently updated, no Collection lock finalized and no profiles changed in this turn. Next: support explicitly pinned eligible historical versions for unversioned legacy requirements while preserving genuine native version ranges. All 75 tests pass.

## 0.6.1 — Premium downloads and real ITP import acceptance

- User enabled Nexus Premium; the configured key now reports `is_premium: true`. Added the supported exact-file Premium API downloader to CLI resolution/import, retaining the website/archive handoff for non-Premium users. Signed URLs are not saved as source metadata, and API credentials are not forwarded to CDN transfers. Live Native Settings URLs contained spaces; path encoding now preserves existing escapes and signed query bytes.
- Downloaded the two missing exact Nexus archives; both matched their published SHA-256. The original seven-entry ITP manifest resolved to eight components, discovering RED4ext transitively. Full lock: `artifacts/itp-nexus-test/modlist.lock.json`.
- Installed `ITP - Nexus Test` into the disposable MO2 with eight readable mod names. Installed the same lock into `ITP - Offline Test` with `--offline` and socket connection functions replaced with failures: no network attempt occurred. Exported the first profile to one manifest, resolved it and imported `ITP - Reexport Test`. All three installations verified 94 managed files with zero differences before launch. Physical framework deployment comprises 76 root files.
- Launched `ITP - Nexus Test` through MO2's documented `run -e` interface. RED4ext loaded six plugins, including the ITP HeadGuard/LootRange/Move360 components; redscript compilation succeeded; CET reports `immersive_third_person` and `nativeSettings` loaded. Loaded-save/input/mod-behavior confirmation remains pending with the user. Logs alone do not prove gameplay acceptance.
- Stable Play modlist SHA-256 still matches `27d1909d8348a8c7e76004d77ef15a64fced0968a7ae27a84aa134516fe63e56`. The stable installation was not modified. All 74 unittest tests pass. The running test MO2 is left available for gameplay checking; plugin package deployment can follow after it exits.

## Real Collection validation — 2026-09-27

- Downloaded the full authenticated Nexus package for CET+Essentials (`n0nymh`, revision 49, revision ID 698560). Package SHA-256: `7674ebd75105a6750e5d5ac09aad86765deea2f0998558c657c0e4ef2b672186`. Conversion now produces a manifest with all 11 exact recorded Nexus file IDs.
- Recognized the upstream `collectionConfig.recommendNewProfile` boolean as advisory metadata, preserving it in manifest extensions. Imports still use new profiles. Unknown configuration keys and non-boolean values remain pending review. Upstream type checked in `extension-collections/src/types/ICollectionConfig.ts`; both boolean values and malformed configurations have regression coverage. All 72 tests pass.
- Real installation remains unproven: the Collection declares `2.3.1.0`, while the test game's product version is `2.31`. Resolution correctly stops before installation; no unverified version equivalence was introduced. An independent dependency-only probe also stops at Virtual Atelier's legacy Browser Extension requirement marked `Optional`, requiring explicit metadata review. It does not constitute a complete lock or installation.
- Evidence: `artifacts/live-collection-20260927/{collection.json,modlist.json,converted-result.json,dependency-resolution.json}`. No test or stable profiles were modified by these probes.

## 0.6.0 — 2026-09-27: Nexus URL conversion, live requirements, readable names

- Added CLI `from-url` and MO2 **Create manifest from Nexus URL…**. Mod conversion pins the root and direct requirements, retaining DLC constraints; Collections reuse full-package conversion/review. Unknown metadata blocks finalization. The user clarified that direct requirements must be explicit and pinned, while transitive expansion belongs to resolution.
- Live authenticated API inspection found `mod.modRequirements` and `legacyModRequirementsEnabled` in GraphQL. Implemented legacy-page normalization alongside v3 file metadata, preserving provenance and notes. The older SDK's top-level `modRequirements` query no longer exists on the live endpoint. Empty file requirements are no longer assumed unknown when the mode flag proves file-level metadata applies.
- Created `artifacts/itp-nexus-test/modlist.json` from live metadata: Immersive Third Person 32203/161480 plus six exact direct requirements. A separate live resolver run found RED4ext transitively, producing eight components. No hand-written flattened dependency list was used. Real MO2 URL-dialog test produced another seven-entry manifest with unchanged profiles (`host-result.json`).
- Fixed actual installed MO2 2.5.2 download integration: its Python binding has `startDownloadNexusFile(modId, fileId)`, not `startDownloadNexusFileForGame`. The corrected call reached Nexus, which rejected unattended download for the non-Premium account. The configured API key works for metadata and also reports non-Premium. The UI now hands that account to the exact-file website/archive flow rather than waiting on a download callback that may never arrive for this rejection.
- Nexus-published scan SHA-256 values matched six existing framework archives exactly. The cache can reuse those bytes while retaining Nexus identity. Immersive Third Person and Native Settings UI are still missing; no lock or completed profile was published for this incomplete install. This is live metadata acceptance, not successful archive transfer or gameplay acceptance.
- New mods use normal provider/Collection/manifest names. Existing names are disambiguated with the profile name and numeric suffix where needed; ownership remains in the journal. Unicode, reserved names, duplicate copies, exact-hash cache reuse and offline locked installs have regression coverage. All 70 tests pass.
- User authorized cleaning the disposable instance. Moved its old mods, all profiles, Overwrite, ownership/cache directory and non-stock game files into `test-install/cleanup-20260927`, with `inventory.json`. Recreated only empty Default. The test MO2 login/configuration was retained. Stable MO2/game were not modified. User reports Probe - Reimport ran successfully before cleanup; that remains historical snapshot evidence.
- Browser/desktop control tools are absent in the current session. API and filesystem tools remain available, but cannot perform the authenticated website clicks. User was told the exact limitation; no browser credential extraction or HTTP restriction bypass was attempted.
- Stable Play now hashes to `27d1909d8348a8c7e76004d77ef15a64fced0968a7ae27a84aa134516fe63e56`, differing from the September 26 record. Its last-write time is September 27 11:21:21, before this cleanup/development work; the old hash is not a current preservation baseline. No action in this work wrote to the stable instance.

Remaining: obtain the two missing exact archives through Nexus's supported flow, finish the clean-profile installation, verify it and cache-only reproduction, then real gameplay and representative Collection acceptance. Prior game-agreement/key blockers have been superseded by this new test and the configured credential.

## 0.5.3 native requirements retained during locked installation

- Audited the spec against the source importer. Fixed lock validation for native Nexus requirements used alongside an explicit installation recipe: missing or redirected required edges, mismatched source snapshots, and unsatisfied native DLC constraints now fail before deployment. Validation uses the locked metadata and selected candidates without refreshing the provider.
- All 62 unittest tests pass, including added negative subcases in the native-provider integration test. Pytest is not installed in the development environment; the suite uses unittest.
- Corrected the stale core version string and packaged 0.5.3. The running test instance has not been hot-reloaded or changed while its game is open.
- Added ACCEPTANCE.md to distinguish implemented behavior, fixture/host evidence, and remaining live gates. The game remains at its agreement screen; no agreement was accepted on the user's behalf. Optional Nexus credentials remain unconfigured. Stable Play and the stable game remain untouched.


## 0.5.2 real mixed-source installation and manual Nexus handoff

- Previous turn was progress (`c0b8aa0`). Added the missing direct manual Nexus archive handoff when the manager cannot start/complete a download or the core has no online downloader. It presents the exact source, retains Nexus identity and enforces provided/locked hashes. Regression coverage verifies manual input, locally-observed status and rejection of a changed locked archive.
- Imported-profile re-export now retains an existing unchanged recipe reference, checked against the recorded digest. Recipe locations are advisory local references, not embedded blobs; changed/missing metadata still needs replacement during resolution. A regression test proves profile -> one exported JSON -> recipe-backed fresh profile with a custom mapping and no metadata prompt.
- 62 tests pass. The new UI fallback still needs a dedicated host-flow check; the earlier MO2 source/Collection tests remain valid for their covered paths.
- Created `tools/prepare_mixed_source_smoke.py` and generated `artifacts/mixed-source-smoke1`: local observer mod -> CET and redscript GitHub artifacts + Nexus Codeware -> GitHub RED4ext. Five components, four transitive edges, three source types. Recipes were reviewed against the authors' official READMEs.
- Nexus Codeware 1.20.5 was identified as mod 7780/file 161780 in the signed-in browser. Its published VirusTotal link contains SHA-256 `102989e199bad650fe6e53395c22bac53fdd7abecc6eeec3b0046886631591f0`, exactly matching the existing official GitHub archive. That verified archive was supplied through the manual callback; no Nexus credentials or expiring URLs were exported. A new browser download was blocked by Brave; the block was not bypassed. No further Codeware download is needed for this pack.
- Resolved real GitHub release/asset identities and downloaded their exact archives. Installed the finalized lock into disposable profile `Mixed Source First`; `verification.json` reports all 37 managed files correct, zero differences. Physical root deployment includes 33 files; remaining files use MO2 overlay.
- Launched through MO2's documented `run -e` CLI. RED4ext initialized, Codeware 1.20.5 loaded and script compilation succeeded. CET reached its first-run hotkey dialog; configured only the previously used overlay key in the disposable runtime settings and relaunched. The game then reached CD Projekt RED's user-agreement screen. Requested the user's decision rather than accepting the agreement automatically. Game PID 23924 was live when recorded; recheck before any control.
- Screenshots and runtime status are under `artifacts/mixed-source-smoke1`. Gameplay and a second locked-profile game launch are **not yet verified**. This real five-component pack advances the acceptance test but does not prove arbitrary Collections or all Play mods compatible. Live authenticated metadata/Collection requests still need the requested credential/package.

## 0.5.1 reviewed game-root restoration

- The previous goal turn made progress in commit `3ee9b3f`. This continuation added the missing post-install root-restoration workflow in MO2 and CLI. New journals record their exact game target and profile. Older journals without those fields require manual recovery rather than guessing ownership.
- Restoration previews the affected files, verifies original backups and current owned bytes, checks the operation identity, and binds execution to the reviewed state. It restores originals or removes added files, preserving mod/profile folders. Another imported profile's lock blocks restoration of shared root paths, including identical bytes that it adopted without writing. Other MO2 instances/unmanaged consumers are explicitly outside this ownership check.
- Interrupted restoration resumes after a fresh review; later user edits and changed backups block it. A restored operation cannot be silently reused as an installation retry. Installing the lock into a new profile deploys it again.
- 60 tests pass. `artifacts/source-ui-probe-restore1/probe-result.json` records a real MO2 Collection fixture install, one reviewed root-file restoration, and a cached second-profile reinstall. Repeated as `source-ui-probe-restore2` after adding profile/status labels to the operation picker; it also passed. Original selected profile and mod folders were preserved.
- Inspected the installed CP77 support plugin: its dummy CrashReporter mod is created only when `version.dll` comes from a mod origin, excluding physical `data` origin. The new importer's physical bootstrap path therefore does not inherently require changing that setting; real CET runtime verification is still pending.
- Prepared the disposable game for source-only smoke testing: moved 315 non-baseline files (708 MB including previous frameworks, DLSS and copied save data) into `test-install/game-root-before-source-smoke`, preserving a full move inventory. The two remaining non-listed root icons are harmless installer assets. The GOG file list gives paths, not authoritative per-file hashes: this is cleanup of the disposable copy, not proof of a pristine vendor-verified game. Earlier fixture profiles are retained as historical evidence and may no longer run after this deliberate test reset.
- Stable Play's modlist still hashes to `22711d90ca05692f6ef0b8b197ea75982e36ed499cf341a95aa266df44ee44d9`; no stable-game files were changed. Requested a securely configured Nexus key or a full downloaded Collection package for the live provider acceptance step; never requested a key in chat.

Remaining acceptance: authenticated Nexus/representative Collection, real mixed-source source-import and locked profile gameplay, and final spec audit. Goal remains active.

## 0.5.0 native candidate resolution

- Added resolvelib 1.2.1 as an unmodified vendored dependency with its ISC license. The wheel SHA-256 was checked against PyPI metadata: `fb06b66c8da04172d9e72a21d7d06186d8919e32ae5ab5cdf5b9d920be805ac2`. MO2 needs no runtime pip installation.
- Native Nexus ranges use provider-materialized finite candidates and file lineages. The solver intersects shared constraints, respects exact pack/recipe pins, backtracks through transitive incompatibilities and alternatives, permits satisfiable cycles, and explains unsatisfiable chains. Missing DLC and empty candidate domains can fall back to another eligible version; unknown metadata still requires an explicit recipe.
- Supplemental recipes are collected before archive acquisition, including Nexus pins reached through GitHub/local dependencies. Selected candidates and the solver identity are retained in the lock. Top-level ambiguous page references and finite recipe options remain explicit choices; arbitrary tag SemVer inference is not added.
- 57 tests pass, including shared constraints, transitive backtracking, component alternatives, cycles, unavailable DLC, empty domains and a full planning/install test with a shared exact pin and no candidate prompt.
- `artifacts/source-ui-probe-solver1/probe-result.json` records success with `solverEngine: resolvelib-1.2.1` inside MO2, plus Collection fixture import and a second profile installed from cache/lock. This remains fixture evidence, not live authenticated Nexus or gameplay acceptance.

Remaining: live authenticated Nexus metadata/downloads and a representative Collection, remaining root ownership/restoration and fresh-instance prerequisite checks, and a real mixed-source playable-profile reproduction. The goal remains active.

## 0.4.1 locked-install verification

The previous goal turn was progress: commits through `c66ce7c` added the source importer and Collection workflows. This continuation inspected the current worktree and tightened the still-open verification requirements without changing the objective.

- Locked aliases must cover manifest roots; graph edges must be valid, unique and reachable. Duplicate component assignments, missing required recipe edges, redirected dependency sources and mismatching options/version identities are rejected.
- Locked priority is reconstructed from the manifest's file winners, recorded choices and Collection rules. Reversing a recorded winner or dropping a required conflict choice blocks deployment.
- Before extraction/deployment, archive inventory and recipe-selected mappings are compared with the lock's member/path/class/size records. A tampered lock cannot add a physical root mapping absent from its recipe merely by copying a valid file digest.
- Added read-only CLI `inspect` and `verify`. Verification checks the stored profile lock, game identity, component provenance, enabled ordering, effective root outputs, overlay file bytes and extra files inside installed mod directories. It explicitly excludes unmanaged game-root files and runtime compatibility, and performs no repairs.
- 51 tests pass. New negative cases prove omitted/redirected dependencies, unapproved root mappings and reversed file winners fail; verifier tests detect runtime edits and extra mod files without changing them.
- Read-only verification of `source-ui-probe-collection1 Cached` against its actual lock reported valid, one managed file checked and zero differences. This is fixture verification, not the pending mixed-source gameplay acceptance.
- Repeated the real MO2 Collection integration with the stricter validator (`source-ui-probe-collection2`): both fresh-profile installs succeeded, with explicit instructions acknowledged per target, cached second installation and the original selected profile preserved.

Remaining objective is unchanged: complete compatible candidate resolution and remaining integration/ownership checks, validate live Nexus workflows and a representative Collection, and reproduce a real mixed-source playable CP77 profile. The goal remains active.

## Current implementation: 0.4.0 source importer (goal remains active)

Collection handoff follow-up to `1adf413`:

- Implemented exact embedded ZIP/7z archive extraction, content/provenance hashes, explicit local/provider source replacement, prepared-archive+recipe handoffs for installer choices/patches/custom types, and reopening saved review drafts. Manual handoffs bind to the exact Collection metadata and preserve the user's note; they do not claim automatic installer or binary patch replay.
- Collection-level instructions now become locked external prerequisites and require fresh acknowledgement per target, recorded in the journal. CLI `--acknowledge` supplies an explicit completed-prerequisite ID. Unacknowledged installs fail before changing the target.
- Real MO2 `source-ui-probe-collection1` passed: import a full Collection package with an embedded source, omit an optional entry, select a missing recipe on the UI thread, acknowledge instructions, review/deploy a new profile, then create a second profile from cache/lock with a fresh acknowledgement. The installed bytes matched and the previously selected profile remained unchanged.
- Strengthened restart-validator ordering, GitHub download cache identity (new asset IDs cannot reuse old temporary downloads), existing staging/profile reparse-path checks, and 7z link/directory validation. Added tests for changed GitHub IDs and restarted downloads.
- 47 tests pass at this checkpoint. Source and Collection host probes remain fixture evidence; a representative live authenticated Collection and the new mixed-source game smoke check are still outstanding. Automatic compatible-candidate backtracking and broader ownership/lock validation remain on the acceptance tracker.

Follow-up to commit `4990eae`:

- Added optional Nexus/GitHub credential controls backed by Windows Credential Manager. An isolated random test credential was written/read/deleted successfully; no real account key was requested or copied from MO2. Individual Nexus mod downloads continue through MO2's service. The optional Nexus key is used for Collection and metadata requests; GitHub token headers are used for release metadata.
- Added an isolated adapter for the current experimental Nexus v3 endpoints, based on the official Vortex OpenAPI schema. It enumerates page file lineages and versions, verifies a file belongs to the requested mod, retains raw/materialized requirements, detects changed definition IDs and converts selected candidate versions into pinned Nexus dependencies. Empty new-style requirements remain unknown rather than concealing legacy page requirements. Multiple eligible candidates require a choice; automatic compatible-candidate solving is still pending.
- Native metadata can generate an artifact-bound recipe and expand transitive dependencies; an integration fixture tests native metadata -> recipe-backed Nexus dependency -> installed profile. Native required edges are retained alongside explicit local installation recipes. First-observed artifact hashes retain their locally-observed status. Native DLC IDs 1/2 were checked live against the public CP77 DLC endpoint and map to Phantom Liberty/REDmod.
- 42 tests now pass, including Credential Manager round-trip, native source normalization, file selection, empty legacy-unknown metadata, changed range snapshots, DLC mapping and transitive native installation.
- `source-ui-probe-v5` passed after these changes: source installation, Qt-thread input, preserved original profile and cache-only second profile. Source Play's hash remains the recorded `22711d90ca05692f6ef0b8b197ea75982e36ed499cf341a95aa266df44ee44d9`. No live authenticated native metadata/Collection transfer or new source-manifest gameplay acceptance is claimed.

Implemented after the user requested the spec importer and Nexus lists:

- Source acquisition for exact Nexus archives (local MO2 download metadata or supported MO2 download-manager callback), exact/stable GitHub release assets with release/asset identity checks, and referenced local archives. SHA-256 cache entries are verified before reuse. Downloads retain partials and resume only with a matching server validator. Credentials/download URLs are not written into locks.
- Recipe-based transitive graph expansion with exact component/version/artifact identity, full reason chains, satisfiable repeated dependencies, finite options, explicit dependency alternatives, variants, declared conflicts, game/DLC requirements and archive mappings. Missing dependency metadata stays unknown and requires a recipe; native provider normalization is still pending.
- Optional Git registry index: resolve one commit, read blobs without checkout, verify index recipe hashes, cache recipes and retain correction reasons/provenance. Conflicting corrections require a choice. Cached exact commits work offline.
- Inspected locks retain the semantic manifest digest, game identity/version, exact artifact IDs/hashes/sizes, recipe bytes/hash/document, options/selected alternatives, graph edges, output hashes/destinations, ordering, registry commits and Collection rules. Lock installation does not re-resolve metadata.
- New source deployment stages files, uses independently writable mod directories, serializes instance installation with an OS-released lock, journals root backups and progress, restores unchanged owned root outputs after failure, and publishes the profile last. A failure between publication and the final journal write is recoverable. Existing profiles/mods are not replaced; incompatible Overwrite files block installation. A child process was terminated with os._exit during a root write; retry completed and retained the original backup. Broader crash coverage and ownership restoration UI remain pending.
- Real MO2 UI now exposes source manifest/lock installation and Collection import. Worker input requests cross to the owning Qt thread; selected recipes/options/winners persist in an import choices sidecar. A final review lists components and physical root effects. Individual Nexus downloads reuse MO2's supported service callbacks.
- Collection reader handles full JSON/ZIP/7z packages, URL/NXM revision identity, optional inclusion, exact Nexus/GitHub sources, exact rule-reference matching, before/after ordering, requires/recommends, conflict rejection and file winners. Unsupported patches/installer choices/bundled assets/instructions and fuzzy references remain explicit review requests with the full original document retained; they are not silently considered installed.
- Imported mod source provenance is stored outside mod file trees and is recoverable by subsequent manifest export. Export remains one agreed-schema JSON.

Validation this iteration:

- 35 core tests passed at this checkpoint. Added tests cover transitive source installs and offline retry, exact conflicts/reason chains, variant output identities, selected alternatives, source provenance re-export, tampered recipe bytes, failed root deployment restoration, final publication recovery, server-validated range resume, archive aliases/links, registry pin/cache verification and Collection semantics.
- `artifacts/source-ui-probe-v3/probe-result.json`: passed in real MO2 2.5.2/Python 3.12.3/PyQt6. A recipe was selected on the UI thread, a plan reviewed, a new profile installed and a second profile installed from the cache/lock after moving original recipe/archive files away. Both installed file contents matched. Existing selected profile hash stayed unchanged. Probe v2 also passed; v1 correctly blocked on leftover Overwrite content from prior gameplay. The disposable Overwrite was preserved as `test-install/MO2/overwrite-before-source-import-v2` before retry.
- Live Collection service check: the public CET+Essentials revision lookup reached the package-download step, which requires authentication. A different Collection returned `ADULT_CONTENT_BLOCKED`, now surfaced as a provider code without bypassing its content flow. No authenticated Collection transfer has been proven. Source references: Nexus-Mods/extension-collections and Nexus-Mods/node-nexus-api, cached read-only under ignored artifacts/references.
- Development deployment remains only in the disposable MO2 instance. No new source-manifest gameplay smoke check has been performed. Historical bundle gameplay below is not evidence for this importer.

Remaining acceptance work (do not mark the goal complete yet):

1. Native metadata/candidate normalization, particularly Nexus file-level requirements and file selection; explicit range/comparison schemes and automatic compatible-alternative solving if needed. Current recipe alternatives require an explicit finite option.
2. Complete manual handoffs for Collection installation instructions/patches, bundled archives and other source sites; authenticated Collection URL download and live MO2 Nexus archive transfer. Validate a representative real Collection, not just fixtures.
3. Additional deployment hardening: broaden hard-process interruption coverage, complete lock validation and root ownership/restoration experience; CP77 support-plugin prerequisites for fresh instances.
4. Final mixed-source CP77 pack from a source manifest (Nexus + GitHub + local + transitive dependency), locked fresh-profile reproduction and game smoke check. Preserve the user's Play profile and stable game.

See RECIPES.md for the implemented recipe/registry format. Documentation intentionally distinguishes this preview from full SPEC.md acceptance.

## Current direction: 0.3.0 source-manifest export

The user corrected the snapshot approach: export only the agreed-schema `modlist.json`. The snapshot round-trip evidence below is historical and does not prove the specified source-manifest workflow complete.

- Added the Manifest v1 JSON Schema and strict runtime validation, with no `mode`, blob recipes or snapshot fields in exported JSON.
- MO2 export prompts for each unknown source: local archive, provider URL, explicit Skip, or cancel. User requested these prompts inside export, not during development. Local references are permitted for testing.
- Tested those three decisions inside the actual MO2 host (`artifacts/manifest-ui-probe-v1/probe-result.json`); three dependencies were exported, the skipped mod was reported, and only one JSON file was created by export.
- Exported real Play to `artifacts/Play-manifest/modlist.json`: 15 dependencies; seven Nexus, seven GitHub and AMM as a local archive. DLSS was explicitly skipped as requested. No lockfile or blobs accompany this export.
- Removed the old bundle importer UI, CLI command, core `import_profile` function and obsolete round-trip import probes/tests. New packages expose export/validation only.
- Repeated the MO2 dialog test after importer removal (`manifest-ui-probe-v2`): all three source choices and single-file export passed. Thirteen current tests pass, including stale GitHub provenance rejection; removed legacy importer tests are not counted.
- Remaining work is the actual source-manifest resolver/installer from SPEC.md. Snapshot deployment must not be reported as completion of that workflow.

The sections below describe the earlier snapshot experiment, including functions and helpers since removed.

## Acceptance target

User requested profile -> modlist -> fresh profile, with Cyberpunk immediately playable; the exact personal configuration is not the product requirement. Current implementation locks installed outputs, reconstructs matching content from pinned archives, and retains local changes in a private bundle.

## Implemented

- Independent Python core and CLI; MO2 Python/PyQt6 tool extension.
- Export/import with per-file SHA-256, manifest binding, preserved ordering, overwrite capture and physical root deployment.
- Separate installed directories; ordinary failure rollback and backups; game-build/DLC checks; Windows path validation.
- CP77 game-plugin settings captured. CLI applies them to the target INI; the UI uses the host settings API.
- Development helpers for creating a credential-free portable test instance and cloning the GOG-listed game files, plugin deployment, real-host Qt integration testing and installed-file verification.

## Evidence

- Real MO2: 2.5.2; embedded Python 3.12.3; PyQt6. Core test environment: Python 3.12.0.
- Nine unit/integration-fixture tests passed, including hash tampering, manifest mismatch, preserving existing profiles, path rejection, INI preservation, matching/conflicting overwrite and root-file rollback after a simulated failure.
- Export of the source Play profile: 16 enabled mods, 311 root files, 134 retained overwrite files, 539 distinct content blobs. Logs and crash dumps are excluded; machine settings/saves were not opted in.
- First restored profile: `Play - Roundtrip` in `test-install/MO2`.
- Verified 429 restored mod/overwrite files across 17 layers against the lock, with no mismatches and matching priority.
- Real-host probe instantiated the tool dialog, ran its Qt worker to re-export the restored profile, and imported that export into `Probe - Reimport`. Probe reported success. A Windows path-length failure in the initial probe was fixed by shortening staging directory names.
- Final real-host rerun (`integration-probe-v4`) passed after adding cooperative progress checkpoints and allowing existing overwrite files whose contents exactly match the incoming effective files. Created `Probe - integration-probe-v4`; its 434 files across 18 layers verified with zero mismatches before launch.
- Launched `Probe - Reimport` through the test MO2 instance against the separate test game directory. Cyberpunk reached the 2.31 / Phantom Liberty main menu. RED4ext logged successful loading of ArchiveXL, Audioware, Codeware and TweakXL; script compiler invocation succeeded.
- A post-launch comparison of the second import found two runtime-mutated files (a database and user.gls). Initial content is locked; runtime mutation is expected. The first, unlaunched import still verified all 429 files.
- Desktop Windows.Graphics.Capture failed with `SetIsBorderRequired ... 0x80004002`. Accessibility inspection worked; input injection was unreliable. Used the previously authorized read-only GDI capture helper for the menu evidence. Requested a user Continue/load-and-move check; gameplay verification remains pending at this point.

Private evidence is under ignored `artifacts/`: exported bundles, `integration-probe-v2/result.json`, verification reports and menu screenshot. It must not be committed or published.

Packaged the extension as `artifacts/MO2-Modlists-0.1.0.zip`, with a SHA-256 sidecar. Only code and documentation are included. Source Play's modlist hash remained `22711d90ca05692f6ef0b8b197ea75982e36ed499cf341a95aa266df44ee44d9` throughout testing. The test game later shut down cleanly; no new REDEngine crash report appeared.

## Test locations

- Source MO2: `E:/Modding/Cyberpunk2077` (not modified by development deployment).
- Source game: `E:/Games/Cyberpunk 2077`.
- Disposable MO2: `E:/Modding/mo2modlist/test-install/MO2`.
- Separate test game: `C:/Users/d/Documents/MO2-Modlists-Test-Game`.
- The game test directory is a copy of the local GOG-listed base files plus imported root contents, not a newly downloaded/pristine installation. This distinction limits what the test proves about unknown stock-file edits.

## Next work

1. Profile round-trip gameplay acceptance is complete; see the final smoke check below. Broader source-manifest work remains separate.
2. Broaden profile/layout/settings support and add strict JSON schemas, import locking and hard-crash recovery.
3. Validate a live Nexus download through MO2 and broaden automatic GitHub provenance discovery. Source-backed exports, archive member recipes and cache reuse are implemented below.
4. Add native dependency metadata normalization and the shared resolver, using supplemental recipes only where necessary.

## Source reconstruction follow-up (0.2.0)

- Added archive-member matching, compact source-backed locks and hydration of exact installed output; FOMOD selections are preserved by output/member mappings.
- Real export matched 208 distinct blobs to 15 original archives. The initial compact bundle retained 894,921,687 bytes instead of 1,373,260,517 bytes (the remainder is modified/generated/unmapped content).
- Reconstructed all 208 missing blobs with an empty source cache: eight GitHub release assets were newly downloaded and seven Nexus archives came from existing MO2 downloads. All final file hashes passed verification. No new Nexus account/API credentials were accessed.
- Added the MO2 download-manager bridge for missing pinned Nexus archives; callbacks register successfully in the real MO2 host (probe v5), and the core verifies callback-supplied content in a fixture test. A live authenticated Nexus transfer is not yet proven.
- UI export now attempts compaction using source archives; UI import hydrates missing content before deployment. Optional settings provide additional archive directories/GitHub source catalog. CLI `compact`, `hydrate` and automatic import hydration expose the same pipeline.
- Fourteen tests pass. New tests cover selected variant reconstruction, retained local changes, changed archives, unsafe members, Nexus acquisition hash verification and the source-export wrapper's temporary snapshot cleanup.
- Imported the reconstructed real bundle into `Source-backed - Roundtrip`. The first attempt correctly rejected runtime-generated conflicting overwrite from the earlier game launch. Preserved that disposable instance's overwrite as `overwrite-before-source-roundtrip`, created an empty overwrite and retried successfully.
- Verified all 429 managed files across 17 layers in that source-backed import, with zero mismatches and matching priority (`artifacts/source-roundtrip-verification.json`). Version 0.2.0 is deployed only in the disposable MO2 instance and packaged as `artifacts/MO2-Modlists-0.2.0.zip` (SHA-256 `895be4dbd31f08bb8ade40aab7bde4c42354f20990e633fa06dbf402b3add21e`).
- Root/overwrite inventories contain some save copies left by the existing setup under game/mod directories. Standard user save folders are not collected, but this generic snapshot includes those nested copies. Bundles must be treated as private; automatic classification of such leftovers remains future work.
- The source-backed pipeline does not imply the broader dependency resolver is complete.

## Final gameplay smoke check

On 2026-09-26, launched `Source-backed - Roundtrip` through the disposable MO2 instance against `C:/Users/d/Documents/MO2-Modlists-Test-Game`. This is the profile reconstructed from eight freshly downloaded GitHub archives, seven cached Nexus archives and retained local blobs.

- The game reached the Cyberpunk 2.31 / Phantom Liberty menu, then loaded the local Continue save (`QuickSave-9`, Gig: Monster Hunt).
- Keyboard control worked on this fresh launch. Verified a rendered in-world HUD and scene, crouch-to-standing camera/stance change, and a jump with visible vertical camera movement. The character and world continued updating without a crash during the smoke check.
- Private screenshots: `artifacts/source-gameplay-before.png`, `source-gameplay-crouch.png`, `source-gameplay-jump.png`. These prove a loaded, responsive game rather than just successful startup. Forward taps were too short to establish sustained walking; no extended playtest is claimed.
- Redscript's current log reports successful compilation. ArchiveXL logged in-world resource patching during save load.
- Closed the test game with Alt+F4. Rechecked that its process and the temporary launch MO2 had exited. The latest REDEngine report remains dated September 22; this test produced no new report.
- Source Play modlist SHA-256 still matches the recorded original. Development deployment and imports targeted only the disposable instance and separate game folder.

The requested **profile -> modlist -> new profile, playable immediately** milestone is verified on this machine. This does not establish support for every MO2/game distribution, replace a long gameplay compatibility test, or complete the broader dependency-resolver stages in SPEC.md. Live authenticated Nexus acquisition remains an integration check for the next stage; this round trip used verified cached Nexus archives.
