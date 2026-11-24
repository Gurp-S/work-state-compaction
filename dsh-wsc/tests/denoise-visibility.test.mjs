import test from 'node:test'
import assert from 'node:assert/strict'
import { createDenoiseState, resetDenoiseState, runtimeDenoise } from '../lib/denoise.js'

const bytes = Array.from({ length: 60 }, (_, index) => `export const value${index} = ${index}`).join('\n')

const read = (state, callId) =>
  runtimeDenoise(bytes, { toolName: 'read', callId, args: { path: 'src/report.js' }, state })

test('dedupe fires while the earlier read is still in the request view', () => {
  const state = createDenoiseState()
  assert.equal(read(state, 'c1'), null)
  const second = read(state, 'c2')
  assert.match(second.text, /identical to call c1/)
})

test('after a compaction boundary a repeat read returns real bytes again', () => {
  const state = createDenoiseState()
  assert.equal(read(state, 'c1'), null)
  assert.match(read(state, 'c2').text, /identical to call c1/)
  resetDenoiseState(state)
  assert.equal(read(state, 'c3'), null, 'the earlier copy was shadowed; a pointer would cost an extra fetch')
})

test('reset also clears identical-result memory', () => {
  const state = createDenoiseState()
  const small = `tests 35, pass 35, fail 0 ${'ok '.repeat(300)}`
  const shared = { toolName: 'pwsh', args: { command: 'npm test' }, state }
  assert.equal(runtimeDenoise(small, { ...shared, callId: 'c1' }), null)
  assert.match(runtimeDenoise(small, { ...shared, callId: 'c2' }).text, /identical to an earlier result/)
  resetDenoiseState(state)
  assert.equal(runtimeDenoise(small, { ...shared, callId: 'c3' }), null)
})

test('a missing state is a no-op, not a crash', () => {
  assert.doesNotThrow(() => resetDenoiseState(undefined))
  assert.doesNotThrow(() => resetDenoiseState(null))
})
