# Declarative recipes and registry index (development format v1)

A recipe is metadata for one exact source artifact. It never executes code. The importer currently needs an explicit recipe or matching registry entry when native dependency metadata is unavailable. An empty `dependencies` object is the recipe author's assertion that there are no required mod dependencies; missing metadata is not equivalent to that assertion.

With a stored Nexus API key, the experimental v3 file adapter can generate metadata for a file with declared native requirements. It preserves raw range definitions, obtains materialized candidates from Nexus and converts a selected candidate to an exact manifest source. Empty new-style requirements still need a recipe because the current GET schema does not expose the legacy-requirements mode. Local installation recipes do not silently remove available native required edges. The CP77 adapter maps verified Nexus DLC IDs 1/2 to Phantom Liberty/REDmod. Candidate backtracking remains future work; multiple native candidates currently request an explicit choice.

```json
{
  "schemaVersion": 1,
  "component": "example/framework",
  "version": "1.2.3",
  "revision": "1",
  "artifact": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "dependencies": {},
  "game": {"id": "cyberpunk2077", "dlc": []},
  "mappings": [
    {"from": "package/r6", "to": "r6", "class": "mo2-overlay"},
    {"from": "package/bin", "to": "bin", "class": "game-root"}
  ]
}
```

Required fields are `schemaVersion`, `component`, `version`, `revision`, `artifact` and `dependencies`. Optional fields are `mappings`, `game`, `conflicts`, `options`, `variants`, `alternatives` and `extensions`. Other fields are rejected. The artifact digest above is a placeholder.

`dependencies` has the same alias/dependency shape as the manifest. Relative archive and recipe references inside it resolve against this recipe's location. `component` explicitly establishes identity across references and sources. A profile can select only one version/artifact/recipe/options combination per component. Different components on the same Nexus page can coexist. Upstream version labels are preserved; current constraints are exact artifact/component assignments, not SemVer range inference.

Mappings select one file, a subtree, or `.` for the whole archive. `to` is a safe game-relative destination, or an empty string for the destination root. A subtree appends each selected member's suffix. Classes are `mo2-overlay` and `game-root`. The latter physically writes the game installation and requires review. Mapping paths use forward slashes; links, path traversal and ambiguous Windows aliases are rejected.

Without `mappings`, the versioned CP77 adapter recognizes paths beginning with `archive/`, `r6/`, `engine/`, `bin/`, `red4ext/` or `mods/`. `bin/` and `red4ext/` use physical root deployment. Root README/license/changelog/text files are ignored. Other layouts and FOMOD installers require explicit mappings. An explicit empty mapping list installs no files. This can describe a dependency-only component.

`conflicts` is an array of component identities. `game` uses the manifest game object and can require an exact game version and DLC.

Options are finite string choices. They may have a default; otherwise the importer requests a choice and records it. A variant can contribute mappings, dependencies and conflicts. Variant mappings append to explicit base mappings; omit base mappings only when the selected variant intentionally supplies the complete mapping.

```json
{
  "options": {"backend": {"choices": ["first", "second"]}},
  "alternatives": {
    "backend": {
      "first": {"source": {"type": "local-archive", "path": "first.zip"}, "recipe": "first.recipe.json"},
      "second": {"source": {"type": "local-archive", "path": "second.zip"}, "recipe": "second.recipe.json"}
    }
  }
}
```

An alternative maps every choice of a declared option to one dependency. Only the selected dependency is expanded, under alias `alternative-<option>`. Its selection and edge are locked. Incompatible explicit choices produce an error with both dependency chains. This is explicit-choice resolution; automatic alternative backtracking and version-range solving are not implemented yet.

## Git registries

The manifest's `registries` maps names to `{repository, revision}`. Repositories can be public HTTPS Git URLs or absolute local repository directories. A revision selector is resolved to one commit. Private repository sign-in is not implemented. Offline resolution requires an exact cached commit; installing an existing complete lock requires no registry checkout or network metadata.

The repository contains `index.json`:

```json
{
  "schemaVersion": 1,
  "entries": [{
    "source": {"type": "nexus", "game": "cyberpunk2077", "modId": 123, "fileId": 456},
    "recipe": "packages/cyberpunk2077/example/1/1.json",
    "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "reason": "Explicit dependencies and install mapping for this exact file"
  }]
}
```

Source matching is exact. Multiple differing recipe corrections for the same source require a choice. All referenced recipe files must be indexed, including recipes reached by relative references. The importer reads Git blobs without checking out files, verifies each recipe against the index and caches it under the pinned commit. The lock retains registry commits, the index digest, selected recipe bytes/digests and correction provenance.

## Nexus Collections

Use the full downloaded collection package, not the website's filtered JSON preview. Collection URLs resolve through Nexus's revision and collection-package endpoints; authentication/content restrictions are surfaced and must be handled through a supported Nexus flow.

The converter pins recorded Nexus file IDs, supports recognized GitHub asset URLs, asks about optional mods, translates unambiguous `before`, `after`, `requires` and `recommends` rules, and retains file winners. Rules use exact Nexus repo/file identities or exact archive metadata; fuzzy filename or version-range references remain pending. Conflict rules block conversion when both sides are selected. Ordering rules and dependency edges stay separate.

Normalized collection metadata lives in `extensions.nexusCollection`; it includes a schema version, revision identity when available, original document digest, rules and path winners. During resolution, the complete output inventory turns ordering rules into effective MO2 priority. Contradictory ordering/file winners block installation.

Patches, FOMOD choices, bundled artifacts, unsupported source sites, collection-specific extensions and installation instructions still require a recorded handoff. The UI saves the complete original data and outstanding requests in a `.collection-review.json`; it does not label that draft installable. General Vortex installer replay is out of scope. Full real-world collection support remains an acceptance item.
