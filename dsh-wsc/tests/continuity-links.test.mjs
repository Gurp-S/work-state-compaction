import assert from 'node:assert/strict'
import test from 'node:test'
import { indexToolReceipts, toolReceiptLinks } from '../lib/continuity-links.js'
import { prepareContinuity } from '../lib/continuity.js'
import { runtimeObservations } from '../lib/verification.js'
import { readReceiptHistory } from '../lib/receipt-history.js'

test('tool excerpt binds only to a unique earlier call and equal typed receipt', () => {
  const call = { role: 'assistant', content: [{ type: 'tool-call', id: 'job', name: 'pwsh' }] }
  const result = { role: 'user', content: [{
    type: 'tool-result', toolCallId: 'job', content: [{ type: 'text', text: '5 tests passed' }],
  }] }
  const original = [{ seq: 12, message: call }, { seq: 18, message: result }]
  const changed = structuredClone(result)
  changed.content[0].content[0].text = '6 tests passed'
  const link = (messages, rows) =>
    toolReceiptLinks(messages, indexToolReceipts(rows, runtimeObservations(rows.map(row => row.message))))
  assert.deepEqual([...link([changed, structuredClone(result)], original)], [[1, 'call #12, receipt #18']])
  assert.equal(link([result], [...original, { seq: 20, message: result }]).size, 0)
  assert.equal(link([result], [{ seq: 11, message: call }, ...original]).size, 0)
  assert.equal(link([result], [{ seq: 10, message: result }, { seq: 12, message: call }]).size, 0)
  for (const region of [[call, result, changed], [call, call, result]]) {
    for (const observation of runtimeObservations(region)) {
      assert.equal(observation.status, 'unknown')
      assert.equal(observation.completedAt, undefined)
    }
  }
})

test('receipt history returns only the matching invocation from a multi-call event', () => {
  const session = {
    events: [
      {seq: 12, type: 'assistant/message', data: {role: 'assistant', content: [
        {type: 'tool-call', id: 'other', name: 'pwsh', arguments: {command: 'other command'}},
        {type: 'tool-call', id: 'verify', name: 'pwsh', arguments: {command: 'check report\ncheck total'}},
      ]}},
      {seq: 17, type: 'tool/result', data: {role: 'user', content: [
        {type: 'tool-result', toolCallId: 'verify', content: [{type: 'text', text: 'passed'}]},
      ]}},
    ],
    deriveEventMessage: event => event.data,
  }
  const result = JSON.parse(readReceiptHistory(session, 17).text)
  assert.equal(result.call_seq, 12)
  assert.equal(result.receipt_seq, 17)
  assert.deepEqual(JSON.parse(result.arguments.text), {command: 'check report\ncheck total'})
  assert.equal(result.result.text, 'passed')
  assert.equal(result.process_status, 'completed')
  assert.throws(() => readReceiptHistory(session, 12), /unbound tool receipt/)
  const originalEvents = [...session.events]
  const truncated = structuredClone(session.events[1].data)
  truncated.content[0].content[0].text = 'pruned'
  session.events.push(
    {seq: 18, type: 'compaction/prune', data: {shadowedSeqs: [17]}},
    {seq: 19, type: 'tool/result', sourceEventSeqs: [17],
     surfaceOp: {op: 'replace', start: 17, end: 17}, data: truncated},
  )
  assert.equal(JSON.parse(readReceiptHistory(session, 17).text).result.text, 'passed')
  assert.throws(() => readReceiptHistory(session, 19), /unbound tool receipt/)
  session.events = originalEvents
  session.events.push({...session.events[1], seq: 19})
  assert.throws(() => readReceiptHistory(session, 17), /unbound tool receipt/)
  const view = prepareContinuity({messages: []}, session, () => false)
  assert.match(view.runtime, /check report.*call #12: unknown/)
  assert.doesNotMatch(view.runtime, /receipt #(?:17|19)/)
})
