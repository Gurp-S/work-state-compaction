"""Pin the reviewed increment and preserve a compact version without rerunning."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
SUITE = ROOT / 'benchmarks/application-five-task-v1'
sys.path.insert(0, str(SUITE / 'acceptance'))
from runtime import manifest, save

def read(path):
    return json.loads(path.read_text(encoding='utf8'))

review = read(HERE / 'review.json')
assert review['positive_checks'] == 27 and review['selected_faults_detected'] == 11
assert review['current_starter_manifest'] == manifest(SUITE / 'tasks')
suite = read(SUITE / 'suite-draft.json')
for task in suite['tasks']:
    if task['id'] != 'a3':
        task['state'] = 'representative_http_positive_and_selected_fault_calibrated_manual_pending'
suite['launch_blockers'][0] = '四任务代表性HTTP验收已校准；人工与剩余边界的正式验收接入及输入范围冻结待完成'
(SUITE / 'suite-draft.json').write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
handoff = ROOT / 'experiments/NATIVE-LOCAL-HANDOFF.md'
text = handoff.read_text(encoding='utf8')
heading = '## 最新继续：2026-10-25 四任务成功路径和具名故障校准完成\n\n'
assert heading not in text
note = ('新增公开extended_cases与四个作者专用HTTP校准后端，模型起点不含后端答案，核心src与生产GUI/python未改。真实运行结果：imports 9/9、booking 6/6、files 6/6、collaboration 6/6，共27项成功路径；11种具名故障均被预期检查检出。总15个纯本地校准变体、102项检查，review.py核对167次服务启动/停止、回执哈希、执行源码与起点不变，未重复旧起点检查、无新增模型调用。证据validation/five-task-calibration-20261025/review.json及外部wsc-*-positive-calibration-20261025-v1目录。\n\n'
        '选定故障为：未知变零、重复入账、替换解码；旧通知发送、重复投递；删除复活、丢历史、冲突块接受；忽略版本、部分批次、迁移重置。未把故障变体视为模型失败或经济收益。作者校准后端只供协议测试，未实现完整界面，也不是合格模型交付。正向检查与故障检查使用同份公开验收可执行字节；之后新增覆盖说明与人工审核文档，不重跑已有执行。\n\n'
        '四任务的完整UI、部分分页/迁移/中途崩溃边界仍依manual-review.md逐项留证，不能把27项当全需求完成。作者材料未进入starter；尚未验证原生worker对外部作者文件的读取隔离，不宣称安全盲测。准备阶段到此不继续追求穷尽参考实现；下一步集中做真实并行worker、最终输入范围、WSC候选及边界和预算冻结，然后首批两组成对。A3新增控件正向路径及人工流程仍需接入。正式5×3研究尚未启动，长期目标active。\n\n')
position = text.index('## 最新继续')
handoff.write_text(text[:position].replace('更新：2026-10-23。', '更新：2026-10-25。') + heading + note + text[position:], encoding='utf8')
base = read(ROOT / 'validation/four-app-tasks-20261023/delivery.json')
assert sha256(Path(base['version']).read_bytes()).hexdigest() == base['sha256']
with zipfile.ZipFile(base['version']) as archive:
    old = json.loads(archive.read('VERSION.json'))['files']
files = {}
for folder in (HERE, SUITE):
    for path in folder.rglob('*'):
        if path.is_file() and path.name != 'delivery.json' and '__pycache__' not in path.parts:
            name = path.relative_to(ROOT).as_posix()
            if old.get(name) != sha256(path.read_bytes()).hexdigest():
                files[name] = path
files['experiments/NATIVE-LOCAL-HANDOFF.md'] = handoff
index = dict(format='four_task_protocol_calibration_delta', base=base['version'], base_sha256=base['sha256'],
             files={n: sha256(p.read_bytes()).hexdigest() for n, p in files.items()},
             scope='27 positive protocol checks and 11 selected faults; not full app qualification or WSC efficacy')
version = ROOT / 'versions/20261025-four-protocol-calibration-v1-delta.zip'
with zipfile.ZipFile(version, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(n)).hexdigest() == h for n, h in index['files'].items())
result = dict(version=str(version), bytes=version.stat().st_size, sha256=sha256(version.read_bytes()).hexdigest(),
              positive_protocol_checks=27, selected_faults_detected=11, model_calls=0, paid_BC_started=False)
save(HERE / 'delivery.json', result)
print(json.dumps(result, ensure_ascii=False))
