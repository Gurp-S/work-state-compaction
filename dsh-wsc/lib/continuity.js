/** A bounded view reconstructed from original events at the session cursor. */
import { byteLength } from './bytes.js'
import { messageText } from './projection.js'
import { runtimeObservations } from './verification.js'
import { indexToolReceipts, toolReceiptLinks } from './continuity-links.js'
import { readCheckpointState } from './checkpoint-state.js'
import { controlledReads } from './state-selection-context.js'
import { originalReceiptEvents } from './receipt-history.js'
import { sessionEvents } from './session.js'

const FILE_LIMIT = 8
const COMMAND_LIMIT = 12
/** Pure directory listings are discovery, not handoff state. */
const LISTING_COMMAND = /^\s*(?:Get-ChildItem|gci|dir|ls|find|fd)\b/i
/** Commands that only inspect a path; the later model can re-run them. */
const normalizeCommand = (command) => command.split(/\r?\n/, 1)[0].trim()
const CONTROL = '## User requests and instructions (verbatim, control)'
const STATE = '## Current state (model account; unverified)'
const RUNTIME = '## Runtime receipts (session event sequences)'
const REBUILT_HEADINGS = new Set([CONTROL, RUNTIME])

export function withoutRebuiltSections(text) {
  let rebuilt = false
  return text.split('\n').filter(line => {
    if (line.startsWith('## ')) rebuilt = REBUILT_HEADINGS.has(line.trimEnd())
    return !rebuilt
  }).join('\n').trim()
}
const isControl = message => message.role === 'developer' ||
  (message.role === 'user' && message.source?.kind === 'user')

function controlTexts(input, events, derive, isCheckpointSource) {
  const bySeq = new Map(events.map(event => [event.seq, event]))
  const checkpoints = new Map(events.filter(event => event.type === 'compaction/summary')
    .map(event => [event.data.compactionId, event]))
  const seen = new Set()
  const controls = []
  const stack = [...input.messages].reverse().map(message => ({ message }))
  while (stack.length > 0) {
    const { message, seq } = stack.pop()
    if (seq !== undefined) {
      if (seen.has(seq)) continue
      seen.add(seq)
    }
    if (!message) continue
    if (isCheckpointSource(message.source)) {
      const parent = checkpoints.get(message.source.compactionId)
      if (!parent) throw new Error('wsc: continuity_control_source_unavailable')
      if (seq !== undefined && parent.seq > seq) throw new Error('wsc: continuity_control_source_invalid')
      for (const sourceSeq of [...parent.data.shadowedSeqs].reverse()) {
        const event = bySeq.get(sourceSeq)
        if (!event || sourceSeq >= parent.seq) throw new Error('wsc: continuity_control_source_invalid')
        const sourceMessage = derive(event)
        if (!sourceMessage && ['user/message', 'developer/message'].includes(event.type)) {
          throw new Error('wsc: continuity_control_source_unavailable')
        }
        stack.push({ seq: sourceSeq, message: sourceMessage })
      }
    } else if (isControl(message)) {
      const text = messageText(message).trim()
      if (text) controls.push(text)
    }
  }
  return controls
}

function priorState(input, isCheckpointSource) {
  for (const message of [...(input.messages ?? [])].reverse()) {
    if (!isCheckpointSource(message.source)) continue
    const text = messageText(message)
    const structured = readCheckpointState(text)
    if (structured) return structured
    const at = text.indexOf(`${STATE}\n`)
    if (at === -1) return ''
    const body = []
    for (const line of text.slice(at + STATE.length + 1).split('\n')) {
      if (line.startsWith('## ')) break
      body.push(line)
    }
    const value = body.join('\n').trim()
    return value
  }
  return ''
}

export function prepareContinuity(input, session, isCheckpointSource, options = {}) {
  const events = [...sessionEvents(session)]
  const derive = event => session.deriveEventMessage(event)
  const original = originalReceiptEvents(events, derive)
  const controls = controlTexts(input, events, derive, isCheckpointSource)

  const files = new Map()
  const commands = new Map()
  const throughSeq = events.at(-1)?.seq ?? 0
  const observations = runtimeObservations(original.map(row => row.message))
  const pairs = indexToolReceipts(original, observations)
  for (const call of observations) {
    const path = call.args?.path ?? call.args?.file_path ?? call.args?.target_file ?? call.args?.notebook_path
    const pair = pairs.get(call.id)
    const receipt = pair ? `, receipt #${pair.receipt.seq}` : ''
    const status = !pair ? 'unknown' : call.status === 'passed' ? 'completed' : call.status
    const outcome = `call #${original[call.index].seq}${receipt}: ${status}`
    const scope = typeof call.args?.workdir === 'string'
      ? `; workdir: ${JSON.stringify(call.args.workdir)}` : '; workdir: unknown'
    if ((call.name === 'write' || call.name === 'edit') && typeof path === 'string') {
      const key = JSON.stringify([call.args.workdir, path])
      files.delete(key)
      files.set(key, `${call.name} ${JSON.stringify(path)} (${outcome}${scope})`)
    }
    if (call.name === 'pwsh' || call.name === 'bash') {
      const command = call.args?.command ?? call.args?.cmd
      if (typeof command !== 'string' || !command) continue
      // A listing only says which files exist. It is cheap to repeat and it is
      // not evidence a later model can act on, so it must not displace a test,
      // a write or a failed command in the bounded receipt section.
      if (LISTING_COMMAND.test(command)) continue
      const firstLine = normalizeCommand(command)
      const excerpt = firstLine.slice(0, 80)
      // Display the first line, while retaining identity of the full script.
      const key = JSON.stringify([call.name, call.args?.workdir, command])
      commands.delete(key)
      commands.set(key, `${call.name} ${JSON.stringify(excerpt)}${excerpt !== command ? ' (excerpt)' : ''} (${outcome}${scope}); file coverage: unknown`)
    }
  }
  const facts = [
    `Through event #${throughSeq}. Latest recorded write/edit attempt per path and latest attempt per command.`,
    ...[...files.values()].slice(-FILE_LIMIT),
    ...[...commands.values()].slice(-COMMAND_LIMIT),
    ...(options.includeControlledReads ? controlledReads(observations, pairs, controls) : []),
  ]
  if (files.size > FILE_LIMIT || commands.size > COMMAND_LIMIT) {
    facts.push(`Earlier rows omitted: ${Math.max(0, files.size - FILE_LIMIT)} file actions, ${Math.max(0, commands.size - COMMAND_LIMIT)} commands.`)
  }
  const block = (heading, items) => items.length
    ? `${heading}\n${items.map(item => `- ${item.replace(/\r?\n/g, '\n  ')}`).join('\n')}` : ''
  const control = block(CONTROL, controls)
  const runtime = block(RUNTIME, facts)
  const receiptLinks = toolReceiptLinks(input.messages, pairs)
  const state = priorState(input, isCheckpointSource)
  return { throughSeq, control, runtime, state, receiptLinks, bytes: byteLength(runtime) + 2 +
    (control ? byteLength(control) + 2 : 0) }
}

export function fitRuntimeReceipts(runtime, allowance) {
  if (byteLength(runtime) <= allowance) return runtime
  const [heading, ...rows] = runtime.split(/\n(?=- )/)
  const omitted = '- Runtime rows omitted due to checkpoint budget.'
  if (byteLength(heading) + byteLength(omitted) + 1 > allowance) return ''
  const kept = [heading]
  let remaining = allowance - byteLength(heading) - byteLength(omitted) - 1
  // Recovery handles for files explicitly named in the active controls are
  // particularly useful when the selector could not produce a checkpoint.
  const ordered = [...rows.filter(row => row.startsWith('- read ')),
    ...rows.filter(row => !row.startsWith('- read '))]
  for (const row of ordered) {
    const cost = byteLength(row) + 1
    if (cost > remaining) continue
    kept.push(row)
    remaining -= cost
  }
  return kept.length > 1 ? [...kept, omitted].join('\n') : ''
}
