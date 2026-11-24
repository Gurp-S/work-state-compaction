/**
 * Deterministic user-command projection.
 *
 * The design treats a user message as an origin signal, not a durable fact:
 * the first real command is kept verbatim, later commands are reduced to the
 * state the engine can prove from receipts. Nothing here calls a model, and a
 * completed command with no later effect is dropped once it falls outside the
 * recent window.
 */
import { byteLength } from './bytes.js'
import { termsOf } from './values.js'

const NON_COMMAND = /^(?:continue|go on|ok(?:ay)?|thanks|yes|no|sure)[.!]?$/i
const CHANGE_WORDS = /\b(?:change|changed|instead|no longer|do not|don't|revert|undo|replace|cancel|supersede|override)\b/i

const clip = (text, max) => {
  const value = String(text ?? '').replace(/\s+/g, ' ').trim()
  const cap = Math.max(0, max)
  return byteLength(value) <= cap ? value : `${value.slice(0, Math.max(0, cap - 1))}…`
}

const strongTerms = (text) => new Set(termsOf(text, 12).filter((term) => !/^\d+$/.test(term)))
const isPath = (term) => /\.[A-Za-z0-9]+$/.test(term) || /[\\/]/.test(term)
const pathsOf = (set) => new Set([...set].filter(isPath))
const namesOf = (set) => new Set([...set].filter((term) => !isPath(term)))

const stateEvidence = (row) => {
  const edit = /edit #(\d+)/.exec(row ?? '')
  const check = /check #(\d+)/.exec(row ?? '')
  return { edit: edit === null ? null : Number(edit[1]), check: check === null ? null : Number(check[1]) }
}

const normalizePath = (value) => String(value ?? '').toLowerCase().replace(/\\/g, '/')
const samePath = (left, right) => {
  const a = normalizePath(left)
  const b = normalizePath(right)
  if (a === '' || b === '') return false
  return a === b || a.endsWith(`/${b}`) || b.endsWith(`/${a}`)
}

// A historical command is complete when any later edit to its file contains one
// of its identifiers and that edit has a post-edit check. Reading only the
// newest edit would mark an older, verified command open after an unrelated
// change to the same file.
const completion = (terms, receipts, checks, seq) => {
  if (!Number.isInteger(seq)) return null
  const paths = pathsOf(terms)
  const names = [...namesOf(terms)].map((name) => name.toLowerCase())
  if (paths.size === 0 || names.length === 0) return null
  let edit = null
  for (const receipt of receipts ?? []) {
    // Only work after the command can complete it; an older edit with the same
    // identifier belongs to a previous request.
    if (!(receipt.edit > seq)) continue
    if (![...paths].some((path) => samePath(path, receipt.path))) continue
    const body = (Array.isArray(receipt.terms) && receipt.terms.length > 0
      ? receipt.terms.join(' ')
      : String(receipt.editText ?? '')).toLowerCase()
    if (!names.some((name) => body.includes(name))) continue
    if (edit === null || receipt.edit < edit) edit = receipt.edit
  }
  if (edit === null) return null
  const check = checks.find((seqNo) => seqNo > edit) ?? null
  return { edit, check }
}

/**
 * Classify every control against the engine state projection.
 *
 * Control numbers are 1-based indexes of the control list, the same numbering
 * `engineState` uses for `req#N`. A control with no projected row is kept as a
 * head line; a later change that shares a strong term supersedes it.
 *
 * @param {readonly string[]} controls accumulated user/developer messages.
 * @param {{ done?: string[], open?: string[], next?: string[], unknown?: string[] }} state
 * @param {{ doneLines?: number, headChars?: number,
 *   receipts?: Array<{ path: string, edit: number, check: number|null, editText: string }> }} [options]
 * @returns {Array<{ no: number, seq: number|null, text: string, head: string,
 *   status: string, stateRow: string, evidence: { edit: number|null, check: number|null },
 *   laterChangeBy: number|null }>}
 */
export function classifyCommands(controls, state, options = {}) {
  const items = (Array.isArray(controls) ? controls : []).map((control) =>
    typeof control === 'string'
      ? { text: String(control ?? ''), seq: null }
      : { text: String(control?.text ?? ''), seq: Number.isInteger(control?.seq) ? control.seq : null })
  const texts = items.map((item) => item.text.trim())
  const byNo = new Map()
  for (const key of ['done', 'open', 'next', 'unknown']) {
    for (const row of state?.[key] ?? []) {
      const text = String(row ?? '')
      for (const match of text.matchAll(/req#(\d+)/g)) byNo.set(Number(match[1]), { status: key, row: text })
    }
  }
  const origin = texts.findIndex((text) => text !== '' && !NON_COMMAND.test(text))
  const real = texts.map((text, index) => ({ text, no: index + 1 }))
    .filter((item) => item.text !== '' && !NON_COMMAND.test(item.text))
  const latestNo = real.at(-1)?.no ?? -1
  const checks = (Array.isArray(options.checks) && options.checks.length > 0
    ? [...options.checks]
    : [...(options.receipts ?? [])].map((receipt) => receipt?.check))
    .filter((value) => Number.isInteger(value))
    .sort((left, right) => left - right)
  const terms = texts.map((text) => strongTerms(text))
  // A later command supersedes an earlier one only when it names the same file
  // and the same identifier/aspect with a change word. Sharing a generic word
  // ("report", "rows") or only the file would mark independent fixes obsolete.
  const laterChange = (index) => {
    const paths = pathsOf(terms[index])
    const names = namesOf(terms[index])
    if (paths.size === 0) return null
    for (let next = index + 1; next < texts.length; next += 1) {
      if (texts[next] === '' || !CHANGE_WORDS.test(texts[next])) continue
      const laterPaths = pathsOf(terms[next])
      if (![...paths].some((path) => laterPaths.has(path))) continue
      const laterNames = namesOf(terms[next])
      if ([...names].some((name) => laterNames.has(name))) return next + 1
    }
    return null
  }
  const records = []
  if (origin === -1) return records
  texts.forEach((text, index) => {
    if (text === '' || NON_COMMAND.test(text)) return
    const no = index + 1
    if (no === origin + 1) {
      records.push({
        no, seq: items[index].seq, text, head: clip(text, options.headChars ?? 96),
        status: 'origin', stateRow: '', evidence: { edit: null, check: null }, laterChangeBy: null,
      })
      return
    }
    const projected = byNo.get(no)
    let status = projected?.status ?? 'recorded'
    let evidence = stateEvidence(projected?.row ?? '')
    const proven = completion(terms[index], options.receipts, checks, items[index].seq)
    if (proven !== null) {
      status = proven.check === null ? 'open' : 'done'
      evidence = proven
    } else if (laterChange(index) !== null) {
      status = 'superseded'
    } else if (projected === undefined) {
      status = no === latestNo ? 'next' : 'recorded'
    }
    const laterChangeBy = status === 'superseded' ? laterChange(index) : null
    records.push({
      no, seq: items[index].seq, text, head: clip(text, options.headChars ?? 96), status,
      stateRow: projected?.row ?? '', evidence,
      laterChangeBy,
    })
  })
  return records
}

/**
 * Render the origin command plus one line per retained command state.
 *
 * Full text survives for the origin and for open/next commands. Completed and
 * superseded commands keep a line only while they fall inside `doneLines`;
 * older ones are dropped. The block is bounded by `sectionBytes`; the origin is
 * always present and is clipped last.
 *
 * @param {ReturnType<typeof classifyCommands>} records
 * @param {{ originMaxChars?: number, activeMaxChars?: number, headChars?: number,
 *   sectionBytes?: number, doneLines?: number }} [options]
 * @returns {string}
 */
export function renderCommandState(records, options = {}) {
  const list = Array.isArray(records) ? records : []
  const origin = list.find((record) => record.status === 'origin')
  if (origin === undefined) return ''
  const statuses = list.filter((record) => record.status !== 'origin')
  const doneLines = Math.max(0, options.doneLines ?? 3)
  const recent = (status) => doneLines === 0
    ? []
    : statuses.filter((record) => record.status === status).slice(-doneLines)
  const visible = new Set()
  for (const record of statuses) {
    if (record.status === 'open' || record.status === 'next') visible.add(record.no)
  }
  for (const status of ['done', 'superseded', 'unknown', 'recorded']) {
    for (const record of recent(status)) visible.add(record.no)
  }
  const dropped = statuses.filter((record) => !visible.has(record.no)).length
  const order = statuses.filter((record) => visible.has(record.no))

  const line = (record, caps) => {
    const head = clip(record.text, caps.head)
    const later = record.laterChangeBy === null ? '' : `; later changed by #${record.laterChangeBy}`
    if (record.status === 'open' || record.status === 'next') {
      return `#${record.no} ${record.status}: "${clip(record.text, caps.active)}"`
    }
    if (record.status === 'done') {
      const edit = record.evidence.edit === null ? '' : ` (edit #${record.evidence.edit}`
      const check = record.evidence.check === null ? '' : `, check #${record.evidence.check}`
      const where = edit === '' ? '' : `${edit}${check})`
      return `#${record.no} done${where}${later}: ${head}`
    }
    if (record.status === 'superseded') {
      return `#${record.no} superseded${record.laterChangeBy === null ? '' : ` by #${record.laterChangeBy}`}: ${head}`
    }
    if (record.status === 'unknown') return `#${record.no} unknown: ${head}`
    return `#${record.no} recorded: ${head}`
  }

  const build = (caps) => {
    const statusText = order.length === 0
      ? ''
      : `Command state: ${order.map((record) => line(record, caps)).join('; ')}.` + (dropped > 0
        ? ` ${dropped} earlier completed/superseded commands omitted.`
        : '')
    const originText = `Origin command (#${origin.no}): "${clip(origin.text, caps.origin)}"`
    return [originText, statusText].filter((part) => part !== '').join('\n\n')
  }

  const budget = Math.max(400, options.sectionBytes ?? 1800)
  const caps = {
    origin: Math.max(160, options.originMaxChars ?? 1200),
    active: Math.max(120, options.activeMaxChars ?? 400),
    head: Math.max(24, options.headChars ?? 96),
  }
  let text = build(caps)
  while (byteLength(text) > budget && (caps.origin > 160 || caps.active > 120 || caps.head > 24)) {
    if (caps.head > 24) caps.head = Math.max(24, caps.head - 24)
    else if (caps.active > 120) caps.active = Math.max(120, caps.active - 80)
    else caps.origin = Math.max(160, caps.origin - 80)
    text = build(caps)
  }
  return text
}
