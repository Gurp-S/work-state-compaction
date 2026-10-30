/** Opt-in boundary only. No listener registration or default host changes. */
import { createDenoiseState } from '../../dsh-wsc/lib/denoise.js'
import { runtimeDenoiseView } from './runtime_denoise_view.mjs'
import { createHash } from 'node:crypto'

const digest = value => createHash('sha256').update(value).digest('hex')

/** classify must be supplied by an executing tool's trusted contract, not model args. */
export function createDshDenoiseBoundary({store, verifyOriginal, classify, observe=()=>{}}) {
  const states = new WeakMap(), tails = new WeakMap()
  const report = event => { try { observe(event) } catch {} }
  const commit = (session,state) => {
    // Eviction only keeps an old duplicate inline; it never removes raw evidence.
    while (state.seen.size > 128) state.seen.delete(state.seen.values().next().value)
    states.set(session,state)
  }
  async function process(exec, result, decision) {
    const bypass = reason => { report({status:'bypass',reason}); return decision }
    if (decision.kind !== 'accept' || result.isError !== false || Object.hasOwn(decision,'value')) return bypass('result_not_eligible')
    const session = exec.agent?.session
    if (!session || typeof session !== 'object' || typeof session.header?.id !== 'string') return bypass('session_missing')
    if (exec.name === 'read' || classify?.(exec,result) !== 'log') return bypass('source_recovery_or_unclassified')
    // Existing foreground shell result schema; infrastructure success is not process success.
    const v = result.value
    if (v?.kind !== 'foreground' || v.exitCode !== 0 || v.signal !== null ||
        v.timedOut !== false || v.aborted !== false || v.sandbox?.denied || v.sandbox?.runnerFailed ||
        v.stdout?.truncated !== false || v.stderr?.truncated !== false) return bypass('process_status_or_output_incomplete')
    const content = decision.content ?? result.content
    if (!Array.isArray(content) || content.length !== 1 || content[0].type !== 'text' || typeof content[0].text !== 'string') return bypass('mixed_or_unknown_content')
    const text = content[0].text
    if (text.length < 1200 || text.length > 50000) return bypass('size')
    if (!store || typeof verifyOriginal !== 'function') return bypass('storage_unavailable')
    const previous = states.get(session) ?? createDenoiseState()
    const state = {reads:new Map(previous.reads),seen:new Set(previous.seen)}
    const outcome = runtimeDenoiseView(text,{toolName:exec.name,callId:exec.callId,args:exec.arguments,
      state,resultClass:'log',exitCode:0})
    if (!outcome) { commit(session,state); return bypass('no_change') }
    const ref = await store.saveText({owner:{sessionId:session.header.id},
      source:{kind:'tool',toolName:exec.name,callId:exec.callId,label:'result'},
      suggestedName:exec.name+'.txt',content:text})
    if (typeof ref?.locator !== 'string' || /[\r\n]/.test(ref.locator) || !(await verifyOriginal(ref,text))) return bypass('raw_verification_failed')
    const rawHash=digest(text)
    const pointer='\n\n[denoise: '+outcome.rules.join(', ')+'; raw='+JSON.stringify(ref.locator)+
      '; bytes='+Buffer.byteLength(text)+'; sha256='+rawHash+']'
    const replacement=outcome.text+pointer
    if (Buffer.byteLength(replacement) >= Buffer.byteLength(text)) return bypass('pointer_exceeds_savings')
    commit(session,state)
    report({status:'replaced',callId:exec.callId,raw_sha256:rawHash,rules:outcome.rules,
      before_bytes:Buffer.byteLength(text),after_bytes:Buffer.byteLength(replacement),raw_locator:ref.locator})
    return {...decision,content:[{...content[0],text:replacement}]}
  }
  return async (exec,result,next) => {
    const decision = await next()
    const session=exec.agent?.session
    if (!session || typeof session !== 'object') return decision
    // Commit dedupe state only after verified storage, in session execution order.
    const previous=tails.get(session) ?? Promise.resolve()
    const current=previous.catch(()=>{}).then(async()=>{
      try { return await process(exec,result,decision) }
      catch { report({status:'bypass',reason:'boundary_failure'}); return decision }
    })
    tails.set(session,current)
    try { return await current }
    finally { if(tails.get(session)===current) tails.delete(session) }
  }
}
