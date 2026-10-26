"""Reproduce stale registration accepted through a current-source binding."""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_application_quality import settle_quality
from native_evidence import save, file_hash


def observe():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        auto = root / 'C1.json'
        manual = root / 'manual.json'
        registration = root / 'registration.json'
        result = root / 'result.json'
        save(auto, dict(id='C1', passed=True))
        save(manual, dict(id='ui', status='pass'))
        save(registration, dict(source_manifest={'app.py': 'OLD'}, harness_manifest={'runner.mjs': 'grader'}))
        save(result, dict(status='completed_checks', stage='S8', mutation='none', selected_subset=False,
                          outcomes=[dict(id='C1', passed=True, receipt='C1.json')]))
        binding = dict(kind='a3', source_manifest={'app.py': 'CURRENT'},
            files={str(p): file_hash(p) for p in (auto, manual, registration, result)},
            registration_path=str(registration), result_path=str(result), grader_manifest={'runner.mjs': 'grader'},
            automatic=[dict(id='C1', passed=True, receipt=str(auto))],
            manual=[dict(id='ui', status='pass', evidence=[str(manual)])])
        return settle_quality(binding, {'app.py': 'CURRENT'}, ['C1'], ['ui'])


if __name__ == '__main__':
    output = Path(sys.argv[1])
    result = observe()
    save(output, dict(result=result, source_sha256=file_hash(ROOT / 'experiments/native_application_quality.py'), model_calls=0))
    print(result)
