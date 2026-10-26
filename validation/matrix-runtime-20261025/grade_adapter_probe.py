"""Run the newly connected external-grade adapter once on an author fixture.

This is adapter qualification, not a model application result. Author source is
not copied into task inputs. Missing UI review must remain unknown.
"""
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_application_adapters import FrozenApplicationAdapters
from native_evidence import read, save, file_hash

AREA = Path('D:/agent-task-runs/wsc-matrix-grade-adapter-20261025-v1')
AREA.mkdir()
input_path = Path('D:/agent-task-runs/wsc-four-app-inputs-20261025-v1/collaboration/input-binding.json')
frozen = Path(read(input_path)['workspace'])
cases = ['startup_and_page']
for path in (frozen/'task-contract/acceptance/cases.py',frozen/'task-contract/acceptance/extended_cases.py'):
    tree=ast.parse(path.read_text(encoding='utf8'))
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator,ast.Call) and isinstance(decorator.func,ast.Name) and decorator.func.id=='case':
                    args=[ast.literal_eval(v) for v in decorator.args]
                    if args[0]=='collaboration': cases.append(args[1])
source = Path('D:/agent-task-runs/wsc-collaboration-positive-calibration-20261025-v1/none/workspace')
adapter=FrozenApplicationAdapters({},dict(collaboration=dict(binding=str(input_path),binding_sha256=file_hash(input_path))),
    dict(collaboration={'8':cases}),node_executable='E:/nodejs/node.exe')
save(AREA/'registration.json',dict(source=str(source),source_kind='author_protocol_calibration_not_model_delivery',
    expected_cases=cases,model_calls=0))
result=adapter.grade(dict(pair_id='collaboration/r1',resources=dict(workspace=str(source))),8,AREA/'acceptance')
assert result['quality']['status']=='unknown' and result['manual_pending']
assert all(r['passed'] for r in result['observations']) and len(result['observations'])==6
save(AREA/'review.json',dict(result=result,model_calls=0,
    scope='Real new grader process/receipt adapter; six existing author checks repeated only to qualify this integration'))
print(dict(automatic_passes=6,full_task_quality=result['quality']['status'],model_calls=0))
