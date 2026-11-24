/**
 * One deterministic passage for the nosig checkpoint, ported from
 * `src/wsc/passage.py`.
 *
 * The rendered order is control, the ranked ledger, the work state, the
 * mechanical checks, the engine value ledger and the discovery index. When the
 * passage exceeds the budget it gives up index slots first, then the oldest
 * values, and only then the lowest-ranked ledger entry; the control text is
 * never trimmed.
 */
import { byteLength } from './bytes.js'
import { cleanEntryText, hasValue } from './ledger-denoise.js'

const LABELS = {
  constraint: 'Constraint',
  requirement: 'Requirement',
  decision: 'Decision',
  verification: 'Verification',
  fact: 'Context',
}
const RANK = { fact: 0, verification: 1, decision: 2, requirement: 3, constraint: 4 }
const STATE_KEYS = ['done', 'open', 'next', 'unknown']

/**
 * Keep a bounded ledger: high rank first, newest first within a rank, then
 * restore chronological order for display. Without this the ledger grows with
 * every compaction and eventually crowds out state/values/index.
 *
 * @param {readonly object[]} ledger
 * @param {number} maxBytes 0 keeps every entry.
 * @returns {{ entries: object[], omitted: number }}
 */
export function capLedger(ledger, maxBytes, options = {}) {
  const active = (ledger ?? []).filter((entry) => (entry.status ?? 'active') === 'active')
  if (!(maxBytes > 0)) return { entries: active, omitted: 0 }
  // A value-bearing claim is what a later probe can ask for; when the cap has
  // to cut, keep it ahead of plain prose of the same kind.
  // A probe-able fact outranks a decision; decisions are history, values are
  // what a later question asks for.
  const rankOf = (entry) => {
    const base = RANK[entry.kind] ?? 0
    if (options.valueFirst !== true || !hasValue(entry.text)) return base
    return entry.kind === 'fact' ? 2.5 : base + 0.5
  }
  const ranked = [...active].sort((a, b) => rankOf(b) - rankOf(a) ||
    (b.seq ?? b.order ?? 0) - (a.seq ?? a.order ?? 0))
  const kept = []
  let bytes = 0
  for (const entry of ranked) {
    const cost = byteLength(String(entry.text ?? '')) + 64
    if (bytes + cost > maxBytes) continue
    kept.push(entry)
    bytes += cost
  }
  kept.sort((a, b) => (a.seq ?? a.order ?? 0) - (b.seq ?? b.order ?? 0))
  return { entries: kept, omitted: active.length - kept.length }
}

const blockedBy = (text, blocked) =>
  blocked.some((phrase) => String(text ?? '').includes(phrase))
const dropPeriod = (text) => String(text ?? '').replace(/\.+$/, '')

/**
 * Ledger entries as one ranked sentence list.
 *
 * Constraint and requirement outrank decisions, which outrank facts; within a
 * rank the older entry stays first and the same claim is stated once.
 *
 * @param {ReadonlyArray<object>} ledger active or historical entries.
 * @param {readonly string[]} [blocked] phrases that invalidate an entry.
 * @returns {string}
 */
export function ledgerSentences(ledger, blocked = []) {
  const active = (ledger ?? [])
    .filter((entry) => (entry.status ?? 'active') === 'active' && !blockedBy(entry.text, blocked))
    .sort((a, b) => (RANK[b.kind] ?? 0) - (RANK[a.kind] ?? 0) ||
      (a.seq ?? a.order ?? 0) - (b.seq ?? b.order ?? 0) ||
      String(a.id ?? '').localeCompare(String(b.id ?? '')))
  const sentences = []
  const seen = new Set()
  for (const entry of active) {
    if (seen.has(entry.text)) continue
    seen.add(entry.text)
    sentences.push(`${LABELS[entry.kind] ?? 'Context'}: ${dropPeriod(entry.text)}.`)
  }
  return sentences.join(' ')
}

/**
 * One line per current ledger entry, for the denoised rendering.
 *
 * Same rank order as `ledgerSentences`, but each claim stays on its own line
 * and the duplicated kind label / literal escapes are cleaned first.
 *
 * @param {ReadonlyArray<object>} ledger entries after version folding.
 * @param {readonly string[]} [blocked] phrases that invalidate an entry.
 * @returns {string[]}
 */
export function ledgerLines(ledger, blocked = []) {
  const active = (ledger ?? [])
    .filter((entry) => (entry.status ?? 'active') === 'active' && !blockedBy(entry.text, blocked))
    .sort((a, b) => (RANK[b.kind] ?? 0) - (RANK[a.kind] ?? 0) ||
      (a.seq ?? a.order ?? 0) - (b.seq ?? b.order ?? 0) ||
      String(a.id ?? '').localeCompare(String(b.id ?? '')))
  const lines = []
  const seen = new Set()
  for (const entry of active) {
    const text = cleanEntryText(entry.text)
    if (text === '' || seen.has(text)) continue
    seen.add(text)
    lines.push(`${LABELS[entry.kind] ?? 'Context'}: ${dropPeriod(text)}.`)
  }
  return lines
}

/** @param {object} state @param {readonly string[]} [blocked] @param {readonly string[]} [skip] */
export function stateText(state, blocked = [], skip = []) {
  if (state === null || typeof state !== 'object') return ''
  const parts = []
  for (const key of STATE_KEYS) {
    if (skip.includes(key)) continue
    const rows = (Array.isArray(state[key]) ? state[key] : []).filter((row) => !blockedBy(row, blocked))
    if (rows.length > 0) parts.push(`${key}: ${dropPeriod(rows.join('; '))}`)
  }
  return parts.length > 0 ? `State: ${parts.join('. ')}.` : ''
}

/** A recorded next action gets its own line, not a clause inside State. */
export function nextText(state, blocked = []) {
  const rows = (Array.isArray(state?.next) ? state.next : []).filter((row) => !blockedBy(row, blocked))
  if (rows.length === 0) return ''
  let row = rows.join('; ')
  const suffix = ' (assistant-originated)'
  if (row.replace(/\.+$/, '').endsWith(suffix)) {
    row = row.replace(/\.+$/, '').slice(0, -suffix.length)
    return `Next action (recorded by assistant): ${dropPeriod(row)}.`
  }
  return `Next action (recorded): ${dropPeriod(row)}.`
}

/**
 * One sentence per mechanical receipt, newest four.
 *
 * @param {ReadonlyArray<object>} receipts receipt rows in edit order.
 * @param {readonly string[]} [represented] state rows that already state a check.
 * @returns {string}
 */
export function receiptsText(receipts, represented = []) {
  const sentences = []
  for (const receipt of (receipts ?? []).slice(-4)) {
    if (represented.some((row) => String(row).includes(receipt.path) &&
      String(row).includes(`#${receipt.check}`))) continue
    if (receipt.check === null || receipt.check === undefined) {
      sentences.push(`${receipt.path} was edited at #${receipt.edit} ` +
        'and no later check covers it.')
      continue
    }
    let sentence = `${receipt.path} was edited at #${receipt.edit}; the check at ` +
      `#${receipt.check} (${receipt.command}) reported: ${dropPeriod(receipt.result)}.`
    if (receipt.stale === true) {
      sentence += ' A later edit to the same file is not covered by that check.'
    }
    sentences.push(sentence)
  }
  return sentences.length > 0 ? `Checks: ${sentences.join(' ')}` : ''
}

const distinctTerms = (terms, label, limit) => {
  const lowered = String(label ?? '').toLowerCase()
  const extra = [...new Set((terms ?? [])
    .filter((term) => !lowered.includes(String(term).toLowerCase())))]
    .filter((term) => ![...new Set((terms ?? []))]
      .some((other) => other !== term && String(other).toLowerCase().includes(String(term).toLowerCase())))
  return extra.slice(0, limit).map((term) => String(term).slice(0, 32))
}

/**
 * Engine-owned exact values, newest first; archived keys stay addressable.
 *
 * @param {ReadonlyArray<object>} values value rows in event order.
 * @param {readonly string[]} [blocked]
 * @param {number} [shown] newest rows to render; default all.
 * @returns {string}
 */
export function valuesText(values, blocked = [], shown = undefined) {
  const ordered = [...(values ?? [])]
    .filter((row) => !blockedBy(row.text, blocked))
    .reverse()
  const total = ordered.length
  const keep = shown === undefined ? total : Math.max(0, Math.min(shown, total))
  const lines = []
  for (const row of ordered.slice(0, keep)) {
    const extra = distinctTerms(row.terms, row.label, 6)
    const terms = extra.length > 0 ? ` | terms: ${extra.join(', ')}` : ''
    lines.push(`[${row.key}] ${row.label}${terms} (read_evidence #${row.seq})`)
  }
  if (lines.length === 0) {
    if (total === 0) return ''
    const keys = ordered.map((row) => row.key)
    return `Observed values archived: fetch ${listKeys(keys)}.`
  }
  let text = `Observed values (fetch by key): ${lines.join('; ')}.`
  if (total > keep) {
    const keys = ordered.slice(keep).map((row) => row.key)
    text += ` ${total - keep} older values archived: fetch ${listKeys(keys)}.`
  }
  return text
}

const listKeys = (keys) => (keys.length <= 10 ? keys.join(', ')
  : `${keys[0]}..${keys[keys.length - 1]}`)

/**
 * Keep the newest control messages verbatim under a byte cap.
 *
 * Long sessions accumulate one quoted user request per round; because control
 * is mandatory, the quotes would otherwise crowd the ledger and values out of
 * the checkpoint. The cut is disclosed and the oldest whole messages go first,
 * so what remains is still verbatim.
 *
 * @param {readonly string[]} texts control messages in order.
 * @param {number} maxBytes 0 or negative keeps everything.
 * @returns {{ texts: string[], omitted: number }}
 */
export function windowControl(texts, maxBytes) {
  if (!(maxBytes > 0) || texts.length === 0) return { texts: [...texts], omitted: 0 }
  const kept = []
  let total = 0
  for (let index = texts.length - 1; index >= 0; index -= 1) {
    const size = byteLength(texts[index]) + 3
    if (kept.length > 0 && total + size > maxBytes) break
    kept.unshift(texts[index])
    total += size
  }
  return { texts: kept, omitted: texts.length - kept.length }
}

/**
 * Discovery index over the shadowed region, one line per source.
 *
 * @param {ReadonlyArray<object>} index index rows in event order.
 * @param {readonly string[]} [blocked]
 * @param {number} [dropped] sources without an index slot.
 * @returns {string}
 */
export function indexText(index, blocked = [], dropped = 0) {
  const rows = (index ?? []).filter((row) => !blockedBy(row.text, blocked))
  if (rows.length === 0) return ''
  const lines = rows.map((row) => {
    const extra = distinctTerms(row.terms, row.label, row.kind === 'value' ? 6 : 2)
    const terms = extra.length > 0 ? ` | terms: ${extra.join(', ')}` : ''
    return `[${row.key}] ${row.label}${terms} (${row.tool === 'read_history' ? 'read_history' : 'read_evidence'} #${row.seq})`
  })
  let text = `Evidence index (fetch by key): ${lines.join('; ')}.`
  if (dropped > 0) text += ` ${dropped} further sources are archived without an index slot.`
  return text
}

/**
 * Compose the passage and trim it to the byte budget.
 *
 * @param {{ control?: readonly string[], commandState?: string, board?: string, ledger?: readonly object[],
 *   state?: object, receipts?: readonly object[], index?: readonly object[],
 *   values?: readonly object[], budget: number, blocked?: readonly string[],
 *   dropped?: number, nextBanner?: boolean, recent?: string, latestControl?: string }} options
 * @returns {string}
 */
export function renderPassage(options) {
  const budget = Math.max(0, options.budget ?? 0)
  const control = [...new Set((options.control ?? []).filter((text) => text))].map(String)
  const capped = capLedger(options.ledger, options.ledgerMaxBytes ?? 0,
    { valueFirst: options.bullets === true })
  const ledger = capped.entries
  const index = Array.isArray(options.index) ? [...options.index] : []
  const values = Array.isArray(options.values) ? [...options.values] : []
  const blocked = [...(options.blocked ?? [])]
  const nextBanner = options.nextBanner === true
  let shownValues = values.filter((row) => !blockedBy(row.text, blocked)).length

  const controlOmitted = Math.max(0, options.controlOmitted ?? 0)
  const latest = typeof options.latestControl === 'string' ? options.latestControl.trim() : ''
  // A long verbatim list buries its newest item. Restate the latest request
  // once at the top; it is the instruction a resuming model must satisfy.
  const commandText = typeof options.commandState === 'string' ? options.commandState.trim() : ''
  const latestText = latest !== '' && (control.length > 4 || commandText !== '')
    ? `Latest request: "${latest.length > 240 ? `${latest.slice(0, 237)}...` : latest}"`
    : ''
  const controlText = control.length > 0
    ? (options.numbered === true
        ? `User requirements (verbatim, in order):\n${control.map((text, index) => `${index + 1}. "${text}"`).join('\n')}` +
          (controlOmitted > 0
            ? `\n${controlOmitted} earlier requests omitted; later instructions and the ledger carry their state.`
            : '')
        : `User requirements, quoted verbatim: ${control.map((text) => `"${text}"`).join(' ')}.` +
          (controlOmitted > 0
            ? ` ${controlOmitted} earlier requests omitted; later instructions and the ledger carry their state.`
            : ''))
    : commandText
  const recentText = typeof options.recent === 'string' && options.recent !== ''
    ? `## Recent changes\n${options.recent}`
    : ''

  const stateRows = options.state
    ? Object.values(options.state).flat().map(String)
    : []

  // The state paragraph is either the engine-rendered DSH block (a caller that
  // must publish a parseable checkpoint state hands us the exact text) or the
  // reference's `State: done: …` sentence.
  const stateParagraph = typeof options.stateBlock === 'string' && options.stateBlock !== ''
    ? options.stateBlock
    : options.state ? stateText(options.state, blocked, nextBanner ? ['next'] : []) : ''

  const ledgerSection = () => {
    const notes = [
      capped.omitted > 0 ? `${capped.omitted} lower-priority ledger entries omitted; ask for their source.` : '',
      (options.superseded ?? 0) > 0
        ? `${options.superseded} older versions folded into the current state; their sources stay in the journal.`
        : '',
    ].filter((note) => note !== '').join(' ')
    if (options.bullets === true) {
      const lines = ledgerLines(ledger, blocked)
      if (lines.length === 0) return ''
      return `Ledger (current):\n${lines.map((line) => `- ${line}`).join('\n')}` +
        (notes === '' ? '' : `\n${notes}`)
    }
    const sentences = ledgerSentences(ledger, blocked)
    if (sentences === '') return ''
    return `Ledger (current): ${sentences}` + (notes === '' ? '' : ` ${notes}`)
  }
  const build = () => {
    return [
      latestText,
      controlText,
      typeof options.board === 'string' ? options.board : '',
      ledgerSection(),
      nextBanner ? nextText(options.state, blocked) : '',
      stateParagraph,
      typeof options.errorPin === 'string' ? options.errorPin : '',
      typeof options.workingSet === 'string' ? options.workingSet : '',
      recentText,
      receiptsText(options.receipts, stateRows),
      valuesText(values, blocked, shownValues),
      indexText(index, blocked, options.dropped ?? 0),
    ].filter((part) => part !== '').join('\n\n')
  }

  let text = build()
  while (byteLength(text) > budget && index.length > 0) {
    index.pop()
    text = build()
  }
  while (byteLength(text) > budget && shownValues > 0) {
    shownValues -= 1
    text = build()
  }
  while (byteLength(text) > budget) {
    const active = ledger.filter((entry) => (entry.status ?? 'active') === 'active')
    if (active.length <= 1) break
    let worst = -1
    let worstRank = Infinity
    ledger.forEach((entry, position) => {
      if ((entry.status ?? 'active') !== 'active') return
      const rank = RANK[entry.kind] ?? 0
      if (rank < worstRank) {
        worstRank = rank
        worst = position
      }
    })
    if (worst === -1) break
    ledger.splice(worst, 1)
    text = build()
  }
  return text
}
