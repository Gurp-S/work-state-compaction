"""Seal the closed first wave without changing its original outcomes."""
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash

AREA=Path('D:/agent-task-runs/wsc-application-matrix-20261025-v3')
review=read(HERE/'first-wave-review.json')
reg=read(AREA/'registration.json')
assert all(file_hash(path)==value for path,value in reg['pins'].items())
assert review['all_owned_processes_empty'] and review['formal_valid_pairs']==0
base=read(HERE/'delivery.json')
assert file_hash(base['version'])==base['sha256']
files={}
for path in AREA.rglob('*'):
    if path.is_file():
        files['evidence/study-v3/'+path.relative_to(AREA).as_posix()]=path
for path in HERE.rglob('*'):
    if path.is_file() and '__pycache__' not in path.parts and path.name!='closure-delivery.json':
        files[path.relative_to(ROOT).as_posix()]=path
for name in ('experiments/native_application_budget_policy.py','experiments/NATIVE-LOCAL-HANDOFF.md',
             'reviews/2026-10-25-native-matrix-runtime.md'):
    files[name]=ROOT/name
partial={}
for task in ('a3','collaboration'):
    binding=read(reg['tasks'][task]['binding'])
    for arm in ('B','C'):
        prepared=read(AREA/'trajectories'/task/'r1'/arm/'output/prepared-input.json')
        work=Path(prepared['registration']['workspace'])
        current={}
        for directory,folders,names in os.walk(work,followlinks=False):
            parent=Path(directory)
            folders[:]=[name for name in folders if name not in ('node_modules','__pycache__','.git')]
            for name in names:
                path=parent/name
                if path.suffix=='.pyc':
                    continue
                key=path.relative_to(work).as_posix()
                current[key]=file_hash(path)
                if current[key]!=binding['source_manifest'].get(key):
                    files['partial-unqualified-workspaces/'+task+'/'+arm+'/'+key]=path
        partial[task+'/'+arm]=dict(source_manifest=current,
            deleted_source_keys=sorted(set(binding['source_manifest'])-set(current)),
            scope='Interrupted partial artifact, not accepted application delivery')
index=dict(format='closed_first_wave_and_unlaunched_budget_proposal',captured_at=datetime.now(timezone.utc).isoformat(),
    base=base['version'],base_sha256=base['sha256'],files={name:file_hash(path) for name,path in files.items()},
    partial_workspace_manifests=partial,executed_runtime_pins=reg['pins'],
    proposal_module_executed_in_study=False,known_responses=review['known_responses'],
    known_usage=review['known_usage'],complete_usage=None,formal_valid_pairs=0,remaining_pairs=13)
version=ROOT/'versions/20261025-native-matrix-first-wave-closure-v1-delta.zip'
with zipfile.ZipFile(version,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,path in files.items():
        archive.write(path,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(version),bytes=version.stat().st_size,sha256=file_hash(version),
    files=len(files),known_responses=review['known_responses'],known_total_tokens=review['known_usage']['total_tokens'],
    complete_usage=None,formal_valid_pairs=0,new_model_calls=0,all_owned_processes_empty=True)
save(HERE/'closure-delivery.json',receipt)
print(json.dumps(receipt))
