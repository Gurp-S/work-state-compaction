import assert from 'node:assert/strict'
import { test } from 'node:test'
import { admitCompaction } from '../lib/admission.js'
import { selectCompactableRange } from '../lib/range.js'

const timing = (tokens, action = 'model') => ({ tokens, capacity: 24000, action })

test('a zero ratio keeps every request', () => {
  const verdict = admitCompaction(timing(10340), { budget: 24000, retainTokens: 3840 })
  assert.equal(verdict.admit, true)
  assert.equal(verdict.reason, 'policy-off')
})

test('the hard boundary compacts even when the reclaim is small', () => {
  const verdict = admitCompaction(timing(9000, 'capacity'), {
    budget: 24000,
    retainTokens: 3840,
    minReclaimRatio: 0.9,
  })
  assert.equal(verdict.admit, true)
  assert.equal(verdict.reason, 'forced')
})

test('a low-pressure model request below the floor is skipped', () => {
  // The measured thrash: 10340 tokens against a 24000 budget reclaims 6500,
  // which is 27% of the budget and cannot pay for a selection round trip.
  const verdict = admitCompaction(timing(10340), {
    budget: 24000,
    retainTokens: 3840,
    minReclaimRatio: 0.35,
  })
  assert.equal(verdict.admit, false)
  assert.equal(verdict.reclaimTokens, 6500)
  assert.equal(verdict.floor, 8400)
  assert.equal(verdict.reason, 'reclaim-below-floor')
})

test('a request at the hard boundary is admitted', () => {
  const verdict = admitCompaction(timing(20400), {
    budget: 24000,
    retainTokens: 3840,
    minReclaimRatio: 0.35,
  })
  assert.equal(verdict.admit, true)
  assert.equal(verdict.reclaimTokens, 16560)
})

test('a negative or missing reclaim never goes below zero', () => {
  const verdict = admitCompaction(timing(1000), {
    budget: 24000,
    retainTokens: 3840,
    minReclaimRatio: 0.35,
  })
  assert.equal(verdict.reclaimTokens, 0)
  assert.equal(verdict.admit, false)
})

test('selected region tokens exclude system, retained tail and an unbalanced pair', () => {
  const session = {
    surface: { nodes: [0, 1, 2, 3, 4] },
    events: [{ seq: 0, type: 'system/message' }],
  }
  const nodes = [10000, 2782, 2000, 2000, 1000].map((tokens, seq) => ({ seq, tokens }))
  const range = selectCompactableRange(session, { nodes }, 2500, (_, seq) => seq !== 3)
  assert.deepEqual(range, { start: 1, end: 1, tokens: 2782 })
})
