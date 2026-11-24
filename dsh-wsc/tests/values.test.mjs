import assert from 'node:assert/strict'
import test from 'node:test'

import { buildCheckpoint } from '../lib/checkpoint.js'
import { mergeEngineValues, regionValueRows, renderValueLines, termsOf, valueRows } from '../lib/values.js'

const call = (id, name, args) => ({
  role: 'assistant',
  content: [{ type: 'tool-call', id, name, arguments: JSON.stringify(args) }],
})
const result = (id, text) => ({
  role: 'user',
  content: [{ type: 'tool-result', toolCallId: id, content: [{ type: 'text', text }] }],
})
const rowsOf = (messages) => messages.map((message, index) => ({ seq: index + 1, message }))

test('values: a constant assignment in a source read becomes an addressable row', () => {
  const rows = valueRows(rowsOf([
    call('c1', 'read', { file_path: 'src/store.js' }),
    result('c1', '<path>C:\\work\\src\\store.js</path>\n<type>file</type>\n<content>\n'
      + '1: export const TAX_RATE = 0.07\n2: export function taxCents(cents) { return cents * TAX_RATE }\n'
      + '</content>'),
  ]))
  assert.equal(rows.length, 1)
  assert.equal(rows[0].key, 'V1')
  assert.equal(rows[0].seq, 2)
  assert.equal(rows[0].label, 'src/store.js: TAX_RATE = 0.07')
  assert.equal(rows[0].identity, 'src/store.js#TAX_RATE')
  assert.ok(rows[0].terms.includes('TAX_RATE'))
  assert.equal(rows[0].text, 'TAX_RATE = 0.07')
})

test('values: a region row carries no key; the keyed list adds them', () => {
  const rows = rowsOf([
    call('c1', 'read', { file_path: 'src/store.js' }),
    result('c1', 'TAX_RATE = 0.07'),
  ])
  assert.equal(regionValueRows(rows)[0].key, undefined)
  assert.equal(valueRows(rows)[0].key, 'V1')
})

test('values: test bodies, spill files, grep output and command output are skipped', () => {
  const rows = valueRows(rowsOf([
    call('c1', 'pwsh', { command: 'npm test' }),
    result('c1', 'REPORT_LIMIT = 20'),
    call('c2', 'read', { file_path: 'tests/report.test.mjs' }),
    result('c2', '1: const REPORT_LIMIT = 20\n2: assert.equal(count, 40)'),
    call('c3', 'read', { file_path: 'C:\\Temp\\dsh-spill-ab\\read.txt' }),
    result('c3', '1: const TAX_RATE = 0.07'),
    call('c4', 'grep', { pattern: 'TAX_RATE' }),
    result('c4', 'src/store.js:1:export const TAX_RATE = 0.07'),
    call('c5', 'read', { file_path: 'src/report.js' }),
    result('c5', '1: export const DEFAULT_REPORT_LIMIT = 20'),
  ]))
  assert.equal(rows.length, 1)
  assert.equal(rows[0].label, 'src/report.js: DEFAULT_REPORT_LIMIT = 20')
})

test('values: the rendered block is newest-first and names omitted keys', () => {
  const rows = Array.from({ length: 18 }, (_, index) => ({
    key: `V${index + 1}`, seq: 100 + index, label: `file${index}.js: LIMIT = ${20 + index}`,
    terms: ['LIMIT'], text: '',
  }))
  const lines = renderValueLines(rows, { maxRows: 16 })
  assert.equal(lines.length, 17)
  assert.match(lines[0], /V18/)
  assert.match(lines[16], /fetch V1, V2/)
})

test('values: terms keep paths, identifiers, codes and commands', () => {
  const terms = termsOf('edit docs/relnotes.md for REL-9482 after node --test tests/store.test.mjs')
  assert.ok(terms.includes('docs/relnotes.md'))
  assert.ok(terms.includes('REL-9482'))
  assert.ok(terms.some((term) => term.startsWith('node --test')))
})

test('values: checkpoint renders the section inside its budget', () => {
  const messages = [
    { role: 'user', content: [{ type: 'text', text: 'Add a report limit.' }] },
    call('c1', 'read', { file_path: 'src/report.js' }),
    result('c1', 'DEFAULT_REPORT_LIMIT = 20'),
  ]
  const values = renderValueLines(valueRows(rowsOf(messages)))
  const built = buildCheckpoint({ messages }, { values, structuredState: false, maxChars: 4000 })
  assert.match(built.text, /## Observed values \(fetch by key\)/)
  assert.match(built.text, /DEFAULT_REPORT_LIMIT = 20/)
  assert.match(built.text, /\(read_evidence #3\)/)
})

test('values: a wrapped read result names its content, not the envelope', () => {
  const rows = valueRows(rowsOf([
    call('c1', 'read', { file_path: 'src/store.js' }),
    result('c1', '<path>C:\\work\\src\\store.js</path>\n<type>file</type>\n<content>\n1: TAX_RATE = 0.07\n</content>'),
  ]))
  assert.equal(rows.length, 1)
  assert.equal(rows[0].label, 'src/store.js: TAX_RATE = 0.07')
  assert.ok(!rows[0].label.includes('<path>'))
})

test('values: one file read yields every constant, and a later read wins per name', () => {
  const rows = valueRows(rowsOf([
    call('c1', 'read', { file_path: 'src/store.js' }),
    result('c1', '<content>\n1: export const TAX_RATE = 0.07\n2: const CENTS_PER_DOLLAR = 100\n</content>'),
    call('c2', 'read', { file_path: 'src/store.js' }),
    result('c2', '<content>\n7: const TAX_RATE = 0.08\n</content>'),
  ]))
  assert.deepEqual(rows.map((row) => `${row.identity}:${row.value}`), [
    'src/store.js#CENTS_PER_DOLLAR:100',
    'src/store.js#TAX_RATE:0.08',
  ])
  assert.equal(rows.length, 2)
  assert.equal(rows[0].seq, 2)
  assert.equal(rows[1].seq, 4)
})

test('values: a read result without an assignment is not a value', () => {
  const rows = valueRows(rowsOf([
    call('c1', 'read', { file_path: 'src/store.js' }),
    result('c1', '<content>\n1: export function taxCents(cents) { return cents * 7 }\n2: // limit is 20\n</content>'),
  ]))
  assert.equal(rows.length, 0)
})

test('values: a fact that only restates an engine value can be hidden', () => {
  const entries = [
    { kind: 'fact', text: 'DEFAULT_REPORT_LIMIT = 20' },
    { kind: 'decision', text: 'decision: limit applies after sorting (keeps totals stable)' },
  ]
  const values = [{ terms: ['DEFAULT_REPORT_LIMIT'], text: 'DEFAULT_REPORT_LIMIT = 20' }]
  const shown = mergeEngineValues(entries, values)
  assert.equal(shown.length, 1)
  assert.equal(shown[0].kind, 'decision')
})
