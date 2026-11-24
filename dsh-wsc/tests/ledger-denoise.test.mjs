import assert from 'node:assert/strict'
import test from 'node:test'

import { cleanEntryText, denoiseLedger, hasValue, subjectKey } from '../lib/ledger-denoise.js'

const entry = (kind, text, order) => ({ id: `e${order}`, kind, text, order, status: 'active' })

test('denoise: older versions of one property are folded, newest wins', () => {
  const ledger = [
    entry('fact', 'src/report.js: toCsv header = \'sku,amountCents\'', 1),
    entry('fact', 'src/report.js: toCsv header = \'sku,amountCents,amountWithTaxCents\'', 2),
    entry('decision', 'src/cli.js: options = { limit, rounding, sort }', 3),
    entry('decision', 'src/cli.js: options = { limit, rounding, sort, noHeader }', 4),
  ]
  const out = denoiseLedger(ledger)
  assert.equal(out.entries.length, 2)
  assert.equal(out.superseded, 2)
  assert.ok(out.entries.some((row) => row.text.includes('amountWithTaxCents')))
  assert.ok(out.entries.some((row) => row.text.includes('noHeader')))
})

test('denoise: different flags stay separate subjects', () => {
  const ledger = [
    entry('decision', "src/cli.js: parseArgs throws 'invalid --round value: <value>'", 1),
    entry('decision', "src/cli.js: parseArgs throws 'invalid --sort value: <value>'", 2),
  ]
  const out = denoiseLedger(ledger)
  assert.equal(out.entries.length, 2)
  assert.equal(out.superseded, 0)
})

test('denoise: a run of test counts collapses to the latest result', () => {
  const ledger = [
    entry('fact', 'npm test -- --test-isolation=none: tests 9, pass 9, fail 0', 1),
    entry('fact', 'npm test -- --test-isolation=none: tests 14, pass 14, fail 0', 2),
    entry('fact', 'npm test -- --test-isolation=none: tests 19, pass 19, fail 0', 3),
  ]
  const out = denoiseLedger(ledger)
  assert.equal(out.entries.length, 1)
  assert.equal(out.folded, 2)
  assert.match(out.entries[0].text, /tests 19/)
})

test('denoise: constraints and requirements are never folded', () => {
  const ledger = [
    entry('requirement', 'src/report.js: keep the exact SKU layout', 1),
    entry('requirement', 'src/report.js: keep the exact SKU layout in text mode', 2),
    entry('constraint', 'src/report.js: do not rename formatCents', 3),
  ]
  const out = denoiseLedger(ledger)
  assert.equal(out.entries.length, 3)
  assert.equal(out.superseded, 0)
})

test('denoise: prose without a path or call is left alone', () => {
  assert.equal(subjectKey('tests/report.test.mjs make the suite deterministic'), '')
  assert.equal(subjectKey('there is no property to replace here'), '')
  const out = denoiseLedger([entry('fact', 'plain prose note', 1)])
  assert.equal(out.entries.length, 1)
})

test('denoise: constant and camel names are the same subject', () => {
  const ledger = [
    entry('fact', 'src/report.js: REPORT_LIMIT defaults to 20 and slices rows before rendering', 1),
    entry('fact', 'src/report.js: reportLimit applies .slice after sort', 2),
  ]
  const out = denoiseLedger(ledger)
  assert.equal(out.entries.length, 1)
  assert.match(out.entries[0].text, /after sort/)
})

test('denoise: signatures with nested calls still fold by name', () => {
  const ledger = [
    entry('decision', 'src/store.js: taxCents(cents, rate = envTaxRate()), env override', 1),
    entry('decision', 'src/store.js: taxCents(cents, rate = envTaxRate(), mode = \'half-up\')', 2),
  ]
  const out = denoiseLedger(ledger)
  assert.equal(out.entries.length, 1)
  assert.match(out.entries[0].text, /half-up/)
})

test('denoise: calls with different literal arguments are different facts', () => {
  const ledger = [
    entry('fact', 'src/format.js: formatCents(-350) = -$3.50', 1),
    entry('fact', 'src/format.js: formatCents(123456789) = $1234567.89', 2),
    entry('fact', "src/report.js: toCsv([]) = 'sku,amountCents'", 3),
    entry('fact', 'src/report.js: toCsv(rows) = header plus rows', 4),
  ]
  const out = denoiseLedger(ledger)
  assert.equal(out.entries.length, 4)
  assert.equal(out.superseded, 0)
})

test('denoise: repeated sandbox failure is stated once', () => {
  const ledger = [
    entry('fact', 'npm test: result = exit code 1, Error: spawn EPERM', 1),
    entry('fact', 'npm test: errno = -4048; syscall = spawn', 2),
  ]
  const out = denoiseLedger(ledger)
  assert.equal(out.entries.length, 1)
})

test('denoise: value-bearing claims are identifiable for cap priority', () => {
  assert.equal(hasValue('src/store.js: TAX_RATE = 0.07'), true)
  assert.equal(hasValue('src/cli.js: accepts --dry-run'), true)
  assert.equal(hasValue('src/report.js: summary(rows) returns {count, totalCents}'), true)
  assert.equal(hasValue('README describes the options section'), false)
})

test('denoise: display cleanup strips double labels but keeps literal escapes', () => {
  assert.equal(cleanEntryText('decision: use cents\nfor money'), 'use cents / for money')
  assert.equal(cleanEntryText("decision: rows joined by '\\n'"), "rows joined by '\\n'")
  assert.equal(cleanEntryText('Context:  plain   text'), 'plain text')
})
