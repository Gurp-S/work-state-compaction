"""Load source-grounded shared history without charging shared receipts twice."""
from pathlib import Path

from native_evidence import read,file_hash,save
from native_rollout_snapshot import parse_rollout
from native_business_delta import split
from native_recursive_fork import observe


def restore(core, spec, initial, destination, adapter=None):
    from wsc.contracts import Event,digest,encode
    from wsc.adapters.codex import CodexCheckpointAdapter
    path=Path(spec['capsule'])
    if file_hash(path)!=spec['capsule_sha256']:
        raise ValueError('common_prefix_capsule_changed')
    capsule=read(path)
    root=capsule['root_history']
    if file_hash(root['archive'])!=root['sha256']:
        raise ValueError('common_prefix_history_changed')
    observed=observe((initial.destination/'opened.jsonl').read_bytes(),initial.fork_binding)
    parent=initial.fork_binding['parents'][0]
    if parent['thread_id']!=capsule['parent_thread_id'] or parent['prefix_sha256']!=capsule['parent_sha256']:
        raise ValueError('common_prefix_native_parent_changed')
    if not any(item['thread_id']==root['thread_id'] and item['prefix_sha256']==root['sha256']
               for item in initial.fork_binding['parents']):
        raise ValueError('common_prefix_root_not_inherited')
    rows=parse_rollout(Path(root['archive']).read_bytes()).rows
    start=root['first_business_row']
    if not (type(start) is int and 0<=start<len(rows)):
        raise ValueError('common_prefix_start_invalid')
    business,host=split(rows[start:])
    allowed={id(row) for row in business}
    ordinal=sum(row['type']=='response_item' for row in rows[:start])
    events=[]
    adapter=adapter or CodexCheckpointAdapter()
    for row in rows[start:]:
        if row['type']!='response_item':
            continue
        if id(row) in allowed:
            events.extend(adapter.import_items([row['payload']],thread_id=root['thread_id'],
                start_ordinal=ordinal,observed_at=[row.get('timestamp')]))
        ordinal+=1
    core.ingest(events)
    result_ids=tuple(event.id for event in events if event.kind=='result')
    core.presented('common-native-history-load',result_ids,receiver=initial.opened['thread']['id'])
    fact=capsule['grade_fact']
    core.ingest([Event('common-check:S2:'+digest(fact),'observation',fact,text=encode(fact),observed_at=fact['observed_at'])])
    save(destination,dict(capsule_sha256=spec['capsule_sha256'],native_inheritance=observed['evidence'],
        source_events=len(events),results_in_loaded_history=list(result_ids),excluded_host_sources=host,
        presentation_scope='Source records in the verified loaded native fork history; not proof of model reading or task completion',
        shared_usage_charged_to_this_arm=False))
    return capsule
