import { globSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import {
  collapseStack, compactCommandOutput, createDenoiseState, diffDigest, failureFingerprint,
  outlineJson, stripNoiseLines, truncateHeadTail,
} from '../../dsh-wsc/lib/denoise.js'

const RUNS = 'C:/Users/Administrator/Desktop/my project/experiments/prod-matrix/runs'
const ARM = process.argv[2] ?? 'v3r'
const files = globSync(`${RUNS}/*/${ARM}/rep*/metrics.json`)

function oldPipeline(text, name, args, state) {
  const path = args?.path ?? args?.file_path
  if (name === 'read' && typeof path === 'string') {
    const previous = state.reads.get(path)
    const hash = text
    state.reads.set(path, { hash, callId: 'old' })
    if (previous !== undefined && previous.hash === hash) return `[read ${path} again; identical to an earlier read]`
    return null
  }
  if (text.length < 1200 || text.length > 50000) return null
  let next = text
  if (state.seen.has(text)) return '[identical to an earlier result]'
  state.seen.add(text)
  next = stripNoiseLines(next)
  next = collapseStack(next)
  next = diffDigest(next)
  next = outlineJson(next)
  next = truncateHeadTail(next)
  return next
}

function newPipeline(text, name, args, state, stats) {
  const path = args?.path ?? args?.file_path
  const record = (rule, before, after) => {
    const delta = before.length - after.length
    stats.set(rule, (stats.get(rule) ?? 0) + delta)
  }
  if (name === 'read' && typeof path === 'string') {
    const previous = state.reads.get(path)
    const hash = text
    state.reads.set(path, { hash, callId: 'new' })
    if (previous !== undefined && previous.hash === hash) {
      const pointer = `[read ${path} again; identical to an earlier read]`
      record('dedupe_reads', text, pointer)
      return pointer
    }
    return null
  }
  if (state.seen.has(text)) {
    const pointer = '[identical to an earlier result]'
    record('dedupe_identical', text, pointer)
    return pointer
  }
  state.seen.add(text)
  const shell = name === 'bash' || name === 'pwsh'
  if (shell) {
    const failure = failureFingerprint(text)
    if (failure !== undefined) {
      const previous = state.failures.get(failure.key)
      if (previous !== undefined) {
        previous.count += 1
        const pointer = `[same failure as call ${previous.callId} (repeat ${previous.count}): ${failure.label}]`
        record('dedupe_failures', text, pointer)
        return pointer
      }
      state.failures.set(failure.key, { callId: 'new', count: 1 })
      if (state.failures.size > 64) state.failures.delete(state.failures.keys().next().value)
    }
  }
  let next = text
  const apply = (rule, fn) => {
    const before = next
    next = fn(next)
    if (next !== before) record(rule, before, next)
  }
  const command = typeof args?.command === 'string'
    ? args.command
    : typeof args?.cmd === 'string' ? args.cmd : ''
  if (command !== '') apply('command_family', (value) => compactCommandOutput(command, value, shell ? 1000 : undefined))
  apply('strip_noise_lines', stripNoiseLines)
  apply('collapse_stack', (value) => collapseStack(value, 6))
  apply('diff_digest', diffDigest)
  apply('outline_json', outlineJson)
  const shellHead = Number(process.env.SHELL_HEAD ?? 4000)
  const shellTail = Number(process.env.SHELL_TAIL ?? 1500)
  apply('truncate_head_tail', (value) => truncateHeadTail(value, shell ? shellHead : 800, shell ? shellTail : 300, true))
  return next
}

function tokenEstimate(chars) {
  return Math.round(chars / 4)
}

const perRun = []
for (const metricsPath of files) {
  const metrics = JSON.parse(readFileSync(metricsPath, 'utf8'))
  if (!Number.isInteger(metrics.steps)) continue
  const outDir = join(dirname(metricsPath), 'out')
  const rounds = globSync(`${outDir}/round-*.jsonl`).sort()
  const calls = new Map()
  const rows = []
  let loggedChars = 0
  for (const file of rounds) {
    for (const line of readFileSync(file, 'utf8').split('\n')) {
      if (line === '') continue
      let event
      try { event = JSON.parse(line) } catch { continue }
      if (event.type === 'tool_call') {
        calls.set(event.callId, { name: event.tool, args: event.input })
        loggedChars += JSON.stringify(event.input ?? {}).length
      } else if (event.type === 'tool_result') {
        rows.push({ callId: event.callId, text: event.result ?? '', status: event.status })
        loggedChars += (event.result ?? '').length
      } else if (event.type === 'text' || event.type === 'thinking') {
        loggedChars += (event.text ?? '').length
      }
    }
  }
  const uniqueTokens = Math.max(1, loggedChars / 4)
  const totalInput = (metrics.uncachedPrompt ?? 0) + (metrics.cachedPrompt ?? 0)
  const factor = Math.min(60, Math.max(1, totalInput / uniqueTokens))

  const oldState = { reads: new Map(), seen: new Set() }
  const newState = createDenoiseState()
  const ruleSaved = new Map()
  let rawChars = 0
  let oldChars = 0
  let newChars = 0
  let big = 0
  let commandHits = 0
  let rescueHits = 0
  const rules = new Map()
  let rescueAdded = 0

  for (const row of rows) {
    const meta = calls.get(row.callId) ?? {}
    const text = String(row.text ?? '')
    rawChars += text.length
    if (row.status !== 'completed' || text.length === 0) { oldChars += text.length; newChars += text.length; continue }
    // The engine gates both pipelines below 1200 chars; keep that boundary here.
    if (text.length < 1200) { oldChars += text.length; newChars += text.length; continue }
    const name = meta.name ?? ''
    const args = meta.args ?? {}
    const old = oldPipeline(text, name, args, oldState)
    oldChars += (old ?? text).length
    const local = new Map()
    const nextText = newPipeline(text, name, args, newState, local) ?? text
    newChars += nextText.length
    if (text.length >= 4000) big += 1
    for (const [rule, saved] of local) {
      if (saved === 0) continue
      rules.set(rule, (rules.get(rule) ?? 0) + 1)
      ruleSaved.set(rule, (ruleSaved.get(rule) ?? 0) + saved)
      if (rule === 'command_family') commandHits += 1
    }
    if (nextText.includes('[error excerpt preserved]')) rescueHits += 1
  }

  perRun.push({
    scenario: metricsPath.includes('long-40') ? 'long-40' : metricsPath.split(/[\\/]/).at(-4),
    arm: metrics.arm, rep: metrics.repeat, factor,
    results: rows.length, big,
    rawChars, oldChars, newChars,
    oldSaved: rawChars - oldChars,
    newSaved: rawChars - newChars,
    incremental: oldChars - newChars,
    commandHits, rescueHits,
    rules: Object.fromEntries(rules),
    ruleSavedTokens: Object.fromEntries([...ruleSaved].map(([rule, chars]) => [rule, tokenEstimate(chars)])),
    rawTokens: tokenEstimate(rawChars),
    oldSavedTokens: tokenEstimate(rawChars - oldChars),
    newSavedTokens: tokenEstimate(rawChars - newChars),
    incrementalTokens: tokenEstimate(oldChars - newChars),
    weightedNewSaved: Math.round(tokenEstimate(rawChars - newChars) * factor),
    weightedIncremental: Math.round(tokenEstimate(oldChars - newChars) * factor),
  })
}

const byScenario = {}
for (const row of perRun) {
  const key = row.scenario
  byScenario[key] ??= []
  byScenario[key].push(row)
}
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : Math.round((sorted[mid - 1] + sorted[mid]) / 2)
}
const summary = Object.fromEntries(Object.entries(byScenario).map(([scenario, rows]) => [scenario, {
  runs: rows.length,
  resultsMedian: median(rows.map((r) => r.results)),
  bigMedian: median(rows.map((r) => r.big)),
  rawTokensMedian: median(rows.map((r) => r.rawTokens)),
  oldSavedTokensMedian: median(rows.map((r) => r.oldSavedTokens)),
  newSavedTokensMedian: median(rows.map((r) => r.newSavedTokens)),
  incrementalTokensMedian: median(rows.map((r) => r.incrementalTokens)),
  weightedNewSavedMedian: median(rows.map((r) => r.weightedNewSaved)),
  weightedIncrementalMedian: median(rows.map((r) => r.weightedIncremental)),
  commandHitsMedian: median(rows.map((r) => r.commandHits)),
  rescueHitsMedian: median(rows.map((r) => r.rescueHits)),
  factorMedian: median(rows.map((r) => r.factor)),
  ruleSavedTokensMedian: Object.fromEntries(
    [...new Set(rows.flatMap((r) => Object.keys(r.ruleSavedTokens)))]
      .map((rule) => [rule, median(rows.map((r) => r.ruleSavedTokens[rule] ?? 0))]),
  ),
}]))

const totalResults = perRun.reduce((sum, r) => sum + r.results, 0)
const totalRaw = perRun.reduce((sum, r) => sum + r.rawChars, 0)
const totalOld = perRun.reduce((sum, r) => sum + r.oldSaved, 0)
const totalNew = perRun.reduce((sum, r) => sum + r.newSaved, 0)
const totalIncremental = perRun.reduce((sum, r) => sum + r.incremental, 0)

const output = {
  scope: `${ARM} runs; logged tool results replayed through old and new runtime denoise; chars/4 token estimate; weighted by run resend factor`,
  summary,
  overall: {
    runs: perRun.length,
    results: totalResults,
    rawChars: totalRaw,
    oldSavedChars: totalOld,
    newSavedChars: totalNew,
    incrementalChars: totalIncremental,
    rawTokens: tokenEstimate(totalRaw),
    oldSavedTokens: tokenEstimate(totalOld),
    newSavedTokens: tokenEstimate(totalNew),
    incrementalTokens: tokenEstimate(totalIncremental),
    oldSavedPct: Number(((totalOld / totalRaw) * 100).toFixed(2)),
    newSavedPct: Number(((totalNew / totalRaw) * 100).toFixed(2)),
    incrementalPct: Number(((totalIncremental / totalRaw) * 100).toFixed(2)),
    ruleSavedTokens: Object.fromEntries(
      [...new Set(perRun.flatMap((r) => Object.keys(r.ruleSavedTokens)))]
        .map((rule) => [rule, perRun.reduce((sum, r) => sum + (r.ruleSavedTokens[rule] ?? 0), 0)]),
    ),
  },
}
console.log(JSON.stringify(output, null, 2))
