// Aligned frozen-snapshot acceptance harness for WSC vs DSH native compression.
// Both arms compress the same shadowed input from the sealed v21 archive, so the
// compression trigger point is aligned by construction. Repeats compression N times
// per arm to measure product / continuation variance, and runs a real byte-level
// restore verification through the actual engine code (historyTextPage).
//
// This is acceptance tooling only: it imports the existing engine and snapshot and
// drives the user-supplied API; it does NOT modify the WSC/DSH product code.
//
// Usage: node acceptance_v19_aligned.mjs --offline | N
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createRequire, registerHooks } from 'node:module'
import { join } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { zstdDecompressSync } from 'node:zlib'
import { messageText } from 'file:///D:/lea/XenYon%20code/dsh-wsc/lib/projection.js'
import { resolvePayloadPolicy } from 'file:///D:/lea/XenYon%20code/dsh-wsc/lib/payload.js'
import { historyTextPage } from 'file:///D:/lea/XenYon%20code/wsc/.local/goal-wsc-paid-20261111/history-text-page.mjs'
import { readReceiptHistory } from './continuity-candidate-plugin-v7/lib/receipt-history.js'
import { commonHistory, comparisonLimits, comparisonRequest, completionStatus, continuationAnswerMessages,
  pairedVerdict, reusableCompression } from './aligned-comparison.mjs'

const requireDsh = createRequire('E:/nodejs/node_modules/@deepseek-ai/dsh/package.json')
registerHooks({
  resolve(specifier, context, next) {
    try { return next(specifier, context) }
    catch (error) {
      if (!specifier.startsWith('@deepseek-ai/')) throw error
      return next(pathToFileURL(requireDsh.resolve(specifier)).href, context)
    }
  },
})
const { BasicCompactionEngine } = await import('@deepseek-ai/dsh-compaction-basic')
const selectorAudit = process.argv.includes('--selector-audit')
const selectorProbe = process.argv.includes('--selector-probe')
const citationReplay = process.argv.includes('--citation-replay')
const stateSourceReplay = process.argv.includes('--state-source-replay')
const stateSourceProbe = process.argv.includes('--state-source-probe')
const dependencyReplay = process.argv.includes('--dependency-replay')
const literalReplay = process.argv.includes('--literal-replay')
const selectorOff = process.argv.includes('--selector-reasoning-off')
const selectorNoTools = selectorOff || process.argv.includes('--selector-no-tools')
const { default: Wsc } = await import(literalReplay ? './continuity-candidate-plugin-v15/engine.js'
  : dependencyReplay ? './continuity-candidate-plugin-v14/engine.js'
  : stateSourceReplay || stateSourceProbe ? './continuity-candidate-plugin-v13/engine.js'
  : citationReplay ? './continuity-candidate-plugin-v12/engine.js'
  : selectorOff ? './continuity-candidate-plugin-v11/engine.js'
  : selectorNoTools ? './continuity-candidate-plugin-v10/engine.js'
  : './continuity-candidate-plugin-v7/engine.js')

const stage = new URL('./host-pair-v21-isolated/', import.meta.url)
const offline = process.argv[2] === '--offline'
const scoped = process.argv.includes('--scoped-state')
assert.ok(!scoped || offline, 'Scoped selector requires offline admission')
const grouped = process.argv.includes('--grouped-lines')
assert.ok(!grouped || offline, 'Grouped selector requires offline admission')
const resumeWorkspace = process.argv.includes('--resume-workspace')
const resumeAnswer = resumeWorkspace || process.argv.includes('--resume-answer')
const resume = resumeAnswer || process.argv.includes('--resume-compression')
assert.ok(!resume || (!scoped && !grouped), 'Use the saved configuration for resumed compression')
const workspaceObservations = process.argv.includes('--workspace-observations')
assert.ok(!workspaceObservations || (offline && !resume), 'Workspace observations require offline compression')
assert.ok(!selectorAudit || offline, 'Selector audit requires offline compression')
assert.ok(!selectorProbe || (selectorOff && !resume && !selectorAudit && (offline || process.argv[2] === '1')),
  'Selector probe requires reasoning-off and one run per arm')
assert.ok(!citationReplay || (selectorProbe && offline), 'Citation replay is offline only')
assert.ok(!stateSourceReplay || citationReplay, 'State source replay requires frozen citation replay')
assert.ok(!stateSourceProbe || (selectorProbe && !offline), 'State source probe requires live selector mode')
assert.ok(!dependencyReplay || (selectorProbe && offline && !citationReplay), 'Dependency replay is offline only')
assert.ok(!literalReplay || dependencyReplay, 'Literal replay requires frozen dependency replay')
assert.ok(!selectorNoTools || selectorAudit || selectorProbe, 'Selector candidate requires an audit or probe')
const selectorVariant = selectorOff ? '-selector-off' : selectorNoTools ? '-selector-no-tools' : '-selector-control'
const DIR = fileURLToPath(new URL(`./aligned-mechanism-${offline ? 'offline' : 'api'}-v42${literalReplay ? '-literal-replay' : dependencyReplay ? '-dependency-replay-v2' : stateSourceProbe ? '-state-source-probe' : stateSourceReplay ? '-state-source-replay' : citationReplay ? '-citation-replay-v2' : selectorProbe ? '-selector-probe' : selectorAudit ? selectorVariant : resumeWorkspace ? '-workspace-answer' : resumeAnswer ? '-answer' : resume ? '-resume' : workspaceObservations ? '-workspace' : scoped ? '-scoped' : grouped ? '-grouped' : ''}/`, import.meta.url))

// ---- load frozen snapshot ----
const prior = JSON.parse(readFileSync(new URL('wsc-result.json', stage), 'utf8'))
assert.equal(prior.session_logs.length, 1)
const raw = readFileSync(prior.session_logs[0])
const sha = (v) => createHash('sha256').update(v).digest('hex')
assert.equal(sha(raw), prior.session_sha256, 'snapshot seal mismatch')
const magic = Buffer.from('28b52ffd', 'hex')
const starts = []
for (let i = 0; i <= raw.length - 4; i++) {
  if (raw.compare(magic, 0, 4, i, i + 4) === 0) starts.push(i)
}
const decoder = new TextDecoder('utf-8', { fatal: true })
const events = starts.flatMap((start, i) => decoder
  .decode(zstdDecompressSync(raw.subarray(start, starts[i + 1] ?? raw.length)))
  .split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)))
const ledger = readFileSync(new URL('dsh-home/wsc/compactions.jsonl', stage), 'utf8')
  .trim().split('\n').map(JSON.parse)
const exhausted = new Set(ledger.filter(row => row.selection?.finish === 'max-tokens')
  .map(row => row.compactionId))
const checkpoint = events.find(event => event.type === 'compaction/summary' &&
  event.data.model === 'deterministic' && exhausted.has(event.data.compactionId))
assert.ok(checkpoint, 'v21 exhausted selector checkpoint not found')
const seq = checkpoint.seq
const eventMap = new Map(events.map((e) => [e.seq, e]))
const derive = (e) => (e.type === 'compaction/summary'
  ? { role: 'user', source: { kind: 'plugin', plugin: 'compact', compactionId: e.data.compactionId }, content: e.data.summary }
  : e.data.message ?? (e.data.role ? e.data : null))
const input = { messages: checkpoint.data.shadowedSeqs.map(id => {
  assert.ok(id < seq && eventMap.has(id), 'frozen source outside boundary')
  const message = derive(eventMap.get(id))
  assert.ok(message, 'frozen source has no message')
  return message
}) }
if (selectorAudit) input.tools = [{ name: 'read', description: 'Archived text', parameters: { type: 'object' } }]
const model = 'deepseek-v4.1-flash'
const maxTokens = selectorProbe ? 4096 : comparisonLimits.compression
const settings = {
  stateSelectionContext: scoped,
  workspaceObservations,
  selectionReasoningEffort: selectorOff ? 'off' : undefined,
  groupedSelectionLines: grouped,
  mode: 'active', selection: 'selective', selectionAddress: 'lines',
  continuityReceipts: true, controlItemCap: 4000, selectionMaxTokens: maxTokens,
  payload: resolvePayloadPolicy({ payloadToolText: 1 }),
}
const session = {
  id: `goal-frozen-${seq}`, requestHeader: () => undefined, deriveEventMessage: derive,
  eventAt: (value) => (value < seq ? eventMap.get(value) : undefined),
  events: events.filter((e) => e.seq < seq),
}
const agent = { session, options: { provider: 'wd', model } }

// ---- API ----
const key = process.env.CSM_BENCH_API_KEY
if (!offline) assert.ok(key, 'CSM_BENCH_API_KEY is required')
mkdirSync(DIR, { recursive: true })
process.env.DSH_HOME = join(DIR, 'dsh-home')
const save = (file, data) => writeFileSync(join(DIR, file), JSON.stringify(data, null, 2), { flag: 'wx' })

async function call(arm, messages, phase, tools) {
  const request = comparisonRequest(model, messages, phase, tools)
  if (selectorProbe) {
    assert.equal(phase, 'compression')
    request.max_tokens = maxTokens
  }
  if (offline) {
    if (dependencyReplay && arm === 'wsc') {
      const load = name => JSON.parse(readFileSync(new URL(`./aligned-mechanism-api-v42-state-source-probe/${name}.json`, import.meta.url)))
      const manifest = load('variance-report')
      assert.equal(manifest.source_sha256, prior.session_sha256)
      assert.equal(manifest.checkpoint_seq, seq)
      assert.equal(manifest.state_source_probe, true)
      const { response, inputSha256 } = load('wsc-run-0').meta.compression_calls[0]
      assert.equal(sha(JSON.stringify(messages)), inputSha256)
      return { model, choices: [response] }
    }
    if (citationReplay && arm === 'wsc') {
      const load = name => JSON.parse(readFileSync(new URL(`./aligned-mechanism-api-v42-selector-probe/${name}.json`, import.meta.url)))
      const manifest = load('variance-report')
      assert.equal(manifest.source_sha256, prior.session_sha256)
      assert.equal(manifest.checkpoint_seq, seq)
      const choice = load('wsc-run-0').meta.compression_calls[0].response
      const output = JSON.parse(choice.message.content)
      const fact = output.facts[0]
      assert.match(fact.text, /CI rc-3 PASSED.*2026-10-30 00:05 UTC/)
      assert.deepEqual(fact.sources, ['m3'])
      const source = messages.map(message => message.content).join('\n')
      assert.match(source, /1753\| .*run rc-3\n1754\| .*status PASSED/)
      fact.sources = ['m3:1728-1754']
      return { model, choices: [{ ...choice, message: { ...choice.message, content: JSON.stringify(output) } }] }
    }
    const toolResults = messages.filter(message => message.role === 'tool').length
    if (tools && toolResults < 6) {
      return { model, choices: [{ finish_reason: 'tool_calls', message: { content: null,
        tool_calls: history.manifest.slice(-2).map(({ seq }, index) => ({
          id: 'offline-read-' + (toolResults + index), type: 'function', function: { name: tools[0].function.name,
            arguments: JSON.stringify({ seq, offset: 0, limit_bytes: 16 }) },
        })),
      } }] }
    }
    const addressable = phase === 'compression' && arm === 'wsc'
      ? [...messages.map(message => message.content).join('\n')
          .matchAll(/^\[(m\d+) (?:assistant|tool-result)\]\r?\n/gm)].slice(0, 8)
      : []
    const content = phase === 'compression' && arm === 'wsc'
      ? JSON.stringify({ state: { done: [], open: [], next: [], unknown: ['Offline fixture.'] },
          keep: addressable.map(match => ({ source: match[1], lines: [1, 4] })), facts: [] })
      : 'Offline fixture. No model was called.'
    return { model, choices: [{ message: { content }, finish_reason: 'stop' }] }
  }
  const response = await fetch('http://127.0.0.1:8788/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal: AbortSignal.timeout(120000),
  })
  const data = await response.json()
  assert.ok(response.ok, `HTTP ${response.status}: ${JSON.stringify(data).slice(0, 200)}`)
  assert.equal(data.model, model)
  return data
}

const CONTINUATION_PROMPT = 'Continue from this checkpoint. State the remaining work, any tests actually completed and what they establish, and the immediate next action. Which current file versions still need verification? Use the evidence in the checkpoint.'

function makeCtx(arm) {
  const logs = []
  const compression = []
  return {
    reflect: { provide() {} },
    on() {},
    get: (k) => (k === 'wscConfig' ? { value: settings } : undefined),
    logger: { info: (v) => logs.push(v), warn: (v) => logs.push(v) },
    logs,
    compression,
    llm: {
      async *stream(options) {
        const messages = options.messages
          .map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: messageText(m, { toolText: true, toolCalls: true }) }))
          .filter((m) => m.content)
        assert.equal(options.maxTokens, maxTokens)
        if (selectorProbe) {
          assert.equal(options.tools?.length ?? 0, 0)
          assert.equal(options.reasoningEffort, arm === 'wsc' ? 'off' : undefined)
          assert.equal(compression.length, 0, 'Selector probe permits only one request per arm')
        }
        const data = await call(arm, messages, 'compression')
        const status = completionStatus(data, model)
        const bodies = messages.map(message => message.content)
        const numberedPrefixes = bodies.flatMap(body => body.match(grouped ? /^Lines \d+-\d+\n/gm : /^\d+\| /gm) ?? [])
        compression.push({ status, inputSha256: sha(JSON.stringify(messages)), usage: data.usage ?? null,
          declared_tool_count: options.tools?.length ?? 0,
          reasoning_effort: options.reasoningEffort ?? null,
          ...(selectorProbe ? { max_tokens: maxTokens, response: data.choices?.[0] ?? null } : {}),
          inputBytes: bodies.reduce((total, body) => total + Buffer.byteLength(body), 0),
          linePrefixBytes: numberedPrefixes.reduce((total, prefix) => total + prefix.length, 0) })
        if (status === 'complete') {
          yield { type: 'text-delta', index: 0, text: data.choices[0].message.content }
        }
        yield { type: 'finish', reason: { kind: status === 'complete' ? 'stop' : 'max-tokens' } }
      },
    },
  }
}

// ---- byte-level restore verification (metric 2: real engine code) ----
function buildSourceMap() {
  const map = new Map()
  for (const event of events) {
    if (!Number.isSafeInteger(event.seq)) continue
    assert.ok(!map.has(event.seq))
    map.set(event.seq, { event, line: '' })
  }
  // re-walk raw to capture original line bytes for sha comparison
  for (const [index, offset] of starts.entries()) {
    for (const line of decoder.decode(zstdDecompressSync(raw.subarray(offset, starts[index + 1]))).split('\n')) {
      if (!line.trim()) continue
      const ev = JSON.parse(line)
      if (Number.isSafeInteger(ev.seq) && map.has(ev.seq)) map.get(ev.seq).line = line
    }
  }
  return map
}

function verifyRestore(sourceMap) {
  const recovered = []
  for (const sseq of checkpoint.data.shadowedSeqs) {
    const row = sourceMap.get(sseq)
    assert.ok(row, `shadowed seq ${sseq} missing`)
    const message = derive(row.event)
    const textValue = messageText(message, { toolText: true, toolCalls: true })
    const expected = Buffer.from(textValue)
    const pages = []
    let offset = 0
    do {
      const page = JSON.parse(historyTextPage(textValue, sseq, { offset }).text)
      const chunk = Buffer.from(page.text)
      assert.equal(page.offset, offset)
      assert.equal(page.sha256, sha(expected))
      assert.equal(page.page_sha256, sha(chunk))
      assert.equal(page.end - offset, chunk.length)
      pages.push(chunk)
      offset = page.next_offset
    } while (offset !== null)
    assert.deepEqual(Buffer.concat(pages), expected)
    recovered.push({ seq: sseq, bytes: expected.length, pages: pages.length, sha256: sha(expected) })
  }
  return recovered
}

function continuationBase(summaryText, history) {
  return [
    { role: 'user', content: summaryText },
    { role: 'user', content: 'Frozen history event catalog (seq, UTF-8 bytes)\n' + JSON.stringify(history.catalog) },
    { role: 'user', content: CONTINUATION_PROMPT },
  ]
}

async function answerFromReceipts(arm, summaryText, history, calls) {
  const replay = calls.map(call => {
    const content = history.read(call.name, JSON.parse(call.arguments))
    assert.equal(sha(content), call.sha256, 'Recovered receipt changed')
    return { role: 'tool', content }
  })
  const messages = continuationAnswerMessages(continuationBase(summaryText, history), replay)
  const data = await call(arm, messages, 'continuation')
  return { status: completionStatus(data, model), text: data.choices?.[0]?.message?.content ?? '',
    calls, usage: [data.usage ?? null], finalOnly: true, answerInputSha256: sha(JSON.stringify(messages)) }
}

async function continueFrom(arm, summaryText, history) {
  const base = continuationBase(summaryText, history)
  const messages = [...base]
  const calls = []
  const usage = []
  const maxToolRounds = 3
  const maxToolCalls = 8
  for (let round = 0; round <= maxToolRounds; round++) {
    const finalOnly = round === maxToolRounds || calls.length >= maxToolCalls
    const requestMessages = finalOnly ? continuationAnswerMessages(base, messages) : messages
    const data = await call(arm, requestMessages, 'continuation', finalOnly ? undefined : history.tools)
    usage.push(data.usage ?? null)
    const status = completionStatus(data, model, { toolAllowed: !finalOnly })
    if (status !== 'tool_calls') {
      return { status, text: data.choices?.[0]?.message?.content ?? '', calls, usage, finalOnly,
        ...(finalOnly ? { answerInputSha256: sha(JSON.stringify(requestMessages)) } : {}) }
    }
    const message = data.choices[0].message
    if (calls.length + message.tool_calls.length > maxToolCalls) {
      return { status: 'history_limit', text: '', calls, usage,
        rejectedBatch: { round, size: message.tool_calls.length } }
    }
    const batch = message.tool_calls
    if (new Set(batch.map(request => request?.id)).size !== batch.length ||
        batch.some(request => request?.type !== 'function' ||
          !history.tools.some(tool => tool.function.name === request.function?.name) ||
          typeof request.id !== 'string' || typeof request.function.arguments !== 'string')) {
      return { status: 'invalid_history_call', text: '', calls, usage }
    }
    messages.push({ role: 'assistant', content: message.content ?? null, tool_calls: batch })
    for (const request of batch) {
      let content
      try {
        content = history.read(request.function.name, JSON.parse(request.function.arguments))
        calls.push({ name: request.function.name, arguments: request.function.arguments,
          status: 'complete', sha256: sha(content) })
      } catch (error) {
        const status = error instanceof SyntaxError ? 'invalid_history_json' : error.message
        content = JSON.stringify({ error: status })
        calls.push({ name: request.function.name, arguments: request.function.arguments, status })
      }
      messages.push({ role: 'tool', tool_call_id: request.id, content })
    }
  }
}

// ---- main ----
const N = offline ? 1 : Number(process.argv[2])
assert.ok(Number.isInteger(N) && N >= 1 && N <= 3, 'Specify 1, 2, 3 or --offline')
const sourceMap = buildSourceMap()
const history = commonHistory(checkpoint.data.shadowedSeqs.map(id =>
  [id, messageText(derive(sourceMap.get(id).event), { toolText: true, toolCalls: true })]))
const historySha = sha(JSON.stringify(history.manifest))
const priorDir = new URL('./aligned-mechanism-api-v26/', import.meta.url)
const priorFile = name => JSON.parse(readFileSync(new URL(name, priorDir), 'utf8'))
const resumed = new Map()
const recovered = new Map()
let workspaceAppendix
if (resume) {
  const pair = priorFile('variance-report.json')
  assert.equal(N, 1)
  assert.equal(pair.offline, false)
  assert.equal(pair.N, N)
  assert.equal(pair.model, model)
  assert.equal(pair.checkpoint_seq, seq)
  assert.equal(pair.source_sha256, prior.session_sha256)
  assert.equal(pair.common_history_sha256, historySha)
  assert.deepEqual(pair.limits, comparisonLimits)
  for (const arm of ['native', 'wsc']) {
    const receipt = priorFile(arm + '-run-0.json')
    const recorded = pair.variance[arm].runs[0]
    assert.deepEqual(receipt.meta, recorded)
    assert.equal(recorded.continuation, 'history_round_limit')
    resumed.set(arm, reusableCompression(receipt, { model, summarySha256: recorded.summarySha256 }))
  }
}
if (resumeAnswer) {
  const directory = new URL('./aligned-mechanism-api-v34-resume/', import.meta.url)
  const load = name => JSON.parse(readFileSync(new URL(name, directory), 'utf8'))
  const pair = load('variance-report.json')
  assert.equal(pair.source_sha256, prior.session_sha256)
  assert.equal(pair.checkpoint_seq, seq)
  assert.equal(pair.model, model)
  assert.equal(pair.common_history_sha256, historySha)
  assert.deepEqual(pair.limits, comparisonLimits)
  for (const [arm, previous] of resumed) {
    const row = load(arm + '-run-0.json')
    assert.deepEqual(row.meta, pair.variance[arm].runs[0])
    assert.equal(row.meta.summarySha256, previous.meta.summarySha256)
    assert.equal(sha(row.continuation), row.meta.continuationSha256)
    assert.equal(row.meta.continuation_final_only, true)
    assert.ok(row.meta.history_calls.length && row.meta.history_calls.every(call =>
      call.status === 'complete' && sha(history.read(call.name, JSON.parse(call.arguments))) === call.sha256))
    recovered.set(arm, row.meta.history_calls)
  }
}
if (resumeWorkspace) {
  const resource = name => new URL('./aligned-mechanism-offline-v38-workspace/' + name, import.meta.url)
  const candidate = JSON.parse(readFileSync(resource('wsc-run-0.json'), 'utf8'))
  const report = JSON.parse(readFileSync(resource('variance-report.json'), 'utf8'))
  assert.equal(report.source_sha256, prior.session_sha256)
  assert.equal(report.checkpoint_seq, seq)
  assert.deepEqual(report.variance.wsc.runs[0], candidate.meta)
  const body = candidate.summary.map(block => block.text).join('\n')
  assert.equal(sha(body), candidate.meta.summarySha256)
  const baseline = resumed.get('wsc').text
  const originalAnswer = JSON.parse(readFileSync(
    new URL('./aligned-mechanism-api-v36-answer/wsc-run-0.json', import.meta.url), 'utf8'))
  assert.equal(originalAnswer.meta.summarySha256, sha(baseline))
  assert.deepEqual(originalAnswer.meta.history_calls, recovered.get('wsc'))
  const baselineHistory = recovered.get('wsc').map(call => ({
    role: 'tool', content: history.read(call.name, JSON.parse(call.arguments)),
  }))
  const baselineInput = continuationAnswerMessages(continuationBase(baseline, history), baselineHistory)
  assert.equal(sha(JSON.stringify(baselineInput)), originalAnswer.meta.answer_input_sha256)
  const delimiter = '- Current workspace version: unverified by the checkpoint archive.'
  const at = body.lastIndexOf('\n' + delimiter)
  assert.ok(at > 0)
  workspaceAppendix = body.slice(at)
  const refs = [...workspaceAppendix.matchAll(/^- read .* \(call #(\d+), receipt #(\d+)\); historical read/gm)]
  assert.equal(refs.length, candidate.meta.workspace_receipts.length)
  assert.ok(refs.length && baseline.includes('## Runtime receipts (session event sequences)'))
  for (const [index, ref] of refs.entries()) {
    const [callSeq, receiptSeq] = ref.slice(1).map(Number)
    const found = candidate.meta.workspace_receipts[index]
    assert.equal(found.callSeq, callSeq)
    assert.equal(found.receiptSeq, receiptSeq)
    const page = JSON.parse(readReceiptHistory(session, receiptSeq, { page: { offset: 0 } }).text)
    assert.equal(page.call_seq, callSeq)
    assert.equal(page.result.sha256, found.originalTextSha256)
  }
}
const restore = {}
for (const arm of ['native', 'wsc']) {
  restore[arm] = verifyRestore(sourceMap)
}
save('restore-report.json', {
  checkpoint_seq: seq,
  shadowed_source_events: checkpoint.data.shadowedSeqs.length,
  common_history: history.manifest,
  arms: restore,
})

const variance = {}
const arms = resumeWorkspace || stateSourceProbe || dependencyReplay ? ['wsc'] : ['native', 'wsc']
for (const arm of arms) {
  const runs = []
  for (let r = 0; r < N; r++) {
    try {
      const ctx = makeCtx(arm)
      const engine = arm === 'native' ? new BasicCompactionEngine(ctx, { auto: false, maxTokens }) : new Wsc(ctx)
      const t0 = Date.now()
      const previous = resumed.get(arm)
      const result = previous ? { model: previous.meta.engine_model, summary: previous.summary }
        : await engine.summarize(input, agent)
      if (resumeWorkspace) {
        assert.equal(result.summary.length, 1)
        result.summary = [{ ...result.summary[0], text: result.summary[0].text + workspaceAppendix }]
      }
      const summaryText = result.summary.map((b) => b.text).join('\n')
      if (citationReplay && arm === 'wsc') {
        assert.match(summaryText, /CI rc-3 PASSED all suites at 2026-10-30 00:05 UTC; earlier rc-1 and rc-2 failed money\.rounding\. \[s\d+\]/)
        assert.doesNotMatch(summaryText, /src\/config\.json specifies rounding/)
      }
      if (stateSourceReplay && arm === 'wsc') {
        assert.match(summaryText, /Work to do:[\s\S]+Phase 1 — money/)
        assert.doesNotMatch(summaryText, /^- (?:Open|Next): /m)
        assert.match(summaryText, /Some proposed progress entries lack retained sources or a recorded next step/)
      }
      const workspaceReceipts = []
      if (workspaceObservations && arm === 'wsc') {
        for (const match of summaryText.matchAll(/^- read .* \(call #(\d+), receipt #(\d+)\); historical read/gm)) {
          const [callSeq, receiptSeq] = match.slice(1).map(Number)
          const receipt = readReceiptHistory(session, receiptSeq, { page: { offset: 0 } })
          const record = JSON.parse(receipt.text)
          assert.equal(record.call_seq, callSeq)
          assert.equal(record.receipt_seq, receiptSeq)
          assert.equal(record.tool, 'read')
          workspaceReceipts.push({ callSeq, receiptSeq, originalTextSha256: record.result.sha256 })
        }
        assert.ok(workspaceReceipts.length)
      }
      const compression = previous ? 'complete'
        : ctx.compression.length === 1 && ctx.compression[0].status !== 'complete'
        ? ctx.compression[0].status
        : result.model === 'deterministic' || ctx.compression.length !== 1 ? 'engine_fallback' : 'complete'
      const cont = selectorProbe ? { status: 'not_part_of_probe', text: '', calls: [], usage: [] }
        : resumeAnswer ? await answerFromReceipts(arm, summaryText, history, recovered.get(arm))
        : compression === 'complete'
        ? await continueFrom(arm, summaryText, history)
        : { status: 'skipped_after_compression', text: '', calls: [], usage: [] }
      const elapsed = (Date.now() - t0) / 1000
      const contText = cont.text
      const out = {
        run: r, engine_model: result.model, summaryBytes: Buffer.byteLength(summaryText),
        summarySha256: sha(Buffer.from(summaryText)),
        compression, compression_calls: previous?.meta.compression_calls ?? ctx.compression,
        ...(previous ? { compression_reused: true } : {}),
        ...(resumeAnswer ? { recovery_reused: true } : {}),
        ...(resumeWorkspace ? { workspace_appendix_sha256: sha(workspaceAppendix),
          comparison_baseline_sha256: previous.meta.summarySha256 } : {}),
        ...(workspaceReceipts.length ? { workspace_receipts: workspaceReceipts } : {}),
        continuation: cont.status, continuation_usage: cont.usage, history_calls: cont.calls,
        continuation_final_only: cont.finalOnly === true,
        ...(cont.answerInputSha256 ? { answer_input_sha256: cont.answerInputSha256 } : {}),
        ...(cont.rejectedBatch ? { rejected_history_batch: cont.rejectedBatch } : {}),
        continuationBytes: Buffer.byteLength(contText),
        continuationSha256: sha(Buffer.from(contText)),
        elapsedSeconds: elapsed, logs_tail: ctx.logs.at(-1) ?? null,
      }
      save(`${arm}-run-${r}.json`, { meta: out, summary: result.summary, continuation: contText, logs: ctx.logs })
      runs.push(out)
    } catch (err) {
      const out = { run: r, error: String(err) }
      save(`${arm}-run-${r}.json`, out)
      runs.push(out)
    }
  }
  variance[arm] = { runs }
}
const paired = resumeWorkspace || stateSourceProbe || dependencyReplay ? [] : Array.from({ length: N }, (_, i) => pairedVerdict({
  native: variance.native.runs[i], wsc: variance.wsc.runs[i],
}))
for (const arm of arms) {
  const { runs } = variance[arm]
  const ok = runs.filter((_, i) => paired[i] === 'eligible_for_paired_quality_review')
  const summaryShas = [...new Set(ok.map((x) => x.summarySha256))]
  const contShas = [...new Set(ok.map((x) => x.continuationSha256))]
  variance[arm] = {
    runs,
    eligible_paired_runs: ok.length,
    distinct_summary_hashes: summaryShas.length,
    distinct_continuation_hashes: contShas.length,
    summaryBytes_min: ok.length ? Math.min(...ok.map((x) => x.summaryBytes)) : null,
    summaryBytes_max: ok.length ? Math.max(...ok.map((x) => x.summaryBytes)) : null,
    summaryBytes_mean: ok.length ? ok.reduce((a, x) => a + x.summaryBytes, 0) / ok.length : null,
    continuation_finish_modes: [...new Set(runs.map((x) => x.continuation ?? 'error'))],
    elapsed_mean_seconds: ok.length ? ok.reduce((a, x) => a + x.elapsedSeconds, 0) / ok.length : null,
  }
}
if (offline && resumeWorkspace) {
  assert.equal(variance.wsc.runs[0].continuation, 'complete')
  assert.equal(variance.wsc.runs[0].history_calls.length, 6)
} else if (offline && !selectorProbe) {
  if (selectorAudit) assert.equal(variance.wsc.runs[0].compression_calls[0].declared_tool_count, selectorNoTools ? 0 : 1)
  if (selectorOff) {
    assert.equal(variance.wsc.runs[0].compression_calls[0].reasoning_effort, 'off')
    assert.equal(variance.native.runs[0].compression_calls[0].reasoning_effort, null)
  }
  assert.deepEqual(paired, ['eligible_for_paired_quality_review'])
  assert.equal(variance.native.runs[0].history_calls.length, 6)
  assert.ok(variance.native.runs[0].continuation_final_only && variance.wsc.runs[0].continuation_final_only)
  assert.ok(variance.native.runs[0].history_calls.every(call => call.status === 'complete'))
  if (!resumeAnswer) assert.deepEqual(variance.native.runs[0].history_calls, variance.wsc.runs[0].history_calls)
}
save('variance-report.json', { N, model, offline, scoped, grouped, resume, resumeAnswer, resumeWorkspace, workspaceObservations, checkpoint_seq: seq,
  source_sha256: prior.session_sha256, selector_probe: selectorProbe, state_source_replay: stateSourceReplay,
  state_source_probe: stateSourceProbe, dependency_replay: dependencyReplay, literal_replay: literalReplay,
  limits: selectorProbe ? { compression: maxTokens } : comparisonLimits, aligned_input_messages: input.messages.length,
  common_history_sha256: historySha, paired, variance })
console.log(JSON.stringify(variance, null, 2))
console.log('restore-report:', JSON.stringify({ shadowed_source_events: checkpoint.data.shadowedSeqs.length, arms: Object.fromEntries(Object.entries(restore).map(([a, r]) => [a, r.length])) }))
