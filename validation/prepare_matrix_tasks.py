"""Prepare selected matrix task fixtures; only known calibration code is executed."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'benchmarks'))
from acceptance_matrix_v1.acceptors import accept_t1, accept_t3, load_candidate
from acceptance_matrix_v1.task_specs import ROOT as SUITE, SPECS, build_task
from acceptance_matrix_v1.evidence import seal
from acceptance_matrix_v1.acceptor_t2 import accept_t2, COMPILER
from acceptance_matrix_v1.acceptor_t5 import accept_t5
from acceptance_matrix_v1.acceptor_t4 import accept_t4

TASKS = {'T1': (accept_t1, 'retry_reference.py'), 'T2': (accept_t2, 't2_api'),
         'T3': (accept_t3, 'migration_reference.py'), 'T4': (accept_t4, 't4_ui'),
         'T5': (accept_t5, 'pipeline_reference.py')}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def smoke(work, path, task):
    if task == 'T4':
        outcome = accept_t4(work, screenshot=path.with_suffix('.png'), smoke=True)
        save(path, outcome)
        return dict(kind='chromium_public_interaction_smoke', exit_code=0 if outcome['success'] else 1,
                    log_sha256=sha256(path.read_bytes()).hexdigest(), browser=outcome['browser'])
    command = [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', '.', '-p', 'test_smoke.py', '-v']
    kind = 'python_public_smoke'
    if task == 'T2':
        command = [shutil.which('node'), str(COMPILER), '--strict', '--skipLibCheck', '--noEmit',
                   '--target', 'ES2020', '--module', 'commonjs', '--lib', 'ES2020,DOM',
                   *[str(p) for p in sorted(work.glob('*.ts'))]]
        kind = 'typescript_public_compile_smoke'
    outcome = subprocess.run(command, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    path.write_bytes(outcome.stdout)
    return dict(kind=kind, argv=command, exit_code=outcome.returncode, log_sha256=sha256(outcome.stdout).hexdigest())


def main(default_tasks=('T1', 'T2', 'T3', 'T4', 'T5')):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--noise', type=int, default=20)
    parser.add_argument('--tasks', nargs='+', choices=TASKS, default=default_tasks)
    args = parser.parse_args()
    if len(set(args.tasks)) != len(args.tasks):
        parser.error('duplicate tasks')
    args.out.mkdir(parents=True, exist_ok=False)
    summaries = []
    for identity in args.tasks:
        acceptor, reference = TASKS[identity]
        spec = SPECS[identity]
        folder = args.out/identity
        folder.mkdir()
        starter = folder/'public-starter'
        shutil.copytree(SUITE/'tasks'/spec['folder']/'starter', starter)
        private = folder/'coordinator-private'
        private.mkdir()
        reference_work = private/'reference-smoke'
        shutil.copytree(starter, reference_work)
        source = SUITE/'calibration'/reference
        if source.is_dir():
            for candidate in source.iterdir():
                shutil.copyfile(candidate, reference_work/candidate.name)
        else:
            shutil.copyfile(source, reference_work/spec['entry'])
        before_smoke = smoke(starter, folder/'public-smoke-before.txt', identity)
        after_smoke = smoke(reference_work, private/'reference-smoke-after.txt', identity)
        before = acceptor(starter if identity in ('T2', 'T4') else load_candidate(starter/spec['entry']))
        after = acceptor(reference_work if identity in ('T2', 'T4') else load_candidate(reference_work/spec['entry']))
        save(private/'starter-acceptance.json', before)
        save(private/'reference-acceptance.json', after)
        if before_smoke['exit_code'] == 0 or after_smoke['exit_code'] != 0 or before['success'] or not after['success']:
            raise ValueError('task_calibration_failed:'+identity)
        rendered_log = (folder/'public-smoke-before.txt').read_text(encoding='utf-8').replace(str(starter.resolve()), '$TASK_STARTER')
        screenshot = None
        if identity == 'T4':
            image = folder/'public-smoke-before.png'
            shutil.copyfile(image, starter/'baseline.png')
            screenshot = dict(sha256=sha256(image.read_bytes()).hexdigest(), width=1024, height=720,
                              capture='Actual Chromium public starter rendering, not a model-generated image')
        public, oracle = build_task(identity, public_failure_log=rendered_log, noise=args.noise, screenshot=screenshot)
        # No private oracle/reference path appears in the public corpus.
        if str(private.resolve()) in json.dumps(public, ensure_ascii=False):
            raise ValueError('private_path_in_public_fixture')
        save(folder/'history.public.json', public)
        save(private/'oracle.json', oracle)
        summary = dict(task=identity, public_sha256=seal(public), starter_smoke=before_smoke,
            reference_smoke=after_smoke, programmatic_checks=len(after['checks']),
            starter_checks_failed=sum(not r['passed'] for r in before['checks']),
            starter_runtime_checks_not_run=before.get('runtime_checks_not_run', 0),
            reference_all_passed=after['success'], history_dependency_model_control_run=False,
            real_agent_qualified=False, native_source_pair_import_verified=False,
            model_oracle_filesystem_isolation_verified=False,
            files={p.relative_to(folder).as_posix(): sha256(p.read_bytes()).hexdigest()
                   for p in folder.rglob('*') if p.is_file()})
        save(folder/'fixture-manifest.json', summary)
        summaries.append(summary)
    save(args.out/'summary.json', dict(status='calibrated_fixture_drafts', tasks=summaries,
        model_inference_calls=0, paid_runs=0, all_five_tasks_ready=False,
        scope='Known starter/reference code only. No model-dependent history qualification or native run.'))
    print(json.dumps([dict(task=r['task'], checks=r['programmatic_checks'],
                          starter_failed=r['starter_checks_failed'], reference_passed=r['reference_all_passed'])
                      for r in summaries], ensure_ascii=False))


if __name__ == '__main__':
    main()
