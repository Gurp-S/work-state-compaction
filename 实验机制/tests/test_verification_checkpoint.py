import json
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock
from unittest import TestCase

from wsc import Event, Selection, Store, WSC
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc_experimental.verification_checkpoint import VerificationCheckpointAdapter
from wsc.contracts import HostReceipt, digest, encode
from wsc.events import rows
from wsc.source_access import SnapshotSourceAccess
from wsc_experimental.verification_capture import VerificationManifest, invalidate_manifest, manifest_observation, verification_receipt
from wsc_experimental.verification_state import project_verification


class VerificationCheckpointTests(TestCase):
    def test_manifest_body_must_match_receipt_digest(self):
        with TemporaryDirectory() as root:
            core = WSC(Store(Path(root) / 'wsc.db', session_id='test', workspace=root), access=lambda *_: True)
            manifest = VerificationManifest('suite', {'app.js': '1' * 64}, {'runner': 'node test.js'})
            receipt = verification_receipt('result', scope='suite', outcome='passed', executed_manifest=manifest)
            receipt.payload['manifest']['execution']['runner'] = 'unrelated runner'
            core.ingest([manifest_observation('v1', manifest), receipt])
            with self.assertRaisesRegex(ValueError, 'verification_manifest_seal_mismatch'):
                project_verification(core, core.capture(), scope='suite')

    def test_unsealed_change_and_mutable_host_inputs_cannot_rebind_a_receipt(self):
        with TemporaryDirectory() as root:
            core = WSC(Store(Path(root) / 'wsc.db', session_id='test', workspace=root), access=lambda *_: True)
            inputs = {'app.js': '1' * 64}
            execution = {'runner': 'node test.js'}
            manifest = VerificationManifest('suite', inputs, execution)
            core.ingest([manifest_observation('v1', manifest)])
            inputs['app.js'] = '2' * 64
            execution['runner'] = 'other runner'
            core.ingest([invalidate_manifest('changed', scope='suite'),
                         verification_receipt('late-v1', scope='suite', outcome='passed', executed_manifest=manifest)])
            state = project_verification(core, core.capture(), scope='suite')
            self.assertEqual(state['status'], 'unknown')
            self.assertEqual(state['receipts'][0]['applicability'], 'unknown')
            core.ingest([manifest_observation('v2', VerificationManifest('suite', inputs, execution))])
            state = project_verification(core, core.capture(), scope='suite')
            self.assertEqual(state['status'], 'unknown')
            self.assertEqual(state['receipts'][0]['applicability'], 'historical')

    def test_publication_uses_manifest_from_tail_and_keeps_receipts_in_archive(self):
        with TemporaryDirectory() as root:
            blocked_reads = set()
            core = WSC(Store(Path(root) / 'wsc.db', session_id='test', workspace=root),
                       access=lambda _, key, action: action != 'read' or key not in blocked_reads)
            native = CodexCheckpointAdapter()
            message = {'type': 'message', 'role': 'user',
                       'content': [{'type': 'input_text', 'text': 'Check release'}]}
            core.ingest(native.import_items([message], thread_id='fixture'))
            v1 = VerificationManifest('suite', {'app.js': '1' * 64}, {'runner': 'node test.js'})
            v2 = VerificationManifest('suite', {'app.js': '2' * 64}, v1.execution)
            core.ingest([manifest_observation('v1', v1),
                         verification_receipt('passed-v1', scope='suite', outcome='passed', executed_manifest=v1)])
            snapshot = core.capture()
            view = core.prepare(snapshot, Selection(source_ids=('passed-v1',)), producer='fixture')
            core.ingest([manifest_observation('v2', v2)])
            tail = {'type': 'message', 'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': 'Recorded latest workspace state'}]}
            core.ingest(native.import_items([tail], thread_id='fixture', start_ordinal=1))
            operation = core.stage(view, directory=root, adapter=VerificationCheckpointAdapter(scopes=['suite']))
            package = core.package(operation)
            blocked_reads.add('passed-v1')
            host = Mock()
            with self.assertRaisesRegex(ValueError, 'Permission denied: source'):
                core.install(operation, host)
            host.install.assert_not_called()
            blocked_reads.clear()
            self.assertEqual(package['items'][1], message)
            self.assertEqual(package['items'][-1], tail)
            self.assertEqual(len(package['items']), 3)
            facts = json.loads(package['items'][0]['content'][0]['text'])
            state, = facts['verification_state']
            self.assertEqual(state['status'], 'unknown')
            self.assertEqual(state['current_manifest']['source'], 'v2')
            self.assertEqual(state['latest_receipts'], [{'source': 'passed-v1', 'outcome': 'passed',
                                                          'applicability': 'historical', 'reference': 'source:s3'}])
            self.assertEqual(facts['historical_excerpts'], [])
            self.assertTrue(Path(package['evidence']['passed-v1']['file_path']).is_file())
            self.assertTrue(Path(package['evidence']['v2']['file_path']).is_file())
            archived = json.loads(Path(package['evidence']['v2']['file_path']).read_text(encoding='utf-8'))
            self.assertEqual(archived['manifest']['inputs'], {'app.js': '2' * 64})
            self.assertNotIn('manifest', state['current_manifest'])
            reader = SnapshotSourceAccess(core.store, core.capture(), access=core.access)
            ref = state['current_manifest']['reference'].removeprefix('source:')
            public = reader.read(ref)
            self.assertIn(v2.fingerprint(), encode(public))
            self.assertNotIn('app.js', encode(public))
            receipt_ref = state['latest_receipts'][0]['reference'].removeprefix('source:')
            self.assertIn(v1.fingerprint(), encode(reader.read(receipt_ref)))
            self.assertNotIn(ref, SnapshotSourceAccess(core.store, snapshot, access=core.access).aliases)
            with core.store.transaction() as db:
                data = json.loads(db.execute('SELECT data FROM events WHERE id=?', ('v2',)).fetchone()[0])
                changed = {**data, 'text': 'changed after stage'}
                db.execute('UPDATE events SET data=?,digest=? WHERE id=?', (encode(changed), digest(changed), 'v2'))
            host = Mock()
            with self.assertRaisesRegex(ValueError, 'verification_tail_changed'):
                core.install(operation, host)
            host.install.assert_not_called()
            with core.store.transaction() as db:
                db.execute('UPDATE events SET data=?,digest=? WHERE id=?', (encode(data), digest(data), 'v2'))
            with core.store.connect() as db:
                source = rows(db)
            compact = VerificationCheckpointAdapter(scopes=['suite'], compact_history=True).render(
                {'sources': source[:3], 'understandings': [], 'clues': []}, source, snapshot.cut,
                package['evidence'], source_index=package['source_index'],
                understanding_index=package['understanding_index'])
            compact_state, = json.loads(compact[0]['content'][0]['text'])['verification_state']
            self.assertEqual(compact_state['status'], state['status'])
            self.assertEqual(compact_state['archived_receipt_counts'], {'historical': {'passed': 1}})
            self.assertLess(len(encode(compact)), len(encode(package['items'])))
            core.ingest([Event('v3', 'observation', {'type': 'input_manifest',
                              'verification_scope': 'suite', 'digest': '3' * 64})])
            host = Mock()
            with self.assertRaisesRegex(ValueError, 'verification_state_changed'):
                core.install(operation, host)
            host.install.assert_not_called()
            core.discard(operation)
            successor = core.prepare(core.capture(), Selection(), producer='fixture')
            operation = core.stage(successor, directory=root, adapter=VerificationCheckpointAdapter(scopes=['suite']))
            fresh = core.package(operation)
            host.install.return_value = HostReceipt(operation, fresh['package_digest'], 'test', root,
                fresh['next_generation'], fresh['binding']['control_epoch'], fresh['through'], 'fixture-host', True)
            core.install(operation, host)
            reopened = WSC(Store(Path(root) / 'wsc.db', session_id='test', workspace=root),
                           access=lambda *_: True)
            self.assertEqual(reopened.status()['cursor'], fresh['through'])
