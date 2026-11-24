import test from 'node:test'
import assert from 'node:assert/strict'
import { TAX_RATE, taxCents, lineTotal, lineTotals } from '../src/store.js'

test('taxCents applies the 7% tax rate to cents', () => {
  assert.equal(TAX_RATE, 0.07)
  assert.equal(taxCents(1000), 70)
})

test('taxCents accepts an optional rate parameter', () => {
  assert.equal(taxCents(1000, 0.2), 200)
})

test('lineTotal multiplies unit price by quantity', () => {
  assert.equal(lineTotal({ sku: 'A-100', unitPrice: 12.5, quantity: 2 }), 25)
})

test('lineTotals maps every line to sku and total', () => {
  const order = {
    lines: [
      { sku: 'A-100', unitPrice: 12.5, quantity: 2 },
      { sku: 'B-200', unitPrice: 3.25, quantity: 4 },
    ],
  }
  assert.deepEqual(lineTotals(order), [
    { sku: 'A-100', total: 25 },
    { sku: 'B-200', total: 13 },
  ])
})
