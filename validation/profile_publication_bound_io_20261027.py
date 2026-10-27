"""Same-path, same-byte warm publication A/B; all checks retained, no models."""
from pathlib import Path
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch
from hashlib import sha256
import argparse,json,sys,sqlite3,time,statistics
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc import WSC,Store,Limits
from wsc.resource_io import ResourceIO
from wsc.bound_windows_io import BoundWindowsIO
from wsc.publication import check_evidence
from wsc.source_reference_view import MODE
from native_incremental_candidate import frontier,compile_draft,POLICY
from native_incremental_compile import compile_choice
from native_indexed_checkpoint import IndexedCheckpointAdapter
from native_evidence import read,save,file_hash


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','candidate','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();source=args.source/'R01';candidate=args.candidate/'candidate'
    if not read(args.candidate/'table-run-audit.json')['passed']:raise ValueError('source_not_audited')
    source_sha=file_hash(source/'state.db');args.out.mkdir(parents=True,exist_ok=False)
    draft=read(candidate/'generation/compiled-draft.json');previous=read(source/'C1-continuation.json')
    producer=read(candidate/'registration.json')['policy'];path=args.out/'working.db';reference=None;objects=None;pairs=[];begin=time.perf_counter()
    def one(kind):
        nonlocal reference,objects
        with closing(sqlite3.connect(source/'state.db')) as a,closing(sqlite3.connect(path)) as b:a.backup(b)
        with closing(sqlite3.connect(path)) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
        io=kind();core=WSC(Store(path,session_id=binding['session_id'],workspace=binding['workspace']),access=lambda *a:True,
            resource_io=io,query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')
        snapshot=core.capture();material,_=frontier(core,snapshot,previous,args.out/'cold-public')
        selection=compile_choice(material,previous,draft,compile_draft)
        view=core.prepare(snapshot,selection,producer=producer,limits=Limits(max_material_bytes=POLICY['max_material_bytes'],max_view_bytes=POLICY['max_view_body_bytes']),source_projection=MODE)
        # Fixed publication identity only in this controlled replay. Live UUID
        # allocation is unchanged; all output paths are equal across A and B.
        start=time.perf_counter()
        with patch('wsc.publication.uuid4',return_value=SimpleNamespace(hex='e'*32)):
            op=core.stage(view,directory=args.out/'publication',archive_directory=args.out/'cold-objects',adapter=IndexedCheckpointAdapter())
        package=core.package(op);check_evidence(core,package);elapsed=time.perf_counter()-start
        raw=json.dumps(package,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        paths=[p for folder in ('publication','cold-objects') for p in (args.out/folder).rglob('*') if p.is_file()]
        current={str(p.relative_to(args.out)):file_hash(p) for p in paths}
        if reference is None:reference=raw;objects=current
        else:assert reference==raw and current==objects
        core.discard(op)
        return dict(seconds=elapsed,bytes_read=io.bytes_read,package_sha256=sha256(raw).hexdigest(),object_files=len(current))
    one(ResourceIO) # Identical pre-existing durable files for every measured run.
    for trial in range(5):
        row={}
        for label,kind in ([('original',ResourceIO),('bound',BoundWindowsIO)] if trial%2==0 else [('bound',BoundWindowsIO),('original',ResourceIO)]):row[label]=one(kind)
        assert row['original']['bytes_read']==row['bound']['bytes_read'];pairs.append(row)
    assert source_sha==file_hash(source/'state.db')
    result=dict(model_calls=0,pairs=pairs,seconds=time.perf_counter()-begin,source_unchanged=True,all_packages_and_objects_byte_identical=True,
        original_median=statistics.median(x['original']['seconds'] for x in pairs),bound_median=statistics.median(x['bound']['seconds'] for x in pairs),
        scope='Alternating five warm-publication pairs on identical paths and outputs. No fsync/hash/authorization/integrity check removed; not cold-write or model end-to-end speed proof.')
    save(args.out/'result.json',result);print(json.dumps(result))


if __name__=='__main__':main()
