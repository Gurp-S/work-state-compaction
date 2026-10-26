"""Reuse closed zero-inference clean inputs after runtime directory admission."""
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys

HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('a3_pilot_v2',HERE/'a3_pilot_v2.py')
base=importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
from native_application_session import NativeApplicationSession

OLD=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v2')
ROOT_CHECK=Path('D:/agent-task-runs/wsc-a3-runtime-root-20261025-v1')
AREA=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v3')
base.AREA=AREA
original_history=base.history


def history():
    envelope,files=original_history()
    zero=base.read(OLD/'result.json')
    assert zero['ledger']['study']['tokens']==zero['ledger']['study']['responses']==0
    assert not zero['ledger']['study']['uncertain'] and not zero['ledger']['inflight']
    checked=base.read(ROOT_CHECK/'result.json')
    assert checked['model_calls']==0
    assert all(row['passed'] and row['cleanup']['empty_confirmed'] for row in checked['arms'].values())
    extra=((OLD/'result.json').stat().st_mtime-(OLD/'registration.json').stat().st_mtime
           +(ROOT_CHECK/'result.json').stat().st_mtime-(ROOT_CHECK/'B-move.json').stat().st_mtime)
    assert extra>=0
    envelope['remaining_limits']['max_seconds']-=math.ceil(extra)
    envelope['elapsed_execution_wall_seconds']+=extra
    for path in (OLD/'result.json',OLD/'registration.json',ROOT_CHECK/'result.json'):
        files[str(path)]=base.file_hash(path)
    return envelope,files


base.history=history


def register():
    AREA.mkdir(exist_ok=False)
    previous=base.read(OLD/'prepared.json')
    root=base.read(ROOT_CHECK/'result.json')
    jobs=deepcopy(previous['jobs'])
    payload_files={}
    for job in jobs:
        arm=job['arm']
        worker=base.read(OLD/'arms'/arm/'output/worker-result.json')
        assert not worker['phases'] and worker['admission_matched'] is False
        assert all(item['empty_confirmed'] for item in worker['cleanup'])
        payload=base.read(OLD/'prepared'/('payload-'+arm+'.json'))
        payload['registration']=root['arms'][arm]['registration']
        source=NativeApplicationSession(payload['registration'],AREA/('source-check-'+arm))
        assert source.source_manifest()==payload['registration']['initial_manifest']
        job['pair_id']='a3/qualification3'
        job['resources']['output']=str(AREA/'arms'/arm/'output')
        job['resources']['browser_profile']=str(AREA/'arms'/arm/'browser-profile')
        payload_path=AREA/'prepared'/('payload-'+arm+'.json')
        base.save(payload_path,payload)
        payload_files[str(payload_path)]=base.file_hash(payload_path)
    previous.update(jobs=jobs,payload_files=payload_files)
    previous['envelope'],previous['history_files']=history()
    previous['input_reuse']=dict(original_preparation=str(OLD/'prepared.json'),
        original_preparation_sha256=base.file_hash(OLD/'prepared.json'),
        zero_inference_result=str(OLD/'result.json'),zero_inference_result_sha256=base.file_hash(OLD/'result.json'),
        root_capability=str(ROOT_CHECK/'result.json'),scope='Clean source unchanged; only private runtime directory moved')
    base.save(AREA/'prepared.json',previous)
    base.register()
    path=AREA/'registration.json'
    # Add the dispatch wrapper to the registration before any model is started.
    registration=base.read(path)
    registration['pins'][str(Path(__file__).resolve())]=base.file_hash(__file__)
    registration['pins'][str((HERE/'a3_pilot_v2.py').resolve())]=base.file_hash(HERE/'a3_pilot_v2.py')
    registration['input_reuse']=previous['input_reuse']
    path.write_text(base.json.dumps(registration,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':
    {'register':register,'run':base.run}[sys.argv[1]]()
