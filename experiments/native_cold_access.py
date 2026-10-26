"""Verify exact cold bytes through the receiver's native read-only execution."""
from pathlib import Path

from native_evidence import save


def _check(session, entries, destination):
    destination=Path(destination)
    destination.mkdir(exist_ok=False)
    unique={}
    for path,expected in entries:
        if path in unique and unique[path]!=expected:
            raise ValueError('cold_access_conflicting_digest')
        unique[path]=expected
    root=Path(session.registration['browser_cache']).parent/'cold-access'
    root.mkdir(exist_ok=True)
    request=root/(session.opened['thread']['id']+'-'+destination.name+'.json')
    save(request,[dict(path=path,sha256=value) for path,value in unique.items()])
    script=("const fs=require('node:fs'),crypto=require('node:crypto');"
        "const entries=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));let bytes=0;const bad=[];"
        "for(const e of entries){try{const b=fs.readFileSync(e.path);bytes+=b.length;"
        "if(crypto.createHash('sha256').update(b).digest('hex')!==e.sha256)bad.push({path:e.path,error:'digest_mismatch'});"
        "}catch(x){bad.push({path:e.path,error:String(x.code||x.message)});}}"
        "console.log(JSON.stringify({passed:bad.length===0,files:entries.length,bytes,bad,model_calls:0}));"
        "if(bad.length)process.exitCode=2;")
    result=session.server.call('command/exec',dict(command=[session.registration['node_executable'],'-e',script,str(request)],
        cwd=session.registration['workspace'],sandboxPolicy=dict(type='readOnly',networkAccess=False),timeoutMs=20000),timeout=30)
    save(destination/'execution.json',result)
    if result.get('exitCode')!=0:
        raise ValueError('native_cold_source_unavailable_or_changed')


def material(session, offered, destination, extra_entries=()):
    _check(session,[(event['cold_source']['path'],event['cold_source']['sha256']) for event in offered['events']]+list(extra_entries),destination)


def package(session, value, destination, extra_entries=()):
    entries=list(extra_entries)
    def collect(node):
        if isinstance(node,dict):
            if 'file_path' in node and 'sha256' in node:
                entries.append((node['file_path'],node['sha256']))
            if 'readable_path' in node and 'readable_sha256' in node:
                entries.append((node['readable_path'],node['readable_sha256']))
            for item in node.values():
                collect(item)
        elif isinstance(node,list):
            for item in node:
                collect(item)
    collect(value['evidence'])
    collect(value.get('excerpt_evidence',{}))
    collect(value.get('adapter',{}).get('projection_evidence',{}))
    for name in ('source_index','understanding_index'):
        entries.append((value[name],value[name+'_sha256']))
    _check(session,entries,destination)
