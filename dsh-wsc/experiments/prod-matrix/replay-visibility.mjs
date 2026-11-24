// Offline before/after over saved tail rounds: what the old error pin and the
// old evidence index kept versus what the fixed renderers keep. No model calls.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { errorPinOf } from '../../lib/error-pin.js'
import { historyIndex } from '../../lib/evidence-index.js'
import { toolResultOf } from '../../lib/projection.js'
import { isEnvironmentalPath } from '../../lib/values.js'

const RUNS = 'runs/long-40'

const rowsOf = (file) => {
  const rows = []
  let seq = 0
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    if (line.trim() === '') continue
    let event
    try { event = JSON.parse(line) } catch { continue }
    if (event.type === 'tool_call') {
      seq += 1
      rows.push({
        seq,
        message: {
          role: 'assistant',
          content: [{ type: 'tool-call', id: event.callId, name: event.tool, arguments: event.input ?? {} }],
        },
      })
    } else if (event.type === 'tool_result') {
      seq += 1
      rows.push({
        seq,
        message: {
          role: 'user',
          content: [{
            type: 'tool-result', toolCallId: event.callId,
            isError: event.isError === true || event.status === 'error',
            content: [{ type: 'text', text: String(event.result ?? '') }],
          }],
        },
      })
    }
  }
  return rows
}

// The shipped rule before R2: any "error" substring wins, raw first line.
const oldPin = (rows) => {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const result = toolResultOf(rows[index].message)
    if (result === undefined) continue
    const text = String(result.text ?? '').trim()
    if (!(result.isError === true || /error|EPERM|exception|traceback/i.test(text))) continue
    const location = /((?:[A-Za-z]:)?[\\/][^\s:]+\.\w+:\d+|[\w./\\-]+\.\w+:\d+)/.exec(text)?.[1] ?? ''
    const line = (text.split('\n').find((part) => part.trim() !== '') ?? '').trim().slice(0, 160)
    if (line === '') continue
    return `## Unresolved error\n- ${location === '' ? '' : `${location}: `}${line}`
  }
  return ''
}

const envRows = (index) => index.filter((row) =>
  isEnvironmentalPath(row.label) || isEnvironmentalPath(String(row.text ?? '').slice(0, 400)))

const cases = [
  ['v2', 6, 37], ['ledger', 6, 37], ['dclean', 3, 37], ['dclean', 1, 26],
  ['w80', 1, 37], ['v2', 1, 31], ['v2', 2, 31], ['ledger', 6, 31], ['v2', 6, 39],
]

for (const [arm, rep, round] of cases) {
  const rows = rowsOf(join(RUNS, arm, `rep${rep}`, 'out', `round-${String(round).padStart(2, '0')}.jsonl`))
  if (rows.length === 0) continue
  const before = oldPin(rows)
  const after = errorPinOf(rows)
  const index = historyIndex(rows, { limit: 20 })
  const leak = envRows(index)
  console.log(`\n${arm} rep${rep} r${round}: rows=${rows.length}`)
  console.log(`  old pin: ${before === '' ? '(none)' : before.split('\n')[1]}`)
  console.log(`  new pin: ${after === '' ? '(none)' : after.split('\n')[1]}`)
  console.log(`  new index: ${index.length} rows, environmental=${leak.length}` +
    (leak.length === 0 ? '' : ` -> ${leak.map((row) => row.label).join(' | ')}`))
}
