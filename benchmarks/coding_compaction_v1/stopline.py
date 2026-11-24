"""Executable stop-line for the compaction layer (see docs/optimization-stop-line.md).

Fails when a change adds a mechanism the stop line forbids: a new top-level
module, a reintroduced removed API, more than one model call per compression
(thin, WSC or WSC-lean), or an unbounded engine pass. Fast, offline, no key.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]

from coding_compaction_v1 import cases as case_module  # noqa: E402
from coding_compaction_v1 import live  # noqa: E402

ALLOWED_MODULES = {
    '__init__', '__main__', 'accounting', 'audit_cache', 'bound_windows_io', 'cli',
    'command_process_tree', 'context_projection', 'context_query',
    'context_query_coordinates', 'context_references', 'context_runtime',
    'continuation_inspection', 'contracts', 'control_grading', 'control_sources',
    'coding_ledger', 'core', 'distillation_gate', 'durable_ops', 'events',
    'evidence', 'excerpts', 'generation',
    'generation_api', 'generation_boundary', 'integrity', 'material_v2',
    'observation_coverage', 'passage', 'plugin', 'projection', 'publication',
    'query_ledger', 'recorded_understandings', 'redaction', 'references',
    'resource_io', 'resume_contract', 'selection_effects', 'selection_transport',
    'settlement',
    'snapshot_literal_access', 'snapshots', 'source_access', 'source_reference_view',
    'state_delta', 'state_view', 'store', 'understanding', 'understanding_identity',
    'view_budget',
}

REMOVED_APIS = ('include_selection_facts', 'publication_policy', 'bounded_catalog',
                'prefix_index', 'write_back', 'state_writeback', 'blob_gc',
                'content_archive', 'generation_frontier', 'bounded_generation')

CALLS_PER_ROUND = 1
AUDIT_BUDGET_SECONDS = 1.5


class CountingModel:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def chat(self, messages, max_tokens=4096, label=''):
        self.calls += 1
        return {'text': self.reply, 'usage': {}, 'finish': 'stop'}


class FakeEvent:
    def __init__(self, text):
        self.text = text


def check_module_surface():
    present = {path.stem for path in (ROOT / 'src' / 'wsc').glob('*.py')}
    added = sorted(present - ALLOWED_MODULES)
    return [f'new top-level module requires stop-line review: {name}' for name in added]


def check_removed_apis():
    failures = []
    for path in (ROOT / 'src' / 'wsc').rglob('*.py'):
        text = path.read_text(encoding='utf-8', errors='ignore')
        for name in REMOVED_APIS:
            if name in text:
                failures.append(f'{path.relative_to(ROOT)} reintroduces removed API {name}')
    return failures


def check_call_budget():
    reply = json.dumps({
        'entries': [{'kind': 'constraint', 'text': 'keep A'}],
        'state': {'done': [], 'open': [], 'next': [], 'unknown': []}})
    failures = []
    allowed = 2 * CALLS_PER_ROUND
    model = CountingModel(reply)
    live.thin_model_work(model, case_module.lease_identity_case())
    if model.calls > allowed:
        failures.append(f'thin layer made {model.calls} model calls for 2 rounds (cap {allowed})')
    with ThreadPoolExecutor(max_workers=2) as pool:
        for name, work in (('wsc', live.wsc_model_work), ('wsc_lean', live.wsc_lean_model_work)):
            model = CountingModel(reply)
            work(model, case_module.lease_identity_case(), pool)
            if model.calls > allowed:
                failures.append(f'{name} made {model.calls} model calls for 2 rounds (cap {allowed})')
    return failures


def check_audit_bound():
    events = [FakeEvent(('keep src/wsc/resource_io.py PASS 4096 marker ' * 60)[:2000])
              for _ in range(2000)]
    entries = [{'id': f't{n}', 'ref': f't{n}@1', 'kind': 'decision', 'status': 'active',
                'seq': 32 + n * 30, 'text': 'decided to keep the file signature stable'}
               for n in range(60)]
    started = time.perf_counter()
    live.anchor_facts(entries, events)
    elapsed = time.perf_counter() - started
    print(f"  anchor pass {elapsed * 1000:.1f}ms over 2000 events x 60 entries")
    failures = [] if elapsed <= AUDIT_BUDGET_SECONDS else \
        [f'anchor pass took {elapsed:.2f}s over 2000 events (budget {AUDIT_BUDGET_SECONDS}s)']
    far = [{'id': 't0', 'ref': 't0@1', 'kind': 'decision', 'status': 'active', 'seq': 1000,
            'text': 'decided to keep the PREFIXMARK signature stable'}]
    near = [FakeEvent('unrelated text') for _ in range(2000)]
    near[0] = FakeEvent('PREFIXMARK appears only at the start')
    facts = live.anchor_facts(far, near)
    if facts['t0@1']['message'] == 1:
        failures.append('anchor pass ignored its window and scanned the whole transcript')
    return failures


def main():
    failures = []
    for check in (check_module_surface, check_removed_apis, check_call_budget, check_audit_bound):
        found = check()
        failures += found
        print(f"{check.__name__:<24} {'ok' if not found else 'FAIL'}")
        for failure in found:
            print('  -', failure)
    print('\nstop line', 'satisfied' if not failures else f'violated ({len(failures)})')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
