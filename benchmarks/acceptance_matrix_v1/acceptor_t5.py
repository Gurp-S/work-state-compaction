"""End-to-end pipeline checks against actual intermediate files and lineage."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from .acceptors import collect, require, raises
from .evidence import canonical


def published(output, manifest):
    require(manifest['format'] == 'invoice.pipeline/2', 'wrong_manifest_format')
    require(canonical(manifest) == canonical(json.loads((output/'manifest.json').read_text(encoding='utf-8'))),
            'returned_manifest_differs_from_disk')
    require(set(manifest['stages']) == {'normalized', 'totals'}, 'missing_stage')
    values, files = {}, {}
    for name, item in manifest['stages'].items():
        relative = Path(item['path'])
        path = (output/relative).resolve()
        require(not relative.is_absolute() and path.is_relative_to(output.resolve()), 'artifact_path_outside_output')
        raw = path.read_bytes()
        require(sha256(raw).hexdigest() == item['sha256'], 'artifact_hash_mismatch')
        values[name] = json.loads(raw.decode('utf-8'))
        files[path] = raw
    require(type(manifest['stages']['normalized']['rows']) is int
            and manifest['stages']['normalized']['rows'] == len(values['normalized']), 'normalized_count_wrong')
    require(type(manifest['stages']['totals']['tenants']) is int
            and manifest['stages']['totals']['tenants'] == len(values['totals']), 'tenant_count_wrong')
    require(manifest['stages']['totals']['from_sha256'] == manifest['stages']['normalized']['sha256'],
            'stage_lineage_mismatch')
    return values, files


def accept_t5(module):
    run = module.run
    normal = b'tenant,invoice,amount\na,one,0.10\na,two,0.20\nb,one,-1.25\n'

    def execute(root, raw):
        source, output = root/'input.csv', root/'out'
        source.write_bytes(raw)
        manifest = run(source, output)
        require(source.read_bytes() == raw, 'input_source_mutated')
        require(manifest['source_sha256'] == sha256(raw).hexdigest(), 'source_digest_not_raw_bytes')
        values, files = published(output, manifest)
        return output, manifest, values, files

    def basic():
        with tempfile.TemporaryDirectory() as folder:
            _, _, values, _ = execute(Path(folder), normal)
            require(canonical(values['normalized']) == canonical([
                dict(tenant='a', invoice='one', cents=10), dict(tenant='a', invoice='two', cents=20),
                dict(tenant='b', invoice='one', cents=-125)]), 'normalization_wrong')
            require(canonical(values['totals']) == canonical([
                dict(tenant='a', invoice_count=2, total_cents=30),
                dict(tenant='b', invoice_count=1, total_cents=-125)]), 'aggregation_wrong')

    def identity():
        with tempfile.TemporaryDirectory() as folder:
            raw = 'tenant,invoice,amount\n a , 一🙂 ,1.0\na,一🙂,1.00\nb,一🙂,1.00\n'.encode('utf-8')
            _, _, values, _ = execute(Path(folder), raw)
            require(values['normalized'] == [dict(tenant='a', invoice='一🙂', cents=100),
                                              dict(tenant='b', invoice='一🙂', cents=100)], 'identity_or_dedup_wrong')

    def reject_without_publication(raw):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output, _, _, files = execute(root, normal)
            before = (output/'manifest.json').read_bytes()
            (root/'input.csv').write_bytes(raw)
            raises(ValueError, lambda: run(root/'input.csv', output))
            require((output/'manifest.json').read_bytes() == before
                    and all(path.read_bytes() == value for path, value in files.items()), 'invalid_input_changed_commit')

    def conflict():
        reject_without_publication(b'tenant,invoice,amount\na,one,1\na,one,2\n')

    def decode():
        reject_without_publication(b'tenant,invoice,amount\na,\xff,1\n')

    def amount():
        for value in ('1.005', 'NaN', '1e2', '', '+1'):
            reject_without_publication(('tenant,invoice,amount\na,x,'+value+'\n').encode())

    def shape():
        for raw in (b'tenant,invoice,wrong\na,x,1\n', b'tenant,invoice,amount\na,x\n',
                    b'tenant,invoice,amount\na,x,1,extra\n', b'tenant,invoice,amount\na,"broken,1\n'):
            reject_without_publication(raw)

    def replay():
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output, manifest, _, files = execute(root, normal)
            before = (output/'manifest.json').read_bytes()
            again = run(root/'input.csv', output)
            require(canonical(again) == canonical(manifest) and (output/'manifest.json').read_bytes() == before
                    and all(path.read_bytes() == raw for path, raw in files.items()), 'replay_changed_bytes')

    def original_bytes():
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, first, values1, _ = execute(root, b'tenant,invoice,amount\r\na,x,1.00\r\n')
            _, second, values2, _ = execute(root, b'tenant,invoice,amount\na,x,1.00\n')
            require(first['source_sha256'] != second['source_sha256'] and values1 == values2,
                    'raw_input_identity_conflated_with_rendered_text')

    def historical_artifacts():
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, old, _, files = execute(root, normal)
            output, new, _, _ = execute(root, b'tenant,invoice,amount\na,changed,9.00\n')
            require(old['source_sha256'] != new['source_sha256'], 'new_input_identity_missing')
            require(all(path.read_bytes() == raw for path, raw in files.items()), 'old_artifact_overwritten')
            published(output, new)

    def corruption():
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output, manifest, _, _ = execute(root, normal)
            target = output/manifest['stages']['normalized']['path']
            target.write_bytes(b'corrupt')
            before = (output/'manifest.json').read_bytes()
            raises(ValueError, lambda: run(root/'input.csv', output))
            require(target.read_bytes() == b'corrupt' and (output/'manifest.json').read_bytes() == before,
                    'existing_corruption_overwritten_or_recertified')

    def large_exact_integer():
        with tempfile.TemporaryDirectory() as folder:
            amount = '123456789012345678901234567890.12'
            _, _, values, _ = execute(Path(folder), ('tenant,invoice,amount\na,x,'+amount+'\n').encode())
            require(values['normalized'][0]['cents'] == 12345678901234567890123456789012,
                    'integer_precision_lost')

    return collect('T5', [('stage-files-and-values', 'stage-lineage', basic),
        ('identity-and-dedup', 'invoice-identity', identity), ('conflict-reject', 'no-invalid-publication', conflict),
        ('strict-utf8', 'source-fidelity', decode), ('amount-format', None, amount),
        ('csv-shape', None, shape), ('byte-stable-replay', None, replay),
        ('original-input-bytes', 'source-fidelity', original_bytes),
        ('historical-artifacts', 'history-preservation', historical_artifacts),
        ('existing-corruption', 'no-conflict-overwrite', corruption), ('exact-integer', None, large_exact_integer)])
