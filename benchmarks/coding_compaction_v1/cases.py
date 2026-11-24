"""Authored coding-agent compaction fixtures with a mechanical oracle.

Each case is a long coding session in which a small amount of coder-critical
state (constraints, decisions, paths, errors, code, numbers, repeated details)
is embedded among large distractor bursts. Every case must compress: the runner
refuses a case whose checkpoint is not smaller than its region, so an execution
can never "pass" without a real compression.

The oracle names, for every key fact, where it is expected to survive:
``evidence`` (a selected source message) or ``ledger`` (a distilled entry).
Facts are plain text: quotes and backslashes are avoided so verbatim checks are
not defeated by JSON escaping.
"""
from __future__ import annotations

import json

BURST_UNIT = ('PASS tests/test_lease_identity.py::test_cancel\n'
              'PASS tests/test_reader_reuse.py::test_window\n'
              'PASS tests/test_publication.py::test_receipt\n'
              'ok 3 passed in 0.42s\n'
              '... (noise: repeated runner output retained only for size)')

REPEATED = 'receipt #17 was reissued after the worker restart'


def _call(call_id, name, args):
    return {'type': 'function_call', 'call_id': call_id, 'name': name,
            'arguments': json.dumps(args)}


def _output(call_id, text):
    return {'type': 'function_call_output', 'call_id': call_id, 'output': text}


def _burst(call_id, units=10):
    return [_call(call_id, 'pwsh', {'command': 'node --test tests/'}),
            _output(call_id, '\n'.join([BURST_UNIT] * units))]


def lease_identity_case():
    """Python lease work: identity instead of lock, a lost reply, a hard error."""
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: must keep the public install() signature unchanged, '
            'and never move the working directory during export.'}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'decided to use an identity lease, not a file lock, because Windows cannot set a share mode from Python'}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'The failing path is src/wsc/resource_io.py and the caller stays src/wsc/publication.py'}]},
        _call('c1', 'read', {'file_path': 'src/wsc/resource_io.py'}),
        _output('c1', 'def lease(package):\n    require(os.name == "nt", "installation_resource_lease_unavailable")'),
        *_burst('b1'),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'PermissionError [WinError 5] while renaming .pending-* files in the temp directory'}]},
        *_burst('b2', 12),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'max_open_handles=4096 is the current export handle budget'}]},
        _call('c2', 'edit', {'file_path': 'src/wsc/resource_io.py', 'new_string': 'def lease(package): ...'}),
        _output('c2', 'ok'),
        *_burst('b3', 14),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'receipt #17 was reissued after the worker restart'}]},
        _call('c3', 'pwsh', {'command': 'python -m unittest tests.test_resource_io'}),
        _output('c3', 'FAILED (errors=1)\nPermissionError: [WinError 5]'),
        *_burst('b4', 16),
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: additionally, must keep the reader_reuse_v1 query policy selectable.'}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'Plan: keep reader_reuse_v1 selectable while the lease stays identity-based; receipt #17 is the reissued one'}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'V1 passed tests before the edit'}]},
        *_burst('b5', 18),
    ]
    oracle = {
        'evidence': [
            {'id': 'p1', 'kind': 'path', 'text': 'src/wsc/resource_io.py',
             'needle': 'src/wsc/resource_io.py'},
            {'id': 'p2', 'kind': 'path', 'text': 'src/wsc/publication.py',
             'needle': 'src/wsc/publication.py'},
            {'id': 'e1', 'kind': 'error',
             'text': 'PermissionError [WinError 5] while renaming .pending-* files in the temp directory',
             'needle': 'PermissionError [WinError 5] while renaming'},
            {'id': 'c1', 'kind': 'code', 'text': 'def lease(package):',
             'needle': 'def lease(package):'},
            {'id': 'n1', 'kind': 'number', 'text': 'max_open_handles=4096',
             'needle': 'max_open_handles=4096'},
            {'id': 'r1', 'kind': 'repeated', 'text': REPEATED, 'needle': REPEATED},
        ],
        'ledger': [
            {'id': 'k1', 'kind': 'constraint', 'needle': 'must keep the public install() signature unchanged'},
            {'id': 'k2', 'kind': 'constraint', 'needle': 'never move the working directory during export'},
            {'id': 'k3', 'kind': 'constraint', 'needle': 'must keep the reader_reuse_v1 query policy selectable'},
            {'id': 'd1', 'kind': 'decision', 'needle': 'decided to use an identity lease, not a file lock'},
            {'id': 'v1', 'kind': 'verification', 'needle': 'V1 passed tests before the edit'},
        ],
    }
    for fact in oracle['ledger']:
        fact['text'] = fact['needle']
    distill = [
        {'text': 'must keep the public install() signature unchanged', 'kind': 'constraint'},
        {'text': 'never move the working directory during export', 'kind': 'constraint'},
        {'text': 'decided to use an identity lease, not a file lock', 'kind': 'decision'},
        {'text': 'must keep the reader_reuse_v1 query policy selectable', 'kind': 'constraint'},
        {'text': 'V1 passed tests before the edit', 'kind': 'verification',
         'invalid_when': {'file_changed': 'src/wsc/resource_io.py'}},
    ]
    probes = [
        {'question': 'Which install constraint survived?', 'expects': ['k1', 'k2']},
        {'question': 'Why identity instead of a lock?', 'expects': ['d1']},
        {'question': 'Which error blocks the rename?', 'expects': ['e1']},
        {'question': 'Is the verification current at this point?', 'expects': ['v1']},
    ]
    round2 = {
        'items': [
            _call('c4', 'edit', {'file_path': 'src/wsc/resource_io.py', 'new_string': 'x'}),
            _output('c4', 'ok'),
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
                'V2 checked after edit'}]},
            *_burst('b6', 22),
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
                'Requirement: must keep export synchronous when the target volume is local.'}]},
        ],
        'distill': [
            {'text': 'must keep export synchronous when the target volume is local.', 'kind': 'constraint'},
        ],
        'oracle': {
            'evidence': [
                {'id': 'v2', 'kind': 'verification', 'text': 'V2 checked after edit',
                 'needle': 'V2 checked after edit'},
            ],
            'ledger': [
                {'id': 'k4', 'kind': 'constraint',
                 'text': 'must keep export synchronous when the target volume is local.',
                 'needle': 'must keep export synchronous when the target volume is local.'},
            ],
        },
        'probes': [
            {'question': 'What is the verification state after the edit?', 'expects': ['v2'],
             'excludes': ['v1']},
            {'question': 'What new constraint arrived?', 'expects': ['k4']},
            {'question': 'Which install constraint still holds?', 'expects': ['k1', 'k2']},
        ],
    }
    return {'case': 'lease-identity', 'title': 'Lease identity work with a lost reply and a rename error',
            'items': items, 'oracle': oracle, 'distill': distill, 'probes': probes,
            'round2': round2}


def checkpoint_index_case():
    """JS checkpoint work: a superseded decision, an exact module error, a cap."""
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: must not change the source_index path or the working set heading.'}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'chose line-addressed selection over verbatim quotes to cut output tokens'}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'export function buildSelectiveCheckpoint(input, options = {}) is the builder under test in dsh-wsc/lib/checkpoint.js'}]},
        _call('j1', 'read', {'file_path': 'dsh-wsc/lib/checkpoint.js'}),
        _output('j1', 'const MAX_TRANSCRIPT_CHARS = 400000'),
        *_burst('jb1', 12),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'Error: wsc: state_required raised when the state block was dropped by the budget'}]},
        *_burst('jb2', 14),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'stateCap defaults to 1200 bytes and the transcript cap is 400000 characters'}]},
        *_burst('jb3', 16),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'revised the earlier choice: quotes are kept as a fallback when the numbered transcript is unavailable'}]},
        _call('j2', 'edit', {'file_path': 'dsh-wsc/lib/checkpoint.js', 'old_string': 'a', 'new_string': 'b'}),
        _output('j2', 'ok'),
        *_burst('jb4', 18),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'receipt #17 was reissued after the worker restart'}]},
    ]
    oracle = {
        'evidence': [
            {'id': 'p1', 'kind': 'path', 'text': 'dsh-wsc/lib/checkpoint.js',
             'needle': 'dsh-wsc/lib/checkpoint.js'},
            {'id': 'e1', 'kind': 'error',
             'text': 'Error: wsc: state_required raised when the state block was dropped by the budget',
             'needle': 'Error: wsc: state_required raised'},
            {'id': 'c1', 'kind': 'code', 'text': 'export function buildSelectiveCheckpoint(input, options = {})',
             'needle': 'export function buildSelectiveCheckpoint(input, options = {})'},
            {'id': 'n1', 'kind': 'number', 'text': 'stateCap defaults to 1200 bytes',
             'needle': 'stateCap defaults to 1200 bytes'},
            {'id': 'r1', 'kind': 'repeated', 'text': REPEATED, 'needle': REPEATED},
        ],
        'ledger': [
            {'id': 'k1', 'kind': 'constraint', 'needle': 'must not change the source_index path'},
            {'id': 'd1', 'kind': 'decision', 'needle': 'chose line-addressed selection over verbatim quotes'},
            {'id': 'd2', 'kind': 'decision', 'needle': 'revised the earlier choice: quotes are kept as a fallback'},
        ],
    }
    for fact in oracle['ledger']:
        fact['text'] = fact['needle']
    distill = [
        {'text': 'must not change the source_index path', 'kind': 'constraint'},
        {'text': 'chose line-addressed selection over verbatim quotes', 'kind': 'decision'},
        {'text': 'revised the earlier choice: quotes are kept as a fallback', 'kind': 'decision'},
    ]
    probes = [
        {'question': 'Which builder and file are under test?', 'expects': ['c1', 'p1']},
        {'question': 'Why was 400k not enough?', 'expects': ['e1']},
        {'question': 'What replaced the quote-only selection?', 'expects': ['d1']},
    ]
    round2 = {
        'items': [
            _call('j3', 'edit', {'file_path': 'dsh-wsc/lib/checkpoint.js', 'old_string': 'a', 'new_string': 'b'}),
            _output('j3', 'ok'),
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
                'stateCap lowered to 800 bytes after the budget review'}]},
            *_burst('jb5', 24),
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
                'Requirement: must keep the archive size under 2 MB.'}]},
        ],
        'distill': [
            {'text': 'must keep the archive size under 2 MB.', 'kind': 'constraint'},
        ],
        'oracle': {
            'evidence': [
                {'id': 'n2', 'kind': 'number', 'text': 'stateCap lowered to 800 bytes after the budget review',
                 'needle': 'stateCap lowered to 800 bytes after the budget review'},
            ],
            'ledger': [
                {'id': 'k2', 'kind': 'constraint', 'text': 'must keep the archive size under 2 MB.',
                 'needle': 'must keep the archive size under 2 MB.'},
            ],
        },
        'probes': [
            {'question': 'What cap did the budget review set?', 'expects': ['n2']},
            {'question': 'Which constraints hold after the second round?', 'expects': ['k2', 'k1']},
            {'question': 'Which selection decision is current?', 'expects': ['d2']},
        ],
    }
    return {'case': 'checkpoint-index', 'title': 'JS checkpoint builder: superseded decision and exact error',
            'items': items, 'oracle': oracle, 'distill': distill, 'probes': probes,
            'round2': round2}


def handoff_multi_round_case():
    """A requirement change after the first round; retention must follow it."""
    items = [
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement: must use Bearer TOKEN on every /api/ call, and must keep GET /api/health public.'}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'the request filter lives in backend/auth.py and the health route in backend/server.py'}]},
        *_burst('hb1', 14),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'Error: 401 missing token returned for /api/health before the exception list existed'}]},
        *_burst('hb2', 16),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'decided to keep one allowlist in backend/auth.py instead of per-route checks'}]},
        _call('h1', 'edit', {'file_path': 'backend/auth.py', 'new_string': 'ALLOWLIST = {"/api/health"}'}),
        _output('h1', 'ok'),
        *_burst('hb3', 18),
        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
            'Requirement changed: public share routes are now exempt from the Bearer check; keep the rest unchanged.'}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'extended the single allowlist to /s/<id> share routes; the old Bearer rule still holds elsewhere'}]},
        *_burst('hb4', 20),
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
            'receipt #17 was reissued after the worker restart'}]},
    ]
    oracle = {
        'evidence': [
            {'id': 'p1', 'kind': 'path', 'text': 'backend/auth.py', 'needle': 'backend/auth.py'},
            {'id': 'p2', 'kind': 'path', 'text': 'backend/server.py', 'needle': 'backend/server.py'},
            {'id': 'e1', 'kind': 'error', 'text': 'Error: 401 missing token returned for /api/health',
             'needle': 'Error: 401 missing token returned'},
            {'id': 'c1', 'kind': 'code', 'text': 'ALLOWLIST = ', 'needle': 'ALLOWLIST = '},
            {'id': 'r1', 'kind': 'repeated', 'text': REPEATED, 'needle': REPEATED},
        ],
        'ledger': [
            {'id': 'k1', 'kind': 'constraint', 'needle': 'must use Bearer TOKEN on every /api/ call'},
            {'id': 'k2', 'kind': 'constraint', 'needle': 'must keep GET /api/health public'},
            {'id': 'k3', 'kind': 'constraint', 'needle': 'public share routes are now exempt from the Bearer check'},
            {'id': 'd1', 'kind': 'decision', 'needle': 'decided to keep one allowlist in backend/auth.py'},
        ],
    }
    for fact in oracle['ledger']:
        fact['text'] = fact['needle']
    distill = [
        {'text': 'must use Bearer TOKEN on every /api/ call', 'kind': 'constraint'},
        {'text': 'must keep GET /api/health public', 'kind': 'constraint'},
        {'text': 'decided to keep one allowlist in backend/auth.py', 'kind': 'decision'},
        {'text': 'public share routes are now exempt from the Bearer check', 'kind': 'constraint'},
    ]
    probes = [
        {'question': 'Which route stayed public and where is the allowlist?', 'expects': ['k2', 'd1']},
        {'question': 'What changed after the first round?', 'expects': ['k3']},
        {'question': 'What error appeared before the allowlist?', 'expects': ['e1']},
    ]
    round2 = {
        'items': [
            _call('h2', 'edit', {'file_path': 'backend/server.py', 'new_string': '# startup section'}),
            _output('h2', 'ok'),
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text':
                'the allowlist still lives in backend/auth.py after the server edit'}]},
            *_burst('hb5', 24),
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text':
                'Requirement: must keep the README startup section unchanged.'}]},
        ],
        'distill': [
            {'text': 'must keep the README startup section unchanged.', 'kind': 'constraint'},
        ],
        'oracle': {
            'evidence': [
                {'id': 'p3', 'kind': 'path', 'text': 'the allowlist still lives in backend/auth.py',
                 'needle': 'the allowlist still lives in backend/auth.py'},
            ],
            'ledger': [
                {'id': 'k5', 'kind': 'constraint', 'text': 'must keep the README startup section unchanged.',
                 'needle': 'must keep the README startup section unchanged.'},
            ],
        },
        'probes': [
            {'question': 'Where is the allowlist after the server edit?', 'expects': ['p3']},
            {'question': 'Which constraints hold after the second round?', 'expects': ['k5', 'k3']},
            {'question': 'What decision governs the allowlist?', 'expects': ['d1']},
        ],
    }
    return {'case': 'handoff-multi-round', 'title': 'Requirement change across rounds with a single allowlist',
            'items': items, 'oracle': oracle, 'distill': distill, 'probes': probes,
            'round2': round2}


CASES = (lease_identity_case, checkpoint_index_case, handoff_multi_round_case)
