import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { UnderstandingStore, STATUSES } from '../lib/understanding.js'
import { currentEntries, entryExpired, latestObservedAt } from '../lib/state-view.js'
import { stateDelta } from '../lib/state-delta.js'
import { buildSelectiveCheckpoint } from '../lib/checkpoint.js'

const text = (value) => [{ type: 'text', text: value }]

const store = () => new UnderstandingStore({ file: join(mkdtempSync(join(tmpdir(), 'wsc-state-')), 'u.jsonl') })

const TIMES = ['2026-11-17T01:00:00Z', '2026-11-17T02:00:00Z', '2026-11-17T03:00:00Z',
  '2026-11-17T04:00:00Z', '2026-11-17T05:00:00Z']

// m1 user task, m2 assistant observation, c1 edit call, r1 its result, m3 later observation.
const sources = [
  { id: 'm1', seq: 0, observedAt: TIMES[0], kind: 'message' },
  { id: 'm2', seq: 1, observedAt: TIMES[1], kind: 'message' },
  { id: 'c1', seq: 2, observedAt: TIMES[2], kind: 'call', name: 'edit', path: 'a.py' },
  { id: 'r1', seq: 3, observedAt: TIMES[3], kind: 'result' },
  { id: 'm3', seq: 4, observedAt: TIMES[4], kind: 'message' },
]

test('state fields: a write carries status and timeliness with active defaults', () => {
  const s = store()
  const record = s.write({ text: 'V2 checked after edit', kind: 'verification', sources: ['m3'], observedAt: TIMES[4] }, { producer: 'p' })
  assert.equal(record.status, 'active')
  assert.equal(record.observedAt, TIMES[4])
  assert.equal(record.validUntil, null)
  assert.equal(record.invalidWhen, null)
  assert.deepEqual(STATUSES, ['active', 'superseded', 'invalidated'])
  assert.throws(() => s.write({ text: 'x', kind: 'fact', status: 'stale' }, { producer: 'p' }), /understanding_status_invalid/)
  assert.throws(() => s.write({ text: 'x', kind: 'fact', invalidWhen: 'a.py' }, { producer: 'p' }), /invalid_understanding_invalid_when/)
  assert.throws(() => s.write({ text: 'x', kind: 'fact', validUntil: '  ' }, { producer: 'p' }), /understanding_time_invalid/)
})

test('state fields: journals predating the state fields replay with defaults', () => {
  const s = store()
  const record = s.write({ text: 'old row', kind: 'fact', sources: ['m1'] }, { producer: 'p' })
  const { status, observedAt, validUntil, invalidWhen, ...legacy } = record
  const file = join(mkdtempSync(join(tmpdir(), 'wsc-legacy-')), 'u.jsonl')
  writeFileSync(file, `${JSON.stringify(legacy)}\n`)
  const reloaded = new UnderstandingStore({ file })
  assert.deepEqual(reloaded.all(), [record])
})

test('current entries: head revision per identity, expired entries never current', () => {
  const s = store()
  const stale = s.write({ text: 'V1 passed', kind: 'verification', sources: ['m2'], observedAt: TIMES[1], invalidWhen: { file_changed: 'a.py' } }, { producer: 'p' })
  const fresh = s.write({ text: 'V2 checked', kind: 'verification', sources: ['m3'], observedAt: TIMES[4] }, { producer: 'p' })
  const current = currentEntries(s.all(), sources)
  assert.deepEqual(current.map(r => r.ref), [fresh.ref])
  assert.equal(entryExpired(stale, sources, latestObservedAt(sources)), true)
  const revised = s.write({ id: fresh.id, text: 'V2 rechecked', kind: 'verification', sources: ['m3'], expectedRevision: 1 }, { producer: 'p' })
  assert.deepEqual(currentEntries(s.all(), sources).map(r => r.ref), [revised.ref])
})

test('current entries: validUntil is judged against the newest observation, not a wall clock', () => {
  const s = store()
  const timed = s.write({ text: 'deadline bound', kind: 'fact', sources: ['m1'], validUntil: TIMES[3] }, { producer: 'p' })
  assert.equal(entryExpired(timed, sources, latestObservedAt(sources)), true)
  assert.equal(entryExpired(timed, sources.slice(0, 2), latestObservedAt(sources.slice(0, 2))), false)
  const invalidated = s.write({ text: 'retired', kind: 'fact', sources: ['m1'], status: 'invalidated' }, { producer: 'p' })
  assert.equal(entryExpired(invalidated, sources, null), true)
})

test('current entries: an entry citing no source is invalidated by any matching edit', () => {
  const s = store()
  const unbound = s.write({ text: 'a.py is broken', kind: 'hypothesis', sources: [], invalidWhen: { file_changed: 'a.py' } }, { producer: 'p' })
  assert.equal(entryExpired(unbound, sources, null), true)
  assert.equal(entryExpired(unbound, sources.slice(0, 2), null), false)
  assert.throws(() => entryExpired({ ...unbound, invalidWhen: { mood_changed: 'x' } }, sources, null), /unsupported_invalid_when/)
})

test('delta: added, revised and expired identities since the last presentation', () => {  const s = store()
  const first = s.write({ text: 'v1', kind: 'fact', sources: ['m1'] }, { producer: 'p' })
  const other = s.write({ text: 'other', kind: 'fact', sources: ['m2'] }, { producer: 'p' })
  assert.deepEqual(stateDelta([first.ref, other.ref], s.all(), sources), { added: [], revised: [], expired: [] })
  const second = s.write({ id: first.id, text: 'v2', kind: 'fact', sources: ['m1'], expectedRevision: 1 }, { producer: 'p' })
  s.write({ id: other.id, text: 'retired', kind: 'fact', sources: ['m2'], expectedRevision: 1, status: 'invalidated' }, { producer: 'p' })
  const fresh = s.write({ text: 'new', kind: 'fact', sources: ['m3'] }, { producer: 'p' })
  assert.deepEqual(stateDelta([first.ref, other.ref], s.all(), sources), {
    added: [fresh.ref],
    revised: [{ ref: second.ref, previous: first.ref }],
    expired: [other.ref],
  })
})

test('checkpoint: the ledger block leads the working state and states the delta', () => {
  const quote = 'the retry policy must not swallow a write error'
  const messages = [
    { role: 'user', content: text('keep this request') },
    { role: 'assistant', content: text(quote) },
  ]
  const built = buildSelectiveCheckpoint({ messages }, {
    quotes: [quote],
    facts: [{ text: 'retry errors surface after the first commit', sources: [quote] }],
    ledger: {
      entries: [
        { ref: 'u1@2', kind: 'verification', text: 'V2 checked after edit', sources: ['seq:4'] },
      ],
      changes: {
        added: ['u3@1'],
        revised: [{ ref: 'u1@2', previous: 'u1@1' }],
        expired: ['u0@1'],
      },
    },
  })
  const heading = '## Working state (ledger; current entries, unverified)'
  const at = built.text.indexOf(heading)
  assert.ok(at >= 0, 'the ledger has its own leading block')
  assert.ok(at < built.text.indexOf('## Selected excerpts'), 'the working state leads the evidence')
  assert.match(built.text, /\[u1@2\] verification: V2 checked after edit \(sources: seq:4\)/)
  assert.match(built.text, /Changed since last presentation: added u3@1; revised u1@2 \(was u1@1\); expired u0@1/)
})