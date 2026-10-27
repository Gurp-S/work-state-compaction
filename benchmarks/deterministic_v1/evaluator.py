"""Shared exact-field evaluator. Natural language/opaque contents abstain."""
import json
from dataset import canonical


def decode(items):
    records=[];opaque=False
    def consume(text):
        try:value=json.loads(text)
        except (ValueError,TypeError):return
        if not isinstance(value,dict):return
        if type(value.get('seq')) is int and isinstance(value.get('record'),dict):
            record=value['record']
            if record.get('record_type')=='bench.fact/1':records.append(value)
        if value.get('kind')=='working_state':
            for field in ('historical_excerpts','observations'):
                for part in value.get(field,[]):consume(part.get('text'))
    for item in items:
        if item.get('type') in ('compaction','reasoning'):opaque=True
        if item.get('type')=='message':
            for part in item.get('content',[]):consume(part.get('text'))
    # Same source may be present in both an excerpt and a retained message.
    unique={canonical(row):row for row in records}
    return list(unique.values()),opaque


def state(records,tick,*,task='application'):
    selected={}
    for row in records:
        p=row['record']
        if p.get('task')!=task:continue
        if not {'fact_id','value','valid_from','valid_to','priority','dependencies'}<=p.keys():continue
        if type(p['valid_from']) is not int or type(p['priority']) is not int:continue
        if p['valid_from']>tick:continue
        key=p['fact_id'];rank=(p['priority'],row['seq'])
        if key not in selected or rank>selected[key][0]:selected[key]=(rank,p)
    values={key:p['value'] for key,(_,p) in selected.items()
            if p['valid_to'] is None or (type(p['valid_to']) is int and tick<p['valid_to'])}
    if 'source.version' in values and 'test.version' in values:
        deps=selected['test.version'][1]['dependencies']
        if deps==['source.version']:
            values['validation.current']=values['source.version']==values['test.version']
    return values


def evaluate(items,oracle,tick):
    records,opaque=decode(items)
    actual=state(records,tick,task=oracle.get('task','application'));details=[]
    for key,expected in oracle['expected'].items():
        verdict='undecidable' if key not in actual else ('correct' if canonical(actual[key])==canonical(expected) else 'incorrect')
        details.append(dict(fact_id=key,category=oracle['categories'][key],verdict=verdict,
            expected=expected,actual=actual.get(key),actual_present=key in actual))
    n=len(details);correct=sum(d['verdict']=='correct' for d in details)
    wrong=sum(d['verdict']=='incorrect' for d in details);known=correct+wrong
    categories={}
    for category in sorted({d['category'] for d in details}):
        subset=[d for d in details if d['category']==category]
        counts={v:sum(d['verdict']==v for d in subset) for v in ('correct','incorrect','undecidable')}
        decided=counts['correct']+counts['incorrect']
        categories[category]={**counts,'coverage':decided/len(subset),
            'accuracy_on_decidable':counts['correct']/decided if decided else None}
    return dict(verifiable_questions=n,correct=correct,incorrect=wrong,undecidable=n-known,
        coverage=known/n if n else None,confirmed_recall_lower_bound=correct/n if n else None,
        accuracy_on_decidable=correct/known if known else None,opaque_payload_present=opaque,
        by_category=categories,details=details,scoring_scope='Exact structured protocol only; no free-text semantic inference.')
