"""Hard scenarios for resumed-behavior scoring.

Each case ends with a state whose correct next action is defined by the oracle,
not by what any checkpoint happens to say. The four families exercise:
pending check after an edit, a reversed requirement, an assistant-recorded next
step, and an exact value that only the cold store holds.
"""
from __future__ import annotations

import json


def _call(call_id, name, args):
    return {'type': 'function_call', 'call_id': call_id, 'name': name,
            'arguments': json.dumps(args)}


def _output(call_id, text):
    return {'type': 'function_call_output', 'call_id': call_id, 'output': text}


def _burst(call_id, units=14):
    return [_call(call_id, 'pwsh', {'command': 'node --test tests/'}),
            _output(call_id, '\n'.join(['PASS synthetic suite row'] * units))]


def pending_check_case():
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: set retries to 5 in src/limiter.py, then verify with '
            'python -m unittest tests.test_limiter.'}]},
        _call('r1', 'read', {'file_path': 'src/limiter.py'}),
        _output('r1', 'retries = 3'),
        _call('t1', 'pwsh', {'command': 'node --test tests/'}),
        _output('t1', 'PASS old suite\nok 3 passed in 0.42s'),
        _call('e1', 'edit', {'file_path': 'src/limiter.py', 'old_string': 'retries = 3',
                             'new_string': 'retries = 5'}),
        _output('e1', 'ok'),
        *_burst('b1', 18),
    ]
    round2 = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Continue. Verification must match the current edit.'}]},
        *_burst('b2', 20),
    ]
    return {'case': 'pending-check', 'items': items, 'round2': {'items': round2},
            'required': [{'tool': 'run', 'command': 'python -m unittest tests.test_limiter'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/limiter.py'}],
            'files': {'src/limiter.py': 'retries = 5\n'},
            'secret': None}


def reversed_requirement_case():
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: keep export synchronous in src/exporter.py.'}]},
        _call('e1', 'edit', {'file_path': 'src/exporter.py', 'old_string': 'async def export',
                             'new_string': 'def export'}),
        _output('e1', 'ok'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Export is now synchronous, as required.'}]},
        *_burst('b1', 16),
    ]
    round2 = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Change: export must be async now. Apply it in src/exporter.py.'}]},
        *_burst('b2', 20),
    ]
    return {'case': 'reversed-requirement', 'items': items, 'round2': {'items': round2},
            'required': [{'tool': 'edit', 'file': 'src/exporter.py', 'content': 'async def export'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/exporter.py', 'content': 'def export(',
                           'unless': 'async def export'}],
            'files': {'src/exporter.py': 'def export(data):\n    return core.send(data)\n'},
            'secret': None}


def recorded_next_step_case():
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: rename the feature flag to FEATURE_X in src/flags.py.'}]},
        _call('e1', 'edit', {'file_path': 'src/flags.py', 'old_string': 'FEATURE_OLD',
                             'new_string': 'FEATURE_X'}),
        _output('e1', 'ok'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Rename done. Next: add FEATURE_X to CHANGELOG.md under Unreleased.'}]},
        *_burst('b1', 18),
    ]
    round2 = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Continue.'}]},
        *_burst('b2', 22),
    ]
    return {'case': 'recorded-next-step', 'items': items, 'round2': {'items': round2},
            'required': [{'tool': 'edit', 'file': 'CHANGELOG.md', 'content': 'FEATURE_X'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/flags.py'}],
            'files': {'CHANGELOG.md': '# Changelog\n\n## Unreleased\n\n- baseline entry\n'},
            'secret': None}


def stale_next_case():
    """A recorded next action is revoked by a later user change."""
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: rename the feature flag to FEATURE_X in src/flags.py.'}]},
        _call('e1', 'edit', {'file_path': 'src/flags.py', 'old_string': 'FEATURE_OLD',
                             'new_string': 'FEATURE_X'}),
        _output('e1', 'ok'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Rename done. Next: add FEATURE_X to CHANGELOG.md under Unreleased.'}]},
        *_burst('b1', 16),
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Change: rename the flag to FEATURE_Y in src/flags.py instead of CHANGELOG.md.'}]},
    ]
    round2 = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Continue.'}]},
        *_burst('b2', 18),
    ]
    return {'case': 'stale-next', 'items': items, 'round2': {'items': round2},
            'required': [{'tool': 'edit', 'file': 'src/flags.py', 'content': 'FEATURE_Y'}],
            'forbidden': [{'tool': 'edit', 'file': 'CHANGELOG.md'},
                          {'tool': 'edit', 'file': 'src/flags.py', 'content': 'FEATURE_X'}],
            'files': {'src/flags.py': 'FEATURE_OLD = "FEATURE_OLD"\n',
                      'CHANGELOG.md': '# Changelog\n\n## Unreleased\n\n- baseline entry\n'},
            'secret': None}


def hidden_value_case():
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: finish the share-route policy in src/share.py; use the exact '
            'historical token, do not guess.'}]},
        _call('r1', 'read', {'file_path': 'src/share.py'}),
        _output('r1', 'def share(route):\n    token = None'),
        _call('m1', 'read', {'file_path': 'docs/policy-notes.md'}),
        _output('m1', 'internal notes\npolicy_data = {"token": "SHARE-9", "scope": "/s/<id>"}\n'
                      + '\n'.join('policy row kept for the share route' for _ in range(12))),
        *_burst('b1', 18),
    ]
    round2 = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Continue the share-route work.'}]},
        *_burst('b2', 22),
    ]
    return {'case': 'hidden-value', 'items': items, 'round2': {'items': round2},
            'required': [{'tool': 'edit', 'file': 'src/share.py', 'content': 'SHARE-9'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/share.py', 'content': 'token = None',
                           'unless': 'SHARE-9'}],
            'files': {'src/share.py': 'def share(route):\n    token = None\n'},
            'secret': 'SHARE-9'}


def _noise_delta(number, path, units=16):
    """One compaction round of unrelated work plus near-duplicate distractor results."""
    return [
        _call(f'e{number}', 'edit', {'file_path': path, 'new_string': f'round {number} change'}),
        _output(f'e{number}', 'ok'),
        _call(f't{number}', 'pwsh', {'command': f'node --test tests/test_{number}.py'}),
        _output(f't{number}', f'PASS row {number}\nok 3 passed in 0.42s'),
        _call(f'u{number}', 'pwsh', {'command': 'node --test tests/'}),
        _output(f'u{number}', '\n'.join(f'PASS synthetic suite row {number}-{i}' for i in range(units))),
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Continue.'}]},
    ]


def long_hidden_case():
    """The token source is far back; five noise rounds push it out of the tail."""
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: finish the share-route policy in src/share.py; use the exact '
            'historical token from the test output, do not guess.'}]},
        _call('r1', 'read', {'file_path': 'src/share.py'}),
        _output('r1', 'def share(route):\n    token = None'),
        _call('t1', 'pwsh', {'command': 'python -m unittest tests.test_share'}),
        _output('t1', 'PASS tests.test_share\npolicy token: SHARE-9\nok 1 passed in 0.31s'),
        *_burst('b1', 18),
    ]
    rounds = [items] + [_noise_delta(number, 'src/share.py') for number in (2, 3, 4, 5, 6)]
    return {'case': 'long-hidden', 'items': items, 'round2': {'items': rounds[1]},
            'rounds': rounds,
            'required': [{'tool': 'edit', 'file': 'src/share.py', 'content': 'SHARE-9'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/share.py', 'content': 'token = None',
                           'unless': 'SHARE-9'}],
            'files': {'src/share.py': 'def share(route):\n    token = None\n'},
            'secret': 'SHARE-9'}


def assistant_next_case():
    """Only an assistant message records an unguessable next step; five rounds never restate it."""
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: rename the feature flag to FEATURE_X in src/flags.py.'}]},
        _call('e1', 'edit', {'file_path': 'src/flags.py', 'old_string': 'FEATURE_OLD',
                             'new_string': 'FEATURE_X'}),
        _output('e1', 'ok'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Rename done. Next: append release marker REL-9482 to docs/relnotes.md.'}]},
        *_burst('b1', 18),
    ]
    rounds = [items] + [_noise_delta(number, 'src/flags.py') for number in (2, 3, 4, 5, 6)]
    return {'case': 'assistant-next', 'items': items, 'round2': {'items': rounds[1]},
            'rounds': rounds,
            'required': [{'tool': 'edit', 'file': 'docs/relnotes.md', 'content': 'REL-9482'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/flags.py'}],
            'files': {'docs/relnotes.md': '# Release notes\n\n## Upcoming\n\n- baseline entry\n'},
            'secret': None}


def reversed_late_case():
    """A requirement is reversed in round 3, then four rounds never restate it."""
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: keep export synchronous in src/exporter.py.'}]},
        _call('e1', 'edit', {'file_path': 'src/exporter.py', 'old_string': 'async def export',
                             'new_string': 'def export'}),
        _output('e1', 'ok'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Export is synchronous now.'}]},
        *_burst('b1', 16),
    ]
    change = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Change: export must be async now. Apply it in src/exporter.py.'}]},
        *_burst('c3', 14),
    ]
    rounds = [items, _noise_delta(2, 'src/exporter.py'), change]
    rounds += [_noise_delta(number, 'src/exporter.py') for number in (4, 5, 6)]
    return {'case': 'reversed-late', 'items': items, 'round2': {'items': rounds[1]},
            'rounds': rounds,
            'required': [{'tool': 'edit', 'file': 'src/exporter.py', 'content': 'async def export'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/exporter.py', 'content': 'def export(',
                           'unless': 'async def export'}],
            'files': {'src/exporter.py': 'def export(data):\n    return core.send(data)\n'},
            'secret': None}


def silent_decision_case():
    """A failure and the assistant's decision arrive with no user message.

    Only the high-signal gate can carry the decision into the checkpoint; the
    engine value ledger cannot, because a decision is not an exact literal.
    """
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: make retries use the idempotency key in src/client.py and verify.'}]},
        _call('r1', 'read', {'file_path': 'src/retry.py'}),
        _output('r1', 'def retry(request):\n    return core.send(request)'),
        *_burst('b1', 18),
    ]
    round2 = [
        _call('t1', 'pwsh', {'command': 'python -m unittest tests.test_retry'}),
        _output('t1', 'FAILED tests.test_retry - AssertionError: idempotency key missing'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Root cause is src/retry.py: it bypasses src/client.py. Decision: route '
                    'retries through client.send_once with the idempotency key.'}]},
        *_burst('b2', 20),
    ]
    rounds = [items, round2]
    for number in (3, 4, 5, 6):
        rounds.append([{'type': 'message', 'role': 'user',
                        'content': [{'type': 'input_text', 'text': 'Continue.'}]},
                       *_burst(f'b{number}', 18)])
    return {'case': 'silent-decision', 'items': items, 'round2': {'items': round2},
            'rounds': rounds,
            'required': [{'tool': 'edit', 'file': 'src/retry.py', 'content': 'send_once'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/retry.py',
                           'content': 'core.send(request)', 'unless': 'send_once'},
                          {'tool': 'edit', 'file': 'src/client.py'}],
            'files': {'src/retry.py': 'def retry(request):\n    return core.send(request)\n',
                      'src/client.py': 'def send_once(request, idempotency_key):\n    ...\n'},
            'secret': None}


def _filler(label, width=2200):
    body = (f'background note {label}: the deployment pipeline keeps staging credentials, '
            'rollout notes and historical context in this channel. ')
    return body + ('routine detail without exact values or decisions. ' * (width // 58))


def silent_decision_long_case():
    """A decision arrives without a user message, then twenty rounds bury it.

    Compaction is threshold-triggered, as in dsh. The decision note is crowded
    out of the note index by later rank-1 notes, so only a compaction that keeps
    the high-signal decision in the ledger can carry it to the resume.
    """
    rounds = [[] for _ in range(20)]
    rounds[0] += [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: make retries use the idempotency key via src/client.py; '
            'do not guess which helper to use.'}]},
        *_burst('b0', 18),
    ]
    rounds[1] += [
        _call('t1', 'pwsh', {'command': 'python -m unittest tests.test_retry'}),
        _output('t1', 'FAILED tests.test_retry - AssertionError: idempotency key missing'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Root cause is src/retry.py: it bypasses src/client.py. Decision: use '
                    'client.send_once with the idempotency key; send_batch is for batch jobs only.'}]},
        *_burst('b1', 20),
    ]
    for number in range(2, 19):
        rounds[number] += [
            _call(f'f{number}', 'read', {'file_path': 'docs/background.md'}),
            _output(f'f{number}', _filler(f'f{number}')),
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
                'text': f'verification note {number}: the legacy path check still passes.'}]},
            {'type': 'message', 'role': 'user',
             'content': [{'type': 'input_text', 'text': 'Continue.'}]},
        ]
    rounds[-1] += [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text',
            'text': 'Continue. Finish the retry change now.'}]},
        *_burst('b19', 20),
    ]
    return {'case': 'silent-decision-long', 'items': rounds[0],
            'round2': {'items': rounds[1]}, 'rounds': rounds,
            'threshold_chars': 32000,
            'required': [{'tool': 'edit', 'file': 'src/retry.py', 'content': 'send_once'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/retry.py',
                           'content': 'send_batch', 'unless': 'send_once'},
                          {'tool': 'edit', 'file': 'src/client.py'}],
            'files': {'src/retry.py': 'def retry(request):\n    return core.send(request)\n',
                      'src/client.py': 'def send_once(request, idempotency_key):\n    ...\n'
                                       'def send_batch(request, items):\n    ...\n',
                      'docs/background.md': 'background\n'},
            'secret': None}


def recorded_next_long_case():
    """A recorded next action must survive twenty rounds and threshold compaction."""
    rounds = [[] for _ in range(20)]
    rounds[0] += [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: rename the feature flag to FEATURE_X in src/flags.py.'}]},
        _call('e1', 'edit', {'file_path': 'src/flags.py', 'old_string': 'FEATURE_OLD',
                             'new_string': 'FEATURE_X'}),
        _output('e1', 'ok'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Rename done. Next: add FEATURE_X to CHANGELOG.md under Unreleased.'}]},
        *_burst('b0', 16),
    ]
    for number in range(1, 19):
        rounds[number] += [
            _call(f'f{number}', 'read', {'file_path': 'docs/background.md'}),
            _output(f'f{number}', _filler(f'f{number}')),
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
                'text': f'verification note {number}: the legacy path check still passes.'}]},
            {'type': 'message', 'role': 'user',
             'content': [{'type': 'input_text', 'text': 'Continue.'}]},
        ]
    rounds[-1] += [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text',
            'text': 'Continue. Finish the recorded next step now.'}]},
        *_burst('b19', 18),
    ]
    return {'case': 'recorded-next-long', 'items': rounds[0],
            'round2': {'items': rounds[1]}, 'rounds': rounds,
            'threshold_chars': 32000,
            'required': [{'tool': 'edit', 'file': 'CHANGELOG.md', 'content': 'FEATURE_X'}],
            # Redoing the completed rename is counted as an extra action, not a
            # violation: this case measures whether the recorded next is run.
            'forbidden': [],
            'files': {'CHANGELOG.md': '# Changelog\n\n## Unreleased\n\n- baseline entry\n',
                      # The round-0 edit returned ok, so the file already holds the
                      # renamed flag; a stale fixture would punish verification.
                      'src/flags.py': 'FEATURE_X = "FEATURE_X"\n',
                      'docs/background.md': 'background\n'},
            'secret': None}


def multi_compaction_case():
    """Twenty-four rounds cross several threshold compactions in one session."""
    rounds = [[
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: rename the feature flag to FEATURE_X in src/flags.py.'}]},
        _call('e1', 'edit', {'file_path': 'src/flags.py', 'old_string': 'FEATURE_OLD',
                             'new_string': 'FEATURE_X'}),
        _output('e1', 'ok'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': 'Rename done. Next: append release marker REL-9482 to docs/relnotes.md.'}]},
    ]]
    for number in range(2, 25):
        rounds.append([
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text',
                                                             'text': 'Continue.'}]},
            _call(f'm{number}', 'read', {'file_path': f'docs/note-{number}.md'}),
            _output(f'm{number}', f'note {number}: ' + _filler(f'n{number}')),
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
                'text': f'background note {number}: the legacy path check still passes.'}]},
        ])
    return {'case': 'multi-compaction', 'items': rounds[0],
            'round2': {'items': rounds[1]}, 'rounds': rounds,
            'threshold_chars': 9600,
            'required': [{'tool': 'edit', 'file': 'docs/relnotes.md', 'content': 'REL-9482'}],
            'forbidden': [{'tool': 'edit', 'file': 'src/flags.py'}],
            'files': {'docs/relnotes.md': '# Release notes\n\n## Upcoming\n\n- baseline entry\n',
                      'src/flags.py': 'FEATURE_X = "FEATURE_X"\n'},
            'secret': None}


CASES = (pending_check_case, reversed_requirement_case, recorded_next_step_case,
         stale_next_case, hidden_value_case)
LONG_CASES = (long_hidden_case, assistant_next_case, reversed_late_case, silent_decision_case,
              silent_decision_long_case, recorded_next_long_case, multi_compaction_case)
