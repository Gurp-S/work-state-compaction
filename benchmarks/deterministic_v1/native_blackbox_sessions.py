"""Fresh native receivers and silent read-only cold-access verification."""
from pathlib import Path
import json
from native_study_fork_session import NativeForkSession
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings
from native_evidence import save,file_hash,state,digest,import_evidence
from native_host_controls import bootstrap_items
from native_rollout_snapshot import capture_rollout,parse_rollout


def fresh(reg,destination,*,dynamic_tools=(),selector_runtime=None):
    if file_hash(reg['executable'])!=reg['executable_sha256']:raise ValueError('registered_cli_changed')
    session=NativeForkSession(reg,destination)
    extra=[]
    if selector_runtime is not None:
        from native_selector_runtime import configure
        extra=configure(Path(destination)/'selector-runtime',selector_runtime)
        save(Path(destination)/'selector-runtime-registration.json',dict(profile=selector_runtime,settings=extra,
            scope='Private C selector only; native control and continuation actor unchanged.'))
    session.server=OwnedNativeRPC(reg['executable'],cwd=reg['workspace'],stderr_path=Path(destination)/'stderr.txt',settings=settings(reg)+extra)
    try:
        save(Path(destination)/'initialized.json',session.server.call('initialize',dict(clientInfo=dict(name='blackbox_receiver',version='1'),capabilities=dict(experimentalApi=True))))
        session.server.send(dict(method='initialized'))
        session.opened=session.server.call('thread/start',dict(cwd=reg['workspace'],model=reg['model'],
            allowProviderModelFallback=False,approvalPolicy='never',sandbox='read-only',
            runtimeWorkspaceRoots=[reg['workspace']],ephemeral=False,dynamicTools=list(dynamic_tools)))
        save(Path(destination)/'opened.json',session.opened)
        if session.opened['model']!=reg['model'] or session.opened['reasoningEffort']!=reg['effort']:
            raise ValueError('receiver_model_or_effort_changed')
        snapshot=capture_rollout(session.opened['thread']['path'])
        if snapshot.metadata['exists'] and (not snapshot.metadata['parse_complete'] or any(r['type']=='token_usage_record' for r in snapshot.rows)):
            raise ValueError('fresh_receiver_inference_or_source_unknown')
        save(Path(destination)/'history-readiness.json',dict(physical_history_exists=snapshot.metadata['exists'],
            import_required_before_execution=True,phase='configured_not_yet_import_verified'))
        return session
    except BaseException:
        session.close();raise


def verify_material(actual,bootstrap,items,*,workspace='__unregistered_workspace__'):
    boundary=len(bootstrap)
    if len(actual)!=boundary+len(items) or bootstrap_items(actual[:boundary],workspace)!=bootstrap_items(bootstrap,workspace):
        raise ValueError('fresh_receiver_import_or_bootstrap_changed')
    imported=import_evidence(actual[boundary:],items)
    if not imported['matched'] or imported['start_ordinal']!=0:
        raise ValueError('fresh_receiver_import_or_bootstrap_changed')
    return dict(bootstrap_equal=True,raw_history_not_inherited=True,material_sha256=digest(actual),
                imported_items_sha256=digest(items),import_proof=imported,
                bootstrap_comparison='Existing native_host_controls normalization: transport IDs/metadata only; tool schemas and text unchanged.',
                scope='Effective native wire items after first import with enumerated native transport additions.')


def import_fresh(session,items,bootstrap,destination):
    path=Path(session.opened['thread']['path'])
    before=path.read_bytes() if path.exists() else b''
    response=session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=items))
    snapshot=capture_rollout(path,archive=Path(destination)/'after-import.jsonl')
    if not snapshot.metadata['parse_complete'] or any(r['type']=='token_usage_record' for r in snapshot.rows):
        raise ValueError('fresh_import_unknown_or_inference_observed')
    if not path.read_bytes().startswith(before):raise ValueError('fresh_import_source_prefix_changed')
    proof=verify_material(state(snapshot.rows),bootstrap,items,workspace=session.registration['workspace'])
    save(Path(destination)/'native-import.json',dict(response=response,proof=proof))
    return proof


def verify_paths(session,entries,destination):
    script=("const fs=require('node:fs'),crypto=require('node:crypto');"
        "let bytes=0;const failures=[];for(const e of JSON.parse(process.argv[1])){"
        "try{const b=fs.readFileSync(e.path);bytes+=b.length;"
        "if(crypto.createHash('sha256').update(b).digest('hex')!==e.sha256)failures.push(e.path);"
        "}catch(x){failures.push(e.path+':'+x.code);}}"
        "console.log(JSON.stringify({files:JSON.parse(process.argv[1]).length,bytes,failures}));"
        "if(failures.length)process.exitCode=2;")
    result=session.server.call('command/exec',dict(command=[session.registration['node_executable'],'-e',script,json.dumps(entries)],
        cwd=session.registration['workspace'],sandboxPolicy=dict(type='readOnly',networkAccess=False),timeoutMs=20000),timeout=30)
    save(destination,result)
    if result.get('exitCode')!=0:raise ValueError('cold_resource_not_accessible')
    return result
