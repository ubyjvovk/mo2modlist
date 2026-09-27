"""Convert public Nexus URLs to the source manifest schema."""
from pathlib import Path
import urllib.parse

from .core import PackError, write_json
from .manifest import source_from_url, validate_manifest
from .collections import (collection_reference, fetch_collection, read_collection,
                          convert_collection, write_collection_manifest, bundled_dependency)


def nexus_url_kind(url):
    parsed = urllib.parse.urlparse(url.strip())
    if '/collections/' in parsed.path:
        collection_reference(url)
        return 'collection'
    source = source_from_url(url)
    if source['type'] != 'nexus' or source['game'] not in ('cyberpunk2077', 'newvegas'):
        raise PackError('Use a Cyberpunk 2077 or Fallout New Vegas Nexus mod or Collection URL')
    return 'mod'


def manifest_from_url(url, output: Path, *, name=None, cache=None, headers=None,
                      decisions=None, fetch=fetch_collection, provider=None, ask=None,
                      progress=lambda text: None):
    if output.exists():
        raise PackError('Manifest destination exists; choose a new filename')
    if nexus_url_kind(url) == 'mod':
        from .nexus import NexusProvider, recipe_from_metadata
        provider = provider or NexusProvider(headers or {})
        source = provider.exact_source(source_from_url(url), ask)
        metadata = provider.metadata(source)
        # Normalize only the root's immediate requirements. Never recursively
        # flatten the dependency graph into this manifest.
        requirements = recipe_from_metadata(metadata, '0' * 64, ask=ask)
        label = name.strip() if name else metadata.get('displayName') or metadata['version'].get('name') or f"Nexus mod {source['modId']}"
        dependencies = {label: {'source': source}}
        for alias, dependency in requirements['dependencies'].items():
            pinned = provider.exact_source(dependency['source'], ask)
            child = provider.metadata(pinned)
            child_name = child.get('displayName') or child['version'].get('name') or alias
            if child_name in dependencies:
                if dependencies[child_name]['source'] == pinned:
                    continue
                child_name += f" ({pinned['modId']}/{pinned['fileId']})"
            dependencies[child_name] = {**dependency, 'source': pinned}
        document = validate_manifest({'schemaVersion': 1, 'name': label,
            'game': requirements.get('game', {'id': source['game'], 'dlc': []}),
            'dependencies': dependencies})
        write_json(output, document)
        return document
    if cache is None:
        raise PackError('A cache directory is required to retrieve a Collection package')
    package, identity = fetch(url, cache, headers=headers, progress=progress)
    document = read_collection(package)
    from copy import deepcopy
    choices = deepcopy(decisions or {})
    for index, mod in enumerate(document['mods'], 1):
        choice = choices.setdefault(f'mod-{index:04d}', {})
        if (mod.get('source', {}).get('type') == 'bundle' and 'source' not in choice
            and (not mod.get('optional') or choice.get('include') is True)):
            choice.update(bundled_dependency(package, mod, cache, progress))
    draft = convert_collection(document, identity=identity, decisions=choices)
    if name:
        draft['manifest']['name'] = name
    write_collection_manifest(draft, output)
    return draft['manifest']
