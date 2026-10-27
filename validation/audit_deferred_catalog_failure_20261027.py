"""Audit an incomplete attempt without grading it or clearing usage unknowns."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys,sqlite3
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'validation'),str(ROOT/'benchmarks/deterministic_v1')]
from native_evidence import read,save,file_hash
from native_rollout_snapshot import capture_rollout
from native_deferred_catalog import restore,decoded_catalog
from native_event_table import restore as restore_events
from structured_tool_outputs import decoded_transport_objects
from wsc.evidence import source_row
from wsc.contracts import encode,digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args();root=args.root;candidate=root/'candidate';g=candidate/'generation'
    registration=read(root/'qualification-registration.json');source=Path(registration['source'])/'R01'
    result=read(root/'result.json');phase=read(candidate/'selection/phase-outcome.json')
    assert result['status']=='failed_preserved' and phase['failure']=='registered_response_cap' and not phase['completed'] and not phase['usage_complete'] and not phase['finals']
    assert result['ledger']['study']['uncertain'] and not result['ledger']['inflight']
    request=read(g/'request.json');payload=read(g/'deferred-catalog.json');binding=read(g/'deferred-catalog-binding.json')
    decoded=deepcopy(request);decoded['material']=restore(decoded['material'],payload,binding)
    old=read(source/'C2-generation/request.json');old['material']=restore_events(old['material'],read(source/'C2-generation/event-table-binding.json'))
    scope=decoded['material']['source_access'];assert scope['operations']==['read','find','catalog']
    scope['operations']=['read','find'];scope.pop('catalog_scope');scope.pop('catalog_budget')
    for r in (old,decoded):
        for k in ('path','sha256'):r['material']['cold_source_manifest'].pop(k)
    assert encode(old)==encode(decoded) and read(g/'schema.json')==read(source/'C2-generation/schema.json')
    snap=capture_rollout(candidate/'closed-selector.jsonl');assert snap.metadata['parse_complete']
    submitted=[];objects=set();actual={}
    for row in snap.rows:
        item=row.get('payload',{})
        if row['type']=='response_item' and item.get('type')=='message' and item.get('role')=='user':
            for part in item.get('content',[]):
                if part.get('type')=='input_text':
                    try:value=json.loads(part['text'])
                    except ValueError:continue
                    if type(value) is dict and value.get('operation')=='working_state_selection':submitted.append(value)
        if row['type']=='response_item' and item.get('type') in ('function_call_output','custom_tool_call_output'):
            objects.update(encode(o) for o in decoded_transport_objects(item.get('output')))
        if row['type']=='token_usage_record':
            assert item['response_id'] not in actual;actual[item['response_id']]=item['usage']
    assert len(submitted)==1 and encode(submitted[0])==encode(request)
    expected={r['response_id']:r['usage'] for r in phase['receipts']['response_receipts']}
    assert actual==expected and set(expected)==set(result['ledger']['response_ids'])
    assert sum(r['total_tokens'] for r in expected.values())==result['ledger']['study']['tokens']
    trace=read(candidate/'source-tool-trace.json');checks=[]
    with sqlite3.connect(candidate/'state.db') as db:
        db.row_factory=sqlite3.Row
        for call in trace:
            output=call['output'];assert encode(output) in objects;operation=call['arguments']['operation']
            if operation=='catalog':
                assert output['catalog']==payload and output['catalog_sha256']==digest(payload)
                decoded_catalog(payload,binding);assert 'not_performed' in output['storage_validation']
            else:
                entries=output['matches'] if operation=='find' else [output]
                for hit in entries:
                    row=source_row(db,hit['original_source_id']);assert digest(row)==hit['source_record_sha256']
                    assert row['text'][hit.get('start',hit.get('offset')):hit['end']]==hit['text']
            checks.append(dict(operation=operation,native_output_exact=True,status=output['status']))
    assert all(c['empty_confirmed'] for c in result['cleanup'].values())
    value=dict(passed=True,audit_scope='Incomplete attempt evidence only; no selection/task quality score and no clearing usage uncertainty.',model_calls=0,
        known_tokens=result['ledger']['study']['tokens'],known_responses=result['ledger']['study']['responses'],final_usage_complete=False,original_unknown_preserved=True,
        failure='registered_response_cap',task_answer_not_dispatched=True,request_actual_and_restoration_exact=True,schema_equal=True,tool_checks=checks,
        all_cleanup_confirmed=True,source_database_unchanged=file_hash(source/'state.db')==registration['cohort']['sources']['R01']['sha256']['state.db'])
    save(root/'incomplete-attempt-audit.json',value);print(value)


if __name__=='__main__':main()
