"""Freeze a new real-code task; this entry point performs no model inference."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil

from native_evidence import digest, file_hash, manifest, read, save
from native_task_checks import grade, require
from run_native_pair import MODEL, SETTINGS
from native_phase_budget import PhaseBudget

HERE = Path(__file__).resolve().parent
FIRST = ['CommandStreamTests.'+name for name in (
    'test_valid_unicode_response_and_partial_usage', 'test_stdout_limit_stops_child_before_followup_action',
    'test_timeout_remains_neutral_and_child_stops', 'test_invalid_selection_retains_returned_usage')]
ALL = FIRST + ['CommandStreamTests.'+name for name in (
    'test_stderr_overflow_is_bounded_even_with_valid_stdout', 'test_simultaneous_streams_finish_without_deadlock',
    'test_stderr_exact_byte_limit_and_utf8_are_not_character_counted', 'test_invalid_limits_fail_before_child_start')]
TASK_BUDGET = {'max_responses':24, 'max_seconds':600, 'max_total_tokens':1500000}
STAGES = [
    {'id':'source_task', 'methods':FIRST, 'budget':TASK_BUDGET,
     'message':'修复这个独立WSC库的可选命令生成器输出限制：现有JsonCommandGenerator在子进程退出后才检查stdout大小，超限期间子进程仍继续执行。请以独立旁路模块wsc.bounded_generation提供BoundedJsonCommandGenerator，保留argv、cwd、timeout、max_output_bytes调用形态和Generated/Usage返回语义，已有模块及默认行为保持。stdout按字节计数，运行中发现超限即停止并回收直接子进程，返回中性generation_output_budget_exhausted；不能先无限收集到内存或临时文件再检查。成功、超时、非法选材已有用量和未知用量语义保持。当前阶段不要求stderr限额或孙进程树治理；请完成必要检查与阶段交付，说明边界。'},
    {'id':'expanded_task', 'methods':ALL, 'budget':TASK_BUDGET,
     'message':'继续同一旁路修复，新增stderr约束：为BoundedJsonCommandGenerator增加正整数字节限额max_stderr_bytes，默认65536；stdout原限额继续生效，两路须同时消费，避免双流阻塞。stderr超限即停止并回收直接子进程，返回generation_stderr_budget_exhausted，即使stdout已输出合法JSON也不得报成功。stderr内容不进入公开错误文本；恰好等于限额允许，UTF-8按字节计数，非法限额在启动子进程前拒绝。保留上一阶段行为、已返回用量和未知用量边界；不扩展到孙进程树治理。请实现新增要求，验证当前版本并完成交付。'},
    {'id':'handoff', 'methods':None, 'budget':{'max_responses':4, 'max_seconds':120, 'max_total_tokens':400000},
     'message':'请依据当前工作区与已取得证据完成最终交接：说明实际实现、当前版本验证范围、旧阶段证据的适用范围和仍未覆盖的问题。'}]


def prepare(area, executable, runtime):
    area, executable, runtime = area.resolve(), executable.resolve(), runtime.resolve()
    require(not area.exists(), 'bounded_study_already_exists')
    for stage in STAGES:
        PhaseBudget.resolve({'phase_budget':stage['budget']}, begin=0, deadline=stage['budget']['max_seconds'])
    provenance = runtime.parent/'provenance.json'
    runtime_paths = []
    for name, expected in read(provenance)['runtime_sha256'].items():
        path = (runtime.parent/name).resolve()
        require(path.is_relative_to(runtime.parent) and file_hash(path)==expected, 'bounded_runtime_changed')
        runtime_paths.append(path)
    area.mkdir()
    frozen = area/'frozen-workspace'
    shutil.copytree(HERE.parent/'src', frozen/'src', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (frozen/'tests').mkdir()
    shutil.copy2(HERE.parent/'tests/test_generation_failures.py', frozen/'tests/test_generation_failures.py')
    shutil.copy2(HERE.parents[1]/'AGENTS.md', frozen/'AGENTS.md')
    shutil.copytree(frozen, area/'workspace')
    grader = HERE/'bounded_command_grader.py'
    pins = [executable, runtime, provenance, *runtime_paths, HERE.parents[1]/'AGENTS.md']
    pins += [p for folder in ('src','tests','experiments') for p in (HERE.parent/folder).rglob('*.py')]
    config = Path.home()/'.codex/config.toml'
    if config.exists(): pins.append(config)
    initial = manifest(frozen)
    reg = {'purpose':'bounded_command_C_qualification_only', 'registered_utc':datetime.now(timezone.utc).isoformat(),
           'origin':str(area), 'workspace':str(area/'workspace'), 'executable':str(executable),
           'model':MODEL, 'effort':'max', 'settings':SETTINGS, 'dynamic_tools':[],
           'initial_manifest':initial, 'grader':str(grader), 'stages':STAGES, 'require_final':True,
           'protected_paths':[p for p in initial if p.startswith('src/') or p=='AGENTS.md'],
           'runtime_command':[str(runtime)], 'pins':{str(p.resolve()):file_hash(p) for p in pins},
           'candidate':{'checkpoint_mode':'host_messages','selection':'original_messages_and_observations',
                        'presentation':'host_bound_recorded','generation_calls':0},
           'scope':'New staged real-code task. One WSC boundary before requirement expansion; handoff follows in same C thread. Not long-horizon proof or B/C comparison.',
           'stop':'Failure, unknown usage, missing final, protected-file change or cap stops later stages. No restart, retry or cap extension.',
           'accounting':'All new source and C phases counted; no failed-run exclusion. Token overshoot is fully retained.',
           'limits':{'retries':0,'B_calls':0,'forced_compactions':0}}
    save(area/'registration.json',reg)
    baseline = grade(area/'workspace',grader,ALL,area/'baseline')
    failed_methods = {item['test'].split(' (')[0].removeprefix('_task_grader.')
                      for item in baseline['failures']}
    require(baseline['tests']==8 and failed_methods==set(ALL) and not baseline['errors'],
            'bounded_baseline_changed')
    save(area/'prepared.json', {'registration_sha256':file_hash(area/'registration.json'),
                               'baseline_sha256':file_hash(area/'baseline/receipt.json'),
                               'failed_methods':sorted(failed_methods), 'model_calls':0})
    print({'prepared':str(area),'failed_methods':len(failed_methods),
           'failure_entries':len(baseline['failures']),'model_calls':0})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','run'])
    parser.add_argument('area',type=Path)
    parser.add_argument('--executable',type=Path)
    parser.add_argument('--runtime',type=Path)
    args=parser.parse_args()
    if args.action=='prepare':
        prepare(args.area,args.executable,args.runtime)
    else:
        from run_control_continuation import run
        prepared = read(args.area/'prepared.json')
        require(file_hash(args.area/'registration.json')==prepared['registration_sha256']
                and file_hash(args.area/'baseline/receipt.json')==prepared['baseline_sha256'],
                'bounded_preparation_changed')
        run(args.area.resolve(),stages=STAGES)
