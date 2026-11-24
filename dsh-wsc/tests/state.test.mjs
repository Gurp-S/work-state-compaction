import assert from 'node:assert/strict'
import test from 'node:test'

import { parseCheckpointState, renderCheckpointState } from '../lib/checkpoint-state.js'
import { asCheckpointState, engineState, receiptsFromRows, recentChanges, requirementTerms } from '../lib/state.js'

const user = (text) => ({ role: 'user', content: [{ type: 'text', text }] })
const assistant = (text) => ({ role: 'assistant', content: [{ type: 'text', text }] })
const call = (id, name, args) => ({
  role: 'assistant',
  content: [{ type: 'tool-call', id, name, arguments: JSON.stringify(args) }],
})
const result = (id, text) => ({
  role: 'user',
  content: [{ type: 'tool-result', toolCallId: id, content: [{ type: 'text', text }] }],
})
const rowsOf = (messages) => messages.map((message, index) => ({ seq: index + 1, message }))

test('state: receipts pair an edit with the last check before the next edit', () => {
  const rows = rowsOf([
    call('e1', 'edit', { file_path: 'src/format.js', old_string: 'a', new_string: 'formatCents(cents)' }),
    call('t1', 'pwsh', { command: 'npm test' }),
    result('t1', 'pass 5\nfail 0'),
    call('e2', 'edit', { file_path: 'src/format.js', old_string: 'b', new_string: 'formatCents(cents / 100)' }),
    call('t2', 'pwsh', { command: 'node --test' }),
    result('t2', 'pass 6'),
  ])
  const receipts = receiptsFromRows(rows)
  assert.equal(receipts.length, 2)
  assert.equal(receipts[0].check, 3)
  assert.equal(receipts[0].stale, true)
  assert.equal(receipts[0].command, 'npm test')
  assert.equal(receipts[1].check, 6)
  assert.equal(receipts[1].stale, false)
})

test('state: receipts carry the durable seq beside the region position', () => {
  const rows = [
    { seq: 101, message: call('e1', 'edit', { file_path: 'src/format.js', old_string: 'a', new_string: 'b' }) },
    { seq: 104, message: call('t1', 'pwsh', { command: 'npm test' }) },
    { seq: 105, message: result('t1', 'pass 6\nfail 0') },
  ]
  const receipts = receiptsFromRows(rows)
  assert.equal(receipts[0].edit, 1, 'region position stays')
  assert.equal(receipts[0].editSeq, 101, 'durable seq is available')
  assert.equal(receipts[0].checkSeq, 105)
})

test('state: a matched edit with a post-edit check is done', () => {
  const messages = [
    user('Add formatCents to src/format.js and run npm test.'),
    call('e1', 'edit', { file_path: 'src/format.js', new_string: 'export function formatCents(cents) { return cents / 100 }' }),
    call('t1', 'pwsh', { command: 'npm test' }),
    result('t1', 'pass 5'),
  ]
  const rows = rowsOf(messages)
  const state = asCheckpointState(engineState([], rows, receiptsFromRows(rows)))
  assert.equal(state.done.length, 1)
  assert.match(state.done[0], /edit #2, check #4/)
  assert.match(state.done[0], /npm test/)
})

test('state: an absolute tool path still matches the relative requirement path', () => {
  const workspace = process.cwd().replace(/\\/g, '/')
  const messages = [
    user('Add formatCents to src/format.js and run npm test.'),
    call('e1', 'edit', {
      file_path: `${workspace}/src/format.js`,
      new_string: 'export function formatCents(cents) { return cents / 100 }',
    }),
    call('t1', 'pwsh', { command: 'npm test' }),
    result('t1', 'pass 5'),
  ]
  const rows = rowsOf(messages)
  const receipts = receiptsFromRows(rows)
  assert.equal(receipts[0].path, 'src/format.js')
  const state = asCheckpointState(engineState([], rows, receipts))
  assert.equal(state.done.length, 1)
})

test('state: req numbers count the accumulated control list, not the region', () => {
  const messages = [
    user('Add formatCents to src/format.js.'),
    call('e1', 'edit', { file_path: 'src/format.js', new_string: 'formatCents(cents)' }),
  ]
  const rows = rowsOf(messages)
  const state = engineState([], rows, receiptsFromRows(rows), {
    controls: ['Read the sources.', 'Add formatCents to src/format.js.'],
  })
  const rowsOut = [...state.done, ...state.open, ...state.unknown]
  assert.ok(rowsOut.some((row) => row.includes('req#2')), rowsOut.join('\n'))
})

test('state: an engine notice is not a user requirement', () => {
  const messages = [
    { role: 'user', source: { kind: 'compaction' }, content: [{ type: 'text', text:
      'This is an automatically generated checkpoint condensing an earlier span. Treat the captured context as established.' }] },
    call('e1', 'edit', { file_path: 'src/format.js', new_string: 'formatCents(cents)' }),
  ]
  const rows = rowsOf(messages)
  const state = engineState([], rows, receiptsFromRows(rows), {
    isSynthetic: (message) => message?.source?.kind === 'compaction',
  })
  const rowsOut = [...state.done, ...state.open, ...state.unknown]
  assert.ok(!rowsOut.some((row) => row.includes('automatically generated')), rowsOut.join('\n'))
})

test('state: a run-and-report probe is not a work requirement', () => {
  const messages = [
    user('Run node src/cli.js data/sample.json and paste its exact output.'),
    call('e1', 'edit', { file_path: 'src/cli.js', new_string: 'console.log(output)' }),
  ]
  const rows = rowsOf(messages)
  const state = engineState([], rows, receiptsFromRows(rows))
  assert.equal(state.open.length, 0)
  assert.equal(state.done.length, 0)
})

test('state: a matched edit without a check stays visible as an open item', () => {
  const messages = [
    user('Add formatCents to src/format.js.'),
    call('e1', 'edit', { file_path: 'src/format.js', new_string: 'formatCents(cents)' }),
  ]
  const rows = rowsOf(messages)
  const state = asCheckpointState(engineState([], rows, receiptsFromRows(rows)))
  assert.equal(state.open.length, 0)
  assert.ok(state.unknown.some((row) => /no post-edit check/.test(row)))
})

test('state: a later edit that no longer matches is unverified, not done', () => {
  const messages = [
    user('Add formatCents to src/format.js.'),
    call('e1', 'edit', { file_path: 'src/format.js', new_string: 'formatCents(cents)' }),
    call('e2', 'edit', { file_path: 'src/format.js', new_string: 'something else' }),
  ]
  const rows = rowsOf(messages)
  const state = engineState([], rows, receiptsFromRows(rows))
  assert.equal(state.done.length, 0)
  assert.ok(state.unknown.some((row) => /current state unverified/.test(row)))
})

test('state: a recorded next action becomes unknown after a later change that shares terms', () => {
  const messages = [
    user('Implement the report limit.'),
    assistant('Next: wire REPORT_LIMIT through cli parsing.'),
    user('Instead, change the limit to come from REPORT_LIMIT only.'),
  ]
  const rows = rowsOf(messages)
  const state = engineState([], rows, receiptsFromRows(rows))
  assert.equal(state.next.length, 0)
  assert.ok(state.unknown.some((row) => /stale after a later change/.test(row)))
})

test('state: the projection renders through the checkpoint state parser', () => {
  const messages = [
    user('Add formatCents to src/format.js and run npm test.'),
    call('e1', 'edit', { file_path: 'src/format.js', new_string: 'formatCents(cents)' }),
    call('t1', 'pwsh', { command: 'npm test' }),
    result('t1', 'pass 4'),
  ]
  const rows = rowsOf(messages)
  const state = asCheckpointState(engineState([], rows, receiptsFromRows(rows)))
  const parsed = parseCheckpointState(state)
  assert.ok(parsed !== null)
  const text = renderCheckpointState(parsed)
  assert.match(text, /## Current state/)
  assert.match(text, /Done: /)
})

test('state: requirement terms keep identifiers and drop filler words', () => {
  const terms = requirementTerms('Please add retries to src/report.js and update REPORT_LIMIT')
  assert.ok(terms.includes('retries'))
  assert.ok(terms.includes('REPORT_LIMIT'))
  assert.ok(terms.includes('src/report.js'))
  assert.ok(!terms.includes('please'))
})

test('state: a request stated before the region still owns its edit', () => {
  const rows = rowsOf([
    call('e1', 'edit', {
      file_path: 'src/format.js',
      new_string: 'export function formatCents(cents) { return cents / 100 }',
    }),
    call('t1', 'pwsh', { command: 'npm test' }),
    result('t1', 'pass 5'),
  ])
  const state = asCheckpointState(engineState([], rows, receiptsFromRows(rows), {
    controls: ['Add formatCents to src/format.js and run npm test.'],
  }))
  assert.equal(state.done.length, 1)
  assert.match(state.done[0], /req#1/)
  assert.match(state.done[0], /edit #1, check #3/)
})

test('state: the newest request with no local edit becomes next, not an empty block', () => {
  const rows = rowsOf([
    call('e1', 'edit', {
      file_path: 'src/format.js',
      new_string: 'export function formatCents(cents) { return cents / 100 }',
    }),
    call('t1', 'pwsh', { command: 'npm test' }),
    result('t1', 'pass 5'),
  ])
  const controls = [
    'Add formatCents to src/format.js and run npm test.',
    'Add buildJsonReport to src/report.js and run npm test.',
  ]
  const state = asCheckpointState(engineState([], rows, receiptsFromRows(rows), { controls }))
  assert.equal(state.done.length, 1)
  assert.equal(state.next.length, 1)
  assert.match(state.next[0], /req#2/)
  assert.match(state.next[0], /buildJsonReport/)
})

test('state: recent changes list the newest distinct paths first', () => {
  const rows = rowsOf([
    call('e1', 'edit', { file_path: 'src/format.js', new_string: 'export function formatCents(cents) {}' }),
    call('t1', 'pwsh', { command: 'npm test' }),
    result('t1', 'pass 5'),
    call('e2', 'edit', { file_path: 'src/report.js', new_string: 'export function buildJsonReport(order) {}' }),
    call('e3', 'edit', { file_path: 'src/format.js', new_string: 'export function formatCents(cents, options) {}' }),
  ])
  const text = recentChanges(receiptsFromRows(rows), 2)
  const lines = text.split('\n')
  assert.equal(lines.length, 2)
  assert.match(lines[0], /src\/format\.js \(edit #5/)
  assert.match(lines[0], /formatCents\(cents, options\)/)
  assert.match(lines[1], /src\/report\.js \(edit #4/)
})

test('state: unmatched-request promotion can be disabled', () => {
  const rows = rowsOf([
    call('e1', 'edit', {
      file_path: 'src/format.js',
      new_string: 'export function formatCents(cents) { return cents / 100 }',
    }),
    call('t1', 'pwsh', { command: 'npm test' }),
    result('t1', 'pass 5'),
  ])
  const controls = [
    'Add formatCents to src/format.js and run npm test.',
    'Add buildJsonReport to src/report.js and run npm test.',
  ]
  const state = engineState([], rows, receiptsFromRows(rows), {
    controls, promoteUnmatched: false,
  })
  assert.equal(state.done.length, 1)
  assert.equal(state.next.length, 0)
})
