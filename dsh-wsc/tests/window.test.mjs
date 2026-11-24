import test from 'node:test'
import assert from 'node:assert/strict'
import { capacityWindow } from '../lib/window.js'

test('caps a large model window at the configured working window', () => {
  assert.equal(capacityWindow(1_000_000, 256_000), 256_000)
})

test('never exceeds a model window smaller than the configured cap', () => {
  assert.equal(capacityWindow(32_768, 256_000), 32_768)
})

test('zero disables the extra cap', () => {
  assert.equal(capacityWindow(1_000_000, 0), 1_000_000)
})

test('invalid caps fall back to the model window', () => {
  assert.equal(capacityWindow(1_000_000, -1), 1_000_000)
  assert.equal(capacityWindow(1_000_000, 1.5), 1_000_000)
  assert.equal(capacityWindow(1_000_000, undefined), 1_000_000)
})

test('an unusable model window stays zero', () => {
  assert.equal(capacityWindow(0, 256_000), 0)
  assert.equal(capacityWindow(undefined, 256_000), 0)
})
