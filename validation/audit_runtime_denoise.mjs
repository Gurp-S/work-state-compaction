/** Offline eligibility audit; never modifies rollouts or claims request-token savings. */
import { readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { runtimeDenoise, createDenoiseState } from '../../dsh-wsc/lib/denoise.js'

const sha = value => createHash('sha256').update(value).digest('hex')
const bytes = value => Buffer.byteLength(value, 'utf8')

// Structural envelope recognition is not semantic classification of shell content.
export function shellEnvelope(text) {
  let value
  try { value = JSON.parse(text) } catch { return null }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  // Observed Promise.allSettled presentation wrappers; do not recursively parse source strings.
  if (Number.isInteger(value.part) && value.status === 'fulfilled') value = value.value
  else if ((Number.isInteger(value.index) || Number.isInteger(value.i)) && value.result?.status === 'fulfilled') value = value.result.value
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  if (typeof value.output !== 'string' || !Number.isInteger(value.exit_code)) return null
  if (typeof value.chunk_id !== 'string' || typeof value.wall_time_seconds !== 'number') return null
  return value
}

export function auditRollout(path) {
  const raw = readFileSync(path)
  const rows = raw.toString('utf8').trim().split('\n').map(JSON.parse)
  const state = createDenoiseState()
  const normalizedState = createDenoiseState()
  const entries = []
  for (const row of rows) {
    const p = row.payload
    if (row.type !== 'response_item' || !['function_call_output', 'custom_tool_call_output'].includes(p?.type)) continue
    const blocks = typeof p.output === 'string' ? [{text: p.output}] : p.output
    if (!Array.isArray(blocks)) continue
    for (const [index, block] of blocks.entries()) {
      if (typeof block.text !== 'string') continue
      const envelope = shellEnvelope(block.text)
      const entry = {call_id:p.call_id, block:index, sha256:sha(block.text), bytes:bytes(block.text)}
      if (!envelope) { entries.push({...entry, status:'untyped_or_other_tool_bypass'}); continue }
      entry.output_bytes = bytes(envelope.output)
      entry.exit_code = envelope.exit_code
      if (envelope.exit_code !== 0) { entries.push({...entry, status:'error_bypass'}); continue }
      // These are the actual DSH runtime size gates (JS UTF-16 lengths).
      if (envelope.output.length < 1200 || envelope.output.length > 50000) {
        entries.push({...entry, status:'size_bypass'}); continue
      }
      const outcome = runtimeDenoise(envelope.output, {
        toolName:'exec_command', callId:p.call_id, args:{}, state,
      })
      const normalized = envelope.output.replace(/\r\n/g, '\n')
      const normalizedOutcome = runtimeDenoise(normalized, {
        toolName:'exec_command', callId:p.call_id, args:{}, state:normalizedState,
      })
      entries.push({...entry, status:outcome ? 'hypothetical_change_unqualified' : 'unchanged',
        rules:outcome?.rules ?? [], hypothetical_view_bytes:bytes(outcome?.text ?? envelope.output),
        normalized_rules:normalizedOutcome?.rules ?? [],
        hypothetical_normalized_view_bytes:bytes(normalizedOutcome?.text ?? envelope.output),
        safe_semantic_classification:false})
    }
  }
  return {path, sha256:sha(raw), entries}
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const [out, ...inputs] = process.argv.slice(2)
  if (!out || !inputs.length) throw Error('Usage: node audit_runtime_denoise.mjs output.json rollout.jsonl ...')
  const cases = inputs.map(auditRollout)
  const all = cases.flatMap(c => c.entries)
  const changed = all.filter(e => e.status === 'hypothetical_change_unqualified')
  const result = {kind:'offline_real_output_eligibility_audit', new_model_calls:0,
    denoiser_sha256:sha(readFileSync(new URL('../../dsh-wsc/lib/denoise.js', import.meta.url))),
    runtime_hook_qualified:false, raw_recovery_qualified:false, actual_token_savings:null,
    pointer_and_recovery_cost_included:false, semantic_quality_verified:false,
    blocks:all.length, hypothetical_changed_blocks:changed.length,
    hypothetical_output_bytes_before:changed.reduce((a,e)=>a+e.output_bytes,0),
    hypothetical_output_bytes_after:changed.reduce((a,e)=>a+e.hypothetical_view_bytes,0),
    cases}
  writeFileSync(out, JSON.stringify(result,null,2)+'\n', {flag:'wx'})
  console.log(JSON.stringify({...result, cases:cases.map(c=>({path:c.path,sha256:c.sha256,blocks:c.entries.length}))}))
}
