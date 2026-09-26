# MO2 Modlists

Python MO2 extension and independent core for a profile -> modlist -> new profile round trip.

## Working vertical slice

- Export enabled mods in priority order, including the actual installed FOMOD selections.
- Produce `modlist.json`, `modlist.lock.json` and hash-addressed `blobs/` in a private local bundle.
- Capture overwrite as a separate highest-priority mod and physical CP77 root additions/replacements identifiable from the installed GOG file list and enabled mod paths.
- Import into distinct mod directories and a new profile. Verify file hashes before installation; preserve originals when replacing game-root files; roll back ordinary failures.
- Capture CP77 support-plugin settings such as `disable_crashreporter`.
- MO2 tool dialog with background progress, cooperative cancellation and import review.

This first slice locks an already-installed profile. It does **not** yet resolve/download a fresh Nexus/GitHub dependency graph. Source metadata is retained where available, but the exported bundle's blobs are required. A lone JSON cannot recreate modified or locally generated files. Bundles are personal backup/transfer artifacts, not automatically redistributable modpacks.

## In MO2

Deploy the extension into a disposable MO2 instance first:

```powershell
.\.venv\Scripts\python.exe tools\deploy_plugin.py 'C:\Path\To\TestMO2'
```

Restart MO2 and choose **Tools -> Modlists -> Export or import profile**. Export the current profile to a new bundle folder, or select an exported `modlist.json` and choose a new profile name. Review root file deployment before importing. Restart MO2 after import to refresh its profile selector. Game-root files and game-plugin settings affect every profile using that game installation; a second game directory isolates those changes.

The test-only `tools/mo2_integration_probe.py` must not be included in the shipped plugin.

## Command line

Python 3.12+; the core has no external runtime dependencies. Use an explicit interpreter because the development machine's bare `python` points to an older installation.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

.\.venv\Scripts\python.exe -m mo2_modlists.cli export `
  --mo2 'E:\Modding\Cyberpunk2077' --game 'E:\Games\Cyberpunk 2077' `
  --profile Play --bundle 'E:\Backups\Play-export'

.\.venv\Scripts\python.exe -m mo2_modlists.cli verify 'E:\Backups\Play-export'

.\.venv\Scripts\python.exe -m mo2_modlists.cli import `
  --mo2 'E:\Modding\TestMO2' --game 'E:\Games\CP77-test' `
  --profile 'Imported Play' --bundle 'E:\Backups\Play-export' --allow-root
```

Close Cyberpunk before export/import. Close the destination MO2 before using the CLI importer, which updates its INI; the in-app tool uses MO2's settings API instead. Targets must already contain the matching base game/DLC and a configured MO2 instance. An optional `--user-settings` path opts into copying the local game's settings file; saves are not bundled.

## Current limits

- GOG CP77 only for root inventory; target executable/build/DLC identity must match. GOG's file list has paths, not original hashes: unknown modifications to stock files outside enabled mod paths cannot be detected automatically.
- Standard instance layout (`mods`, `profiles`, `overwrite` together). Existing target overwrite files must match the incoming effective contents (logs/crash dumps are ignored); conflicting contents block import. Export refuses existing destination folders; import refuses existing profiles.
- The snapshot preserves initial managed file contents, not subsequent game edits, drivers or save state. Runtime databases/settings may change after launching; that is not an import hash failure.
- No automatic Nexus/GitHub fetching, dependency solver, arbitrary-manifest installation, FOMOD replay, hard-crash resume or automatic root rollback on profile switching yet.
- Journals/backups are retained under `.modlists`. Exceptions trigger rollback; a killed process/power failure requires inspection before retrying.
- Deep destination paths still need broader Windows compatibility testing. Staging uses short names to accommodate MO2's embedded Python host.

## Documents

- [Specification](SPEC.md): broader design and planned source-resolved workflow.
- [Progress and validation](PROGRESS.md): completed checks and remaining acceptance work.
- [Illustrative future source manifest](modlist.example.json): placeholder sources, not an installable pack for this preview.
