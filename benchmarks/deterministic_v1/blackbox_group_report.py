"""Receipt-bound group report; no judge and no inferred opaque token counts."""
from pathlib import Path
import argparse,csv,itertools,json,math,statistics
from dataset import canonical

PHASES={'uncompressed':['uncompressed-probe'],'native':['native-compression','native-probe'],
        'wsc':['selection-phase','wsc-probe']}


def paired_interval(values):
    if not values:return None
    # Descriptive exact bootstrap over paired repetitions, never over questions.
    means=sorted(statistics.mean(sample) for sample in itertools.product(values,repeat=len(values)))
    return dict(mean=statistics.mean(values),minimum=min(values),maximum=max(values),
        empirical_bootstrap_95=[means[int(.025*(len(means)-1))],means[math.ceil(.975*(len(means)-1))]],
        repetitions=len(values),scope='Descriptive paired bootstrap; tiny sample and shared runtime do not establish population reliability.')


def collect(root):
    root=Path(root);result=json.loads((root/'result.json').read_text());rows=[]
    reused=Path(result['reused_group']) if result.get('reused_group') else None
    native_post=Path(result['reused_native_post_group']) if result.get('reused_native_post_group') else None
    registration_path=(reused or root)/'registration.json'
    registration=json.loads(registration_path.read_text()) if registration_path.exists() else {}
    for repetition,cell in sorted(result['repetitions'].items(),key=lambda p:int(p[0])):
        for arm,names in PHASES.items():
            costs=[]
            files=[]
            for name in names:
                base=reused if reused and name in ('uncompressed-probe','native-compression') else root
                if native_post and name=='native-probe':base=native_post
                path=base/f'R{int(repetition):02d}'/name/'phase-outcome.json';files.append(str(path))
                if path.exists():costs.append(json.loads(path.read_text()))
            complete=len(costs)==len(names) and all(p.get('completed') and p.get('usage_complete') and not p.get('failure') for p in costs)
            scores=cell.get('scores',{}).get(arm,{});counts=scores.get('counts',{})
            known=[p.get('receipts',{}).get('all_usage',{}) for p in costs]
            fields=('total_tokens','input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens')
            usage={key:sum(u[key] for u in known if type(u.get(key)) is int) if any(type(u.get(key)) is int for u in known) else None for key in fields}
            complete=complete and all(all(type(u.get(key)) is int for key in fields) for u in known)
            # A missing cost is unknown. A known partial cost remains separately visible.
            rows.append(dict(repetition=int(repetition),arm=arm,status=cell['status'],complete=complete,
                correct=counts.get('correct'),scored=sum(counts.get(k,0) for k in ('correct','incorrect','missing','invalid')) if counts else None,
                usage=usage if complete else None,known_partial_usage=usage if not complete else None,
                phase_seconds=sum(p['seconds'] for p in costs) if complete else None,
                responses=sum(len(p.get('receipts',{}).get('response_receipts',[])) for p in costs),
                raw_public_bytes=cell.get('raw_public_bytes'),wsc_package_bytes=cell.get('wsc_package_bytes') if arm=='wsc' else None,
                persisted_bytes=cell.get('persisted_wsc_bytes') if arm=='wsc' else None,
                internal_context_tokens=None,phase_files=files))
    paired={}
    for metric in ('total_tokens','phase_seconds','accuracy'):
        values=[]
        for repetition in sorted({r['repetition'] for r in rows}):
            arms={r['arm']:r for r in rows if r['repetition']==repetition}
            if all(arms[k]['complete'] for k in ('native','wsc')):
                if metric=='accuracy':
                    if not all(arms[k]['scored'] for k in ('native','wsc')):continue
                    b=arms['native']['correct']/arms['native']['scored'];c=arms['wsc']['correct']/arms['wsc']['scored']
                else:
                    b=arms['native']['usage'][metric] if metric=='total_tokens' else arms['native'][metric]
                    c=arms['wsc']['usage'][metric] if metric=='total_tokens' else arms['wsc'][metric]
                values.append(c-b)
        paired[metric+'_wsc_minus_native']=paired_interval(values)
    return dict(schema='wsc.blackbox.group-report/1',status=result['status'],rows=rows,paired=paired,
        case=registration.get('case'),checkpoint=registration.get('checkpoint'),
        answer_failures=[dict(repetition=int(rep),arm=arm,**detail) for rep,cell in result['repetitions'].items()
            for arm,score in cell.get('scores',{}).items() for detail in score['details'] if detail['verdict']!='correct'],
        actual_group_tokens=result['ledger']['study']['tokens']+result.get('reused_tokens',0),actual_group_responses=result['ledger']['study']['responses']+result.get('reused_responses',0),
        newly_consumed_tokens=result['ledger']['study']['tokens'],reused_tokens=result.get('reused_tokens',0),
        accounting_complete=not result['ledger']['study']['uncertain'] and not result['ledger']['inflight'],
        cash=None,internal_context_tokens=None,
        interpretation='Observed system answers and receipt costs, not proof of summary content, fixed-context-token dominance or long-term task success.')


def write(root):
    root=Path(root);report=collect(root)
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with (root/'report.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.writer(stream);writer.writerow(['repetition','arm','complete','correct','scored','total_tokens','input_tokens','cached_input_tokens','output_tokens','phase_seconds','responses','internal_context_tokens'])
        for r in report['rows']:
            u=r['usage'] or {};writer.writerow([r['repetition'],r['arm'],r['complete'],r['correct'],r['scored'],*[u.get(k) for k in ('total_tokens','input_tokens','cached_input_tokens','output_tokens')],r['phase_seconds'],r['responses'],None])
    lines=[f"# 黑盒组结果：{report['case'] or 'unknown case'}",'',
        '相同业务历史，三次配对；每次一个真实原生压缩边界。标准答案由程序生成、程序评分，无额外模型裁判。',
        '', '| 重复 | 分支 | 正确/可评分 | 完整调用Token | 模型阶段秒数 |', '| --- | --- | --- | --- | --- |']
    for r in report['rows']:
        token=(r['usage'] or {}).get('total_tokens','未知');seconds='未知' if r['phase_seconds'] is None else f"{r['phase_seconds']:.2f}"
        lines.append(f"| {r['repetition']} | {r['arm']} | {r['correct']}/{r['scored']} | {token} | {seconds} |")
    totals={arm:(sum(r['correct'] for r in report['rows'] if r['arm']==arm and r['correct'] is not None),
        sum(r['scored'] for r in report['rows'] if r['arm']==arm and r['scored'] is not None)) for arm in PHASES}
    means={arm:statistics.mean([r['usage']['total_tokens'] for r in report['rows'] if r['arm']==arm and r['usage']])
        for arm in PHASES if any(r['arm']==arm and r['usage'] for r in report['rows'])}
    quality='；'.join(f'{arm} {a}/{b}' for arm,(a,b) in totals.items())
    cost='；'.join(f'{arm}平均{value:.0f} Token' for arm,value in means.items())
    if means.get('native') and 'wsc' in means:cost+=f"；WSC/native={means['wsc']/means['native']:.2f}倍"
    lines+=['',f"本组已知总用量：{report['actual_group_tokens']} Token、{report['actual_group_responses']} 个响应；本地记录闭合：{report['accounting_complete']}。历史研究未知项仍保留，金额未知。",'',
        f'本组实测：{quality}。这是该确定性状态协议与输入下的有限行为证据；不能据此推断摘要内容完整或所有错误都由压缩算法造成。', '',
        cost+'。原生热上下文与内部持久化大小未知，不能将WSC字节缩减当作对原生的效率优势。','',
        'WSC成本包含正常选材及续接，native包含真实压缩及续接；未压缩基线仅包含查询。阶段耗时不含全部导出、导入、固定文件校验及清理，不能当作完整产品延迟。三次重复并行，共享服务与缓存，统计独立性有限。','',
        '## 配对差异（WSC减native）','']
    for metric,value in report['paired'].items():
        lines.append(f'- {metric}: '+('不足以计算' if value is None else f"均值{value['mean']:.2f}，观测范围[{value['minimum']:.2f}, {value['maximum']:.2f}]，描述性bootstrap 95%区间{value['empirical_bootstrap_95']}。"))
    lines+=['','## 原始失败回答','']
    for failure in report['answer_failures']:
        lines.append(f"- R{failure['repetition']:02d}/{failure['arm']}/{failure['question_id']}: 实际{canonical(failure['actual'])}，预期{canonical(failure['expected'])}，{failure['verdict']}。")
    lines+=['','## 证据与限制','',
        '- 各重复compression-proof.json记录真实压缩确认；package.json与generation保存WSC原始材料、草稿和来源绑定。phase-outcome.json、events.jsonl、rollout.jsonl保存调用证据。',
        '- 每次查询进入一次性兄弟分支，原业务主干与共用启动父线程均校验未被查询改写。WSC未继承原业务历史，只继承固定启动环境并导入其正常包；没有伪造HostReceipt。',
        '- 启动技能目录曾在独立线程之间变化；零调用准入保留失败记录，后改用同一无业务、无推理父线程分叉。正文和工具定义不作删减归一化。',
        '- 这是明确状态协议下的小型事实/约束行为测试；不是大型应用开发或真实任务正确续接的证明。全答对会出现天花板，不能据此判两者等效或证明长期优势。',
        '- 只有三次重复。若三次均全部通过，将每次完整通过当作Bernoulli事件，精确二项95%区间下界仅约29.2%；也不能假定共享服务下完全独立。',
        '- 原生压缩后的真实上下文Token、摘要内容与内部恢复成本未知；无法画等上下文Token保真曲线或作严格算法级Pareto结论。',
        '- 持久化hash验证是无模型的可访问性检查，不等于模型已经主动恢复信息。尚未证明连续5/10/20/50次压缩、真实工具任务续接或收益值得全部维护成本。',
        '- private oracle仅在所有自建运行进程关闭后落盘；预先生成的数据目录未提供给模型。运行器不构成对恶意任意主机访问的安全隔离承诺。','',
        '下一步依据本组失败或天花板情况选择剩余案例；保持原始失败和花费，不为追求差异修改压缩算法或删除样本。']
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    points=[r for r in report['rows'] if r['usage'] and r['scored']]
    if points:
        maximum=max(r['usage']['total_tokens'] for r in points)*1.12
        colors={'uncompressed':'#71717a','native':'#2563eb','wsc':'#b45309'}
        svg=['<svg xmlns="http://www.w3.org/2000/svg" width="900" height="440" viewBox="0 0 900 440">',
            '<rect width="900" height="440" fill="#fafafa"/>',
            '<g font-family="Segoe UI,Arial,sans-serif" fill="#27272a"><text x="70" y="30" font-size="18">Observed call tokens vs answer accuracy (three paired repetitions)</text>',
            '<text x="70" y="53" font-size="12">Call tokens include compression/selection + query; opaque context tokens remain unknown.</text>',
            '<path d="M70 80V350H850" fill="none" stroke="#71717a"/>']
        for fraction in (0,.5,1):
            y=350-fraction*250
            svg.append(f'<path d="M70 {y}H850" stroke="#e4e4e7"/><text x="32" y="{y+4}" font-size="12">{fraction:.0%}</text>')
        for step in range(5):
            value=maximum*step/4;x=70+value/maximum*760
            svg.append(f'<text x="{x-12:.1f}" y="373" font-size="12">{value/1000:.0f}k</text>')
        for r in points:
            x=70+r['usage']['total_tokens']/maximum*760;y=350-r['correct']/r['scored']*250
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{colors[r["arm"]]}" fill-opacity=".65"><title>R{r["repetition"]} {r["arm"]}: {r["usage"]["total_tokens"]} tokens, {r["correct"]}/{r["scored"]}</title></circle>')
        for i,(arm,color) in enumerate(colors.items()):
            x=90+i*200;svg.append(f'<circle cx="{x}" cy="410" r="5" fill="{color}"/><text x="{x+12}" y="414" font-size="13">{arm}</text>')
        svg.append('</g></svg>');(root/'observed-cost-quality.svg').write_text('\n'.join(svg),encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    result=write(args.root);print(canonical(dict(status=result['status'],tokens=result['actual_group_tokens'],paired=result['paired'])))


if __name__=='__main__':main()
