import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { AsyncLocalStorage } from 'node:async_hooks'
import { join } from 'node:path'
import { loadDshPackage } from './lib/resolve.js'
import { adjust, decide, usedPercent } from './lib/timing.js'
import { selectCompactableRange } from './lib/range.js'
import { admitCompaction } from './lib/admission.js'
import { buildCheckpoint, buildSelectiveCheckpoint, buildVerificationState, mandatoryLowerBound } from './lib/checkpoint.js'
import { byteLength } from './lib/bytes.js'
import { createDenoiseState, resetDenoiseState, runtimeDenoise } from './lib/denoise.js'
import {
  SELECTION_INSTRUCTION,
  SELECTION_INSTRUCTION_RANGES,
  STATE_INSTRUCTION,
  numberedTranscript,
  parseSelection,
  parseSelectionRanges,
} from './lib/selection.js'
import { messageText as projectMessageText, toolResultOf } from './lib/projection.js'
import { canonicalJson, digest, loadEvidence, read as readEvidence, recordEvidence, sessionStore } from './lib/evidence.js'
import { eventAt, sessionEvents } from './lib/session.js'
import { readReceiptHistory } from './lib/receipt-history.js'
import {
  assertCheckpointState, carryCheckpointState, checkpointStateFromSummary, mechanicalCheckpointState,
  preservePriorOpenScope, renderCheckpointState,
} from './lib/checkpoint-state.js'
import { sha256Hex } from './lib/excerpts.js'
import { confirm as confirmInstall, loadOperations, recordOperation } from './lib/publication.js'
import { ResourceIO, checkEvidence } from './lib/resources.js'
import { UnderstandingStore } from './lib/understanding.js'
import { currentEntries } from './lib/state-view.js'
import { stateDelta } from './lib/state-delta.js'
import { prepareContinuity } from './lib/continuity.js'
import { regionRows, regionValueRows, termsOf } from './lib/values.js'
import { errorPinOf } from './lib/error-pin.js'
import { cleanEntryText, denoiseLedger } from './lib/ledger-denoise.js'
import { asCheckpointState, engineState, receiptsFromRows, recentChanges, recentReceipts } from './lib/state.js'
import { historyIndex, indexSourceCount } from './lib/evidence-index.js'
import { renderPassage, windowControl } from './lib/passage.js'
import { capacityWindow } from './lib/window.js'
import { requirementBoard, requirementBoardText } from './lib/requirement-board.js'
import { classifyCommands, renderCommandState } from './lib/command-state.js'
import { buildWorkingSet } from './lib/workingset.js'
import { buildWorkingSet as buildWorkingSetV2 } from './lib/workingset-v2.js'
import { checkpointBudget } from './lib/checkpoint-budget.js'
import {
  LedgerJournal, runExtraction, runExtractionOnce, segmentMessages, numberedSegment,
} from './lib/nosig.js'

const { BasicCompactionEngine } = await loadDshPackage('@deepseek-ai/dsh-compaction-basic')
const { toolPairingBalancedBefore, isCompactCheckpointSource } = await loadDshPackage('@deepseek-ai/dsh-compaction')
const { BlockAssembler, createUserMessage } = await loadDshPackage('@deepseek-ai/dsh-llm')

const TOOL_NAME = 'compact_context'
const MAX_SELECTION_TOKENS = 4096
// Largest numbered region sent to one extraction request. The whole region is
// the reference behaviour; past this bound a request cannot be read in one
// pass, so the engine segments instead of silently truncating.
const NOSIG_SINGLE_MAX_BYTES = 180000
const selectedRange = new AsyncLocalStorage()

/**
 * Why the selective path fell back, kept on the ledger row.
 *
 * Headless runs swallow `logger.warn`, so a silent degradation used to be
 * invisible. The row is the only place a later reader can tell "the model chose
 * nothing" from "the request never finished" from "the JSON did not parse".
 */
const FALLBACK = {
  noProvider: 'no-provider',
  requestError: 'request-error',
  unfinished: 'unfinished',
  emptyOutput: 'empty-output',
  unusable: 'unusable-selection',
  rejected: 'checkpoint-rejected',
}


/** Custom message source: a labelled notice, not a user prompt. */
const NOTICE_SOURCE = { kind: 'wsc-compaction', form: 'notice', summary: 'Context pressure' }

/**
 * One value per fact, newest wins; a fact the ledger already states is not
 * repeated in the value block.
 */
const normalizeQuote = (text) => String(text ?? '')
  .toLowerCase()
  .replace(/^headless\s+/, '')
  .replace(/[^a-z0-9]+/g, ' ')
  .trim()

/**
 * A requirement the verbatim quote block already states is not restated in
 * the ledger; the quote is the more precise copy.
 */
const pruneQuotedRequirements = (entries, controls) => {
  const quoted = (controls ?? []).map(normalizeQuote).filter((text) => text.length >= 20)
  if (quoted.length === 0) return entries
  return entries.filter((entry) => {
    if (entry.kind !== 'requirement') return true
    const text = normalizeQuote(entry.text)
    return text.length < 20 || !quoted.some((quote) => quote.includes(text))
  })
}

const dedupeValues = (values, ledger) => {
  const ledgerText = (ledger ?? [])
    .map((entry) => cleanEntryText(entry.text).toLowerCase().replace(/\\/g, '/'))
  const seen = new Set()
  const kept = []
  const rows = [...(values ?? [])]
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index]
    const text = cleanEntryText(row.text ?? row.label).toLowerCase().replace(/\\/g, '/')
    if (text === '' || seen.has(text)) continue
    if (text.length >= 8 && ledgerText.some((line) => line.includes(text))) continue
    seen.add(text)
    kept.push(row)
  }
  return kept.reverse()
}

/**
 * The latest error in the region, pinned with its file:line when the result
 * carries one. Extraction used to paraphrase errors without the line number.
 */
const safeSessionId = (value) => String(value ?? 'session').replace(/[^A-Za-z0-9._-]/g, '_')

/**
 * Control messages quoted verbatim, in region order.
 *
 * The reference accumulates control text across compactions; DSH recovers it
 * through the continuity walk, which replays the shadowed sources of prior
 * checkpoints. A region that still holds its prompts is read directly.
 */
const carriedControlLines = (block) => {
  if (typeof block !== 'string' || block === '') return []
  const texts = []
  let current = null
  for (const line of block.split('\n').slice(1)) {
    if (line.startsWith('- ')) {
      if (current !== null) texts.push(current.trim())
      current = line.slice(2)
    } else if (current !== null && line.startsWith('  ')) {
      current += `\n${line.slice(2)}`
    }
  }
  if (current !== null) texts.push(current.trim())
  return texts.filter((text) => text !== '')
}
const controlEntries = (rows, continuity, journal) => {
  // The reference accumulates every control message across compactions. The
  // journal keeps them; the continuity block is a second recovery path when a
  // journal is unavailable. The seq lets a deterministic command status compare
  // a request with the edits that came after it.
  const entries = []
  const byText = new Map()
  const push = (text, seq) => {
    const value = String(text ?? '').trim()
    if (value === '') return
    const address = Number.isInteger(seq) ? seq : null
    if (byText.has(value)) {
      const entry = byText.get(value)
      if (entry.seq === null && address !== null) entry.seq = address
      return
    }
    const entry = { text: value, seq: address }
    byText.set(value, entry)
    entries.push(entry)
  }
  for (const text of journal?.controls ?? []) push(text, journal?.controlSeqs?.get(text))
  for (const text of carriedControlLines(continuity?.control)) push(text, null)
  for (const row of rows) {
    if (row.message?.role !== 'user') continue
    if (row.message.source?.kind !== 'user') continue
    if (toolResultOf(row.message) !== undefined) continue
    push(projectMessageText(row.message), row.seq)
  }
  for (const entry of entries) journal?.addControl(entry.text, entry.seq)
  return entries
}

/**
 * Ledger source rows: one per session event, with every tool call it carried.
 *
 * The seq is the durable address, so expiry compares seqs and never a wall
 * clock. A row with no tool call is an observation, not a candidate anchor.
 *
 * @param {{ events: object[], deriveEventMessage: (event: object) => object }} session
 * @returns {object[]}
 */
function ledgerSources(session) {
  const rows = []
  for (const event of sessionEvents(session)) {
    let message
    try {
      message = session.deriveEventMessage(event)
    } catch {
      continue
    }
    if (message === null || message === undefined) continue
    const calls = []
    for (const block of message.content ?? []) {
      if (block?.type !== 'tool-call') continue
      let args = block.arguments
      if (typeof args === 'string') {
        try {
          args = JSON.parse(args)
        } catch {
          args = {}
        }
      }
      const path = args?.path ?? args?.file_path ?? args?.target_file ?? args?.notebook_path
      calls.push({ name: block.name, path: typeof path === 'string' ? path : null })
    }
    rows.push({
      id: `seq:${event.seq}`,
      seq: event.seq,
      observedAt: null,
      kind: calls.length > 0 ? 'call' : 'message',
      calls,
    })
  }
  return rows
}

const TOOL_DESCRIPTION_BASE =
  'Requests compaction of earlier conversation history. Execution happens at the next model-request boundary, ' +
  'so this call returns accepted/pending rather than a finished checkpoint. No arguments.'

/**
 * Compaction's effect on file state, stated as a capability fact.
 *
 * The checkpoint carries a bounded set of files, so a model that expects every
 * file to survive mis-plans. Stating the bound here — where the model reads
 * what the tool does — is a fact about the tool's effect, not advice about
 * when to call it. Only v2 keeps bodies, so v1 and `off` say nothing.
 *
 * @param {object|undefined} settings resolved wsc settings.
 * @returns {string} tool description.
 */
const describeTool = (settings) => {
  const workingset = settings?.workingset
  if (workingset === undefined || workingset === null) return TOOL_DESCRIPTION_BASE
  if ((workingset.version ?? 1) < 2) return TOOL_DESCRIPTION_BASE
  const parts = []
  if (Number.isInteger(workingset.maxFiles)) parts.push(`at most ${workingset.maxFiles} files`)
  if (Number.isInteger(workingset.capChars)) parts.push(`${workingset.capChars} characters each`)
  if (Number.isInteger(workingset.sectionCap)) parts.push(`${workingset.sectionCap} characters total`)
  const bounds = parts.length === 0 ? '' : ` (${parts.join(', ')})`
  return (
    `${TOOL_DESCRIPTION_BASE} The checkpoint carries the file state of the most recently touched files${bounds}; ` +
    'files outside that set are not carried, and reading them again returns their current content.'
  )
}

/**
 * Compaction backend whose ordinary trigger belongs to the model.
 *
 * Pressure at the warning line only publishes a factual notice; the hard line
 * compacts without asking. A successful `compact_context` call records one
 * pending request that the next `agent/pre-step` executes.
 */
export default class WscCompactionEngine extends BasicCompactionEngine {
  static inject = ['llm', 'tokenMeter', 'sessions', 'tools', 'wscConfig']

  constructor(ctx, config = {}) {
    super(ctx, { ...config, auto: false })
    this.pending = new WeakSet()
    this.notified = new WeakSet()
    this.toolAgents = new WeakSet()
    this.denoiseState = new Map()
    this.#install()
  }

  /**
   * Per-session compaction telemetry, consumed by the ledger row.
   *
   * `selection` and `control` are recorded by the builder that ran; the ledger
   * handler merges them into the durable row and drops the entry, so one row
   * says both how much of the task survived and why the selective path did or
   * did not produce the checkpoint.
   */
  #telemetry = new Map()

  #debugged = false

  /**
   * The resolved payload policy is logged once per engine instance.
   *
   * A flag that never reaches the live path behaves exactly like a flag that
   * does nothing, and the difference is invisible from the results. One log
   * line naming the values the builder actually received turns that into a
   * fact the run record can be checked against.
   */
  #policyEchoed = false

  #echoPolicy(settings) {
    if (this.#policyEchoed) return
    this.#policyEchoed = true
    const p = settings.payload
    this.ctx.logger.info(
      `wsc policy: fraction=${p.sourceFraction} maxChars=${p.maxChars} quote=${p.quoteMaxChars} priorDepth=${p.priorEchoDepth} outputs=${p.outputsItems} outputsWeight=${p.outputsWeight} priorItemCap=${p.priorItemCap} workingset=${settings.workingset === undefined ? 'off' : `on(v${settings.workingset.version ?? 1},files=${settings.workingset.maxFiles},cap=${settings.workingset.capChars})`}`,
    )
  }

  #recordTelemetry(agent, patch) {
    const id = agent?.session?.id
    if (typeof id !== 'string') return
    const current = this.#telemetry.get(id) ?? {}
    // Merge in place: callers keep mutating the objects they handed over.
    Object.assign(current, patch)
    this.#telemetry.set(id, current)
  }

  /**
   * The ledger's current entries and the delta since the last installed
   * presentation. Read-only: the write edge is the confirmed install handler,
   * and a missing journal simply presents no working state.
   */
  #ledgerState(session) {
    const home = process.env.DSH_HOME
    if (home === undefined || home === '') return null
    try {
      const store = new UnderstandingStore({ file: join(home, 'wsc', 'understanding', `${session.id}.jsonl`) })
      const records = store.all()
      if (records.length === 0) return null
      const sources = ledgerSources(session)
      const entries = currentEntries(records, sources)
      let previousRefs = []
      try {
        const saved = JSON.parse(readFileSync(join(home, 'wsc', 'state', `${safeSessionId(session.id)}.json`), 'utf8'))
        if (Array.isArray(saved?.presentedRefs)) previousRefs = saved.presentedRefs
      } catch {
        previousRefs = []
      }
      return { entries, changes: stateDelta(previousRefs, records, sources), refs: entries.map(entry => entry.ref) }
    } catch (error) {
      this.ctx.logger.warn(`wsc ledger state skipped: ${error instanceof Error ? error.message : String(error)}`)
      return null
    }
  }

  #install() {
    const ctx = this.ctx

    // The engine lives in the preset's isolated compaction group, whose scope is
    // a child of the agent. A tool registered here would be invisible to the
    // model, so register it on each agent's own scoped context instead.
    ctx.on('agent/created', ({ agent }) => {
      try {
        this.#ensureTool(agent)
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        ctx.logger.warn(`wsc compaction tool registration skipped: ${message}`)
      }
    })

    ctx.on('agent/pre-step', async ({ agent, signal }, next) => {
      try {
        this.#ensureTool(agent)
        await this.#consider(agent, signal)
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        ctx.logger.warn(`wsc compaction skipped: ${message}`)
        process.stderr.write(`wsc compaction skipped: ${message}\n`)
      }
      return next()
    })

    this.#installDenoise()
    this.#installLedger()
  }

  /**
   * Side ledger for cost analysis: one JSONL row per durable compaction, read
   * from the committed summary event. It never writes session events.
   */
  #installLedger() {
    this.ctx.on('session/event', (session, event) => {
      if (event.type !== 'compaction/summary') return
      resetDenoiseState(this.denoiseState.get(session.id))
      try {
        const home = process.env.DSH_HOME
        if (home === undefined || home === '') return
        const dir = join(home, 'wsc')
        mkdirSync(dir, { recursive: true })
        const data = event.data
        const summaryChars = Array.isArray(data.summary)
          ? data.summary.reduce((total, block) => total + (block.type === 'text' ? block.text.length : 0), 0)
          : 0

        // Shadow mode still compacts through the shipped backend; the candidate
        // is built here, never installed, so the two checkpoints can be compared.
        const settings = this.ctx.get('wscConfig')?.value
        const shadow = settings?.mode === 'shadow'
        let candidate = null
        if (shadow) {
          const messages = []
          for (const seq of data.shadowedSeqs ?? []) {
            const sourceEvent = eventAt(session, seq)
            if (sourceEvent === undefined) continue
            const message = session.deriveEventMessage(sourceEvent)
            if (message !== null && message !== undefined) messages.push(message)
          }
          const built = buildCheckpoint(
            { messages },
            {
              isCheckpointSource: (source) =>
                source !== undefined && source !== null && isCompactCheckpointSource(source),
              denoise: settings.denoise === true,
              controlItemCap: settings.controlItemCap,
              payload: settings.payload,
              workingset: settings.workingset,
              outputs: settings.outputs,
            },
          )
          candidate = {
            bytes: byteLength(built.text),
            sourceBytes: built.sourceBytes,
            verification: (built.text.match(/verified after that change/g) ?? []).length,
          }
        }

        const telemetry = this.#telemetry.get(session.id)
        if (telemetry !== undefined) this.#telemetry.delete(session.id)

        const record = {
          kind: shadow ? 'shadow' : 'compaction',
          at: new Date().toISOString(),
          sessionId: session.id,
          compactionId: data.compactionId,
          provider: data.provider,
          model: data.model,
          shadowedNodes: Array.isArray(data.shadowedSeqs) ? data.shadowedSeqs.length : 0,
          shadowedTokens: data.shadowedTokenCount,
          summaryChars,
          ...(candidate === null
            ? {}
            : {
                candidateBytes: candidate.bytes,
                candidateSourceBytes: candidate.sourceBytes,
                candidateVerification: candidate.verification,
              }),
          ...(telemetry === undefined
            ? {}
            : {
                control: telemetry.control ?? null,
                selection: telemetry.selection ?? null,
                payload: telemetry.payload ?? null,
                timing: telemetry.timing ?? null,
                nosig: telemetry.nosig ?? null,
                extraction: telemetry.nosig?.usage ?? null,
              }),
          usage: data.usage ?? null,
        }
        // A summary is only accepted when it is bound to a package this engine
        // issued: same session, provider, model and summary digest. Anything
        // else is an unknown install and is reported rather than recorded.
        const packageDigest = sha256Hex(canonicalJson(Array.isArray(data.summary) ? data.summary : []))
        const operation = loadOperations(home, session.id).get(packageDigest)

        // Export the shadowed observations before anything is confirmed: the
        // bytes are fixed now, so a later read can prove it returns what was
        // hidden rather than whatever the log holds at that moment.
        // A failed export is reported and leaves no locators behind.
        let locators = {}
        try {
          const io = new ResourceIO()
          const sequences = data.shadowedSeqs ?? []
          if (sequences.length === 0) throw new Error('wsc: evidence_sources_missing')
          for (const seq of sequences) {
            const sourceEvent = eventAt(session, seq)
            if (sourceEvent === undefined) throw new Error('wsc: evidence_source_missing')
            const message = session.deriveEventMessage(sourceEvent)
            if (message === null || message === undefined) throw new Error('wsc: evidence_message_missing')
            const file = join(dir, 'evidence', session.id, `${seq}.json`)
            io.writeOnce(file, Buffer.from(canonicalJson(message)))
            locators[seq] = { file_path: file, sha256: digest(message) }
          }
          checkEvidence(io, { evidence: locators })
        } catch (error) {
          locators = {}
          this.ctx.logger.warn(`wsc evidence export: ${error.message}`)
        }
        let installed = false
        if (operation === undefined) {
          this.ctx.logger.warn(`wsc install: unknown_install ${packageDigest}`)
        } else if (Object.keys(locators).length === 0) {
          recordOperation(home, session.id, {
            id: operation.id, package: operation.package, state: 'recovery_required', at: new Date().toISOString(),
            reason: 'evidence_unavailable',
          })
        } else {
          try {
            const state = operation.package?.stateDigest === undefined ? null : checkpointStateFromSummary(data.summary)
            const done = confirmInstall(operation, {
              operationId: operation.id,
              packageDigest,
              sessionId: session.id,
              provider: data.provider,
              model: data.model,
              installedThrough: operation.package?.throughSeq,
              ...(state ? { stateDigest: digest(state) } : {}),
              receiver: 'session-log',
              evidenceAccessible: true,
            })
            recordOperation(home, session.id, {
              id: done.id,
              state: done.state,
              at: new Date().toISOString(),
              package: done.package,
              receipt: done.receipt,
              ...(Object.keys(locators).length === 0 ? {} : { evidence: locators }),
            })
            installed = true
          } catch (error) {
            this.ctx.logger.warn(`wsc install: ${error.message}`)
          }
        }

        // The shadowed observations become evidence: each digest is fixed at the
        // moment of shadowing, so a later read can prove it returns the bytes
        // that were hidden rather than whatever the log holds now. Evidence is
        // only recorded for a confirmed install.
        if (installed) {
          recordEvidence(
            home,
            session.id,
            (data.shadowedSeqs ?? []).flatMap((seq) => {
              const sourceEvent = eventAt(session, seq)
              if (sourceEvent === undefined) return []
              const message = session.deriveEventMessage(sourceEvent)
              if (message === null || message === undefined) return []
              return [{ seq, digest: digest(message), bytes: byteLength(canonicalJson(message)) }]
            }),
          )
        }

        // Model-authored judgments become durable records, outside the
        // checkpoint text: each one keeps the refs it cited and the range it
        // was written for, and a later revision is a compare-and-swap.
        const judgments = operation?.package?.judgments
        if (installed && Array.isArray(judgments) && judgments.length > 0) {
          try {
            const store = new UnderstandingStore({
              file: join(dir, 'understanding', `${session.id}.jsonl`),
            })
            // A replayed install must not turn one judgment into two revisions.
            const seen = new Set(
              store.all().map((record) => `${record.text}\u0000${JSON.stringify(record.scope)}`),
            )
            // H2: the durable source pointer is the shadowed region itself; a
            // later write/edit to a cited path is newer than this seq.
            const durable = (data.shadowedSeqs ?? []).map((seq) => `seq:${seq}`)
            for (const judgment of judgments) {
              if (typeof judgment?.text !== 'string' || judgment.text.trim() === '') continue
              const scope = { session: session.id, shadowedSeqs: data.shadowedSeqs ?? [] }
              if (seen.has(`${judgment.text}\u0000${JSON.stringify(scope)}`)) continue
              store.write(
                {
                  text: judgment.text,
                  kind: 'judgment',
                  sources: durable.length > 0
                    ? durable
                    : (Array.isArray(judgment.sources) ? judgment.sources : []),
                  scope,
                },
                { producer: 'selection' },
              )
            }
          } catch (error) {
            this.ctx.logger.warn(`wsc understanding skipped: ${error.message}`)
          }
        }

        // H3 baseline: the refs this checkpoint presented become the delta
        // baseline for the next one, measured against what the model saw.
        if (installed && Array.isArray(telemetry?.ledger?.refs)) {
          try {
            mkdirSync(join(dir, 'state'), { recursive: true })
            writeFileSync(join(dir, 'state', `${safeSessionId(session.id)}.json`),
              JSON.stringify({ presentedRefs: telemetry.ledger.refs }))
          } catch (error) {
            this.ctx.logger.warn(`wsc state baseline skipped: ${error.message}`)
          }
        }

        appendFileSync(join(dir, 'compactions.jsonl'), `${JSON.stringify(record)}\n`, 'utf8')
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        this.ctx.logger.warn(`wsc ledger skipped: ${message}`)
      }
    })
  }

  /**
   * Runtime denoise: rewrite one tool result before it enters request history,
   * keeping the original retrievable through the spill store. Fail-open: a
   * missing backend or a storage error keeps the raw result inline.
   */
  #installDenoise() {
    const ctx = this.ctx

    ctx.on('tools/post-execute', async (exec, result, next) => {
      const decision = await next()
      try {
        if (decision.kind !== 'accept' || result.isError === true) return decision
        const settings = ctx.get('wscConfig')?.value
        if (settings?.denoise !== true) return decision
        const agent = exec.agent
        if (agent === undefined) return decision
        const sessionId = agent.session?.id
        if (typeof sessionId !== 'string') return decision

        const content = decision.content ?? result.content
        const textBlocks = content.filter((block) => block.type === 'text')
        if (textBlocks.length === 0) return decision
        const text = textBlocks.map((block) => block.text).join('\n')
        // Below this the rewrite costs more than it saves; above the ceiling the
        // result is spilling anyway, so a known log family can still compress it.
        if (text.length < 1200 || text.length > 200_000) return decision

        let state = this.denoiseState.get(sessionId)
        if (state === undefined) {
          state = createDenoiseState()
          this.denoiseState.set(sessionId, state)
        }

        const outcome = runtimeDenoise(text, {
          toolName: exec.name,
          callId: exec.callId,
          args: exec.arguments,
          state,
        })
        if (outcome === null) return decision

        const pointer = await this.#spillOriginal(exec, text, outcome.rules)
        if (pointer === undefined) return decision

        return {
          ...decision,
          content: [
            { type: 'text', text: outcome.text + pointer },
            ...content.filter((block) => block.type !== 'text'),
          ],
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        ctx.logger.warn(`wsc denoise skipped: ${message}`)
        return decision
      }
    })
  }

  async #spillOriginal(exec, text, rules) {
    const spillStore = this.ctx.get('spillStore')
    if (spillStore === undefined) return undefined
    const sessionId = exec.agent?.session?.header?.id
    if (sessionId === undefined) return undefined
    try {
      const ref = await spillStore.saveText({
        owner: { sessionId },
        source: { kind: 'tool', toolName: exec.name, callId: exec.callId, label: 'result' },
        suggestedName: `${exec.name}.txt`,
        content: text,
      })
      const bytes = Buffer.byteLength(text, 'utf8')
      return `\n\n[denoise: ${rules.join(', ')}; original ${bytes} bytes at ${ref.locator}. ${ref.retrievalHint}]`
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.ctx.logger.warn(`wsc denoise could not preserve the original: ${message}`)
      return undefined
    }
  }

  #ensureTool(agent) {
    if (this.toolAgents.has(agent)) return
    this.toolAgents.add(agent)
    agent.ctx.tools.register({
      name: TOOL_NAME,
      description: describeTool(this.ctx.get('wscConfig')?.value),
      parameters: { type: 'object', properties: {}, additionalProperties: false },
      output: {
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: { status: { type: 'string' } },
          required: ['status'],
        },
        render: (_args, value) => [
          {
            type: 'text',
            text: String((value && value.status) ?? 'compaction_request=accepted; execution=pending'),
          },
        ],
      },
      execute: async (_args, exec) => {
        if (exec.agent === undefined) throw new Error('compact_context requires an agent Session')
        this.pending.add(exec.agent.session)
        return { status: 'compaction_request=accepted; execution=pending' }
      },
    })

    if (this.ctx.get('wscConfig')?.value?.evidenceTool === false) return

    const receiptHistory = this.ctx.get('wscConfig')?.value?.continuityReceipts === true
    agent.ctx.tools.register({
      name: 'read_history',
      description:
        'Read earlier conversation events that were compacted away. Use seq to read one event by sequence number, ' +
        'or query to find literal text across the session history. Read-only.' +
        (receiptHistory ? ' receipt_seq returns a paired original tool invocation and result; receipt_query is a literal match in that result.' : ''),
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          seq: { type: 'integer', description: 'Exact event sequence number to read.' },
          query: { type: 'string', description: 'Literal text to find in earlier events.' },
          ...(receiptHistory ? {
            receipt_seq: { type: 'integer', description: 'Original tool receipt sequence number.' },
            receipt_query: { type: 'string', description: 'Optional case-sensitive literal within the original receipt body.' },
          } : {}),
        },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: { text: { type: 'string' }, matches: { type: 'integer' } },
          required: ['text', 'matches'],
        },
        render: (_args, value) => [{ type: 'text', text: String((value && value.text) ?? '') }],
      },
      execute: async (args, exec) => {
        if (exec.agent === undefined) throw new Error('read_history requires an agent Session')
        const session = exec.agent.session

        if (receiptHistory && args?.receipt_seq !== undefined) {
          if (args.seq !== undefined || args.query !== undefined) throw new Error('read_history: ambiguous event address')
          return readReceiptHistory(session, args.receipt_seq, { query: args.receipt_query })
        }
        if (args?.receipt_query !== undefined) throw new Error('read_history: receipt_query requires receipt_seq')
        const seq = Number(args?.seq)
        if (Number.isInteger(seq)) {
          const event = eventAt(session, seq)
          if (event === undefined) throw new Error(`read_history: no event at seq ${seq}`)
          const message = session.deriveEventMessage(event)
          const text = message === null || message === undefined ? `[${event.type}]` : fullText(message)
          return { text: clip(text, 6000), matches: 1 }
        }

        const query = typeof args?.query === 'string' ? args.query.trim() : ''
        if (query.length === 0) throw new Error('read_history requires seq or query')

        const lower = query.toLowerCase()
        const matches = []
        for (const event of sessionEvents(session)) {
          const message = session.deriveEventMessage(event)
          if (message === null || message === undefined) continue
          const text = messageText(message)
          const at = text.toLowerCase().indexOf(lower)
          if (at === -1) continue
          const start = Math.max(0, at - 80)
          matches.push(`#${event.seq} ${message.role}: ${clip(text.slice(start, at + query.length + 120), 260)}`)
          if (matches.length >= 8) break
        }

        return {
          text: matches.length === 0 ? `No event contains ${JSON.stringify(query)}.` : matches.join('\n'),
          matches: matches.length,
        }
      },
    })

    agent.ctx.tools.register({
      name: 'read_evidence',
      description:
        'Read exact bytes of one shadowed observation. seq must be an event that a compaction shadowed; the read ' +
        'returns canonical bytes, byte bounds and integrity hashes. offset and limit are bytes. Read-only.',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          seq: { type: 'integer', description: 'Event sequence number of a shadowed observation.' },
          offset: { type: 'integer', description: 'Byte offset of the first byte to return.' },
          limit: { type: 'integer', description: 'Maximum number of bytes to return.' },
        },
        required: ['seq'],
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: {
            text: { type: 'string' },
            offset: { type: 'integer' },
            length: { type: 'integer' },
            total_bytes: { type: 'integer' },
            complete: { type: 'boolean' },
            read_sha256: { type: 'string' },
            object_sha256: { type: 'string' },
          },
          required: ['text', 'offset', 'length', 'total_bytes', 'complete', 'read_sha256', 'object_sha256'],
        },
        render: (_args, value) => [
          {
            type: 'text',
            text: value.complete
              ? String(value.text ?? '')
              : `${String(value.text ?? '')}\n[bytes ${value.offset}-${value.offset + value.length} of ${value.total_bytes}]`,
          },
        ],
      },
      execute: async (args, exec) => {
        if (exec.agent === undefined) throw new Error('read_evidence requires an agent Session')
        const session = exec.agent.session
        const seq = Number(args?.seq)
        if (!Number.isInteger(seq)) throw new Error('read_evidence requires an integer seq')
        const index = loadEvidence(process.env.DSH_HOME, session.id)
        const { store, access } = sessionStore(session, index, fullText)
        const result = readEvidence(store, access, seq, { offset: args?.offset, limit: args?.limit })
        return {
          text: result.content,
          offset: result.offset,
          length: result.length,
          total_bytes: result.total_bytes,
          complete: result.complete,
          read_sha256: result.read_sha256,
          object_sha256: result.object_sha256,
        }
      },
    })
  }

  /**
   * Produce the checkpoint. `selective` asks the model for verbatim quotes and
   * validates them; `deterministic` extracts by rule; `basic` delegates to the
   * shipped summarizer. A selective failure falls back to deterministic
   * extraction, so compaction never depends on one model answer.
   *
   * @param {{ messages: ReadonlyArray<object>, tools?: ReadonlyArray<object> }} input replayed region.
   * @param {object} agent owner of the session being compacted.
   * @param {AbortSignal | undefined} signal cancellation.
   * @returns {Promise<object>} summary blocks plus the producing identity.
   */
  async summarize(input, agent, signal) {
    const settings = this.ctx.get('wscConfig')?.value
    if (settings === undefined || settings.mode !== 'active') return super.summarize(input, agent, signal)

    if (settings.strategy === 'nosig') {
      const checkpoint = await this.#summarizeNosig(input, agent, signal, settings)
      assertCheckpointState(checkpoint)
      this.#recordReady(checkpoint, agent)
      return checkpoint
    }

    this.#echoPolicy(settings)
    const checkpoint = await this.#summarizeCheckpoint(input, agent, signal, settings)
    assertCheckpointState(checkpoint)
    this.#recordReady(checkpoint, agent)
    return checkpoint
  }

  /**
   * Record the package this engine is about to publish. The row is what makes a
   * later summary event verifiable: only a digest we issued can be confirmed.
   *
   * @param {object} checkpoint summary blocks plus the producing identity.
   * @param {object} agent owner of the session being compacted.
   */
  #recordReady(checkpoint, agent) {
    const home = process.env.DSH_HOME
    const sessionId = agent?.session?.id
    const blocks = checkpoint?.summary
    if (typeof home !== 'string' || home === '' || typeof sessionId !== 'string') return
    if (!Array.isArray(blocks) || blocks.length === 0) return
    const events = sessionEvents(agent.session)
    const throughSeq = events.length === 0 ? 0 : events[events.length - 1].seq
    const packageDigest = sha256Hex(canonicalJson(blocks))
    recordOperation(home, sessionId, {
      id: packageDigest,
      state: 'ready',
      at: new Date().toISOString(),
      package: {
        sessionId,
        provider: checkpoint.provider,
        model: checkpoint.model,
        throughSeq,
        packageDigest,
        stateDigest: digest(checkpoint.state),
        judgments: Array.isArray(checkpoint.judgments) ? checkpoint.judgments : [],
      },
    })
  }

  /**
   * nosig checkpoint: the mechanical base (control, state, verification,
   * evidence) plus a model-extracted, cite-checked ledger.
   *
   * Extraction runs one numbered segment at a time, so each call sees a bounded
   * region rather than the whole compacted history. A failed or rejected
   * segment never blocks compaction: it is listed under Extraction gaps, and
   * the base checkpoint still publishes.
   */
  async #summarizeNosig(input, agent, signal, settings) {
    const isCheckpointSource = source =>
      source !== undefined && source !== null && isCompactCheckpointSource(source)
    const continuity = settings.continuityReceipts
      ? prepareContinuity(input, agent.session, isCheckpointSource,
        { includeControlledReads: settings.stateSelectionContext === true })
      : undefined
    const store = selectedRange.getStore()
    const rows = store !== undefined && Number.isInteger(store.start) && Number.isInteger(store.end)
      ? regionRows(agent.session, store.start, store.end)
      : []
    if (rows.length === 0) {
      return this.#summarizeDeterministic(input, agent, settings, isCheckpointSource, continuity)
    }

    const messages = input.messages.filter((message) => message.role !== 'system')
    const { sourceBytes, budget } = checkpointBudget(messages, { payload: settings.payload })

    const header = agent.session.requestHeader()?.config
    const provider = header?.provider ?? agent.options?.provider
    const model = header?.model ?? agent.options?.model
    const home = typeof process.env.DSH_HOME === 'string' && process.env.DSH_HOME !== ''
      ? process.env.DSH_HOME : ''
    const journal = new LedgerJournal(
      home === '' ? null : join(home, 'wsc', 'nosig', `${safeSessionId(agent.session.id)}.jsonl`),
    ).load()

    const telemetry = { segments: 0, accepted: 0, rejected: 0, gaps: 0, mode: settings.nosigVerification }
    const extractionUsage = { calls: 0, inputTokens: 0, outputTokens: 0, cacheReadTokens: 0 }
    const gaps = []
    if (typeof provider !== 'string' || typeof model !== 'string' || provider === '' || model === '') {
      gaps.push('no provider/model for ledger extraction; base checkpoint published')
    } else {
      // The Python reference extracts the whole region in one request. The
      // request is bounded by the model window, so a region too large to read
      // in one pass still falls back to ordered segments.
      const singlePass = byteLength(numberedSegment(messages).text) <= NOSIG_SINGLE_MAX_BYTES
      const segments = singlePass ? [messages] : segmentMessages(messages, { maxBytes: settings.nosigSegmentBytes })
      const run = singlePass ? runExtractionOnce : runExtraction
      const extraction = await run(singlePass ? messages : segments, journal, {
        mode: settings.nosigVerification,
        entries: settings.nosigEntryCap,
        revisions: settings.nosigRevisionCap,
        delta: settings.extractDelta === true,
        callModel: async (numbered, prior, instruction) => {
          if (signal?.aborted === true) throw new Error('wsc nosig request aborted')
          const assembler = new BlockAssembler()
          try {
            for await (const chunk of this.ctx.llm.stream({
              provider,
              model,
              messages: [{
                role: 'user',
                content: [
                  { type: 'text', text: numbered.text },
                  { type: 'text', text: prior },
                  { type: 'text', text: instruction },
                ],
              }],
              maxTokens: settings.nosigMaxTokens,
              sessionId: agent.session.id,
              purpose: 'compaction',
              ...(settings.nosigReasoningEffort
                ? { reasoningEffort: settings.nosigReasoningEffort }
                : {}),
              ...(signal === undefined ? {} : { signal }),
            })) assembler.push(chunk)
          } catch (error) {
            if (signal?.aborted === true) throw error
            throw new Error('wsc nosig request failed')
          }
          if (assembler.finish?.kind !== 'stop') {
            const finish = assembler.finish?.kind ?? 'unknown'
            const detail = assembler.finish?.failure?.message
              ?? assembler.finish?.error?.message ?? ''
            throw new Error(`wsc nosig extraction did not finish (${finish}`
              + `${detail ? `: ${String(detail).slice(0, 120)}` : ''})`)
          }
          extractionUsage.calls += 1
          for (const key of ['inputTokens', 'outputTokens', 'cacheReadTokens']) {
            const value = assembler.usage?.[key]
            if (Number.isFinite(value) && value > 0) extractionUsage[key] += value
          }
          return assembler.blocks()
            .filter((block) => block.type === 'text')
            .map((block) => block.text)
            .join('')
        },
      })
      telemetry.segments = extraction.segments
      telemetry.accepted = extraction.accepted
      telemetry.rejected = extraction.rejected
      telemetry.gaps = extraction.gaps.length
      telemetry.recovered = extraction.recovered ?? 0
      telemetry.converted = extraction.converted ?? 0
      // Which literal check failed, so a repeated rejection is a diagnosis,
      // not a count.
      telemetry.reasons = extraction.reasons ?? {}
      telemetry.usage = extractionUsage
      // Extraction is a separate model call per compaction; the session usage
      // does not include it. Persist it so a cost audit can sum both sides.
      journal.append({ op: 'usage', usage: { ...extractionUsage }, segments: extraction.segments })
      gaps.push(...extraction.gaps)
    }

    // The passage is the checkpoint: control quotes, the ranked ledger, the
    // engine work state, mechanical checks, the value ledger and the discovery
    // index, in that order. The model never sees source bytes it did not ask for.
    // Values accumulate across regions: a constant read in round 3 is still
    // addressable after the fifth compaction, as the reference's event-wide
    // ledger is. The journal assigns each value one key at first sight.
    journal.addValues(regionValueRows(rows))
    // Denoise is a render-time view: the journal keeps every entry, the
    // checkpoint shows one current version per subject. Folding before the
    // byte cap is what lets unique facts keep their slot.
    const denoise = settings.ledgerDenoise === true ? denoiseLedger(journal.entries()) : null
    const values = denoise === null ? journal.values : dedupeValues(journal.values, denoise.entries)
    const index = settings.evidenceIndexRows === 0
      ? []
      : historyIndex(rows, { limit: settings.evidenceIndexRows ?? 20 }).filter((row) => row.kind !== 'value')
    const controlEntriesNow = controlEntries(rows, continuity, journal)
    const allControls = controlEntriesNow.map((entry) => entry.text)
    const ledgerEntries = denoise === null
      ? journal.entries()
      : pruneQuotedRequirements(denoise.entries, allControls)
    // Long sessions add one quoted request per round. The cap keeps the newest
    // verbatim and discloses the cut; 0 keeps the reference's unbounded list.
    const windowed = windowControl(allControls, settings.controlMaxBytes ?? 0)
    const control = windowed.texts
    const commandMode = settings.controlMode === 'command-state'
    // Command state is a presentation reduction: the status projection still
    // sees every request, so a completed command can drop its quote without
    // losing the requirement it produced.
    const stateControls = commandMode ? allControls : control
    const mechanical = receiptsFromRows(rows)
    // The durable form cites session seqs; the region-position form feeds the
    // state projection, which matches within this region only.
    const receiptRows = settings.receiptSeq === true
      ? mechanical.map((row) => ({ ...row, edit: row.editSeq ?? row.edit, check: row.checkSeq ?? row.check }))
      : mechanical
    // Persist edit/check evidence so a command stated before this region can be
    // proven complete after its own region is gone.
    journal.addReceipts(receiptRows.map((row) => ({
      path: row.path, edit: row.edit, check: row.check, terms: termsOf(row.editText, 12),
    })))
    const receipts = recentReceipts(receiptRows)
    const projected = engineState(journal.entries(), rows, mechanical, {
      controls: settings.stateFromControls === false ? [] : stateControls,
      promoteUnmatched: settings.stateFromControls !== false,
      isSynthetic: (message) => {
        const source = message?.source
        return source !== undefined && source !== null && isCompactCheckpointSource(source)
      },
    })
    // A region with no stated requirement still needs a state block a later
    // model can rely on; the receipts say what ran, not who asked for it.
    const workState = ['done', 'open', 'next', 'unknown'].some((key) => projected[key].length > 0)
      ? projected
      : {
          done: [], open: [], next: [],
          unknown: mechanical.length > 0
            ? [...new Set(mechanical.slice(-2).map((row) =>
              `${row.path} was edited at #${row.edit}; no active requirement matched it`))].slice(0, 6)
            : ['No verified work state recorded in this region.'],
        }
    const commandBlock = commandMode
      ? renderCommandState(classifyCommands(controlEntriesNow, projected, {
        receipts: journal.receipts, checks: journal.checks,
      }), {
          originMaxChars: settings.originMaxChars,
          activeMaxChars: settings.activeCommandMaxChars,
          headChars: settings.commandHeadChars,
          sectionBytes: settings.commandSectionBytes,
          doneLines: settings.commandDoneLines,
        })
      : ''
    const storedState = asCheckpointState(workState)
    const shownSeqs = new Set([...index.map((row) => row.seq), ...values.map((row) => row.seq)])
    const dropped = Math.max(0, indexSourceCount(rows) - shownSeqs.size)
    // Optional file-state block: the reference leaves bodies to the index, but
    // the production A/B measured 41% more reads after a body-less checkpoint.
    // It stays a separate arm until the matrix prices it.
    let workingSetBlock = ''
    if (settings.workingset !== undefined) {
      const configured = typeof settings.workingset === 'object' ? settings.workingset : {}
      const seed = messages
        .filter((message) => isCheckpointSource(message.source))
        .map((message) => projectMessageText(message))
        .filter((text) => text !== '')
        .join('\n\n')
      const build = (configured.version ?? 1) >= 2 ? buildWorkingSetV2 : buildWorkingSet
      const items = build(messages, seed === '' ? configured : { ...configured, seed })
      if (items.length > 0) workingSetBlock = `## Working set\n${items.join('\n')}`
    }
    // Coverage counts only recorded edits: a request still inside the current,
    // uncompacted region has no receipt yet, and the block says so instead of
    // calling the work open.
    const board = settings.requirementBoard === true
      ? requirementBoardText(requirementBoard(
          control.map((text) => ({ text, seq: controlEntriesNow.find((entry) => entry.text === text)?.seq ?? null })),
          journal.receipts))
      : ''
    const passage = renderPassage({
      control: commandMode ? [] : control,
      commandState: commandBlock,
      board: commandMode ? '' : board,
      controlOmitted: commandMode ? 0 : windowed.omitted,
      latestControl: settings.passageLatest === false
        ? ''
        : ((commandMode ? allControls.at(-1) : control.at(-1)) ?? ''),
      ledger: ledgerEntries,
      ledgerMaxBytes: commandMode ? settings.nosigLedgerBytes : (settings.ledgerCapBytes ?? 0),
      stateBlock: renderCheckpointState(storedState),
      workingSet: workingSetBlock,
      numbered: denoise !== null,
      bullets: denoise !== null,
      superseded: denoise?.superseded ?? 0,
      errorPin: denoise === null ? '' : errorPinOf(rows),
      recent: settings.passageRecent === false ? '' : recentChanges(mechanical),
      receipts,
      index,
      values,
      budget,
      dropped,
    })
    const reasonText = Object.entries(telemetry.reasons ?? {})
      .sort((a, b) => b[1] - a[1])
      .map(([reason, count]) => `${reason}=${count}`)
      .join(', ')
    const gapLines = reasonText === '' ? gaps : [...gaps, `reasons: ${reasonText}`]
    const gapText = gapLines.length > 0
      ? `## Extraction gaps\n${gapLines.map((line) => `- ${line}`).join('\n')}`
      : ''
    telemetry.control = {
      sourceBytes: allControls.reduce((sum, item) => sum + byteLength(item), 0),
      keptBytes: commandMode
        ? byteLength(commandBlock)
        : control.reduce((sum, item) => sum + byteLength(item), 0),
      omitted: commandMode ? 0 : windowed.omitted,
      cap: settings.controlMaxBytes ?? 0,
      mode: settings.controlMode,
    }
    const body = passage !== '' ? passage : 'State: no verified work recorded in this region.'
    const text = [body, gapText].filter((part) => part !== '').join('\n\n')
    if (storedState === null || text.length === 0) throw new Error('wsc: state_required')
    if (byteLength(text) >= sourceBytes * 0.85) throw new Error('wsc: checkpoint_not_smaller')
    this.#recordTelemetry(agent, { nosig: telemetry })
    this.ctx.logger.info(
      `wsc nosig checkpoint: ${byteLength(text)} bytes (budget ${budget}) from ${sourceBytes} shadowed bytes; ` +
        `${telemetry.segments} segments, ${telemetry.accepted} entries, ` +
        `${telemetry.rejected} rejected, ${telemetry.recovered} re-cited, ` +
        `${telemetry.converted} ref-converted, ` +
        `${telemetry.gaps} gaps (${telemetry.mode})`,
    )
    return {
      summary: [{ type: 'text', text }],
      state: storedState,
      provider: typeof provider === 'string' && provider !== '' ? provider : 'wsc',
      model: typeof model === 'string' && model !== '' ? model : 'nosig',
    }
  }

  async #summarizeCheckpoint(input, agent, signal, settings) {
    const isCheckpointSource = source =>
      source !== undefined && source !== null && isCompactCheckpointSource(source)
    const continuity = settings.selection !== 'basic' && settings.continuityReceipts
      ? prepareContinuity(input, agent.session, isCheckpointSource,
        { includeControlledReads: settings.stateSelectionContext === true })
      : undefined
    if (settings.selection === 'selective') {
      // A model-selected checkpoint costs a full transcript request. Below the
      // configured region size the deterministic extractor carries the same
      // control/errors/receipts for free; paying a model there is pure loss.
      if (settings.selectionMinTokens > 0) {
        const measured = selectedRange.getStore()
        const regionTokens = Number.isFinite(input.shadowedTokenCount) ? input.shadowedTokenCount
          : measured?.agent === agent ? measured.tokens : Math.ceil(JSON.stringify(input.messages ?? []).length / 4)
        if (regionTokens < settings.selectionMinTokens) {
          return this.#summarizeDeterministic(input, agent, settings, isCheckpointSource, continuity)
        }
      }
      const selected = await this.#summarizeSelective(input, agent, signal, settings, isCheckpointSource, continuity)
      if (selected !== null) return selected
      // A selective pass can legitimately return no usable quote (the model
      // returned nothing, or every quote was ambiguous). Throwing here turns
      // one failed selection into repeated compaction attempts, each paying a
      // model call. Fall back to the deterministic checkpoint instead.
      this.ctx.logger.warn('wsc selective checkpoint unavailable; falling back to deterministic')
    }
    if (settings.selection === 'basic') {
      const basic = await super.summarize(input, agent, signal)
      const state = mechanicalCheckpointState()
      return { ...basic, state, summary: [
        { type: 'text', text: renderCheckpointState(state) },
        { type: 'text', text: '## Evidence (supporting only)\nNative model account' },
        ...basic.summary,
      ] }
    }

    return this.#summarizeDeterministic(input, agent, settings, isCheckpointSource, continuity)
  }

  #summarizeDeterministic(input, agent, settings, isCheckpointSource, continuity, values = [], workState = null) {
    if (continuity && (sessionEvents(agent.session).at(-1)?.seq ?? 0) !== continuity.throughSeq) {
      throw new Error('wsc: continuity_source_advanced')
    }
    const { text, state, sourceBytes, budget, control } = buildCheckpoint(input, {
      isCheckpointSource,
      continuity,
      denoise: settings.denoise === true,
      controlItemCap: settings.controlItemCap,
      payload: settings.payload,
      workingset: settings.workingset,
      outputs: settings.outputs,
      values,
      ...(workState === null ? {} : { state: workState }),
      structuredState: true,
      dedupeCarriedState: settings.dedupeCarriedState,
    })
    this.#recordTelemetry(agent, { control })
    if (!state || text.length === 0) throw new Error('wsc: state_required')
    if (byteLength(text) >= sourceBytes * 0.85) throw new Error('wsc: checkpoint_not_smaller')

    this.ctx.logger.info(
      `wsc checkpoint: ${byteLength(text)} bytes (budget ${budget}) from ${sourceBytes} shadowed bytes`,
    )
    return {
      summary: [{ type: 'text', text }],
      state,
      provider: 'wsc',
      model: 'deterministic',
    }
  }

  /**
   * One small request for the state narrative.
   *
   * The checkpoint is already assembled at this point, so the request costs one
   * short turn instead of the full region, and the answer is prose the model
   * judged from what the checkpoint actually carries.
   */
  async #stateNarrative(agent, signal, settings, checkpointText, gaps, provider, model) {
    const assembler = new BlockAssembler()
    try {
      for await (const chunk of this.ctx.llm.stream({
        provider,
        model,
        messages: [
          {
            role: 'user',
            content: [
              { type: 'text', text: checkpointText },
              {
                type: 'text',
                text:
                  Array.isArray(gaps) && gaps.length > 0
                    ? `Verified gaps (harness facts, not guesses):\n${gaps.join('\n')}`
                    : 'Verified gaps: none.',
              },
              { type: 'text', text: STATE_INSTRUCTION },
            ],
          },
        ],
        maxTokens: 1200,
        sessionId: agent.session.id,
        purpose: 'compaction',
        ...(signal === undefined ? {} : { signal }),
      })) assembler.push(chunk)
    } catch (error) {
      if (signal?.aborted === true) throw error
      this.ctx.logger.warn(`wsc state narrative failed: ${error instanceof Error ? error.message : String(error)}`)
      return ''
    }
    const text = assembler
      .blocks()
      .filter((block) => block.type === 'text')
      .map((block) => block.text)
      .join('')
      .trim()
    return text.length <= settings.state.cap ? text : ''
  }

  async #summarizeSelective(input, agent, signal, settings, isCheckpointSource, continuity) {
    const selection = {
      attempted: true,
      parsed: false,
      quotes: 0,
      spans: 0,
      fragments: 0,
      droppedAmbiguous: 0,
      droppedFacts: 0,
      hasOutput: false,
      finish: null,
      outputTokens: null,
      maxTokens: settings.selectionMaxTokens ?? MAX_SELECTION_TOKENS,
      fallbackReason: null,
    }
    this.#recordTelemetry(agent, { selection })

    const header = agent.session.requestHeader()?.config
    const provider = header?.provider ?? agent.options?.provider
    const model = header?.model ?? agent.options?.model
    if (typeof provider !== 'string' || typeof model !== 'string' || provider === '' || model === '') {
      selection.fallbackReason = FALLBACK.noProvider
      return null
    }

    const scopedSelection = settings.stateSelectionContext === true && settings.continuityReceipts === true
    const previousState = scopedSelection ? carryCheckpointState(continuity?.state) : null
    // H1/H3: the ledger's current entries lead the checkpoint, and the delta
    // since the last installed presentation tells the model what moved.
    const ledger = this.#ledgerState(agent.session)
    if (ledger !== null) this.#recordTelemetry(agent, { ledger: { refs: ledger.refs, changes: ledger.changes } })

    // Mandatory content is priced before the model call: when control messages
    // and prior checkpoints already exceed the view budget, no safe checkpoint
    // exists and the request must not be sent.
    const bound = mandatoryLowerBound(input, { isCheckpointSource, payload: settings.payload, controlItemCap: settings.controlItemCap })
    if (continuity && byteLength(continuity.control) >= bound.budget) return null
    if (!continuity && bound.mandatoryBytes >= bound.budget) {
      throw new Error(
        `wsc: mandatory view budget exhausted (${bound.mandatoryBytes} >= ${bound.budget} bytes)`,
      )
    }

    const assembler = new BlockAssembler()
    // Line addressing exists because output tokens are what a compaction
    // mostly spends: asking for quotes costs ~3.4k output tokens to keep ~550
    // tokens of text, asking for line numbers costs a few hundred.
    const rangeMode = settings.selectionAddress === 'lines'
    const instruction = rangeMode ? SELECTION_INSTRUCTION_RANGES : SELECTION_INSTRUCTION
    // The model can only address a message by name when the request shows the
    // same numbering the engine resolves against, so the region is projected as
    // a numbered transcript. Quotes are still verified against the original
    // bytes; the labels exist only inside this request.
    const transcript = numberedTranscript(input.messages, {
      toolText: settings.payload.toolText >= 1,
      lineNumbers: rangeMode,
      ...(scopedSelection ? { omit: message => isCheckpointSource(message.source) } : {}),
    })
    if (scopedSelection && !transcript.addressable) return null
    const messages = transcript.addressable
      ? [
          {
            role: 'user',
            content: [
              ...(scopedSelection ? [
                { type: 'text', text: continuity.control },
                { type: 'text', text: continuity.runtime },
                { type: 'text', text: previousState
                  ? `Previous handoff state (current applicability unverified):\n${JSON.stringify(previousState)}` : '' },
              ].filter(block => block.text) : []),
              { type: 'text', text: transcript.text },
              { type: 'text', text: instruction },
            ],
          },
        ]
      : [
          ...input.messages,
          { role: 'user', content: [{ type: 'text', text: instruction }] },
        ]
    const options = {
      provider,
      model,
      messages,
      ...(scopedSelection || input.tools === undefined ? {} : { tools: [...input.tools] }),
      maxTokens: settings.selectionMaxTokens ?? MAX_SELECTION_TOKENS,
      sessionId: agent.session.id,
      purpose: 'compaction',
      ...(signal === undefined ? {} : { signal }),
    }

    try {
      for await (const chunk of this.ctx.llm.stream(options)) assembler.push(chunk)
    } catch (error) {
      if (signal?.aborted === true) throw error
      const message = error instanceof Error ? error.message : String(error)
      selection.fallbackReason = FALLBACK.requestError
      this.ctx.logger.warn(`wsc selection request failed: ${message}`)
      return null
    }

    const finish = assembler.finish
    selection.finish = finish?.kind ?? null
    selection.outputTokens = assembler.usage?.outputTokens ?? null
    if (finish?.kind !== 'stop') {
      if (signal?.aborted === true) throw new Error('wsc selection request aborted')
      selection.fallbackReason = FALLBACK.unfinished
      this.ctx.logger.warn('wsc selection request did not finish; using deterministic extraction')
      return null
    }

    const rawOutput = assembler.blocks()
    const text = rawOutput
      .filter((block) => block.type === 'text')
      .map((block) => block.text)
      .join('')
    selection.hasOutput = text.trim().length > 0
    const selectionResult = rangeMode ? parseSelectionRanges(text) : parseSelection(text)
    selection.address = rangeMode ? 'lines' : 'quotes'
    selection.ranges = selectionResult.ranges?.length ?? 0
    // The two parsers return different shapes: quotes mode carries quotes,
    // spans and fragments, line mode carries ranges. Read both through the same
    // optional accessors, or a range-mode result throws on a missing list and
    // the compaction never completes.
    selection.quotes = selectionResult.quotes?.length ?? 0
    selection.spans = selectionResult.spans?.length ?? 0
    selection.fragments = selectionResult.fragments?.length ?? 0
    if (
      selection.quotes === 0 &&
      selection.spans === 0 &&
      selection.fragments === 0 &&
      selection.ranges === 0
    ) {
      // Distinguishing "the model said nothing" from "it answered but the
      // object did not parse" is the whole point of the ledger field.
      selection.fallbackReason = selection.hasOutput ? FALLBACK.unusable : FALLBACK.emptyOutput
      this.ctx.logger.info('wsc selection returned no usable selection; using deterministic extraction')
      return null
    }

    const proposedState = scopedSelection
      ? preservePriorOpenScope(selectionResult.state, previousState)
      : selectionResult.state
    if (scopedSelection && proposedState === null) return null
    const buildOptions = {
      quotes: selectionResult.quotes ?? [],
      selectionAddress: rangeMode ? 'lines' : 'quotes',
      facts: selectionResult.facts,
      state: proposedState || '',
      ledger,
      // A checkpoint without state is not a handoff; it is an evidence dump.
      requireState: true,
      structuredState: true,
      dedupeCarriedState: settings.dedupeCarriedState,
      continuity,
      ...(transcript.addressable
        ? {
            spans: selectionResult.spans ?? [],
            fragments: selectionResult.fragments ?? [],
            ranges: selectionResult.ranges ?? [],
          }
        : {}),
      toolText: settings.payload.toolText >= 1,
      // The narrative is derived from this checkpoint; it cannot replace
      // file evidence that was removed before the narrative was generated.
      isCheckpointSource,
      controlItemCap: settings.controlItemCap,
      payload: settings.payload,
      workingset: settings.workingset,
      outputs: settings.outputs,
    }
    let checkpoint = buildSelectiveCheckpoint(input, buildOptions)
    if (
      checkpoint === null ||
      checkpoint.text.length === 0 ||
      byteLength(checkpoint.text) >= checkpoint.sourceBytes * 0.85
    ) {
      // Name the exact condition: "the model offered nothing usable" and "the
      // checkpoint was not smaller than its region" need different fixes, and
      // the ledger used to collapse both into one reason.
      selection.fallbackReason = FALLBACK.rejected
      selection.rejectedBecause =
        checkpoint === null
          ? 'no-quote-bound'
          : checkpoint.text.length === 0
            ? 'empty-text'
            : 'not-smaller'
      selection.offered =
        (selectionResult.quotes?.length ?? 0) +
        (selectionResult.fragments?.length ?? 0) +
        (selectionResult.ranges?.length ?? 0)
      return null
    }

    selection.parsed = true

    // The state narrative is its own small request. Asking for it as an extra
    // field of the selection contract did not work: the model answers the task
    // it was given and drops appended fields (measured 0/3 runs emitted it).
    if (settings.state !== undefined && !selectionResult.state) {
      const gaps = buildVerificationState(input.messages)
      const narrative = await this.#stateNarrative(agent, signal, settings, checkpoint.text, gaps, provider, model)
      if (narrative.length > 0) {
        const withState = buildSelectiveCheckpoint(input, {
          ...buildOptions,
          state: narrative,
          stateCap: settings.state.cap,
        })
        if (
          withState !== null &&
          withState.text.length > 0 &&
          byteLength(withState.text) < withState.sourceBytes * 0.85
        ) {
          checkpoint = withState
          selection.stateChars = narrative.length
        }
      }
    }

    if (continuity && (sessionEvents(agent.session).at(-1)?.seq ?? 0) !== continuity.throughSeq) {
      throw new Error('wsc: continuity_source_advanced')
    }
    selection.droppedAmbiguous = checkpoint.droppedAmbiguous
    selection.droppedFacts = checkpoint.droppedFacts
    this.#recordTelemetry(agent, { control: checkpoint.control, payload: checkpoint.payload })

    this.ctx.logger.info(
      `wsc selective checkpoint: ${checkpoint.selectedCount} quotes ` +
        `(${checkpoint.droppedAmbiguous} ambiguous/missing dropped), ` +
        `${checkpoint.judgmentCount} judgments (${checkpoint.droppedFacts} unsourced dropped), ` +
        `${byteLength(checkpoint.text)} bytes from ${checkpoint.sourceBytes} shadowed bytes`,
    )
    return {
      summary: [{ type: 'text', text: checkpoint.text }],
      state: checkpoint.state,
      rawOutput,
      llmStreamCall: true,
      provider,
      model,
      maxTokens: settings.selectionMaxTokens ?? MAX_SELECTION_TOKENS,
      judgments: checkpoint.keptFacts ?? [],
      ...(assembler.usage === undefined ? {} : { usage: assembler.usage }),
    }
  }

  async #consider(agent, signal) {
    const settings = this.ctx.get('wscConfig')?.value
    if (process.env.WSC_DEBUG === '1' && !this.#debugged) {
      this.#debugged = true
      process.stderr.write(`wsc settings: ${JSON.stringify(settings ?? null)}\n`)
    }
    if (settings === undefined || settings.mode === 'off') return

    const session = agent.session
    const target = routedTarget(session)
    if (target === undefined) return

    const info = await this.ctx.llm.resolveModelInfo(target.provider, target.model, signal)
    const capacity = info?.context?.contextWindow
    if (!Number.isInteger(capacity) || capacity <= 0) return

    const reserved = session.requestHeader()?.config?.maxTokens ?? info.defaultMaxTokens ?? 0
    const usable = capacity - Math.max(0, Math.trunc(reserved))
    if (usable <= 0) return

    // Capacity basis is mutually exclusive: a share of the working window or a
    // fixed token cap. The working window is the model's usable window bounded
    // by `effectiveWindowTokens` (0 keeps the model window).
    const working = capacityWindow(usable, settings.effectiveWindowTokens)
    const budget =
      settings.capacityMode === 'tokens'
        ? Math.min(working, Math.max(1024, Math.trunc(settings.capacityTokens)))
        : Math.max(1, Math.floor((working * settings.capacityPercent) / 100))

    let measurement = this.ctx.tokenMeter.measure(session)
    const warnPercent = Math.round(settings.warnRatio * 100)
    const forcePercent = Math.round(settings.forceRatio * 100)
    const requested = this.pending.has(session)

    const decision = () => adjust(
      decide(measurement.totalTokens, budget, {
        modelRequested: requested,
        notified: this.notified.has(session),
        warnPercent,
        forcePercent,
      }),
      forcePercent,
    )
    let timing = decision()
    if (settings.mode === 'active' && settings.pruneBeforeCheckpoint && timing.action === 'capacity') {
      const pruner = this.ctx.get('toolResultPruner')
      if (pruner !== undefined) {
        pruner.pruneSession(session)
        measurement = this.ctx.tokenMeter.measure(session)
        timing = decision()
      }
    }

    if (settings.mode === 'shadow') {
      this.ctx.logger.info(
        `wsc shadow: ${usedPercent(timing.tokens, timing.capacity)}% ` +
          `(${timing.tokens}/${timing.capacity}), action=${timing.action}, notify=${timing.notify}`,
      )
    }

    if (timing.action === 'keep') {
      if (settings.mode === 'shadow') return
      if (measurement.totalTokens * 100 < budget * warnPercent) {
        this.notified.delete(session)
        return
      }
      if (!timing.notify) return
      this.notified.add(session)
      this.#notice(agent, timing, forcePercent)
      return
    }

    const retainTokens = Math.floor(budget * settings.retainRatio)

    // A request that cannot reclaim a meaningful share of the budget is a full
    // selection round trip for a few thousand tokens: the context regrows past
    // the trigger within a couple of steps and the run thrashes. The request is
    // consumed either way, so a skipped call does not stay pending.
    const admission = admitCompaction(timing, {
      budget,
      retainTokens,
      minReclaimRatio: settings.minReclaimRatio ?? 0,
    })
    if (!admission.admit) {
      this.pending.delete(session)
      this.ctx.logger.info(
        `wsc compaction skipped (${timing.action}): reclaim ~${admission.reclaimTokens} tokens ` +
          `is below the ${admission.floor}-token floor`,
      )
      return
    }

    const range = selectCompactableRange(session, measurement, retainTokens, toolPairingBalancedBefore)
    if (range === null) return

    this.pending.delete(session)
    this.notified.delete(session)
    this.#recordTelemetry(agent, {
      timing: {
        action: timing.action,
        tokens: timing.tokens,
        capacity: timing.capacity,
        retainTokens,
        reclaimTokens: admission.reclaimTokens,
        rangeTokens: range.tokens,
        reason: admission.reason,
      },
    })

    const compact = () => this.compactRegion(range.start, range.end, agent, signal)
    // The range is carried through the async compaction so the checkpoint can
    // address region rows by their durable seq (value keys, verification).
    const result = await selectedRange.run(
      { agent, tokens: range.tokens, start: range.start, end: range.end },
      compact,
    )
    this.ctx.logger.info(
      `wsc compaction (${timing.action}): shadowed ${result.shadowedSeqs.length} surface nodes, ` +
        `~${result.shadowedTokenCount} tokens (reclaim ~${admission.reclaimTokens}, ${admission.reason})`,
    )
  }

  #notice(agent, timing, forcePercent) {
    const percent = usedPercent(timing.tokens, timing.capacity)
    const text = `Context pressure ${percent}% (${timing.tokens} / ${timing.capacity} tokens). Forced compaction at ${forcePercent}% of capacity; compact_context triggers compaction on request.`
    agent.inject(
      createUserMessage({
        content: [{ type: 'text', text }],
        source: { ...NOTICE_SOURCE, summary: `Context pressure ${percent}%` },
      }),
    )
  }
}

/** History and evidence reads show tool output: it is the region's content. */
const fullText = (message) => projectMessageText(message, { toolText: true, toolCalls: true })

function clip(text, max) {
  const value = String(text ?? '')
  return value.length <= max ? value : `${value.slice(0, max)}…`
}


function routedTarget(session) {
  const config = session.requestHeader()?.config
  if (config === undefined || config.provider.length === 0 || config.model.length === 0) return undefined
  return { provider: config.provider, model: config.model }
}









