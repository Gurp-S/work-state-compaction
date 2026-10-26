"""Register a new requirement on preserved interrupted material, without rerunning acquisition."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import zipfile

from native_evidence import digest, file_hash, manifest, read, save
from native_task_checks import require
from run_control_continuation import HERE, METHODS, MODEL, SETTINGS, STAGES


def prepare(source, area, runtime, checkpoint_mode='generated'):
    require(checkpoint_mode in {'generated', 'messages'}, 'recovery_checkpoint_mode_invalid')
    require(not area.exists(), 'recovery_study_already_exists')
    prior_reg, result = read(source / 'registration.json'), read(source / 'result.json')
    require(result['status'] == 'stopped' and len(result['stages']) == 1,
            'recovery_requires_registered_stopped_source')
    work = Path(prior_reg['workspace']).resolve()
    current = manifest(work)
    require(current == result['stages'][0]['after']['manifest'], 'recovery_interrupted_workspace_changed')
    with zipfile.ZipFile(source / 'source_task/after.zip') as archive:
        from hashlib import sha256
        require({n: sha256(archive.read(n)).hexdigest() for n in archive.namelist()} == current,
                'recovery_interrupted_archive_changed')
    phase, rollout = source / 'source_task/phase-outcome.json', source / 'native-rollout-archive/source.jsonl'
    receipt_path = source / 'interrupted-offline-acceptance/receipt.json'
    receipt = read(receipt_path)
    require(file_hash(rollout) == read(phase)['rollout_sha256'], 'recovery_native_archive_changed')
    require(receipt['source_manifest'] == current and receipt['source_manifest_sha256'] == digest(current)
            and receipt['names'] == METHODS and receipt['tests'] == 7 and not receipt['errors']
            and len(receipt['failures']) == 1 and
            receipt['failures'][0]['test'].endswith(METHODS[-1]), 'recovery_baseline_scope_changed')
    grader = HERE.parent / 'tests/test_control_retention.py'
    require(file_hash(grader) == receipt['grader_sha256'], 'recovery_grader_changed')
    runtime = runtime.resolve()
    provenance = runtime.parent / 'provenance.json'
    pins = [phase, rollout, receipt_path, source / 'registration.json', source / 'result.json',
            source / 'source_task/after.zip', grader, Path(prior_reg['executable']), provenance]
    for name, expected in read(provenance)['runtime_sha256'].items():
        path = (runtime.parent / name).resolve()
        require(path.is_relative_to(runtime.parent) and file_hash(path) == expected, 'recovery_runtime_changed')
        pins.append(path)
    pins.extend(p for folder in ('src', 'tests', 'experiments') for p in (HERE.parent / folder).rglob('*.py'))
    config = Path.home() / '.codex/config.toml'
    if config.exists():
        pins.append(config)
    area.mkdir()
    shutil.copytree(work, area / 'frozen-workspace', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    require(manifest(area / 'frozen-workspace') == current, 'recovery_frozen_copy_changed')
    reg = {'purpose': 'C_interrupted_material_new_requirement_qualification',
        'registered_utc': datetime.now(timezone.utc).isoformat(), 'origin': str(area), 'workspace': str(work),
        'executable': prior_reg['executable'], 'model': MODEL, 'effort': 'max', 'settings': SETTINGS,
        'dynamic_tools': [], 'initial_manifest': current, 'grader': str(grader),
        'stages': STAGES[1:], 'runtime_command': [str(runtime)], 'protected_paths': ['AGENTS.md'],
        'source_recovery': {'phase': str(phase), 'rollout': str(rollout), 'acceptance': str(receipt_path),
                            'original_result': str(source / 'result.json')},
        'pins': {str(p.resolve()): file_hash(p) for p in pins}, 'limits': prior_reg['limits'],
        'candidate': {'selection': 'automatic_word_span_first_checkpoint' if checkpoint_mode == 'generated'
                                  else 'all_message_and_observation_events_v1',
                      'schema': 'enumerated' if checkpoint_mode == 'generated' else None,
                      'checkpoint_mode': checkpoint_mode,
                      'presentation': 'recorded_covered', 'scope_and_phase_observations': True},
        'scope': 'New opaque requirement from preserved interrupted source; original acquisition is not repeated or declared complete.',
        'accounting': 'New generation and continuation costs counted once; historical incomplete usage retained separately, never assumed zero.',
        'stop': 'Any new phase failure, unknown new usage, changed protected file or cap stops later phases. No restart, retry or cap extension.',
        'workspace_lifecycle': 'Same absolute cwd; interrupted bytes remain in the immutable source ZIP and frozen copy. New edits belong to this registration.'}
    save(area / 'registration.json', reg)
    print(__import__('json').dumps({'prepared': str(area), 'model_calls': 0, 'acquisition_repeated': False}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('area', type=Path)
    p.add_argument('--runtime', required=True, type=Path)
    p.add_argument('--checkpoint-mode', choices=['generated', 'messages'], default='generated')
    args = p.parse_args()
    prepare(args.source.resolve(), args.area.resolve(), args.runtime, args.checkpoint_mode)
