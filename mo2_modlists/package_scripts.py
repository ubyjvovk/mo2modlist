"""Explicitly trusted install scripts prepare an archive before deployment review."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from .acquisition import InputRequired
from .core import PackError, digest, json_digest, safe_join, write_json
from .sources import members, stream_member


def prepare_script(document, original, store, *, ask=None, progress=lambda text: None):
    command = document['scripts']['install']
    identity = {'package': document['name'], 'version': document['version'],
                'command': command, 'inputSha256': original['sha256'], 'definitionSha256': json_digest(document)}
    key = json_digest(identity)
    record_path = store.root / 'script-preparations' / (key + '.json')
    if record_path.exists():
        saved = json.loads(record_path.read_text(encoding='utf-8'))
        if saved.get('identity') != identity:
            raise PackError('Script preparation identity was modified')
        if store.verified(saved['artifact']):
            return saved['artifact'], saved
    request = InputRequired('install-script',
        f"Run install script for {document['name']}@{document['version']}?\n{command}\n"
        'It runs with your account permissions in a temporary preparation directory, not a security sandbox. '
        'Its resulting files are hashed before the normal deployment review.',
        **identity, approvalId=key)
    if ask is None or ask(request.request) != key:
        raise request
    store.root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='package-script-', dir=store.root) as temp:
        root = Path(temp)
        for member, _ in members(store.path(original['sha256'])):
            target = safe_join(root, member)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('wb') as output:
                stream_member(store.path(original['sha256']), member, output=output)
        # Standard package.json is available even when a mod ZIP omitted it.
        write_json(root / 'package.json', document)
        env = os.environ.copy()
        env.update(MO2_PACKAGE_DIR=str(root), npm_package_name=document['name'], npm_package_version=document['version'])
        progress('Running approved install script: ' + document['name'])
        process = subprocess.Popen(command, cwd=root, env=env, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=0x08000000 if os.name == 'nt' else 0,
                                   start_new_session=os.name != 'nt')
        try:
            output, _ = process.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise PackError('Install script exceeded 300 seconds') from None
        if process.returncode:
            raise PackError(f"Install script failed for {document['name']} (exit {process.returncode}); no game files were deployed")
        result = store.root / 'script-preparations' / (key + '.zip')
        result.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for file in sorted(root.rglob('*')):
                if file.is_symlink() or (hasattr(file, 'is_junction') and file.is_junction()):
                    raise PackError('Install scripts cannot publish filesystem links')
                if file.is_file() and file != root / 'package.json':
                    if not file.resolve().is_relative_to(root.resolve()):
                        raise PackError('Script output escapes preparation directory')
                    info = zipfile.ZipInfo(file.relative_to(root).as_posix(), (2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    bundle.writestr(info, file.read_bytes())
        artifact = store.acquire({'source': {'type': 'local-archive', 'path': result.as_posix()},
                                  'integrity': 'sha256:' + digest(result)}, result)
    saved = {'identity': identity, 'sourceArtifact': original, 'artifact': artifact,
             'notice': 'Prepared by an explicitly approved executable command; locked installs use the verified cached output.'}
    write_json(record_path, saved)
    return artifact, saved
