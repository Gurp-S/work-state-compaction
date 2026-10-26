"""Move only runtime directories within closed clean workspaces; zero inference."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
from native_application_session import NativeApplicationSession
from native_application_capability import admit

AREA=Path('D:/agent-task-runs/wsc-a3-runtime-root-20261025-v1')
AREA.mkdir(exist_ok=False)
PRIOR=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v2')
results={}
for arm in ('B','C'):
    payload=read(PRIOR/'prepared'/('payload-'+arm+'.json'))
    reg=payload['registration']
    work=Path(reg['workspace']).resolve()
    old=work/'gui/node_modules/.wsc-runtime'
    new=work/'.wsc-runtime'
    assert old.resolve().is_relative_to(work) and new.resolve().is_relative_to(work)
    assert old.resolve()!=new.resolve() and old.is_dir() and not new.exists()
    worker=read(PRIOR/'arms'/arm/'output/worker-result.json')
    assert not worker['phases'] and worker['admission_matched'] is False
    assert all(row['empty_confirmed'] for row in worker['cleanup'])
    save(AREA/(arm+'-move.json'),dict(source=str(old.resolve()),destination=str(new.resolve()),
        workspace=str(work),previous_worker_sha256=file_hash(PRIOR/'arms'/arm/'output/worker-result.json')))
    old.replace(new)
    reg['browser_cache']=str(new/'browsers')
    reg['browser_probe']=str(new/'browser-capability.mjs')
    session=NativeApplicationSession(reg,AREA/arm)
    assert session.source_manifest()==reg['initial_manifest']
    try:
        session.open()
        admit(session,AREA/(arm+'-capability'))
        results[arm]=dict(passed=True,registration=reg)
        print(arm,'passed',flush=True)
    except Exception as error:
        results[arm]=dict(passed=False,error=type(error).__name__+':'+str(error),registration=reg)
        print(arm,results[arm]['error'],flush=True)
    finally:
        results[arm]['cleanup']=session.close()
save(AREA/'result.json',dict(arms=results,model_calls=0))
