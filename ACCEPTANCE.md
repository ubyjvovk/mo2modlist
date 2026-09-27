# Source importer acceptance

Status: 2026-09-27, version 0.6.0. Implementation is available; final live acceptance is incomplete. Historical bundle gameplay does not validate this source importer.

| Requirement | Evidence | Remaining check |
| --- | --- | --- |
| Export only Manifest v1 JSON; unknown-source Local/URL/Skip prompts | Manifest tests and real MO2 export probes | None for covered paths |
| Mixed Nexus, GitHub and local sources with transitive dependencies | Five-component real pack installed as Mixed Source First; 37 managed files verified | Loaded-world smoke and second real locked profile |
| Recipe options, alternatives, conflicts, native candidate backtracking | Resolver and source-install tests; vendored resolvelib runs in MO2 | Live eight-component Immersive Third Person graph passed; archive installation pending |
| Exact locks, verified cache, offline reinstall | Automated tests and real MO2 fixture reinstallation | Real mixed-source second-profile reproduction |
| Archive safety, collisions, stage before activation, interrupted recovery | Automated tests including hard process exit and changed download validators | No general claim about every archive or runtime conflict |
| Physical root deployment with ownership and restoration | Real framework launch and real MO2 restoration probes | Loaded-world check; physical writes affect all profiles using that game |
| Profile export preserves verified installation recipe references | Custom-mapping export/import regression | Real mixed-source profile re-export on current version |
| Nexus Collection package/rules/manual choices | Full-package fixtures and real MO2 Collection fixture imports | Representative downloaded Collection or authenticated live revision |
| Nexus acquisition and manual fallback | Verified Codeware bytes with exact Nexus identity; manager bridge registered in MO2 | Installed binding fixed; non-Premium transfer requires website handoff |
| Existing installation preserved | Disposable MO2/game only; stable Play hash recorded in PROGRESS.md | Recheck at final acceptance |

## Resume live acceptance

1. Supply the exact Immersive Third Person archive (32203/161480) and Native Settings UI (3518/63684) through the supported Nexus website flow. Six framework archives already match Nexus-published hashes. Metadata authentication and live transitive resolution are verified.
2. Resolve `artifacts/itp-nexus-test/modlist.json` to its complete lock, review actual output mappings/collisions, and install into a fresh named profile in the cleaned disposable MO2. Do not publish a partial profile.
3. Verify managed files and readable names, then reproduce the lock in a second profile with network access disabled. Export/re-import the resulting profile with its verified recipe references available.
4. Launch through the test MO2 and perform a loaded-world/input/mod-function check. The user's successful Probe - Reimport run was an older snapshot import, before the authorized test cleanup.
5. Validate a representative real Collection using the now-configured API key or a complete downloaded package. Preserve unresolved installer choices as incomplete.
6. Recheck stable-profile preservation and record final scope limits. Stable installation is outside cleanup/deployment scope.

The prior test data is recoverable under `test-install/cleanup-20260927`; the current instance has only an empty Default profile until the new installation succeeds. Browser/desktop control tools were absent during the latest work, so website-only downloads await a supported interactive flow.

Current evidence lives under ignored `artifacts/`; private manifests, caches, credentials and screenshots are not release contents. The disposable game is a copy based on GOG's installed-file list, not a vendor-hash-verified pristine download.
