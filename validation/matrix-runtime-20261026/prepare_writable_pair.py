"""Move closed physical runtimes into paired workspaces; zero model calls."""
from pathlib import Path
import os,sys,shutil
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
PAIR=Path('D:/agent-task-runs/wsc-paired-evaluation-admission-20261026-v1')
OUT=Path('D:/agent-task-runs/wsc-paired-writable-admission-20261026-v1')
SOURCES={'B':Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/arms/B/workspace'),
 'C':Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1/workspace')}
common=read(Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/result.json'))
assert all(v['empty_confirmed'] for v in common['outcomes']['B']['cleanup']) and not common['ledger']['inflight']
latest=read(Path('D:/agent-task-runs/wsc-a3-dev-C-incremental-20261026-v1/result.json'))
assert latest['cleanup']['empty_confirmed'] and not latest['ledger']['inflight']
reg=read(PAIR/'registration.json');assert read(PAIR/'result.json')['native_import_and_cold_access_passed']
OUT.mkdir(exist_ok=False)
moves=[]
for arm in ('B','C'):
 source_root=SOURCES[arm].resolve();target_root=Path(reg['sessions'][arm]['workspace']).resolve()
 assert source_root.is_relative_to(Path('D:/agent-task-runs').resolve())
 assert target_root== (PAIR/arm/'workspace').resolve()
 for relative in ('gui/node_modules','.wsc-runtime/browsers'):
  source=source_root/relative;target=target_root/relative
  assert source.resolve().is_relative_to(source_root) and not os.lstat(source).st_file_attributes & 1024
  assert target.parent.resolve().is_relative_to(target_root)
  is_link=bool(os.lstat(target).st_file_attributes & 1024)
  if relative=='gui/node_modules':
   assert is_link and target.resolve()==(SOURCES['C']/'gui/node_modules').resolve()
  else:
   assert not is_link and not any(target.iterdir())
  moves.append(dict(arm=arm,source=str(source),target=str(target),remove_target_junction=is_link))
save(OUT/'runtime-move-plan.json',moves)
for move in moves:
 source,target=Path(move['source']),Path(move['target'])
 # rmdir removes just the verified reparse entry or verified empty placeholder.
 target.rmdir()
 assert not target.exists() and not target.is_symlink()
 assert target.resolve().is_relative_to((PAIR/move['arm']/'workspace').resolve())
 source.rename(target)
 assert target.is_dir() and not os.lstat(target).st_file_attributes & 1024
save(OUT/'runtime-move-completed.json',moves)
for arm in ('B','C'):
 value=dict(reg['sessions'][arm]);work=Path(value['workspace'])
 original=SOURCES[arm]/'.wsc-runtime/browser-capability.mjs'
 target=work/'.wsc-runtime/browser-capability.mjs';shutil.copyfile(original,target)
 value.update(sandbox='workspace-write',browser_probe=str(target),browser_probe_sha256=file_hash(target))
 reg['sessions'][arm]=value
save(OUT/'prepared.json',dict(sessions=reg['sessions'],conditions=reg['conditions'],envelope=reg['envelope'],
 prior_result=reg['prior_result'],readonly_pair_registration=dict(path=str(PAIR/'registration.json'),sha256=file_hash(PAIR/'registration.json')),
 model_calls=0,paid_development_permitted=False,physical_private_runtime_roots=True,
 parallel_probes_permitted=True,old_readonly_junctions_removed=True,
 scope='Physical closed runtime relocation; no source mutation or new dependency copies'))
print(dict(physical_runtime_moves=len(moves),large_directory_copies=0,model_calls=0))
