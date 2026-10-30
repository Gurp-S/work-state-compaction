"""Identical owned Python assets and no-inference native admission for both arms."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil

from .permissions import permission_flags, PROFILE, runtime_startup_flags


def digest(path):
    value=sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    return value.hexdigest()


def verify_runtime(folder):
    folder=Path(folder)
    if folder.is_symlink() or getattr(folder.lstat(),'st_file_attributes',0) & 0x400:
        raise ValueError('runtime_link_not_allowed')
    value=json.loads((folder/'runtime-manifest.json').read_text(encoding='utf-8'))
    if value['version']!='3.11.9':raise ValueError('runtime_version_not_qualified')
    expected=value['files']
    if not {'python.exe','python311.dll','stdlib.zip','python311._pth'} <= expected.keys():
        raise ValueError('runtime_assets_missing')
    actual=set()
    for path in folder.rglob('*'):
        if getattr(path.lstat(),'st_file_attributes',0) & 0x400 or path.is_symlink():
            raise ValueError('runtime_link_not_allowed')
        if path.is_file() and path!=folder/'runtime-manifest.json':actual.add(path.relative_to(folder).as_posix())
    if actual!=set(expected):raise ValueError('runtime_inventory_changed')
    for name,entry in expected.items():
        relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
            raise ValueError('runtime_manifest_path_invalid')
        path=folder/name
        if path.stat().st_size!=entry['bytes'] or digest(path)!=entry['sha256']:
            raise ValueError('runtime_asset_changed:'+name)
    if sum(v['bytes'] for v in expected.values())!=value['bytes']:
        raise ValueError('runtime_total_changed')
    if (folder/'python311._pth').read_bytes()!=b'stdlib.zip\nDLLs\n.\n':
        raise ValueError('runtime_search_path_changed')
    return value


def provision_pair(source,out,*,arms=('Bprime','C')):
    """Copy only after validation, then verify both against the same manifest."""
    source=Path(source);out=Path(out)
    value=verify_runtime(source)
    expected=digest(source/'runtime-manifest.json')
    for name in arms:
        destination=out/name/'.runtime'
        shutil.copytree(source,destination)
        if verify_runtime(destination)!=value or digest(destination/'runtime-manifest.json')!=expected:
            raise ValueError('runtime_copy_changed')
    return dict(manifest_sha256=expected,version=value['version'],bytes_per_arm=value['bytes'],
                relative_executable='.runtime/python.exe',provisioning='copy_existing_local_installation_no_download')


def environment_facts(binding):
    return dict(record_type='bench.environment/1',python=dict(executable=binding['relative_executable'],
                version=binding['version'],stdlib=['unittest','sqlite3','hashlib']))


def qualify_pair(plan,out,*,material_inputs=None,private_probes=()):
    """Native command/exec check only; never executes a model turn or compact."""
    from native_blackbox_sessions import fresh
    out=Path(out);private=out/'coordinator-private'
    canary=private/'runtime-private-canary.txt'
    canary.write_text('runtime-admission-private-canary',encoding='utf-8')
    results={}
    code=('import sys,json,unittest,sqlite3,hashlib;from pathlib import Path;denials=[]\n'
          'for path in sys.argv[1:]:\n'
          ' try:Path(path).read_bytes();denials.append(False)\n'
          ' except PermissionError:denials.append(True)\n'
          'print(json.dumps(dict(version=sys.version.split()[0],unittest_available=True,'
          'sqlite_available=True,private_denied=bool(denials) and all(denials))))')
    probes=[str(Path(p).resolve(strict=True)) for p in private_probes]
    for name in plan.get('runtime_arms',('Bprime','C')):
        work=out/name;runtime=work/'.runtime'
        verify_runtime(runtime)
        if digest(runtime/'runtime-manifest.json')!=plan['runtime']['manifest_sha256']:
            raise ValueError('registered_runtime_changed')
        blocked=plan['blocked']+[str(out/p) for p in plan.get('workspace_names',('Bprime','C','C-selector')) if out/p!=work and (out/p).exists()]
        folder=private/(name+'-runtime-admission')
        reg=dict(workspace=str(work),executable=plan['executable'],executable_sha256=plan['executable_sha256'],**plan['model'])
        session=fresh(reg,folder,host_permissions=dict(profile=PROFILE,startup_flags=permission_flags(work,blocked)+runtime_startup_flags(plan)),
            startup_timeout=plan.get('startup_timeout_seconds',20))
        try:
            response=session.server.call('command/exec',dict(command=[str(runtime/'python.exe'),'-B','-c',code,str(canary),*probes],
                cwd=str(work),permissionProfile=PROFILE,timeoutMs=15000),timeout=25)
            (folder/'command-result.json').write_text(json.dumps(response,indent=2)+'\n',encoding='utf-8')
            if response.get('exitCode')!=0:raise ValueError('runtime_native_execution_failed:'+name)
            observed=json.loads(response['stdout'])
            if observed!=dict(version=plan['runtime']['version'],unittest_available=True,sqlite_available=True,private_denied=True):
                raise ValueError('runtime_native_boundary_failed:'+name)
            if material_inputs is not None:
                from native_rollout_snapshot import capture_rollout
                from native_evidence import state
                from .baseline_material import import_baseline
                session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=[dict(type='message',role='assistant',
                    content=[dict(type='output_text',text='{"record_type":"bench.bootstrap/1","id":"material-admission"}')])]))
                bootstrap=state(capture_rollout(session.opened['thread']['path']).rows)
                prefix=[] if name=='last-state-only' else material_inputs['prefix']
                proof=import_baseline(session,prefix,bootstrap,folder)
                if not proof['import_proof']['matched']:raise ValueError('native_material_preflight_failed')
                observed['material_transport_verified']=True
                observed['empty_history']=not bool(prefix)
            results[name]=observed
        finally:
            session.server.owner.close()
            cleanup=session.close()
            (folder/'runtime-cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n',encoding='utf-8')
    result=dict(qualified=True,arms=results,model_calls=0,scope='Same native command/exec profile; no model tool execution or compression quality claim.')
    with (private/'runtime-admission.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    return result
