# Progress: 2026-09-26

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
