/**
 * Discovery index over a shadowed region, ported from
 * `benchmarks/coding_compaction_v1/live.py::index_from_events`.
 *
 * The bytes stay in the session; this index only names each source with a
 * mechanical label and its identifying terms, so a later model can decide what
 * is worth fetching. Every kind present keeps one slot before quotas fill.
 */
import { messageText, toolResultOf } from './projection.js'
import {
  TEST_COMMAND, VALUE_SIGNAL, envelopePathOf, firstLine, isEnvironmentalPath, isOutsideWorkspace,
  looksLikeError, relativePath, stripDenoisePointer, termsOf,
} from './values.js'

const CAPS = { error: 4, test: 4, edit: 5, value: 16, read: 2, cmd: 3, note: 6, output: 5 }
const KIND_ORDER = ['error', 'test', 'value', 'edit', 'note', 'output', 'cmd', 'read']

const parseArgs = (value) => {
  if (value !== null && typeof value === 'object') return value
  try { return JSON.parse(value) } catch { return {} }
}
const pathOf = (args) => ['path', 'file_path', 'target_file', 'notebook_path']
  .map((key) => args?.[key])
  .find((value) => typeof value === 'string' && value !== '') ?? ''
const commandOf = (args) => {
  const value = args?.command ?? args?.cmd
  return typeof value === 'string' ? value : ''
}

const cleanLabel = (text) => firstLine(text).replace(/^\d+:\s*/, '').slice(0, 72)

// A read's bytes live in its result, so the call row cites the paired seq.
// Its own generic result row would only repeat the envelope path.
const READ_LIKE = new Set(['read', 'write', 'edit'])

/**
 * The region as an ordered event list: every tool call, tool result and
 * message, with the message position a label can cite.
 *
 * @param {ReadonlyArray<{ seq: number, message: object }>} rows
 * @returns {Array<object>}
 */
function eventsOf(rows) {
  const events = []
  rows.forEach((row, index) => {
    const position = index + 1
    const message = row.message
    const blocks = Array.isArray(message?.content) ? message.content : []
    const calls = blocks.filter((block) => block?.type === 'tool-call')
    for (const block of calls) {
      events.push({
        kind: 'call', position, seq: row.seq, callId: block.id,
        name: String(block.name ?? ''), args: parseArgs(block.arguments), text: '',
      })
    }
    const result = toolResultOf(message)
    if (result !== undefined) {
      events.push({
        kind: 'result', position, seq: row.seq, callId: result.callId,
        role: message.role, isError: result.isError, text: String(result.text ?? '').trim(),
      })
      return
    }
    if (calls.length > 0) return
    const text = messageText(message, { toolText: true }).trim()
    if (text === '') return
    events.push({ kind: 'message', position, seq: row.seq, role: message.role, text })
  })
  return events
}

/** Number of sources the index and the value ledger have to cover. */
export function indexSourceCount(rows) {
  return eventsOf(rows)
    .filter((event) => event.text !== '' && !(event.kind === 'message' && event.role === 'user'))
    .length
}

/**
 * Build the discovery rows.
 *
 * @param {ReadonlyArray<{ seq: number, message: object }>} rows region rows.
 * @param {{ limit?: number }} [options]
 * @returns {Array<object>} at most `limit` rows, sorted by rank then position.
 */
export function historyIndex(rows, options = {}) {
  const limit = Math.max(1, options.limit ?? 20)
  const events = eventsOf(rows)
  const calls = new Map()
  const results = new Map()
  for (const event of events) {
    if (event.kind === 'call' && typeof event.callId === 'string') calls.set(event.callId, event)
    if (event.kind === 'result' && typeof event.callId === 'string') results.set(event.callId, event)
  }
  const candidates = []
  for (const event of events) {
    if (event.kind === 'call') {
      const name = event.name
      const rawPath = pathOf(event.args)
      if (isOutsideWorkspace(rawPath)) continue
      const path = relativePath(rawPath)
      if ((name === 'edit' || name === 'write') && path !== '') {
        const changed = ['old_string', 'new_string']
          .map((key) => event.args?.[key])
          .filter((value) => typeof value === 'string')
          .join(' ')
        const terms = termsOf(changed)
        candidates.push({
          position: event.position, seq: event.seq, tool: 'read_history',
          label: `edit ${path}`, rank: 2, kind: 'edit',
          terms: terms.length > 0 ? terms : termsOf(path), text: changed,
        })
        continue
      }
      if (name === 'read' || name === 'write' || name === 'edit') {
        const target = relativePath(pathOf(event.args))
        // The call names the path; the result holds the file bytes, so the
        // fetch has to resolve to the result event or the read returns only
        // the arguments.
        const paired = results.get(event.callId)
        candidates.push({
          position: event.position, seq: paired?.seq ?? event.seq, tool: 'read_evidence',
          label: `read ${target}`, rank: 5, kind: 'read',
          terms: termsOf(target), text: target,
        })
        continue
      }
      const command = commandOf(event.args)
      if (command !== '') {
        const paired = results.get(event.callId)
        candidates.push({
          position: event.position, seq: paired?.seq ?? event.seq, tool: 'read_evidence',
          label: `cmd ${command.slice(0, 80)}`, rank: 4, kind: 'cmd', terms: termsOf(command), text: command,
        })
      }
      continue
    }
    if (event.kind === 'result') {
      const raw = stripDenoisePointer(event.text)
      if (raw === '' || isEnvironmentalPath(raw)) continue
      const text = raw
      const call = calls.get(event.callId)
      const callPath = pathOf(call?.args)
      if (isOutsideWorkspace(callPath) || isOutsideWorkspace(envelopePathOf(text))) continue
      const command = commandOf(call?.args)
      const readLike = READ_LIKE.has(call?.name ?? '')
      const target = relativePath(callPath)
      if (looksLikeError(text, event.isError === true)) {
        const where = !readLike || target === '' ? cleanLabel(text) : target
        candidates.push({
          position: event.position, seq: event.seq, tool: 'read_evidence',
          label: `error ${where.slice(0, 72)}`, rank: 0, kind: 'error', terms: termsOf(text), text,
        })
        continue
      }
      if (TEST_COMMAND.test(command)) {
        candidates.push({
          position: event.position, seq: event.seq, tool: 'read_evidence',
          label: `test ${cleanLabel(text).slice(0, 72)}`, rank: 1, kind: 'test', terms: termsOf(text), text,
        })
        continue
      }
      if (VALUE_SIGNAL.test(text)) {
        const where = readLike && target !== '' ? target : cleanLabel(text)
        candidates.push({
          position: event.position, seq: event.seq, tool: 'read_evidence',
          label: `value ${where.slice(0, 72)}`, rank: 2, kind: 'value', terms: termsOf(text), text,
        })
        continue
      }
      if (readLike) continue
      candidates.push({
        position: event.position, seq: event.seq, tool: 'read_evidence',
        label: `result ${cleanLabel(text).slice(0, 72)}`, rank: 3, kind: 'output', terms: termsOf(text), text,
      })
      continue
    }
    if (event.kind === 'message') {
      if (event.role === 'user') continue
      const text = event.text
      const checked = /verif|check|passed|failed|test|edit/i.test(text)
      const stateful = /\d|\.py|\.js|\//.test(text)
      candidates.push({
        position: event.position, seq: event.seq, tool: 'read_history',
        label: `m${event.position} note ${firstLine(text).slice(0, 72)}`,
        rank: checked ? 1 : stateful ? 3 : 5, kind: 'note', terms: termsOf(text), text,
      })
    }
  }
  const seen = new Set()
  const unique = []
  for (const row of candidates.sort((a, b) => a.rank - b.rank || a.position - b.position)) {
    const fingerprint = `${row.kind}|${row.label.slice(0, 60)}|${row.terms.slice(0, 3).join(',')}`
    if (seen.has(fingerprint)) continue
    seen.add(fingerprint)
    unique.push(row)
  }
  const rowsOut = []
  const used = new Set()
  for (const kind of KIND_ORDER) {
    const row = unique.find((item) => item.kind === kind)
    if (row === undefined) continue
    rowsOut.push(row)
    used.add(row)
  }
  const counts = {}
  for (const row of rowsOut) counts[row.kind] = (counts[row.kind] ?? 0) + 1
  for (const row of unique) {
    if (rowsOut.length >= limit) break
    if (used.has(row)) continue
    if ((counts[row.kind] ?? 0) >= CAPS[row.kind]) continue
    counts[row.kind] = (counts[row.kind] ?? 0) + 1
    rowsOut.push(row)
  }
  rowsOut.sort((a, b) => a.rank - b.rank || a.position - b.position)
  return rowsOut.map((row, index) => ({ ...row, key: `E${index + 1}` }))
}
