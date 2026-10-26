"""Opt-in private browser runtime and zero-inference execution admission."""
from pathlib import Path
import shutil

from native_evidence import read,save,file_hash,manifest


def materialize(work, spec):
    work=Path(work).resolve()
    binding_path=Path(spec['binding'])
    if file_hash(binding_path)!=spec['binding_sha256']:
        raise ValueError('application_browser_binding_changed')
    binding=read(binding_path)
    source=Path(binding['cache'])
    if manifest(source)!=binding['files']:
        raise ValueError('application_browser_runtime_changed')
    root=work/'.wsc-runtime'
    root.mkdir(exist_ok=False)
    cache=root/'browsers'
    shutil.copytree(source,cache)
    if manifest(cache)!=binding['files']:
        raise ValueError('application_browser_copy_changed')
    probe=root/'browser-capability.mjs'
    if file_hash(spec['probe'])!=spec['probe_sha256']:
        raise ValueError('application_browser_probe_changed')
    shutil.copyfile(spec['probe'],probe)
    return dict(browser_cache=str(cache),browser_probe=str(probe),browser_probe_sha256=spec['probe_sha256'])


def admit(session, destination):
    reg=session.registration
    if not reg.get('browser_cache') or reg.get('sandbox')=='read-only':
        return
    if file_hash(reg['browser_probe'])!=reg['browser_probe_sha256']:
        raise ValueError('application_browser_probe_changed')
    destination=Path(destination)
    destination.mkdir(exist_ok=False)
    work=Path(reg['workspace']).resolve()
    output=work/'.wsc-probes'/session.opened['thread']['id']
    command=[reg['node_executable'],reg['browser_probe'],str(work/'gui'),str(output),'default']
    execution=session.server.call('command/exec',dict(command=command,cwd=str(work),
        sandboxPolicy=dict(type='workspaceWrite',writableRoots=[str(work)],networkAccess=False),timeoutMs=35000),timeout=45)
    save(destination/'execution.json',execution)
    result=read(output/'result.json') if (output/'result.json').exists() else dict(passed=False,error='probe_did_not_write_result')
    save(destination/'result.json',result)
    if execution.get('exitCode')!=0 or result.get('passed') is not True:
        raise ValueError('application_browser_capability_unavailable')
