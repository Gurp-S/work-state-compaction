"""Adapters receive public history only, never questions or oracle answers."""
import json
from pathlib import Path
import sys
import time
from dataset import canonical,native_items

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from wsc import WSC,Store,Selection,Limits
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.generation import JsonCommandGenerator


class Identity:
    label='identity-control'
    scope='Uncompressed control; never native Codex.'
    def compress(self,events,area,**kwargs):
        return dict(items=native_items(events),external_bytes=0,model_usage=None,
                    algorithm_config=dict(policy='retain_all_public_observations'))


class WscReplay:
    label='wsc-fixed-selection'
    scope='Real WSC prepare/stage; externally fixed selection, not measured semantic selection quality.'
    def __init__(self,root,generator=None,selection_ordinals=None):
        self.core=WSC(Store(root/'state.db',session_id='deterministic-benchmark',workspace=str(root)),access=lambda *args:True)
        self.adapter=CodexCheckpointAdapter();self.seen=0;self.generator=generator
        self.root=root;self.selection_ordinals=selection_ordinals;self.package=None
        if generator:self.label='wsc-generator';self.scope='Actual caller-supplied WSC generator; model metadata externally registered.'
    def compress(self,events,area,**kwargs):
        batch=self.adapter.import_items(native_items(events[self.seen:]),thread_id='benchmark',start_ordinal=self.seen)
        self.core.ingest(batch);self.seen=len(events)
        snap=self.core.capture()
        limits=Limits(max_view_bytes=kwargs['byte_limit'],max_material_bytes=16*1024*1024)
        if self.generator:
            view=self.core.generate(snap,JsonCommandGenerator(self.generator),producer='registered-generator',limits=limits)
        else:
            selected=tuple(x['id'] for i,x in enumerate(snap.events) if self.selection_ordinals is None or i in self.selection_ordinals)
            view=self.core.prepare(snap,Selection(source_ids=selected),producer='fixed-selection',limits=limits)
        operation=self.core.stage(view,directory=area/'exports',adapter=self.adapter)
        package=self.core.package(operation)
        self.package=package
        (area/'checkpoint.json').write_text(canonical(package),encoding='utf-8')
        # No fake HostReceipt: stage-only replay, never claimed as actual installation.
        self.core.discard(operation)
        external=sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
        return dict(items=package['items'],external_bytes=external,model_usage=self.core.status()['usage'],
            package_digest=package['package_digest'],algorithm_config=dict(policy='registered-generator' if self.generator else 'fixed-source-selection',selection_ordinals=self.selection_ordinals),
            installation='not_executed',recovery='not_executed')

    def recover(self,max_calls,max_bytes):
        begin=time.perf_counter();items=[];calls=0;size=0;failures=[]
        # Use the actual exported source index, not the oracle's target IDs.
        index_path=Path(self.package['source_index'])
        with index_path.open('rb') as stream:index=stream.read(max_bytes)
        calls+=1;size+=len(index)
        if calls>max_calls or index_path.stat().st_size>len(index):
            return dict(items=[],io_calls=calls,bytes=size,seconds=time.perf_counter()-begin,failures=['index_budget_exceeded'])
        for source_id in json.loads(index):
            if calls>=max_calls or size>=max_bytes:break
            calls+=1
            try:
                result=self.core.read(source_id,limit=max_bytes-size)
                raw=result['content'];size+=len(raw)
                if result['complete']:items.append(json.loads(raw.decode('utf-8')))
                else:failures.append('partial_source')
            except Exception as error:failures.append(type(error).__name__+':'+str(error))
        return dict(items=items,io_calls=calls,bytes=size,seconds=time.perf_counter()-begin,failures=failures,
                    strategy='Bounded sequential scan of actual source index; not model-directed discovery.')


def audit_native_archive(path):
    """Observe real recorded native output; no claim of matching generated data."""
    import hashlib
    raw=Path(path).read_bytes();rows=[json.loads(s) for s in raw.decode('utf-8').splitlines()]
    results=[]
    for i,row in enumerate(rows):
        if row.get('type')=='compacted':
            p=row['payload'];history=p.get('replacement_history',[])
            results.append(dict(line=i+1,items=history,response_id=p.get('compaction_response_id'),
                usage=p.get('latest_token_usage_record',{}).get('usage'),
                encrypted=any(x.get('type')=='compaction' and 'encrypted_content' in x for x in history)))
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(),compactions=results,
        paired_with_generated_dataset=False,scope='Actual native archive audit; unrelated input, excluded from paired scores.')
