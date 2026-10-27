"""Fixed-length native command, sealed manifest, streaming resource hashes."""
from pathlib import Path
from hashlib import sha256
import json
from native_evidence import save

SCRIPT="""const fs=require('node:fs'),crypto=require('node:crypto');
const raw=fs.readFileSync(process.argv[1]);
if(crypto.createHash('sha256').update(raw).digest('hex')!==process.argv[2])throw Error('manifest_changed');
const entries=JSON.parse(raw),buffer=Buffer.alloc(65536),failures=[];let bytes=0,count=0;
for(const e of entries){let fd;try{fd=fs.openSync(e.path,'r');if(!fs.fstatSync(fd).isFile())throw Error('not_regular');
const h=crypto.createHash('sha256');let n;while((n=fs.readSync(fd,buffer,0,buffer.length,null))>0){bytes+=n;h.update(buffer.subarray(0,n));}
if(h.digest('hex')!==e.sha256)throw Error('hash_mismatch');
}catch(x){count++;if(failures.length<8)failures.push({path:e.path,error:x.code||x.message});}finally{if(fd!==undefined)fs.closeSync(fd);}}
console.log(JSON.stringify({files:entries.length,bytes,failure_count:count,failures}));if(count)process.exitCode=2;"""


def verify_paths(session,entries,destination):
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    if len(entries)>100000:raise ValueError('resource_manifest_count_exhausted')
    raw=json.dumps(entries,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(raw)>16*1024*1024:raise ValueError('resource_manifest_bytes_exhausted')
    path=destination.with_suffix('.manifest.json')
    with path.open('xb') as stream:stream.write(raw)
    checksum=sha256(raw).hexdigest()
    command=[session.registration['node_executable'],'-e',SCRIPT,str(path.resolve()),checksum]
    # Escaping backslashes/quotes at worst doubles this short fixed command.
    if sum(len(value.encode('utf-16-le')) for value in command)>12000:raise ValueError('resource_probe_command_budget_exhausted')
    result=session.server.call('command/exec',dict(command=command,cwd=session.registration['workspace'],
        sandboxPolicy=dict(type='readOnly',networkAccess=False),timeoutMs=20000),timeout=30)
    save(destination,dict(result=result,manifest=str(path),manifest_sha256=checksum,manifest_bytes=len(raw)))
    if result.get('exitCode')!=0:raise ValueError('cold_resource_not_accessible')
    return result
