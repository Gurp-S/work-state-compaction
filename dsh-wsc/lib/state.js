/**
 * Engine-owned work state, ported from `live.py::engine_state` and
 * `receipts_from_events`.
 *
 * The ledger keeps conclusions; this projection keeps the relations a resume
 * decision needs: the latest edit payload, whether it still matches an active
 * requirement, what the check covers, and who originated the requirement. No
 * model call is involved.
 */
import { toolResultOf } from './projection.js'
import { looksLikeError, relativePath, termsOf } from './values.js'

const THIN_PATH = /[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|txt|cjs)/g
const STATE_STOP = new Set(['round', 'change', 'file', 'source', 'test', 'tests', 'pass', 'result', 'ok',
  'continue', 'latest', 'current', 'after', 'before', 'edit', 'edits', 'path',
  'requirement', 'requirements', 'policy', 'the', 'and', 'for', 'with'])
const STATE_WORDS = ['async', 'await', 'synchronous', 'asynchronous']
const REQ_STOP = new Set(['requirement', 'must', 'should', 'then', 'with', 'from', 'that', 'this',
  'have', 'also', 'only', 'will', 'using', 'use', 'the', 'and', 'for', 'not',
  'exact', 'current', 'version', 'file', 'files', 'continue', 'please'])
const TEST_COMMAND = /test|unittest|pytest|check/i
const NEXT_LINE = /\bnext(?:\s+(?:step|action))?\s*:\s*(.+?)(?:\.\s|\.$|$)/i
const CHANGE_WORDS = /\b(change|changed|instead|no longer|do not|don't|revert|undo|replace|cancel)\b/i
// A change verb marks a work requirement. `run`/`read` alone is a probe: the
// user asks for a report, not for a change that state could be open about.
const ACTION_WORDS = /\b(add|change|update|fix|implement|refactor|remove|rename|create|write|wire|make|use|set|limit|support|sort|validate|export|replace)\b/i
const PATH_LIKE = /[\\/]|\.[A-Za-z0-9]{1,5}$/

const clean = (text) => String(text ?? '').replace(/\s+/g, ' ').trim()
const clip = (text, limit) => {
  const value = clean(text)
  if (value.length <= limit) return value.replace(/[ ;,]+$/, '')
  return `${value.slice(0, limit).replace(/\s+\S*$/, '').replace(/[ ;,]+$/, '')}…`
}
const quote = (text) => {
  const value = clean(text)
  return value === '' ? '(empty)' : `"${value.slice(0, 40)}"`
}
const parseArgs = (value) => {
  if (value !== null && typeof value === 'object') return value
  try { return JSON.parse(value) } catch { return {} }
}
const pathOf = (args) => ['path', 'file_path', 'target_file', 'notebook_path']
  .map((key) => args?.[key])
  .find((value) => typeof value === 'string' && value !== '') ?? ''

/** Literals, quoted spans and identifier words from a requirement. */
export function significantTerms(text) {
  const found = termsOf(text ?? '', 12)
  for (const quoted of String(text ?? '').match(/"([^"\n]{2,48})"/g) ?? []) {
    const value = quoted.slice(1, -1)
    if (!found.includes(value)) found.push(value)
  }
  const lowered = String(text ?? '').toLowerCase()
  for (const word of STATE_WORDS) {
    if (new RegExp(`\\b${word}\\b`).test(lowered)) found.push(word)
  }
  return [...new Set(found)].filter((term) => term.length >= 3 && !STATE_STOP.has(term.toLowerCase()))
}

/** Anchors from the requirement itself; plain identifiers stay anchors. */
export function requirementTerms(text) {
  const found = significantTerms(text)
  const lowered = String(text ?? '').toLowerCase()
  for (const match of lowered.matchAll(/\b([a-z_][a-z0-9_]*)\s+(?:to|=)\s+([a-z0-9_./-]+)/g)) {
    for (const term of [match[1], match[2]]) {
      if (REQ_STOP.has(term) || STATE_STOP.has(term) || found.includes(term)) continue
      found.push(term)
    }
  }
  return found
}

/**
 * Mechanical receipts: which edit each later test-like check actually covers.
 *
 * @param {Array<{ seq: number, message: object }>} rows region rows.
 * @returns {Array<object>} one receipt per edit, in edit order.
 */
export function receiptsFromRows(rows) {
  const calls = new Map()
  const failed = new Set()
  for (const row of rows) {
    for (const block of row.message?.content ?? []) {
      if (block?.type === 'tool-call' && typeof block.id === 'string') {
        calls.set(block.id, { name: block.name, args: parseArgs(block.arguments) })
      }
    }
    const result = toolResultOf(row.message)
    if (result !== undefined && looksLikeError(result.text, result.isError === true)) failed.add(result.callId)
  }
  const edits = []
  const checks = []
  rows.forEach((row, index) => {
    const position = index + 1
    for (const block of row.message?.content ?? []) {
      if (block?.type !== 'tool-call') continue
      if (block.name !== 'edit' && block.name !== 'write') continue
      if (failed.has(block.id)) continue
      const args = parseArgs(block.arguments)
      const path = relativePath(pathOf(args))
      if (path === '') continue
      const next = typeof args.new_string === 'string' ? args.new_string
        : typeof args.content === 'string' ? args.content : ''
      edits.push({ at: position, seq: row.seq ?? position, path, text: next })
    }
    const result = toolResultOf(row.message)
    if (result === undefined) return
    const call = calls.get(result.callId)
    const command = String(call?.args?.command ?? call?.args?.cmd ?? '')
    if (!TEST_COMMAND.test(command)) return
    checks.push({
      at: position,
      seq: row.seq ?? position,
      command: command.slice(0, 80),
      result: clip(String(result.text ?? '').split('\n').find((line) => line.trim() !== '') ?? '', 120),
      synthetic: /synthetic/i.test(`${command} ${result.text ?? ''}`),
    })
  })
  return edits.map((edit) => {
    const later = edits.find((other) => other.path === edit.path && other.at > edit.at)
    const window = checks.filter((check) => check.at > edit.at && (later === undefined || check.at < later.at))
    const last = window.at(-1)
    return {
      path: edit.path,
      edit: edit.at,
      editSeq: edit.seq,
      editText: edit.text,
      check: last === undefined ? null : last.at,
      checkSeq: last === undefined ? null : last.seq,
      command: last?.command ?? '',
      result: last?.result ?? '',
      synthetic: last?.synthetic === true,
      stale: later !== undefined && last !== undefined,
    }
  })
}

// A tool call may address a file by absolute path while the user wrote the
// region's short form; both name the same edit.
const normalizePath = (value) => String(value ?? '').toLowerCase().replace(/\\/g, '/')
const samePath = (a, b) => {
  const left = normalizePath(a)
  const right = normalizePath(b)
  if (left === '' || right === '') return false
  return left === right || left.endsWith(`/${right}`) || right.endsWith(`/${left}`)
}

const entryAuthority = (entry, rows) => {
  const cites = Array.isArray(entry?.cites) ? entry.cites : []
  if (cites.length === 0) return null
  const roles = cites.map((n) => rows[n - 1]?.message?.role)
  return roles.every((role) => role === 'assistant') ? 'assistant' : null
}
const tag = (text, authority) => (authority === 'assistant' ? `(assistant-originated) ${text}` : text)
const stateClean = (text) => clean(text).replace(/^(requirement|constraint|change)\s*:\s*/i, '')

/**
 * Project done/open/next/unknown for the current region.
 *
 * @param {Array<object>} entries active ledger entries.
 * @param {Array<{ seq: number, message: object }>} rows region rows.
 * @param {Array<object>} receipts rows from {@link receiptsFromRows}.
 * @param {{ controls?: string[], isSynthetic?: (message: object) => boolean,
 *   promoteUnmatched?: boolean }} [options]
 *   accumulated control messages in order; a predicate for engine notices that
 *   are user-role messages but carry no user request; whether the newest
 *   unmatched request becomes `next` instead of leaving the state empty.
 */
export function engineState(entries, rows, receipts, options = {}) {
  const synthetic = typeof options.isSynthetic === 'function' ? options.isSynthetic : () => false
  const userRowsOnly = rows.filter((row) =>
    row.message?.role === 'user' && synthetic(row.message) !== true)
  const state = { done: [], open: [], next: [], unknown: [] }
  const gapKeys = new Set()
  const active = entries.filter((entry) => (entry.status ?? 'active') === 'active')
  const requirements = active.filter((entry) => ['requirement', 'constraint'].includes(entry.kind))
  const controlTexts = [...new Set(Array.isArray(options.controls) && options.controls.length > 0
    ? options.controls.map(clean).filter((text) => text !== '')
    : userRowsOnly
      .map((row) => clean(projectText(row.message)))
      .filter((text) => text !== ''))]
  const controlNo = new Map(controlTexts.map((text, index) => [text, index + 1]))
  const covered = new Set(requirements.flatMap((entry) => significantTerms(entry.text ?? '')))
  for (const entry of active) {
    if (entry.kind !== 'fact' && entry.kind !== 'decision') continue
    if (!/\b(?:pending|remaining|todo)\b/i.test(entry.text ?? '')) continue
    const terms = new Set(significantTerms(entry.text ?? ''))
    if ([...terms].some((term) => covered.has(term))) continue
    requirements.push(entry)
    for (const term of terms) covered.add(term)
  }
  // Requirements are synthesized over the accumulated controls, not only the
  // current region: the reference projects from every event, and a request
  // stated before this region still owns the edit it produced there.
  const candidates = Array.isArray(options.controls) && options.controls.length > 0
    ? controlTexts.map((text, index) => ({ position: index, text }))
    : userRowsOnly.map((row) => ({
        position: rows.indexOf(row) + 1,
        text: clean(projectText(row.message)),
      }))
  const messagesByPath = new Map()
  for (const { position, text } of candidates) {
    if (text === '' || text.replace(/\.$/, '').toLowerCase() === 'continue') continue
    const paths = text.match(THIN_PATH)
    if (!paths || paths.length === 0) continue
    if (!messagesByPath.has(paths[0])) messagesByPath.set(paths[0], [])
    messagesByPath.get(paths[0]).push({ position, text })
  }
  for (const rowsOfPath of messagesByPath.values()) {
    const changed = rowsOfPath.findIndex(({ text }) => /\b(change|now|instead|no longer|replace)\b/i.test(text))
    const kept = changed === -1 ? rowsOfPath : rowsOfPath.slice(changed)
    for (const { position, text } of kept) {
      // A message that only asks for a read or a summary is not a work
      // requirement, and a shared file path alone must not mark a later change
      // as already covered.
      if (!ACTION_WORDS.test(text)) continue
      const terms = new Set(significantTerms(text))
      const work = [...terms].filter((term) => !PATH_LIKE.test(term))
      if (work.some((term) => covered.has(term))) continue
      requirements.push({
        kind: 'requirement', text, status: 'active', seq: position,
        control_no: controlNo.get(text), synthesized: true, order: position,
      })
      for (const term of work) covered.add(term)
    }
  }

  const edits = receipts.map((receipt) => ({ at: receipt.edit, path: receipt.path, new: receipt.editText }))
  const byPath = new Map(edits.map((edit) => [edit.path, edit]))
  const editFor = (path) => byPath.get(path) ?? edits.find((edit) => samePath(edit.path, path))
  const unmatched = []
  let matchedOrder = -1
  for (const entry of requirements) {
    const text = stateClean(entry.text ?? '').replace(/[. ]+$/, '')
    if (text === '') continue
    const brief = entry.control_no ? `req#${entry.control_no}` : clip(text, 160)
    const terms = [...new Set(requirementTerms(clean(entry.text ?? '')))]
    const paths = (entry.text ?? '').match(THIN_PATH)
    const path = paths?.[0]
    const edit = path ? editFor(path) : edits.at(-1)
    const authority = entryAuthority(entry, rows)
    if (edit === undefined) {
      // A requirement stated before this region names work whose edit may be
      // in an earlier region; "open" would be a claim this region cannot make.
      if (entry.synthesized === true) {
        unmatched.push(entry)
        continue
      }
      const where = path ? `no edit to ${path} found` : 'no target file identified'
      state.open.push(tag(`${brief}; ${where}`, authority))
      continue
    }
    if (entry.synthesized === true) matchedOrder = Math.max(matchedOrder, entry.order ?? -1)
    const matches = (candidate) => {
      const next = String(candidate.new ?? '').toLowerCase()
      const found = terms.filter((term) => next.includes(term.toLowerCase()) && term.toLowerCase() !== (path ?? '').toLowerCase())
      if (/\bsynchronous\b|\bsync\b/i.test(text) && /(?<!async )\bdef\s+/.test(next)) found.push('def')
      return found
    }
    const matched = matches(edit)
    const earlier = edits.filter((candidate) => (!path || samePath(candidate.path, path))
      && candidate.at < edit.at && matches(candidate).length > 0)
    const receipt = receipts.find((row) => samePath(row.path, edit.path) && row.edit === edit.at)
    if (matched.length > 0) {
      if (receipt?.check) {
        const detail = clip(receipt.result ?? '', 60)
        const command = String(receipt.command ?? '').slice(0, 40)
        state.done.push(tag(`${brief} (edit #${edit.at}, check #${receipt.check}`
          + (command || detail ? ` ${command}: ${detail}` : '') + ')', authority))
      } else {
        state.open.push(tag(`${brief}; edit #${edit.at} matches but has no post-edit check`, authority))
      }
    } else if (earlier.length > 0) {
      state.unknown.push(tag(`${brief}; latest edit #${edit.at} to ${edit.path} wrote `
        + `${quote(edit.new)}; earlier edit #${earlier.at(-1).at} matched; current state unverified`, authority))
    } else {
      state.open.push(tag(`${brief}; latest edit to ${edit.path} wrote ${quote(edit.new)}`, authority))
    }
    if (receipt?.check) {
      for (const [kind, row] of [
        ['synthetic', `check at #${receipt.check} is synthetic; it does not verify ${edit.path}`],
        ['stale', `${edit.path} changed after the check at #${receipt.check}`],
      ]) {
        const key = `${edit.path}:${receipt.check}:${kind}`
        if (receipt[kind] && !gapKeys.has(key)) {
          gapKeys.add(key)
          state.unknown.push(row)
        }
      }
    }
  }

  let nextPosition = -1
  let nextValue = ''
  let nextRole = null
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const match = NEXT_LINE.exec(projectText(rows[index].message) ?? '')
    if (match) {
      nextPosition = index
      nextValue = clip(match[1], 120)
      nextRole = rows[index].message?.role ?? null
      break
    }
  }
  if (nextValue !== '') {
    const terms = new Set(significantTerms(nextValue))
    let stale = ''
    for (const row of rows.slice(nextPosition + 1)) {
      if (row.message?.role !== 'user') continue
      const text = clean(projectText(row.message))
      if (!CHANGE_WORDS.test(text)) continue
      if ([...significantTerms(text)].some((term) => terms.has(term))) {
        stale = text.slice(0, 120)
        break
      }
    }
    if (stale !== '') state.unknown.push(`recorded next action may be stale after a later change: ${stale}`)
    else state.next.push(`${nextValue}${nextRole === 'assistant' ? ' (assistant-originated)' : ''}`)
  }
  if (state.next.length > 0) {
    const value = state.next[0].replace(/\s*\([^)]*originated\)$/, '').slice(0, 60).toLowerCase()
    state.open = state.open.filter((row) => !row.toLowerCase().includes(value))
  }
  if (options.promoteUnmatched !== false && state.next.length === 0 && unmatched.length > 0) {
    // The newest instruction has no edit in this region. It is still the goal a
    // resuming model must satisfy, so name it as next instead of publishing an
    // empty state block.
    const latest = unmatched.at(-1)
    if ((latest.order ?? -1) > matchedOrder) {
      const text = stateClean(latest.text ?? '').replace(/[. ]+$/, '')
      if (text !== '') {
        const brief = latest.control_no ? `req#${latest.control_no}` : 'latest request'
        state.next.push(`${brief}; complete the latest request: ${clip(text, 120)}`)
      }
    }
  }
  if (state.open.length > 0 && state.next.length === 0) {
    state.unknown.push('next action not recorded for the open item')
  }
  for (const key of ['done', 'open', 'next', 'unknown']) {
    state[key] = [...new Set(state[key].map((row) => row.slice(0, 200)))].slice(0, 6)
  }
  return state
}

/** One receipt per path: the latest edit and the check that followed it. */
export function recentReceipts(receipts) {
  const seen = new Set()
  const kept = []
  for (const receipt of [...(receipts ?? [])].reverse()) {
    if (seen.has(receipt.path)) continue
    seen.add(receipt.path)
    kept.push(receipt)
  }
  return kept.reverse()
}

/**
 * The latest distinct edits as a compact recency block.
 *
 * A ranked ledger keeps conclusions, not the newest concrete change; resume
 * questions about what just changed need the edit itself. One line per path,
 * newest first, from the receipt the state projection already computes.
 *
 * @param {Array<object>} receipts rows from {@link receiptsFromRows}.
 * @param {number} [limit] maximum paths to show.
 * @returns {string} rendered lines, or '' when nothing was edited.
 */
export function recentChanges(receipts, limit = 3) {
  const seen = new Set()
  const lines = []
  for (const receipt of [...(receipts ?? [])].reverse()) {
    if (seen.has(receipt.path) || lines.length >= limit) continue
    seen.add(receipt.path)
    const changed = String(receipt.editText ?? '')
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find((line) => line !== '')
    const check = Number.isInteger(receipt.check) ? `, check #${receipt.check}` : ''
    lines.push(`- ${receipt.path} (edit #${receipt.edit}${check})` + (changed ? `: ${clip(changed, 80)}` : ''))
  }
  return lines.join('\n')
}

/** Message text without tool output: state reads user/assistant prose only. */
function projectText(message) {
  const blocks = Array.isArray(message?.content) ? message.content : []
  return blocks
    .filter((block) => block?.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
}

/**
 * Normalize a projection for `parseCheckpointState`, which rejects an open item
 * without a next action. Keeping the item visible as unknown is the same fact
 * the reference states in prose.
 */
export function asCheckpointState(state) {
  const normalized = {
    done: [...state.done], open: [...state.open], next: [...state.next], unknown: [...state.unknown],
  }
  if (normalized.open.length > 0 && normalized.next.length === 0) {
    normalized.unknown = [...normalized.unknown, ...normalized.open.map((row) => `open: ${row}`)]
    normalized.open = []
  }
  for (const key of ['done', 'open', 'next', 'unknown']) {
    normalized[key] = [...new Set(normalized[key].map((row) => row.replace(/\s+/g, ' ').slice(0, 200)))].slice(0, 6)
  }
  return normalized
}

/** Render the projection in the reference's `done: … open: …` form. */
export function renderEngineState(state) {
  return ['done', 'open', 'next', 'unknown']
    .filter((key) => state[key]?.length > 0)
    .map((key) => `${key}: ${state[key].join('; ')}`)
    .join('\n')
}
