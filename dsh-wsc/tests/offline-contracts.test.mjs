import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildVerificationState, buildSelectiveCheckpoint, mandatoryLowerBound } from '../lib/checkpoint.js'

const call = (id, name, args) => ({role: 'assistant', content: [{type: 'tool-call', id, name, arguments: JSON.stringify(args)}]})
const result = (id, isError = false, role = 'user') => role === 'tool'
  ? {role, toolCallId: id, isError, content: [{type: 'text', text: 'completed operation'}]}
  : {role, source: {kind: 'tool', callId: id}, content: [{type: 'tool-result', toolCallId: id, isError, content: [{type: 'text', text: 'completed operation'}]}]}

test('failed or unfinished checks never certify a changed file', () => {
  for (const completion of [[], [result('t', true)], [result('t', true, 'tool')]]) {
    const rows = buildVerificationState([call('w', 'write', {file_path: 'a.js', content: 'new'}), result('w'), call('t', 'pwsh', {command: 'npm test'}), ...completion])
    assert.ok(rows.every(x => !x.includes('→ completed') && !x.includes('verified after that change: yes')))
  }
})

test('a completed check reports process status without asserting file coverage', () => {
  for (const role of ['user', 'tool']) {
    const rows = buildVerificationState([call('w', 'write', {file_path: 'billing.js', content: 'new'}), result('w', false, role), call('t', 'pwsh', {command: 'npm test tests/theme.js'}), result('t', false, role)])
    assert.ok(rows[0].includes('→ completed'))
    assert.ok(!rows[0].includes('verified after that change: yes'))
    assert.ok(rows[0].includes('file coverage: unknown'))
  }
})

test('a rejected mutation is not recorded as a file change', () => {
  assert.deepEqual(buildVerificationState([call('w', 'write', {file_path: 'a.js', content: 'new'}), result('w', true)]), [])
})

test('an unfinished mutation stays explicitly unconfirmed', () => {
  const rows = buildVerificationState([call('w', 'write', {file_path: 'a.js', content: 'new'})])
  assert.ok(rows[0].includes('outcome: unknown'))
  assert.ok(!rows[0].includes('last write at'))
})

test('foreground exit markers and interruptions are not tool-level success', () => {
  for (const marker of ['[exit code: 1]', '[exit code: -1]', '[timed out after 10ms]', '[killed by signal: TERM]']) {
    const completed = result('t')
    completed.content[0].content[0].text = 'command output\n' + marker
    const rows = buildVerificationState([call('w', 'write', {file_path: 'a.js', content: 'new'}), result('w'), call('t', 'pwsh', {command: 'npm test'}), completed])
    assert.ok(!rows[0].includes('→ completed'))
  }
})

test('background acknowledgement never establishes command completion', () => {
  const rows = buildVerificationState([call('w', 'write', {file_path: 'a.js', content: 'new'}), result('w'), call('t', 'bash', {command: 'npm test', run_in_background: true}), result('t')])
  assert.ok(rows[0].includes('→ unknown'))
})

test('shell observations do not depend on guessed test command names', () => {
  for (const command of ['node --test tests/basic.mjs', 'node .verify.mjs', 'custom-runner local-plan']) {
    const rows = buildVerificationState([call('w', 'write', {file_path: 'a.js', content: 'new'}), result('w'), call('t', 'pwsh', {command}), result('t')])
    assert.ok(rows[0].includes('latest command'))
    assert.ok(rows[0].includes(command))
    assert.ok(rows[0].includes('→ completed'))
    assert.ok(rows[0].includes('file coverage: unknown'))
  }
})

test('tool quote and fragment bind to the same projected bytes', () => {
  const evidence = 'The check failed for the current version.'
  const message = {role: 'user', source: {kind: 'tool', callId: 't'}, content: [{type: 'tool-result', toolCallId: 't', content: [{type: 'text', text: evidence}], isError: true}]}
  const quote = buildSelectiveCheckpoint({messages: [message]}, {toolText: true, quotes: [evidence]})
  const fragment = buildSelectiveCheckpoint({messages: [message]}, {toolText: true, fragments: [{source: 'm1', text: evidence}]})
  assert.equal(quote?.selectedCount, 1)
  assert.equal(fragment?.selectedCount, 1)
  assert.equal(quote?.text, fragment?.text)
})

test('preflight prices actual policy and UTF-8 control bytes', () => {
  const evidence = 'The implementation and its check are recorded.'
  const input = {messages: [{role: 'user', source: {kind: 'user'}, content: [{type: 'text', text: '保留要求。'.repeat(250)}]}, {role: 'assistant', content: [{type: 'text', text: evidence + ' details'.repeat(500)}]}]}
  const options = {controlItemCap: 0, payload: {maxChars: 900}}
  const bound = mandatoryLowerBound(input, options)
  const built = buildSelectiveCheckpoint(input, {...options, quotes: [evidence]})
  assert.equal(built, null, 'a checkpoint with no room for complete selected evidence is rejected')
  assert.ok(bound.mandatoryBytes >= bound.budget)
})
