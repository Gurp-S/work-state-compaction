"""Receipt and visible-tool audit. No model calls or reasoning extraction."""
from pathlib import Path
from hashlib import sha256
import collections
import json
import re

PAIR=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1/execution-v3/R02')
OUT=Path('D:/agent-task-runs/wsc-R02-cost-review-20261027-v1')
OUT.mkdir(exist_ok=False)
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
hashfile=lambda p:sha256(p.read_bytes()).hexdigest()
report=dict(model_calls=0,old_usage_unknown_preserved=True,arms={},
    limitations=['Command categories overlap; counts are not token attribution.',
                 'Repeated invocation is not proof of unnecessary work: source may have changed.',
                 'Visible output text characters exclude image data and are not tokens.',
                 'Compaction cost is observed, but its net benefit lacks a same-threshold control.'])
patterns=dict(source_read=r'Get-Content|Select-String|\brg\b',
    test_or_build=r'vitest|pytest|tsc\b|npm (?:run|test)|run-acceptance|acceptance-cases|playwright',
    source_edit=r'apply_patch|write_text|WriteAllText|Set-Content|\.writeFile',
    memory_read=r'memories|MEMORY\.md',
    polling=r'write_stdin')
for arm in ('B','C'):
    area=PAIR/arm/'S3-phase'
    raw=(area/'rollout.jsonl').read_bytes()
    rows=[json.loads(line) for line in raw.decode('utf-8').splitlines()]
    phase=read(area/'phase-outcome.json')
    calls={};tools=[];compactions=[];receipts=[];terminal=[]
    for i,row in enumerate(rows):
        p=row.get('payload',{})
        if row['type']=='token_usage_record':receipts.append((i,p))
        if row['type']=='compacted':
            rid=p['compaction_response_id']
            bound=[(n,r) for n,r in receipts if r['response_id']==rid]
            assert len(bound)==1 and bound[0][1]==p['latest_token_usage_record']
            compactions.append(dict(line=i+1,response_id=rid,usage=bound[0][1]['usage']))
        if row['type']=='event_msg' and p.get('type') in ('turn_aborted','task_complete'):
            terminal.append(dict(line=i+1,type=p['type']))
        if row['type']!='response_item':continue
        if p.get('type') in ('custom_tool_call','function_call'):
            source=p.get('input',p.get('arguments',''))
            assert isinstance(source,str)
            calls[p['call_id']]=dict(line=i+1,input=source)
        elif p.get('type') in ('custom_tool_call_output','function_call_output'):
            value=p.get('output','')
            text='\n'.join(b.get('text','') for b in value if isinstance(b,dict) and isinstance(b.get('text'),str)) if isinstance(value,list) else str(value)
            call=calls.get(p.get('call_id'))
            assert call is not None
            tools.append(dict(call_id=p['call_id'],call_line=call['line'],output_line=i+1,
                input_characters=len(call['input']),visible_output_characters=len(text),
                truncated='Warning: truncated output' in text,
                categories=[name for name,pattern in patterns.items() if re.search(pattern,call['input'],re.I)]))
    ids=[p['response_id'] for _,p in receipts]
    assert len(ids)==len(set(ids))
    assert len(receipts)==phase['receipts']['response_count']
    compact_ids={p['response_id'] for p in compactions}
    compact_total=sum(p['usage']['total_tokens'] for p in compactions)
    normal=[p for _,p in receipts if p['response_id'] not in compact_ids]
    all_usage=phase['receipts']['all_usage']
    assert sum(p['usage']['total_tokens'] for _,p in receipts)==all_usage['total_tokens']
    transitions=[]
    for compact in compactions:
        prior=[p for i,p in receipts if i+1<compact['line'] and p['response_id'] not in compact_ids]
        later=[p for i,p in receipts if i+1>compact['line'] and p['response_id'] not in compact_ids]
        transitions.append(dict(compaction_line=compact['line'],
            prior_normal_input=prior[-1]['usage']['input_tokens'] if prior else None,
            next_normal_input=later[0]['usage']['input_tokens'] if later else None))
    categories=collections.Counter(tag for call in tools for tag in call['categories'])
    report['arms'][arm]=dict(source_sha256=sha256(raw).hexdigest(),
        phase_sha256=hashfile(area/'phase-outcome.json'),known_usage=all_usage,
        complete_usage=all_usage if phase['usage_complete'] else None,
        unknown_reasons=phase['turn_accounting']['reasons'],
        terminal=terminal,compactions=compactions,compaction_total_tokens=compact_total,
        normal_responses=len(normal),normal_total_tokens=all_usage['total_tokens']-compact_total,
        uncached_input=all_usage['input_tokens']-all_usage['cached_input_tokens'],
        compaction_input_transitions=transitions,paired_tool_calls=len(tools),
        unpaired_call_ids=sorted(set(calls)-{t['call_id'] for t in tools}),
        visible_tool_output_characters=sum(t['visible_output_characters'] for t in tools),
        truncated_tool_outputs=sum(t['truncated'] for t in tools),command_categories=dict(categories),
        largest_visible_outputs=sorted(tools,key=lambda t:t['visible_output_characters'],reverse=True)[:5])
    assert hashfile(area/'rollout.jsonl')==sha256(raw).hexdigest()
report['conclusion']='B unknown is a missing terminal-closure proof, not an observed cumulative receipt gap. Do not relax accounting or dispatch R03. C has observed compaction spend and more ordinary responses; neither alone establishes causal overhead or unnecessary work.'
with (OUT/'audit.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
for arm,v in report['arms'].items():
    print(arm,json.dumps({k:v[k] for k in ('compaction_total_tokens','normal_responses','normal_total_tokens','uncached_input','paired_tool_calls','visible_tool_output_characters','truncated_tool_outputs','command_categories','compaction_input_transitions')},ensure_ascii=False))
