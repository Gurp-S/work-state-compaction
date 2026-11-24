"""Resume a paid-format multi-turn probe without redoing a saved answer."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'benchmarks'), str(ROOT / 'src'),
                str(ROOT / '.bench/chat-memory-benchmark-2.2/benchmark-2.2/harness')]
from csm_bench22 import CsmBench22
from csm_bench22_natural_resume import run_natural


class NaturalResumeTests(unittest.TestCase):
    def test_multi_turn_resume_uses_original_answer_in_next_turn(self):
        calls = []

        class Gateway:
            def __init__(self, *_):
                pass

            def chat(self, model, messages, phase, tag, **options):
                calls.append((tag, messages[0]['content']))
                if tag.endswith('#1') and len(calls) == 2:
                    raise RuntimeError('429')
                return {'usage': {'prompt_tokens': 30, 'completion_tokens': 5},
                        'choices': [{'message': {'content': '已封存的回答' if tag.endswith('#0') else '续答'}}]}

        history = {'M01': [{'turn': 1, 'time': '2026-09-05T17:00:00+08:00',
                            'user': '账本标签是黄铜。', 'assistant': '记下了'}]}
        probe = {'id': 'probe', 'persona': 'M01', 'cutoff_turn': 1, 'tier': 'B',
                 'script': [
                     {'time': '2026-09-05T18:00:00+08:00', 'user': '标签是什么材质？'},
                     {'time': '2026-09-05T18:02:00+08:00', 'user': '再说一下。'},
                 ]}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch('csm_bench22_natural_resume.natural.load_histories', return_value=history),
            patch('csm_bench22_natural_resume.natural.load_natural', return_value=([probe], {})),
            patch('csm_bench22_natural_resume.Gateway', Gateway),
        ):
            out = Path(directory)
            options = {'release': out, 'outdir': out, 'run': 'local', 'system_name': 'csm-source',
                       'gateway_url': 'fake', 'workers': 1, 'system_factory': lambda _: CsmBench22(None),
                       'seal': {'version': 1}}
            with self.assertRaisesRegex(RuntimeError, '429'):
                run_natural(**options)
            self.assertFalse((out / 'turns.jsonl').exists())
            self.assertTrue((out / 'answer-receipts/probe.0.json').exists())
            run_natural(**options)
            self.assertEqual(['probe#0', 'probe#1', 'probe#1'], [tag for tag, _ in calls])
            self.assertEqual(calls[1][1], calls[2][1])
            self.assertIn('已封存的回答', calls[2][1])
            rows = [json.loads(line) for line in (out / 'turns.jsonl').read_bytes().splitlines()]
            self.assertEqual([0, 1], [row['k'] for row in rows])
            run_natural(**options)
            self.assertEqual(3, len(calls))
            with self.assertRaisesRegex(ValueError, 'configuration_mismatch'):
                run_natural(**{**options, 'seal': {'version': 2}})


if __name__ == '__main__':
    unittest.main()
