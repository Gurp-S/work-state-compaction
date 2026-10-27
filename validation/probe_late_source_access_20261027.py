"""Zero-model reachability probe with exact late-source ground truth."""
from pathlib import Path
import argparse,json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wsc import WSC,Store,Event
from wsc.source_access import SnapshotSourceAccess


def search(reader,literal):
    cursor=0;pages=[]
    for _ in range(reader.limits.max_calls):
        page=reader.find(literal,cursor=cursor);pages.append(page)
        if page['matches'] or page['complete'] or page['errors']:break
        next_cursor=page['next_cursor']
        if next_cursor is None or next_cursor<=cursor:break
        cursor=next_cursor
    return dict(found=any(p['matches'] for p in pages),complete=pages[-1]['complete'],pages=pages,
        metrics=pages[-1]['metrics'])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);rows=[];begin=time.monotonic()
    literal='receipt:fixed-probe-target';expected='historical-value-7f4c'
    for size in (128,512,1024,4096):
        for location in (6,size-8):
            area=args.out/f'N{size}-at{location}';area.mkdir()
            core=WSC(Store(area/'state.db',session_id=area.name,workspace=str(area)),access=lambda *a:True)
            events=[Event('event-'+str(i),'observation',{},text=f'log {i}: unrelated observation') for i in range(1,size+1)]
            events[location-1]=Event('event-'+str(location),'observation',{},text=literal+' '+expected)
            core.ingest(events);snapshot=core.capture();reader=SnapshotSourceAccess(core.store,snapshot,access=core.access)
            start=time.monotonic();result=search(reader,literal);seconds=time.monotonic()-start
            direct=SnapshotSourceAccess(core.store,snapshot,access=core.access).read('s'+str(location))
            assert direct['text']==literal+' '+expected
            row=dict(size=size,target_seq=location,found=result['found'],complete=result['complete'],
                pages=len(result['pages']),rows_verified=result['metrics']['rows_verified'],seconds=seconds,
                direct_known_alias_read_correct=True,errors=result['pages'][-1]['errors'])
            rows.append(row);(area/'search.json').write_text(json.dumps(result,indent=2))
    result=dict(model_calls=0,rows=rows,seconds=time.monotonic()-begin,
        scope='Literal discovery under normal bounded API; no model inference or native comparison. Known-alias read proves existence, not model discoverability.')
    (args.out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':main()
