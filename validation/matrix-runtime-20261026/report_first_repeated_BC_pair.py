"""Report the first closed pair from saved receipts, never current workspaces."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash
AREA=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1/execution-v2/R01')
assert (AREA/'pair-result.json').is_file(),'first_pair_still_running'
pair=read(AREA/'pair-result.json')
rows={}
for arm in ('B','C'):
    result=read(AREA/arm/'result.json')
    phase=read(AREA/arm/'phase-journal.json')
    grade=read(AREA/arm/'qualification.json')
    value=phase['receipts']['all_usage']
    rows[arm]=dict(native_completed=result.get('native_completed') is True,
        qualified=grade['qualification_passed'],functional_checks_and_scroll=grade.get('functional_17_and_scroll'),
        usage_complete=result.get('usage_complete') is True and not result.get('accounting_mismatch'),
        known_tokens=value['total_tokens'],input_tokens=value['input_tokens'],cached_input_tokens=value['cached_input_tokens'],
        uncached_input_tokens=value['input_tokens']-value['cached_input_tokens'],output_tokens=value['output_tokens'],
        responses=phase['receipts']['response_count'],compactions=len(phase['receipts']['compactor_response_ids']),
        seconds=phase['seconds'],failure=result.get('failure'),error=result.get('error'),cleanup_empty=result['cleanup']['empty_confirmed'],
        phase_sha256=file_hash(AREA/arm/'phase-journal.json'),grade_sha256=file_hash(AREA/arm/'qualification.json'))
same_success=all(row['qualified'] and row['usage_complete'] for row in rows.values())
comparison=None
if same_success:
    comparison=dict(C_token_change_percent=100*(rows['C']['known_tokens']/rows['B']['known_tokens']-1),
        C_stage_seconds_change_percent=100*(rows['C']['seconds']/rows['B']['seconds']-1))
summary=dict(pair=1,scope='One paired continuation from fixed compressed S2 states, not three-pair result or full five-task matrix',
    arms=rows,comparison_on_same_success_condition=comparison,
    causal_significance_proven=False,WSC_semantic_attribution_proven=False,whole_campaign_usage_complete=False,
    pair_receipt_sha256=file_hash(AREA/'pair-result.json'))
save(AREA/'first-report.json',summary)
fmt=lambda v:f'{v:,}'
text='第一组 B/C 结果\n\n| 指标 | B：默认原生 | C：WSC包＋更早原生压缩 |\n| --- | --- | --- |\n'
for title,key in [('原生正常结束','native_completed'),('独立资格验收通过','qualified'),('17项与滚动通过','functional_checks_and_scroll'),
    ('本臂用量完整','usage_complete'),('已知 token','known_tokens'),('未缓存输入','uncached_input_tokens'),('输出 token','output_tokens'),
    ('响应次数','responses'),('阶段内压缩次数','compactions'),('阶段秒数','seconds')]:
    values=[]
    for arm in ('B','C'):
        val=rows[arm][key]
        values.append(('是' if val else '否') if type(val) is bool else ('未知' if val is None else fmt(val) if type(val) is int else f'{val:.3f}'))
    text+=f'| {title} | {values[0]} | {values[1]} |\n'
text+='\n'
if comparison:
    text+=f"在本组相同成功条件下，C token变化{comparison['C_token_change_percent']:+.2f}%，阶段耗时变化{comparison['C_stage_seconds_change_percent']:+.2f}%。这是一次观察，不是统计效应或费用优势证明。\n\n"
else:
    text+='两侧尚不满足“都正确完成且用量完整”的可比条件，不将失败或未知一侧的较低已知token当作节省。\n\n'
for arm in ('B','C'):
    if rows[arm]['failure'] or rows[arm]['error']:
        text+=f"{arm}失败记录：{rows[arm]['failure'] or rows[arm]['error']}。\n\n"
text+='本报告只依据第一组已封存结果。两侧共享原始S2历史和补充观察，各自使用固定压缩状态；未覆盖压缩生成波动。C同时包含选材和更早压缩，不能单独归因为WSC语义能力。一次性准备及历史失败另行保留，不是零成本。\n\n下一步：保留第一组，继续已登记的第二、三组，之后一起比较成功率、完整用量和波动。五任务长期目标尚未完成。\n'
with (AREA/'first-report.md').open('x',encoding='utf-8') as stream:stream.write(text)
print(summary)
