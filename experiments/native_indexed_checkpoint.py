"""Lossless indexed provenance and literal text sections for native checkpoints."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from wsc.contracts import encode,require
from wsc.evidence import write_once
from wsc.source_reference_view import MODE


class IndexedCheckpointAdapter(RecordedCodexCheckpointAdapter):
    def __init__(self,*,source_alias_policy='snapshot_event_seq_v1'):
        require(source_alias_policy in {'legacy_dense_v1','snapshot_event_seq_v1'},'indexed_alias_policy_unknown')
        self.projection=None;self.source_alias_policy=source_alias_policy
    def capabilities(self):
        return {**super().capabilities(),'adapter':'codex_indexed_sections_v1','source_projection':MODE,
            **({'projection_evidence':self.projection} if self.projection else {})}

    def render(self,body,source,cut,locators,*,source_index,understanding_index):
        items=super().render(body,source,cut,locators,source_index=source_index,understanding_index=understanding_index)
        index=sum(row['kind']=='message' for row in body['sources'])
        facts=json.loads(items[index]['content'][0]['text'])
        sections=[]
        template=deepcopy(facts)
        aliases={}
        spine={}
        canonical=None
        if self.source_alias_policy=='snapshot_event_seq_v1':
            from native_snapshot_aliases import SourceAliases
            canonical=SourceAliases.from_facts(source,facts)
        def alias(value):
            identity=value['source_id']
            if identity not in aliases:
                key=canonical.get(identity) if canonical is not None else 's'+str(len(aliases))
                aliases[identity]=key
                spine[key]=dict(source_id=identity,observed_at=value.get('observed_at'))
            return aliases[identity]
        def section(text,kind,source_ref=None):
            key='t'+str(len(sections))
            sections.append(dict(id=key,kind=kind,source=source_ref,text=text,bytes=len(text.encode()),sha256=sha256(text.encode()).hexdigest()))
            return key
        compact=dict(kind='working_state',format='wsc.indexed_sections/1',model_records=[],clues=[],historical_excerpts=[],observations=[])
        for field in ('model_records','clues'):
            for n,row in enumerate(facts[field]):
                entry={k:v for k,v in row.items() if k not in ('sources','text')}
                entry['sources']=[alias(value) for value in row['sources']]
                entry['text_section']=section(row['text'],field)
                template[field][n]['text']={'$section':entry['text_section']}
                compact[field].append(entry)
        for n,row in enumerate(facts['historical_excerpts']):
            ref=alias(row['source'])
            text=section(row['text'],'historical_excerpts',ref)
            template['historical_excerpts'][n]['text']={'$section':text}
            compact['historical_excerpts'].append(dict(kind=row['kind'],source=ref,text_section=text))
        for n,row in enumerate(facts.get('observations',[])):
            entry=dict(reference='e'+str(n))
            if 'inline_coverage' in row:
                entry['inline_coverage']=row['inline_coverage']
            else:
                entry['source']=alias(row['source'])
                entry['text_section']=section(row['text'],'observations',entry['source'])
                template['observations'][n]['text']={'$section':entry['text_section']}
            if 'current_reference' in row:entry['current_reference']=row['current_reference']
            compact['observations'].append(entry)
        compact['source_aliases']=spine
        compact['source_alias_policy']=self.source_alias_policy
        compact['archive']=deepcopy(facts['archive'])
        metadata=dict(format='wsc.indexed_sections/1',fact_template=template,header=deepcopy(compact),
            sections=[{k:v for k,v in section.items() if k!='text'} for section in sections])
        path=Path(source_index).parent/'projection.json'
        raw=encode(metadata).encode()
        write_once(path,raw)
        self.projection=dict(file_path=str(path),sha256=sha256(raw).hexdigest())
        compact['archive']={**facts['archive'],'projection':self.projection}
        lines=[encode(compact)]
        for value in sections:
            lines.extend([f"[WSC section {value['id']} kind={value['kind']} source={value['source'] or '-'} bytes={value['bytes']}]",value['text']])
        items[index]['content'][0]['text']='\n'.join(lines)
        return items


def expand_working_state(text,metadata):
    raw=text.encode()
    header,raw=raw.split(b'\n',1)
    compact=json.loads(header)
    require(compact.get('format')=='wsc.indexed_sections/1','indexed_state_format_unknown')
    projection=compact['archive'].pop('projection')
    require(sha256(encode(metadata).encode()).hexdigest()==projection['sha256'],
            'indexed_state_metadata_changed')
    require(compact==metadata['header'],'indexed_state_header_changed')
    values={}
    for n,section in enumerate(metadata['sections']):
        line,raw=raw.split(b'\n',1)
        expected=f"[WSC section {section['id']} kind={section['kind']} source={section['source'] or '-'} bytes={section['bytes']}]".encode()
        require(line==expected,'indexed_state_section_header_changed')
        value,raw=raw[:section['bytes']],raw[section['bytes']:]
        require(sha256(value).hexdigest()==section['sha256'],'indexed_state_text_changed')
        values[section['id']]=value.decode('utf8',errors='strict')
        if n+1<len(metadata['sections']):
            require(raw.startswith(b'\n'),'indexed_state_separator_changed')
            raw=raw[1:]
    require(not raw,'indexed_state_tail_changed')
    def expand(node):
        if isinstance(node,dict):
            if set(node)=={'$section'}:return values[node['$section']]
            return {k:expand(value) for k,value in node.items()}
        if isinstance(node,list):return [expand(value) for value in node]
        return node
    return expand(metadata['fact_template'])
