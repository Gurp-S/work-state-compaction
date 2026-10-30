import json
from pathlib import Path
import tempfile
import unittest
from pipeline import run


class PipelineSmoke(unittest.TestCase):
    def test_versioned_stage_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'input.csv'
            source.write_text('tenant,invoice,amount\na,one,1.00\n', encoding='utf-8')
            manifest = run(source, root/'out')
            self.assertEqual('invoice.pipeline/2', manifest['format'])
            self.assertEqual(manifest, json.loads((root/'out/manifest.json').read_text(encoding='utf-8')))
            self.assertEqual({'normalized', 'totals'}, set(manifest['stages']))


if __name__ == '__main__':
    unittest.main()
