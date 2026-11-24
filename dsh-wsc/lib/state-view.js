/**
 * Current-state projection, ported from XENYON `wsc/state_view.py`.
 *
 * Which ledger entries are still applicable at a cut. Validity is mechanical,
 * driven by the entry's own source pointers: a file_changed condition fires on
 * any write/edit call to that path whose event seq is newer than the newest
 * source the entry cites. An entry citing no source is conservatively
 * invalidated by any matching call in the prefix. validUntil is compared
 * against the newest observation time in the prefix, never a wall clock.
 *
 * A source row is { id, seq, observedAt, kind, calls }: kind is
 * 'call' | 'message' | 'result'; calls lists the tool calls the event carried
 * as { name, path }, and a row without calls may carry flat name/path instead.
 */
import { STATE_FIELDS } from './understanding.js'

const INVALID_WHEN_KEYS = ['file_changed']
const EDIT_NAMES = ['write', 'edit']

/** @param {object[]} sources @returns {string|null} */
export function latestObservedAt(sources) {
  const times = sources.map(row => row.observedAt).filter(Boolean)
  return times.length ? times.reduce((a, b) => (a > b ? a : b)) : null
}

/** @param {object} entry @param {Map<string, object>} byId @returns {number} */
function entrySeq(entry, byId) {
  const seqs = entry.sources.map(id => byId.get(id)?.seq).filter(seq => seq !== undefined)
  return seqs.length ? Math.max(...seqs) : -1
}

/**
 * @param {object} entry a normalized ledger record.
 * @param {object[]} sources the prefix rows.
 * @param {string|null} now newest observation time in the prefix.
 * @param {Map<string, object>} [byId]
 * @returns {boolean}
 */
export function entryExpired(entry, sources, now, byId = new Map(sources.map(row => [row.id, row]))) {
  if (entry.status !== 'active') return true
  if (entry.validUntil && now && entry.validUntil <= now) return true
  const conditions = entry.invalidWhen ?? {}
  for (const key of Object.keys(conditions)) {
    if (!INVALID_WHEN_KEYS.includes(key)) throw new Error('unsupported_invalid_when')
  }
  if (Object.keys(conditions).length === 0) return false
  const anchor = entrySeq(entry, byId)
  for (const row of sources) {
    if (row.kind !== 'call' || row.seq <= anchor) continue
    const calls = Array.isArray(row.calls) ? row.calls : [{ name: row.name, path: row.path }]
    for (const call of calls) {
      if (EDIT_NAMES.includes(call.name) && call.path != null && conditions.file_changed === call.path) return true
    }
  }
  return false
}

/**
 * The ledger's current state: the head revision of each identity that is not
 * expired. Older revisions stay readable as history but are never current.
 *
 * @param {object[]} records journal rows (any revisions).
 * @param {object[]} sources the prefix rows.
 * @returns {object[]} current entries.
 */
export function currentEntries(records, sources) {
  const heads = new Map()
  for (const raw of records) {
    const record = { ...STATE_FIELDS, ...raw }
    const head = heads.get(record.id)
    if (head === undefined || record.revision > head.revision) heads.set(record.id, record)
  }
  const now = latestObservedAt(sources)
  const byId = new Map(sources.map(row => [row.id, row]))
  return [...heads.values()].filter(record => !entryExpired(record, sources, now, byId))
}