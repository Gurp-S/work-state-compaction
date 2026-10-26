"""Finalize reviewed execution-layer progress and compact version provenance."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, manifest, file_hash

review = read(HERE / 'review.json')
guard = read(HERE / 'cleanup-guard-check.json')
paid_reg = read(Path(review['receipts']['paid_probe']['path']).parent / 'registration.json')
old = HERE / 'before-cleanup-guard.py.txt'
session = ROOT / 'experiments/native_application_session.py'
assert file_hash(old) == guard['before_sha256'] == paid_reg['source_pins'][str(session)]
assert file_hash(session) == guard['current_sha256']
expected = old.read_text(encoding='utf8').replace(
    "            if not terminal:\n                outcome['termination'] = self.close()\n",
    "            if not terminal:\n                try:\n                    outcome['termination'] = self.close()\n"
    "                except Exception as error:\n"
    "                    # Cleanup failure must not bypass receipt capture/journaling.\n"
    "                    outcome['termination_error'] = type(error).__name__ + ':' + str(error)\n")
assert expected == session.read_text(encoding='utf8'), 'unreviewed_post_probe_source_change'
assert guard['after']['journal_entries'] == 1 and guard['after']['receipt_persisted']
for path, value in paid_reg['source_pins'].items():
    if Path(path) != session:
        assert file_hash(path) == value
final = dict(original_review_sha256=file_hash(HERE / 'review.json'),
    current_session_sha256=file_hash(session), paid_probe_session_sha256=file_hash(old),
    post_probe_change='Only cleanup-exception guard, verified with separate synthetic before/after; paid smoke not repeated',
    paid_protocol_responses=1, paid_protocol_total_tokens=22567, paid_comparison_started=False,
    cumulative_budgets_and_C_boundary_policy_pending=True, goal_complete=False)
save(HERE / 'final-review.json', final)

suite_path = ROOT / 'benchmarks/application-five-task-v1/suite-draft.json'
suite = read(suite_path)
suite['execution']['model'] = review['observed_model']
suite['execution']['effort'] = review['effort']
suite['execution']['native_runtime_observation'] = review['current_executable']
suite['execution']['configuration_status'] = 'model_and_binary_observed_remaining_study_conditions_unfrozen'
suite['execution']['frozen_four_app_inputs'] = review['receipts']['frozen_inputs']
suite['launch_blockers'][2] = '原生会话执行层已验证四服务并行和单真实回合；完整矩阵worker的跨阶段/边界/累计预算/质量接入待完成'
suite_path.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
handoff = ROOT / 'experiments/NATIVE-LOCAL-HANDOFF.md'
text = handoff.read_text(encoding='utf8')
heading = '## 最新继续：2026-10-25 新原生版本执行层与输入冻结\n\n'
assert heading not in text
note = ('旧6257d9e8f63c0f2b/codex.exe已不存在；当前2993767bd1dfb009为0.164.0-alpha.11.1。新增native_owned_process可选JobObject进程所有权，native_application_session可选实际原生阶段执行/追加回执结算，以及native_application_inputs明确白名单输入冻结。旧NativeRPC入口不改。四原生服务实际同时就绪、成员集合互斥、关闭后空；初始检查因空线程rollout不存在保守失败，保留原result，reviewed-result另存。独立零推理试验确认：idle无文件，注入事实后产生11条/132438字节完整历史，0响应，不重跑四路。\n\n'
        '新会话实际打开成功；2个合成阶段检查验证错回合completion不会提前完成、断连会落盘且禁止继续。唯一新增付费探针：D:/agent-task-runs/wsc-native-application-phase-20261025-v1，1响应、22567 total tokens（input22542/cache11776/output25/reason14）、2.734秒；完成/结算完整，JSON ready=true，工作区不变，金额未知。该探针只验证新版本新模块的协议与结算，无工具或压缩，不计B/C成绩。\n\n'
        '付费探针后的审核发现cleanup异常会跳过账本落盘；保留其源码before-cleanup-guard.py.txt，新增异常保护。针对性前后检查证实旧版0条journal/无落盘，新版1条journal/回执存在并保留cleanup错误；未重跑付费探针。final-review.json明确paid版与当前版源哈希和唯一差异。\n\n'
        '四应用各15文件已冻结于D:/agent-task-runs/wsc-four-app-inputs-20261025-v1；含starter、八阶段请求、公开验收/人工程序，不含作者后端/其他任务/缓存。只证明包内白名单，未证明OS拒绝读取外部答案。A3及依赖未冻结。模型luna/max与二进制观测写入suite-draft，但候选、三次边界、累计预算、全矩阵worker协调和最终质量接入未完成，ready仍false。不要把四服务并行称为四条模型轨迹完成；不要重跑协议测量。下一步集中冻结C策略和边界、A3输入，接上累计预算及质量出口后启动首批两组成对。长期目标active。\n\n')
position = text.index('## 最新继续')
handoff.write_text(text[:position] + heading + note + text[position:], encoding='utf8')

report = '''# 当前原生运行接入记录（2026-10-25）

当前Codex已换版本，旧实验可执行文件不存在。新可选执行层验证了四服务并行、独立进程树回收、空线程历史物化和一次真实回合。完整15组研究未启动。

进程监督的结构性问题是原入口仅管理服务父进程，父进程退出不足以证明后台工具退出。新规则为每个worker在首次RPC握手前加入专属Windows Job，关闭时终止剩余成员；真实子进程前后检查验证了父退出后仍存活的子进程可被新规则回收。Job不是suspended创建，不能宣称覆盖所有赋权前产生的子进程。

异常留证的结构性问题是清理步骤位于保存回执之前且未隔离异常。新规则为清理异常作为结果字段保存，回执归档与阶段journal仍执行；针对性合成前后验证从无回执变为一条完整阶段记录。实际付费探针运行的是此修补前版本，最终审核明确保留两版哈希，不重复付费测量。

唯一新增付费协议回合：1响应，22567总token，2.734秒，账本完整，金额未知。它无工具/压缩调用，仅返回JSON。该消耗属于准备成本，不能作为WSC收益或完整应用交付。另有四路与历史/会话打开检查，均未启动模型回合。

依据[OpenAI Docs](https://learn.chatgpt.com/docs/app-server)核对initialize、turn/start、turn/interrupt及turn/completed接口；本机实际回执而非文档示例证明本轮行为。初始四路检查的rollout缺失失败保留，单独history探针证实当前空线程延迟持久化。新模块没有覆盖默认原生实现。

四个应用的起点、合同、验收代码已按白名单冻结，每任务15文件；A3和依赖仍待冻结。正式运行仍缺C候选与三次边界、累计预算和完整矩阵worker的质量出口/协调。输入白名单不等于阻止模型读取机器上的外部材料；读隔离尚无证明。
'''
report_path = ROOT / 'reviews/2026-10-25-native-application-execution.md'
with report_path.open('x', encoding='utf8') as stream:
    stream.write(report)
base = read(ROOT / 'validation/five-task-calibration-20261025/delivery.json')
assert file_hash(base['version']) == base['sha256']
source = {p.relative_to(ROOT).as_posix(): file_hash(p) for folder in ('src', 'experiments', 'tests')
          for p in sorted((ROOT / folder).rglob('*.py'))}
files = {name: ROOT / name for name in ('experiments/native_owned_process.py',
    'experiments/native_application_session.py', 'experiments/native_application_inputs.py',
    'experiments/NATIVE-LOCAL-HANDOFF.md', 'benchmarks/application-five-task-v1/suite-draft.json',
    'reviews/2026-10-25-native-application-execution.md')}
for path in HERE.rglob('*'):
    if path.is_file() and path.name != 'delivery.json' and '__pycache__' not in path.parts:
        files[path.relative_to(ROOT).as_posix()] = path
index = dict(format='native_application_execution_delta', base=base['version'], base_sha256=base['sha256'],
    source_manifest=source, files={n: file_hash(p) for n, p in files.items()},
    paid_probe_session_sha256=file_hash(old), current_session_sha256=file_hash(session),
    scope='Execution layer and four input packages; matrix/candidate qualification incomplete')
version = ROOT / 'versions/20261025-native-application-execution-v1-delta.zip'
with zipfile.ZipFile(version, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(n)).hexdigest() == h for n, h in index['files'].items())
result = dict(version=str(version), bytes=version.stat().st_size, sha256=file_hash(version),
    source_files=len(source), new_paid_responses=1, paid_protocol_total_tokens=22567,
    matrix_started=False, goal_complete=False)
save(HERE / 'delivery.json', result)
print(json.dumps(result))
