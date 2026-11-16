import assert from 'node:assert/strict'
import test from 'node:test'

import { buildCheckpoint, buildSelectiveCheckpoint } from '../lib/checkpoint.js'
import { trimErrorStack } from '../lib/denoise.js'
import { fitRuntimeReceipts, prepareContinuity } from '../lib/continuity.js'
import { assertCheckpointState, fitCheckpointState, preservePriorOpenScope, readCheckpointState } from '../lib/checkpoint-state.js'
import { receiptWriteOrder } from '../lib/receipt-write-order.js'

const text = (value) => [{ type: 'text', text: value }]

test('command write order distinguishes prior and overlapping observations without assigning a version', () => {
  const pair = (name, status, call, receipt) => ({
    call: { name, status }, callEvent: { seq: call }, receipt: { seq: receipt },
  })
  const command = pair('pwsh', 'passed', 10, 20)
  const pairs = new Map([
    ['prior', pair('write', 'passed', 1, 2)],
    ['overlap', pair('edit', 'passed', 8, 13)],
    ['failed', pair('write', 'failed', 3, 9)],
    ['after', pair('write', 'passed', 21, 22)],
    ['check', command],
  ])
  assert.deepEqual(receiptWriteOrder(pairs, command), {
    call_seq: 10, receipt_seq: 20, latest_prior_write_receipt_seq: 2,
    overlapping_write_receipt_seqs: [13], overlapping_write_receipts_omitted: 0,
    file_coverage: 'unknown', tested_version: 'unknown',
  })
})

test('partial updates carry untouched open work through another handoff and budget fitting', () => {
  const previous = { done: [], open: ['Check input', 'Validate output'], next: ['Run checks'], unknown: [] }
  const update = { done: [], open: ['Check input'], next: ['Open input'], unknown: [] }
  const first = preservePriorOpenScope(update, previous)
  assert.deepEqual(first.open, update.open)
  assert.deepEqual(first.unknown, ['Previous open item; no transition in current account: Validate output'])
  const second = preservePriorOpenScope({ ...update, done: ['Earlier details '.repeat(100)] }, first)
  const packed = fitCheckpointState(second, 320)
  assert.ok(packed)
  assert.ok(packed.unknown.includes(first.unknown[0]))
  assert.equal(fitCheckpointState(second, 140), null)
})
const user = (value) => ({ role: 'user', content: text(value), source: { kind: 'user' } })

const region = () => {
  const body = Array.from({ length: 400 }, (_, index) => `const value${index} = ${index * 7}`).join('\n')
  return {
    messages: [
      user('Ship the --watch flag.'),
      { role: 'assistant', content: text('Reading the file.') },
      { role: 'tool', content: text(body), toolCallId: 'c1' },
    ],
    quote: body.split('\n').slice(0, 20).join('\n'),
  }
}

test('continuity keeps the model-written state narrative', () => {
  const { messages, quote } = region()
  const built = buildSelectiveCheckpoint(
    { messages },
    {
      quotes: [quote],
      state: 'Done: the flag is implemented. Open: the two-run byte comparison. Unknown: none.',
      payload: { sourceFraction: 0.9 },
      continuity: {
        bytes: 0,
        control: '## User requests and instructions (verbatim, control)\n- Ship the --watch flag.',
        runtime: '## Runtime receipts (session event sequences)\n- write "x" (call #1, receipt #2: completed)',
        receiptLinks: new Map(),
      },
    },
  )
  assert.notEqual(built, null)
  assert.match(built.text, /## Current state/)
  assert.match(built.text, /Done: the flag is implemented/)
  assert.match(built.text, /## Runtime receipts/)
})

test('selective checkpoint without state is rejected when state is required', () => {
  const quote = 'The source file was changed; the check has not run yet.'
  const built = buildSelectiveCheckpoint(
    { messages: [{ role: 'assistant', content: text(quote + ' context'.repeat(300)) }] },
    { quotes: [quote], requireState: true },
  )
  assert.equal(built, null)
})

test('deterministic fallback carries the previous state narrative', () => {
  const prior = [
    '## Current state (model account; unverified)',
    '- The rename is done; the visible test has not run.',
    '',
    '## Selected excerpts (verbatim; role prefix shows the speaker)',
    '- [s1] [tool:read] old evidence',
  ].join('\n')
  const messages = [
    { role: 'user', source: { kind: 'checkpoint' }, content: text(prior) },
    user('Continue.'),
  ]
  const built = buildCheckpoint({ messages }, { isCheckpointSource: (source) => source?.kind === 'checkpoint' })
  assert.match(built.text, /## Current state/)
  assert.match(built.text, /The rename is done; the visible test has not run\./)
})

test('continuity returns the previous state narrative', () => {
  const prior = [
    '## Current state (model account; unverified)',
    '- The rename is done; the visible test has not run.',
  ].join('\n')
  const checkpoint = { role: 'user', source: { kind: 'checkpoint', compactionId: 'c1' }, content: text(prior) }
  const session = {
    events: [
      { seq: 1, type: 'compaction/summary', data: { compactionId: 'c1', shadowedSeqs: [] } },
      { seq: 2, type: 'user/message', data: checkpoint },
    ],
    deriveEventMessage: (event) => event.data,
  }
  const view = prepareContinuity({ messages: [checkpoint] }, session, (source) => source?.kind === 'checkpoint')
  assert.match(view.state, /The rename is done/)
  const withoutState = { ...checkpoint, content: text('A newer checkpoint without structured state.') }
  const newer = prepareContinuity({ messages: [checkpoint, withoutState] }, session,
    (source) => source?.kind === 'checkpoint')
  assert.equal(newer.state, '')
})

test('active publication requires structured state actually present in the budgeted summary', () => {
  const { messages, quote } = region()
  const state = { done: [], open: ['Byte comparison'], next: ['Compare two output files'], unknown: [] }
  const options = { quotes: [quote], toolText: true, structuredState: true, requireState: true,
                    payload: { sourceFraction: 0.9 } }
  assert.equal(buildSelectiveCheckpoint({ messages }, { ...options, state: {...state, next: []} }), null)
  const checkpoint = buildSelectiveCheckpoint({ messages }, { ...options, state })
  assert.ok(checkpoint)
  assert.equal(checkpoint.text.indexOf('## Current state') < checkpoint.text.indexOf('## Evidence'), true)
  assert.deepEqual(readCheckpointState(checkpoint.text), state)
  assert.doesNotThrow(() => assertCheckpointState({ state, summary: text(checkpoint.text) }))
  assert.throws(() => assertCheckpointState({ state, summary: text('## Selected excerpts\n- evidence only') }),
                /state_required/)
  assert.equal(buildSelectiveCheckpoint({ messages }, { ...options, state, stateCap: 30 }), null)
})

test('selective publication fits supporting receipts after state and selected evidence', () => {
  const { messages, quote } = region()
  const state = { done: [], open: ['Byte comparison'], next: ['Compare outputs'], unknown: [] }
  const runtime = `## Runtime receipts\n- ${'Long receipt '.repeat(4000)}\n- read "input.json"`
  const continuity = { bytes: Buffer.byteLength(runtime) + 2, control: '', runtime }
  const checkpoint = buildSelectiveCheckpoint({ messages }, {
    quotes: [quote], toolText: true, state, structuredState: true, requireState: true, continuity,
  })
  assert.ok(checkpoint)
  assert.deepEqual(checkpoint.state, state)
  assert.equal(checkpoint.selectedCount, 1)
  assert.match(checkpoint.text, /read "input.json"/)
  assert.match(checkpoint.text, /Runtime rows omitted/)
  assert.ok(Buffer.byteLength(checkpoint.text) <= checkpoint.budget)
})

test('fallback carries prior state with its historical scope across repeated checkpoints', () => {
  const isCheckpointSource = source => source?.kind === 'checkpoint'
  const prior = { done: ['Earlier version passed.'], open: [], next: [], unknown: [] }
  const { messages, quote } = region()
  const options = { structuredState: true, isCheckpointSource, payload: { sourceFraction: 0.9 } }
  const first = buildSelectiveCheckpoint({ messages }, { ...options, state: prior, quotes: [quote] })
  const fallback = previous => buildCheckpoint({ messages: [
    { role: 'user', content: text(previous.text), source: { kind: 'checkpoint' } },
    ...messages,
  ] }, options)
  const second = fallback(first)
  const third = fallback(second)
  assert.deepEqual(second.state.done, prior.done)
  assert.match(second.state.unknown[0], /Current applicability unverified/)
  assert.deepEqual(second.state, third.state)
})

test('fallback carries continuity state when the projected region omits the prior checkpoint', () => {
  const { messages } = region()
  const prior = { done: [], open: ['Byte comparison'], next: ['Read both output files'], unknown: [] }
  const checkpoint = buildCheckpoint({ messages }, { structuredState: true, continuity: { state: prior } })
  assert.deepEqual(checkpoint.state.open, prior.open)
  assert.deepEqual(checkpoint.state.next, prior.next)
  assert.match(checkpoint.state.unknown[0], /Current applicability unverified/)
  assert.doesNotThrow(() => assertCheckpointState({ state: checkpoint.state, summary: text(checkpoint.text) }))
})

test('carried state is emitted once while prior-only evidence remains available', () => {
  const { messages, quote } = region()
  const prior = { done: ['Earlier version passed.'], open: ['Verify current version.'],
    next: ['Read test receipt.'], unknown: [] }
  const options = { structuredState: true, isCheckpointSource: source => source?.kind === 'checkpoint',
    payload: { sourceFraction: 0.9, priorItemCap: 2400 } }
  const previous = buildSelectiveCheckpoint({ messages }, { ...options, state: prior, quotes: [quote] })
  const history = { messages: [
    { role: 'user', content: text(previous.text + '\n\n## Archive evidence\nUnique earlier receipt.'), source: { kind: 'checkpoint' } },
    ...messages,
  ] }
  for (const build of [buildCheckpoint, buildSelectiveCheckpoint]) {
    const before = build(history, { ...options, quotes: [quote] })
    const after = build(history, { ...options, quotes: [quote], dedupeCarriedState: true })
    assert.deepEqual(after.state, before.state)
    assert.match(after.text, /Unique earlier receipt\./)
    assert.equal(before.text.split('Earlier version passed.').length - 1, 2)
    assert.equal(after.text.split('Earlier version passed.').length - 1, 1)
    assert.ok(Buffer.byteLength(after.text) < Buffer.byteLength(before.text))
    assert.doesNotThrow(() => assertCheckpointState({ state: after.state, summary: text(after.text) }))
  }
  const changed = buildSelectiveCheckpoint(history, { ...options, quotes: [quote], dedupeCarriedState: true,
    state: { ...prior, done: ['New version built.'] } })
  assert.match(changed.text, /Earlier version passed\./)
})

test('fallback fits whole recovery receipts and discloses omitted runtime rows', () => {
  const runtime = '## Runtime receipts\n- ' + 'long command '.repeat(100) +
    '\n- read "HISTORY.md" (call #2, receipt #3)'
  const fitted = fitRuntimeReceipts(runtime, 140)
  assert.ok(Buffer.byteLength(fitted) <= 140)
  assert.match(fitted, /read "HISTORY.md" \(call #2, receipt #3\)/)
  assert.match(fitted, /Runtime rows omitted due to checkpoint budget/)
  assert.doesNotMatch(fitted, /long command/)
})

test('fallback keeps pending work with its next step when earlier completion details exceed budget', () => {
  const { messages } = region()
  const state = { done: ['Old result '.repeat(140).trim()], open: ['Verify file version.'],
    next: ['Compare the current file with the verification input.'], unknown: [] }
  const candidate = buildCheckpoint({ messages }, { state, structuredState: true })
  assert.deepEqual(candidate.state.open, state.open)
  assert.deepEqual(candidate.state.next, state.next)
  assert.deepEqual(candidate.state.done, [])
  assert.match(candidate.state.unknown[0], /omitted due to checkpoint budget/)
  assert.doesNotThrow(() => assertCheckpointState({ state: candidate.state, summary: text(candidate.text) }))
  const tooSmall = buildCheckpoint({ messages }, { state, structuredState: true, stateCap: 80 })
  assert.equal(tooSmall.state, null)
  assert.equal(tooSmall.text, '')
})

test('error stack trim keeps the message and boundary frames', () => {
  const frames = Array.from({ length: 20 }, (_, index) => `    at frame${index} (file.js:${index + 1}:1)`)
  const input = ['Error: spawn EPERM', '    at ChildProcess.spawn (node:child_process:421:11)', ...frames].join('\n')
  const output = trimErrorStack(input)
  assert.match(output, /spawn EPERM/)
  assert.match(output, /stack frames omitted/)
  assert.match(output, /frame0/)
  assert.match(output, /frame19/)
  assert.ok(output.length < input.length)
  assert.equal(trimErrorStack('plain output\nno frames'), 'plain output\nno frames')
})

test('continuity drops listings and keeps the latest same-command attempt', () => {
  const call = (seq, id, command) => ({
    seq,
    type: 'assistant/message',
    data: { role: 'assistant', content: [{ type: 'tool-call', id, name: 'pwsh', arguments: { command } }] },
  })
  const result = (seq, id, body, isError = false) => ({
    seq,
    type: 'tool/result',
    data: {
      role: 'user',
      content: [{ type: 'tool-result', toolCallId: id, isError, content: [{ type: 'text', text: body }] }],
    },
  })
  const session = {
    events: [
      call(1, 'list', 'Get-ChildItem -Force'),
      result(2, 'list', 'a\nb\nc'),
      call(3, 'verify-failed', "$script = @'\nGet-Content a"),
      result(4, 'verify-failed', 'Error: boom', true),
      call(5, 'verify-passed', "$script = @'\nGet-Content a"),
      result(6, 'verify-passed', 'all assertions passed'),
    ],
    deriveEventMessage: (event) => event.data,
  }
  const view = prepareContinuity({ messages: [] }, session, () => false)
  assert.doesNotMatch(view.runtime, /Get-ChildItem/)
  assert.equal(view.runtime.match(/\$script/g)?.length, 1)
  assert.match(view.runtime, /completed/)
  assert.doesNotMatch(view.runtime, /failed/)
})
