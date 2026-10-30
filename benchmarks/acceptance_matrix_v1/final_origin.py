"""Authoritative model finals from bound public rollout records, not UI presentations."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
from .final_assertions import score_final,normalize_claims


def strict_json(text):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('final_origin_duplicate_json_key')
            result[key]=value
        return result
    def constant(value):raise ValueError('final_origin_nonfinite_json')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)


def model_finals(phase,rows):
    turn=phase.get('usage_completion_evidence',{}).get('turn_id')
    if not isinstance(turn,str) or not turn:raise ValueError('final_origin_turn_missing')
    finals=[];seen=set();tools=set();context=None
    for row in rows:
        p=row.get('payload',{})
        if row.get('type')=='turn_context':context=p.get('root_turn_id') or p.get('turn_id')
        if row.get('type')!='response_item':continue
        meta=p.get('internal_chat_message_metadata_passthrough',{}) or {}
        identity=meta.get('turn_id') or context
        if identity!=turn:continue
        if p.get('type') in ('function_call','custom_tool_call'):
            tools.add(p.get('call_id'));continue
        if p.get('type')!='message' or p.get('role')!='assistant' or p.get('phase')!='final_answer':continue
        # A current-turn context is insufficient for an unbound model message.
        if meta.get('turn_id')!=turn:raise ValueError('final_origin_message_turn_unbound')
        key=p.get('id')
        if not isinstance(key,str) or key in seen:raise ValueError('final_origin_identity_ambiguous')
        seen.add(key);blocks=p.get('content')
        if not isinstance(blocks,list) or not all(b.get('type')=='output_text' and isinstance(b.get('text'),str) for b in blocks):
            raise ValueError('final_origin_content_unassessable')
        finals.append(dict(type='agentMessage',id=key,phase='final_answer',text=''.join(b['text'] for b in blocks)))
    excluded=[]
    for event in phase.get('finals',[]):
        key=event.get('id')
        if key in seen:
            actual=next(f for f in finals if f['id']==key)
            if event.get('text')!=actual['text']:raise ValueError('final_origin_text_mismatch')
        elif key in tools:excluded.append(key)
        else:raise ValueError('final_origin_event_unbound')
    return finals,excluded


def score_bound_final(phase,oracle,rollout_path):
    raw=Path(rollout_path).read_bytes()
    if sha256(raw).hexdigest()!=phase.get('rollout_sha256'):raise ValueError('final_origin_rollout_changed')
    rows=[strict_json(line) for line in raw.decode('utf-8',errors='strict').splitlines()]
    finals,excluded=model_finals(phase,rows)
    projected=deepcopy(phase);projected['finals']=finals
    annotations=[];claims=[];projection_error=None
    if len(finals)==1:
        try:
            text=finals[0]['text'].strip();lines=text.splitlines()
            if len(lines)>=3 and lines[0] in ('```json','```') and lines[-1]=='```':text='\n'.join(lines[1:-1])
            value=strict_json(text)
            if not isinstance(value,dict) or not isinstance(value.get('assertions'),list):raise ValueError('structured_assertions_missing')
            core=[];allowed={'id','assertion_id','value','source_id','field_path'}
            for row in value['assertions']:
                if not isinstance(row,dict):raise ValueError('assertion_shape_invalid')
                annotations.append(dict(assertion_id=row.get('assertion_id',row.get('id')),fields=sorted(set(row)-allowed)))
                core.append({key:deepcopy(item) for key,item in row.items() if key in allowed})
            claims=normalize_claims(core,oracle['sources'])
            value['assertions']=core
            projected['finals'][0]['text']=json.dumps(value,ensure_ascii=False,allow_nan=False)
        except (ValueError,TypeError,KeyError) as error:
            projection_error=str(error);projected['finals']=[]
    result=score_final(projected,oracle)
    if projection_error:result['output_parse_error']=projection_error
    unknown={c['assertion_id'] for c in claims if c.get('value') is None and oracle['expected_assertions'].get(c['assertion_id']) is not None}
    if result['output_parse_error']:
        # Format failure does not establish free-text semantic correctness/incorrectness.
        for name in ('citation_byte_match_rate','missing_or_nonmatching_citation_rate','exact_answer_accuracy'):
            result[name]=None
        result['exact_answer_correct']=None;result['citation_byte_matches']=None
    else:
        submitted={c['assertion_id']:c for c in claims}
        for row in result['details']:
            if row['assertion_id'] in unknown:
                row.update(answer_correct=None,citation_byte_match=None,citation_error='declared_unknown_value')
        answered=[r for r in result['details'] if r['submitted'] and r['assertion_id'] not in unknown]
        result['exact_required_recall']=result['exact_answer_correct']/result['required_assertions'] if result['required_assertions'] else None
        result['answerable_field_coverage']=len(answered)/result['required_assertions'] if result['required_assertions'] else None
        result['exact_answer_accuracy']=sum(r['answer_correct'] is True for r in answered)/len(answered) if answered else None
        result['nonmatching_exact_values']=sum(r['answer_correct'] is False for r in answered)
        for row in result['details']:
            c=submitted.get(row['assertion_id'],{})
            if c.get('source_id') is None and row['citation_error']=='citation_source_unknown':row['citation_error']='citation_missing'
        result['unknown_source_citations']=sum(r['citation_error']=='citation_source_unknown' for r in result['details'])
    result['final_answer_count']=len(finals)
    return dict(**result,final_origin_policy='bound_model_response_item_v1',excluded_tool_presentations=excluded,
        unassessed_annotation_fields=annotations,declared_unknown_assertions=sorted(unknown),
        format_correct=result['output_parse_error'] is None,semantic_evaluation_coverage='structured_fields_only',
        phase_usage_complete=phase.get('usage_complete'),phase_completed=phase.get('completed'),
        source_rollout_sha256=sha256(raw).hexdigest(),original_phase_changed=False)
