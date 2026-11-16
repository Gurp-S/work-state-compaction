import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { continuitySourceAdvanced } from './continuity-title-fence.mjs'
import { sessionArchive } from './session-archive.mjs'

function sumUsage(records) {
  const sum = { usage_reports: records.length, with_tokens: 0, input_uncached: 0,
    input_cache_read: 0, input_cache_write: 0, output: 0 }
  for (const u of records) {
    if (Object.values(u).some(n => typeof n === 'number' && n > 0)) sum.with_tokens += 1
    sum.input_uncached += u.inputTokens ?? 0
    sum.input_cache_read += u.cacheReadTokens ?? 0
    sum.input_cache_write += u.cacheWriteTokens ?? 0
    sum.output += u.outputTokens ?? 0
  }
  return sum
}

const stage = process.argv[2]
const requested = process.argv.slice(3)
assert.ok(requested.every(arm => ['native', 'wsc'].includes(arm)))
const arms = {}
for (const arm of requested.length ? requested : ['native', 'wsc']) {
  const record = JSON.parse(readFileSync(join(stage, `${arm}-result.json`), 'utf8'))
  assert.equal(record.session_logs.length, 1)
  const { events, sha256 } = sessionArchive(record.session_logs[0])
  assert.equal(sha256, record.session_sha256, `${arm} session seal mismatch`)
  const compactions = events.filter(event => event.type === 'compaction/summary')
  const usage = events.flatMap(event => event.type === 'assistant/chunk' && event.data.chunk?.usage
    ? [event.data.chunk.usage] : [])
  const log = readFileSync(join(stage, `${arm}.log`), 'utf8')
  assert.equal(createHash('sha256').update(readFileSync(join(stage, `${arm}.log`))).digest('hex'),
    record.log_sha256, `${arm} host log seal mismatch`)
  arms[arm] = {
    seconds: record.seconds, exit_code: record.exit_code, timed_out: record.timed_out,
    rate_limited: log.includes('RATE_LIMIT'), quality: { passed: record.score.passed, total: record.score.total },
    retries: events.filter(event => event.type === 'llm/retry').length,
    turn_end: events.filter(event => event.type === 'turn/end').map(event => ({ seq: event.seq, ...event.data })),
    compaction_attempts: events.filter(event => event.type === 'compaction/start').length,
    compaction_without_summary: events.filter(event => event.type === 'compaction/start')
      .filter(start => !compactions.some(summary => summary.data.compactionId === start.data.compactionId))
      .map(start => {
        const end = events.find(event => event.type === 'compaction/end'
          && event.data.compactionId === start.data.compactionId)
        const intervening_events = events
          .filter(event => event.seq > start.seq && event.seq < (end?.seq ?? start.seq))
          .map(event => ({ seq: event.seq, type: event.type }))
        return { seq: start.seq, end: end?.data, intervening_events,
          candidate_fence: continuitySourceAdvanced([start, ...intervening_events], start.seq)
            ? 'reject' : 'unchanged' }
      }),
    main: sumUsage(usage),
    compaction: sumUsage(compactions.flatMap(event => event.data.usage ? [event.data.usage] : [])),
    prunes: events.filter(event => event.type === 'compaction/prune').map(event => ({
      seq: event.seq, sources: event.data.shadowedSeqs, tokens: event.data.shadowedTokenCount,
    })),
    checkpoints: compactions.map(event => ({
      seq: event.seq, model: event.data.model, shadowed_tokens: event.data.shadowedTokenCount,
      state_heading: (Array.isArray(event.data.summary) ? event.data.summary : [])
        .some(block => /^## (?:Current state|Work state)\b/m.test(block.text ?? '')),
      continued: events.some(later => later.seq > event.seq && later.type === 'assistant/message'),
    })),
    session_sha256: sha256,
  }
}
writeFileSync(join(stage, requested.length ? `verified-usage-${requested.join('-')}.json` : 'verified-usage.json'),
  JSON.stringify(arms, null, 2))
console.log(JSON.stringify(arms))
