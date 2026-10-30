import { test } from 'node:test'
import assert from 'node:assert/strict'
import { shellEnvelope } from './audit_runtime_denoise.mjs'

test('structured source evidence is not classified as shell output', () => {
  assert.equal(shellEnvelope(JSON.stringify({status:'ok', source:'s45', text:'source', output:'accidental'})),null)
})
test('failure status survives extraction and is not guessed from prose', () => {
  const e = {chunk_id:'x', wall_time_seconds:0.1, exit_code:1, output:'all good'}
  assert.deepEqual(shellEnvelope(JSON.stringify(e)),e)
  assert.equal(shellEnvelope(JSON.stringify({...e,exit_code:null})),null)
})
test('plain text and malformed envelopes stay unclassified', () => {
  for (const text of ['passed', '{', 'null', '[]', '{"output":"log","exit_code":0}']) {
    assert.equal(shellEnvelope(text),null)
  }
})
test('known parallel wrappers expose objects but never recursively parse source strings', () => {
  const e = {chunk_id:'x', wall_time_seconds:1, exit_code:0, output:'source'}
  for (const v of [{part:0,status:'fulfilled',value:e}, {i:0,result:{status:'fulfilled',value:e}}, {index:0,result:{status:'fulfilled',value:e}}]) {
    assert.deepEqual(shellEnvelope(JSON.stringify(v)),e)
  }
  assert.equal(shellEnvelope(JSON.stringify({part:0,status:'fulfilled',value:JSON.stringify(e)})),null)
})
