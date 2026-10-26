"""Retain frozen design/code/input versions without duplicating installed dependencies."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, manifest

review = read(HERE / 'review.json')
conditions_path = HERE / 'study-conditions-v1.json'
conditions = read(conditions_path)
assert file_hash(conditions_path) == review['conditions']['sha256']
transport_area = Path('D:/agent-task-runs/wsc-boundary-transport-20261025-v1')
transport = read(transport_area / 'result.json')
assert transport['status'] == 'native_fork_import_and_readonly_open_verified'
assert transport['new_responses'] == 0 and transport['parent_unchanged'] and transport['cleanup']['empty_confirmed']
save(HERE / 'transport-review.json', dict(path=str(transport_area / 'result.json'), sha256=file_hash(transport_area / 'result.json'),
    native_forks_and_import_verified=True, matched_observed_controls=True, readonly_start_accepted=True,
    native_compaction_or_generation_executed=False, provider_wire_equivalence_proven=False, model_calls=0))

suite_path = ROOT / 'benchmarks/application-five-task-v1/suite-draft.json'
suite = read(suite_path)
suite['execution']['candidate_WSC_version'] = dict(id=conditions['candidate']['id'],
    implementation_sha256=conditions['candidate']['implementation']['sha256'],
    registration=str(conditions_path), registration_sha256=file_hash(conditions_path))
suite['execution']['budgets'] = conditions['budgets']
suite['execution']['configuration_status'] = 'selection_policy_boundaries_budgets_frozen_full_native_coordination_pending'
for task in suite['tasks']:
    if task['id'] == 'a3':
        task['state'] = 'source_and_dependencies_frozen_browser_baseline_source_match_pipeline_pending'
        task['input_binding'] = review['A3']['binding']
        task['input_binding_sha256'] = review['A3']['binding_sha256']
suite['launch_blockers'] = [
    '原生fork和注入接口已零推理验证；完整三边界执行、原生压缩与只读生成回调尚未接入矩阵worker',
    '累计预算与质量判定组件已验证；每阶段预留/结算/回执和实际验收出口尚未整体接线',
    'A3源码和依赖基座已冻结；每臂私有依赖物化及新功能正向/人工审核出口待接入',
    '外部作者答案读取未有OS拒绝证明，运行时访问审计与无效观察规则仍需接入']
suite_path.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n', encoding='utf8')

handoff = ROOT / 'experiments/NATIVE-LOCAL-HANDOFF.md'
text = handoff.read_text(encoding='utf8')
heading = '## 最新继续：2026-10-25 增量候选、A3输入、累计预算与质量条件冻结\n\n'
assert heading not in text
note = ('C候选incremental_recorded_spans_v1已在validation/application-freeze-20261025/study-conditions-v1.json登记，绑定实现与核心源码清单。新增native_incremental_candidate：新阶段文本+旧源冷入口+模型明确保留的理解修订/原文；不再自动把上轮整段assistant消息装入下轮。模型可修订记录、显式留旧片段；旧观察时间/hash/版本不升级为当前结论，rendered上限49152字节、body131072、material2097152，超限/非法选择不回退也不重试。5项检查含三次实际导出，均discard且不冒称host安装；没有实际模型选材或收益证明。\n\n'
        '新增native_application_budget/quality。累计预算：普通阶段32响应/600秒/750000总token，边界12/180/400000，每臂120/2700/6000000，全研究3600/28800/180000000（含缓存输入，不等于费用）；所有生成/压缩都从同臂扣。并发预留不重复花已预留额度，超额整笔计，未知保留已知并冻结新调用。质量要求当前源码/辅助包、完整自动项和有证据人工项，单自动通过不能变完整应用。质量组件首版实际复现“外层CURRENT绑定包装OLD登记仍通过”，已同时核对原登记/结果/单项回执/同运行目录；前后passed→unknown，源版本留存。当前预算/质量9项通过，加候选5项共14项，详见final-check-scope.json。\n\n'
        'A3输入D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1已完成：824源码/任务文件、41935依赖文件、656671688字节。先前串行复制因实测吞吐被明确停止；第一次并行resume的containment断言失败，具体瞬时路径未记下，静态复查未发现越界。最终预校验目录/相对清单、逐文件源目标hash完成，复用41887文件，只补48；不重复已验证复制。实际Node24.14.0/React19.2.8/Vite6.4.3/Playwright1.62.1及Chromium二进制已pin。src/package/lock与原A3验收基线精确相同，未重跑旧截图。依赖与每臂私有副本无hardlink/junction共享可写状态；实际私有物化待worker。\n\n'
        '计划三次边界S2/S4/S6：B用原生压缩后native fork，C用sealed初始bootstrap native fork+精确WSC导入，双方均native fork以减少接入混杂；真实compaction/选材尚未接入。新增零推理boundary_transport_probe已用既有一次付费协议线程验证full-parent和initial-parent双fork，继承1/0响应，已观察host配置相同，C事实注入原值匹配，另开read-only选择线程被接受；父文件不变、0新增响应、所有进程已退出。该检查未调用compactor/模型选材，不证明完整边界或模型wire等价。\n\n'
        '本轮0新增模型响应，正式5×3研究未启动。下一步直接接完整矩阵worker（fork结算、实际compaction、只读selection、三个边界、质量出口和累计ledger），做准入后启动首批；不再重跑上述基础校准/旧截图/旧JSONL题。所有句柄终态，无等待任务。长期目标active。\n\n')
position = text.index('## 最新继续')
handoff.write_text(text[:position] + heading + note + text[position:], encoding='utf8')

report_path = ROOT / 'reviews/2026-10-25-application-study-freeze.md'
report = '''# 五任务研究条件冻结记录

C候选固定为incremental_recorded_spans_v1：原文冷档保真，新阶段文本进入本次选材，前次理解和原文片段由模型显式选择复用或修订，用户控制消息继续保留。旧检查的时间与版本不会被运行时改为当前通过。热导出设49152字节上限，超限保留失败而不静默截断或回退全历史。5项离线检查包含三次导出；尚未验证真实模型的选材效果。

预算和质量组件已完成针对性验证。预算按响应边界监督，包含压缩/生成和全部已知失败消耗，无法承诺提供商硬性token上限；未知总量冻结新调用。登记每臂600万、研究1.8亿总token上限，含缓存输入，并非实际用量或货币预算。每臂45分钟/120响应，研究8小时/3600响应，阶段与边界另有限额。当前研究尚未启动；本轮新增模型响应0。

质量判定不能仅信外层源码标识：真实复现了首版可将旧登记包装为当前通过，已改为连同原始登记、结果、单项回执和同一输出目录核对。针对性前后从passed变unknown，原版源码与两份结果保留。当前预算/质量9项、候选5项合计14项通过；不代表完整界面或真实WSC收益。

A3源码与任务824文件、依赖41935文件（约657MB）已冻结，原始GUI未改。源码/包声明/锁与旧浏览器基线相同，直接复用其来源事实。串行复制的吞吐较低，保留部分改用并行校验；一次并行路径断言失败的具体原因未证实，静态复查无逃逸路径。最终采用先验证固定清单与目录，再逐文件校验源/目标字节，复用41887文件、只补48文件。每臂仍需私有物化，不共享可写node_modules。

三次边界固定在S2/S4/S6。两边均使用原生fork：B继承原生压缩结果，C从sealed初始bootstrap导入WSC视图。已在新原生版本上零推理验证双fork、相同已观察host配置、事实导入和read-only选择线程打开，父线程不变。未调用实际压缩和选择生成，不声称完整协议或wire等价。

下一步是连接完整矩阵worker的实际压缩/选择、fork累计结算、预算与外部质量出口，完成准入后启动首批两组。15组正式结果仍缺失，ready_to_launch继续false。
'''
with report_path.open('x', encoding='utf8') as stream:
    stream.write(report)

base = read(ROOT / 'validation/native-worker-20261025/delivery.json')
assert file_hash(base['version']) == base['sha256']
source = {p.relative_to(ROOT).as_posix(): file_hash(p) for folder in ('src', 'experiments', 'tests')
          for p in sorted((ROOT / folder).rglob('*.py'))}
files = {name: ROOT / name for name in (
    'experiments/native_incremental_candidate.py', 'experiments/native_application_budget.py',
    'experiments/native_application_quality.py', 'tests/test_native_incremental_candidate.py',
    'tests/test_native_application_limits_quality.py', 'experiments/NATIVE-LOCAL-HANDOFF.md',
    'benchmarks/application-five-task-v1/suite-draft.json', 'reviews/2026-10-25-application-study-freeze.md')}
for path in HERE.rglob('*'):
    if path.is_file() and path.name != 'delivery.json' and '__pycache__' not in path.parts:
        files[path.relative_to(ROOT).as_posix()] = path
a3 = read(review['A3']['binding'])
frozen_root = Path(a3['workspace'])
for key, value in a3['source_manifest'].items():
    assert file_hash(frozen_root / key) == value
    files['frozen-inputs/a3/' + key] = frozen_root / key
for name in ('input-binding.json', 'dependency-source-manifest.json', 'runtime.json',
             'copy-resume-registration.json', 'copy-completion-registration.json'):
    files['frozen-inputs/a3-bindings/' + name] = Path(review['A3']['binding']).parent / name
files['validation/application-freeze-20261025/native-boundary-result.json'] = transport_area / 'result.json'
index = dict(format='incremental_candidate_and_study_inputs_delta', base=base['version'], base_sha256=base['sha256'],
    source_manifest=source, files={n: file_hash(p) for n, p in files.items()},
    installed_dependencies_archived=False, installed_dependency_manifest_sha256=a3['dependency_manifest_sha256'],
    scope='Policy/code/input freeze and bounded checks, not complete matrix worker or model-benefit proof')
version = ROOT / 'versions/20261025-incremental-candidate-study-freeze-v1-delta.zip'
with zipfile.ZipFile(version, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(n)).hexdigest() == h for n, h in index['files'].items())
result = dict(version=str(version), bytes=version.stat().st_size, sha256=file_hash(version),
    source_files=len(source), installed_dependencies_copied_to_version=False, new_model_responses=0,
    study_started=False, goal_complete=False)
save(HERE / 'delivery.json', result)
print(json.dumps(result))
