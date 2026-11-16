/** Audit the first published checkpoint per arm against its actual sources. */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { zstdDecompressSync } from 'node:zlib'
import { historyTextPage } from './history-text-page.mjs'
import { messageText } from '../../../dsh-wsc/lib/projection.js'

const stage = process.argv[2]
const sha = value => createHash('sha256').update(value).digest('hex')
const read = name => JSON.parse(readFileSync(join(stage, name), 'utf8'))
const usage = read('verified-usage.json')
const magic = Buffer.from('28b52ffd', 'hex')
const output = {}
for (const arm of ['native', 'wsc']) {
  const receipt = read(`${arm}-result.json`)
  const [archive] = receipt.session_logs
  const bytes = readFileSync(archive)
  assert.equal(sha(bytes), receipt.session_sha256)
  const offsets = []
  for (let i = bytes.indexOf(magic); i >= 0; i = bytes.indexOf(magic, i + 4)) offsets.push(i)
  const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })
  const originals = new Map()
  for (const [index, offset] of offsets.entries()) {
    for (const line of decoder.decode(zstdDecompressSync(bytes.subarray(offset, offsets[index + 1]))).split('\n')) {
      if (!line.trim()) continue
      const event = JSON.parse(line)
      if (!Number.isSafeInteger(event.seq)) continue
      assert.ok(!originals.has(event.seq))
      originals.set(event.seq, { event, line })
    }
  }
  const events = [...originals.values()].map(row => row.event)
  const checkpoint = events.find(event => event.type === 'compaction/summary')
  const text = checkpoint.data.summary.map(block => block.text ?? '').join('\n')
  const retained = Buffer.from(text)
  const layers = Object.fromEntries(['user_controls', 'numbered_constraints', 'paths', 'errors', 'assistant_accounts', 'code_lines']
    .map(name => [name, new Set()]))
  const archivedSources = []
  for (const seq of checkpoint.data.shadowedSeqs) {
    const { event, line } = originals.get(seq)
    archivedSources.push({ seq, event_line_sha256: sha(line), utf8_bytes: Buffer.byteLength(line) })
    const message = event.data.message ?? event.data
    const parts = (message.content ?? []).flatMap(block =>
      block.type === 'tool-result' ? block.content : [block]).flatMap(block => typeof block.text === 'string' ? [block.text] : [])
    for (const part of parts) {
      if (event.type === 'user/message' && message.source?.kind === 'user') {
        layers.user_controls.add(part)
        for (const row of part.split(/\r?\n/)) {
          if (/^\s*\d{1,2}\.\s+/.test(row)) layers.numbered_constraints.add(row.trim())
        }
      }
      if (event.type === 'assistant/message') layers.assistant_accounts.add(part)
      if (event.type !== 'tool/result') continue
      for (const match of part.matchAll(/<path>([^<]+)<\/path>/g)) layers.paths.add(match[1])
      for (const line of part.split(/\r?\n/)) {
        if (/\b(?:error|exception|enoent|eperm)\b/i.test(line)) layers.errors.add(line)
        const body = /^\d+: ((?:const|let|export|import|function|return)\b.*)$/.exec(line)
        if (body) layers.code_lines.add(body[1])
      }
    }
  }
  const calls = events.filter(event => event.type === 'tool/call')
  const recoveredText = []
  for (const source of archivedSources) {
    const event = originals.get(source.seq).event
    const message = event.type === 'user/message' ? event.data : event.data.message
    if (!message) continue
    const textValue = messageText(message, { toolText: true, toolCalls: true })
    const expected = Buffer.from(textValue)
    const pages = []
    let offset = 0
    do {
      const page = JSON.parse(historyTextPage(textValue, source.seq, { offset }).text)
      const chunk = Buffer.from(page.text)
      assert.equal(page.offset, offset)
      assert.equal(page.sha256, sha(expected))
      assert.equal(page.page_sha256, sha(chunk))
      assert.equal(page.end - offset, chunk.length)
      pages.push(chunk)
      offset = page.next_offset
    } while (offset !== null)
    assert.deepEqual(Buffer.concat(pages), expected)
    recoveredText.push({ seq: source.seq, bytes: expected.length, pages: pages.length, sha256: sha(expected) })
  }
  const edits = new Set(), reads = new Set()
  let repeatedReads = 0, postReads = 0, repeatedWrites = 0, postWrites = 0
  const readRecoveries = [], searchCalls = []
  for (const call of calls) {
    const args = typeof call.data.arguments === 'string' ? JSON.parse(call.data.arguments) : call.data.arguments
    const after = call.seq > checkpoint.seq
    const path = args?.file_path ?? args?.path
    if (after && call.data.name === 'read_history') readRecoveries.push(call.seq)
    if (after && ['grep', 'glob'].includes(call.data.name)) searchCalls.push(call.seq)
    if (typeof path !== 'string') continue
    const normalized = resolve(receipt.work, path).toLowerCase()
    if (call.data.name === 'read') {
      if (after) {
        postReads++
        if (reads.has(normalized)) repeatedReads++
      }
      reads.add(normalized)
    } else if (['write', 'edit'].includes(call.data.name)) {
      if (after) {
        postWrites++
        if (edits.has(normalized)) repeatedWrites++
      }
      edits.add(normalized)
    }
  }
  output[arm] = { first_checkpoint_seq: checkpoint.seq, checkpoint_sha256: sha(text),
    observed_layers: Object.fromEntries(Object.entries(layers).map(([name, values]) => [name,
      { source_items: values.size, exact_items: [...values].filter(value => retained.includes(Buffer.from(value))).length }])),
    archived_source_events: archivedSources, offline_paged_text_recovery: recoveredText,
    actual_read_history_calls: readRecoveries, post_checkpoint_search_calls: searchCalls,
    post_checkpoint_file_reads: postReads, repeated_path_reads: repeatedReads,
    post_checkpoint_edits: postWrites, repeated_edit_paths: repeatedWrites, usage: usage[arm],
    unmeasured: ['semantic_fact_decision_coverage', 'complete_file_byte_recovery', 'repeat_variance',
      'matched_late_checkpoints', 'usd_ledger_reconciliation'] }
}
writeFileSync(join(stage, 'compression-fidelity-audit-v3.json'), JSON.stringify(output, null, 2), { flag: 'wx' })
console.log(JSON.stringify(Object.fromEntries(Object.entries(output).map(([arm, row]) =>
  [arm, { layers: row.observed_layers, readHistory: row.actual_read_history_calls.length,
    postReads: row.post_checkpoint_file_reads, repeatedReads: row.repeated_path_reads }]))))
