import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildJsonReport,
  buildReport,
  renderReport,
  summary,
  toCsv,
  totalCents,
} from '../src/report.js'

const order = {
  lines: [
    { sku: 'A-100', unitPrice: 12.5, quantity: 2 },
    { sku: 'B-200', unitPrice: 3.25, quantity: 4 },
  ],
}

test('buildReport shows each line total in cents including tax', () => {
  assert.deepEqual(buildReport(order), ['A-100  $26.75', 'B-200  $13.91'])
})

test('renderReport joins rows with newlines keeping the SKU  $amount layout', () => {
  assert.equal(
    renderReport(order),
    'A-100  $26.75\nB-200  $13.91\nTOTAL $40.66',
  )
})

test('totalCents sums the taxed amountCents of the given rows', () => {
  assert.equal(
    totalCents([
      { sku: 'A-100', amountCents: 2675 },
      { sku: 'B-200', amountCents: 1391 },
    ]),
    4066,
  )
  assert.equal(totalCents([]), 0)
})

test('summary returns the row count and summed amountCents', () => {
  assert.deepEqual(summary(buildJsonReport(order).rows), {
    count: 2,
    totalCents: 4066,
  })
  assert.deepEqual(summary([]), { count: 0, totalCents: 0 })
})

test('options.limit overrides REPORT_LIMIT', () => {
  const previous = process.env.REPORT_LIMIT
  try {
    process.env.REPORT_LIMIT = '2'
    assert.deepEqual(buildReport(order, { limit: 1 }), ['A-100  $26.75'])
  } finally {
    if (previous === undefined) {
      delete process.env.REPORT_LIMIT
    } else {
      process.env.REPORT_LIMIT = previous
    }
  }
})

test('buildJsonReport returns rows plus a summary of those rows', () => {
  assert.deepEqual(buildJsonReport(order), {
    rows: [
      { sku: 'A-100', amountCents: 2675 },
      { sku: 'B-200', amountCents: 1391 },
    ],
    summary: { count: 2, totalCents: 4066 },
  })
})

test('rows are sorted by amountCents descending in text and JSON', () => {
  const unsorted = {
    lines: [
      { sku: 'B-200', unitPrice: 3.25, quantity: 4 },
      { sku: 'C-300', unitPrice: 99.99, quantity: 1 },
      { sku: 'A-100', unitPrice: 12.5, quantity: 2 },
    ],
  }
  assert.deepEqual(buildReport(unsorted), [
    'C-300  $106.99',
    'A-100  $26.75',
    'B-200  $13.91',
  ])
  assert.deepEqual(
    buildJsonReport(unsorted).rows.map((row) => row.sku),
    ['C-300', 'A-100', 'B-200'],
  )
})

test('toCsv renders a header and one row per item with no trailing newline', () => {
  const rows = [
    { sku: 'A-100', amountCents: 2675 },
    { sku: 'B-200', amountCents: 1391 },
  ]
  const csv = toCsv(rows)
  assert.equal(csv, 'sku,amountCents\nA-100,2675\nB-200,1391')
  assert.ok(!csv.endsWith('\n'))
  assert.equal(toCsv([]), 'sku,amountCents')
})

test('toCsv rejects negative amounts with a clear error', () => {
  assert.throws(
    () =>
      toCsv([
        { sku: 'A-100', amountCents: 2675 },
        { sku: 'N-500', amountCents: -350 },
      ]),
    {
      message: 'negative amounts are not allowed in CSV export: N-500',
    },
  )
})

test('an empty order renders no text output', () => {
  assert.equal(renderReport({ lines: [] }), '')
})

test('toCsv on an empty report returns only the header', () => {
  assert.equal(
    toCsv(buildJsonReport({ lines: [] }).rows),
    'sku,amountCents',
  )
})

test('a zero-amount line renders as $0.00 and is included in the total', () => {
  const free = { lines: [{ sku: 'Z-900', unitPrice: 0, quantity: 3 }] }
  assert.equal(renderReport(free), 'Z-900  $0.00\nTOTAL $0.00')
  assert.deepEqual(buildJsonReport(free), {
    rows: [{ sku: 'Z-900', amountCents: 0 }],
    summary: { count: 1, totalCents: 0 },
  })
})

test('REPORT_LIMIT caps the number of rows', () => {
  const previous = process.env.REPORT_LIMIT
  try {
    process.env.REPORT_LIMIT = '1'
    assert.deepEqual(buildReport(order), ['A-100  $26.75'])
  } finally {
    if (previous === undefined) {
      delete process.env.REPORT_LIMIT
    } else {
      process.env.REPORT_LIMIT = previous
    }
  }
})


test('limit keeps the highest rows after sorting', () => {
  const unsorted = {
    lines: [
      { sku: 'B-200', unitPrice: 3.25, quantity: 4 },
      { sku: 'C-300', unitPrice: 99.99, quantity: 1 },
      { sku: 'A-100', unitPrice: 12.5, quantity: 2 },
    ],
  }
  assert.deepEqual(
    buildJsonReport(unsorted, { limit: 2 }).rows.map((row) => row.sku),
    ['C-300', 'A-100'],
  )
})
