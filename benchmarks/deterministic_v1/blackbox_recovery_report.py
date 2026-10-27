"""Two-boundary answer/cost/recovery evidence, with unknowns kept separate."""
from pathlib import Path
import argparse,json,csv,statistics
from blackbox import score_answer
from blackbox_group_report import paired_interval

PHASES={'uncompressed':['uncompressed-probe'],'native':['B1-compression','B2-compression','native-probe'],
        'wsc':['C1-selection','C2-selection','wsc-probe']}


def collect(root):
    root=Path(root);result=json.loads((root/'result.json').read_text());oracle=json.loads((root/'oracle.private.json').read_text());rows=[]
    for repetition,cell in sorted(result['repetitions'].items(),key=lambda p:int(p[0])):
        folder=root/f'R{int(repetition):02d}'
        for arm,names in PHASES.items():
            phases={name:json.loads((folder/name/'phase-outcome.json').read_text()) for name in names if (folder/name/'phase-outcome.json').exists()}
            complete=len(phases)==len(names) and all(p.get('completed') and p.get('usage_complete') and not p.get('failure') for p in phases.values())
            entries=[r for phase in phases.values() for r in phase.get('receipts',{}).get('response_receipts',[])]
            known=sum(r['usage']['total_tokens'] for r in entries)
            answer_phase=phases.get(names[-1],{})
            score=None
            if names[-1].endswith('probe') and len(answer_phase.get('finals',[]))==1:score=score_answer(answer_phase['finals'][0]['text'],oracle)
            rows.append(dict(repetition=int(repetition),arm=arm,cell_status=cell['status'],cost_complete=complete,
                total_tokens=known if complete else None,known_partial_tokens=known if not complete and entries else None,
                responses=len(entries),phase_seconds=sum(p['seconds'] for p in phases.values()) if complete else None,
                score=score,stage_tokens={name:p.get('receipts',{}).get('all_usage',{}).get('total_tokens') for name,p in phases.items()},
                target_nonce_literal_in_second_selector_input=cell.get('target_nonce_literal_in_second_selector_input') if arm=='wsc' else None,
                recovery=cell.get('recovery_evidence') if arm=='wsc' else None,
                old_sources_without_inline_spans=cell.get('old_sources_without_inline_spans'),
                internal_context_tokens=None))
    paired={}
    for field in ('total_tokens','phase_seconds'):
        values=[]
        for repetition in sorted({r['repetition'] for r in rows}):
            arms={r['arm']:r for r in rows if r['repetition']==repetition}
            if all(arms[arm][field] is not None for arm in ('native','wsc')):values.append(arms['wsc'][field]-arms['native'][field])
        paired[field+'_wsc_minus_native']=paired_interval(values)
    return dict(schema='wsc.blackbox.two-boundary-report/1',status=result['status'],rows=rows,paired=paired,
        total_known_tokens=result['ledger']['study']['tokens'],total_responses=result['ledger']['study']['responses'],
        accounting_complete=not result['ledger']['study']['uncertain'] and not result['ledger']['inflight'],
        total_wall_seconds=result['seconds'],cash=None,whole_campaign_usage_complete=False)


def write(root):
    root=Path(root);report=collect(root)
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with (root/'report.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['repetition','arm','status','correct','total_tokens','known_partial_tokens','responses','phase_seconds','nonce_literal_in_second_selector'])
        for r in report['rows']:
            writer.writerow([r['repetition'],r['arm'],r['cell_status'],r['score']['counts']['correct'] if r['score'] else None,r['total_tokens'],r['known_partial_tokens'],r['responses'],r['phase_seconds'],r['target_nonce_literal_in_second_selector_input']])
    lines=['# 两次压缩后的旧构建回执恢复','',f"整组状态：{report['status']}；当前没有完整三次B/C结论。",'',
        '三次并行配对，固定目标build-003；原生两次真实压缩，WSC两次正常模型选材与实际导入。第二轮129条旧来源不直接提供正文/span；用户新任务与最终问题相同，无额外模型裁判。','',
        '| 重复 | 分支 | 正确数/2 | 完整调用Token | 模型阶段秒数 |','| --- | --- | --- | --- | --- |']
    for r in report['rows']:
        correct=r['score']['counts']['correct'] if r['score'] else '未知'
        token=r['total_tokens'] if r['total_tokens'] is not None else f"未知（已知部分{r['known_partial_tokens']}）"
        seconds=f"{r['phase_seconds']:.2f}" if r['phase_seconds'] is not None else '未知'
        lines.append(f"| {r['repetition']} | {r['arm']} | {correct}/2 | {token} | {seconds} |")
    lines+=['',f"本轮已知{report['total_known_tokens']} Token、{report['total_responses']}响应；本地用量闭合{report['accounting_complete']}。总运行墙钟{report['total_wall_seconds']:.2f}秒；分支模型阶段耗时不等于完整产品延迟。历史未知和金额未知保留。",'',
        '## 恢复证据','']
    for r in report['rows']:
        if r['arm']!='wsc':continue
        evidence=r.get('recovery') or {}
        lines.append(f"- R{r['repetition']:02d}：第二轮输入含目标nonce原样值={r['target_nonce_literal_in_second_selector_input']}；旧正文/span未直接提供={r['old_sources_without_inline_spans']}。")
        for name,proof in evidence.items():lines.append(f"  - {name}：完整旧来源对象出现在模型工具结果={proof['full_source_object_observed']}；目标回执对象出现在模型工具结果={proof['target_receipt_observed']}；行号{proof['exact_objects_in_model_tool_outputs']}。")
    lines+=['','## 边界','',
        '- 程序严格比较nonce字符串和当前build_number；正确回答不是“摘要完整”的证明。nonce原样值扫描仅为曝光诊断，不作为正确率评分或语义完整性判定。',
        '- 恢复证据只采集原生模型工具输出，解析JSON对象并与绑定旧来源/回执完全比较。引擎自己做的hash可访问性检查、assistant自述和关键词出现均不算模型恢复。未匹配到对象也不直接断言没有恢复，可能是只输出了字段或不同工具格式。',
        '- 两次真实原生compacted证据分别保存在B1/B2-compression-proof.json；WSC实际包、continuation和生成草稿保存。没有伪造HostReceipt，未证明原子core.install。',
        '- 同模型/effort和共用无业务启动父线程；原生内部模型、温度、seed、上下文Token与恢复内部成本不可控，属于系统级比较。未提供额外原始归档给原生；WSC使用自身设计的存储恢复资源。',
        '- 没有专门禁用恢复的消融分支，不能从正确率单独作严格恢复因果归因。仅一个结构化构建回执续接案例、三次重复、两次边界，不能推广到5/10/20/50次或大型应用长期任务。','',
        '下一步依据失败/成本与真实工具恢复证据决定，不自动扩大付费矩阵，不删除失败或重置预算。']
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    report=write(args.root);print(json.dumps(dict(status=report['status'],tokens=report['total_known_tokens'],responses=report['total_responses'],paired=report['paired'])))


if __name__=='__main__':main()
