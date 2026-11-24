import test from 'node:test'
import assert from 'node:assert/strict'
import { formatAmount, formatCents } from '../src/format.js'

test('formats positive amounts with two decimals and a dollar sign', () => {
  assert.equal(formatAmount(12.5), '$12.50')
  assert.equal(formatAmount(3.256), '$3.26')
})

test('formatCents converts integer cents to a dollar string', () => {
  assert.equal(formatCents(1250), '$12.50')
  assert.equal(formatCents(3256), '$32.56')
  assert.equal(formatCents(5), '$0.05')
  assert.equal(formatCents(0), '$0.00')
  assert.equal(formatCents(100), '$1.00')
})

test('formatCents puts the minus sign before the dollar sign', () => {
  assert.equal(formatCents(-350), '-$3.50')
  assert.equal(formatCents(-5), '-$0.05')
})
