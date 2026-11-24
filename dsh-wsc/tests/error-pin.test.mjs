import test from 'node:test'
import assert from 'node:assert/strict'
import { join } from 'node:path'
import { errorPinOf } from '../lib/error-pin.js'
import { envelopePathOf, isEnvironmentalPath, isOutsideWorkspace, looksLikeError } from '../lib/values.js'

const resultRow = (seq, text, isError = false) => ({
  seq,
  message: {
    role: 'user',
    content: [{ type: 'tool-result', toolCallId: `c${seq}`, isError, content: [{ type: 'text', text }] }],
  },
})

const workspace = 'C:\\Users\\Administrator\\Desktop\\my project\\dsh-wsc\\src\\report.js'
const spill = 'C:\\Users\\Administrator\\AppData\\Local\\Temp\\dsh-spill-OiBTDk\\session-abc\\deadbeef-read.txt'

test('error pin: a successful read of source text containing Error is not a failure', () => {
  const text = `<path>${workspace}</path>\n<type>file</type>\n<content>\n1: export function toCsv(rows) {\n2:   throw new Error('negative amounts')\n3: }\n`
  assert.equal(errorPinOf([resultRow(1, text)]), '')
})

test('error pin: a spill envelope is never pinned, even when flagged', () => {
  const text = `<path>${spill}</path>\n<type>file</type>\n<content>\n1: Error: spawn EPERM\n`
  assert.equal(errorPinOf([resultRow(1, text, true)]), '')
})

test('error pin: a real flagged failure keeps a workspace location only', () => {
  const text = `Error: Cannot find module './store.js'\n    at src\\report.js:3:1\n`
  const pin = errorPinOf([resultRow(1, text, true)])
  assert.match(pin, /^## Unresolved error\n- .*Error: Cannot find module/)
  assert.ok(!pin.includes('AppData'))
})

test('error pin: an explicit error head counts without a runtime flag', () => {
  const text = 'Traceback (most recent call last):\n  File "src/report.js", line 2\n'
  assert.match(errorPinOf([resultRow(1, text)]), /^## Unresolved error\n- Traceback/)
})

test('error pin: a value line that merely mentions error does not count', () => {
  const text = 'npm test (isolation disabled): tests 35, pass 35, fail 0; no errors.'
  assert.equal(errorPinOf([resultRow(1, text)]), '')
})

test('error pin: the newest actionable failure wins, environmental noise is skipped', () => {
  const rows = [
    resultRow(1, 'Error: first failure\n', true),
    resultRow(2, `<path>${spill}</path>\n<type>file</type>\n<content>\n1: Error: spill failure\n`, true),
  ]
  const pin = errorPinOf(rows)
  assert.match(pin, /Error: first failure/)
})

test('path helpers: spill, temp scratch and run transcripts are environmental', () => {
  assert.equal(isEnvironmentalPath(spill), true)
  assert.equal(isEnvironmentalPath('C:\\run\\out\\round-37.jsonl'), true)
  assert.equal(isEnvironmentalPath('src/Temp/helpers.js'), false)
  assert.equal(isEnvironmentalPath('src/report.js'), false)
  assert.equal(envelopePathOf(`<path>${spill}</path>\n<body>`), spill)
})

test('looksLikeError: only a flagged result or an error head', () => {
  assert.equal(looksLikeError('throw new Error("x") inside a read', false), false)
  assert.equal(looksLikeError('1: throw new Error("x")', false), false)
  assert.equal(looksLikeError('Error: boom', false), true)
  assert.equal(looksLikeError('×3', false), false, 'a collapsed run marker is not an error header')
  assert.equal(looksLikeError('✖ parseArgs keeps the default', false), true)
  assert.equal(looksLikeError('anything at all', true), true)
})

test('path helpers: siblings outside the workspace are not sources', () => {
  assert.equal(isOutsideWorkspace(join(process.cwd(), '..', 'other-arm', 'src', 'report.js')), true)
  assert.equal(isOutsideWorkspace(join(process.cwd(), 'src', 'report.js')), false)
  assert.equal(isOutsideWorkspace('src/report.js'), false)
  assert.equal(isOutsideWorkspace(spill), true)
})
