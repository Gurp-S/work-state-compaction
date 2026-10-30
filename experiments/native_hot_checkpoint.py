"""Opt-in hot view; authenticated identity scaffolding stays engine-side."""
from copy import deepcopy
from hashlib import sha256
import json

from wsc.contracts import encode,require
from wsc.resource_io import ResourceIO
from native_indexed_checkpoint import IndexedCheckpointAdapter,expand_working_state
from native_snapshot_aliases import validate_recovery_aliases

POLICY='engine_identity_sidecar_v1'
FORMAT='wsc.hot_sections/1'
MAX_METADATA_BYTES=16*1024*1024


def _pairs(values):
    result={}
    for key,value in values:
        require(key not in result,'hot_projection_duplicate_key')
        result[key]=value
    return result


def _constant(value):raise ValueError('hot_projection_nonfinite_json')


def _json(text):return json.loads(text,object_pairs_hook=_pairs,parse_constant=_constant)


def hot_header(original):
    require(original.get('format')=='wsc.indexed_sections/1','hot_projection_source_format_invalid')
    require(original.get('source_alias_policy')=='snapshot_event_seq_v1','hot_projection_alias_policy_invalid')
    value=deepcopy(original)
    value['format']=FORMAT
    value.pop('archive')
    value['source_aliases']={alias:{'observed_at':deepcopy(source['observed_at'])}
        for alias,source in original['source_aliases'].items()}
    return value


def _authenticate(metadata,reference):
    require(isinstance(reference,dict) and set(reference)=={'file_path','sha256'},'hot_projection_reference_invalid')
    require(sha256(encode(metadata).encode('utf-8')).hexdigest()==reference['sha256'],
        'hot_projection_metadata_changed')


def load_projection(reference,*,resource_io=None):
    require(isinstance(reference,dict) and set(reference)=={'file_path','sha256'},'hot_projection_reference_invalid')
    io=resource_io or ResourceIO()
    raw=io.read_bounded(reference['file_path'],MAX_METADATA_BYTES+1)
    require(len(raw)<=MAX_METADATA_BYTES,'hot_projection_metadata_budget_exhausted')
    require(sha256(raw).hexdigest()==reference['sha256'],'hot_projection_evidence_changed')
    metadata=_json(raw.decode('utf-8',errors='strict'))
    _authenticate(metadata,reference)
    return metadata


def project_text(indexed_text,metadata,reference):
    _authenticate(metadata,reference)
    # Existing decoder verifies every literal byte and the complete header.
    expand_working_state(indexed_text,metadata)
    first,tail=indexed_text.split('\n',1)
    header=_json(first)
    require(header['archive']['projection']==reference,'hot_projection_reference_changed')
    expected=deepcopy(metadata['header']);expected['archive']['projection']=deepcopy(reference)
    require(first==encode(expected),'hot_projection_header_changed')
    return encode(hot_header(header))+'\n'+tail


def restore_text(hot_text,metadata,reference):
    _authenticate(metadata,reference)
    first,tail=hot_text.split('\n',1)
    require(first==encode(hot_header(metadata['header'])),'hot_projection_header_changed')
    original=deepcopy(metadata['header'])
    original['archive']['projection']=deepcopy(reference)
    restored=encode(original)+'\n'+tail
    expand_working_state(restored,metadata)
    return restored


def expand_hot_state(text,metadata,reference):
    return expand_working_state(restore_text(text,metadata,reference),metadata)


def engine_items(package,*,resource_io=None):
    adapter=package.get('adapter',{})
    require(adapter.get('actor_projection_policy')==POLICY,'hot_projection_policy_invalid')
    reference=adapter.get('projection_evidence')
    metadata=load_projection(reference,resource_io=resource_io)
    index=adapter.get('hot_working_state_index')
    require(type(index) is int and 0<=index<len(package['items']),'hot_projection_state_index_invalid')
    items=deepcopy(package['items']);item=items[index]
    require(item.get('role')=='assistant' and len(item.get('content',[]))==1
        and item['content'][0].get('type')=='output_text','hot_projection_state_item_invalid')
    item['content'][0]['text']=restore_text(item['content'][0]['text'],metadata,reference)
    return items


def validate_hot_recovery_aliases(package,reader):
    # Same canonical source/alias guard, fed by authenticated engine metadata.
    validate_recovery_aliases({'items':engine_items(package)},reader)


class HotCheckpointAdapter(IndexedCheckpointAdapter):
    def __init__(self):
        super().__init__(source_alias_policy='snapshot_event_seq_v1')
        self.hot_index=None
    def capabilities(self):
        value={**super().capabilities(),'adapter':'codex_hot_sections_v1','actor_projection_policy':POLICY}
        if self.hot_index is not None:value['hot_working_state_index']=self.hot_index
        return value
    def render(self,body,source,cut,locators,*,source_index,understanding_index):
        items=super().render(body,source,cut,locators,source_index=source_index,understanding_index=understanding_index)
        self.hot_index=sum(row['kind']=='message' for row in body['sources'])
        reference=self.projection
        metadata=load_projection(reference)
        block=items[self.hot_index]['content'][0]
        block['text']=project_text(block['text'],metadata,reference)
        return items
