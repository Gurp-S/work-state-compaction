/** Callback-scoped qualification: real WSC listener + installed spill implementation.
 * Framework/LLM imports are stubs. No live app, model request or task-quality claim.
 */
import { registerHooks } from 'node:module'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { pathToFileURL } from 'node:url'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createDshDenoiseBoundary } from '../experiments/dsh_runtime_denoise_boundary.mjs'

const output = resolve(process.argv[2] ?? 'D:/agent-task-runs/wsc-dsh-denoise-qualification-20261029-v1')
const stub = code => 'data:text/javascript,'+encodeURIComponent(code)
const modules = {
  '@deepseek-ai/dsh-compaction-basic': 'export class BasicCompactionEngine { constructor(ctx,config){this.ctx=ctx;this.config=config} }',
  '@deepseek-ai/dsh-compaction': 'export const toolPairingBalancedBefore=()=>true; export const isCompactCheckpointSource=()=>false;',
  '@deepseek-ai/dsh-llm': 'export class BlockAssembler{}; export const createUserMessage=x=>x;',
  '@deepseek-ai/schemastery': 'const z=new Proxy(function(){},{get:()=>z,apply:()=>z});export default z;',
  '@deepseek-ai/dsh-spill': 'export class SpillStore{constructor(ctx){this.ctx=ctx}};export const SpillLocator=x=>x;',
}
const hooks = registerHooks({resolve(specifier,ctx,next){
  return modules[specifier] ? {url:stub(modules[specifier]),shortCircuit:true} : next(specifier,ctx)
}})
const {default:Engine} = await import('../../dsh-wsc/engine.js')
const spillPath = join(output,'source/dsh-spill-local/lib/index.js')
const {LocalSpillStore} = await import(pathToFileURL(spillPath).href)
const saved = []
const store = new LocalSpillStore({effect(){}}, {root:join(output,'spill'),cleanupPeriodDays:0})
const spill = {async saveText(input){const ref=await store.saveText(input); saved.push({input,ref});return ref}}
function fixture(backend=spill) {
  const handlers=new Map(),warnings=[]
  const ctx={on(name,fn){handlers.set(name,fn)},get(name){return name==='wscConfig'?{value:{denoise:true}}:name==='spillStore'?backend:undefined},logger:{warn(message){warnings.push(message)}}}
  new Engine(ctx)
  const agent={session:{header:{id:'denoise-callback-fixture'}}}
  return {warnings, async call(name,text,args={},value={}){
    const result={isError:false,value,content:[{type:'text',text}]}
    const decision={kind:'accept'}
    const actual=await handlers.get('tools/post-execute')({name,callId:'call-'+saved.length,arguments:args,agent},result,async()=>decision)
    return {actual,result,decision}
  }}
}
const checks=[]
const record=(name,evidence)=>checks.push({name,...evidence})
const f=fixture()
const log=('test_record ... ok\r\n').repeat(100)
const crlf=await f.call('pwsh',log,{command:'fixture'}, {kind:'foreground',exitCode:0})
assert.notEqual(crlf.actual,crlf.decision)
assert.equal(saved[0].input.content,log)
assert.equal(await readFile(saved[0].ref.locator,'utf8'),log)
record('original_crlf_loss_reproduced_raw_retrievable',{rewritten:true,view:crlf.actual.content[0].text.split('\n')[0],raw_bytes:Buffer.byteLength(log)})

const diff='diff --git a/a.py b/a.py\n'+('-old\n+new\n').repeat(200)+'[exit code: 1]'
const failed=await f.call('pwsh',diff,{command:'fixture'}, {kind:'foreground',exitCode:1})
assert.notEqual(failed.actual,failed.decision)
assert.equal(failed.result.value.exitCode,1)
assert.equal(saved.at(-1).input.content,diff)
record('nonzero_exit_with_isError_false_rewritten',{rewritten:true,structured_exit_code:1,rules_view:failed.actual.content[0].text.split('\n')[0]})

const locator=saved[0].ref.locator
const read1=await f.call('read',log,{path:locator})
const read2=await f.call('read',log,{path:locator})
assert.equal(read1.actual,read1.decision)
assert.notEqual(read2.actual,read2.decision)
assert.equal(await readFile(locator,'utf8'),log)
record('original_recovery_read_repeated_is_folded',{first_raw:true,second_rewritten:true,raw_file_unchanged:true})

// Explicit storage rejection instead of a default-argument fallback.
const broken=fixture({async saveText(){throw Error('fixture disk failure')}})
const failure=await broken.call('pwsh',log)
assert.equal(failure.actual,failure.decision)
record('storage_failure_keeps_raw',{unchanged:true})
const engineRaw=await readFile(new URL('../../dsh-wsc/engine.js',import.meta.url))
const result={scope:'actual WSC listener with installed spill storage, framework stubbed; no live DSH/model',
  model_calls:0,checks,engine_sha256:createHash('sha256').update(engineRaw).digest('hex'),
  spill_source_sha256:createHash('sha256').update(await readFile(spillPath)).digest('hex'),
  raw_file_retrieval_verified:true,model_recovery_verified:false,safe_runtime_qualified:false}
if (process.argv.includes('--sidecar')) {
  const observations=[]
  const boundary=createDshDenoiseBoundary({store:spill,
    verifyOriginal:async(ref,text)=>(await readFile(ref.locator,'utf8'))===text,
    classify:exec=>exec.trustedOutputClass,observe:event=>observations.push(event)})
  const session={header:{id:'safe-sidecar-fixture'}}
  const exec={name:'pwsh',callId:'safe-call',arguments:{command:'fixture'},agent:{session},trustedOutputClass:'log'}
  const value={kind:'foreground',exitCode:0,signal:null,timedOut:false,aborted:false,
    stdout:{truncated:false},stderr:{truncated:false}}
  const res={isError:false,value,content:[{type:'text',text:log}]}
  const accept={kind:'accept',opaque:'preserved'}
  const invoke=(e=exec,r=res,d=accept)=>boundary(e,r,async()=>d)
  const changed=await invoke()
  assert.notEqual(changed,accept)
  assert.equal(changed.opaque,'preserved')
  assert.equal(res.value,value)
  assert.equal(res.content[0].text,log)
  assert.equal(changed.content[0].text.split('\n')[0],'test_record ... ok  ×100')
  const latest=saved.at(-1)
  assert.equal(await readFile(latest.ref.locator,'utf8'),log)
  for (const e of [{...exec,name:'read'},{...exec,trustedOutputClass:undefined},{...exec,trustedOutputClass:'source'},{...exec,trustedOutputClass:'recovery'}]) {
    assert.equal(await invoke(e),accept)
    assert.equal(await invoke(e),accept)
  }
  for(const changes of [{exitCode:1},{signal:'SIGTERM'},{timedOut:true},{aborted:true},
      {stdout:{truncated:true}},{sandbox:{denied:true}},{kind:'background'}]) {
    assert.equal(await invoke(exec,{...res,value:{...value,...changes}}),accept)
  }
  assert.equal(await invoke(exec,{...res,isError:true}),accept)
  assert.equal(await invoke(exec,{...res,content:[...res.content,{type:'image',data:'fixture'}]}),accept)
  const conflict={...accept,value:{other:'result'}}
  assert.equal(await invoke(exec,res,conflict),conflict)
  const brokenBoundary=createDshDenoiseBoundary({store:{saveText(){throw Error('disk')}},
    verifyOriginal:async()=>true,classify:()=> 'log'})
  assert.equal(await brokenBoundary(exec,res,async()=>accept),accept)
  let verified=false
  const transactionalEvents=[]
  const transaction=createDshDenoiseBoundary({store:spill,verifyOriginal:async()=>verified,
    classify:()=> 'log',observe:event=>transactionalEvents.push(event)})
  assert.equal(await transaction(exec,res,async()=>accept),accept)
  verified=true
  const recovered=await transaction(exec,res,async()=>accept)
  assert.notEqual(recovered,accept)
  assert.deepEqual(transactionalEvents.at(-1).rules,['collapse_stack'])
  const cacheEvents=[]
  const cacheBoundary=createDshDenoiseBoundary({store:{async saveText(){return {locator:'fixture-cache'}}},
    verifyOriginal:async()=>true,classify:()=> 'log',observe:event=>cacheEvents.push(event)})
  for(let i=0;i<129;i++) await cacheBoundary(exec,{...res,content:[{type:'text',text:('record '+i+'\n').repeat(200)}]},async()=>accept)
  await cacheBoundary(exec,{...res,content:[{type:'text',text:('record 0\n').repeat(200)}]},async()=>accept)
  assert.deepEqual(cacheEvents.at(-1).rules,['collapse_stack'])
  result.sidecar={checks_passed:true,source_and_recovery_always_raw:true,
    explicit_process_status_required:true,failed_persistence_does_not_commit_dedupe:true,
    pointer_included_in_bytes:true,cache_eviction_retains_original_content:true,observations,
    first_before_bytes:Buffer.byteLength(log),first_after_bytes:Buffer.byteLength(changed.content[0].text),
    live_host_enabled:false,real_task_quality_verified:false,actual_token_savings:null,
    crash_durability_verified:false,classification_from_real_host_verified:false,
    boundary_sha256:createHash('sha256').update(await readFile(new URL('../experiments/dsh_runtime_denoise_boundary.mjs',import.meta.url))).digest('hex')}
}
const receiptAt=process.argv.indexOf('--receipt')
const receipt=receiptAt===-1?(process.argv.includes('--sidecar')?'callback-sidecar-qualification.json':'callback-qualification.json'):process.argv[receiptAt+1]
assert.equal(receipt,receipt.split(/[\\/]/).at(-1))
await writeFile(join(output,receipt),JSON.stringify(result,null,2)+'\n',{flag:'wx'})
hooks.deregister()
console.log(JSON.stringify(result))
