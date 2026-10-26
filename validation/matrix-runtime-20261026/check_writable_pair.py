"""Parallel native writable-root and actual A3 browser admission; zero inference."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json,sys,time,os
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash
from native_application_session import NativeApplicationSession
from native_application_capability import admit
from native_paired_evaluation import load_facts
from native_evaluation_context import capture,from_bound_probe
from native_rollout_snapshot import capture_rollout
OUT=Path('D:/agent-task-runs/wsc-paired-writable-admission-20261026-v1')
p=read(OUT/'prepared.json');sessions=p['sessions']
probe=ROOT/'validation/matrix-runtime-20261026/check_s2_clipping.mjs'
started=time.monotonic()
save(OUT/'registration.json',dict(created_at=datetime.now(timezone.utc).isoformat(),prepared_sha256=file_hash(OUT/'prepared.json'),
 sessions=sessions,conditions=p['conditions'],envelope=p['envelope'],model_calls=0,automatic_retries=0,
 checks=['private_directory_roots','native_own_write','native_cross_write_denied','native_browser_capability','native_A3_geometry'],
 scope='Zero-inference environment admission, not native or WSC continuation'))
def check(arm):
 reg=sessions[arm];work=Path(reg['workspace']);area=OUT/arm;area.mkdir()
 session=NativeApplicationSession(reg,area/'receiver');result=dict(passed=False,model_calls=0)
 try:
  facts=load_facts(reg)
  assert facts is not None
  for relative in ('gui/node_modules','.wsc-runtime/browsers'):
   assert not os.lstat(work/relative).st_file_attributes & 1024
  session.open()
  own=work/'.wsc-runtime'/('ownership-'+arm+'.json')
  other=Path(sessions['C' if arm=='B' else 'B']['workspace'])/'.wsc-runtime'/('cross-write-from-'+arm+'.json')
  code="const fs=require('node:fs'),path=require('node:path');fs.writeFileSync(process.argv[1],JSON.stringify({arm:process.argv[3]}),{flag:'wx'});let denied=false,error=null;const parentVisible=fs.existsSync(path.dirname(process.argv[2]));try{fs.writeFileSync(process.argv[2],'cross-write-probe',{flag:'wx'});}catch(e){error=e.code;denied=['EACCES','EPERM'].includes(e.code);}console.log(JSON.stringify({ownWrite:true,parentVisible,crossWriteDenied:denied,error}));if(!parentVisible||!denied)process.exitCode=2;"
  execution=session.server.call('command/exec',dict(command=[reg['node_executable'],'-e',code,str(own),str(other),arm],
    cwd=str(work),sandboxPolicy=dict(type='workspaceWrite',writableRoots=[str(work)],networkAccess=False),timeoutMs=20000),timeout=30)
  save(area/'write-isolation-execution.json',execution)
  result['write_isolation']=json.loads(execution.get('stdout') or '{}')
  assert execution['exitCode']==0,'native_writable_root_isolation_failed'
  assert read(own)['arm']==arm
  admit(session,area/'generic-browser-capability')
  context=capture(work/'gui',reg['fixture_root'],probe,entry='production_panel',scenario='normal',viewport=dict(width=1440,height=1000))
  save(area/'context-registration.json',context)
  output=work/'.wsc-probes'/('actual-A3-'+session.opened['thread']['id'])
  command=[reg['node_executable'],str(probe),str(work/'gui'),reg['fixture_root'],str(output)]
  execution=session.server.call('command/exec',dict(command=command,cwd=str(work),sandboxPolicy=dict(type='workspaceWrite',
    writableRoots=[str(work)],networkAccess=False),timeoutMs=35000),timeout=45)
  save(area/'A3-browser-execution.json',execution)
  assert execution['exitCode']==0,'native_A3_browser_execution_failed'
  observation=from_bound_probe(work/'gui',reg['fixture_root'],probe,area/'context-registration.json',output/'registration.json',output/'result.json')
  save(area/'A3-observation.json',observation)
  assert not observation['clipping_observed'] and observation['real_wheel_changed_scroll']
  result.update(passed=True,native_browser_qualified=True,actual_A3_browser_qualified=True,
    actual_browser_version=observation['browser'],source_binding=observation['source_binding'])
 except Exception as error:result['error']=type(error).__name__+':'+str(error)
 finally:
  result['cleanup']=session.close()
  if session.opened:
   snapshot=capture_rollout(session.opened['thread']['path'],archive=area/'closed-native.jsonl')
   result['no_token_usage_records']=snapshot.metadata['parse_complete'] and not any(row['type']=='token_usage_record' for row in snapshot.rows)
  else:result['no_token_usage_records']=True
  result['source_unchanged']=session.source_manifest()==reg['initial_manifest']
  result['passed']=result['passed'] and result['source_unchanged'] and result['no_token_usage_records'] and bool(result['cleanup'] and result['cleanup']['empty_confirmed'])
  save(area/'result.json',result)
 return arm,result
with ThreadPoolExecutor(max_workers=2) as pool:results=dict(pool.map(check,['B','C']))
assert file_hash(p['prior_result']['path'])==p['prior_result']['sha256']
review=dict(model_calls=0,results=results,parallel_writable_native_admission_passed=all(r['passed'] for r in results.values()),
 large_directory_copies=0,private_physical_runtime_roots=True,old_ledger_unchanged=True,historical_usage_still_unknown=True,
 elapsed_seconds=round(time.monotonic()-started,3),paid_development_started=False,formal_BC_started=False,
 scope='Two parallel native environment admissions; no continuation, compaction or benefit result',
 next_step='If environment passes, assess registered continuation hypothesis and budget; never automatically repeat an old 6M run')
save(OUT/'result.json',review)
print(json.dumps(review,ensure_ascii=False))
