"""Compose manifests and review additions to an existing MO2 profile."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

from .acquisition import InputRequired
from .core import PackError, active_mods, digest, files, json_digest, safe_join, write_json
from .games import detect_game, game_path, overlay_path
from .manifest import export_manifest, profile_sources, validate_manifest


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def absolute_manifest(document, declaring):
    document = deepcopy(document)
    for dep in document["dependencies"].values():
        if dep["source"]["type"] == "local-archive":
            dep["source"]["path"] = (declaring.parent / dep["source"]["path"]).resolve().as_posix()
        if "recipe" in dep:
            dep["recipe"] = (declaring.parent / dep["recipe"]).resolve().as_posix()
    for registry in document.get("registries", {}).values():
        if "://" not in registry["repository"]:
            registry["repository"] = (declaring.parent / registry["repository"]).resolve().as_posix()
    return document


def merge_collections(left, right):
    """Retain both sets of rules, instructions and hash-bound review provenance."""
    result = {"schemaVersion": 1, "rules": [], "pathWinners": [], "manualHandoffs": {}, "sources": []}
    instructions = []
    for collection in (left, right):
        if collection.get("schemaVersion") != 1:
            raise PackError("Unsupported Collection metadata version")
        for source in collection.get("sources", [collection]):
            if source not in result["sources"]:
                result["sources"].append(deepcopy(source))
        for field in ("rules", "pathWinners"):
            for rule in collection.get(field, []):
                if rule not in result[field]:
                    result[field].append(deepcopy(rule))
        for alias, handoff in collection.get("manualHandoffs", {}).items():
            if alias in result["manualHandoffs"] and result["manualHandoffs"][alias] != handoff:
                raise PackError("Conflicting Collection installer handoffs: " + alias)
            result["manualHandoffs"][alias] = deepcopy(handoff)
        instruction = collection.get("externalInstructions")
        if instruction and instruction not in instructions:
            instructions.append(instruction)
    result["externalInstructions"] = "\n\n".join(instructions)
    return result


def package_signature(package):
    return json_digest({"component": package["component"], "artifact": package["artifact"]["sha256"],
                        "options": package["options"], "outputs": package["outputs"]})


def installed_packages(mo2, profile, lock):
    """Use recorded provenance rather than positional zip of mods and lock entries."""
    found = {}
    for name in active_mods(profile):
        path = safe_join(mo2, ".modlists/installed/" + name + ".json")
        if not path.is_file():
            continue
        record = read(path)
        for key, package in lock.get("packages", {}).items():
            if (record.get("component") == package["component"]
                    and record.get("artifact", {}).get("sha256") == package["artifact"]["sha256"]
                    and record.get("options") == package["options"]):
                if key in found:
                    raise PackError("Multiple active copies of component: " + package["component"])
                found[key] = name
    return found


def snapshot(mo2, game, profile, root_paths=()):
    """Bind review to profile metadata, active mods, overwrite and relevant root files."""
    result = {"profile": {}, "mods": {}, "root": {}, "otherLocks": {}}
    for name in ("modlist.txt", "modlist.json", "modlist.origin.json", "modlist.state.json", "modlist.lock.json", "plugins.txt", "loadorder.txt"):
        path = safe_join(profile, name)
        result["profile"][name] = digest(path) if path.is_file() else None
    # MO2 rewrites comments/line endings and discovers disabled folders after
    # refresh. Only enabled membership/order affects the reviewed solve; the
    # current disabled lines and separators are retained at publication.
    result["profile"]["modlist.txt"] = json_digest(active_mods(profile))
    for name in active_mods(profile):
        directory = safe_join(mo2, "mods/" + name)
        result["mods"][name] = {p.relative_to(directory).as_posix(): digest(p) for p in files(directory)
                                if p.relative_to(directory).as_posix().casefold() != "meta.ini"}
    directory = safe_join(mo2, "overwrite")
    result["overwrite"] = {p.relative_to(directory).as_posix(): digest(p) for p in files(directory)}
    for name in root_paths:
        path = safe_join(game, name)
        result["root"][name] = digest(path) if path.is_file() else None
    for other in (mo2 / "profiles").iterdir():
        if other != profile:
            path = safe_join(other, "modlist.lock.json")
            if path.is_file():
                result["otherLocks"][other.name] = digest(path)
    return result


def source_identity(source):
    """Provider identity across versions; never infer identity from folder titles."""
    kind = source.get('type')
    if kind == 'nexus':
        return kind, source['game'].casefold(), source['modId']
    if kind == 'github-release':
        asset = source.get('asset', '').casefold()
        tag = source.get('tag', '').casefold()
        for token in (tag, tag.removeprefix('v')):
            if token:
                asset = asset.replace(token, '{version}')
        return kind, source['repository'].casefold(), asset
    return kind, str(Path(source['path']).resolve()).casefold()


def prepare_add(incoming, store, mo2, game, profile_name, *, ask=None, progress=lambda text: None, upgrade=False):
    """Solve against the actual active profile, preferring compatible installed versions."""
    from .packages import (validate_package, definitions, package_from_lock, merge_packages,
                           compile_package, package_name, exported_version)
    from .planning import resolve_source_plan as resolve_manifest
    from .install import recover_profile_update
    incoming_raw = validate_package(read(incoming))
    profile = safe_join(mo2, 'profiles/' + profile_name)
    if not (profile / 'modlist.txt').is_file():
        raise PackError('Select an existing MO2 profile')
    recover_profile_update(mo2, game, profile_name)
    initial = snapshot(mo2, game, profile)
    workspace = mo2 / '.modlists/additions' / uuid.uuid4().hex
    workspace.mkdir(parents=True)
    old = read(profile / 'modlist.lock.json') if (profile / 'modlist.lock.json').is_file() else {}
    mapped = installed_packages(mo2, profile, old)
    active = active_mods(profile)
    records, _ = definitions(incoming_raw, incoming, store, progress)
    catalog = list(records.values())
    captured, captured_entries, captured_definitions, prepared_definitions = {}, {}, {}, []
    extra_names = set(active) - set(mapped.values())
    for item in profile_sources(mo2, profile_name, store.archives, game_id=detect_game(game)):
        name = item['name']
        if name not in extra_names:
            continue
        dependency = item['dependency']
        if dependency is None:
            request = InputRequired('existing-source', 'Choose a source for existing mod: ' + name, mod=name)
            if ask is None:
                raise request
            dependency = ask(request.request)
        if dependency is None:
            continue
        captured[name] = dependency
        # Reuse an authoritative package definition for an exact recorded archive.
        exact = [d for d in catalog if
                 (dependency.get('integrity') and dependency['integrity'] == d['mo2'].get('integrity'))
                 or dependency['source'] in d['mo2'].get('sources', [])]
        exact = [d for d in exact if not (dependency['source']['type'] == 'nexus'
                 and 'fileId' not in dependency['source'] and not dependency.get('integrity'))]
        source_path = workspace / (json_digest(name) + '.json')
        source_lock = source_path.with_suffix('.lock.json')
        if len(exact) == 1:
            doc = deepcopy(exact[0])
            doc['mo2']['packages'] = catalog
            write_json(source_path, doc)
        else:
            write_json(source_path, {'schemaVersion': 1, 'name': name,
                'game': {'id': detect_game(game), 'dlc': []}, 'dependencies': {name: dependency}})
        resolved = resolve_manifest(source_path, store, game, source_lock, ask=ask, progress=progress)
        prepared = package_from_lock(resolved.get('resolvedManifest') or read(source_path), resolved, collapse_root=True)
        prepared_definitions.extend(prepared['mo2'].pop('packages', []))
        captured_definitions[name] = prepared
        candidates = [p for p in resolved['packages'].values()
                      if p['artifact']['source'] == dependency['source']
                      or dependency.get('integrity') == 'sha256:' + p['artifact']['sha256']]
        if len(candidates) != 1:
            raise PackError('Cannot identify the installed package for ' + name)
        entry = candidates[0]
        expected = {overlay_path(detect_game(game), e['path']).casefold(): e['sha256']
                    for e in entry['outputs'] if e['class'] == 'mo2-overlay'}
        if not expected or any(not safe_join(mo2 / 'mods' / name, path).is_file()
                               or digest(safe_join(mo2 / 'mods' / name, path)) != sha
                               for path, sha in expected.items()):
            raise PackError('Installed files differ from the recorded source; reconcile before adoption: ' + name)
        captured_entries[name] = entry

    entries = {name: old['packages'][key] for key, name in mapped.items()}
    entries.update(captured_entries)
    # Recover complete named metadata from the active records, not the stale saved list.
    selected = {}
    for folder, entry in entries.items():
        authored = entry['recipe']['document'].get('extensions', {}).get('package')
        if authored:
            doc = deepcopy(authored)
        elif folder in captured_definitions:
            doc = deepcopy(captured_definitions[folder])
        else:
            key = 'installed'
            temporary = {'packages': {key: entry}, 'aliases': {key: key}, 'dependencyEdges': []}
            intent = {'name': folder, 'game': {'id': detect_game(game), 'dlc': []},
                      'dependencies': {key: {'source': entry['artifact']['source'],
                          'integrity': 'sha256:' + entry['artifact']['sha256']}}}
            doc = package_from_lock(intent, temporary, collapse_root=True)
        doc['mo2'].pop('packages', None)
        # Provider provenance connects an MO2-installed mod to its catalog name.
        identities = {source_identity(s) for s in doc['mo2'].get('sources', [])}
        names = {d['name'] for d in catalog if identities &
                 {source_identity(s) for s in d['mo2'].get('sources', [])}}
        if len(names) > 1:
            raise PackError('Ambiguous package identity for installed mod: ' + folder)
        if names and not authored:
            doc['name'] = names.pop()
        same = [d for d in catalog if d['name'] == doc['name'] and d['version'] == doc['version']]
        if same and not authored:
            # The source/file check above binds adoption; the published definition supplies dependencies.
            doc = deepcopy(same[0])
        if doc['name'] in selected and selected[doc['name']]['version'] != doc['version']:
            raise PackError('Multiple active versions of ' + doc['name'] + '; disable the unwanted version first')
        selected[doc['name']] = doc

    saved = read(profile / 'modlist.json') if (profile / 'modlist.json').is_file() else {}
    authored_root = saved.get('extensions', {}).get('packageRoot')
    if authored_root:
        base = deepcopy(authored_root)
        if base['mo2'].get('extensions', {}).get('composedPackage') or not base['mo2'].get('sources'):
            base['dependencies'] = {n: r for n, r in base['dependencies'].items() if n in selected}
        elif base['name'] not in selected:
            base = None
    else:
        base = None
    if base is None:
        base = {'name': package_name(profile_name) + '-profile', 'version': '1.0.0',
                'dependencies': {n: '*' for n in selected},
                'mo2': {'schemaVersion': 1, 'game': {'id': detect_game(game), 'dlc': []},
                        'extensions': {'composedPackage': True}}}
    elif captured_entries and base['mo2'].get('sources'):
        base = {'name': package_name(profile_name) + '-profile', 'version': '1.0.0',
                'dependencies': {base['name']: base['version']},
                'mo2': {'schemaVersion': 1, 'game': deepcopy(base['mo2']['game']),
                        'extensions': {**base['mo2'].get('extensions', {}), 'composedPackage': True}}}
    # Add manually enabled packages while keeping authored ranges for managed roots.
    for folder, entry in captured_entries.items():
        matches = [n for n, d in selected.items() if any(source_identity(s) == source_identity(entry['artifact']['source'])
                   for s in d['mo2'].get('sources', []))]
        for name in matches:
            base['dependencies'].setdefault(name, '*')
    identities = {(n, d['version']) for n, d in selected.items()}
    base['mo2']['packages'] = [d for n, d in selected.items() if n != base['name']] + [
        d for d in prepared_definitions if (d['name'], d['version']) not in identities]
    combined_package = merge_packages(base, incoming_raw, store, workspace / 'base.json', incoming,
                                      ask=ask, progress=progress)
    path = workspace / 'package.json'
    write_json(path, combined_package)
    compiled = compile_package(path, store, ask=ask, game=game, progress=progress,
                               installed=None if upgrade else {n: d['version'] for n, d in selected.items()})
    combined = read(compiled)
    combined.setdefault('extensions', {})['profilePriority'] = [entries[n]['component'] for n in active if n in entries]
    if combined['game']['id'] == 'newvegas':
        from .newvegas import profile_plugins
        requested = profile_plugins(profile)
        for name in combined.pop('plugins', []):
            if name.casefold() not in {p.casefold() for p in requested}:
                requested.append(name)
        combined['extensions']['profileAddPlugins'] = {'enabled': requested, 'previousFiles': sorted({
            e['path'].split('/')[-1].casefold() for p in entries.values() for e in p['outputs']
            if e['path'].lower().endswith(('.esm', '.esp'))})}
    manifest = workspace / 'modlist.json'
    write_json(manifest, combined)
    lock_path = workspace / 'modlist.lock.json'
    lock = resolve_manifest(manifest, store, game, lock_path, progress=progress, ask=ask)
    if snapshot(mo2, game, profile) != initial:
        raise PackError('Profile changed during resolution; retry the addition')
    plan = update_plan(mo2, game, profile_name, lock, captured, captured_entries=captured_entries)
    plan.update(manifest=str(manifest), lock=str(lock_path))
    write_json(workspace / 'update.json', plan)
    return plan


def root_outputs(lock):
    result = {}
    for key in reversed(lock.get("priority", [])):
        for entry in lock["packages"][key]["outputs"]:
            if entry["class"] == "game-root":
                result[entry["path"].casefold()] = entry
    return result


def original_root(mo2, game, entry):
    """Follow recorded replacement backups to the bytes preceding mod deployment."""
    records = []
    for path in (mo2 / ".modlists").glob("*/journal.json"):
        journal = read(path)
        if journal.get("status") != "complete" or journal.get("targetGame") != str(game.resolve()):
            continue
        item = journal.get("root", {}).get(entry["path"].casefold())
        if item:
            records.append((path, item))
    current, backup, visited = entry["sha256"], None, set()
    while current not in visited:
        visited.add(current)
        matches = [(path, item) for path, item in records if item["writtenSha256"] == current]
        if not matches:
            if backup is None:
                raise PackError("No ownership backup for obsolete root file: " + entry["path"])
            return backup
        path, item = max(matches, key=lambda pair: pair[0].stat().st_mtime_ns)
        if not item["backup"]:
            return None
        original = item["backup"]
        location = safe_join(path.parent, Path(original["path"]).relative_to(path.parent).as_posix())
        if not location.is_file() or digest(location) != original["sha256"]:
            raise PackError("Root ownership backup changed: " + entry["path"])
        backup = {"path": str(location), "sha256": original["sha256"]}
        current = original["sha256"]
    raise PackError("Cyclic root backup history; review manually: " + entry["path"])


def update_plan(mo2, game, profile_name, lock, captured=None, *, captured_entries=None):
    profile = safe_join(mo2, "profiles/" + profile_name)
    old = read(profile / "modlist.lock.json") if (profile / "modlist.lock.json").is_file() else {}
    names = installed_packages(mo2, profile, old)
    old_components = {p["component"]: (key, p) for key, p in old.get("packages", {}).items() if key in names}
    reuse, replaced, added = {}, [], []
    managed = set(names.values())
    existing = {names[key]: package for key, package in old.get('packages', {}).items() if key in names}
    existing.update(captured_entries or {})
    for key, package in lock["packages"].items():
        previous = old_components.get(package["component"])
        if not previous:
            matches = [(name, prior) for name, prior in existing.items()
                       if (not prior['recipe']['document'].get('extensions', {}).get('package')
                           or prior['recipe']['document']['extensions']['package']['name'] == package['component'])
                       and (source_identity(prior['artifact']['source']) == source_identity(package['artifact']['source'])
                            or prior['artifact']['sha256'] == package['artifact']['sha256']
                            or prior['recipe']['document'].get('extensions', {}).get('package', {}).get('name') == package['component'])]
            if len(matches) > 1:
                raise PackError('Multiple active copies match ' + package['displayName'] + '; disable the unwanted copies first')
            if matches:
                name, prior = matches[0]
                previous = (None, prior)
        if previous:
            old_key, prior = previous
            if old_key is not None:
                name = names[old_key]
            managed.add(name)
            if package_signature(package) == package_signature({**prior, 'component': package['component']}):
                reuse[key] = name
            else:
                expected = {overlay_path(lock["game"]["id"], e["path"]).casefold(): e["sha256"]
                            for e in prior["outputs"] if e["class"] == "mo2-overlay"}
                actual = {p.relative_to(mo2 / "mods" / name).as_posix().casefold(): digest(p)
                          for p in files(mo2 / "mods" / name) if p.name.casefold() != "meta.ini"}
                if actual != expected:
                    raise PackError("Locally edited mod needs reconciliation before upgrading: " + name)
                replaced.append(name)
        else:
            added.append(package["displayName"])
            for name, dependency in (captured or {}).items():
                if dependency["source"] != package["artifact"]["source"]:
                    continue
                # Adopt a manually installed mod only when all expected overlay
                # bytes match. Extra user files stay in the adopted directory.
                entries = [e for e in package["outputs"] if e["class"] == "mo2-overlay"]
                if not entries:
                    continue
                for entry in entries:
                    path = safe_join(mo2 / "mods" / name, overlay_path(lock["game"]["id"], entry["path"]))
                    if not path.is_file() or digest(path) != entry["sha256"]:
                        raise PackError("Installed files differ from source; provide the correct recipe: " + name)
                reuse[key] = name
                managed.add(name)
                break
    unmanaged = [n for n in active_mods(profile) if n not in managed]
    changed_outputs = {}
    for key, package in lock["packages"].items():
        if key not in reuse:
            for entry in package["outputs"]:
                changed_outputs.setdefault(entry["path"].casefold(), set()).add(entry["sha256"])
    for key, name in reuse.items():
        package = lock["packages"][key]
        expected = {e["path"].casefold(): e["sha256"] for e in package["outputs"]}
        for path in files(mo2 / "mods" / name):
            relative = game_path(lock["game"]["id"], path.relative_to(mo2 / "mods" / name).as_posix()).casefold()
            if relative in changed_outputs:
                actual = digest(path)
                if actual != expected.get(relative) and changed_outputs[relative] != {actual}:
                    raise PackError("Locally edited or extra file conflicts with the addition: " + str(path))
    # Unmanaged mods remain enabled. Never silently choose their file conflicts.
    outputs = {e["path"].casefold(): e["sha256"] for p in lock["packages"].values() for e in p["outputs"]}
    for name in unmanaged:
        for path in files(mo2 / "mods" / name):
            relative = game_path(lock["game"]["id"], path.relative_to(mo2 / "mods" / name).as_posix()).casefold()
            if relative in outputs and digest(path) != outputs[relative]:
                raise PackError("Unmanaged mod conflicts with the addition; record its source first: " + name)
    before, after = root_outputs(old), root_outputs(lock)
    removed_root = {k: v for k, v in before.items() if k not in after}
    removed_root = {k: {**v, "restore": original_root(mo2, game, v)} for k, v in removed_root.items()}
    changed_root = {k: v for k, v in before.items() if k not in after or after[k]["sha256"] != v["sha256"]}
    for entry in before.values():
        path = safe_join(game, entry["path"])
        if not path.is_file() or digest(path) != entry["sha256"]:
            raise PackError("Locally edited game-root file needs reconciliation: " + entry["path"])
    for other in (mo2 / "profiles").iterdir():
        if other == profile or not (other / "modlist.lock.json").is_file():
            continue
        for canonical, entry in root_outputs(read(other / "modlist.lock.json")).items():
            if canonical in changed_root or (canonical in after and after[canonical]["sha256"] != entry["sha256"]):
                raise PackError(f"Profile '{other.name}' requires a different shared game-root file: {entry['path']}")
    paths = sorted({e["path"] for e in [*before.values(), *after.values()]})
    return {"profileName": profile_name, "reuse": reuse, "managed": sorted(managed),
            "unmanaged": unmanaged, "added": added, "replaced": replaced,
            "removed": [n for n in names.values() if n not in reuse.values() and n not in replaced],
            "removeRoot": list(removed_root.values()), "rootPaths": paths,
            "snapshot": snapshot(mo2, game, profile, paths), "lockSha256": json_digest(lock)}


def assert_review_current(plan, mo2, game):
    profile = safe_join(mo2, "profiles/" + plan["profileName"])
    if snapshot(mo2, game, profile, plan["rootPaths"]) != plan["snapshot"]:
        raise PackError("Profile or installed files changed since review; resolve and review again")


def updated_modlist(profile, plan, names):
    managed = {n.casefold() for n in plan["managed"]}
    preserved = [line for line in (profile / "modlist.txt").read_text(encoding="utf-8-sig").splitlines()
                 if not (line.startswith(("+", "-")) and line[1:].casefold() in managed)]
    return "# MO2 Modlists: highest priority first\n" + "".join("+" + name + "\n" for name in names) + "\n".join(preserved) + "\n"
