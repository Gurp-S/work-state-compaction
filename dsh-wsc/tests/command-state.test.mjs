import assert from 'node:assert/strict'
import test from 'node:test'

import { classifyCommands, renderCommandState } from '../lib/command-state.js'
import { capLedger, renderPassage } from '../lib/passage.js'

const state = {
  done: ['req#2 (edit #17, check #23)', 'req#3 (edit #21, check #24)', 'req#4 (edit #30, check #31)'],
  open: [],
  next: ['req#6; complete the latest request: add --dry-run'],
  unknown: [],
}

test('command-state: the first real command stays verbatim, later ones become status lines', () => {
  const controls = [
    'Read src/format.js and summarize it.',
    'Add formatCents to src/format.js.',
    'Add TAX_RATE = 0.07 to src/store.js.',
    'Change src/report.js to use taxCents.',
    'Update README options.',
    'Add --dry-run to src/cli.js.',
  ]
  const records = classifyCommands(controls, state)
  const text = renderCommandState(records, { doneLines: 3, sectionBytes: 1800 })
  assert.match(text, /^Origin command \(#1\): "Read src\/format\.js and summarize it\."/)
  assert.doesNotMatch(text, /"Add formatCents to src\/format\.js\."/)
  assert.match(text, /#2 done \(edit #17, check #23\): Add formatCents/)
  assert.match(text, /#3 done \(edit #21, check #24\)/)
  assert.match(text, /#6 next: "Add --dry-run to src\/cli\.js\."/)
  assert.match(text, /#5 recorded: Update README options/)
})

test('command-state: only the newest completed lines are kept and the section is bounded', () => {
  const controls = ['Origin task.']
  for (let index = 2; index <= 42; index += 1) controls.push(`Add feature ${index} to src/report.js.`)
  const done = controls.slice(1).map((_, position) => `req#${position + 2} (edit #${100 + position}, check #${200 + position})`)
  const records = classifyCommands(controls, { done, open: [], next: [], unknown: [] })
  const text = renderCommandState(records, { doneLines: 3, sectionBytes: 1800 })
  assert.ok(Buffer.byteLength(text) <= 1800, `section is ${Buffer.byteLength(text)} bytes`)
  assert.match(text, /#42 done/)
  assert.doesNotMatch(text, /#30 done/)
  assert.match(text, /earlier completed\/superseded commands omitted/)
})

test('command-state: a verified done command is not relabelled by a later independent change', () => {
  const controls = [
    'Origin task.',
    'Add formatCents to src/format.js.',
    'Change src/report.js to use formatCents.',
  ]
  const records = classifyCommands(controls, {
    done: ['req#2 (edit #17, check #23)'], open: [], next: [], unknown: [],
  })
  const text = renderCommandState(records, { doneLines: 3 })
  assert.match(text, /#2 done \(edit #17, check #23\): Add formatCents/)
  assert.doesNotMatch(text, /later changed/)
})

test('command-state: an unmatched command replaced by a later change is superseded, never quoted in full', () => {
  const controls = [
    'Origin task.',
    'Add REPORT_LIMIT support to src/report.js.',
    'Change REPORT_LIMIT handling in src/report.js to 50 instead.',
  ]
  const records = classifyCommands(controls, { done: [], open: [], next: [], unknown: [] })
  const text = renderCommandState(records, { doneLines: 3 })
  assert.match(text, /#2 superseded by #3/)
  assert.doesNotMatch(text, /"Add REPORT_LIMIT support to src\/report\.js\."/)
})

test('command-state: acknowledgements are skipped when choosing the origin', () => {
  const records = classifyCommands(['continue', 'Sure.', 'Build the CSV export.'], {
    done: [], open: [], next: [], unknown: [],
  })
  assert.equal(records[0].status, 'origin')
  assert.equal(records[0].no, 3)
})

test('command-state: a historical edit with a later check proves completion over an open projection', () => {
  const controls = [
    { text: 'Origin task.', seq: 1 },
    { text: 'Add formatCents to src/format.js.', seq: 10 },
    { text: 'Change src/report.js to use formatCents.', seq: 30 },
  ]
  const records = classifyCommands(controls, {
    done: [], open: ['req#2; latest edit to src/format.js wrote something else'],
    next: [], unknown: [],
  }, {
    receipts: [
      { path: 'src/format.js', edit: 17, check: null, terms: ['formatCents', 'src/format.js'] },
      { path: 'src/format.js', edit: 40, check: null, terms: ['formatCents', 'src/format.js'] },
    ],
    checks: [23, 41],
  })
  const text = renderCommandState(records, { doneLines: 3 })
  assert.match(text, /#2 done \(edit #17, check #23\): Add formatCents/)
})

test('command-state: the ledger cap keeps high rank and newest entries', () => {
  const ledger = [
    { id: 'a', kind: 'constraint', text: 'keep the output format', status: 'active', seq: 1 },
    ...Array.from({ length: 40 }, (_, index) => ({
      id: `f${index}`, kind: 'fact', text: `old fact number ${index} about a file`, status: 'active', seq: 10 + index,
    })),
    { id: 'z', kind: 'fact', text: 'newest fact with an exact value', status: 'active', seq: 99 },
  ]
  const capped = capLedger(ledger, 600)
  assert.ok(capped.omitted > 0)
  assert.ok(capped.entries.some((entry) => entry.kind === 'constraint'))
  assert.ok(capped.entries.some((entry) => entry.seq === 99))
  assert.ok(!capped.entries.some((entry) => entry.seq === 10))
})

test('command-state: passage renders the block without a verbatim requirement list', () => {
  const controls = [
    'Read src/a.js and summarize.',
    'Add formatCents to src/format.js.',
    'Add --dry-run to src/cli.js.',
  ]
  const records = classifyCommands(controls, {
    done: ['req#2 (edit #17, check #23)'], open: [], next: ['req#3; complete the latest request'],
    unknown: [],
  })
  const block = renderCommandState(records, {})
  const text = renderPassage({
    control: [], commandState: block, latestControl: controls.at(-1), ledger: [], budget: 4000,
  })
  assert.match(text, /Origin command \(#1\)/)
  assert.match(text, /Command state:/)
  assert.doesNotMatch(text, /User requirements, quoted verbatim/)
  assert.match(text, /Latest request: "Add --dry-run/)
})
