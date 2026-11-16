"""Pin source bytes and evaluation settings across all paid run stages."""
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal_run(*, root, release, harness, out, run, system, state_producer, separate_producer_budget,
             answer_model, judge_model, raw_memory=False, source_state_guards=False, narrow_source_checks=False,
             write_revisions=False, batch_revisions=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run):
        raise ValueError('invalid_run_name')
    manifest_path = release / 'manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    for name, expected in json.loads(manifest_bytes)['files'].items():
        if _sha(release / name) != expected:
            raise ValueError(f'release_hash_mismatch: {name}')
    sources = [root / 'benchmarks/run_csm_bench22.py',
               *(root / 'benchmarks').glob('csm_bench22*.py'),
               *(root / 'src/wsc').rglob('*.py'), *harness.rglob('*.py'), *harness.rglob('*.md'),
               harness / 'bench22/score_config.json', harness / 'bench22/prices.json']
    config = {'run': run, 'split': 'dev', 'system': system, 'state_producer': state_producer,
              'separate_producer_budget': separate_producer_budget,
              'answer_model': answer_model, 'judge_model': judge_model,
              'dataset_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
              'code_sha256': {path.relative_to(root).as_posix(): _sha(path) for path in sorted(sources)}}
    if raw_memory:
        config['raw_memory'] = True
    if source_state_guards:
        config['source_state_guards'] = True
    if narrow_source_checks:
        config['narrow_source_checks'] = True
    if write_revisions:
        config['write_revisions'] = True
    if batch_revisions:
        config['batch_revisions'] = True
    stage = out / run
    path = stage / 'config.json'
    if path.is_file():
        if json.loads(path.read_bytes()) != config:
            raise ValueError(f'run_config_mismatch: {run}')
    else:
        if stage.exists() and any(stage.iterdir()):
            raise ValueError(f'unsealed_existing_run: {run}')
        out.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='seal-', dir=out) as directory:
            pending = Path(directory) / run
            snapshot = pending / 'code-snapshot'
            for name, expected in config['code_sha256'].items():
                content = (root / name).read_bytes()
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError(f'source_changed_during_seal: {name}')
                destination = snapshot / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            (pending / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
            if stage.exists():
                stage.rmdir()
            pending.rename(stage)
    return config
