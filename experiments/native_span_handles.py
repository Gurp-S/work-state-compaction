"""Bijective wire aliases for exact spans; content and source order stay exact."""
from copy import deepcopy


def project(offered):
    wire=deepcopy(offered)
    bindings={}
    for event in wire['events']:
        for span in event['spans']:
            handle='p'+str(len(bindings))
            bindings[handle]=span['ref']
            span['ref']=handle
    if len(set(bindings.values()))!=len(bindings):
        raise ValueError('native_span_reference_ambiguous')
    return wire,bindings


def expand(draft,bindings):
    value=deepcopy(draft)
    refs=value.get('span_refs',[])
    if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in bindings for ref in refs):
        raise ValueError('native_span_handle_not_offered')
    value['span_refs']=[bindings[ref] for ref in refs]
    return value
