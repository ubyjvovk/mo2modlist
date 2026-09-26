# Progress: 2026-09-26

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

1. Finish gameplay acceptance (save loading and movement); preview packaging is complete.
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
- Verified all 429 managed files across 17 layers in that source-backed import, with zero mismatches and matching priority (`artifacts/source-roundtrip-verification.json`). Version 0.2.0 is deployed only in the disposable MO2 instance and packaged as `artifacts/MO2-Modlists-0.2.0.zip` (SHA-256 `6d519507023d8b65076b278b5e50ffbc8c4bf95ff427fd08d83a67e05068a1bf`).
- Root/overwrite inventories contain some save copies left by the existing setup under game/mod directories. Standard user save folders are not collected, but this generic snapshot includes those nested copies. Bundles must be treated as private; automatic classification of such leftovers remains future work.
- Save loading/movement acceptance remains pending. The source-backed pipeline does not imply the broader dependency resolver is complete.
