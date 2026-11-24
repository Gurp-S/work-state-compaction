import test from 'node:test'
import assert from 'node:assert/strict'

import {
  capLedger, indexText, ledgerSentences, nextText, receiptsText, renderPassage, stateText, valuesText, windowControl,
} from '../lib/passage.js'
import { historyIndex } from '../lib/evidence-index.js'

const entry = (kind, text, seq = 1, status = 'active') => ({ id: `t${seq}`, rev: 1, kind, text, seq, status })
const call = (id, name, args) => ({
  role: 'assistant',
  content: [{ type: 'tool-call', id, name, arguments: JSON.stringify(args) }],
})
const result = (id, text) => ({
  role: 'user',
  content: [{ type: 'tool-result', toolCallId: id, content: [{ type: 'text', text }] }],
})
const rowsOf = (messages) => messages.map((message, index) => ({ seq: index + 1, message }))

test('passage: ledger sentences rank constraints over facts and drop periods', () => {
  const text = ledgerSentences([
    entry('fact', 'src/store.js: TAX_RATE = 0.07', 3),
    entry('constraint', 'Do not rename formatCents.', 1),
    entry('decision', 'decision: use cents', 2),
    entry('fact', 'src/store.js: TAX_RATE = 0.07', 4),
    entry('decision', 'stale', 5, 'superseded'),
  ])
  assert.equal(text, 'Constraint: Do not rename formatCents. Decision: decision: use cents. Context: src/store.js: TAX_RATE = 0.07.')
})

test('passage: state keeps done/open/next and skips next when a banner carries it', () => {
  const state = { done: ['A'], open: ['B'], next: ['run npm test'], unknown: ['C'] }
  assert.equal(stateText(state), 'State: done: A. open: B. next: run npm test. unknown: C.')
  assert.equal(stateText(state, [], ['next']), 'State: done: A. open: B. unknown: C.')
  assert.equal(nextText(state), 'Next action (recorded): run npm test.')
  assert.equal(nextText({ next: ['run tests (assistant-originated)'] }),
    'Next action (recorded by assistant): run tests.')
})

test('passage: a receipt already stated by the state is not repeated', () => {
  const receipts = [{
    path: 'src/report.js', edit: 4, check: 6, command: 'npm test', result: 'ok', stale: false,
  }]
  assert.equal(receiptsText(receipts, ['src/report.js matches (edit #4, check #6 npm test: ok)']), '')
  assert.match(receiptsText(receipts), /^Checks: src\/report\.js was edited at #4; the check at #6 \(npm test\) reported: ok\.$/)
  assert.match(receiptsText([{ path: 'a.js', edit: 2, check: null }]),
    /^Checks: a\.js was edited at #2 and no later check covers it\.$/)
})

test('passage: values render newest first and name archived keys', () => {
  const values = [
    { key: 'V1', label: 'a.txt: one', terms: ['a.txt'], text: 'one', seq: 11 },
    { key: 'V2', label: 'a.txt: two', terms: ['a.txt'], text: 'two', seq: 12 },
  ]
  assert.equal(valuesText(values), 'Observed values (fetch by key): [V2] a.txt: two (read_evidence #12); [V1] a.txt: one (read_evidence #11).')
  assert.equal(valuesText(values, [], 1),
    'Observed values (fetch by key): [V2] a.txt: two (read_evidence #12). 1 older values archived: fetch V1.')
  assert.equal(valuesText(values, [], 0), 'Observed values archived: fetch V2, V1.')
})

test('passage: index lines carry a seq and disclose sources without a slot', () => {
  const index = [{
    key: 'E1', label: 'edit src/report.js', kind: 'edit', terms: ['src/report.js', 'cents'],
    text: '', seq: 7, tool: 'read_history',
  }]
  assert.equal(indexText(index), 'Evidence index (fetch by key): [E1] edit src/report.js | terms: cents (read_history #7).')
  assert.match(indexText(index, [], 3), / 3 further sources are archived without an index slot\.$/)
})

test('index: observations fetch the result seq and calls fetch the call seq', () => {
  const rows = rowsOf([
    call('r1', 'read', { file_path: 'src/a.js' }),
    result('r1', 'export const a = 1'),
    call('e1', 'edit', { file_path: 'src/a.js', old_string: 'a = 1', new_string: 'a = 2' }),
    result('e1', 'ok'),
  ])
  const index = historyIndex(rows, { limit: 20 })
  const read = index.find((row) => row.kind === 'read')
  const edit = index.find((row) => row.kind === 'edit')
  assert.equal(read.seq, 2, 'the read points at the result event, not the call')
  assert.equal(read.tool, 'read_evidence')
  assert.equal(edit.seq, 3, 'the edit keeps the call that holds old/new')
  assert.equal(edit.tool, 'read_history')
})

test('passage: a value-bearing fact outlives plain prose under the cap', () => {
  const ledger = [
    entry('fact', `src/store.js: TAX_RATE = 0.07 ${'x'.repeat(20)}`, 1),
    entry('fact', `src/report.js: a long contextual sentence ${'y'.repeat(20)}`, 2),
  ]
  const capped = capLedger(ledger, 200, { valueFirst: true })
  assert.equal(capped.entries.length, 1)
  assert.match(capped.entries[0].text, /TAX_RATE = 0.07/)
})

test('passage: trimming drops the index before the ledger, and keeps one entry', () => {
  const ledger = [entry('fact', 'x'.repeat(200), 1), entry('constraint', 'keep this', 2)]
  const index = [{ key: 'E1', label: `edit ${'y'.repeat(300)}`, kind: 'edit', terms: [], text: '', seq: 3 }]
  const text = renderPassage({ control: ['do it'], ledger, index, budget: 400 })
  assert.ok(!text.includes('Evidence index'), 'index gave up its slot first')
  assert.ok(text.includes('Constraint: keep this.'))
  const tiny = renderPassage({ control: [], ledger, budget: 10 })
  assert.equal(tiny, 'Ledger (current): Constraint: keep this.')
})

test('passage: old control messages are omitted whole and the cut is disclosed', () => {
  const texts = ['a'.repeat(100), 'b'.repeat(100), 'c'.repeat(100)]
  assert.deepEqual(windowControl(texts, 0), { texts, omitted: 0 })
  const windowed = windowControl(texts, 220)
  assert.deepEqual(windowed.texts, [texts[1], texts[2]])
  assert.equal(windowed.omitted, 1)
  const text = renderPassage({ control: windowed.texts, controlOmitted: 1, budget: 4096 })
  assert.match(text, /^User requirements, quoted verbatim: "b+" "c+"/)
  assert.match(text, /1 earlier requests omitted; later instructions and the ledger carry their state\.$/)
})

test('passage: an optional working-set block sits between state and checks', () => {
  const text = renderPassage({
    control: [],
    ledger: [],
    stateBlock: '## Current state (model account; unverified)\n- Done: x',
    workingSet: '## Working set\n- src/report.js — edit #3: "y"',
    receipts: [{ path: 'src/report.js', edit: 3, check: 4, command: 'npm test', result: 'ok' }],
    budget: 4096,
  })
  const lines = text.split('\n\n').map((part) => part.split('\n')[0])
  assert.deepEqual(lines, [
    '## Current state (model account; unverified)',
    '## Working set',
    'Checks: src/report.js was edited at #3; the check at #4 (npm test) reported: ok.',
  ])
})

test('passage: control quotes are deduplicated and always first', () => {
  const text = renderPassage({ control: ['add a flag', 'add a flag', 'run tests'], ledger: [], budget: 4096 })
  assert.equal(text, 'User requirements, quoted verbatim: "add a flag" "run tests".')
})

test('evidence index: one slot per kind survives before quotas fill', () => {
  const row = (position, blocks) => ({ seq: position, message: { role: 'assistant', content: blocks } })
  const rows = [
    row(1, [{ type: 'text', text: 'next: run npm test.' }]),
    row(2, [{ type: 'tool-call', id: 'c1', name: 'read', arguments: { path: 'src/report.js' } }]),
    row(3, [{ type: 'tool-call', id: 'c2', name: 'edit', arguments: { path: 'src/report.js', old_string: 'a', new_string: 'b' } }]),
    { seq: 4, message: { role: 'user', content: [{ type: 'tool-result', toolCallId: 'c2', content: [{ type: 'text', text: 'ok' }] }] } },
    row(5, [{ type: 'tool-call', id: 'c3', name: 'pwsh', arguments: { command: 'npm test' } }]),
    { seq: 6, message: { role: 'user', content: [{ type: 'tool-result', toolCallId: 'c3', content: [{ type: 'text', text: 'tests pass' }] }] } },
  ]
  const index = historyIndex(rows, { limit: 3 })
  // One slot per kind present survives even below the quota limit, exactly as
  // the reference fills its first pass. The edit's result is covered by its
  // call row, so it adds no generic output slot.
  assert.deepEqual(index.map((row) => row.kind).sort(), ['cmd', 'edit', 'note', 'read', 'test'])
  assert.ok(index.every((row) => /^E\d+$/.test(row.key)))
  assert.ok(index.every((row) => Number.isInteger(row.seq)))
})

test('passage: the latest request is restated once when the quote list is long', () => {
  const controls = ['one', 'two', 'three', 'four', 'five']
  const text = renderPassage({ control: controls, latestControl: 'five', ledger: [], budget: 4096 })
  assert.ok(text.startsWith('Latest request: "five"'))
  assert.equal(text.split('"five"').length - 1, 2)
  const short = renderPassage({ control: ['one'], latestControl: 'one', ledger: [], budget: 4096 })
  assert.ok(!short.includes('Latest request'))
})

test('passage: recent changes follow the state block and precede checks', () => {
  const stateBlock = '## Current state (model account; unverified)\n## Next step\n## Open / Unknown\n- Unknown: x'
  const text = renderPassage({
    control: ['add a flag'],
    stateBlock,
    recent: '- src/format.js (edit #3, check #4): formatCents(cents)',
    receipts: [{ path: 'src/format.js', edit: 3, check: 4, command: 'npm test', result: 'ok' }],
    ledger: [],
    budget: 4096,
  })
  assert.ok(text.includes('## Recent changes\n- src/format.js (edit #3, check #4): formatCents(cents)'))
  assert.ok(text.indexOf('## Current state') < text.indexOf('## Recent changes'))
  assert.ok(text.indexOf('## Recent changes') < text.indexOf('Checks:'))
})
