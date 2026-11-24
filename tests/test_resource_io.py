"""Before/after I/O and host-window experiments; no model calls."""
from pathlib import Path
from hashlib import sha256
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc import WSC,Store,Selection,WSCError
from wsc.resource_io import ResourceIO
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.publication import check_evidence
from wsc.evidence import write_once
from test_contracts import DurableTestHost,message


class ResourceIOTests(unittest.TestCase):
    def test_failed_file_sync_never_exposes_new_final_name_in_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'old';new=root/'new'
            with patch('os.fsync',side_effect=OSError('injected flush failure')):
                with self.assertRaises(OSError):write_once(old,b'payload')
                with self.assertRaisesRegex(WSCError,'evidence_object_unavailable'):ResourceIO().write_once(new,b'payload')
            self.assertTrue(old.exists());self.assertFalse(new.exists())
            self.assertFalse(list(root.glob('.pending-*')))
            ResourceIO().write_once(new,b'payload')
            self.assertFalse(ResourceIO().capabilities()['power_loss_recovery_proven'])
    @unittest.skipUnless(os.name=='nt','Pinned Windows publication cache')
    def test_publication_cache_is_pinned_and_closes_before_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'object';io=ResourceIO()
            with io.publication_writer() as writer:
                writer(path,b'original');read=io.bytes_read
                writer(path,b'original');self.assertEqual(read,io.bytes_read)
                with self.assertRaisesRegex(WSCError,'evidence_object_conflict'):writer(path,b'other')
                with self.assertRaises(OSError):path.write_bytes(b'changed')
            path.write_bytes(b'changed')
            with io.publication_writer() as writer:
                with self.assertRaisesRegex(WSCError,'evidence_object_conflict'):writer(path,b'original')

    def test_streamed_hash_and_comparison_do_not_use_read_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'object';payload=b'large payload'*100000
            io=ResourceIO(chunk_bytes=4096);io.write_once(path,payload)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('unbounded read')):
                io.write_once(path,payload)
                self.assertEqual(sha256(payload).hexdigest(),io.digest(path))
            self.assertFalse(list(Path(directory).glob('.pending-*')))

    def test_existing_read_failure_is_neutral_and_can_recover_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'object';io=ResourceIO();io.write_once(path,b'original')
            with patch.object(io,'equal',side_effect=PermissionError('fixture unreadable')):
                with self.assertRaisesRegex(WSCError,'evidence_object_unavailable'):io.write_once(path,b'original')
            self.assertEqual(b'original',path.read_bytes())

    def test_conflict_comparison_does_not_read_whole_object(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'object';payload=b'x'*200000;write_once(path,payload)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('unbounded read')):
                write_once(path,payload)
                with self.assertRaisesRegex(WSCError,'evidence_object_conflict'):write_once(path,b'y'*200000)


    def test_existing_object_read_error_does_not_permanently_block_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);io=ResourceIO()
            core=WSC(Store(root/'state.db',session_id='s',workspace=str(root)),access=lambda *a:True,resource_io=io)
            adapter=CodexCheckpointAdapter();core.ingest(adapter.import_items([message('user','task')],thread_id='s'))
            view=core.prepare(core.capture(),Selection(),producer='fixture')
            first=core.stage(view,directory=root/'exports',adapter=adapter);core.discard(first)
            with patch.object(io,'equal',side_effect=PermissionError('transient read failure')):
                with self.assertRaisesRegex(WSCError,'evidence_object_unavailable'):
                    core.stage(view,directory=root/'exports',adapter=adapter)
            self.assertIn('failed',[op['state'] for op in core.status()['operations']])
            recovered=core.stage(view,directory=root/'exports',adapter=adapter)
            check_evidence(core,core.package(recovered))

    def test_post_commit_confirmation_failure_stops_without_second_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            core=WSC(Store(root/'state.db',session_id='s',workspace=str(root)),access=lambda *a:True)
            adapter=CodexCheckpointAdapter();items=[message('user','task')]
            core.ingest(adapter.import_items(items,thread_id='source'))
            view=core.prepare(core.capture(),Selection(),producer='fixture');op=core.stage(view,directory=root/'exports',adapter=adapter)
            host=DurableTestHost(root/'host.db',core,items)
            with patch('wsc.publication.confirm',side_effect=RuntimeError('injected local settlement failure')):
                with self.assertRaises(RuntimeError):core.install(op,host)
            self.assertEqual('recovery_required',core.status()['operations'][0]['state'])
            with self.assertRaisesRegex(WSCError,'installation_outcome_unknown'):core.install(op,host)
            self.assertEqual(1,host.state()['effects'])
            self.assertEqual(0,core.status()['cursor'])


if __name__=='__main__':unittest.main()
