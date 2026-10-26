"""Private acceptance for the independently registered command transport task.

These tests run only in copied task source trees, not against the main library.
"""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc import Event, Store, WSC, WSCError


class CommandStreamTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.core = WSC(Store(self.root/'state.db', session_id='fixture', workspace=str(self.root)),
                        access=lambda *args: True)
        self.core.ingest([Event('fixture', 'observation', {'scope':'command_transport'}, text='local fixture')])

    def generator(self, program, *argv, **options):
        try:
            module = importlib.import_module('wsc.bounded_generation')
        except ModuleNotFoundError:
            self.fail('BoundedJsonCommandGenerator entry point unavailable')
        return module.BoundedJsonCommandGenerator([sys.executable, '-c', program, *map(str,argv)], **options)

    def test_valid_unicode_response_and_partial_usage(self):
        program = "import json,sys; m=json.load(sys.stdin); print(json.dumps({'selection':{},'usage':{'input_uncached':8,'output':2}},ensure_ascii=False))"
        result = self.generator(program)({'fixture':'中文🙂'})
        self.assertEqual(8, result.usage.input_uncached)
        self.assertEqual(2, result.usage.output)
        self.assertIsNone(result.usage.input_cached)

    def test_stdout_limit_stops_child_before_followup_action(self):
        marker = self.root/'after-overflow.txt'
        program = "import sys,time,pathlib; sys.stdout.buffer.write(b'x'*8192); sys.stdout.flush(); time.sleep(.8); pathlib.Path(sys.argv[1]).write_text('continued')"
        generator = self.generator(program, marker, max_output_bytes=128, timeout=4)
        with self.assertRaisesRegex(WSCError, '^generation_output_budget_exhausted$'):
            self.core.generate(self.core.capture(), generator, producer='local_fixture')
        time.sleep(.9)
        self.assertFalse(marker.exists(), 'child continued after output rejection')
        report = self.core.status()['usage']
        self.assertEqual(1, len(report['attempts']))
        self.assertEqual('failed', report['attempts'][0]['status'])
        self.assertEqual(1, report['totals']['output']['unknown_attempts'])

    def test_timeout_remains_neutral_and_child_stops(self):
        marker = self.root/'after-timeout.txt'
        generator = self.generator("import time,pathlib,sys; time.sleep(.8); pathlib.Path(sys.argv[1]).write_text('continued')",
                                   marker, timeout=.1)
        with self.assertRaisesRegex(WSCError, '^generation_command_timeout$'):
            generator({})
        time.sleep(.9)
        self.assertFalse(marker.exists())

    def test_invalid_selection_retains_returned_usage(self):
        generator = self.generator("print('{\"selection\":{\"source_ids\":8},\"usage\":{\"input_uncached\":19,\"output\":7}}')")
        with self.assertRaisesRegex(WSCError, 'source_reference_list_invalid'):
            self.core.generate(self.core.capture(), generator, producer='local_fixture')
        report = self.core.status()['usage']
        self.assertEqual(19, report['totals']['input_uncached']['known_sum'])
        self.assertEqual(7, report['totals']['output']['known_sum'])

    def test_stderr_overflow_is_bounded_even_with_valid_stdout(self):
        marker = self.root/'after-stderr.txt'
        program = "import sys,time,pathlib; print('{\"selection\":{}}',flush=True); sys.stderr.write('private-detail-'*1024); sys.stderr.flush(); time.sleep(.8); pathlib.Path(sys.argv[1]).write_text('continued')"
        generator = self.generator(program, marker, max_stderr_bytes=128, timeout=4)
        with self.assertRaisesRegex(WSCError, '^generation_stderr_budget_exhausted$'):
            generator({})
        time.sleep(.9)
        self.assertFalse(marker.exists())

    def test_simultaneous_streams_finish_without_deadlock(self):
        program = "import sys,threading; t=threading.Thread(target=lambda: (sys.stderr.buffer.write(b'e'*65536),sys.stderr.flush())); t.start(); sys.stdout.write(' '*65536+'{\"selection\":{}}'); sys.stdout.flush(); t.join()"
        result = self.generator(program, max_output_bytes=100000, max_stderr_bytes=100000, timeout=4)({})
        self.assertEqual((), result.selection.source_ids)

    def test_stderr_exact_byte_limit_and_utf8_are_not_character_counted(self):
        program = "import sys; sys.stderr.buffer.write('汉'.encode('utf8')); sys.stderr.flush(); print('{\"selection\":{}}')"
        self.generator(program, max_stderr_bytes=3)({})
        with self.assertRaisesRegex(WSCError, '^generation_stderr_budget_exhausted$'):
            self.generator(program, max_stderr_bytes=2)({})

    def test_invalid_limits_fail_before_child_start(self):
        marker = self.root/'invalid-start.txt'
        for options in ({'max_output_bytes':0}, {'max_stderr_bytes':0}, {'max_stderr_bytes':True}, {'timeout':0}):
            with self.subTest(options=options), self.assertRaises((WSCError, ValueError, TypeError)):
                self.generator("import sys,pathlib; pathlib.Path(sys.argv[1]).write_text('started')", marker, **options)({})
        self.assertFalse(marker.exists())
