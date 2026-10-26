"""Review completed starter runs, update draft readiness, retain a small delta."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / 'benchmarks/application-five-task-v1'
OUT = Path(__file__).parent
RUN = Path('D:/agent-task-runs/wsc-four-app-starters-20261025-v1')
sys.path.insert(0, str(SUITE / 'acceptance'))
from runtime import manifest, save

def read(path):
    return json.loads(path.read_text(encoding='utf8'))

observed = read(RUN / 'review.json')
assert len(observed['tasks']) == 4
receipts = []
for task in observed['tasks']:
    receipt = Path(task['receipt'])
    assert sha256(receipt.read_bytes()).hexdigest() == task['receipt_sha256']
    result = read(receipt)
    folder = SUITE / 'tasks' / task['task']
    registration = read(receipt.parent / 'registration.json')
    assert manifest(folder / 'starter') == registration['source_manifest']
    assert result['passes'] == 1 and not result['full_task_qualified']
    for check in result['outcomes']:
        entry = read(receipt.parent / check['id'] / 'receipt.json')
        starts = [e['pid'] for e in entry['events'] if e['event'] == 'started']
        stops = [e['pid'] for e in entry['events'] if e['event'] == 'stopped']
        assert starts and starts == stops, 'process_lifecycle_incomplete'
        if not check['passed']:
            assert entry['failure']['type'] == 'AssertionError'
            assert 'got 404' in entry['failure']['message']
    # Keep machine-readable stages in sync with the public Markdown draft.
    text = (folder / 'TASK.md').read_text(encoding='utf8')
    contract = read(folder / 'task.json')
    for stage, section in zip(contract['stages'], text.split('\n## ')[1:], strict=True):
        title, request = section.split('\n', 1)
        assert title.startswith(stage['id'] + ' ')
        stage.update(title=title, request=request.strip())
    contract['status'] = 'starter_boot_verified_representative_http_checks_authored'
    (folder / 'task.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    receipts.append(dict(task=task['task'], path=str(receipt), sha256=task['receipt_sha256']))

suite = read(SUITE / 'suite-draft.json')
for task in suite['tasks']:
    if task['id'] != 'a3':
        task.update(task_draft=f"tasks/{task['id']}/task.json",
            state='starter_boot_verified_representative_http_checks_authored_full_coverage_pending')
suite['launch_blockers'][0] = '其余四任务已具备起点和代表性HTTP检查；完整覆盖、成功分支校准及浏览器验收尚未完成'
(SUITE / 'suite-draft.json').write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n', encoding='utf8')

handoff = ROOT / 'experiments/NATIVE-LOCAL-HANDOFF.md'
text = handoff.read_text(encoding='utf8')
heading = '## 最新继续：2026-10-25 四应用起点与代表性HTTP验收\n\n'
note = ('此前中断后的prepare.py已完成，未重跑。四个任务各8阶段的公开说明、固定API和隔离starter已落盘于benchmarks/application-five-task-v1/tasks。collaboration只复制旧starter，不含calibration作者答案。新增acceptance/runtime.py/cases.py/run.py，实际启动服务、记录请求响应并管理直接子进程；外部总时限/后代进程治理仍待worker承担。\n\n'
        '首轮四任务并行本地校准：D:/agent-task-runs/wsc-four-app-starters-20261025-v1，17项中4启动项通过，13项因未实现API/迁移读取404失败；不是13个新bug，后续成功分支并未执行。所有17个服务启动/停止PID逐项核对，起点源码未变。验收后只明确files合同中删除对象PATCH404并同步task.json，保留原运行合同哈希，不伪称运行过最终合同。覆盖缺口见acceptance/COVERAGE.md，人工界面和全阶段覆盖待补。\n\n'
        '新增模型调用0；不重跑这批起点来凑证据。5×3正式研究未启动；接下来集中补四任务关键缺口与成功分支校准、共享浏览器验收，再完成真实并行worker和候选/预算冻结。A3归档版本20261023-a3-browser-acceptance-v1-delta.zip为52192字节，sha256 fa05e6b1c869a6e009c6c0cdbc22898a8d87b22219ff51377f07d372e5413aa2。长期目标保持active。\n\n')
assert heading not in text
position = text.index('## 最新用户任务')
handoff.write_text(text[:position] + heading + note + text[position:], encoding='utf8')

review = dict(status='four_app_preparation_reviewed', receipts=receipts, total_checks=17,
    startup_passes=4, expected_feature_gaps=13, all_recorded_service_processes_stopped=True,
    starter_sources_unchanged=True, positive_domain_calibration_complete=False,
    current_contract_delta='After execution, explicitly specified deleted file PATCH=404 and synchronized task.json; original run pins retained',
    model_calls=0, study_started=False, goal_complete=False)
save(OUT / 'review.json', review)

base = read(ROOT / 'validation/a3-acceptance-20261023/delivery.json')
assert sha256(Path(base['version']).read_bytes()).hexdigest() == base['sha256']
files = {}
for folder in (SUITE, OUT):
    for path in folder.rglob('*'):
        if path.is_file() and path.name != 'delivery.json' and '__pycache__' not in path.parts:
            files[path.relative_to(ROOT).as_posix()] = path
files['experiments/NATIVE-LOCAL-HANDOFF.md'] = handoff
index = dict(format='four_application_tasks_delta', base=base['version'], base_sha256=base['sha256'],
             files={name: sha256(path.read_bytes()).hexdigest() for name, path in files.items()},
             scope=review)
version = ROOT / 'versions/20261025-four-application-tasks-v1-delta.zip'
with zipfile.ZipFile(version, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(n)).hexdigest() == h for n, h in index['files'].items())
delivery = dict(version=str(version), bytes=version.stat().st_size,
    sha256=sha256(version.read_bytes()).hexdigest(), new_model_calls=0, study_started=False)
save(OUT / 'delivery.json', delivery)
print(json.dumps(delivery, ensure_ascii=False))
