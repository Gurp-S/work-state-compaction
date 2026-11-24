import test from 'node:test'
import assert from 'node:assert/strict'
import { join } from 'node:path'
import { historyIndex } from '../lib/evidence-index.js'

const root = process.cwd()
const spill = join(root, '..', '..', 'AppData', 'Local', 'Temp', 'dsh-spill-OiBTDk', 'session-a', 'deadbeef-read.txt')

const call = (id, name, args) => ({ type: 'tool-call', id, name, arguments: args })
const result = (id, text, isError = false) => ({
  type: 'tool-result', toolCallId: id, isError, content: [{ type: 'text', text }],
})
const rowsOf = (blocks) => blocks.map((blocks, index) => ({
  seq: index + 1,
  message: { role: index % 2 === 0 ? 'assistant' : 'user', content: blocks },
}))
const envelope = (path, body) =>
  `<path>${path}</path>\n<type>file</type>\n<content>\n${body}\n`

test('index: a spill read is not evidence', () => {
  const rows = rowsOf([
    [call('c1', 'read', { path: spill })],
    [result('c1', envelope(spill, '1: Error: spawn EPERM'))],
  ])
  assert.deepEqual(historyIndex(rows), [])
})

test('index: a workspace read whose body contains Error is a read, not an error', () => {
  const path = join(root, 'src', 'report.js')
  const rows = rowsOf([
    [call('c1', 'read', { path })],
    [result('c1', envelope(path, "1: export function toCsv() {\n2:   throw new Error('negative')"))],
  ])
  const index = historyIndex(rows)
  assert.deepEqual(index.map((row) => row.kind), ['read'])
  assert.equal(index[0].label, 'read src/report.js')
  assert.equal(index[0].seq, 2, 'the read cites the result bytes')
})

test('index: a read result is not repeated as a generic output row', () => {
  const path = join(root, 'src', 'report.js')
  const rows = rowsOf([
    [call('c1', 'read', { path })],
    [result('c1', envelope(path, '1: export const alpha = beta'))],
  ])
  assert.deepEqual(historyIndex(rows).map((row) => row.kind), ['read'])
})

test('index: an explicit error head keeps the error slot', () => {
  const rows = rowsOf([
    [call('c1', 'pwsh', { command: 'npm test' })],
    [result('c1', 'Error: Cannot find module ./store.js\n    at src/report.js:3:1')],
  ])
  const index = historyIndex(rows)
  const error = index.find((row) => row.kind === 'error')
  assert.ok(error !== undefined)
  assert.match(error.label, /^error Error: Cannot find module/)
})

test('index: a round transcript read is dropped even when it holds matches', () => {
  const transcript = join(root, '..', 'runs', 'out', 'round-37.jsonl')
  const rows = rowsOf([
    [call('c1', 'read', { path: transcript })],
    [result('c1', envelope(transcript, '1: {"type":"thinking"}'))],
  ])
  assert.deepEqual(historyIndex(rows), [])
})

test('index: output labels do not repeat the envelope path', () => {
  const rows = rowsOf([
    [call('c1', 'pwsh', { command: 'node src/report.js' })],
    [result('c1', envelope(join(root, 'out', 'log.txt'), '1: no output'))],
  ])
  const output = historyIndex(rows).find((row) => row.kind === 'output')
  assert.ok(output !== undefined)
  assert.equal(output.label, 'result no output')
})
