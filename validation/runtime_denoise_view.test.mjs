import { test } from 'node:test'
import assert from 'node:assert/strict'
import { runtimeDenoise, createDenoiseState } from '../../dsh-wsc/lib/denoise.js'
import { runtimeDenoiseView } from '../experiments/runtime_denoise_view.mjs'

const ctx = (extra={}) => ({toolName:'exec_command', callId:'c1', args:{}, state:createDenoiseState(), resultClass:'log', exitCode:0, ...extra})

test('reproduces CRLF data loss in original rule and preserves both records in sidecar', () => {
  const text = 'test_a ... ok\r\ntest_b ... ok\r\n'
  assert.equal(runtimeDenoise(text,ctx()).text,'  ×3')
  assert.equal(runtimeDenoiseView(text,ctx()),null)
})
test('source, unknown classification, errors and recovery results bypass all rewriting', () => {
  const text = 'const contract = 42;\r\n'.repeat(100)
  for (const extra of [{resultClass:'source'}, {resultClass:undefined}, {exitCode:1}, {rawRecovery:true}]) {
    assert.equal(runtimeDenoiseView(text,ctx(extra)),null)
  }
})
test('CRLF and LF yield same denoise view while progress controls retain their meaning', () => {
  const lf = ('test ... ok\n').repeat(100)+'progress 1\rprogress 2\n'
  assert.deepEqual(runtimeDenoiseView(lf.replace(/\n/g,'\r\n'),ctx()), runtimeDenoiseView(lf,ctx()))
  assert.equal(runtimeDenoiseView(lf,ctx()).text, 'test ... ok  ×100\nprogress 2\n')
})
