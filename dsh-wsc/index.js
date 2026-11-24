import { loadDshPackage } from './lib/resolve.js'
import { resolvePayloadPolicy } from './lib/payload.js'

const { default: z } = await loadDshPackage('@deepseek-ai/schemastery')
const { Service } = await loadDshPackage('@deepseek-ai/cordis')

const clamp = (value, min, max, fallback) =>
  typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback

/**
 * Mark a field live-editable where the running schemastery supports it.
 *
 * Desktop builds ship a schemastery with `Schema#volatile`; the CLI build ships
 * 3.18.1, which has no such method. Falling back to the plain default keeps the
 * schema loadable there — the policy is still read at construction, only live
 * re-editing from the Settings form is unavailable on those builds.
 */
const live = (schema, fallback) => {
  const field = schema.default(fallback)
  return typeof field.volatile === 'function' ? field.volatile() : field
}

/**
 * Live compaction policy. Every field is volatile so the Settings form can
 * rewrite it without a restart; the engine reads this service on each step.
 */
export const Config = z.object({
  mode: live(z.string(), 'active'),
  capacityMode: live(z.string(), 'ratio'),
  // Share of the usable window the region may grow to before a compaction is
  // due. 100 is the measured long-session default: on 40-round sessions it
  // compacted 16 times against 35 for the native summarizer, at about half the
  // cost. A smaller budget only spends more requests for the same result.
  capacityPercent: live(z.number().min(1).max(100), 100),
  // Working window cap in tokens. The pressure thresholds are shares of
  // min(model usable window, this cap); 0 keeps the model window unchanged.
  effectiveWindowTokens: live(z.number().step(1).min(0), 256000),
  capacityTokens: live(z.number().step(1).min(1024), 100000),
  warnRatio: live(z.number().min(0.5).max(0.95), 0.8),
  forceRatio: live(z.number().min(0.5).max(0.99), 0.8),
  retainRatio: live(z.number().min(0).max(0.5), 0),
  // Share of the budget a compaction must reclaim before it is worth a full
  // selection round trip. 0.15 skips compactions that would reclaim almost
  // nothing; it was the measured default on 40-round sessions.
  minReclaimRatio: live(z.number().min(0).max(1), 0.15),
  selection: live(z.string(), 'selective'),
  // nosig keeps the benchmark's extraction semantics (numbered segment, cited
  // ledger, engine-rendered state) while the trigger stays pressure-driven.
  strategy: live(z.string(), 'nosig'),
  nosigVerification: live(z.string(), 'literal'),
  nosigSegmentBytes: live(z.number().step(1).min(4096), 24000),
  nosigEntryCap: live(z.number().step(1).min(1).max(50), 5),
  nosigRevisionCap: live(z.number().step(1).min(1).max(20), 3),
  nosigLedgerBytes: live(z.number().step(1).min(400), 8000),
  // Quotes mode has no status projection, so the ranked ledger is the only
  // unbounded block. 8000 keeps the newest, highest-priority relations and
  // discloses the cut; it was the measured default on 40-round sessions.
  ledgerCapBytes: live(z.number().step(1).min(0), 8000),
  // Render the ledger as current state: fold older versions of the same
  // subject and repeated test results before the byte cap. Journal untouched.
  ledgerDenoise: live(z.boolean(), true),
  nosigMaxTokens: live(z.number().step(1).min(1024), 8192),
  selectionMinTokens: live(z.number().step(1).min(0), 0),
  continuityReceipts: live(z.boolean(), false),
  dedupeCarriedState: live(z.boolean(), false),
  stateSelectionContext: live(z.boolean(), false),
  pruneBeforeCheckpoint: live(z.boolean(), false),
  // Byte cap per control item. 0 removes the per-item cap and leaves the
  // decision to the section budget. The 800 default is the shipped behaviour.
  controlItemCap: live(z.number().step(1).min(0), 800),
  // Total byte cap on the passage's quoted control list. 0 keeps every request
  // the way the reference does; a long session should bound it.
  controlMaxBytes: live(z.number().step(1).min(0), 0),
  // 'quotes' keeps every user request verbatim (shipped). 'command-state' keeps
  // the first real command and reduces later ones to deterministic status lines.
  controlMode: live(z.string(), 'quotes'),
  originMaxChars: live(z.number().step(1).min(160), 1200),
  activeCommandMaxChars: live(z.number().step(1).min(120), 400),
  commandHeadChars: live(z.number().step(1).min(24), 96),
  commandSectionBytes: live(z.number().step(1).min(400), 1800),
  commandDoneLines: live(z.number().step(1).min(0).max(24), 3),
  // Legacy alias of `payloadWorkingset`; either flag turns the passage working
  // set on. The single switch is `payloadWorkingset` now.
  passageWorkingset: live(z.boolean(), false),
  // Project requirements over the accumulated controls, not only the current
  // region. Off reproduces the pre-2026-11-21 region-only projection.
  stateFromControls: live(z.boolean(), true),
  // A compact newest-edit block and a latest-request banner. Both are small;
  // off reproduces the ranked-ledger-only checkpoint.
  passageRecent: live(z.boolean(), true),
  passageLatest: live(z.boolean(), true),
  // Reasoning effort for the nosig extraction call. Empty inherits the
  // session's model effort; 'off' keeps the JSON answer without the reasoning
  // tokens that dominate extraction output.
  nosigReasoningEffort: live(z.string(), ''),
  // Output budget of one selection request. A reasoning model spends part of it
  // on reasoning, so this is not a JSON-size cap.
  selectionMaxTokens: live(z.number().step(1).min(1024), 4096),
  // Line addressing: the model names lines, the engine copies the bytes, so a
  // compaction spends a few hundred output tokens instead of a few thousand.
  selectionAddress: live(z.string(), 'quotes'),
  // Checkpoint payload policy (lib/payload.js). Every default below is the
  // shipped behaviour, so an unset profile is unchanged. The knobs exist to
  // test whether a bigger checkpoint stops the post-compaction re-read loop
  // measured in experiments/report/COST-ATTRIBUTION.md.
  payloadFraction: live(z.number().min(0.05).max(2), 0.35),
  payloadMaxChars: live(z.number().step(1).min(600), 24000),
  payloadQuoteMaxChars: live(z.number().step(1).min(1200), 1200),
  payloadSelectedItemCap: live(z.number().step(1).min(200), 1200),
  payloadFactMaxChars: live(z.number().step(1).min(320), 320),
  payloadJudgmentItemCap: live(z.number().step(1).min(80), 320),
  payloadVerificationItemCap: live(z.number().step(1).min(80), 220),
  payloadPriorItemCap: live(z.number().step(1).min(200), 1200),
  payloadPriorEchoDepth: live(z.number().step(1).min(0).max(8), 0),
  payloadOutputsItemCap: live(z.number().step(1).min(60), 240),
  // Project `tool-result` blocks into the selection transcript (0 = shipped).
  payloadToolText: live(z.number().step(1).min(0).max(1), 0),
  payloadOutputsItems: live(z.number().step(1).min(0).max(64), 6),
  payloadOutputsWeight: live(z.number().min(0.05).max(4), 0.2),
  // Carry the last known content of each read/written file through a compaction.
  // Off keeps the shipped behaviour: the checkpoint names files but not their
  // contents, so the model re-reads them after every compaction.
  payloadWorkingset: live(z.boolean(), false),
  payloadWorkingsetFiles: live(z.number().step(1).min(0).max(24), 6),
  payloadWorkingsetItemCap: live(z.number().step(1).min(200), 700),
  payloadWorkingsetVersion: live(z.number().step(1).min(1).max(2), 2),
  payloadWorkingsetSectionCap: live(z.number().step(1).min(400), 2500),
  // Model-written state narrative: replaces the file-body working set with a
  // short prose description of where the work stands (settled / open / unsure).
  // The compressing model judges what is uncertain; the engine only carries it.
  payloadStateNarrative: live(z.boolean(), false),
  payloadStateCap: live(z.number().step(1).min(400).max(2000), 900),
  // Engine-side backfill of recent tool output into the selective checkpoint:
  // selection alone left most of the budget unused, so the model re-ran
  // commands to recover output the checkpoint could have carried.
  payloadBackfill: live(z.boolean(), false),
  payloadBackfillItems: live(z.number().step(1).min(0).max(24), 10),
  payloadBackfillItemCap: live(z.number().step(1).min(200), 900),
  denoise: live(z.boolean(), true),
  evidenceTool: live(z.boolean(), true),
  // How many discovery rows to publish. Zero lets the ledger and quotes own
  // the checkpoint; the fetch tools stay registered either way.
  evidenceIndexRows: live(z.number().step(1).min(0).max(20), 20),
  // Extraction returns only relations the current ledger does not already
  // hold; unchanged restatements are the largest measured output waste.
  extractDelta: live(z.boolean(), false),
  // Receipts cite the session seq instead of a region position, so a later
  // model can fetch `#N` and a resumed checkpoint keeps a real address.
  receiptSeq: live(z.boolean(), true),
  // One compact line of evidence that earlier requests were addressed. It
  // needs the durable receipt seqs, so it stays off unless `receiptSeq` is on.
  requirementBoard: live(z.boolean(), false),
})

/**
 * Host-plane configuration owner. It lives at the profile level because the
 * Settings service projects profile entries only; the compaction engine runs
 * inside an agent preset and reads this service.
 */
export default class WscConfigService extends Service {
  static Config = Config

  constructor(ctx, config = {}) {
    super(ctx, 'wscConfig')
    // Volatile fields resolve to live cells ({ get }) under the desktop
    // schemastery; the CLI build hands plain values. Unwrap once so both
    // shapes reach the same constructor logic.
    const unwrap = (value) => {
      if (value !== null && typeof value === 'object' && typeof value.get === 'function') {
        try { return value.get() } catch { return undefined }
      }
      return value
    }
    const options = {}
    for (const [key, value] of Object.entries(config)) options[key] = unwrap(value)
    if (process.env.WSC_DEBUG === '1') {
      process.stderr.write(`wscConfig resolved: ${JSON.stringify(options)}\n`)
    }

    const warnRatio = clamp(options.warnRatio, 0.5, 0.95, 0.8)
    const forceRatio = clamp(options.forceRatio, 0.5, 0.99, 0.8)

    this.value = Object.freeze({
      mode: options.mode === 'shadow' || options.mode === 'off' ? options.mode : 'active',
      capacityMode: options.capacityMode === 'tokens' ? 'tokens' : 'ratio',
      capacityPercent: clamp(options.capacityPercent, 1, 100, 100),
      effectiveWindowTokens:
        Number.isInteger(options.effectiveWindowTokens) && options.effectiveWindowTokens >= 0
          ? options.effectiveWindowTokens
          : 256000,
      capacityTokens:
        Number.isInteger(options.capacityTokens) && options.capacityTokens >= 1024
          ? options.capacityTokens
          : 100000,
      warnRatio,
      forceRatio: Math.max(warnRatio, forceRatio),
      retainRatio: clamp(options.retainRatio, 0, 0.5, 0),
      minReclaimRatio: clamp(options.minReclaimRatio, 0, 1, 0.15),
      selection: options.selection === 'basic' || options.selection === 'deterministic' ? options.selection : 'selective',
      strategy: options.strategy === 'selection' ? 'selection' : 'nosig',
      nosigVerification: ['cite', 'quote'].includes(options.nosigVerification)
        ? options.nosigVerification : 'literal',
      nosigSegmentBytes:
        Number.isInteger(options.nosigSegmentBytes) && options.nosigSegmentBytes >= 4096
          ? options.nosigSegmentBytes : 24000,
      nosigEntryCap:
        Number.isInteger(options.nosigEntryCap) && options.nosigEntryCap >= 1
          ? Math.min(50, options.nosigEntryCap) : 5,
      nosigRevisionCap:
        Number.isInteger(options.nosigRevisionCap) && options.nosigRevisionCap >= 1
          ? Math.min(20, options.nosigRevisionCap) : 3,
      nosigLedgerBytes:
        Number.isInteger(options.nosigLedgerBytes) && options.nosigLedgerBytes >= 400
          ? options.nosigLedgerBytes : 8000,
      ledgerCapBytes:
        Number.isInteger(options.ledgerCapBytes) && options.ledgerCapBytes >= 0
          ? options.ledgerCapBytes : 8000,
      ledgerDenoise: options.ledgerDenoise !== false,
      nosigMaxTokens:
        Number.isInteger(options.nosigMaxTokens) && options.nosigMaxTokens >= 1024
          ? options.nosigMaxTokens : 8192,
      selectionMinTokens: Number.isSafeInteger(options.selectionMinTokens) && options.selectionMinTokens >= 0
        ? options.selectionMinTokens : 0,
      continuityReceipts: options.continuityReceipts === true,
      dedupeCarriedState: options.dedupeCarriedState === true,
      stateSelectionContext: options.stateSelectionContext === true,
      pruneBeforeCheckpoint: options.pruneBeforeCheckpoint === true,
      // How the selection request addresses the region: 'quotes' copies the
      // text back (shipped), 'lines' names line ranges and the engine copies.
      selectionAddress: options.selectionAddress === 'lines' ? 'lines' : 'quotes',
      controlItemCap:
        Number.isInteger(options.controlItemCap) && options.controlItemCap >= 0
          ? options.controlItemCap
          : 800,
      controlMaxBytes:
        Number.isInteger(options.controlMaxBytes) && options.controlMaxBytes >= 0
          ? options.controlMaxBytes
          : 0,
      controlMode: options.controlMode === 'command-state' ? 'command-state' : 'quotes',
      originMaxChars:
        Number.isInteger(options.originMaxChars) && options.originMaxChars >= 160
          ? options.originMaxChars : 1200,
      activeCommandMaxChars:
        Number.isInteger(options.activeCommandMaxChars) && options.activeCommandMaxChars >= 120
          ? options.activeCommandMaxChars : 400,
      commandHeadChars:
        Number.isInteger(options.commandHeadChars) && options.commandHeadChars >= 24
          ? options.commandHeadChars : 96,
      commandSectionBytes:
        Number.isInteger(options.commandSectionBytes) && options.commandSectionBytes >= 400
          ? options.commandSectionBytes : 1800,
      commandDoneLines:
        Number.isInteger(options.commandDoneLines) && options.commandDoneLines >= 0
          ? Math.min(24, options.commandDoneLines) : 3,
      passageWorkingset: options.payloadWorkingset === true || options.passageWorkingset === true,
      stateFromControls: options.stateFromControls !== false,
      passageRecent: options.passageRecent !== false,
      passageLatest: options.passageLatest !== false,
      nosigReasoningEffort: typeof options.nosigReasoningEffort === 'string'
        ? options.nosigReasoningEffort.trim()
        : '',
      selectionMaxTokens:
        Number.isInteger(options.selectionMaxTokens) && options.selectionMaxTokens >= 1024
          ? options.selectionMaxTokens
          : 4096,
      payload: resolvePayloadPolicy(options),
      workingset:
        options.payloadWorkingset === true || options.passageWorkingset === true
          ? {
              maxFiles: Number.isInteger(options.payloadWorkingsetFiles)
                ? Math.max(0, options.payloadWorkingsetFiles)
                : 8,
              capChars: Number.isInteger(options.payloadWorkingsetItemCap)
                ? Math.max(200, options.payloadWorkingsetItemCap)
                : 1200,
              version: Number.isInteger(options.payloadWorkingsetVersion)
                ? options.payloadWorkingsetVersion
                : 1,
              sectionCap: Number.isInteger(options.payloadWorkingsetSectionCap)
                ? Math.max(400, options.payloadWorkingsetSectionCap)
                : 1500,
            }
          : undefined,
      state:
        options.payloadStateNarrative === true
          ? {
              cap: Number.isInteger(options.payloadStateCap)
                ? Math.max(400, options.payloadStateCap)
                : 900,
            }
          : undefined,
      outputs:
        options.payloadBackfill === true
          ? {
              items: Number.isInteger(options.payloadBackfillItems)
                ? Math.max(0, options.payloadBackfillItems)
                : 10,
              cap: Number.isInteger(options.payloadBackfillItemCap)
                ? Math.max(200, options.payloadBackfillItemCap)
                : 900,
            }
          : undefined,
      denoise: options.denoise !== false,
      evidenceTool: options.evidenceTool !== false,
      evidenceIndexRows:
        Number.isInteger(options.evidenceIndexRows) && options.evidenceIndexRows >= 0
          ? Math.min(20, options.evidenceIndexRows) : 20,
      extractDelta: options.extractDelta === true,
      receiptSeq: options.receiptSeq !== false,
      // The board compares a request's seq with an edit's seq; without durable
      // seqs the comparison would mix positions with session numbers.
      requirementBoard: options.requirementBoard === true && options.receiptSeq !== false,
    })

    // The bundle ships its own Settings page; keep the schema-derived page off
    // so the two never render the same fields twice.
    ctx.inject(['settings'], (child) => {
      child.effect(() => child.settings.configure({ auto: false }, ctx.fiber))
    })
  }
}

