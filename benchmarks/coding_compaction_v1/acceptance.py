"""Offline acceptance for the engine side of the thin layer and index v2.

No model, no network, no API key: every check is mechanical over the same
fixture events used by the live evaluation. This is what CI runs.

    python benchmarks/coding_compaction_v1/acceptance.py [--json]

Checks per case:
  discover   the mechanical top-1 index pick leads to the source holding the needle
  retrieve   the cold archive holds every oracle needle
  index      keys sequential and unique, no duplicate fingerprints, user text excluded
  passage    one natural-language paragraph, no JSON slots, index only lists keys
  expiry     a file edit retracts a file-bound verification, not a decision
  state      engine adds missing next-action and version-binding gaps
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]

from coding_compaction_v1 import cases as case_module  # noqa: E402
from coding_compaction_v1 import live  # noqa: E402
from coding_compaction_v1 import resume  # noqa: E402
from coding_compaction_v1 import resume_cases  # noqa: E402
from coding_compaction_v1 import stress  # noqa: E402
from coding_compaction_v1 import stress_cases  # noqa: E402


def _events(case):
    first, second = case['items'], case['round2']['items']
    events1 = live.CodexCheckpointAdapter().import_items(
        first, thread_id=case['case'], observed_at=live.observed_at(0, len(first)))
    events2 = live.CodexCheckpointAdapter().import_items(
        second, thread_id=case['case'], start_ordinal=len(first),
        observed_at=live.observed_at(len(first), len(second)))
    return events1, events1 + events2


def _archive_text(archive):
    return '\n'.join(item['text'] for item in archive)


def _edit_path(case):
    for item in case['items'] + case['round2']['items']:
        if item.get('type') == 'function_call' and item.get('name') == 'edit':
            return json.loads(item['arguments'])['file_path']
    raise AssertionError('case has no edit call')


def _check_selection(failures):
    """Cites alone must reproduce the evidence selection, with control first."""
    items = [
        {'type': 'message', 'role': 'user'},
        {'type': 'message', 'role': 'assistant'},
        {'type': 'function_call', 'call_id': 'c1', 'name': 'edit'},
        {'type': 'function_call_output', 'call_id': 'c1', 'output': 'ok'},
        {'type': 'message', 'role': 'assistant'},
    ]
    ids = [f's{index}' for index in range(len(items))]
    entries = [
        live.Understanding(text='a fact', kind='fact', sources=('s4',)),
        live.Understanding(text='a requirement', kind='requirement', sources=('s1',)),
        live.Understanding(text='a decision about the edit', kind='decision', sources=('s2',)),
    ]
    chosen = live.cited_indices(entries, items, ids, control=[0])
    if chosen[0] != 0:
        failures.append('control message was not kept ahead of cited sources')
    if {2, 3} - set(chosen):
        failures.append('a cited call did not drag its result into the selection')
    if chosen.index(4) < chosen.index(1):
        failures.append('a fact source was ordered ahead of a requirement source')
    stray = live.Understanding(text='unmatched', kind='constraint', sources=('missing',))
    if live.cited_indices([stray], items, ids) != []:
        failures.append('an unknown source id entered the selection')


def check_case(case):
    events1, events_all = _events(case)
    index1 = live.index_from_events(events1)
    index_all = live.index_from_events(events_all)
    archive1 = live.archive_from_events(events1)
    archive_all = live.archive_from_events(events_all)
    failures = []
    results = {}
    _check_selection(failures)

    first = live.evidence_scores(case, 1, index1, _archive_text(archive1))
    second = live.evidence_scores(case, 2, index_all, _archive_text(archive_all))
    results.update({'discover_r1': first['discover'], 'discover_r2': second['discover'],
                    'retrieve_r1': first['retrieve'], 'retrieve_r2': second['retrieve']})
    for name, row in (('round 1', first), ('round 2', second)):
        for metric in ('discover', 'retrieve'):
            if row[metric] < 1.0:
                failures.append(f'{name} {metric} {row[metric]} < 1.00')

    for name, index in (('r1', index1), ('all', index_all)):
        keys = [row['key'] for row in index]
        if keys != [f'E{number}' for number in range(1, len(index) + 1)]:
            failures.append(f'{name} index keys are not sequential E1..En: {keys}')
        if len({row['source_id'] for row in index}) != len(index):
            failures.append(f'{name} index repeats a source id')
        fingerprints = [(row['kind'], row['label'][:60], tuple(row['terms'][:3])) for row in index]
        if len(set(fingerprints)) != len(fingerprints):
            failures.append(f'{name} index repeats a fingerprint')
        if len(index) > 20:
            failures.append(f'{name} index has {len(index)} rows > 20')
    if sum(row['kind'] == 'output' and case_module.REPEATED in row['text'] for row in index_all) > 1:
        failures.append('repeated burst keeps more than one index slot')
    indexed = {row['source_id'] for row in index_all}
    expected_dropped = sum(1 for event in events_all
                           if (event.text or '').strip() and event.id not in indexed
                           and not (event.kind == 'message' and event.role == 'user'))
    if live.archived_without_slot(events_all, index_all) != expected_dropped:
        failures.append('archived_without_slot disagrees with the index')
    if any(event.kind == 'message' and event.role == 'user' and event.id in indexed
           for event in events_all):
        failures.append('user requirements leaked into the evidence index')
    results['index_rows'] = len(index_all)

    entries = [
        {'id': 't1', 'rev': 1, 'ref': 't1@1', 'kind': 'constraint', 'seq': 0, 'status': 'active',
         'text': 'must keep the public install() signature unchanged'},
        {'id': 't2', 'rev': 1, 'ref': 't2@1', 'kind': 'decision', 'seq': 1, 'status': 'active',
         'text': 'decided to use an identity lease'},
        {'id': 't6', 'rev': 1, 'ref': 't6@1', 'kind': 'decision', 'seq': 2, 'status': 'active',
         'text': 'decided to use an identity lease'},
    ]
    state = live.thin_state({'state': {'done': [], 'open': ['finish the rename'], 'next': [],
                                       'unknown': []}}, [], [])
    passage = live.passage_text(['Requirement: quote me'], entries, state,
                                [{'path': 'src/x.py', 'edit': 3, 'check': 5,
                                  'command': 'node --test', 'result': 'PASS ok', 'stale': False}],
                                index_all[:4], 32768, dropped=2)
    results['passage_bytes'] = len(passage.encode())
    for needle in ('Requirement: quote me', 'Constraint:', 'Decision:', 'open: finish the rename',
                   'next action not recorded', '[E1]', 'archived without an index slot',
                   'src/x.py was edited at #3', 'the check at #5', 'node --test', 'PASS ok'):
        if needle not in passage:
            failures.append(f'passage misses {needle!r}')
    if '"Requirement: quote me"' not in passage:
        failures.append('control quote was not verbatim')
    for entry in entries:
        if entry['text'].rstrip('.') not in passage:
            failures.append(f"passage dropped ledger text {entry['ref']}")
    if '{"entries"' in passage or '"kind"' in passage:
        failures.append('passage leaked model JSON slots')
    if passage.count('decided to use an identity lease') != 1:
        failures.append('passage repeats an identical active entry')
    trimmed = live.passage_text([], [dict(entry) for entry in entries], None, [],
                                [{'key': f'E{n}', 'label': 'note filler', 'terms': [],
                                  'text': 'x', 'source_id': f's{n}', 'message': n}
                                 for n in range(1, 21)], 260)
    if len(trimmed.encode()) > 260:
        failures.append(f'budget trim exceeded: {len(trimmed.encode())} > 260')
    if 'Constraint:' not in trimmed and 'Decision:' not in trimmed:
        failures.append('budget trim removed the whole ledger')

    path = _edit_path(case)
    bound = live.thin_entry({'kind': 'verification', 'text': f'V1 checked before the edit to {path}'},
                            entry_id='t3', seq=0)
    decision = live.thin_entry({'kind': 'decision', 'text': f'decided to edit {path} once'},
                               entry_id='t4', seq=0)
    live.thin_expire([bound, decision], events1, base=0)
    if bound['status'] != 'invalidated':
        failures.append('file-bound verification survived an edit to its file')
    if decision['status'] != 'active':
        failures.append('decision was retracted by a path mention alone')
    historical = live.thin_entry({'kind': 'verification', 'text': 'V4 checked before the edit'},
                                 entry_id='t5', seq=len(events1) - 1)
    live.thin_expire([historical], events1, base=1)
    if historical['status'] != 'invalidated':
        failures.append('a later round kept a before-the-edit verification current')

    gaps = live.thin_state({'state': {'done': [], 'open': ['ship it'], 'next': [], 'unknown': []}},
                           [], [])
    if 'next action not recorded for the open item' not in gaps['unknown']:
        failures.append('state did not record the missing next action')
    unbound = live.thin_state({}, [], [{'kind': 'verification', 'status': 'active',
                                        'text': 'tests passed'}])
    if not any('not version-bound' in row for row in unbound['unknown']):
        failures.append('state did not flag an unversioned verification')

    source = live.CodexCheckpointAdapter().import_items(
        [case_module._call('z1', 'edit', {'file_path': path, 'new_string': 'PASS value 4096'})],
        thread_id='repair')
    entry = live.thin_entry({'kind': 'decision', 'text': 'decided to change the file'},
                            entry_id='t7', seq=0)
    repairs = live.repair_identifiers([entry], source)
    if not repairs or 'PASS' not in entry['text'] or '4096' not in entry['text']:
        failures.append('source literals were not copied into the entry')
    if 'file_path' in entry['text']:
        failures.append('repair copied a JSON key instead of a value')
    if live.repair_identifiers([entry], source):
        failures.append('repair is not idempotent')
    junk = live.terms_of('python -m unittest tests.test_resource_io\\"}","n')
    if any(any(char in term for char in '"\\{}[]') for term in junk):
        failures.append('term extraction kept encoded JSON punctuation')

    invalid = live.thin_entry({'kind': 'verification',
                               'text': f'V4 checked after the edit to {path}'},
                              entry_id='t8', seq=0, status='invalidated')
    work = {'control': [], 'rounds': {1: {'entries': [invalid],
            'state': {'done': ['V4 checked after the edit'], 'open': [], 'next': [],
                      'unknown': ['V4 was retracted by the later edit']},
            'archive': [], 'index': [], 'dropped': 0}}, 'receipts': {1: []}}
    text = live.thin_render(work, 1, 32768)
    if 'V4 checked' in text or 'V4 was retracted' not in text:
        failures.append('invalidated version phrase was not filtered from state')

    entries = []
    next_id = live.thin_apply(entries, {'entries': [{'kind': 'constraint', 'text': 'keep A'}]},
                              case['items'], base=0, next_id=1)
    live.thin_apply(entries, {'replaces': [{'ref': 't1@1', 'kind': 'constraint', 'text': 'keep B'}]},
                    case['round2']['items'], base=len(case['items']), next_id=next_id)
    current = [entry['text'] for entry in entries if entry['status'] == 'active']
    if current != ['keep B'] or next_id != 2:
        failures.append(f'revision chain wrong: current={current} next_id={next_id}')

    return {'case': case['case'], 'failures': failures, **results}


def _long(name):
    return next(factory() for factory in resume_cases.LONG_CASES
                if factory()['case'] == name)


def check_state():
    """WSC/lean state projection: relations, payload, coverage and authority."""
    failures = []
    adapter = live.CodexCheckpointAdapter()

    def events_of(case):
        return adapter.import_items([item for delta in case['rounds'] for item in delta],
                                    thread_id=case['case'])

    case = _long('reversed-late')
    events = events_of(case)
    ids = [event.id for event in events]
    entries = [{'kind': 'requirement', 'text': 'src/exporter.py export must be async now.',
                'status': 'active', 'sources': (ids[13],), 'seq': 13}]
    receipts = live.receipts_from_events(events)
    state = live.engine_state(entries, events, receipts)
    if not any('round 6 change' in row for row in state['open']):
        failures.append('state did not expose the placeholder edit payload')
    if state['done']:
        failures.append('state marked an unimplemented requirement done')
    if not any('synthetic' in row for row in state['unknown']):
        failures.append('state did not mark the synthetic check')
    if not any('next action not recorded' in row for row in state['unknown']):
        failures.append('state did not record the missing next action')
    if len(live.recent_receipts(receipts)) != 1:
        failures.append('recent receipts did not collapse to one per path')

    case = _long('long-hidden')
    events = events_of(case)
    ids = [event.id for event in events]
    entries = [
        {'kind': 'requirement', 'text': 'Finish the share-route policy in src/share.py; '
                                       'use the exact historical token, do not guess.',
         'status': 'active', 'sources': (ids[0],), 'seq': 0},
        {'kind': 'fact', 'text': 'The historical policy token from tests.test_share is SHARE-9.',
         'status': 'active', 'sources': (ids[4],), 'seq': 4},
        {'kind': 'fact', 'text': 'src/share.py edit at m36 set new_string to "round 6 change", '
                                 'not SHARE-9.',
         'status': 'active', 'sources': (ids[35],), 'seq': 35},
    ]
    state = live.engine_state(entries, events, live.receipts_from_events(events))
    index = live.index_from_events(events)
    if not any('round 6 change' in row for row in state['open']):
        failures.append('long-hidden state did not expose the placeholder edit')
    if state['done']:
        failures.append('negated fact turned a placeholder edit into done')
    if not any('SHARE-9' in column for row in index for column in
               [row.get('label', ''), *row.get('terms', [])]):
        failures.append('SHARE-9 was not discoverable in the evidence index')

    case = _long('assistant-next')
    events = events_of(case)
    ids = [event.id for event in events]
    items = [{'type': 'message', 'role': 'user',
              'content': [{'type': 'input_text',
                           'text': 'Requirement: rename the flag to FEATURE_X in src/flags.py.'}]},
             case_module._call('e1', 'edit', {'file_path': 'src/flags.py',
                                               'old_string': 'FEATURE_OLD',
                                               'new_string': 'FEATURE_X'}),
             case_module._output('e1', 'ok'),
             case_module._call('e2', 'edit', {'file_path': 'src/flags.py',
                                               'new_string': 'round 9 change'}),
             case_module._output('e2', 'ok')]
    earlier_events = adapter.import_items(items, thread_id='state-earlier')
    rename = {'kind': 'requirement', 'text': 'Rename the flag to FEATURE_X in src/flags.py.',
              'status': 'active', 'sources': (earlier_events[0].id,), 'seq': 0}
    state = live.engine_state([rename], earlier_events,
                              live.receipts_from_events(earlier_events))
    if not any('earlier edit' in row for row in state['unknown']):
        failures.append('state did not record the overwritten earlier edit')

    rename = {'kind': 'requirement', 'text': 'Rename the feature flag to FEATURE_X in src/flags.py.',
              'status': 'active', 'sources': (ids[0],), 'seq': 0}
    entries = [rename,
               {'kind': 'fact', 'text': 'Pending: append release marker REL-9482 to docs/relnotes.md.',
                'status': 'active', 'sources': (ids[3],), 'seq': 3}]
    state = live.engine_state(entries, events, live.receipts_from_events(events))
    if any('REL-9482' in row for row in state['open']):
        failures.append('the recorded next action was duplicated into open')
    if not any('assistant-originated' in row for row in state['next']):
        failures.append('assistant-originated next action was not marked')
    if not any('src/flags.py' in row for row in state['unknown']):
        failures.append('state dropped a real gap on another file')

    message = {'type': 'message', 'role': 'user',
               'content': [{'type': 'input_text',
                            'text': 'Requirement: export must be async in src/exporter.py.'}]}
    items = [message,
             case_module._call('z1', 'edit', {'file_path': 'src/exporter.py',
                                               'old_string': 'def export',
                                               'new_string': 'async def export'}),
             case_module._output('z1', 'ok'),
             case_module._call('z2', 'pwsh', {'command': 'node --test tests/'}),
             case_module._output('z2', 'PASS export test')]
    events = adapter.import_items(items, thread_id='state-done')
    entries = [{'kind': 'requirement', 'text': 'export must be async in src/exporter.py.',
                'status': 'active', 'sources': (events[0].id,), 'seq': 0}]
    state = live.engine_state(entries, events, live.receipts_from_events(events))
    if not state['done']:
        failures.append('state did not recognize a matching edit plus check')

    items = [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
              'Requirement: set retries to 5 in src/limiter.py.'}]},
             case_module._call('p1', 'edit', {'file_path': 'src/limiter.py',
                                               'old_string': 'retries = 3',
                                               'new_string': 'retries = 5'}),
             case_module._output('p1', 'ok'),
             case_module._call('p2', 'pwsh', {'command': 'python -m unittest tests.test_limiter'}),
             case_module._output('p2', 'PASS 1 test')]
    events = adapter.import_items(items, thread_id='state-anchor')
    state = live.engine_state([], events, live.receipts_from_events(events))
    if not state['done']:
        failures.append('a plain identifier anchor did not mark the requirement done')
    if not any(row.startswith('req#1') for row in state['done']):
        failures.append('a user requirement was copied into state instead of referenced')

    items = [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
              'Requirement: set retries to 5 in src/limiter.py.'}]},
             case_module._call('x1', 'edit', {'file_path': 'src/limiter.py',
                                               'new_string': 'retries = 5'}),
             case_module._output('x1', 'Error: permission denied')]
    events = adapter.import_items(items, thread_id='state-failed-edit')
    state = live.engine_state([], events, live.receipts_from_events(events))
    if state['done'] or not any('no edit' in row for row in state['open']):
        failures.append('a failed edit was treated as applied')

    items = [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
              'Requirement: rename the flag to FEATURE_X in src/flags.py.'}]},
             case_module._call('n1', 'edit', {'file_path': 'src/flags.py',
                                               'new_string': 'FEATURE_X'}),
             case_module._output('n1', 'ok'),
             {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
              'text': 'Rename done. Next: add FEATURE_X to CHANGELOG.md.'}]}]
    events = adapter.import_items(items, thread_id='state-next')
    state = live.engine_state([], events, live.receipts_from_events(events))
    if not any('CHANGELOG' in row for row in state['next']):
        failures.append('a recorded next action was not projected')

    reverted = items + [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
         'Change: rename the flag to FEATURE_Y in src/flags.py instead of CHANGELOG.md.'}]}]
    events = adapter.import_items(reverted, thread_id='state-stale-next')
    state = live.engine_state([], events, live.receipts_from_events(events))
    if state['next']:
        failures.append('a revoked next action was still recommended')
    if not any('stale' in row for row in state['unknown']):
        failures.append('a revoked next action was not recorded as unknown')

    long_next = resume_cases.recorded_next_long_case()
    events = adapter.import_items([item for delta in long_next['rounds'] for item in delta],
                                  thread_id='state-next-long')
    state = live.engine_state([], events, live.receipts_from_events(events))
    if not any('CHANGELOG' in row for row in state['next']):
        failures.append('a recorded next action did not survive twenty rounds')

    case = resume_cases.silent_decision_case()
    delta = case['rounds'][1]
    if resume.instruction(delta) or not resume.high_signal(delta):
        failures.append('silent-decision round is not high-signal-only')
    if not resume.should_distil(delta, round_number=2, last_signal=0):
        failures.append('gate did not trigger on a silent decision round')
    if resume.should_distil(delta, round_number=3, last_signal=2):
        failures.append('gate repeated a lingering high-signal round')

    long_case = resume_cases.silent_decision_long_case()
    rounds = long_case['rounds']
    if sum(len(json.dumps(delta)) for delta in rounds) < long_case['threshold_chars']:
        failures.append('long silent case never reaches the compaction threshold')
    if 'send_once' not in resume.signal_hint(rounds[1]):
        failures.append('compaction hint did not name the silent decision')
    events = adapter.import_items([item for delta in rounds for item in delta],
                                  thread_id='silent-long')
    index = live.index_from_events(events)
    decision_ids = {event.id for event in events if event.kind == 'message'
                    and event.role == 'assistant' and 'Decision: use' in (event.text or '')}
    if not decision_ids:
        failures.append('long silent case lost its decision message')
    elif decision_ids & {row['source_id'] for row in index}:
        failures.append('crowding did not push the decision note out of the index')
    return failures


def check_stress():
    """Layered scenarios: tags, oracle, control and mechanical metrics."""
    failures = []
    for config in stress_cases.CONFIGS:
        rounds = 10 if config == 'all' else 6
        case = stress_cases.stress_case(config, rounds)
        markers = [row['marker'] for row in case['segments']]
        if len(markers) != len(set(markers)):
            failures.append(f'{config}: marker repeated')
        transcript = json.dumps(case['rounds'])
        for marker in markers:
            if marker not in transcript:
                failures.append(f'{config}: marker {marker} not in transcript')
        if not case['required']:
            failures.append(f'{config}: no required action')
        if config in ('L2', 'L3', 'L4', 'all') and not case['forbidden']:
            failures.append(f'{config}: no forbidden action')
        if config == 'all' and (len(case['rounds']) != 10
                                or set(case['layers']) != {'L1', 'L2', 'L3', 'L4'}):
            failures.append('all-on case does not cover ten rounds and four layers')
        control = stress.control_state(case)
        for marker in markers:
            if marker not in control['presented']:
                failures.append(f'{config}: control dropped {marker}')
    case = stress_cases.stress_case('all', 10)
    control = stress.control_state(case)
    facts = ' '.join(stress_cases.FACTS.values())
    good = {'actions': [{'tool': 'edit', 'file': stress_cases.NOTE,
                         'content': facts + ' docs/internal/runbook.md'}]}
    row = stress.evaluate(case, control['presented'], good, None)
    if not row['success'] or row['violations'] or len(row['stale_used']):
        failures.append('stress good actions were not scored as clean')
    bad = {'actions': [{'tool': 'edit', 'file': stress_cases.NOTE,
                        'content': 'LIM4 KEY8 SLA4 TTL6 ZON5 OWN3 VER2 STL8'}]}
    row = stress.evaluate(case, control['presented'], bad, None)
    if row['success'] or not row['stale_used']:
        failures.append('stress stale/contradictory use was not detected')
    govern = {'actions': [{'tool': 'run', 'command': 'delete rows'}]}
    row = stress.evaluate(case, 'GOV1 GOV2 GOV3', govern, None)
    if not row['violations']:
        failures.append('stress governance violation was not detected')

    # A gated arm only calls the model on rounds with a user instruction of
    # their own. Every required value read in a skipped round must therefore be
    # carried by the engine's own value ledger or index, or the gate loses it.
    events = live.CodexCheckpointAdapter().import_items(
        [item for delta in case['rounds'] for item in delta], thread_id='stress-index')
    index = live.index_from_events(events)
    values = live.value_rows_from_events(events)
    if [row['key'] for row in values] != [f'V{n}' for n in range(1, len(values) + 1)]:
        failures.append('value keys are not sequential V1..Vn')
    if len({row['source_id'] for row in values}) != len(values):
        failures.append('value ledger repeats a source id')
    navigation = [row for row in index if row['kind'] != 'value']
    discoverable = ' '.join(f"{row['label']} {' '.join(row['terms'])}"
                            for row in navigation + values)
    for marker in [*stress_cases.FACTS.values(), *stress_cases.GOVERN.values()]:
        if marker not in discoverable:
            failures.append(f'value ledger does not expose required value {marker}')
    for event in events:
        if event.kind == 'message' and event.role == 'user' and \
                event.id in {row['source_id'] for row in index + values}:
            failures.append('a user requirement leaked into the evidence index')
    triggers = [number for number, delta in enumerate(case['rounds'], 1)
                if resume.needs_distillation(delta)]
    if len(triggers) >= len(case['rounds']):
        failures.append('the distillation gate never skips a round')
    for number, delta in enumerate(case['rounds'], 1):
        if number in triggers:
            continue
        for item in delta:
            text = json.dumps(item)
            for marker in [*stress_cases.FACTS.values(), *stress_cases.GOVERN.values()]:
                if marker in text and marker not in discoverable:
                    failures.append(f'round {number} fact {marker} lost with the gate')

    # Budget overflow keeps every archived value addressable by its key.
    full = live.passage_text([], [], None, [], [], 32768, values=values)
    cut = live.passage_text([], [], None, [], [], max(300, len(full.encode()) - 150),
                            values=values)
    if 'Observed values' not in cut:
        failures.append('value section vanished under the budget')
    for row in values:
        if row['key'] not in cut:
            failures.append(f'archived value key {row["key"]} is not addressable')

    # The engine sink hides only facts that restate an engine value.
    entries = [
        {'kind': 'fact', 'text': 'src/limits.py: region code = RGN7'},
        {'kind': 'fact', 'text': 'owner code = OWN3'},
        {'kind': 'decision', 'text': 'decision: write docs/deploy-note.md (single target)'},
        {'kind': 'fact', 'text': 'retries = 7'},
    ]
    shown = [entry['text'] for entry in live.merge_engine_values(entries, values)]
    if any(text in shown for text in ('src/limits.py: region code = RGN7', 'owner code = OWN3')):
        failures.append('ledger presentation restated an engine value')
    if 'decision: write docs/deploy-note.md (single target)' not in shown \
            or 'retries = 7' not in shown:
        failures.append('engine dedupe removed a non-duplicate entry')
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    reports = [check_case(factory()) for factory in case_module.CASES]
    state_failures = check_state()
    stress_failures = check_stress()
    failed = [report for report in reports if report['failures']]
    if args.json:
        print(json.dumps({'ok': not failed and not state_failures and not stress_failures,
                          'reports': reports, 'state_failures': state_failures,
                          'stress_failures': stress_failures},
                         ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(f"{report['case']:<22} rows={report['index_rows']:<3} "
                  f"discover {report['discover_r1']:.2f}/{report['discover_r2']:.2f}  "
                  f"retrieve {report['retrieve_r1']:.2f}/{report['retrieve_r2']:.2f}  "
                  f"passage {report['passage_bytes']}B  "
                  f"{'ok' if not report['failures'] else 'FAIL'}")
            for failure in report['failures']:
                print('  -', failure)
        print(f"state projection{' ' * 5}{'ok' if not state_failures else 'FAIL'}")
        for failure in state_failures:
            print('  -', failure)
        print(f"stress scenarios{' ' * 4}{'ok' if not stress_failures else 'FAIL'}")
        for failure in stress_failures:
            print('  -', failure)
    return 1 if failed or state_failures or stress_failures else 0


if __name__ == '__main__':
    sys.exit(main())
