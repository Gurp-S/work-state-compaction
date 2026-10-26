"""One offline calibration on preserved B/C copies; never a task retry."""
from copy import deepcopy
from pathlib import Path
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, manifest, digest
from native_public_checks import publish_contract, grade_public_contract
from strict_jsonl_study import STAGES

ORIGINAL = Path('D:/agent-task-runs/wsc-strict-jsonl-pair-20261023-v1')
AREA = Path('D:/agent-task-runs/wsc-public-contract-calibration-20261023-v1')
AREA.mkdir()
legacy = (ROOT / 'experiments/strict_jsonl_grader.py').read_text('utf-8')
legacy = legacy.replace("if __name__=='__main__':unittest.main()", '')
boundary = '''
class NumericBoundaryAudit(unittest.TestCase):
    def test_large_signed_integer_value_and_hash(self):
        from wsc.strict_jsonl import parse_strict_rollout
        limit = sys.get_int_max_str_digits()
        for digits in (4300, 4301, 5000):
            for negative in (False, True):
                with self.subTest(digits=digits, negative=negative):
                    number = (b'-' if negative else b'') + b'9' * digits
                    raw = b'{"type":"event_msg","payload":' + number + b'}'
                    value = parse_strict_rollout(raw)
                    expected = (10**digits - 1) * (-1 if negative else 1)
                    self.assertIs(type(value.rows[0]['payload']), int)
                    self.assertEqual(expected, value.rows[0]['payload'])
                    self.assertEqual(sha256(raw).hexdigest(), value.metadata['sha256'])
                    self.assertTrue(value.metadata['parse_complete'])
                    self.assertEqual(limit, sys.get_int_max_str_digits())

    def test_finite_extremes_and_all_unterminated_nonfinite_forms(self):
        import math
        from wsc.strict_jsonl import parse_strict_rollout
        for literal in (b'0.0', b'-0.0', b'1.7976931348623157e308', b'-1.7976931348623157e308'):
            with self.subTest(literal=literal):
                value = parse_strict_rollout(b'{"type":"event_msg","payload":' + literal + b'}')
                result = value.rows[0]['payload']
                self.assertIs(type(result), float)
                self.assertEqual(float(literal), result)
                self.assertEqual(math.copysign(1, float(literal)), math.copysign(1, result))
        for literal in (b'NaN', b'Infinity', b'-Infinity', b'1e9999', b'-1e9999', b'1.7976931348623159e308'):
            with self.subTest(literal=literal), self.assertRaisesRegex(ValueError, r'^rollout_nonfinite_number:line=1$'):
                parse_strict_rollout(b'{"type":"event_msg","payload":' + literal + b'}')

if __name__ == '__main__': unittest.main()
'''
grader = AREA / 'contract-checks.py'
grader.write_text(legacy + boundary, encoding='utf-8')
extra = ['NumericBoundaryAudit.test_large_signed_integer_value_and_hash',
         'NumericBoundaryAudit.test_finite_extremes_and_all_unterminated_nonfinite_forms']
stages = [{'id': s['id'], 'message': s['message'], 'methods': deepcopy(s['methods'] or [])} for s in STAGES]
for stage in stages[1:3]: stage['methods'].extend(extra)
names = stages[2]['methods']
coverage = [
    {'requirement': 'Unicode、物理LF行号、原始字节身份', 'methods': [names[0]],
     'boundaries': '中文、U+2028、空白行、原始字节SHA及长度'},
    {'requirement': '任意对象深度重复键拒绝', 'methods': [names[1]],
     'boundaries': '同值、嵌套、数组中的对象、解码等价键、无末尾LF'},
    {'requirement': '字符串不是递归JSON', 'methods': [names[2]],
     'boundaries': '非有限常量及重复键同形文本'},
    {'requirement': '真实尾行和缺文件语义、中间坏行及错误记录形状', 'methods': [names[3], names[4]],
     'boundaries': '不完整JSON、坏UTF-8尾行、中间坏行、非对象及错误type'},
    {'requirement': '非有限数值拒绝，完整无LF坏数不丢弃', 'methods': [names[5], names[6], extra[1]],
     'boundaries': '正负非有限常量、溢出、最大有限浮点附近、带/不带末尾LF'},
    {'requirement': '有限浮点及合法大整数保持值与类型', 'methods': [names[7], *extra],
     'boundaries': '120、4300、4301、5000位正负整数；浮点正负零及最大有限值；观察转换上限是否改变'},
    {'requirement': '单行原字节预算，先于跳过空白或解码解析', 'methods': [names[8], names[9]],
     'boundaries': '多字节中文、CR计入LF不计、恰好允许、空白和坏编码超限'},
    {'requirement': 'None无额外限额，启用仅正整数排除bool', 'methods': [names[10]],
     'boundaries': 'None、True/False、0、负数、浮点及字符串'},
]
runtime = read(ORIGINAL / 'runtime-preflight/result.json')['facts']
results, bindings, original_manifests = {}, {}, {}
for arm in ('C', 'B'):
    source = ORIGINAL / arm / 'final-workspace'
    original_manifests[arm] = manifest(source)
    workspace = AREA / arm / 'workspace'
    shutil.copytree(source / 'src', workspace / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    bindings[arm] = publish_contract(workspace, grader, stages, coverage)
    result = grade_public_contract(workspace, bindings[arm], 'line_budget_task', AREA / arm / 'acceptance', runtime=runtime)
    results[arm] = {'tests': result['tests'], 'passed': result['passed'], 'failures': result['failures'],
                    'errors': result['errors'], 'runtime': result['observed_runtime'],
                    'receipt_sha256': file_hash(AREA / arm / 'acceptance/public-receipt.json')}
assert bindings['C']['contract_sha256'] == bindings['B']['contract_sha256']
assert results['B']['passed'] and results['B']['tests'] == 13
assert not results['C']['passed'] and results['C']['tests'] == 13 and not results['C']['errors']
assert results['C']['failures'] and all('test_large_signed_integer_value_and_hash' in x['test'] for x in results['C']['failures'])
for arm in ('C', 'B'):
    assert manifest(ORIGINAL / arm / 'final-workspace') == original_manifests[arm]
save(AREA / 'result.json', {'status': 'calibration_detected_known_contract_gap', 'scope': 'Offline preserved-artifact copies, not new native task qualification',
    'model_calls': 0, 'original_task_artifacts_unchanged': True, 'bindings': bindings, 'results': results,
    'original_manifests_sha256': {a: digest(m) for a, m in original_manifests.items()},
    'grader_sha256': file_hash(grader), 'script_sha256': file_hash(__file__)})
print(json.dumps({'status': 'calibration_detected_known_contract_gap', 'C_tests': results['C']['tests'],
                  'C_failed_subcases': len(results['C']['failures']), 'B_passed': results['B']['passed'], 'model_calls': 0}))
