// Offline replay: apply the ledger denoise to saved journals and report what
// folding would change. No model calls, no session writes.
import { readFileSync } from 'node:fs'

import { denoiseLedger, subjectKey } from '../../lib/ledger-denoise.js'
import { capLedger, ledgerLines } from '../../lib/passage.js'

import { homedir } from 'node:os'

const DSH = (process.env.DSH_HOME ?? `${homedir()}/.dsh`).replace(/\\/g, '/')
const ROOT = `${DSH}/wsc/nosig`
const RUNS = 'runs/long-40'
const FACTS = ['TAX_RATE', '0.07', 'REPORT_LIMIT', 'summary(rows)', 'totalCents', 'DEFAULT_REPORT_LIMIT', 'resolveTaxRate', 'amountWithTaxCents', 'dry-run']
const bytes = (text) => Buffer.byteLength(String(text ?? ''), 'utf8') + 64

const loadEntries = (sid) => {
  const entries = new Map()
  for (const line of readFileSync(`${ROOT}/${sid}.jsonl`, 'utf8').split('\n')) {
    if (line.trim() === '') continue
    const row = JSON.parse(line)
    if (row.op === 'add') entries.set(row.entry.id, row.entry)
    else if (row.op === 'revise' && row.entry?.id !== undefined) Object.assign(entries.get(row.entry.id) ?? {}, row.entry)
    else if (row.op === 'supersede') for (const id of row.ids ?? []) {
      const entry = entries.get(id)
      if (entry !== undefined) entry.status = 'superseded'
    }
  }
  return [...entries.values()].filter((entry) => (entry.status ?? 'active') === 'active')
}

const cap = (entries, limit) => capLedger(entries, limit)
const factsAfter = (lines) => FACTS.filter((fact) => lines.join('\n').includes(fact))

for (const [arm, rep] of [['ledger', 4], ['ledger', 5], ['w80', 7], ['w80', 8]]) {
  const sid = readFileSync(`${RUNS}/${arm}/rep${rep}/done`, 'utf8').trim()
  const active = loadEntries(sid)
  const denoised = denoiseLedger(active)
  const beforeBytes = active.reduce((sum, entry) => sum + bytes(entry.text), 0)
  const afterBytes = denoised.entries.reduce((sum, entry) => sum + bytes(entry.text), 0)
  const cappedRaw = cap(active, 8000)
  const cappedClean = cap(denoised.entries, 8000)
  const lines = ledgerLines(denoised.entries)
  const keys = new Map()
  for (const entry of denoised.entries) {
    if (['constraint', 'requirement'].includes(entry.kind)) continue
    const key = subjectKey(entry.text)
    if (key === '') continue
    keys.set(key, (keys.get(key) ?? 0) + 1)
  }
  const reminders = [...keys.values()].filter((count) => count > 1).length
  console.log(`${arm} rep${rep}: active=${active.length} -> ${denoised.entries.length} ` +
    `(superseded=${denoised.superseded}, tests=${denoised.folded}) bytes ${beforeBytes} -> ${afterBytes}`)
  console.log(`   cap8k: raw keeps ${cappedRaw.entries.length}/omits ${cappedRaw.omitted}; ` +
    `denoised keeps ${cappedClean.entries.length}/omits ${cappedClean.omitted}; ` +
    `subjectDuplicatesLeft=${reminders}; facts=${factsAfter(lines).length}/${FACTS.length}`)
}
