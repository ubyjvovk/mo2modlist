# Source importer acceptance

Status: 2026-09-27, version 0.6.2. Real ITP download, installation, offline reproduction and export/re-import passed; user confirmed third-person gameplay works. Real Collection resolution, cache-only installation, 138-file verification and startup passed; loaded-save/UI confirmation remains pending. Current mixed-source reproduction/gameplay also remains pending.

| Requirement | Evidence | Remaining check |
| --- | --- | --- |
| Export only Manifest v1 JSON; unknown-source Local/URL/Skip prompts | Manifest tests and real MO2 export probes | None for covered paths |
| Mixed Nexus, GitHub and local sources with transitive dependencies | Five-component real pack installed as Mixed Source First; 37 managed files verified | Loaded-world smoke and second real locked profile |
| Recipe options, alternatives, conflicts, native candidate backtracking | Resolver tests and live eight-component ITP graph installed | Broader live alternative/conflict cases |
| Exact locks, verified cache, offline reinstall | Real ITP lock installed with socket networking blocked; 94 files verified | Real mixed-source second-profile reproduction |
| Archive safety, collisions, stage before activation, interrupted recovery | Automated tests including hard process exit and changed download validators | No general claim about every archive or runtime conflict |
| Physical root deployment with ownership and restoration | Real framework launch and real MO2 restoration probes | Loaded-world check; physical writes affect all profiles using that game |
| Profile export preserves verified installation recipe references | Real eight-component ITP export/re-import; 94 files verified | Real mixed-source profile re-export on current version |
| Nexus Collection package/rules/manual choices | Full-package fixtures and real MO2 Collection fixture imports | Representative downloaded Collection or authenticated live revision |
| Nexus acquisition and manual fallback | Real Premium API downloads of ITP and Native Settings matched published hashes | Non-Premium transfer requires website handoff |
| Existing installation preserved | Disposable MO2/game only; stable Play hash recorded in PROGRESS.md | Recheck at final acceptance |

## Resume live acceptance

1. Completed: Premium downloaded ITP 32203/161480 and Native Settings UI 3518/63684; six framework archives were reused by matching Nexus-published hashes.
2. Completed: resolved eight components and installed `ITP - Nexus Test` with readable names.
3. Completed: `ITP - Offline Test` installed with network connections blocked; one-file export imported into `ITP - Reexport Test`. All three profiles verified 94 managed files without differences before launch.
4. Completed: launched `ITP - Nexus Test`; script compilation and ITP/nativeSettings loading succeeded. User confirmed third-person mod gameplay works.
5. Complete real Collection gameplay check. CET+Essentials revision 49 installed from cache into `test-collection/MO2`, with every original pin preserved and three explicit review recipes. All 138 managed files verified; frameworks loaded and scripts compiled. User loaded-save/UI confirmation is pending. Evidence is under `artifacts/live-collection-20260927`.
6. Recheck stable-profile preservation and record final scope limits. Stable installation is outside cleanup/deployment scope.

The prior test data is recoverable under `test-install/cleanup-20260927`. Current profiles are Default and the three ITP acceptance profiles. Browser/desktop control tools remain unavailable; Premium API access removed the archive-download blocker.

Current evidence lives under ignored `artifacts/`; private manifests, caches, credentials and screenshots are not release contents. The disposable game is a copy based on GOG's installed-file list, not a vendor-hash-verified pristine download.
