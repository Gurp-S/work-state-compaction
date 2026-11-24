import test from 'node:test'
import assert from 'node:assert/strict'
import {
  collapseStack, compactCommandOutput, createDenoiseState, resetDenoiseState, runtimeDenoise,
  truncateHeadTail,
} from '../lib/denoise.js'

const pytestLog = [
  '============================= test session starts =============================',
  'collected 80 items',
  ...Array.from({ length: 220 }, (_, i) => `tests/test_${i}.py ....... [ ${i + 1}%]`),
  '=================================== FAILURES ===================================',
  '_________________________________ test_report __________________________________',
  '    def test_report():',
  '>       assert report()["total"] == 500',
  'E       AssertionError: 0 != 500',
  'src/report.py:42: AssertionError',
  '=========================== short test summary info ============================',
  'FAILED tests/test_report.py::test_report - AssertionError: 0 != 500',
  '========================= 79 passed, 1 failed in 1.2s =========================',
].join('\n')

test('pytest compaction keeps the failure and summary', () => {
  const out = compactCommandOutput('python -m pytest -q', pytestLog)
  assert.ok(out.length < pytestLog.length)
  assert.match(out, /FAILED tests\/test_report\.py/)
  assert.match(out, /79 passed, 1 failed/)
  assert.match(out, /\[compacted pytest\]$/)
})

test('unknown commands are left alone', () => {
  const log = 'x'.repeat(5000)
  assert.equal(compactCommandOutput('ls -la', log), log)
})

test('compile errors are kept', () => {
  const log = ['src/a.ts(1,2): error TS2304: Cannot find name x.', ...Array.from({ length: 400 }, () => 'noise line')].join('\n')
  const out = compactCommandOutput('npx tsc --noEmit', log)
  assert.match(out, /error TS2304/)
  assert.match(out, /\[compacted tsc\]$/)
})

test('truncation rescues an error from the dropped middle', () => {
  const raw = `${'a'.repeat(900)}\n${'b'.repeat(5000)}\nValueError: bad limit\n${'c'.repeat(5000)}\ntail line`
  const out = truncateHeadTail(raw, 800, 300, true)
  assert.match(out, /error excerpt preserved/)
  assert.match(out, /ValueError: bad limit/)
  assert.ok(out.length < raw.length)
})

test('an error already in the tail is not duplicated', () => {
  const raw = `${'a'.repeat(5000)}\nValueError: bad limit`
  const out = truncateHeadTail(raw, 800, 300, true)
  assert.doesNotMatch(out, /error excerpt preserved/)
})

test('short repeated runs survive; long runs collapse', () => {
  assert.equal(collapseStack('x\nx\nx', 6), 'x\nx\nx')
  assert.match(collapseStack('x\n'.repeat(6).trimEnd(), 6), /×6/)
})

test('runtime denoise applies command compaction before generic rules', () => {
  const state = createDenoiseState()
  const out = runtimeDenoise(pytestLog, {
    toolName: 'pwsh', callId: 'c1', args: { command: 'pytest -q' }, state,
  })
  assert.ok(out !== null)
  assert.ok(out.rules.includes('command_family'))
  assert.match(out.text, /FAILED tests\/test_report\.py/)
})

test('read results keep their bytes', () => {
  const state = createDenoiseState()
  assert.equal(runtimeDenoise(pytestLog, {
    toolName: 'read', callId: 'c2', args: { path: 'src/report.py' }, state,
  }), null)
})

test('bash keeps a 4k head and a 1.5k tail', () => {
  const raw = `${'a'.repeat(6000)}${'b'.repeat(6000)}`
  const state = createDenoiseState()
  const out = runtimeDenoise(raw, { toolName: 'bash', callId: 'c3', args: { command: 'echo hi' }, state })
  assert.ok(out !== null)
  assert.ok(out.text.startsWith('a'.repeat(4000)))
  assert.ok(out.text.endsWith('b'.repeat(1500)))
  assert.ok(out.text.length < 6000)
})

test('non-shell results keep the 800/300 budget', () => {
  const raw = `${'a'.repeat(6000)}${'b'.repeat(6000)}`
  const state = createDenoiseState()
  const out = runtimeDenoise(raw, { toolName: 'grep', callId: 'c4', args: { pattern: 'x' }, state })
  assert.ok(out !== null)
  assert.ok(out.text.startsWith('a'.repeat(800)))
  assert.ok(out.text.endsWith('b'.repeat(300)))
})

test('node test logs compact at the shell trigger', () => {
  const log = [
    '', '> orders-report@0.1.0 test', '> node --test', '',
    '✖ tests/format.test.mjs (8.6ms)', '✖ tests/store.test.mjs (4.8ms)',
    'ℹ tests 2', 'ℹ pass 0', 'ℹ fail 2', 'ℹ duration_ms 39.6', '',
    '✖ failing tests:', 'test at tests/format.test.mjs:1:1',
    '✖ tests/format.test.mjs (8.6ms)', '  Error: spawn EPERM',
    ...Array.from({ length: 40 }, (_, i) => `      at frame${i} (node:internal/x:${i}:1)`),
    '[exit code: 1]',
  ].join('\n')
  const out = runtimeDenoise(log, {
    toolName: 'pwsh', callId: 'c11', args: { command: 'npm test' }, state: createDenoiseState(),
  })
  assert.ok(out !== null)
  assert.ok(out.rules.includes('command_family'))
  assert.match(out.text, /✖ tests\/format\.test\.mjs/)
  assert.match(out.text, /ℹ fail 2/)
  assert.ok(out.text.length < log.length)
})

const failingRun = (duration, line) => [
  '============================= test session starts =============================',
  ...Array.from({ length: 8 }, (_, i) => `collected item ${i}`),
  '=================================== FAILURES ===================================',
  '_________________________________ test_total ___________________________________',
  `src/report.py:${line}: AssertionError`,
  'E       AssertionError: 0 != 500',
  'FAILED tests/test_report.py::test_total - AssertionError: 0 != 500',
  `========================= 1 failed, 79 passed in ${duration}s ====================`,
].join('\n')

test('repeated failures fold after normalizing line numbers and timings', () => {
  const state = createDenoiseState()
  const args = { command: 'pytest -q' }
  const first = runtimeDenoise(failingRun(1.2, 42), { toolName: 'pwsh', callId: 'c5', args, state })
  assert.equal(first, null)
  const second = runtimeDenoise(failingRun(2.4, 57), { toolName: 'pwsh', callId: 'c6', args, state })
  assert.ok(second !== null)
  assert.deepEqual(second.rules, ['dedupe_failures'])
  assert.match(second.text, /same failure as call c5/)
})

test('different failures are not folded', () => {
  const state = createDenoiseState()
  const args = { command: 'pytest -q' }
  runtimeDenoise(failingRun(1.2, 42), { toolName: 'pwsh', callId: 'c7', args, state })
  const other = failingRun(1.3, 42).replaceAll('AssertionError', 'TypeError')
  const out = runtimeDenoise(other, { toolName: 'pwsh', callId: 'c8', args, state })
  assert.ok(out === null || !out.rules.includes('dedupe_failures'))
})

test('compaction boundary clears failure fingerprints', () => {
  const state = createDenoiseState()
  const args = { command: 'pytest -q' }
  runtimeDenoise(failingRun(1.2, 42), { toolName: 'pwsh', callId: 'c9', args, state })
  resetDenoiseState(state)
  const out = runtimeDenoise(failingRun(2.4, 57), { toolName: 'pwsh', callId: 'c10', args, state })
  assert.equal(out, null)
})

test('git status keeps counts and samples', () => {
  const status = [
    '## main...origin/main',
    ...Array.from({ length: 300 }, (_, i) => ` M src/file${i}.js`),
  ].join('\n')
  const out = compactCommandOutput('git status', status)
  assert.match(out, /branch: main/)
  assert.match(out, /dirty: staged=0 unstaged=300 untracked=0/)
  assert.match(out, /\[compacted git\]$/)
})

test('tsc diagnostics are grouped by file', () => {
  const log = [
    'src/a.ts(1,2): error TS2304: Cannot find name x.',
    'src/a.ts(3,4): error TS1005: expected ;',
    'src/b.ts(5,6): error TS2322: bad type',
    ...Array.from({ length: 500 }, () => 'noise line'),
  ].join('\n')
  const out = compactCommandOutput('npx tsc --noEmit', log)
  assert.match(out, /tsc: 3 issues in 2 files/)
  assert.match(out, /src\/a\.ts: 2/)
  assert.match(out, /src\/b\.ts: 1/)
})
