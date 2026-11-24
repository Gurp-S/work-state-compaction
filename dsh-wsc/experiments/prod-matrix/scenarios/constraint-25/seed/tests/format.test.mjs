import test from 'node:test'
import assert from 'node:assert/strict'
import { formatAmount } from '../src/format.js'

test('formats positive amounts with two decimals and a dollar sign', () => {
  assert.equal(formatAmount(12.5), '$12.50')
  assert.equal(formatAmount(3.256), '$3.26')
})
