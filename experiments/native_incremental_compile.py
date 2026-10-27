"""Mechanical compilation shared by live generation and receipt-bound reuse."""
from dataclasses import replace
from wsc.excerpts import Excerpt
from wsc.contracts import require


def compile_choice(material,previous,draft,compiler):
    value=dict(draft)
    retained=value.pop('retained_excerpt_keys',[])
    require(isinstance(retained,list) and all(isinstance(k,str) for k in retained)
        and len(retained)==len(set(retained)),'incremental_retained_excerpt_keys_invalid')
    known={item['key']:item for item in (previous['excerpts'] if previous else [])}
    require(set(retained)<=known.keys(),'incremental_retained_excerpt_missing')
    selection=compiler(material,value)
    require(set(selection.understanding_refs)<={r['ref'] for r in material['understandings']},'incremental_record_not_offered')
    combined=(*selection.excerpts,*(Excerpt(**known[key]) for key in retained))
    require(len({e.key for e in combined})==len(combined),'incremental_excerpt_key_collision')
    return replace(selection,excerpts=combined)
