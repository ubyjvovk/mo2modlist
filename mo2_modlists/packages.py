"""Package definitions, named range resolution, and generated deployment plans.

Only this module knows about the lowering boundary. Authors supply package.json;
generated recipe documents are immutable cache implementation details.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
import zipfile

from ._vendor.semantic_version import Version, NpmSpec
from ._vendor.resolvelib import AbstractProvider, BaseReporter, Resolver, ResolutionImpossible, ResolutionTooDeep
from .acquisition import InputRequired, reference_path
from .core import PackError, digest, json_digest, write_json, safe_relative

NAME = re.compile(r'(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z')


def is_package(document):
    return isinstance(document, dict) and isinstance(document.get('mo2'), dict)


def version(value):
    try:
        return Version(value)
    except (TypeError, ValueError):
        raise PackError(f'Package version must be SemVer (for example 2.1.0): {value!r}') from None


def spec(value):
    try:
        if not isinstance(value, str) or not value.strip():
            raise ValueError()
        return NpmSpec(value)
    except (TypeError, ValueError, AttributeError):
        raise PackError(f'Invalid npm version range {value!r}; use ~2.1.0, ^2.1.0 or >=2.1.0 <3.0.0') from None


def validate_package(document, depth=0):
    from .manifest import validate_source, validate_manifest, fields
    if depth > 24:
        raise PackError('Package nesting exceeds 24 levels')
    if not is_package(document) or type(document['mo2'].get('schemaVersion')) is not int or document['mo2']['schemaVersion'] != 1:
        raise PackError('Expected package.json with mo2.schemaVersion: 1')
    if not isinstance(document.get('name'), str) or not NAME.fullmatch(document['name']):
        raise PackError('Use a stable lowercase npm package name; put the readable title in displayName')
    version(document.get('version'))
    if 'displayName' in document and (not isinstance(document['displayName'], str) or not document['displayName'].strip()):
        raise PackError('displayName must be a nonempty string')
    deps = document.get('dependencies')
    if not isinstance(deps, dict):
        raise PackError('Package dependencies must be an explicit name-to-npm-range object')
    for name, requirement in deps.items():
        if not NAME.fullmatch(name):
            raise PackError('Invalid dependency package name: ' + name)
        spec(requirement)
    scripts = document.get('scripts', {})
    if not isinstance(scripts, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in scripts.items()):
        raise PackError('scripts must map lifecycle names to command strings')
    config = document['mo2']
    fields(config, ('schemaVersion', 'game'),
           ('sources', 'integrity', 'install', 'packages', 'conflicts', 'fileOverrides', 'plugins', 'extensions'), 'mo2')
    validate_manifest({'schemaVersion': 1, 'name': 'package game', 'game': config['game'], 'dependencies': {}})
    sources = config.get('sources', [])
    if not isinstance(sources, list):
        raise PackError('mo2.sources must be an ordered array of source objects')
    for source in sources:
        validate_source(source)
    if 'integrity' in config and (not isinstance(config['integrity'], str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', config['integrity'])):
        raise PackError('mo2.integrity must be sha256:<64 lowercase hex characters>')
    if 'install' in config:
        if not isinstance(config['install'], list):
            raise PackError('mo2.install must be a list of declarative file mappings')
        for mapping in config['install']:
            fields(mapping, ('from', 'to', 'class'), (), 'mo2.install mapping')
            if mapping['from'] != '.':
                safe_relative(mapping['from'])
            if mapping['to']:
                safe_relative(mapping['to'])
            if mapping['class'] not in ('game-root', 'mo2-overlay'):
                raise PackError('Unknown install mapping class')
    if not sources and (config.get('install') or scripts.get('install')):
        raise PackError('An install action requires an archive source; collections only declare dependencies')
    for key in ('conflicts',):
        if not isinstance(config.get(key, []), list) or any(not isinstance(x, str) or not NAME.fullmatch(x) for x in config.get(key, [])):
            raise PackError('mo2.' + key + ' must contain package names')
    if not isinstance(config.get('fileOverrides', []), list):
        raise PackError('mo2.fileOverrides must be a list')
    for rule in config.get('fileOverrides', []):
        fields(rule, ('winner', 'loser', 'paths'), (), 'fileOverrides')
        if (not isinstance(rule['winner'], str) or not NAME.fullmatch(rule['winner'])
            or not isinstance(rule['loser'], str) or not NAME.fullmatch(rule['loser'])
            or rule['winner'] == rule['loser']):
            raise PackError('File winners and losers must be distinct package names')
        if not isinstance(rule['paths'], list) or not rule['paths']:
            raise PackError('File override paths must be a nonempty list')
        for path in rule['paths']:
            safe_relative(path)
    if 'plugins' in config:
        if config['game']['id'] != 'newvegas':
            raise PackError('plugins is only supported for New Vegas')
        from .newvegas import validate_plugins
        validate_plugins(config['plugins'])
    packages = config.get('packages', [])
    if not isinstance(packages, list):
        raise PackError('mo2.packages must contain package definitions or JSON document references')
    for item in packages:
        if isinstance(item, str):
            if not item.strip():
                raise PackError('Empty package reference')
        elif isinstance(item, dict):
            validate_package(item, depth + 1)
        else:
            raise PackError('Invalid package definition/reference')
    return document


def absolute_package(document, declaring):
    """Preserve declaration-relative paths when definitions move into a cache/profile."""
    doc = deepcopy(document)
    for source in doc['mo2'].get('sources', []):
        if source['type'] == 'local-archive':
            source['path'] = reference_path(source['path'], declaring).as_posix()
    for i, item in enumerate(doc['mo2'].get('packages', [])):
        if isinstance(item, dict):
            doc['mo2']['packages'][i] = absolute_package(item, declaring)
        elif not item.startswith('https://'):
            doc['mo2']['packages'][i] = reference_path(item, declaring).as_posix()
    return doc


def definitions(document, declaring, store, progress):
    records, seen, identities = {}, set(), {}
    def add(doc, path, depth=0):
        if depth > 24 or len(records) > 512:
            raise PackError('Package catalog exceeds the count/depth limit')
        validate_package(doc)
        doc = absolute_package(doc, path)
        children = doc['mo2'].pop('packages', [])
        token = json_digest(doc)
        key = (doc['name'], doc['version'])
        if key in identities and identities[key] != token:
            raise PackError('Conflicting definitions for ' + '@'.join(key))
        identities[key] = token
        records[token] = doc
        for child in children:
            if isinstance(child, str):
                from .remote_manifests import manifest_reference
                child_path = manifest_reference(child, store.root, offline=store.offline, progress=progress)
                key_path = str(child_path.resolve())
                if key_path in seen:
                    continue
                seen.add(key_path)
                add(json.loads(child_path.read_text(encoding='utf-8-sig')), child_path, depth + 1)
            else:
                add(child, path, depth + 1)
        return token
    root = add(document, declaring)
    return records, root


@dataclass(frozen=True)
class Requirement:
    name: str
    constraint: str
    chain: tuple


@dataclass(frozen=True)
class Candidate:
    name: str
    token: str


class PackageProvider(AbstractProvider):
    def __init__(self, records, installed=None):
        self.records = records
        self.installed = installed or {}

    def identify(self, requirement_or_candidate):
        return requirement_or_candidate.name

    def get_preference(self, identifier, resolutions, candidates, information, backtrack_causes):
        return len(list(candidates[identifier])), identifier

    def find_matches(self, identifier, requirements, incompatibilities):
        constraints, excluded = list(requirements[identifier]), set(incompatibilities[identifier])
        found = [Candidate(identifier, token) for token, doc in self.records.items()
                 if doc['name'] == identifier and all(spec(r.constraint).match(version(doc['version'])) for r in constraints)]
        return sorted((c for c in found if c not in excluded),
                      key=lambda c: (self.installed.get(identifier) == self.records[c.token]['version'],
                                     version(self.records[c.token]['version']), c.token), reverse=True)

    def is_satisfied_by(self, requirement, candidate):
        return requirement.name == candidate.name and spec(requirement.constraint).match(version(self.records[candidate.token]['version']))

    def get_dependencies(self, candidate):
        doc = self.records[candidate.token]
        return [Requirement(name, value, (f"{doc['name']}@{doc['version']}", name)) for name, value in doc['dependencies'].items()]


def solve_packages(records, root, installed=None):
    document = records[root]
    # An explicit root version may be a prerelease; exact npm specs include it.
    requirements = [Requirement(document['name'], document['version'], (document['name'],))]
    try:
        result = Resolver(PackageProvider(records, installed), BaseReporter()).resolve(requirements, max_rounds=10000)
    except ResolutionImpossible as exc:
        causes = sorted({f'{c.requirement.name} {c.requirement.constraint} (via {" -> ".join(c.requirement.chain)})' for c in exc.causes})
        raise PackError('No compatible named package solution: ' + '; '.join(causes) + '. Supply matching package definitions in mo2.packages.') from None
    except ResolutionTooDeep:
        raise PackError('Named dependency resolution exceeded its round limit') from None
    return {name: records[candidate.token] for name, candidate in result.mapping.items()}


def acquire_package(doc, declaring, store):
    sources = doc['mo2'].get('sources', [])
    cache = store.root / 'package-acquisitions' / (json_digest({'name': doc['name'], 'version': doc['version'],
        'sources': sources, 'integrity': doc['mo2'].get('integrity')}) + '.json')
    if store.offline and cache.exists():
        saved = json.loads(cache.read_text(encoding='utf-8'))
        if doc['mo2'].get('integrity') and doc['mo2']['integrity'] != 'sha256:' + saved['sha256']:
            raise PackError('Cached package identity differs from declared integrity')
        if saved['source'] not in sources and not any(s['type'] == 'nexus' and all(saved['source'].get(k) == v for k, v in s.items()) for s in sources):
            raise PackError('Cached package source differs from definition')
        if store.verified(saved):
            return saved
    if not sources:
        # A collection has a dependency graph but deliberately has zero files.
        target = store.root / 'package-collections' / (json_digest(doc) + '.zip')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with zipfile.ZipFile(target, 'w'):
                pass
        return store.acquire({'source': {'type': 'local-archive', 'path': target.as_posix()}, 'integrity': 'sha256:' + digest(target)}, declaring)
    failures = []
    for source in sources:
        dep = {'source': source}
        if 'integrity' in doc['mo2']:
            dep['integrity'] = doc['mo2']['integrity']
        if source['type'] == 'nexus' and 'fileId' not in source:
            if store.nexus_metadata is None:
                raise InputRequired('nexus-file', 'Nexus metadata is required to select ' + doc['name'] + '@' + doc['version'], source=source)
            candidates = store.nexus_metadata.current_versions(source)
            matches = [v for v in candidates if v.get('version') == doc['version'] or v.get('version_number') == doc['version']]
            if len(matches) != 1:
                raise PackError('Nexus source has no unique file for ' + doc['name'] + '@' + doc['version'] + '; specify an exact source file for this package version')
            dep['source'] = {**source, 'fileId': int(matches[0]['game_scoped_id'])}
        try:
            acquired = store.acquire(dep, declaring)
            write_json(cache, acquired)
            return acquired
        except InputRequired:
            raise  # Authentication/manual choices must not silently select a different provider.
        except (OSError, PackError) as exc:
            # A hash mismatch is a provenance error, never a mirror retry.
            if 'SHA-256' in str(exc) or 'modified' in str(exc) or 'changed' in str(exc):
                raise
            failures.append(str(exc))
    raise PackError('No source available for ' + doc['name'] + ': ' + '; '.join(failures))


def compile_package(path, store, *, progress=lambda text: None, ask=None, game=None, installed=None):
    """Resolve names first; only then acquire artifacts and lower to existing plans."""
    original = validate_package(json.loads(path.read_text(encoding='utf-8-sig')))
    records, root = definitions(original, path, store, progress)
    selected = solve_packages(records, root, installed)
    if any(d.get('scripts', {}).get('install') for d in selected.values()):
        from .core import require_game_closed
        if game is None:
            raise PackError('Script preparation requires a target game so running-game checks can be enforced')
        require_game_closed(game)
    for name, doc in selected.items():
        if doc['mo2']['game']['id'] != original['mo2']['game']['id']:
            raise PackError('Package belongs to a different game: ' + name)
        if set(doc['mo2'].get('conflicts', [])) & selected.keys():
            raise PackError('Conflicting named package: ' + name)
    artifacts, preparation = {}, {}
    for name, doc in sorted(selected.items()):
        progress('Acquiring ' + name + '@' + doc['version'])
        artifact = acquire_package(doc, path, store)
        if doc.get('scripts', {}).get('install'):
            from .package_scripts import prepare_script
            artifact, preparation[name] = prepare_script(doc, artifact, store, ask=ask, progress=progress)
        artifacts[name] = artifact
    directory = store.root / 'package-plans' / json_digest({'input': original, 'selected': selected, 'artifacts': artifacts})
    directory.mkdir(parents=True, exist_ok=True)
    def dependency(name):
        artifact = artifacts[name]
        return {'source': artifact['source'], 'integrity': 'sha256:' + artifact['sha256'],
                'recipe': (directory / (json_digest(name) + '.json')).as_posix(),
                'extensions': {'displayName': selected[name].get('displayName', name)}}
    for name, doc in selected.items():
        config = doc['mo2']
        recipe = {'schemaVersion': 1, 'component': name, 'version': doc['version'], 'revision': '1',
                  'artifact': 'sha256:' + artifacts[name]['sha256'], 'game': config['game'],
                  'dependencies': {n: dependency(n) for n in doc['dependencies']},
                  'extensions': {'package': doc, 'acquiredArtifact': artifacts[name], **({'scriptPreparation': preparation[name]} if name in preparation else {})}}
        if 'install' in config:
            recipe['mappings'] = config['install']
        elif not config.get('sources'):
            recipe['mappings'] = []
        if config.get('conflicts'):
            recipe['conflicts'] = config['conflicts']
        write_json(directory / (json_digest(name) + '.json'), recipe)
    config = original['mo2']
    # The root is also a package: it may carry files, dependencies, or both.
    manifest = {'schemaVersion': 1, 'name': original.get('displayName', original['name']), 'game': config['game'],
                'dependencies': {original['name']: dependency(original['name'])},
                'extensions': {**config.get('extensions', {}), 'packageDefinitions': selected, 'packageRoot': absolute_package(original, path)}}
    # Alias all selected names when file ordering rules reference them.
    if config.get('fileOverrides') or config.get('extensions', {}).get('nexusCollection'):
        manifest['dependencies'].update({name: dependency(name) for name in selected})
    if config.get('fileOverrides'):
        manifest['fileOverrides'] = config['fileOverrides']
    if 'plugins' in config:
        manifest['plugins'] = config['plugins']
    output = directory / 'modlist.json'
    write_json(output, manifest)
    return output


def locked_manifest(lock, document):
    """Resolve the public document to its locked, hash-bound internal plan input."""
    if not is_package(document):
        return document
    validate_package(document)
    if lock.get('packageInputSha256') != json_digest(document):
        raise PackError('Package definition differs from lock; re-resolve before installing')
    resolved = lock.get('resolvedManifest')
    if not isinstance(resolved, dict) or json_digest(resolved) != lock.get('manifestSha256'):
        raise PackError('Resolved package manifest differs from lock')
    return resolved


def package_name(value):
    if NAME.fullmatch(value):
        return value
    result = re.sub('[^a-z0-9._-]+', '-', value.lower()).strip('-._')
    if not result or not NAME.fullmatch(result):
        raise PackError('Cannot derive a package name from ' + repr(value))
    return result


def exported_version(value):
    """Normalize numeric provider versions; never guess ordering for vendor labels."""
    text = str(value).removeprefix('v')
    if re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,2}', text):
        text = '.'.join(text.split('.') + ['0'] * (3 - len(text.split('.'))))
    version(text)
    return text


def package_from_lock(document, lock, *, collapse_root=False):
    """Export the selected graph as one portable package.json, without recipe paths."""
    packages = lock['packages']
    names, used = {}, {}
    for key, entry in packages.items():
        authored = entry['recipe']['document'].get('extensions', {}).get('package')
        name = authored['name'] if authored else package_name(entry.get('displayName') or entry['component'])
        if name in used and used[name] != entry['component']:
            raise PackError('Distinct installed components share package name ' + name + '; assign explicit package names before export')
        used[name] = entry['component']
        names[key] = name
    definitions = {}
    for key, entry in packages.items():
        recipe = entry['recipe']['document']
        authored = recipe.get('extensions', {}).get('package')
        if authored:
            doc = deepcopy(authored)
        else:
            from .planning import selected_recipe
            selected, _ = selected_recipe(recipe, entry.get('options', {}))
            source = deepcopy(entry['artifact']['source'])
            if source['type'] == 'local-archive':
                source['path'] = reference_path(source['path'], Path(entry['sourceDocument'])).as_posix()
            doc = {'name': names[key], 'version': exported_version(entry['version']),
                   'displayName': entry.get('displayName', names[key]), 'dependencies': {},
                   'mo2': {'schemaVersion': 1, 'game': recipe.get('game', document['game']),
                           'sources': [source], 'integrity': 'sha256:' + entry['artifact']['sha256']}}
            if 'mappings' in selected:
                doc['mo2']['install'] = selected['mappings']
            if selected.get('conflicts'):
                by_component = {p['component']: names[k] for k, p in packages.items()}
                doc['mo2']['conflicts'] = [by_component.get(c, package_name(c)) for c in selected['conflicts']]
        doc['mo2'].pop('packages', None)
        # Export includes native required edges as well as authored named edges.
        for edge in lock['dependencyEdges']:
            if edge['from'] == key:
                target = packages[edge['to']]
                doc['dependencies'].setdefault(names[edge['to']], exported_version(target['version']))
        definitions[names[key]] = doc
    aliases = {}
    for alias, dependency in document['dependencies'].items():
        matches = [key for key, p in packages.items()
                   if dependency.get('integrity') == 'sha256:' + p['artifact']['sha256']
                   and dependency['source'] in [p['artifact']['source'], *p.get('sourceReferences', [])]]
        if len(matches) != 1:
            # The lock's original aliases identify otherwise unambiguous source requests.
            key = lock.get('aliases', {}).get(alias)
            if key is None or (dependency.get('integrity') and dependency['integrity'] != 'sha256:' + packages[key]['artifact']['sha256']):
                raise PackError('Export needs resolved package metadata for ' + alias)
        else:
            key = matches[0]
        aliases[alias] = names[key]
    reachable, pending = set(), list(aliases.values())
    while pending:
        name = pending.pop()
        if name not in reachable:
            reachable.add(name)
            pending.extend(definitions[name]['dependencies'])
    if collapse_root and len(aliases) == 1:
        root_name = next(iter(aliases.values()))
        result = deepcopy(definitions[root_name])
        reachable.discard(root_name)
    else:
        root_name = package_name(document['name'])
        if root_name in definitions:
            root_name += '-collection'
        result = {'name': root_name, 'version': '1.0.0', 'displayName': document['name'],
                  'dependencies': {name: definitions[name]['version'] for name in aliases.values()},
                  'mo2': {'schemaVersion': 1, 'game': document['game']}}
    result['mo2']['packages'] = [definitions[name] for name in sorted(reachable)]
    if document.get('fileOverrides'):
        result['mo2']['fileOverrides'] = [{**r, 'winner': aliases[r['winner']], 'loser': aliases[r['loser']]} for r in document['fileOverrides']]
    if 'plugins' in document:
        result['mo2']['plugins'] = document['plugins']
    extensions = deepcopy(document.get('extensions', {}))
    extensions.pop('packageDefinitions', None)
    extensions.pop('packageRoot', None)
    collection = extensions.get('nexusCollection')
    if collection:
        for rule in collection.get('rules', []):
            for field in ('source', 'target'):
                rule[field] = aliases.get(rule[field], rule[field])
        for rule in collection.get('pathWinners', []):
            rule['winner'] = aliases.get(rule['winner'], rule['winner'])
        collection['manualHandoffs'] = {aliases.get(k, k): v for k, v in collection.get('manualHandoffs', {}).items()}
    if extensions:
        result['mo2']['extensions'] = extensions
    return validate_package(result)


def package_from_sources(document, destination, store, game, *, ask=None, progress=lambda text: None, single=False):
    """Resolve provider ingestion data and publish only the unified package format."""
    import uuid
    from .profile_add import absolute_manifest
    from .planning import resolve_source_plan as resolve_manifest
    if destination.exists():
        raise PackError('Package destination exists; choose a new filename')
    directory = store.root / 'provider-preparation' / uuid.uuid4().hex
    directory.mkdir(parents=True)
    plan = absolute_manifest(document, destination)
    path = directory / 'plan.json'
    write_json(path, plan)
    lock = resolve_manifest(path, store, game, directory / 'lock.json', ask=ask, progress=progress)
    package = package_from_lock(plan, lock, collapse_root=single)
    write_json(destination, package)
    return package


def merge_packages(base, incoming, store, base_path, incoming_path, *, ask=None, progress=lambda text: None):
    """Combine requested roots, retaining ranges and all available candidates."""
    left, left_root = definitions(base, base_path, store, progress)
    right, right_root = definitions(incoming, incoming_path, store, progress)
    a, b = left[left_root], right[right_root]
    if a['mo2']['game']['id'] != b['mo2']['game']['id']:
        raise PackError('Cannot combine packages for different games')
    if not a['mo2'].get('sources'):
        requirements = dict(a['dependencies'])
        left.pop(left_root)
    else:
        requirements = {a['name']: a['version']}
    if not b['mo2'].get('sources'):
        requested = b['dependencies']
        right.pop(right_root)
    else:
        requested = {b['name']: b['version']}
    for name, constraint in requested.items():
        if name in requirements and requirements[name] != constraint:
            previous = requirements[name]
            shared = [d for d in [*left.values(), *right.values()] if d['name'] == name
                      and spec(previous).match(version(d['version'])) and spec(constraint).match(version(d['version']))]
            if shared:
                def conjunction(a, b):
                    def normalize(value):
                        value = value.strip()
                        if ' - ' in value:
                            low, high = value.split(' - ')
                            return f'>={low} <={high}'
                        return value
                    a, b = normalize(a), normalize(b)
                    if a == '*' or f' {a} ' in f' {b} ':
                        return b
                    if b == '*' or f' {b} ' in f' {a} ':
                        return a
                    return f'{a} {b}'
                constraint = ' || '.join(dict.fromkeys(conjunction(a, b) for a in previous.split('||') for b in constraint.split('||')))
            else:
                request = InputRequired('replace-dependency', f"Replace {name} {previous} with {constraint}?",
                                        alias=name, choices=['replace', 'cancel'], labels=['Replace existing request', 'Cancel'])
                if ask is None or ask(request.request) != 'replace':
                    raise request
        requirements[name] = constraint
    config = deepcopy(base['mo2'])
    config.pop('sources', None)
    config.pop('integrity', None)
    config.pop('install', None)
    config['game']['dlc'] = sorted(set(config['game']['dlc'] + b['mo2']['game']['dlc']))
    old_build, new_build = config['game'].get('version'), b['mo2']['game'].get('version')
    if old_build and new_build and old_build != new_build:
        raise PackError('Conflicting game versions')
    if new_build:
        config['game']['version'] = new_build
    config['packages'] = list({**left, **right}.values())
    for rule in incoming['mo2'].get('fileOverrides', []):
        if rule not in config.setdefault('fileOverrides', []):
            config['fileOverrides'].append(rule)
    from .profile_add import merge_collections
    extra = config.setdefault('extensions', {})
    for key, value in incoming['mo2'].get('extensions', {}).items():
        if key == 'remoteManifests':
            extra[key] = {**extra.get(key, {}), **value}
        elif key == 'nexusCollection' and key in extra:
            extra[key] = merge_collections(extra[key], value)
        elif key in extra and extra[key] != value and key != 'composedPackage':
            raise PackError('Conflicting package extension: ' + key)
        else:
            extra[key] = value
    extra['composedPackage'] = True
    for item in incoming['mo2'].get('plugins', []):
        if item.casefold() not in [n.casefold() for n in config.setdefault('plugins', [])]:
            config['plugins'].append(item)
    return validate_package({'name': package_name(base['name']) + ('' if extra.get('composedPackage') and base['mo2'].get('extensions', {}).get('composedPackage') else '-collection'),
                             'version': '1.0.0', 'dependencies': requirements, 'mo2': config})
