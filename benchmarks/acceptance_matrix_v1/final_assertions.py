"""Strict structured final extraction; never a free-text semantic judge."""
import json
import re
from .evidence import evaluate


def normalize_claims(claims,sources):
    """Accept two explicit identifier/path dialects, never infer answer values."""
    if type(claims) is not list:raise ValueError('assertion_list_invalid')
    result=[]
    for item in claims:
        if type(item) is not dict:raise ValueError('assertion_shape_invalid')
        row=dict(item)
        if 'id' in row:
            if 'assertion_id' in row:raise ValueError('assertion_identifier_ambiguous')
            row['assertion_id']=row.pop('id')
        path=row.get('field_path')
        if type(path) is str:
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*',path):
                raise ValueError('dot_path_not_supported')
            parts=path.split('.')
            data=sources.get(row.get('source_id'),{}).get('data')
            for index,part in enumerate(parts):
                if type(data) is dict and '.'.join(parts[index:]) in data and index<len(parts)-1:
                    raise ValueError('dot_path_ambiguous')
                data=data.get(part) if type(data) is dict else None
            row['field_path']=parts
        result.append(row)
    return result


def score_final(phase,oracle):
    finals=[row for row in phase.get('finals',[]) if row.get('type')=='agentMessage' and row.get('phase')=='final_answer']
    claims=[];error=None
    try:
        if len(finals)!=1:raise ValueError('final_answer_not_unique')
        text=finals[0]['text'].strip()
        lines=text.splitlines()
        if len(lines)>=3 and lines[0] in ('```json','```') and lines[-1]=='```':text='\n'.join(lines[1:-1])
        value=json.loads(text)
        if not isinstance(value,dict) or 'assertions' not in value:raise ValueError('structured_assertions_missing')
        claims=normalize_claims(value['assertions'],oracle['sources'])
        result=evaluate(claims,oracle['expected_assertions'],oracle['sources'])
    except (ValueError,KeyError,TypeError) as exc:
        error=str(exc)
        result=evaluate([],oracle['expected_assertions'],oracle['sources'])
    return dict(**result,output_parse_error=error,final_answer_count=len(finals),format_policy='identifier_alias_and_unambiguous_dot_path_v1',
        free_text_semantic_evaluation='not_performed')
