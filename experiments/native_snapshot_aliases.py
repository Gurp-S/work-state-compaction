"""Exact engine identities; no semantic selection or repair of old references."""
import json
from wsc.contracts import require

POLICY='snapshot_event_seq_v1'


class SourceAliases:
    def __init__(self,source,identities=None):
        self.aliases={}
        seen=set()
        remaining=set(identities) if identities is not None else None
        if remaining is not None and not remaining:return
        for row in source:
            seq=row['seq'];identity=row['id']
            if remaining is not None and identity not in remaining:continue
            require(type(seq) is int and seq>0 and identity not in self.aliases,'snapshot_alias_identity_invalid')
            alias='s'+str(seq)
            require(alias not in seen,'snapshot_alias_sequence_ambiguous')
            seen.add(alias);self.aliases[identity]=alias
            if remaining is not None:
                remaining.remove(identity)
                if not remaining:break
        require(not remaining,'snapshot_alias_source_not_bound')
    @classmethod
    def from_facts(cls,source,facts):
        wanted={value['source_id'] for field in ('model_records','clues') for row in facts[field] for value in row['sources']}
        wanted.update(row['source']['source_id'] for row in facts['historical_excerpts'])
        wanted.update(row['source']['source_id'] for row in facts.get('observations',[]) if 'source' in row)
        return cls(source,wanted)
    def get(self,identity):
        require(identity in self.aliases,'snapshot_alias_source_not_bound')
        return self.aliases[identity]


def validate_recovery_aliases(package,reader):
    for item in package['items']:
        for content in item.get('content',[]):
            text=content.get('text','')
            try:header=json.loads(text.splitlines()[0])
            except (ValueError,IndexError):continue
            if not isinstance(header,dict) or header.get('format')!='wsc.indexed_sections/1':continue
            for alias,value in header.get('source_aliases',{}).items():
                identity=value['source_id']
                require(alias in reader.aliases and identity in reader.aliases
                        and reader.aliases[alias]==reader.aliases[identity],'checkpoint_recovery_alias_mismatch')
