"""Byte-level audit of WSC-owned hot wire only; not native request tokens."""
import argparse
from hashlib import sha256
import json
from pathlib import Path


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')


def audit(base,repetitions):
    rows={}
    for label,folder in [('r1',base)]+[(name,repetitions/name) for name in ('r2','r3')]:
        publication=folder/'coordinator-private/C/publication.json'
        raw=publication.read_bytes();package=json.loads(raw)['package']
        candidates=[]
        for item in package['items']:
            for content in item.get('content',[]):
                text=content.get('text','');first=text.split('\n',1)[0]
                try:header=json.loads(first)
                except ValueError:continue
                if header.get('format')=='wsc.indexed_sections/1':candidates.append((text,header))
        if len(candidates)!=1:raise ValueError('indexed_actor_header_not_unique')
        text,header=candidates[0]
        aliases=header['source_aliases']
        rows[label]=dict(publication_sha256=sha256(raw).hexdigest(),
            whole_hot_text_bytes=len(text.encode('utf-8')),header_bytes=len(text.split('\n',1)[0].encode('utf-8')),
            header_value_bytes={key:len(encoded(value)) for key,value in header.items()},
            alias_count=len(aliases),null_observation_times=sum(row['observed_at'] is None for row in aliases.values()),
            archive_paths_all_coordinator_private=all('coordinator-private' in str(value)
                for key,value in header['archive'].items() if key in ('sources','understandings')))
    return dict(samples=rows,model_calls=0,algorithm_modified=False,
        tokens=None,scope='WSC-owned visible text bytes only. No token savings or cache causality claim; native opaque summary is not inspected.',
        candidate_boundary='Keep semantic text, source selection, applicability and non-null observation times. Investigate moving canonical IDs/hash/path bindings to engine-side metadata with exact restoration and alias checks.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--repetitions',type=Path,required=True)
    args=parser.parse_args();value=audit(args.base,args.repetitions)
    with (args.repetitions/'actor-input-byte-audit.json').open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    print(json.dumps(value,ensure_ascii=False))
