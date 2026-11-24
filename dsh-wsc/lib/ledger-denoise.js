/**
 * Deterministic ledger denoise: render accumulated entries as the current
 * state, not as an append-only changelog.
 *
 * The journal keeps every entry. Before rendering (and before the byte cap),
 * entries that describe the same subject are folded to the newest one, and a
 * run of test-count observations is folded to the latest result. That removes
 * the stale-version residue that used to fill the cap and push unique facts
 * out, without a model call and without changing any retained text.
 */

const PATH = /((?:[A-Za-z0-9_.-]+[\\/])?[A-Za-z0-9_.-]+\.(?:[cm]?[jt]sx?|py|json|md|ya?ml))(?::|\b)/
// A statement has to name a changeable property; plain prose is never folded.
const STATE_WORD = /(?:=|\b(?:returns|throws|default|defaults|header|options|slice|slices|sort|sorts|applies|uses|takes|wraps|prints|documents|suppresses|overrides|counts|exports|accepts|rejects|requires|validates|emits|appends|maps|keeps|removes)\b)/i
const TEST_RESULT = /\b(?:passes? \d+\s*\/\s*\d+|tests?\s+\d+\s*,\s*pass|tests?:\s*\d+ tests?, \s*\d+ pass|\d+ tests?, \s*pass \d+)/i
// The sandbox's spawn failure is stated once; every later copy is noise.
const TEST_ENV = /spawn EPERM|errno = -4048|syscall = spawn|test-isolation=none.*EPERM/i
const EXEMPT_KINDS = new Set(['constraint', 'requirement'])
const TEST_KEY = '__test_result__'
const ENV_KEY = '__test_environment__'

const normalizePath = (value) => String(value ?? '').toLowerCase().replace(/\\/g, '/')
// `REPORT_LIMIT` and `reportLimit` name the same subject.
const normalizeName = (value) => String(value ?? '').toLowerCase().replace(/_/g, '')
const clock = (entry) => Number(entry?.seq ?? entry?.order ?? 0)
const stripPrefix = (text) => String(text ?? '')
  .replace(/^(?:decision|context|constraint|requirement|verification):\s*/i, '')
  .trim()

/**
 * Stable subject key, or '' when the entry must not be folded.
 *
 * The key is path (or function call) plus the first identifier and any
 * `--flag` tokens. Flags keep `parseArgs throws '--round'` and
 * `parseArgs throws '--sort'` apart; property names merge their versions.
 */
export function subjectKey(text) {
  const t = stripPrefix(text)
  if (t === '' || !STATE_WORD.test(t)) return ''
  const flags = [...new Set((t.match(/--[a-z][a-z-]+/g) ?? []))].sort().join(' ')
  // Two calls with different literal arguments are different facts
  // (`formatCents(-350)` vs `formatCents(123456789)`), and an empty-argument
  // call is its own case (`toCsv([])`).
  const argText = /\(([^)]*)\)/.exec(t)?.[1] ?? ''
  const numeric = /\d/.test(argText) ? `::#${(argText.match(/-?\d+(?:\.\d+)?/) ?? [''])[0]}` : ''
  const empty = /\(/.test(t) && /^[[\]\s]*$/.test(argText) ? '::empty' : ''
  const suffix = `${flags === '' ? '' : `::${flags}`}${numeric}${empty}`
  const path = PATH.exec(t)?.[1]
  if (path !== undefined) {
    const rest = t.slice(t.indexOf(path) + path.length)
    const first = /[A-Za-z_$][A-Za-z0-9_$]*/.exec(rest)?.[0]
    if (first === undefined) return ''
    return `${normalizePath(path)}::${normalizeName(first)}${suffix}`
  }
  // Do not require a closing paren: signatures that contain a nested call
  // (`taxCents(cents, rate = envTaxRate())`) still fold by function name.
  const call = /([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^\n]{0,160})/.exec(t)
  if (call === null) return ''
  const seen = new Set()
  const args = String(call[2]).match(/[A-Za-z_$][A-Za-z0-9_$]*/g) ?? []
  for (const name of args) {
    const lower = name.toLowerCase()
    if (['default', 'options', 'args', 'value', 'text'].includes(lower)) continue
    seen.add(lower)
    if (seen.size >= 2) break
  }
  return `fn:${normalizeName(call[1])}(${[...seen].map(normalizeName).join(',')})${suffix}`
}

/**
 * A claim that carries a probe-able value: a decimal, a flag, a quoted
 * literal or a return shape. The cap keeps these before plain prose.
 */
export function hasValue(text) {
  return /\b\d+\.\d+\b|--[a-z][a-z-]+|`[^`]{2,}`|\breturns?\b/i.test(String(text ?? ''))
}

/**
 * @param {ReadonlyArray<object>} entries journal entries (any status).
 * @returns {{ entries: object[], superseded: number, folded: number }}
 */
export function denoiseLedger(entries) {
  const active = (entries ?? []).filter((entry) => (entry.status ?? 'active') === 'active')
  const groups = new Map()
  const kept = []
  for (const entry of active) {
    if (EXEMPT_KINDS.has(entry.kind)) {
      kept.push(entry)
      continue
    }
    const text = String(entry.text ?? '')
    const plain = stripPrefix(text)
    const key = TEST_RESULT.test(plain) ? TEST_KEY : TEST_ENV.test(plain) ? ENV_KEY : subjectKey(text)
    if (key === '') {
      kept.push(entry)
      continue
    }
    const list = groups.get(key)
    if (list === undefined) groups.set(key, [entry])
    else list.push(entry)
  }
  let superseded = 0
  let folded = 0
  for (const [key, list] of groups) {
    if (list.length === 1) {
      kept.push(list[0])
      continue
    }
    list.sort((a, b) => clock(a) - clock(b) || String(a.id ?? '').localeCompare(String(b.id ?? '')))
    kept.push(list[list.length - 1])
    superseded += list.length - 1
    if (key === TEST_KEY) folded += list.length - 1
  }
  kept.sort((a, b) => clock(a) - clock(b) || String(a.id ?? '').localeCompare(String(b.id ?? '')))
  return { entries: kept, superseded, folded }
}

/** Strip a duplicated kind label and flatten literal escapes for display. */
export function cleanEntryText(text) {
  // Real line breaks become a separator; a literal `\n` is code content and
  // stays untouched.
  return stripPrefix(text)
    .replace(/[\r\n]+/g, ' / ')
    .replace(/[ \t]+/g, ' ')
    .trim()
}
