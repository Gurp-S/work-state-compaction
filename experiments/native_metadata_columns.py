"""Optional lossless column vectors for already-tabular selector metadata.

No text extraction, ranking, selection, or executable expressions.
"""
from copy import deepcopy
import re
from wsc.contracts import encode,digest,require

FORMAT='wsc.metadata_columns/1'
MAX_ROWS=65536


def vector(values,depth=0):
    candidates=[dict(encoding='values',values=deepcopy(values))]
    if values:
        runs=[]
        for value in values:
            if runs and encode(runs[-1][0])==encode(value):runs[-1][1]+=1
            else:runs.append([deepcopy(value),1])
        candidates.append(dict(encoding='runs',runs=runs))
        dictionary=[];indices=[];known={}
        for value in values:
            key=encode(value)
            if key not in known:known[key]=len(dictionary);dictionary.append(deepcopy(value))
            indices.append(known[key])
        candidates.append(dict(encoding='dictionary',dictionary=dictionary,indices=indices))
        if all(type(v) is int for v in values):
            step=values[1]-values[0] if len(values)>1 else 0
            if all(v==values[0]+i*step for i,v in enumerate(values)):
                candidates.append(dict(encoding='integer_progression',start=values[0],step=step))
        if all(type(v) is str for v in values):
            parts=[re.fullmatch(r'(.*?)(0|[1-9][0-9]*)',v) for v in values]
            if all(parts) and all(len(p[2])<=100 for p in parts) and len({p[1] for p in parts})==1:
                numbers=[int(p[2]) for p in parts];step=numbers[1]-numbers[0] if len(numbers)>1 else 0
                if all(v==numbers[0]+i*step for i,v in enumerate(numbers)):
                    candidates.append(dict(encoding='prefixed_integer_progression',prefix=parts[0][1],start=numbers[0],step=step))
        if depth<8 and all(type(v) is dict and len(v)==1 for v in values):
            keys=[next(iter(v)) for v in values]
            if len(set(keys))==1:
                candidates.append(dict(encoding='single_field_objects',field=keys[0],values=vector([v[keys[0]] for v in values],depth+1)))
    return min(candidates,key=lambda v:len(encode(v).encode()))


def expand(value,count,depth=0):
    require(type(count) is int and 0<=count<=MAX_ROWS and depth<=8,'metadata_column_count_invalid')
    require(type(value) is dict,'metadata_column_shape_invalid')
    mode=value.get('encoding')
    if mode=='values':
        require(set(value)=={'encoding','values'} and type(value['values']) is list,'metadata_values_invalid')
        result=deepcopy(value['values'])
    elif mode=='runs':
        require(set(value)=={'encoding','runs'} and type(value['runs']) is list,'metadata_runs_invalid')
        result=[]
        for run in value['runs']:
            require(type(run) is list and len(run)==2 and type(run[1]) is int and 0<run[1]<=count-len(result),'metadata_run_invalid')
            result.extend(deepcopy(run[0]) for _ in range(run[1]))
    elif mode=='dictionary':
        require(set(value)=={'encoding','dictionary','indices'} and type(value['dictionary']) is list and type(value['indices']) is list,'metadata_dictionary_invalid')
        require(len(value['indices'])==count and all(type(i) is int and 0<=i<len(value['dictionary']) for i in value['indices']),'metadata_index_invalid')
        result=[deepcopy(value['dictionary'][i]) for i in value['indices']]
    elif mode in ('integer_progression','prefixed_integer_progression'):
        fields={'encoding','start','step'}|({'prefix'} if mode=='prefixed_integer_progression' else set())
        require(set(value)==fields and type(value['start']) is int and type(value['step']) is int,'metadata_progression_invalid')
        result=[value['start']+i*value['step'] for i in range(count)]
        if mode=='prefixed_integer_progression':
            require(type(value['prefix']) is str and all(v>=0 for v in result),'metadata_prefix_invalid')
            result=[value['prefix']+str(v) for v in result]
    elif mode=='single_field_objects':
        require(set(value)=={'encoding','field','values'} and type(value['field']) is str,'metadata_object_invalid')
        result=[{value['field']:v} for v in expand(value['values'],count,depth+1)]
    else:raise ValueError('metadata_encoding_unknown')
    require(len(result)==count,'metadata_column_length_invalid')
    return result


def table(rows):
    if type(rows) is not list or not rows or len(rows)>MAX_ROWS:return None
    if not all(type(row) is list and len(row)==len(rows[0]) for row in rows):return None
    result=dict(format=FORMAT,row_count=len(rows),column_vectors=[vector([row[i] for row in rows]) for i in range(len(rows[0]))])
    return result if len(encode(result).encode())<len(encode(rows).encode()) else None


def project(material):
    result=deepcopy(material);paths=[]
    candidates=[]
    events=result.get('events')
    if type(events) is dict and events.get('format')=='wsc.cold_event_rows/1' and type(events.get('rows')) is list:
        candidates.append((['events','rows'],events))
    facts=result.get('selection_facts',{}).get('source_record_table')
    if type(facts) is dict and set(facts)=={'columns','rows'}:candidates.append((['selection_facts','source_record_table','rows'],facts))
    for path,parent in candidates:
        encoded=table(parent['rows'])
        if encoded is not None:parent['rows']=encoded;paths.append(path)
    binding=dict(format='wsc.metadata_column_binding/1',paths=paths,original_sha256=digest(material),represented_sha256=digest(result))
    require(encode(restore(result,binding))==encode(material),'metadata_roundtrip_changed')
    return result,binding


def restore(material,binding):
    require(binding.get('format')=='wsc.metadata_column_binding/1' and digest(material)==binding['represented_sha256'],'metadata_binding_changed')
    result=deepcopy(material);paths=binding['paths']
    allowed=[['events','rows'],['selection_facts','source_record_table','rows']]
    require(type(paths) is list and all(p in allowed for p in paths) and len({tuple(p) for p in paths})==len(paths),'metadata_paths_invalid')
    for path in paths:
        parent=result
        for key in path[:-1]:parent=parent[key]
        value=parent[path[-1]]
        require(type(value) is dict and set(value)=={'format','row_count','column_vectors'} and value['format']==FORMAT and type(value['column_vectors']) is list,'metadata_table_invalid')
        columns=[expand(c,value['row_count']) for c in value['column_vectors']]
        parent[path[-1]]=[list(row) for row in zip(*columns)] if columns else [[] for _ in range(value['row_count'])]
    require(digest(result)==binding['original_sha256'],'metadata_roundtrip_changed')
    return result
