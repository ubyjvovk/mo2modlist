# Source importer acceptance

Status: 2026-09-27, version 0.7.0. The specified source-manifest workflow and representative CP77/Nexus Collection acceptance checks have passed. New Vegas acceptance is tracked separately below. The release remains a development preview with the scope limits below.

| Requirement | Evidence | Scope |
| --- | --- | --- |
| Export only Manifest v1 JSON; unknown-source Local/URL/Skip prompts | Manifest tests, real MO2 export probes and one-file ITP/mixed-source exports | No archives, local edits or saves exported |
| Nexus, GitHub and local sources, including transitive dependencies | Twelve-component mixed ITP pack installed twice; 99 initial managed files verified in each profile | Real GitHub framework release assets, Nexus mods and local observer archive |
| Recipes, variants, alternatives, conflicts and reason chains | Resolver tests, native candidate backtracking tests, live ITP graph | Unknown metadata and unsupported installer choices block completion |
| Exact locks, cache and offline reinstall | ITP and mixed-source locks reproduced with socket networking blocked; 94/99 initial files verified | Offline install requires finalized lock and cached archives; fresh resolution may need provider metadata |
| Archive safety, collisions and interruption recovery | Tests cover unsafe paths/links, conflicting outputs, validator changes and hard process exit | No claim to detect semantic conflicts inside different game archives |
| Physical root deployment and restoration | Real MO2 restoration probes and framework gameplay; CET reload regression fixed in 0.6.3 | Root writes affect all profiles sharing a game directory; keep extension enabled for runtime mappings |
| Profile re-export retains verified recipes | Eight-component ITP export/re-import verified 94 files; twelve-component mixed-source re-export resolves to identical managed output hashes | Local recipe/archive references must remain accessible |
| Real Nexus Collection conversion and import | Authenticated CET+Essentials revision 49, all 11 exact pins preserved, three explicitly reviewed recipes, 138 initial files verified | Browser Extension/Virtual Atelier settings and loaded-world movement smoke passed |
| Playable fresh profile | User confirmed ITP third-person operation; autonomous mixed-source and Collection save/load/move/crouch checks passed | Representative smoke checks, not long-duration stability tests |
| Existing installation preserved | Stable Play hash matches September 27 baseline; deployment confined to disposable MO2/game directories | Windows Saved Games location was repaired separately after failed-drive discovery |

The automated suite has 94 passing tests. Additional acceptance cases include unavailable locked assets, selected-variant output separation, source identity/hash changes, manifest/lock mismatch, native dependency omission, root restoration protection, unsupported Collection choices, New Vegas Data mounting, plugin master ordering, extended TES4 subrecords, bundled Collection directories and hash-bound external reviews.

## Live evidence

### New Vegas: Gopher's Stable New Vegas revision 17

The real Collection `60wuix` was converted into a finalized manifest and lock, then installed from the verified cache into `E:/Modding/FalloutNewVegas/profiles/Gopher Stable NV r17`. All 24 required entries were included; two optional ESM-repair entries were excluded. All 23 Nexus archives matched the Collection's MD5 values, with SHA-256 pins in the recipes/lock. Bundled NVTF settings, exact applicable ordering and external handoffs were reviewed explicitly. The regional executable was 4GB-patched before resolution with a separate original backup.

Initial verification checked 1,543 managed files with zero differences. MO2 showed 24 active mods and 12 active plugins. All 14 NVSE DLL plugins reported successful loading, both mod ESM/ESP files appeared in runtime logs, and the existing Remix/ReShade DLSS5 addon initialized on the RTX 5080. The processes remained responsive and exited after Alt+F4. Window capture timed out twice; this is startup evidence, not a loaded-world gameplay or neural-rendering evaluation result for the Collection.

First run populated the supplied ShowOff, OneTweak and Stewie INIs without changing their existing key values. The post-launch verifier correctly reports these three changed files. Cell Offset Generator's runtime Overwrite files remain preserved. Evidence is under `E:/Modding/FalloutNewVegas/modlists/60wuix`, including the manifest, lock, exact recipes/review decisions, before/after verification and startup logs. The historical DLSS-only lock still describes the pre-4GB executable and is not rewritten.

### Cyberpunk 2077

- `artifacts/itp-nexus-test`: Premium acquisition, exact dependency graph, install, offline reproduction and export/re-import.
- `artifacts/mixed-itp-test`: two installations, network-blocked reproduction, initial file verification, re-export comparison and `fixed-{mods,world,moved-crouched}.png`.
- `artifacts/live-collection-20260927`: downloaded package, explicit review decisions, resolved lock, installation, initial verification and `playtest-{modsettings,world,moved}.png`.

The first hands-on reload exposed CET Lua lookup failures caused by runtime Overwrite directories. The focused 0.6.3 file mapper fixes these without deleting runtime files or changing installed mod bytes. A broader experimental mapping caused one crash and was removed; no new crash report followed the focused implementation's gameplay checks. The passive observer's player-existence log is not used as proof that a save loaded.

The test save initially could not be found because Windows Saved Games still referred to the failed F: drive. That known-folder location was repaired and the preserved test autosave copied to the restored location without overwriting existing saves. See PROGRESS.md for the repair record.

Private manifests, caches, credentials, helper code and screenshots under ignored `artifacts/` are not release contents. Disposable game directories were copied from GOG's installed-file list, not verified against vendor hashes. Non-Premium acquisition remains a website/manual-archive handoff; universal mod/runtime compatibility is not claimed.
