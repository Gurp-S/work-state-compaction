"""End-to-end state loop acceptance: the design diagram as executable checks.

Origin signals enter as signals, never as facts; distilled entries enter only
through the write-back edge (H2); the next view presents the ledger's current
entries (H1); after a change, the next presentation states what moved (H3).
"""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from wsc import WSC, Store, Selection, Understanding, WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultStore, ResultPolicy
from test_contracts import DurableTestHost, message

TIMES = ["2026-11-17T01:00:00Z", "2026-11-17T02:00:00Z", "2026-11-17T03:00:00Z",
         "2026-11-17T04:00:00Z", "2026-11-17T05:00:00Z"]


class StateLoopAcceptance(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = WSC(Store(self.root / 'core.db', session_id='session', workspace=str(self.root)),
                        access=lambda *args: True)
        self.ctx = ContextRuntime(self.core, ResultStore(self.root / 'results', session='session'),
                                  policy=ResultPolicy(enabled=True))
        self.adapter = CodexCheckpointAdapter()
        self.ordinal = 0
        self.items = []
        first = [message('user', 'Constraint: keep the existing a.py API'),
                 message('assistant', 'V1 passed tests')]
        self.ids = self.observe(first)
        self.core.presented('request-1', (self.ids[1],), receiver='offline-model')
        self.host = DurableTestHost(self.root / 'host.db', self.core, self.items)

    def observe(self, items):
        events = self.adapter.import_items(items, thread_id='native-thread',
                                           start_ordinal=self.ordinal, observed_at=TIMES[self.ordinal:self.ordinal + len(items)])
        self.ordinal += len(items)
        self.items.extend(items)
        self.ctx.observe(events)
        return [event.id for event in events]

    def write_back(self, understandings):
        from wsc import Generated, Usage
        def generator(material):
            return Generated(Selection(new_understandings=tuple(understandings)), Usage(output=5))
        return self.ctx.write_back(self.ctx.capture(), generator, producer='turn-model')

    def test_continuation_after_a_change_presents_the_new_head_and_the_delta(self):
        # H2: only distilled entries enter the ledger; an origin signal does not.
        v1 = self.write_back([Understanding(text='V1 passed tests', kind='verification',
                                            sources=(self.ids[1],), observed_at=TIMES[1],
                                            invalid_when={'file_changed': 'a.py'})])
        with self.core.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM views').fetchone()[0], 0)
        self.assertEqual(v1[0]['text'], 'V1 passed tests')

        # H1: the installed round presents the ledger entry as the working state.
        view = self.core.prepare(self.core.capture(), Selection(), producer='offline-choice')
        self.assertEqual([r['ref'] for r in self.core.view(view)['body']['understandings']], [v1[0]['ref']])
        operation = self.ctx.stage(view, directory=self.root / 'exports',
                                   adapter=CodexCheckpointAdapter())
        facts = json.loads(self.core.package(operation)['items'][0]['content'][0]['text'])
        self.assertEqual(facts['kind'], 'working_state')
        self.assertEqual(facts['understandings'][0]['status'], 'active')
        self.assertEqual(facts['understandings'][0]['observed_at'], TIMES[1])
        self.assertNotIn('state_changes', facts)

        self.core.install(operation, self.host)
        self.assertEqual(1, self.host.state()['effects'])

        # A new observation arrives: a.py is edited and the verification is redone.
        later = self.observe([
            {'type': 'function_call', 'call_id': 'edit-1', 'name': 'edit',
             'arguments': json.dumps({'file_path': 'a.py', 'new_string': 'x'})},
            {'type': 'function_call_output', 'call_id': 'edit-1', 'output': 'ok'},
            message('assistant', 'V2 checked after edit'),
        ])
        self.core.presented('request-2', (later[1],), receiver='offline-model')
        v2 = self.write_back([Understanding(text='V2 checked after edit', kind='verification',
                                            sources=(later[2],), observed_at=TIMES[4])])

        # H1: the edit mechanically expires V1; only V2 is current.
        view = self.core.prepare(self.core.capture(), Selection(), producer='offline-choice')
        body = self.core.view(view)['body']
        self.assertEqual([r['ref'] for r in body['understandings']], [v2[0]['ref']])
        with self.assertRaisesRegex(WSCError, 'state_entry_not_current'):
            self.core.prepare(self.core.capture(),
                              Selection(understanding_refs=(v1[0]['ref'],)), producer='offline-choice')

        # H3: the delta is measured against the installed presentation.
        self.assertEqual(body['state_changes'], {'added': [v2[0]['ref']], 'revised': [],
                                                 'expired': [v1[0]['ref']]})
        operation = self.ctx.stage(view, directory=self.root / 'exports', adapter=CodexCheckpointAdapter())
        facts = json.loads(self.core.package(operation)['items'][0]['content'][0]['text'])
        self.assertEqual([e['ref'] for e in facts['understandings']], [v2[0]['ref']])
        self.assertEqual(facts['state_changes'], body['state_changes'])
        self.assertNotIn(v1[0]['ref'], json.dumps(facts['understandings']))


if __name__ == '__main__':
    main()