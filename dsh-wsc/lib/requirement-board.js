/**
 * Mechanical coverage of the verbatim user requests.
 *
 * A request is covered when a recorded edit addressed its file path or one of
 * its identifying literals after the request was stated. This is evidence, not
 * a work judgement: a request with no recorded edit may still be complete in a
 * region the engine has not compacted yet, so the block says "no recorded edit"
 * instead of claiming the work is open.
 */
import { significantTerms } from './state.js'

const FILE_PATH = /[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|cjs|ts|tsx|json|md|yml|yaml|txt|toml)/g
const BARE_FILE = /\b(README|CHANGELOG)\b/g
const FLAG = /--[a-z][a-z0-9-]+/g
const WORK_VERB = /\b(?:add|change|update|fix|implement|refactor|remove|rename|create|write|wire|make|use|set|limit|support|sort|validate|export|replace)\b/i
// "Do not change files" is a constraint on the work, not work of its own.
const NEGATED_EDIT = /\b(?:do not|don't|without)\s+(?:change|modify|edit)\b/gi

const pathLike = (term) => /[\\/]/.test(term) || /\.[a-z0-9]{1,5}$/i.test(term)
const normalizeTerm = (term) => String(term)
  .replace(/^--/, '')
  .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
  .toLowerCase()
  .replace(/[^a-z0-9-]/g, '')
const slash = (value) => String(value ?? '').replace(/\\/g, '/').toLowerCase()
const samePath = (left, right) => {
  const a = slash(left)
  const b = slash(right)
  return a !== '' && b !== '' && (a === b || a.endsWith(`/${b}`) || b.endsWith(`/${a}`))
}

const requestTerms = (text) => {
  const raw = [...significantTerms(text), ...(String(text).match(FLAG) ?? [])]
    .filter((term) => !pathLike(term))
    .map(normalizeTerm)
    .filter((term) => term.length >= 3)
  return [...new Set(raw)]
}
const requestPaths = (text) => [
  ...(String(text).match(FILE_PATH) ?? []),
  ...[...(String(text).match(BARE_FILE) ?? [])].map((name) => `${name}.md`),
]

const covers = (receipt, request) => {
  if (!Number.isInteger(receipt?.edit)) return false
  if (Number.isInteger(request.seq) && receipt.edit <= request.seq) return false
  if (request.paths.some((path) => samePath(path, receipt.path))) return true
  const recorded = (receipt.terms ?? []).map(normalizeTerm)
  return request.terms.some((term) => recorded.includes(term))
}

/**
 * @param {Array<{ text: string, seq?: number | null }>} controls requests in
 *   the order the checkpoint quotes them.
 * @param {Array<{ path?: string, edit?: number, check?: number | null, terms?: string[] }>} receipts
 *   durable rows from the journal (edit/check are session seqs when the latch
 *   is on).
 * @returns {{ total: number, covered: number, checked: number, missing: number[] }}
 */
export function requirementBoard(controls, receipts) {
  const requests = []
  for (const [index, control] of (controls ?? []).entries()) {
    const text = String(control?.text ?? control ?? '')
    if (!WORK_VERB.test(text.replace(NEGATED_EDIT, ''))) continue
    requests.push({
      number: index + 1,
      seq: Number.isInteger(control?.seq) ? control.seq : null,
      terms: requestTerms(text),
      paths: requestPaths(text),
    })
  }
  const hits = requests.map((request) => ({
    request,
    found: (receipts ?? []).filter((receipt) => covers(receipt, request)),
  }))
  const covered = hits.filter((row) => row.found.length > 0)
  return {
    total: requests.length,
    covered: covered.length,
    checked: covered.filter((row) => row.found.some((receipt) => Number.isInteger(receipt.check))).length,
    missing: hits.filter((row) => row.found.length === 0).map((row) => row.request.number),
  }
}

/** @param {{ total: number, covered: number, checked: number, missing: number[] }} summary */
export function requirementBoardText(summary) {
  if (summary.total === 0 || summary.covered === 0) return ''
  const checked = summary.checked === summary.covered
    ? 'each with a later check'
    : `${summary.checked} with a later check`
  const missing = summary.missing.length > 0
    ? ` No recorded edit yet: ${summary.missing.map((number) => `#${number}`).join(', ')}.`
    : ''
  return `## Requirement coverage (mechanical)\n` +
    `${summary.covered}/${summary.total} work requests have an edit recorded after they were stated, ` +
    `${checked}.${missing}`
}
