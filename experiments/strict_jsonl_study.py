"""New two-boundary task and immutable preparation; no inference during prepare."""
from datetime import datetime,timezone
from pathlib import Path
import shutil

from native_evidence import read,save,manifest,file_hash
from native_task_checks import grade,require
from run_native_pair import MODEL,SETTINGS

HERE=Path(__file__).resolve().parent
FIRST=['StrictJSONLTests.'+n for n in (
 'test_unicode_physical_lines_and_raw_identity','test_duplicate_keys_at_all_object_depths_are_rejected',
 'test_strings_are_not_recursively_decoded','test_partial_tail_and_missing_file_observations_remain_distinct',
 'test_invalid_interior_and_record_shapes_are_rejected')]
SECOND=FIRST+['StrictJSONLTests.'+n for n in (
 'test_nonfinite_values_and_overflow_numbers_are_rejected',
 'test_complete_unterminated_nonfinite_tail_is_not_silently_dropped',
 'test_finite_numbers_keep_integer_precision_and_float_values')]
ALL=SECOND+['StrictJSONLTests.'+n for n in (
 'test_line_budget_is_bytes_and_includes_cr_but_excludes_lf',
 'test_oversized_invalid_line_is_rejected_before_decoding','test_default_unlimited_and_invalid_budget_values')]
BUDGET={'max_responses':24,'max_seconds':600,'max_total_tokens':1500000}
STAGES=[
 {'id':'source_task','methods':FIRST,'budget':BUDGET,'message':
  '真实原生JSONL读取器已按原字节复制到src/wsc/native_rollout_snapshot.py。其json.loads会静默覆盖重复键。请新增独立旁路src/wsc/strict_jsonl.py，提供parse_strict_rollout(raw: bytes, *, exists=True)，返回既有RolloutSnapshot兼容对象，不修改既有文件或默认读取器。任何对象深度的重复键（含解码后等价键、同值重复）都以ValueError("rollout_duplicate_key:line=N")拒绝，不泄露键或载荷；完整但无末尾换行的重复键记录也必须拒绝。payload中的字符串不递归解析，合法Unicode（含U+2028）、整数精度、物理LF行号、原始字节哈希与长度保留。沿用旧读取器的真实部分尾行/坏UTF-8尾行观察及缺文件语义，中间坏行和错误记录形状继续拒绝。当前阶段非有限数值与行字节预算留待后续要求；完成必要检查和阶段交付。'},
 {'id':'finite_task','methods':SECOND,'budget':BUDGET,'message':
  '继续同一旁路，新增数值保真约束：任意层级的NaN、Infinity、-Infinity，以及转换为Python浮点后溢出为非有限值的合法数字如1e9999，均以ValueError("rollout_nonfinite_number:line=N")拒绝。完整但无末尾换行的此类记录不能被误当部分尾行丢弃。有限浮点和任意本任务合法大整数保持值与类型，普通字符串中的同形文本保持原文。上一阶段重复键、UTF-8、物理行号、原始哈希和真正部分尾行规则保持；若同一记录有多种错误，不约定错误优先级。请验证当前版本并交付。'},
 {'id':'line_budget_task','methods':ALL,'budget':BUDGET,'message':
  '继续同一旁路，新增parse_strict_rollout(..., max_line_bytes=None)：None保持无额外单行限额，启用值必须是正整数且排除bool，非法值以ValueError("rollout_line_budget_invalid")拒绝。每个物理LF分隔段在跳过空白、UTF-8解码和JSON解析前按原字节检查；LF分隔符不计，CR计入；空白段也受限，恰好等于允许。超限以ValueError("rollout_line_budget_exhausted:line=N")拒绝，包括无末尾换行或本身编码无效的段。raw本来已在内存，这不是整个来源读取内存上限，也不是跨文件原子快照。保留前两阶段行为，既有文件及默认读取器保持。请完成检查和当前交付。'},
 {'id':'handoff','methods':None,'budget':{'max_responses':4,'max_seconds':120,'max_total_tokens':400000},'message':
  '请依据当前工作区与已有证据完成最终交接：当前实现、当前版本验收范围、旧阶段回执适用范围、未知或未覆盖问题。'}]
COMPACT_BUDGET={'max_responses':1,'max_seconds':180,'max_total_tokens':250000}


def prepare(area):
 area=Path(area).resolve();require(not area.exists(),'study_already_exists');area.mkdir()
 old=read('D:/agent-task-runs/wsc-bounded-command-20261023-v2/registration.json')
 frozen=area/'frozen-workspace'
 shutil.copytree(HERE.parent/'src',frozen/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 shutil.copy2(HERE/'native_rollout_snapshot.py',frozen/'src/wsc/native_rollout_snapshot.py')
 shutil.copy2(HERE.parents[1]/'AGENTS.md',frozen/'AGENTS.md');(frozen/'tests').mkdir()
 shutil.copytree(frozen,area/'workspace')
 initial=manifest(frozen)
 paths=[p for f in ('src','tests','experiments') for p in (HERE.parent/f).rglob('*.py')]
 paths += [Path(old['executable']),Path.home()/'.codex/config.toml',HERE.parents[1]/'AGENTS.md']
 paths += [HERE/'STRICT-JSONL-PAIR-20261023.md',HERE.parent/'validation/strict-jsonl-study-20261023/baseline-reader.json',
           Path('D:/agent-task-runs/wsc-strict-jsonl-calibration-20261023-v1/calibration.json')]
 runtime=Path(old['runtime_command'][0]);provenance=runtime.parent/'provenance.json'
 paths.append(provenance)
 for name,h in read(provenance)['runtime_sha256'].items():
  path=(runtime.parent/name).resolve();require(path.is_relative_to(runtime.parent) and file_hash(path)==h,'runtime_changed');paths.append(path)
 reg={'purpose':'comparison','registered_utc':datetime.now(timezone.utc).isoformat(),
  'origin':str(area),'workspace':str(area/'workspace'),'executable':old['executable'],
  'model':MODEL,'effort':'max','settings':SETTINGS,'dynamic_tools':[],
  'initial_manifest':initial,'protected_paths':list(initial),'grader':str(HERE/'strict_jsonl_grader.py'),
  'runtime_command':old['runtime_command'],'pins':{str(p.resolve()):file_hash(p) for p in paths},
  'stages':STAGES,'compaction_budget':COMPACT_BUDGET,'admission_warmup_threads':1,
  'review_wait_seconds':600,'retries':0,'order':'shared source, C1, C2, C handoff, review, B compact/finite/compact/budget/handoff',
  'stop':'Any failed phase, missing final, unknown usage, failed acceptance, protected change or host drift stops later stages. No restart or extension.',
  'scope':'One new two-boundary task. Same retained host cohort, source history, cwd, task budgets and checks. Fixed-order single-task evidence only.'}
 save(area/'registration.json',reg)
 baseline=grade(area/'workspace',reg['grader'],ALL,area/'baseline')
 require(baseline['tests']==11 and not baseline['passed'] and len(baseline['failures'])==11 and not baseline['errors'],'baseline_mismatch')
 save(area/'prepared.json',{'registration_sha256':file_hash(area/'registration.json'),'baseline_sha256':file_hash(area/'baseline/receipt.json'),'model_calls':0})
 print({'prepared':str(area),'baseline_failed':baseline['tests'],'model_calls':0},flush=True)
