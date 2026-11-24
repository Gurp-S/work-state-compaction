import assert from 'node:assert/strict'
import test from 'node:test'

import { renderPassage } from '../lib/passage.js'
import { requirementBoard, requirementBoardText } from '../lib/requirement-board.js'

const control = (text, seq) => ({ text, seq })

test('coverage: an edit after the request covers it, and a later check marks it checked', () => {
  const board = requirementBoard(
    [control('Add formatCents to src/format.js and run npm test.', 100)],
    [{ path: 'src/format.js', edit: 140, check: 160, terms: ['formatCents'] }],
  )
  assert.deepEqual(board, { total: 1, covered: 1, checked: 1, missing: [] })
})

test('coverage: an edit recorded before the request or without matching evidence does not cover', () => {
  const controls = [
    control('Add formatCents to src/format.js.', 300),
    control('Add toCsv to src/report.js.', 400),
  ]
  const receipts = [
    { path: 'src/format.js', edit: 140, check: 160, terms: ['formatCents'] },
    { path: 'src/cli.js', edit: 480, check: 500, terms: ['parseArgs'] },
  ]
  const board = requirementBoard(controls, receipts)
  assert.equal(board.covered, 0, 'the formatCents edit predates its request and toCsv has no receipt')
  assert.deepEqual(board.missing, [1, 2])
})

test('coverage: a flag matches the camelCase term the edit recorded', () => {
  const board = requirementBoard(
    [control('Add --no-header to suppress the text header; update tests.', 10)],
    [{ path: 'src/cli.js', edit: 20, check: 30, terms: ['noHeader', 'header'] }],
  )
  assert.equal(board.covered, 1)
})

test('coverage: README and CHANGELOG name their files without an extension', () => {
  const board = requirementBoard(
    [control('Add a README section documenting --limit and --json.', 10)],
    [{ path: 'README.md', edit: 20, check: 30, terms: ['README'] }],
  )
  assert.equal(board.covered, 1)
})

test('coverage: a report-only request is not work, even with a "do not change" tail', () => {
  const board = requirementBoard([
    control('Run npm test and report the exact test count and any failures. Do not change files.', 10),
    control('Add summary(rows) to src/report.js.', 20),
  ], [])
  assert.equal(board.total, 1, 'only the real change request counts')
  assert.deepEqual(board.missing, [2])
})

test('coverage: text names the counts and the requests with no recorded edit', () => {
  const text = requirementBoardText(requirementBoard([
    control('Add formatCents to src/format.js.', 10),
    control('Add toCsv to src/report.js.', 20),
  ], [{ path: 'src/format.js', edit: 30, check: 40, terms: ['formatCents'] }]))
  assert.match(text, /^## Requirement coverage \(mechanical\)\n1\/2 work requests have an edit recorded/)
  assert.match(text, /each with a later check\./)
  assert.match(text, /No recorded edit yet: #2\./)
  assert.equal(requirementBoardText(requirementBoard([], [])), '')
})

test('passage: the board sits between the quotes and the ledger', () => {
  const text = renderPassage({
    control: ['Add a flag'],
    board: '## Requirement coverage (mechanical)\n1/1 work requests have an edit recorded, each with a later check.',
    ledger: [{ kind: 'fact', text: 'src/store.js: TAX_RATE = 0.07', seq: 1 }],
    budget: 4096,
  })
  const parts = text.split('\n\n').map((part) => part.split('\n')[0])
  assert.deepEqual(parts, [
    'User requirements, quoted verbatim: "Add a flag".',
    '## Requirement coverage (mechanical)',
    'Ledger (current): Context: src/store.js: TAX_RATE = 0.07.',
  ])
})
