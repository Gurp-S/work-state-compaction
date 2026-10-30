"""Common frozen-copy evaluator. Run in a coordinator-owned isolated process."""
from hashlib import sha256
import json
from pathlib import Path

from .acceptors import load_candidate
from .chain_evaluation import evaluate_code,evaluate_claims,evaluate_work_state
from .final_assertions import normalize_claims
from .task_specs import SPECS


def read_bounded(path,limit):
    if type(limit) is not int or not 0<=limit<=1048576:raise ValueError('artifact_size_invalid')
    with path.open('rb') as source:raw=source.read(limit+1)
    if len(raw)>limit:raise ValueError('artifact_size_exceeded')
    return raw


def unique_pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('artifact_json_duplicate_key')
        result[key]=value
    return result


def evaluate_snapshot(snapshot,oracle,*,public_test_sha256):
    """Candidate import executes code; this function supplies no security boundary."""
    files=snapshot.get('files',{});entry=SPECS[oracle['task']]['entry'];errors=[]
    expected=(entry,'work_state.json','test_smoke.py');paths={}
    for name in expected:
        try:
            value=files[name];path=Path(value['path'])
            if path.name!=name or path.is_symlink():raise ValueError('artifact_path_invalid')
            data=read_bounded(path,value['bytes'])
            if len(data)!=value['bytes'] or sha256(data).hexdigest()!=value['sha256']:
                raise ValueError('artifact_digest_changed')
            paths[name]=path
        except (KeyError,OSError,ValueError) as error:errors.append(dict(file=name,error=type(error).__name__))
    protected=files.get('test_smoke.py',{}).get('sha256')==public_test_sha256
    code=None;state=None;claims=None
    if not errors and not snapshot.get('errors'):
        try:
            code=evaluate_code(load_candidate(paths[entry]),oracle)
            state=evaluate_work_state(read_bounded(paths['work_state.json'],8192),oracle)
        except Exception as error:errors.append(dict(stage='code_execution',error=type(error).__name__))
    try:
        finals=[f for f in snapshot['task_phase']['finals']
                if f.get('type')=='agentMessage' and f.get('phase')=='final_answer']
        if len(finals)!=1:raise ValueError('final_answer_not_unique')
        text=finals[0]['text'].strip();lines=text.splitlines()
        if len(lines)>=3 and lines[0] in ('```json','```') and lines[-1]=='```':text='\n'.join(lines[1:-1])
        value=json.loads(text,object_pairs_hook=unique_pairs,
                         parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
        claims=evaluate_claims(normalize_claims(value['assertions'],oracle['sources']),oracle)
    except (KeyError,TypeError,ValueError) as error:errors.append(dict(stage='claims',error=type(error).__name__))
    # A candidate import/call cannot silently change the version being scored.
    for name,path in paths.items():
        try:
            if sha256(read_bounded(path,files[name]['bytes'])).hexdigest()!=files[name]['sha256']:
                errors.append(dict(file=name,error='artifact_changed_during_evaluation'))
        except (OSError,ValueError):errors.append(dict(file=name,error='artifact_changed_after_evaluation'))
    failures=errors or snapshot.get('errors') or not protected
    values=[v.get('success') if type(v) is dict else False for v in (code,state,claims)]
    success=False if failures or any(v is False for v in values) else None if any(v is None for v in values) else True
    return dict(task_success=success,code=code,state=state,claims=claims,errors=errors,
        public_test_preserved=protected,artifact_source_errors=snapshot.get('errors',[]),
        scope='Frozen version plus deterministic checks; not free-text semantics or a process isolation guarantee.')
