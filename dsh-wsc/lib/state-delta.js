/**
 * Identity-level delta since a previous presentation, ported from XENYON
 * `wsc/state_delta.py`.
 *
 * An identity whose current revision differs from the one last presented is
 * revised; an identity absent before is added; a previously presented identity
 * with no current entry is expired. Refs are identities, never parsed as paths.
 */
import { currentEntries } from './state-view.js'

const identity = ref => ref.slice(0, ref.lastIndexOf('@'))

/**
 * @param {string[]} previousRefs refs presented by the last installed view.
 * @param {object[]} records journal rows (any revisions).
 * @param {object[]} sources the prefix rows.
 * @returns {{ added: string[], revised: {ref: string, previous: string}[], expired: string[] }}
 */
export function stateDelta(previousRefs, records, sources) {
  const current = currentEntries(records, sources)
  const currentById = new Map(current.map(record => [identity(record.ref), record]))
  const previousById = new Map(previousRefs.map(ref => [identity(ref), ref]))
  const added = []
  const revised = []
  const expired = []
  for (const [id, record] of currentById) {
    if (!previousById.has(id)) added.push(record.ref)
    else if (previousById.get(id) !== record.ref) revised.push({ ref: record.ref, previous: previousById.get(id) })
  }
  for (const [id, ref] of previousById) {
    if (!currentById.has(id)) expired.push(ref)
  }
  return { added, revised, expired }
}