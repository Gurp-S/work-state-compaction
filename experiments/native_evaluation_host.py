"""Opt-in A3 evaluation host with the existing production panel wrapper."""
from pathlib import Path
import shutil

from native_evidence import read, save, file_hash, manifest
from native_fixture_transport import verify as verify_transport

MODE = 'a3_production_panel_host_v1'


def attach(registration, frozen):
    root = Path(registration['workspace']) / '.wsc-runtime/evaluation-host-v1'
    if not root.exists():
        materialize(registration['fixture_root'], frozen, root)
    verify(root, frozen)
    return {**registration, 'evaluation_host': MODE, 'fixture_root': str(root)}


def materialize(transport_root, frozen, destination):
    transport_root, destination = Path(transport_root), Path(destination)
    verify_transport(transport_root, frozen)
    before = manifest(transport_root)
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(transport_root / 'harness', destination / 'harness')
    shutil.copyfile(transport_root / 'public-contract.json', destination / 'public-contract.json')
    main = destination / 'harness/main.tsx'
    text = main.read_text(encoding='utf8')
    if text.count('UsagePageBody') != 2 or 'A3SnapshotPanel' not in text:
        raise ValueError('evaluation_host_template_changed')
    main.write_text(text.replace('UsagePageBody', 'A3SnapshotPanel'), encoding='utf8', newline='\n')
    if manifest(transport_root) != before:
        raise ValueError('evaluation_host_upstream_changed')
    save(destination / 'evaluation-host-binding.json', dict(mode=MODE,
        upstream_root=str(transport_root.resolve()), upstream_manifest=before,
        upstream_transport_receipt_sha256=file_hash(transport_root / 'transport-binding.json'),
        derived_manifest=manifest(destination),
        component_entry='A3SnapshotPanel', source_transformations=0,
        scope='Existing production panel wrapper; separate opt-in host, original frozen fixtures unchanged'))
    return verify(destination, frozen)


def verify(root, frozen):
    root = Path(root)
    value = read(root / 'evaluation-host-binding.json')
    current = {key: h for key, h in manifest(root).items() if key != 'evaluation-host-binding.json'}
    upstream = Path(value['upstream_root'])
    verify_transport(upstream, frozen)
    if (value.get('mode') != MODE or value.get('component_entry') != 'A3SnapshotPanel'
            or value.get('derived_manifest') != current or value.get('upstream_manifest') != manifest(upstream)
            or value.get('upstream_transport_receipt_sha256') != file_hash(upstream / 'transport-binding.json')):
        raise ValueError('evaluation_host_binding_changed')
    return root / 'harness/run-acceptance.mjs'
