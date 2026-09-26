# Source importer acceptance

Status: 2026-09-26, version 0.5.3. Implementation is available; final live acceptance is incomplete. Historical bundle gameplay does not validate this source importer.

| Requirement | Evidence | Remaining check |
| --- | --- | --- |
| Export only Manifest v1 JSON; unknown-source Local/URL/Skip prompts | Manifest tests and real MO2 export probes | None for covered paths |
| Mixed Nexus, GitHub and local sources with transitive dependencies | Five-component real pack installed as Mixed Source First; 37 managed files verified | Loaded-world smoke and second real locked profile |
| Recipe options, alternatives, conflicts, native candidate backtracking | Resolver and source-install tests; vendored resolvelib runs in MO2 | Authenticated Nexus metadata against representative live mods |
| Exact locks, verified cache, offline reinstall | Automated tests and real MO2 fixture reinstallation | Real mixed-source second-profile reproduction |
| Archive safety, collisions, stage before activation, interrupted recovery | Automated tests including hard process exit and changed download validators | No general claim about every archive or runtime conflict |
| Physical root deployment with ownership and restoration | Real framework launch and real MO2 restoration probes | Loaded-world check; physical writes affect all profiles using that game |
| Profile export preserves verified installation recipe references | Custom-mapping export/import regression | Real mixed-source profile re-export on current version |
| Nexus Collection package/rules/manual choices | Full-package fixtures and real MO2 Collection fixture imports | Representative downloaded Collection or authenticated live revision |
| Nexus acquisition and manual fallback | Verified Codeware bytes with exact Nexus identity; manager bridge registered in MO2 | Dedicated current UI fallback check and authenticated transfer |
| Existing installation preserved | Disposable MO2/game only; stable Play hash recorded in PROGRESS.md | Recheck at final acceptance |

## Resume live acceptance

1. User reviews the CD Projekt RED agreement in the disposable game and accepts it if they agree. Do not automate acceptance or bypass it through settings.
2. Load a save and verify responsive gameplay plus the acceptance observer's WORLD_READY log. Close the disposable game before installation work.
3. Deploy the current plugin only into `test-install/MO2`. Re-resolve into a new lock to record current recipe provenance, reproduce the real pack in a fresh profile using the verified cache, and verify managed files. Export that profile to one JSON and import it again with its referenced recipes available.
4. Configure an optional Nexus credential through the test plugin's secure credentials UI, or supply a full downloaded Collection package. Never put a key into chat or committed files. Validate a representative Collection's actual install requirements and preserve unresolved choices as incomplete.
5. Run the targeted host fallback flow, final file verification and stable-profile preservation check. Record failures and scope limits; mark the goal complete only after required live gates pass.

Current evidence lives under ignored `artifacts/`; private manifests, caches, credentials and screenshots are not release contents. The disposable game is a copy based on GOG's installed-file list, not a vendor-hash-verified pristine download.
