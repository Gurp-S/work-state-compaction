"""Run a sealed fixture through two real DSH headless profiles."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from uuid import uuid4

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
J = ROOT / 'dsh-wsc'
WORKSPACE_CANDIDATE = HERE / 'continuity-candidate-plugin-v8'
READ_RECEIPT_CANDIDATE = HERE / 'continuity-candidate-plugin-v9'
SELECTOR_OFF_CANDIDATE = HERE / 'continuity-candidate-plugin-v11'
STATE_SOURCE_CANDIDATE = HERE / 'continuity-candidate-plugin-v15'
WORK_STATE_CANDIDATE = HERE / 'state-ledger-plugin-v1'
NODE = Path('E:/nodejs/node.exe')
CLI = Path('E:/nodejs/node_modules/@deepseek-ai/dsh/lib/bin.js')
HOME = Path.home() / '.dsh'
BASE_HOME = HOME
STAGE = HERE / 'host-pair'
SOURCE = J / 'experiments'
HASH = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def save(path, data):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def wsc_candidate(spec):
    return (WORK_STATE_CANDIDATE if spec.get('work_state_ledger') else
            STATE_SOURCE_CANDIDATE if spec.get('state_source_candidate') else
            SELECTOR_OFF_CANDIDATE if spec.get('selection_reasoning_off') else
            READ_RECEIPT_CANDIDATE if spec.get('dedupe_read_receipts') else
            WORKSPACE_CANDIDATE if spec.get('workspace_observations') else J)


def setup(*, prune=False, fixture='constraint', scoped_state=False, dedupe_carried_state=False,
          workspace_observations=False, dedupe_read_receipts=False, selection_reasoning_off=False,
          state_source_candidate=False, work_state_ledger=False):
    STAGE.mkdir(exist_ok=False)
    if HOME != BASE_HOME:
        (HOME / 'profiles').mkdir(parents=True)
        patch_path = BASE_HOME / 'cordis.patch.yml'
        if patch_path.is_file():
            shutil.copyfile(patch_path, HOME / patch_path.name)
    temp = STAGE / 'work' if HOME != BASE_HOME else Path(tempfile.mkdtemp(prefix='codex-wsc-host-'))
    temp.mkdir(exist_ok=True)
    nonce = uuid4().hex[:7]
    result = {}
    for arm in ('native', 'wsc'):
        old = BASE_HOME / 'profiles' / ('ab-a' if arm == 'native' else 'ab-b')
        name = f'ab-goal-{nonce}-{arm}'
        profile = HOME / 'profiles' / name
        profile.mkdir()
        shutil.copyfile(old / 'cordis.yml', profile / 'cordis.yml')
        package = json.loads((old / 'package.json').read_bytes())
        package['name'] = name
        if arm == 'wsc':
            plugin = wsc_candidate({'work_state_ledger': work_state_ledger,
                                    'state_source_candidate': state_source_candidate,
                                    'selection_reasoning_off': selection_reasoning_off,
                                    'dedupe_read_receipts': dedupe_read_receipts,
                                    'workspace_observations': workspace_observations})
            snapshot = profile / 'node_modules/@xeyo/dsh-wsc'
            snapshot.mkdir(parents=True)
            runtime = [p for p in plugin.iterdir() if p.name in
                       ('index.js', 'engine.js', 'client.js', 'package.json', 'cordis.patch.yml', 'icon.svg')]
            runtime += [plugin / 'lib', plugin / 'locale']
            for p in runtime:
                if p.is_dir():
                    shutil.copytree(p, snapshot / p.name)
                else:
                    shutil.copyfile(p, snapshot / p.name)
            package['dependencies']['@xeyo/dsh-wsc'] = '0.1.0'
            for p in [plugin / 'index.js', plugin / 'engine.js', *(plugin / 'lib').glob('*.js')]:
                assert HASH(p) == HASH(snapshot / p.relative_to(plugin))
        save(profile / 'package.json', package)
        patch = yaml.safe_load((old / 'cordis.patch.yml').read_text(encoding='utf-8'))
        patch = [row for row in patch if not any(x.get('id') == 'wsc-probe' for x in row.get('insert', []))]
        for row in patch:
            if row.get('id') == 'agent-default-model':
                row['config']['reasoningEffort'] = 'low'
            if row.get('id') == 'llm-pi-ai':
                model = row['config']['providers']['wd']['models'][0]
                # No truncation budget for a normal agent response: 32768 gives 4x the
                # original 8192 headroom. MUST stay < contextWindow (65536): WSC's engine
                # computes usable = contextWindow - maxTokens and disables its compaction
                # trigger entirely when maxTokens >= contextWindow (usable <= 0). 32768
                # keeps usable=32768>24000 so WSC's capacity monitor still fires.
                model['maxTokens'] = 32768
                # YAML turns the boolean `false` key into the string "false";
                # the provider schema only accepts false or named efforts.
                efforts = model.get('reasoningEfforts')
                if isinstance(efforts, dict):
                    efforts.pop(False, None)
                    efforts.pop('false', None)
                if selection_reasoning_off or work_state_ledger:
                    efforts['off'] = None
                    row['config']['providers']['wd'].setdefault('compat', {})['thinkingFormat'] = 'deepseek'
            if row.get('id') == 'compaction-basic' and arm == 'native':
                row['config'].update(thresholdRatio=20400 / 65536, retainRatio=3840 / 65536,
                                     maxTokens=4096)
            if row.get('id') == 'wsc-config':
                row['config'].update(warnRatio=0.8, forceRatio=0.85, continuityReceipts=True,
                                     selectionAddress='lines', selectionMaxTokens=4096, payloadToolText=1,
                                     payloadPriorEchoDepth=1, selectionMinTokens=4000)
                if work_state_ledger:
                    row['config'].update(selection='state-ledger', continuityReceipts=False)
                if prune:
                    row['config']['pruneBeforeCheckpoint'] = True
                if scoped_state:
                    row['config']['stateSelectionContext'] = True
                if dedupe_carried_state:
                    row['config']['dedupeCarriedState'] = True
                if workspace_observations:
                    row['config']['workspaceObservations'] = True
                if dedupe_read_receipts:
                    row['config']['dedupeReadReceipts'] = True
                if selection_reasoning_off:
                    row['config']['selectionReasoningEffort'] = 'off'
        (profile / 'cordis.patch.yml').write_text(yaml.safe_dump(patch, sort_keys=False), encoding='utf-8')
        work = temp / (name + '-task')
        shutil.copytree(SOURCE / f'fixture-{fixture}', work)
        fixture_seals = {str(p.relative_to(work)): HASH(p) for p in work.rglob('*') if p.is_file()}
        result[arm] = {'profile': name, 'profile_dir': str(profile), 'work': str(work),
                       'workspace_observations': workspace_observations and arm == 'wsc',
                       'dedupe_read_receipts': dedupe_read_receipts and arm == 'wsc',
                       'selection_reasoning_off': selection_reasoning_off and arm == 'wsc',
                       'state_source_candidate': state_source_candidate and arm == 'wsc',
                       'work_state_ledger': work_state_ledger and arm == 'wsc',
                       'patch_sha256': HASH(profile / 'cordis.patch.yml'),
                       'prune_experiment': prune and arm == 'wsc', 'fixture': fixture,
                       'scoped_state': scoped_state and arm == 'wsc', 'fixture_seals': fixture_seals,
                       'dedupe_carried_state': dedupe_carried_state and arm == 'wsc',
                       'selection_min_tokens': 4000 if arm == 'wsc' else None,
                       'prompt_sha256': HASH(SOURCE / f'PROMPT-{fixture}.md'),
                       'grader_sha256': HASH(SOURCE / 'hidden' / f'{fixture}.test.mjs')}
    if selection_reasoning_off or work_state_ledger:
        shared = []
        for spec in result.values():
            patch = yaml.safe_load((Path(spec['profile_dir']) / 'cordis.patch.yml').read_bytes())
            shared.append({row['id']: row['config'] for row in patch
                           if row.get('id') in ('agent-default-model', 'llm-pi-ai')})
        if shared[0] != shared[1] or len(shared[0]) != 2:
            raise RuntimeError('paired host model settings differ')
    save(STAGE / 'setup.json', result)
    return result


def cmd(spec):
    return [str(NODE), '--import', (HERE / 'host-resolve.mjs').as_uri(), str(CLI), '--profile', spec['profile']]


def host_env(*, paid=False):
    env = {**os.environ, 'DSH_HOME': str(HOME)}
    if paid and HOME != BASE_HOME and not env.get('WD_API_KEY'):
        key = env.get('CSM_BENCH_API_KEY')
        if not key:
            config = BASE_HOME / '.credentials.yaml'
            key = yaml.safe_load(config.read_text(encoding='utf-8'))['refs']['WD_API_KEY']
        env['WD_API_KEY'] = key
    return env


def verify_wsc_snapshot(spec):
    snapshot = Path(spec['profile_dir']) / 'node_modules/@xeyo/dsh-wsc'
    def inventory(root):
        top = ('index.js', 'engine.js', 'client.js', 'package.json', 'cordis.patch.yml', 'icon.svg')
        files = [root / name for name in top if (root / name).is_file()]
        files.extend(path for directory in ('lib', 'locale')
                     for path in (root / directory).rglob('*') if path.is_file())
        return {path.relative_to(root).as_posix(): HASH(path) for path in files}

    plugin = wsc_candidate(spec)
    current, installed = inventory(plugin), inventory(snapshot)
    for relative in sorted(current.keys() | installed.keys()):
        if current.get(relative) != installed.get(relative):
            raise RuntimeError(f'Stale WSC host snapshot: {relative}')
    sealed = spec.get('plugin_runtime_sha256')
    if sealed is not None and installed != sealed:
        raise RuntimeError('Prepared WSC plugin runtime changed')
    return installed


def preflight(specs, pending=None):
    specs['wsc']['plugin_runtime_sha256'] = verify_wsc_snapshot(specs['wsc'])
    for arm, spec in specs.items():
        assert HASH(Path(spec['profile_dir']) / 'cordis.patch.yml') == spec['patch_sha256']
        if pending is not None and arm not in pending:
            continue
        runtime_seals = {name: HASH(path) for name, path in (
            ('node', NODE), ('host_entry', CLI), ('resolver', HERE / 'host-resolve.mjs'),
            ('base_profile', Path(spec['profile_dir']) / 'cordis.yml'))}
        if spec.get('runtime_seals', runtime_seals) != runtime_seals:
            raise RuntimeError(f'{arm}: prepared host runtime changed')
        spec['runtime_seals'] = runtime_seals
        if 'fixture_seals' in spec:
            work = Path(spec['work'])
            assert {str(p.relative_to(work)): HASH(p) for p in work.rglob('*') if p.is_file()} == spec['fixture_seals']
            fixture = spec['fixture']
            assert HASH(SOURCE / f'PROMPT-{fixture}.md') == spec['prompt_sha256']
            assert HASH(SOURCE / 'hidden' / f'{fixture}.test.mjs') == spec['grader_sha256']
        reply = subprocess.run(cmd(spec) + ['--help'], cwd=spec['work'], capture_output=True, timeout=30, env=host_env())
        assert reply.returncode == 0 and b'Answer one task' in reply.stdout, reply.stderr.decode('utf-8', 'replace')
        dump = subprocess.run(cmd(spec) + ['--dump-config'], cwd=spec['work'], capture_output=True, timeout=30, env=host_env())
        assert dump.returncode == 0
        spec['config_dump_sha256'] = hashlib.sha256(dump.stdout).hexdigest()
        if arm == 'wsc':
            assert b'wsc-engine' in dump.stdout
            if spec.get('work_state_ledger'):
                assert b'selection: state-ledger' in dump.stdout and b'continuityReceipts: false' in dump.stdout
            else:
                assert b'continuityReceipts: true' in dump.stdout
            if spec.get('selection_min_tokens') is not None:
                assert f"selectionMinTokens: {spec['selection_min_tokens']}".encode() in dump.stdout
            if spec.get('selection_reasoning_off'):
                assert b'selectionReasoningEffort: off' in dump.stdout or b"selectionReasoningEffort: 'off'" in dump.stdout
            if spec.get('prune_experiment'):
                assert b'pruneBeforeCheckpoint: true' in dump.stdout
                assert b'tool-result-pruner' in dump.stdout
            if spec.get('scoped_state'):
                assert b'stateSelectionContext: true' in dump.stdout
            if spec.get('dedupe_carried_state'):
                assert b'dedupeCarriedState: true' in dump.stdout
            if spec.get('workspace_observations'):
                assert b'workspaceObservations: true' in dump.stdout
            if spec.get('dedupe_read_receipts'):
                assert b'dedupeReadReceipts: true' in dump.stdout and b'spill-local' in dump.stdout
        else:
            assert b'wsc-engine' not in dump.stdout and b'compaction-basic' in dump.stdout
    save(STAGE / 'setup.json', specs)


def check_receipt(stage, arm, spec):
    path = stage / f'{arm}-result.json'
    if not path.is_file():
        if (stage / f'{arm}-process.json').exists():
            raise RuntimeError(f'{arm}: started arm has no terminal receipt')
        return None
    receipt = json.loads(path.read_bytes())
    for key in ('profile', 'patch_sha256', 'work', 'fixture_seals', 'grader_sha256', 'prompt_sha256', 'runtime_seals'):
        if receipt.get(key) != spec.get(key):
            raise RuntimeError(f'{arm}: terminal receipt does not match prepared arm')
    if receipt.get('plugin_runtime_sha256') != spec.get('plugin_runtime_sha256'):
        raise RuntimeError(f'{arm}: terminal receipt plugin runtime seal mismatch')
    if receipt.get('log_sha256') != HASH(stage / f'{arm}.log'):
        raise RuntimeError(f'{arm}: terminal host log seal mismatch')
    if len(receipt['session_logs']) == 1 and receipt.get('session_sha256') != HASH(Path(receipt['session_logs'][0])):
        raise RuntimeError(f'{arm}: terminal session archive seal mismatch')
    return receipt


def is_complete(receipt):
    return receipt['exit_code'] == 0 and not receipt['timed_out'] and len(receipt['session_logs']) == 1


def unfinished_arms(specs):
    pending = []
    for arm, spec in specs.items():
        receipt = check_receipt(STAGE, arm, spec)
        if receipt is None:
            pending.append(arm)
            continue
        if not is_complete(receipt) and not model_limit_terminal(arm, receipt):
            raise RuntimeError(f'{arm}: terminal receipt is an incomplete comparison arm')
    return pending


def model_limit_terminal(arm, receipt):
    if receipt['timed_out'] or len(receipt['session_logs']) != 1:
        return False
    audit = STAGE / f'verified-usage-{arm}.json'
    if not audit.is_file():
        return False
    observed = json.loads(audit.read_bytes())[arm]
    return (observed['session_sha256'] == receipt['session_sha256'] and observed['exit_code'] == receipt['exit_code']
            and observed['turn_end'][-1:]
            and observed['turn_end'][-1]['reason']['kind'] == 'max-tokens')


def reuse_completed(source, specs, selected_arms=None):
    old_specs = json.loads((source / 'setup.json').read_bytes())
    reusable = {}
    for arm, spec in specs.items():
        if selected_arms is not None and arm not in selected_arms:
            continue
        old = old_specs[arm]
        receipt = check_receipt(source, arm, old)
        if receipt is None or not is_complete(receipt):
            continue
        keys = ('patch_sha256', 'fixture_seals', 'grader_sha256', 'prompt_sha256', 'runtime_seals')
        if any(key not in old or key not in spec or old[key] != spec[key] for key in keys):
            raise RuntimeError(f'{arm}: completed comparison arm used different inputs')
        old_profile, new_profile = (Path(config['profile_dir']) for config in (old, spec))
        if HASH(old_profile / 'cordis.yml') != HASH(new_profile / 'cordis.yml'):
            raise RuntimeError(f'{arm}: completed comparison arm used a different base profile')
        if arm == 'wsc':
            verify_wsc_snapshot(old)
        reusable[arm] = (old, receipt)
    for arm, (old, receipt) in reusable.items():
        shutil.copyfile(source / f'{arm}.log', STAGE / f'{arm}.log')
        save(STAGE / f'{arm}-result.json', receipt)
        specs[arm] = old
    save(STAGE / 'setup.json', specs)


def run(arm, spec):
    out = STAGE / (arm + '.log')
    started = time.time()
    fixture = spec.get('fixture', 'constraint')
    with out.open('wb') as stream:
        proc = subprocess.Popen(cmd(spec) + [(SOURCE / f'PROMPT-{fixture}.md').read_text(encoding='utf-8')],
                                cwd=spec['work'], stdout=stream, stderr=subprocess.STDOUT, env=host_env(paid=True))
        save(STAGE / (arm + '-process.json'), {'pid': proc.pid, 'started': started, **spec})
        try:
            code = proc.wait(timeout=1200)
            timed_out = False
        except subprocess.TimeoutExpired:
            proc.terminate()
            code = proc.wait(timeout=15)
            timed_out = True
    result = subprocess.run([str(NODE), str(SOURCE / 'score.mjs'), spec['work'],
                             str(SOURCE / 'hidden' / f'{fixture}.test.mjs')], capture_output=True, timeout=90)
    candidates = [p for d in (HOME / 'sessions').glob('*' + Path(spec['work']).name + '*')
                  for p in d.glob('**/session.jsonl.zstd')]
    record = {'exit_code': code, 'timed_out': timed_out, 'seconds': time.time() - started,
              'score': json.loads(result.stdout), 'session_logs': [str(p) for p in candidates],
              'session_sha256': HASH(candidates[0]) if len(candidates) == 1 else None,
              'log_sha256': HASH(out), **spec}
    save(STAGE / (arm + '-result.json'), record)
    print(arm, code, record['score']['passed'], '/', record['score']['total'], flush=True)
    return code == 0 and not timed_out and len(candidates) == 1


def run_prepared(serial):
    lock = sqlite3.connect(STAGE / 'host-writer.sqlite3', timeout=0)
    try:
        lock.execute('BEGIN EXCLUSIVE')
        specs = json.loads((STAGE / 'setup.json').read_bytes())
        pending = unfinished_arms(specs)
        preflight(specs, pending)
        schedule_path = STAGE / 'schedule.json'
        schedule = {'mode': 'serial' if serial else 'parallel', 'arms': list(specs)}
        if schedule_path.exists():
            if json.loads(schedule_path.read_bytes()) != schedule:
                raise RuntimeError('host comparison schedule changed')
        else:
            save(schedule_path, schedule)
        if serial:
            for arm in pending:
                if not run(arm, specs[arm]):
                    return False
            return True
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(run, arm, specs[arm]) for arm in pending]
            return all([task.result() for task in tasks])
    finally:
        lock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'preflight', 'run'))
    parser.add_argument('--stage', default='host-pair')
    parser.add_argument('--prune', action='store_true')
    parser.add_argument('--scoped-state', action='store_true')
    parser.add_argument('--dedupe-carried-state', action='store_true')
    parser.add_argument('--workspace-observations', action='store_true')
    parser.add_argument('--dedupe-read-receipts', action='store_true')
    parser.add_argument('--selection-reasoning-off', action='store_true')
    parser.add_argument('--state-source-candidate', action='store_true')
    parser.add_argument('--work-state-ledger', action='store_true')
    parser.add_argument('--reuse-from', help='Reuse complete sealed arms from an earlier matching stage')
    parser.add_argument('--reuse-arm', choices=('native', 'wsc'), action='append')
    parser.add_argument('--fixture', choices=('constraint', 'hard', 'mega'), default='constraint')
    parser.add_argument('--serial', action='store_true')
    parser.add_argument('--isolated-home', action='store_true')
    args = parser.parse_args()
    if args.work_state_ledger and (args.mode != 'prepare' or not args.isolated_home):
        parser.error('--work-state-ledger requires prepare and --isolated-home')
    if (args.workspace_observations or args.dedupe_read_receipts or args.selection_reasoning_off) and (args.mode != 'prepare' or not args.isolated_home):
        parser.error('candidate flags require prepare and --isolated-home')
    if args.selection_reasoning_off and args.reuse_from:
        parser.error('selector-off staging requires fresh matched host arms')
    if args.state_source_candidate and not args.selection_reasoning_off:
        parser.error('--state-source-candidate requires --selection-reasoning-off')
    if not re.fullmatch(r'host-pair(?:-[a-z0-9-]+)?', args.stage):
        parser.error('stage must be host-pair or host-pair-<name>')
    STAGE = HERE / args.stage
    if args.isolated_home:
        HOME = STAGE / 'dsh-home'
        if args.mode != 'prepare' and not HOME.is_dir():
            parser.error('isolated home missing')
    if args.reuse_from and (args.mode != 'prepare' or args.reuse_from == args.stage or
                            not re.fullmatch(r'host-pair(?:-[a-z0-9-]+)?', args.reuse_from)):
        parser.error('--reuse-from requires prepare and a different host-pair stage')
    if args.reuse_arm and not args.reuse_from:
        parser.error('--reuse-arm requires --reuse-from')
    mode = args.mode
    if mode in ('prepare', 'preflight'):
        specs = (setup(prune=args.prune, fixture=args.fixture, scoped_state=args.scoped_state,
                       dedupe_carried_state=args.dedupe_carried_state,
                       workspace_observations=args.workspace_observations,
                       dedupe_read_receipts=args.dedupe_read_receipts,
                       selection_reasoning_off=args.selection_reasoning_off,
                       state_source_candidate=args.state_source_candidate,
                       work_state_ledger=args.work_state_ledger)
                 if mode == 'prepare' else json.loads((STAGE / 'setup.json').read_bytes()))
        preflight(specs)
        if args.reuse_from:
            reuse_completed(HERE / args.reuse_from, specs, args.reuse_arm)
        print('Both real host profiles passed preflight', flush=True)
    else:
        raise SystemExit(0 if run_prepared(args.serial) else 1)
