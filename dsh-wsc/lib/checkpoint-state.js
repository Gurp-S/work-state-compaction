import { byteLength } from './bytes.js'

const FIELDS = ['done', 'open', 'next', 'unknown']
export const CURRENT_STATE_HEADING = '## Current state (model account; unverified)'

export function parseCheckpointState(value) {
  if (!value || typeof value !== 'object' || Object.keys(value).length !== FIELDS.length) return null
  const state = {}
  for (const key of FIELDS) {
    const rows = value[key]
    if (!Array.isArray(rows) || rows.length > 6 ||
        rows.some(row => typeof row !== 'string' || !row.trim() || /[\r\n]/.test(row))) return null
    state[key] = rows.map(row => row.trim())
  }
  if (state.open.length && !state.next.length) return null
  return FIELDS.some(key => state[key].length) ? state : null
}

export function mechanicalCheckpointState(prior = '') {
  const unknown = prior.trim().replace(/\s+/g, ' ')
  return { done: [], open: [], next: [], unknown: [
    unknown ? `Prior model account: ${unknown}` : 'No verified work state recorded in this region.',
  ] }
}

const PRIOR_SCOPE = 'Previous handoff state. Current applicability unverified.'
const PRIOR_OPEN = 'Previous open item; no transition in current account: '

function priorOpenItem(note) {
  const row = note.startsWith(`${PRIOR_SCOPE} `) ? note.slice(PRIOR_SCOPE.length + 1) : note
  return row.startsWith(PRIOR_OPEN) ? row.slice(PRIOR_OPEN.length) : null
}

export function carryCheckpointState(value) {
  const state = parseCheckpointState(value)
  if (!state) return null
  if (state.unknown[0]?.startsWith(PRIOR_SCOPE)) return state
  const [first, ...rest] = state.unknown
  state.unknown = [first ? `${PRIOR_SCOPE} ${first}` : PRIOR_SCOPE, ...rest]
  return state
}

export function preservePriorOpenScope(fresh, previous) {
  const state = parseCheckpointState(fresh)
  if (!state || !previous) return state
  const priorOpen = [...previous.open, ...previous.unknown.map(priorOpenItem).filter(Boolean)]
  const notes = priorOpen.filter(item => !state.open.includes(item)).map(item => `${PRIOR_OPEN}${item}`)
  const unknown = [...new Set([...state.unknown, ...notes])]
  return parseCheckpointState({ ...state, unknown })
}

export function fitCheckpointState(state, budget) {
  const fits = candidate => byteLength(renderCheckpointState(candidate)) <= budget
  if (fits(state)) return state
  const scope = state.unknown[0]?.startsWith(PRIOR_SCOPE) ? `${PRIOR_SCOPE} ` : ''
  const unresolved = state.unknown.filter(note => priorOpenItem(note) !== null)
  const packed = { done: [], open: [...state.open], next: [...state.next],
    unknown: [`${scope}Some state entries omitted due to checkpoint budget.`, ...unresolved] }
  if (packed.unknown.length > 6) return null
  if (!fits(packed)) return null
  for (const field of ['unknown', 'done']) {
    for (const entry of state[field]) {
      if (packed[field].length >= 6) break
      if (packed[field].includes(entry)) continue
      const next = { ...packed, [field]: [...packed[field], entry] }
      if (fits(next)) packed[field].push(entry)
    }
  }
  return packed
}

export function renderCheckpointState(state) {
  const items = (key, label) => state[key].map(row => `- ${label}: ${row}`)
  return [
    CURRENT_STATE_HEADING, ...items('done', 'Done'),
    '## Next step', ...items('next', 'Next'),
    '## Open / Unknown', ...items('open', 'Open'), ...items('unknown', 'Unknown'),
  ].join('\n')
}

/** Recognize the contiguous, engine-rendered state block of a prior handoff. */
export function readCheckpointState(text) {
  if (typeof text !== 'string') return null
  const lines = text.split(/\r?\n/)
  const start = lines.indexOf(CURRENT_STATE_HEADING)
  if (start < 0) return null
  const state = { done: [], open: [], next: [], unknown: [] }
  let at = start + 1
  const take = (key, label) => {
    const prefix = `- ${label}: `
    while (lines[at]?.startsWith(prefix)) state[key].push(lines[at++].slice(prefix.length))
  }
  take('done', 'Done')
  if (lines[at++] !== '## Next step') return null
  take('next', 'Next')
  if (lines[at++] !== '## Open / Unknown') return null
  take('open', 'Open')
  take('unknown', 'Unknown')
  return !lines[at] || lines[at].startsWith('## ') ? parseCheckpointState(state) : null
}

export function assertCheckpointState(checkpoint) {
  const state = parseCheckpointState(checkpoint?.state)
  if (!state) throw new Error('wsc: state_required')
  const published = checkpointStateFromSummary(checkpoint.summary)
  if (!published || renderCheckpointState(state) !== renderCheckpointState(published)) {
    throw new Error('wsc: state_required')
  }
}

export function checkpointStateFromSummary(summary) {
  const rendered = Array.isArray(summary) ? summary.find(block => block?.type === 'text')?.text : undefined
  return readCheckpointState(rendered)
}
