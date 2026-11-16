/** Completed process facts; command text alone never proves file coverage. */
import { toolResultOf } from './projection.js'

const parse = value => {
  if (value && typeof value === 'object') return value
  try { return JSON.parse(value) } catch { return {} }
}
const pathOf = args => args?.path ?? args?.file_path ?? args?.target_file ?? args?.notebook_path
const clip = text => String(text).split('\n')[0].slice(0, 80)

function outcome(call, result) {
  if (result === undefined || result.index <= call.index) return 'unknown'
  if (result.isError) return 'failed'
  if (call.name !== 'bash' && call.name !== 'pwsh') return 'passed'
  if (call.args?.run_in_background === true) return 'unknown'
  const text = result.text.trimEnd()
  if (/(?:^|\n)\[(?:timed out after|killed by signal:)/.test(text)) return 'interrupted'
  const exit = /(?:^|\n)\[exit code: (-?\d+|null)\]\s*$/.exec(text)
  if (exit !== null) return exit[1] === '0' ? 'passed' : exit[1] === 'null' ? 'unknown' : 'failed'
  // DSH's completed foreground renderer omits the marker for a clean exit.
  return 'passed'
}

export function runtimeObservations(messages) {
  const calls = []
  const invocationCounts = new Map()
  const completions = new Map()
  messages.forEach((message, index) => {
    if (message.role === 'assistant') {
      for (const block of message.content ?? []) {
        if (block.type !== 'tool-call') continue
        calls.push({...block, args: parse(block.arguments), index})
        invocationCounts.set(block.id, (invocationCounts.get(block.id) ?? 0) + 1)
      }
    } else {
      const result = toolResultOf(message)
      if (result !== undefined) {
        completions.set(result.callId, completions.has(result.callId) ? undefined : {...result, index})
      }
    }
  })
  return calls.map(call => {
    const result = typeof call.id === 'string' && call.id && invocationCounts.get(call.id) === 1
      ? completions.get(call.id) : undefined
    return { ...call, status: outcome(call, result),
      completedAt: result?.index > call.index ? result.index : undefined }
  })
}

export function verificationFacts(messages, limit = 8) {
  const edits = new Map()
  const checks = []
  for (const call of runtimeObservations(messages)) {
    const { status } = call
    const path = pathOf(call.args)
    if ((call.name === 'write' || call.name === 'edit') && path !== undefined && status !== 'failed') {
      edits.set(path, call)
    }
    // Shell text is not a typed test report. Record the observed command,
    // including node --test and arbitrary verification scripts, without
    // guessing from command names whether it verified a particular file.
    if (call.name === 'bash' || call.name === 'pwsh') {
      checks.push({...call, status, command: clip(call.args.command ?? call.args.cmd ?? '')})
    }
  }
  return [...edits.entries()].slice(-limit).map(([path, edit]) => {
    if (edit.status === 'unknown') return `${path}: ${edit.name} requested at #${edit.index}; outcome: unknown; file coverage: unknown`
    const latest = checks.filter(check => check.index > edit.completedAt).at(-1)
    const tail = latest === undefined ? 'no command observed after that change'
      : `latest command \`${latest.command}\` at #${latest.index} → ${latest.status === 'passed' ? 'completed' : latest.status}`
    return `${path}: last ${edit.name} at #${edit.index}; ${tail}; file coverage: unknown`
  })
}
