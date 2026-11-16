/**
 * Read one session event by sequence number.
 *
 * Harness builds differ in how a Session exposes its append-only log: some
 * carry an `eventAt(seq)` accessor, others expose an `events` or `eventsSnapshot`
 * array. Reading both shapes here keeps the engine independent of which build
 * hosts it.
 *
 * @param {{ eventAt?: (seq: number) => object|undefined, events?: object[], eventsSnapshot?: object[] }} session
 * @param {number} seq event sequence number.
 * @returns {object|undefined} the event, or `undefined` when the log has no such seq.
 */
export function eventAt(session, seq) {
  if (typeof session?.eventAt === 'function') return session.eventAt(seq)
  const events = Array.isArray(session?.eventsSnapshot) ? session.eventsSnapshot : session?.events
  if (!Array.isArray(events)) return undefined
  return events[seq]?.seq === seq ? events[seq] : events.find((event) => event.seq === seq)
}
