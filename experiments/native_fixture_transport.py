"""Opt-in isolated WebSocket transport for frozen A3 browser fixtures."""
from pathlib import Path
import shutil

from native_evidence import manifest, file_hash, save

MODE = 'http_attached_websocket_v1'


def materialize(frozen, destination):
    source = Path(frozen) / 'task-contract/a3-ui-long-v1'
    destination = Path(destination)
    before = manifest(source)
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / 'harness', destination / 'harness')
    shutil.copyfile(source / 'public-contract.json', destination / 'public-contract.json')
    host = destination / 'harness/browser-host.mjs'
    text = host.read_text(encoding='utf8')
    replacements = [
        ('    vite=await createServer({', '    server=createHttpServer();\n    vite=await createServer({'),
        ('server:{middlewareMode:true,hmr:false,fs:', 'server:{middlewareMode:true,hmr:{server},fs:'),
        ('    server=createHttpServer(vite.middlewares);', "    server.on('request',vite.middlewares);")]
    for original, replacement in replacements:
        if text.count(original) != 1:
            raise ValueError('fixture_transport_template_changed')
        text = text.replace(original, replacement)
    host.write_text(text, encoding='utf8', newline='\n')
    assert manifest(source) == before
    receipt = dict(mode='http_attached_websocket_v1', original_manifest=before,
        derived_manifest=manifest(destination), source_unchanged=True,
        original_host_sha256=file_hash(source / 'harness/browser-host.mjs'),
        derived_host_sha256=file_hash(host),
        scope='Transport-only derived fixture; default/frozen original remains unchanged')
    save(destination / 'transport-binding.json', receipt)
    return receipt


def attach(registration, frozen):
    """Attach the same opt-in transport to either arm's existing private runtime."""
    root = Path(registration['workspace']) / '.wsc-runtime/fixture-transport-v1'
    if not root.exists():
        materialize(frozen, root)
    verify(root, frozen)
    return {**registration, 'fixture_transport': MODE, 'fixture_root': str(root),
        'manifest_excludes': list(dict.fromkeys([*registration.get('manifest_excludes', []), '.wsc-runtime']))}


def verify(root, frozen):
    from native_evidence import read
    root = Path(root)
    value = read(root / 'transport-binding.json')
    source = Path(frozen) / 'task-contract/a3-ui-long-v1'
    current = {key: digest for key, digest in manifest(root).items() if key != 'transport-binding.json'}
    if (value.get('mode') != MODE or value.get('original_manifest') != manifest(source)
            or value.get('derived_manifest') != current):
        raise ValueError('fixture_transport_binding_changed')
    return root / 'harness/run-acceptance.mjs'


def public_binding(registration):
    if registration.get('evaluation_host'):
        from native_paired_evaluation import public_binding as evaluation_binding
        return evaluation_binding(registration)
    if not registration.get('fixture_transport'):
        return {}
    if registration['fixture_transport'] != MODE or not registration.get('fixture_root'):
        raise ValueError('fixture_transport_registration_invalid')
    return dict(fixture_transport=MODE,
        public_acceptance_harness=str(Path(registration['fixture_root']) / 'harness/run-acceptance.mjs'))
