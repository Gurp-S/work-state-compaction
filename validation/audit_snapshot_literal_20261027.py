"""Verify persisted before/after outputs against independent source rows."""
from pathlib import Path
from contextlib import closing
from hashlib import sha256
import argparse,json,sys,sqlite3
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wsc.evidence import source_row
from wsc.contracts import digest


def main():
    parser=argparse.ArgumentParser()
    for name in ('fixtures','profile'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();profile=json.loads((args.profile/'result.json').read_text());checks=[]
    for row in profile['rows']:
        name=f"N{row['size']}-at{row['target_seq']}";dbpath=args.fixtures/name/'state.db'
        assert sha256(dbpath.read_bytes()).hexdigest()==row['source_db_sha256'] and row['source_unchanged']
        with closing(sqlite3.connect(dbpath)) as db:
            db.row_factory=sqlite3.Row
            assert db.execute('SELECT count(*) FROM events').fetchone()[0]==row['size']
            for kind in ('legacy','snapshot'):
                raw=json.loads((args.profile/(name+'-'+kind+'.json')).read_text())
                hits=[hit for page in raw['pages'] for hit in page['matches']]
                assert bool(hits)==row[kind]['found'] and len(raw['pages'])==row[kind]['calls']
                assert raw['pages'][-1]['metrics']['rows_verified']==row[kind]['rows_verified']
                for hit in hits:
                    record=source_row(db,hit['original_source_id']);assert digest(record)==hit['source_record_sha256']
                    assert record['seq']==row['target_seq'] and hit['source']=='s'+str(record['seq'])
                    assert record['text']=='receipt:fixed-probe-target historical-value-7f4c'
                    assert record['text'][hit['start']:hit['end']]==hit['text']
                    assert sha256(hit['text'].encode()).hexdigest()==hit['text_sha256']
                    assert record['text'][hit['match_start']:hit['match_end']]=='receipt:fixed-probe-target'
        checks.append(dict(case=name,source_unchanged=True,old_found=row['legacy']['found'],new_found=row['snapshot']['found']))
    result=dict(passed=True,model_calls=0,checks=checks,
        scope='Exact source reachability and evidence binding only; no model answer quality, native comparison, physical I/O or production latency proof.')
    with (args.profile/'audit.json').open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result))


if __name__=='__main__':main()
