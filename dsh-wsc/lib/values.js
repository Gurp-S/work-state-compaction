/**
 * Engine-owned exact values, ported from `coding_ledger.py`.
 *
 * A tool result that states an exact value is discovery surface of its own: the
 * engine can list it without deciding which value the task needs, and the model
 * can copy it instead of re-running the command. No model call is involved.
 */
import { eventAt } from './session.js'
import { toolResultOf } from './projection.js'

// The reference writes `\b(?:is|=|:)`; that boundary never fires for the
// spaced form `NAME = 20` because both the space and `=` are non-word. Keep
// both assignment spellings so a spaced assignment still counts.
export const VALUE_SIGNAL = /\b[A-Z]{2,}\d+\b|(?:\bis\b|[=:])\s*[-+]?\d+(?:\.\d+)?\b/
export const TEST_COMMAND = /test|unittest|pytest|check/i

const TERM_PATTERNS = [
  /[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|txt|cjs)/g,
  /\b[A-Z]{2,}-\d+\b/g,
  /\b[A-Z][A-Z0-9_]{2,}\b/g,
  /\b[a-z]+[A-Z][A-Za-z0-9]+\b/g,
  /\b[a-z][a-z0-9]*_[a-z0-9_]+\b/g,
  /\b\d{2,}\b/g,
  /(?:\bwinerror|\bhttp|\berrno)\s*\d+/gi,
  /(?:node --test[^\n]{0,30}|python -m unittest[^\n]{0,40})/gi,
]

const MAX_TERMS = 6
const MAX_LABEL = 96

// Tools address files by absolute path; labels and state relations read by the
// region's own short form (`src/report.js`), so the workspace root is stripped
// when the process runs inside it.
const ROOT = (() => {
  try { return process.cwd() } catch { return '' }
})()
const slash = (text) => text.replace(/\\/g, '/')
export const relativePath = (path) => {
  const value = slash(String(path ?? ''))
  if (value === '' || ROOT === '') return value
  const root = slash(ROOT).replace(/\/+$/, '')
  if (value.toLowerCase() === root.toLowerCase()) return '.'
  if (value.toLowerCase().startsWith(`${root.toLowerCase()}/`)) return value.slice(root.length + 1)
  return value
}

// Tool results wrap content in `<path>`/`<type>`/`<content>` tags; a label that
// starts with a tag names the envelope, not the value.
export const unwrapToolResult = (text) => String(text ?? '')
  .replace(/^\s*<path>[\s\S]*?<\/path>\s*/i, '')
  .replace(/^\s*<type>[^<]*<\/type>\s*/i, '')
  .replace(/^\s*<content>\s*/i, '')

export const firstLine = (text) => unwrapToolResult(text).split('\n')
  .map((line) => line.trim())
  .find((line) => line !== '' && !/^<[^>]+>$/.test(line)) ?? ''

export const envelopePathOf = (text) => {
  const match = /^\s*<path>([\s\S]*?)<\/path>/i.exec(String(text ?? ''))
  return match === null ? '' : match[1].trim()
}

/**
 * Spill files, temp scratch and round transcripts are runtime scaffolding.
 * A checkpoint that names them sends the resumed model to read files that no
 * source edit owns, so every renderer drops them.
 */
export const isEnvironmentalPath = (value) => {
  const text = String(value ?? '')
  if (text === '') return false
  return /dsh-spill-|[\\/]AppData[\\/]Local[\\/]Temp[\\/]|[\\/]out[\\/]round-\d+\.(?:jsonl|txt)\b/i.test(text)
}

/**
 * Absolute paths outside the workspace are not sources this session owns.
 * Relative paths are workspace-relative by construction.
 */
export const isOutsideWorkspace = (value) => {
  const text = String(value ?? '')
  if (text === '') return false
  if (isEnvironmentalPath(text)) return true
  const normalized = slash(text)
  if (!/^(?:[A-Za-z]:\/|\/\/|\/)/.test(normalized)) return false
  const root = slash(ROOT).replace(/\/+$/, '')
  if (root === '') return false
  const lower = normalized.toLowerCase()
  return lower !== root.toLowerCase() && !lower.startsWith(`${root.toLowerCase()}/`)
}

/**
 * Drop the runtime's own spill receipt from a denoised result.
 *
 * The receipt names a scratch file; it is scaffolding for the live model, not
 * evidence a checkpoint should index or quote.
 */
export const stripDenoisePointer = (text) =>
  String(text ?? '').replace(/\n\n\[denoise: [^\]]*\]\s*$/, '')

const ERROR_HEAD = /^(?:eperm|eacces|enoent|not ok\b|[×✖]\s+\S|[A-Za-z]*error\b|exception\b|traceback\b|fatal\b|unhandled\b)/i

/**
 * True only for a runtime-flagged failure or a result whose first real line
 * opens as an error. Source text that merely contains `throw new Error(...)`
 * is not a failure: reading it succeeded.
 */
export const looksLikeError = (text, flagged = false) => {
  if (flagged === true) return true
  const line = firstLine(text).replace(/^\d+:\s*/, '')
  return line !== '' && !line.startsWith('<') && ERROR_HEAD.test(line)
}

/** Mechanical identifying tokens: paths, identifiers, numbers, codes, commands. */
export function termsOf(text, limit = MAX_TERMS) {
  const found = []
  for (const pattern of TERM_PATTERNS) {
    for (const match of String(text ?? '').match(pattern) ?? []) {
      const value = match.trim().slice(0, 48)
      // Encoded payloads can bleed JSON punctuation into a match; a token with
      // quotes or braces is not a literal a later turn should copy.
      if (!value || /["\\{}[\]]/.test(value)) continue
      if (!found.some((item) => item.toLowerCase() === value.toLowerCase())) found.push(value)
      if (found.length >= limit) return found
    }
  }
  return found
}

const parseArgs = (value) => {
  if (value !== null && typeof value === 'object') return value
  try { return JSON.parse(value) } catch { return {} }
}

const targetOf = (args) => ['path', 'file_path', 'target_file']
  .map((key) => args?.[key])
  .find((value) => typeof value === 'string' && value !== '') ?? ''

/**
 * Region rows with their event sequences.
 *
 * Value rows must be addressable by a durable seq, because the presentation may
 * keep only the newest rows. Deriving them from the session surface keeps the
 * key stable across a checkpoint that trims older rows.
 *
 * @param {object} session owning session.
 * @param {number} start first shadowed seq.
 * @param {number} end last shadowed seq (inclusive).
 * @returns {Array<{ seq: number, message: object }>}
 */
export function regionRows(session, start, end) {
  const nodes = session?.surface?.nodes ?? []
  const from = nodes.indexOf(start)
  const to = nodes.indexOf(end)
  if (from === -1 || to === -1 || to < from) return []
  const rows = []
  for (let index = from; index <= to; index += 1) {
    const seq = nodes[index]
    const event = eventAt(session, seq)
    if (event === undefined) continue
    let message
    try { message = session.deriveEventMessage(event) } catch { continue }
    if (message === null || message === undefined) continue
    rows.push({ seq, message })
  }
  return rows
}

/**
 * Every tool result that states an exact value, addressable by a stable key.
 *
 * @param {Array<{ seq: number, message: object }>} rows region rows.
 * @returns {Array<object>} value rows in event order.
 */
export function valueRows(rows) {
  return regionValueRows(rows).map((row, index) => ({ key: `V${index + 1}`, ...row }))
}

/**
 * Value rows of one region without keys.
 *
 * A journal assigns global keys and dedupes by text digest, so a value found in
 * an earlier region keeps its key after the next compaction. The reference
 * computes the ledger over every event of the session; DSH only sees the current
 * region, and without this the ledger forgets a value at each compaction.
 *
 * @param {Array<{ seq: number, message: object }>} rows region rows.
 * @returns {Array<object>} value rows in event order, `key` unset.
 */
const LINE_PREFIX = /^\s*\d+:\s?/
const CONST_ASSIGN = /^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(-?\d+(?:\.\d+)?)\s*;?\s*$/
const UPPER_ASSIGN = /^\s*([A-Z][A-Z0-9_]{1,})\s*=\s*(-?\d+(?:\.\d+)?)\s*$/
const JSON_NUMBER = /^\s*"([A-Za-z_$][\w$]*)"\s*:\s*(-?\d+(?:\.\d+)?)\s*,?\s*$/

// A file read is a snapshot, not a value statement. Only an assignment with a
// numeric right-hand side is a constant a later turn can copy; test bodies,
// grep output and spill files contain numbers everywhere and crowd the list.
const VALUE_SOURCE_SKIP = /(?:^|\/)(?:tests?|node_modules|vendor|dist|coverage|fixtures?)(?:\/|$)|(?:^|\/)dsh-spill|(?:^|\/)[^/]*lock[^/]*$/i

export function distillConstants(text) {
  const body = unwrapToolResult(text)
  const found = new Map()
  for (const raw of body.split(/\r?\n/)) {
    const line = raw.replace(LINE_PREFIX, '')
    const match = CONST_ASSIGN.exec(line) ?? UPPER_ASSIGN.exec(line) ?? JSON_NUMBER.exec(line)
    if (!match) continue
    found.set(match[1], match[2])
  }
  return [...found].map(([name, value]) => ({ name, value }))
}

export function regionValueRows(rows) {
  const calls = new Map()
  for (const row of rows) {
    for (const block of row.message?.content ?? []) {
      if (block?.type === 'tool-call' && typeof block.id === 'string') {
        calls.set(block.id, { name: block.name, args: parseArgs(block.arguments), seq: row.seq })
      }
    }
  }
  const values = []
  const byIdentity = new Map()
  rows.forEach((row, index) => {
    const result = toolResultOf(row.message)
    if (result === undefined) return
    const call = calls.get(result.callId)
    if (call?.name !== 'read') return
    const target = relativePath(targetOf(call?.args))
    if (target === '' || VALUE_SOURCE_SKIP.test(target.replace(/\\/g, '/'))) return
    for (const { name, value } of distillConstants(String(result.text ?? ''))) {
      const identity = `${target}#${name}`
      const record = {
        seq: row.seq,
        message: index + 1,
        identity,
        name,
        value,
        label: `${target}: ${name} = ${value}`.slice(0, MAX_LABEL),
        terms: [name, target],
        text: `${name} = ${value}`,
      }
      const previous = byIdentity.get(identity)
      if (previous !== undefined) values.splice(values.indexOf(previous), 1)
      byIdentity.set(identity, record)
      values.push(record)
    }
  })
  return values
}

/** One rendered value line: key, label, terms, and the tool/seq that reads it. */
export function valueLine(row) {
  const terms = row.terms.length > 0 ? ` | terms: ${row.terms.join(', ')}` : ''
  return `[${row.key}] ${row.label}${terms} (read_evidence #${row.seq})`
}

/**
 * Render the value block newest-first, naming the keys it had to drop.
 *
 * Python `passage.py` renders the newest rows and lists archived keys, so a
 * value is never silently lost.
 *
 * @param {Array<object>} rows value rows in event order.
 * @param {{ maxRows?: number }} [options]
 * @returns {string[]} lines oldest-first (the builder reverses for display).
 */
export function renderValueLines(rows, options = {}) {
  if (!Array.isArray(rows) || rows.length === 0) return []
  const maxRows = Math.max(1, options.maxRows ?? 16)
  if (rows.length <= maxRows) return rows.map(valueLine).reverse()
  const kept = rows.slice(-maxRows).reverse().map(valueLine)
  const dropped = rows.slice(0, rows.length - maxRows).map((row) => row.key)
  const names = dropped.length > 10
    ? `${dropped[0]}..${dropped[dropped.length - 1]}`
    : dropped.join(', ')
  return [...kept, `(older values omitted; fetch ${names})`]
}

/**
 * Hide ledger facts that only restate a value the engine already lists.
 *
 * Presentation only: stored entries and engine state are untouched. This is the
 * `merge_engine_values` rule from the reference; nosig does not enable it by
 * default, but the dedupe is available to a caller that does.
 *
 * @param {Array<object>} entries ledger entries.
 * @param {Array<object>} values engine value rows.
 * @returns {Array<object>} entries to display.
 */
export function mergeEngineValues(entries, values) {
  if (!Array.isArray(values) || values.length === 0) return entries
  const tokens = new Set()
  for (const row of values) {
    for (const term of row.terms ?? []) tokens.add(String(term).toLowerCase())
    for (const term of termsOf(row.text ?? '')) tokens.add(term.toLowerCase())
  }
  const pureValue = /^(?:[^:=]{1,80}:\s*)?[^=]{1,60}=\s*[A-Za-z0-9_./"'\\-]+$/
  return entries.filter((entry) => {
    const text = String(entry.text ?? '').trim()
    if (entry.kind !== 'fact' || !pureValue.test(text)) return true
    return !(text.match(/[A-Za-z0-9_]{3,}/g) ?? [])
      .some((token) => tokens.has(token.toLowerCase()))
  })
}
