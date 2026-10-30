/** Export only structurally verified shell envelopes; no model calls. */
import { readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { shellEnvelope } from './audit_runtime_denoise.mjs'

const [auditPath,out] = process.argv.slice(2)
if (!auditPath || !out) throw Error('Usage: node export_recorded_shell_receipts.mjs audit.json output.json')
const sha = value => createHash('sha256').update(value).digest('hex')
const audit = JSON.parse(readFileSync(auditPath,'utf8'))
const receipts=[]
for(const c of audit.cases) {
  const raw=readFileSync(c.path)
  if(sha(raw)!==c.sha256) throw Error('rollout_changed')
  const outputs=new Map(raw.toString('utf8').trim().split('\n').map(JSON.parse)
    .filter(r=>r.type==='response_item' && ['custom_tool_call_output','function_call_output'].includes(r.payload?.type))
    .map(r=>[r.payload.call_id,r.payload.output]))
  for(const e of c.entries) {
    if(!Object.hasOwn(e,'exit_code')) continue
    const blocks=outputs.get(e.call_id)
    const text=blocks?.[e.block]?.text
    if(typeof text!=='string' || sha(text)!==e.sha256) throw Error('block_changed')
    const envelope=shellEnvelope(text)
    if(!envelope || envelope.exit_code!==e.exit_code) throw Error('envelope_changed')
    receipts.push({rollout:c.path,rollout_sha256:c.sha256,call_id:e.call_id,block:e.block,
      envelope_sha256:e.sha256,exit_code:envelope.exit_code,
      output:envelope.output,output_sha256:sha(envelope.output)})
  }
}
writeFileSync(out,JSON.stringify({kind:'observed_shell_output_export',new_model_calls:0,receipts},null,2)+'\n',{flag:'wx'})
console.log(JSON.stringify({receipts:receipts.length,new_model_calls:0}))
