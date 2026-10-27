"""Exact scoring and receipt report for the completed mixed-provenance cohort."""
from pathlib import Path
from contextlib import closing
import argparse,csv,json,sqlite3,statistics,tempfile,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from blackbox_group_report import paired_interval
from blackbox_recovery_case import build
from blackbox import score_answer
from native_evidence import read,save,file_hash
from native_source_tool import SourceToolHandler
from native_source_tool_budget import BudgetResultSourceToolHandler
from wsc import WSC,Store
from wsc.source_access import SnapshotSourceAccess


def equivalent_callbacks(root):
    source=root/'state.db';before=file_hash(source)
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'clone.db'
        with closing(sqlite3.connect(source)) as a,closing(sqlite3.connect(path)) as b:a.backup(b)
        with closing(sqlite3.connect(path)) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
        core=WSC(Store(path,session_id=binding['session_id'],workspace=binding['workspace']),access=lambda *a:True)
        snap=core.capture();old=SourceToolHandler(SnapshotSourceAccess(core.store,snap,access=core.access))
        new=BudgetResultSourceToolHandler(SnapshotSourceAccess(core.store,snap,access=core.access))
        count=0
        for line in (root/'selection/events.jsonl').read_text().splitlines():
            event=json.loads(line)
            if event.get('method')!='item/tool/call':continue
            kwargs=dict(thread_id=event['params']['threadId'],turn_id=event['params']['turnId'])
            assert old.handle(event,**kwargs)==new.handle(event,**kwargs);count+=1
        assert new.refused_callbacks==0 and old.reader.calls==new.reader.calls
    assert file_hash(source)==before
    return dict(passed=True,callbacks=count,overflow_not_triggered=True,source_unchanged=True,
        scope='Byte-equivalent handler results on these recorded requests only; not equality of all possible model trajectories.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runs',type=Path,default=Path('D:/agent-task-runs'))
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();r=args.runs
    original=r/'wsc-two-boundary-recovery-20261027-v2';native=r/'wsc-native-recovery-queries-20261027-v1'
    c1=r/'wsc-budget-results-qualification-20261027-v1/candidate';c2=r/'wsc-source-tool-minimal-candidate-20261027-v1'
    c3=r/'wsc-minimal-recovery-group-20261027-v4/R03/C';c3_query=r/'wsc-published-c-query-20261027-v1'
    assert read(native/'result.json')['status']=='completed'
    public=read(original/'dataset.public.json');rebuilt,oracle,_=build(public['seed'],public['receipt_count']);assert public==rebuilt
    pairs=[];all_ids=set();files={};failures=[]
    fields=('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','total_tokens')
    for name,c_source,c_query in [('R01',c1,c1/'query/phase-outcome.json'),('R02',c2,c2/'query/phase-outcome.json'),('R03',c3,c3_query/'R03/C/query/phase-outcome.json')]:
        base=original/name;b_query=(native/name/'B/query/phase-outcome.json') if name!='R03' else r/'wsc-minimal-recovery-group-20261027-v2/R03/B/query/phase-outcome.json'
        baseline=read(base/'uncompressed-probe/phase-outcome.json');assert baseline['completed'] and baseline['usage_complete']
        row=dict(repetition=name,uncompressed=score_answer(baseline['finals'][0]['text'],oracle),source_tool_compatibility=equivalent_callbacks(c_source))
        for arm,paths in [('B',[base/'B1-compression/phase-outcome.json',base/'B2-compression/phase-outcome.json',b_query]),
                          ('C',[base/'C1-selection/phase-outcome.json',c_source/'selection/phase-outcome.json',c_query])]:
            phases=[read(p) for p in paths]
            assert all(p['completed'] and not p['failure'] and p['usage_complete'] for p in phases)
            assert len(phases[-1]['finals'])==1
            for path,phase in zip(paths,phases):
                files[str(path)]=file_hash(path)
                for receipt in phase['receipts']['response_receipts']:
                    assert receipt['response_id'] not in all_ids;all_ids.add(receipt['response_id'])
            usage={key:sum(p['receipts']['all_usage'][key] for p in phases) for key in fields}
            score=score_answer(phases[-1]['finals'][0]['text'],oracle)
            row[arm]=dict(score=score,usage=usage,phase_seconds=sum(p['seconds'] for p in phases),
                responses=sum(p['receipts']['response_count'] for p in phases),phase_files=[str(p) for p in paths],
                internal_context_tokens=None,cash=None)
            failures.extend(dict(repetition=name,arm=arm,**detail) for detail in score['details'] if detail['verdict']!='correct')
        pairs.append(row)
    means={arm:dict(tokens=statistics.mean(x[arm]['usage']['total_tokens'] for x in pairs),
        seconds=statistics.mean(x[arm]['phase_seconds'] for x in pairs),correct=sum(x[arm]['score']['counts']['correct'] for x in pairs),questions=6) for arm in ('B','C')}
    new_roots=[r/p for p in ['wsc-minimal-recovery-group-20261027-v4','wsc-budget-results-qualification-20261027-v1','wsc-published-c-query-20261027-v1','wsc-native-recovery-queries-20261027-v1']]
    new_usage=[read(p/'result.json')['ledger']['study'] for p in new_roots]
    report=dict(schema='wsc.two-boundary.mixed-cohort/1',pairs=pairs,means=means,answer_failures=failures,
        full_chain_token_ratio_C_over_B=means['C']['tokens']/means['B']['tokens'],
        phase_time_ratio_C_over_B=means['C']['seconds']/means['B']['seconds'],
        paired_token_difference=paired_interval([x['C']['usage']['total_tokens']-x['B']['usage']['total_tokens'] for x in pairs]),
        paired_accuracy_difference=paired_interval([(x['C']['score']['counts']['correct']-x['B']['score']['counts']['correct'])/2 for x in pairs]),
        newly_known_tokens=sum(x['tokens'] for x in new_usage),newly_known_responses=sum(x['responses'] for x in new_usage),
        newly_usage_unknown=any(x['uncertain'] for x in new_usage),historical_unknown_preserved=True,
        selected_successful_chain_tokens=sum(x[a]['usage']['total_tokens'] for x in pairs for a in ('B','C')),
        source_phase_sha256=files,judge_model_calls=0,repetitions=3,independent_datasets=1,
        all_answer_cells_completed=True,all_C_handler_revisions_identical=False,
        evidence_scope='Three paired observed system outcomes with historical reuse and a protocol repair. No affected overflow path in accepted C traces; all legacy/fixed results replay equal. Not an all-prospective, identical-revision randomized trial.',
        resource_scope='B two actual compactions plus QA; C two actual selections plus QA. Failed attempts retained separately, excluded from successful-chain figures; whole research spend remains unknown.',
        pareto='Neither mean point dominates: C higher observed quality and higher average known chain token cost. Fixed-context-token-budget comparison and monetary dominance unproven.')
    args.out.mkdir(parents=True,exist_ok=False);save(args.out/'report.json',report)
    with (args.out/'report.csv').open('x',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(['repetition','arm','correct','questions','total_tokens','phase_seconds','responses'])
        for row in pairs:
            for arm in ('B','C'):writer.writerow([row['repetition'],arm,row[arm]['score']['counts']['correct'],2,row[arm]['usage']['total_tokens'],row[arm]['phase_seconds'],row[arm]['responses']])
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(7,4.5))
    for arm,color in [('B','#64748b'),('C','#0f766e')]:
        ax.scatter([x[arm]['usage']['total_tokens']/1000 for x in pairs],[x[arm]['score']['counts']['correct']/2 for x in pairs],label=arm,s=70,color=color)
        for index,x in enumerate(pairs):ax.annotate(x['repetition'],(x[arm]['usage']['total_tokens']/1000,x[arm]['score']['counts']['correct']/2),xytext=(5,5+index*12 if arm=='C' else 5),textcoords='offset points',fontsize=8)
    ax.set(xlabel='Observed successful-chain call tokens (thousands)',ylabel='Exact QA accuracy',ylim=(0,1.2),title='Two compactions, one dataset, three paired outcomes')
    ax.grid(alpha=.2);ax.legend(title='B native / C WSC');fig.tight_layout();fig.savefig(args.out/'cost-quality.svg');fig.savefig(args.out/'cost-quality.png',dpi=160);plt.close(fig)
    print(json.dumps({key:report[key] for key in ('means','full_chain_token_ratio_C_over_B','newly_known_tokens','newly_known_responses','newly_usage_unknown')}))


if __name__=='__main__':main()
