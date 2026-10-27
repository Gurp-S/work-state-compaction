"""Tables and standard plotting; no fabricated native comparison or token curve."""
import csv
import json


def write_report(root,run):
    rows=run['results']
    with (root/'metrics.csv').open('w',encoding='utf-8',newline='') as stream:
        fields=['adapter','round','status','context_bytes','context_tokens','external_bytes','seconds','correct','incorrect','undecidable','coverage']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:
            writer.writerow({k:row.get(k,row.get('hot',{}).get(k)) for k in fields})
    lines=['# Deterministic WSC benchmark','',
        'Scope: structured-protocol, stage-only mechanism replay. No native superiority claim.',
        'The identity control is uncompressed history, not native Codex. Free-text and encrypted semantics abstain.',
        'Repeated stage snapshots are not repeated native installation/compaction. Full selection is a mechanism control.',
        '',f"Public dataset SHA-256: `{run['public_sha256']}`",'',
        '| Adapter | Round | Status | Bytes | Correct | Incorrect | Undecidable |',
        '| --- | ---: | --- | ---: | ---: | ---: | ---: |']
    for row in rows:
        q=row.get('hot',{})
        lines.append(f"| {row['adapter']} | {row['round']} | {row['status']} | {row.get('context_bytes','')} | {q.get('correct','')} | {q.get('incorrect','')} | {q.get('undecidable','')} |")
    lines+=['','## Availability and fairness','',*['- '+x for x in run['limitations']],
        '', '## Experiments','',*['- '+k+': '+v for k,v in run['experiments'].items()],
        '', 'All failures remain in results.json and cell directories. Re-run into a new output directory.',
        'Recovery uses actual WSC read plus bounded sequential index scan; it is a system mechanism test, not inferred Agent behavior.',
        'No Pareto ranking across different protocols, undecidable coverage, unmatched native data or failed budgets.']
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    frontier=[]
    for number in sorted({r['round'] for r in rows}):
        group=[r for r in rows if r['round']==number and r['status']=='measured' and r['hot']['coverage']==1]
        for row in group:
            dominated=any(other['context_bytes']<=row['context_bytes'] and other['hot']['correct']>=row['hot']['correct']
                and (other['context_bytes']<row['context_bytes'] or other['hot']['correct']>row['hot']['correct']) for other in group)
            frontier.append(dict(adapter=row['adapter'],round=number,dominated=dominated))
    (root/'pareto.json').write_text(json.dumps(dict(scope='Matched structured-protocol hot-only mechanism rows with full decidability. Bytes, not model tokens; no native ranking.',rows=frontier),indent=2),encoding='utf-8')
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig,axes=plt.subplots(1,2,figsize=(10,4))
    for adapter in sorted({x['adapter'] for x in rows}):
        series=[x for x in rows if x['adapter']==adapter and x['status']=='measured']
        if not series:continue
        axes[0].plot([x['round'] for x in series],[x['hot']['confirmed_recall_lower_bound'] for x in series],marker='o',label=adapter)
        axes[1].plot([x['context_bytes'] for x in series],[x['hot']['confirmed_recall_lower_bound'] for x in series],marker='o',label=adapter)
    axes[0].set(xlabel='Stage checkpoint (not native compaction)',ylabel='Confirmed recall lower bound',ylim=(-.05,1.05))
    axes[1].set(xlabel='Context UTF-8 bytes (NOT tokens)',ylabel='Confirmed recall lower bound',ylim=(-.05,1.05))
    for ax in axes:ax.grid(True,alpha=.3);ax.legend(fontsize=7)
    fig.tight_layout();fig.savefig(root/'mechanism-curves.png',dpi=130);plt.close(fig)
