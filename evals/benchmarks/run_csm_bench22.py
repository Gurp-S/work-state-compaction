"""Run the pinned public Bench 2.2 harness with the CSM source adapter."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / '.bench/chat-memory-benchmark-2.2/benchmark-2.2'
STAGE = ROOT / '.local/bench22-public-20261111'
RELEASE = STAGE / 'dataset'
PORT = 18892
RUN = 'csm-public-first'
SYSTEM = 'csm-source'
sys.path[:0] = [str(UPSTREAM / 'harness'), str(ROOT / 'src')]


def prepare_release():
    shutil.copytree(UPSTREAM / 'dataset', RELEASE)
    manifest = json.loads((RELEASE / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = RELEASE / name
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() == expected:
            continue
        # Match the release's declared bytes when Git normalized line endings.
        crlf = content.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        if hashlib.sha256(crlf).hexdigest() != expected:
            raise ValueError(f'release_hash_mismatch: {name}')
        path.write_bytes(crlf)
        print('Restored manifest line endings:', name, flush=True)


def serve():
    import yaml
    from bench22 import gateway

    key = os.environ.get('CSM_BENCH_API_KEY')
    if not key:
        path = Path.home() / '.dsh' / '.credentials.yaml'
        key = yaml.safe_load(path.read_text(encoding='utf-8'))['refs']['WD_API_KEY']
    gateway.State.keys['deepseek'] = key
    gateway.DEEPSEEK_URL = 'http://127.0.0.1:8788/v1/chat/completions'
    post = gateway._post
    from threading import Lock

    maximum = os.environ.get('CSM_BENCH_MAX_UPSTREAM')
    remaining = int(maximum) if maximum is not None else None
    admission = Lock()

    def forward(url, body, provider, extra_headers=None, timeout=90, retries=2):
        nonlocal remaining
        if provider != 'deepseek' or url != gateway.DEEPSEEK_URL:
            raise RuntimeError('local_public_run_upstream_not_configured')
        if remaining is not None:
            with admission:
                if remaining <= 0:
                    raise RuntimeError('public_evaluation_upstream_limit')
                remaining -= 1
            retries = 1
        response = post(url, dict(body, _wb_strict_chat_contract=True), provider,
                        extra_headers, timeout=timeout, retries=retries)
        if response.get('model') != body['model'] or not response.get('usage'):
            raise RuntimeError('upstream_model_or_usage_missing')
        return response

    gateway._post = forward
    ledger = STAGE / 'runs/bench22/spend-ledger.jsonl'
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.touch(exist_ok=True)
    # The natural summary reads the same ledger at its historical subpath.
    (ledger.parent / 'natural').mkdir(exist_ok=True)
    gateway.serve(PORT, str(ledger), str(ledger.parent / 'gateway-cache.sqlite3'), 50 / gateway.USD_CNY)


def run_harness(stage, workers, run, produce_state, separate_producer_budget=False, raw_memory=False,
                *, source_state_guards=False, narrow_source_checks=False, write_revisions=False,
                batch_revisions=False):
    from bench22 import natural, runner, systems
    from csm_bench22 import CsmBench22
    from csm_bench22_run_seal import seal_run

    seal = seal_run(root=ROOT, release=RELEASE, harness=UPSTREAM / 'harness',
                    out=STAGE / 'runs/bench22', run=run, system=SYSTEM,
                    state_producer=produce_state, separate_producer_budget=separate_producer_budget,
                    answer_model=runner.ANSWER_MODEL,
                    judge_model=runner.JUDGE_MODEL, raw_memory=raw_memory, source_state_guards=source_state_guards,
                    narrow_source_checks=narrow_source_checks, write_revisions=write_revisions,
                    batch_revisions=batch_revisions)
    if stage == 'seal':
        print(f"Sealed {run}: {len(seal['code_sha256'])} source files", flush=True)
        return
    boundaries = None
    if batch_revisions:
        from functools import partial
        from csm_bench22_batch_revision import BatchRevisionBench22
        from csm_bench22_batch_runner import run_batch_persona, public_boundaries
        boundaries = public_boundaries(RELEASE)
        systems.REGISTRY[SYSTEM] = BatchRevisionBench22
        runner.run_persona = partial(run_batch_persona, boundaries=boundaries)
    elif write_revisions:
        from csm_bench22_flat_revision import FlatRevisionBench22
        systems.REGISTRY[SYSTEM] = FlatRevisionBench22
    elif raw_memory:
        from csm_bench22_raw_memory import RawMemoryBench22
        systems.REGISTRY[SYSTEM] = lambda gateway: RawMemoryBench22(revision_state=True)
    else:
        systems.REGISTRY[SYSTEM] = lambda gateway: CsmBench22(
            gateway, produce_state=produce_state, separate_producer_budget=separate_producer_budget,
            validate_conflict_sources=source_state_guards or narrow_source_checks,
            scope_producer_source=source_state_guards,
            scope_numeric_state=source_state_guards or narrow_source_checks)
    runner.ROOT = natural.ROOT = str(STAGE)
    common = ['--release', str(RELEASE), '--system', SYSTEM, '--split', 'dev',
              '--run', run, '--gateway', f'http://127.0.0.1:{PORT}/v1', '--workers', str(workers)]
    if stage == 'contexts':
        from types import SimpleNamespace

        histories = runner.load_histories(str(RELEASE))
        splits = {row['id']: row['split'] for row in runner.jl(str(RELEASE / 'review-only/answer-key.jsonl'))}
        items = [item for item in runner.load_items(str(RELEASE), with_key=False)
                 if splits[item['id']] == 'dev']
        out = STAGE / 'runs/bench22' / run / SYSTEM / 'dev'
        out.mkdir(parents=True, exist_ok=True)
        for persona in sorted({item['persona'] for item in items}):
            leaked = runner.run_persona(SimpleNamespace(system=SYSTEM, split='dev'), str(RELEASE),
                                        histories, persona, items, str(out), SimpleNamespace(), None)
            if leaked:
                raise ValueError(f'context_source_outside_cutoff: {leaked}')
        print(f'Prepared {len(items)} direct public contexts', flush=True)
        return
    if stage in ('exam', 'sentinel', 'pilot'):
        extra = {'exam': [], 'sentinel': ['--sentinel'], 'pilot': ['--sample', '2']}[stage]
        sys.argv[1:] = common + extra
        runner.main()
        return
    if stage == 'natural-sentinel':
        probes, _ = natural.load_natural(str(RELEASE / 'natural'), 'dev')
        items = [{'id': p['id'], 'persona': p['persona'], 'cutoff_turn': p['cutoff_turn'],
                  'kind': 'main', 'question': p['probe']['user'], 'now': p['probe']['time']}
                 for p in probes if p['tier'] == 'A']
        out = STAGE / 'runs/bench22' / run / SYSTEM / 'natural-sentinel'
        out.mkdir(parents=True, exist_ok=True)
        args = argparse.Namespace(system=SYSTEM, sentinel_n=12, seed=20261109,
                                  leaky=False, gateway=f'http://127.0.0.1:{PORT}/v1', run=run)
        runner.run_sentinel(args, items, runner.load_histories(str(RELEASE)), str(out), None)
        return
    if stage == 'run':
        from csm_bench22_natural_resume import run_natural

        seal = {**seal, 'model': natural.ANSWER_MODEL}
        run_natural(release=RELEASE, outdir=STAGE / 'runs/bench22' / run / SYSTEM / 'natural-dev',
                    run=run, system_name=SYSTEM, gateway_url=f'http://127.0.0.1:{PORT}/v1',
                    workers=workers, system_factory=systems.REGISTRY[SYSTEM], seal=seal,
                    boundaries=boundaries)
        return
    if stage == 'summarize':
        ledger = STAGE / 'runs/bench22/spend-ledger.jsonl'
        shutil.copyfile(ledger, ledger.parent / 'natural/spend-ledger.jsonl')
    sys.argv[1:] = [stage] + common + ['--natural', str(RELEASE / 'natural')]
    natural.main()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'gateway', 'seal', 'contexts', 'exam', 'sentinel', 'pilot',
                                         'natural-sentinel', 'run', 'judge', 'confirm', 'summarize'))
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--run', default=RUN)
    parser.add_argument('--state-producer', action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument('--separate-producer-budget', action='store_true')
    parser.add_argument('--raw-memory', action='store_true')
    parser.add_argument('--write-revisions', action='store_true')
    parser.add_argument('--batch-revisions', action='store_true')
    source_checks = parser.add_mutually_exclusive_group()
    source_checks.add_argument('--source-state-guards', action='store_true')
    source_checks.add_argument('--narrow-source-checks', action='store_true')
    args = parser.parse_args()
    args.write_revisions |= args.batch_revisions
    if args.write_revisions and (args.raw_memory or args.state_producer or args.stage == 'contexts'):
        parser.error('--write-revisions requires a gateway evaluation without legacy state production')
    if args.separate_producer_budget and not args.state_producer:
        parser.error('--separate-producer-budget requires --state-producer')
    if args.source_state_guards and not args.state_producer:
        parser.error('--source-state-guards requires --state-producer')
    if args.narrow_source_checks and not args.state_producer:
        parser.error('--narrow-source-checks requires --state-producer')
    if args.raw_memory and args.state_producer:
        parser.error('--raw-memory requires the state producer to be disabled')
    if args.stage == 'contexts' and args.state_producer:
        parser.error('contexts requires the state producer to be disabled')
    if args.stage == 'prepare':
        prepare_release()
    elif args.stage == 'gateway':
        serve()
    else:
        run_harness(args.stage, args.workers, args.run, args.state_producer, args.separate_producer_budget,
                    args.raw_memory, source_state_guards=args.source_state_guards,
                    narrow_source_checks=args.narrow_source_checks, write_revisions=args.write_revisions,
                    batch_revisions=args.batch_revisions)
