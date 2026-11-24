# 引擎设计记录（2026-11-17 至 11-20）

> 这是移植 WSC 语义时的工程记录，保留“为什么这样做”和各项的验收方式。
> 其中提到的 `D:\lea\XenYon code\wsc` 是当时的 Python 参考实现，不在本仓库内；
> 2026-11-21 之后的长跑结论见 `experiments/过往实验/`。

# dsh-wsc — pending work

Tracked so the remaining WSC semantics are not lost between sessions.

## Done

- Version/verification relation section (`## Verification state`), so a check
  that ran before a file change is not read as verifying the current file.
- Evidence retrieval tool `read_history` (seq read + literal query over the
  whole session log), registered per agent.
- Control vs model layering: control messages are their own section, assistant
  quotes carry a role prefix, prior checkpoints are labelled historical.
- Prior-checkpoint drift control: only the newest one is kept, its framing is
  stripped, and it is labelled historical.
- Cost ledger: `$DSH_HOME/wsc/compactions.jsonl`, one row per durable
  `compaction/summary`.
- Understanding layer, text-embedded version: selective selection may return
  `facts: [{ text, sources }]`; each fact is kept only when it cites at least
  one kept quote, rendered as `## Recorded judgments` with `[sN]` references.
  No CAS; the next checkpoint supersedes the previous set.
- Control-cap and selection-budget defects: `controlItemCap` (default 4000,
  UTF-8 bytes) and `selectionMaxTokens` (default 16384) are configuration, and
  every compaction row now carries `control` / `selection` telemetry. Verified
  by offline replay of the recorded B runs; see
  `experiments/report/FIX-AB.md`.

## Understanding layer — durable store

Records now live in `lib/understanding.js` (append-only journal, CAS revisions,
exact `id@revision` refs). What is still deferred is the engine consuming them:
`facts` are rendered inline from the checkpoint text today, and item 6 in the
parity plan tracks the remaining wiring.

## Original WSC record model (reference)

WSC stores a model's explicit judgments as records with:

- sources (source ids that support the judgment),
- category,
- scope (where it applies),
- version / CAS revision,
- no upgrade of a source-less assumption into a fact.

DSH has no equivalent. Design questions before implementing:

1. Where do records live? A new session event type is forbidden (readers reject
   unknown types unless `ignorable: true`, which live append cannot set).
   Options: a storage-domain record keyed by session, or encode them inside the
   checkpoint text with durable ids.
2. How are they revised without breaking replay?
3. How does selective selection reference them (quote ids, record ids)?

## Parity plan (ordered; implement, then test each item)

Reference implementation: `D:\lea\XenYon code\wsc` (python). Every item is
"same mechanism, DSH-shaped wiring only".

1. **Byte budget** — DONE. `lib/bytes.js` (`byteLength`, `jsonBytes`,
   `truncateBytes`); `lib/checkpoint.js` now measures source, budget, section
   allocations and the final cut in UTF-8 bytes (`sourceBytes`, `mandatoryBytes`);
   `engine.js` compares and logs bytes. Tests: `checkpoint: a CJK region is
   budgeted in UTF-8 bytes, not characters`.
2. **Span / exact-fragment selection** — DONE. `lib/excerpts.js` ports
   `excerpts.py` (`textAt`, `resolveExcerpt`, code-point offsets, digest check)
   and `span_boundaries.py` (`ranges`); `lib/selection.js` owns the selection
   surface. The request shows a numbered transcript (`[m<n> <role>]`) built from
   the same numbering the engine resolves against, so the model can address a
   span or an exact fragment as well as a verbatim quote; quotes are still
   verified against the original bytes, and the labels exist only inside the
   request. An oversized region is not projected, and addressed selections are
   then refused rather than resolved against a transcript the model never saw.
   `buildSelectiveCheckpoint` takes `spans`/`fragments` and reports
   `droppedExcerpts`. Tests: `selective:` and `selection:` cases.
3. **Evidence read API** — DONE. `lib/evidence.js` ports `evidence.py`:
   `canonicalJson`/`digest`, `read` (authorize → integrity re-hash against the
   digest recorded at shadowing → exact byte slice → re-authorize, returning
   `read_sha256`/`object_sha256`/`total_bytes`/`complete`), plus `writeOnce`,
   `sameBytes`, `linkLike` and `exportSources` for the lease/export work.
   Shadowed observations are recorded in `$DSH_HOME/wsc/evidence/<session>.jsonl`
   by the ledger; `read_evidence` is registered beside `read_history` and reads
   only seqs that index grants, so an unrecorded seq is refused without
   revealing bytes. Tests: `evidence:` cases.
4. **`reconcile` / unknown-install** — DONE, narrowed by evidence. DSH has no
   bracket transaction or orphan lock: the plugin contract is `eventAt(seq)` plus
   one atomic `compaction/summary` append, so there is no lost-reply window to
   reconcile. What transfers is the binding half of `publication.py`, and it is
   real: `lib/publication.js` ports the operation lifecycle
   (`ready → installing → confirmed`/`rejected`, `unknown`,
   `recovery_required`), `checkBinding` (session, provider, model, package
   digest, `installedThrough`, non-empty receiver, `evidenceAccessible`),
   `confirm`, `install`, `reconcile`, `discard` and a per-session journal at
   `$DSH_HOME/wsc/operations/<session>.jsonl`. `summarize` records the package
   it is about to publish; the ledger confirms only a digest this engine issued
   and reports `unknown_install` otherwise, recording evidence only for a
   confirmed install. Tests: `publication:` cases.
5. **Resource leases + install-time evidence re-check** — DONE, with a stated
   limit. `lib/resources.js` ports `resource_io.py`: `ResourceIO` with a chunk
   budget, `withOpened` (refuses a link leaf, re-checks identity/size/mtime_ns
   after the body), `equal`, `digest` (byte budget + deadline), `readBounded`,
   `capabilities`, `writeOnce` (pending file → fsync → `link`, so an existing
   object is never replaced), `publicationWriter` (memoized while handles pin
   the object), `lease` (every named object plus every parent directory, with a
   handle budget and `installation_resource_unavailable` /
   `installation_resource_budget_exhausted`), `collectPaths` and
   `checkEvidence` (`exported_source_changed` / `exported_readable_changed` /
   `exported_index_changed` / `exported_projection_index_changed` /
   `exported_source_unavailable`). Limit: JavaScript cannot set a Windows share
   mode, so a lease is an identity lease — it records volume/file index, size
   and mtime, holds file handles open, and `verify()` fails closed on drift;
   `capabilities().installation_path_leases` reports `identity`, not `true`.
   Engine producer: the compaction ledger exports every shadowed observation
   with `writeOnce` to `$DSH_HOME/wsc/evidence/<session>/<seq>.json`, records
   `{file_path, sha256: digest(message)}` locators, re-checks them with
   `checkEvidence` before confirming the install, and stores the locators on the
   confirmed operation row (a failed export is reported and leaves no
   locators). Tests: `resources:` cases plus the export/lease step of
   `tests/integration.test.mjs`.

6. **Durable understanding store** — DONE (store + engine write path).
   `lib/understanding.js` ports `understanding.py` + `understanding_identity.py`:
   `UnderstandingStore` over an append-only per-session journal
   (`all`, `resolve` by exact `id@revision`, `epoch`, `write`), with
   compare-and-swap on the stored revision (`understanding_revision_conflict`),
   an optional allowed-source set (`understanding_source_missing`), identifier
   and scope validation, and replay from the journal after a restart. Tests:
   `understanding:` cases.
   Engine wiring: `buildSelectiveCheckpoint` now returns `keptFacts`
   (`{text, sources: ['sN']}`) alongside the rendered section;
   `#summarizeSelective` passes them up; `#recordReady` stores them in the
   operation package; the compaction ledger hook writes one record per kept
   fact (`kind: 'judgment'`, `producer: 'selection'`, `sources` = cited refs,
   `scope = { session, shadowedSeqs }`) after a confirmed install, and skips a
   fact whose text and scope already exist so a replayed hook adds no revision.
   `tests/integration.test.mjs` walks the whole chain (checkpoint → package
   digest → confirm → evidence → record → lease → tamper).
   Still open: the checkpoint still renders the inline list; the next step is to
   render current records (`store.epoch()`) instead. Provenance is checkpoint
   refs, not seqs: the builder resolves a quote to `sN`, so seq provenance needs
   the quote → seq map surfaced from the builder.

7. **nosig passage** — DONE for the nosig strategy. `lib/passage.js` ports
   `passage.py` (`LABELS`, `RANK`, ranked deduped ledger sentences, the
   `State: done…` sentence and next banner, the last-four `Checks` receipts,
   newest-first values with archived keys, the index paragraph, and the
   index → oldest values → lowest-rank ledger trim order). `lib/evidence-index.js`
   ports `index_from_events` (per-kind labels, dedupe fingerprint, one slot per
   kind before quotas, caps, `E<n>` keys). `lib/values.js` unwraps the
   `<path>/<type>/<content>` envelope before naming a value and normalizes
   absolute tool paths to the workspace's short form; `lib/state.js` matches
   short and absolute paths to the same edit. Control text accumulates across
   compactions in the nosig journal (`op: 'control'`), so the passage always
   quotes every user request; the checkpoint state is rendered as the DSH
   `## Current state` block (so `assertCheckpointState` can publish it) instead
   of the reference's `State:` sentence. Engine notices (user-role checkpoint
   text) and run/read-only probes are not turned into requirements.
   Checkpoint size on the 25-round smoke: 6.9k bytes for a region of 10.5k
   shadowed tokens.



## Essential causes found after the passage port (2026-11-21)

Measured from the 25-round production runs, not guessed:

1. **The value ledger forgot across regions.** Engine values were computed from
   the current shadowed range only; the reference computes them over every
   event of the session. A constant read in round 3 disappeared at the next
   compaction, and a no-read continuity probe then guessed the tax rate wrong
   (8.75% instead of 0.07). Fixed: the nosig journal now persists value rows
   (`op: 'value'`), assigns each value one key at first sight, dedupes by text,
   and the passage renders the accumulated list.
2. **Control text grew without a bound.** The verbatim control paragraph was
   1.2k of a 5.1k checkpoint at the first compaction and 3.6k of 8.6k at the
   sixth — 41% of the checkpoint, and in a longer session it would crowd out
   the ledger, values and index. Fixed as an option (`controlMaxBytes`): the
   newest quotes stay verbatim, older whole messages are omitted with a
   disclosure; 0 keeps the reference behaviour.
3. **The passage dropped file bodies while native keeps code.** In the clean
   25-round A/B the nosig arm made 48 reads and 36 shell calls against native's
   34 and 25. Fixed as an option (`passageWorkingset`): the v2 working set is
   appended between state and checks, seeded from the previous checkpoint so a
   file the current region never saw still carries its body.
4. **Extraction rejections were counted, not explained.** The ledger stored
   only `rejected: n`; the reason (`literal-not-in-cite`, `unknown-ref`, …) was
   dropped. Telemetry now carries a reason histogram per compaction.
5. **The 60% notice can cost a step.** The model sometimes answers the current
   task, then spends an extra step on the pressure notice. It is a trigger
   policy choice, not a passage defect; keep it visible in the cost report.

## Verification still owed

- Production A/B vs dsh native compaction, after the nosig passage port: DONE
  for a 32k window, 25 scripted rounds, deepseek-flash, clean rerun. Result:
  6 compactions vs 9, cost 0.79x, wall 0.86x, both repos 20/20 tests, both
  continuity probes answered with zero reads. See
  `doc/dsh-wsc-production-ab-20261121.md`.
- Production A/B vs dsh native compaction, section-checkpoint version: DONE for
  the same 32k window and 25 rounds. Result: 9 compactions vs 8, cost 1.28x,
  wall 1.47x, continuity equal (both probes answered with zero reads, both
  repos pass tests). See `doc/dsh-wsc-production-ab-20261120.md`.
- The first run (36 compactions, 1.96x) measured code defaults: desktop
  schemastery hands volatile fields as `{ get }` cells, so every profile value
  was discarded. `index.js` now unwraps cells; all earlier live-profile runs
  were affected.
- Fixed by that run: `session.events` is absent in this DSH build (only
  `session.log`/`eventAt`), so every install threw in `#recordReady`; float
  journal segment orders; duplicate re-extracted facts; extraction gaps now
  name their reason.
- `minReclaimRatio` is not a frequency lever: forced compactions bypass it, and
  reclaim is measured on the whole context. Frequency is set by the capacity
  baseline and retain ratio (now effective).
- Next: reduce extraction gaps (1-2 failed segments per compaction), and the
  60% notice that spends a whole turn on `compact_context`; 1M-window and GLM
  runs are still owed.
- 80% notice and 85% forced compaction on a real long session.
- Selective compaction against a real model (quote match rate, fallback rate).
- Runtime denoise on a real tool result (spill pointer present, original readable).
- A/B: `selection: basic` vs `selective` vs `deterministic` on the same session.
- Settings page after a DSH restart (client roster is built at boot).
- Understanding records on a live install: the desktop profile runs
  `mode: shadow`, which never installs, so the write path needs one session in
  `mode: live` (then check `<DSH_HOME>/wsc/understanding/<session>.jsonl`).

## Production matrix: does nosig beat dsh native? (2026-11-21)

Four scenarios (feature-25, long-40, refactor-18, bugfix-16), five arms
(native, wsc, cap, ws, fix), 46 runs, deepseek-flash 32k. Full record:
`doc/experiment_results/prod-matrix-20261121/`.

- **WSC beats native in every scenario**: median cost 0.47x (long-40), 0.65x
  (feature-25), 0.77x (refactor-18), 0.85x (bugfix-16); compactions roughly
  half. The saving is almost entirely uncached input (native re-sends each
  summary every turn: 0.28-0.31 CNY in long-40 vs 0.02-0.03).
- **Correctness equal**: all 46 runs pass `node --test`; 40/46 probes are full,
  the 6 misses are all `TAX_RATE=0.07` in runs that never read `store.js`
  (native and WSC miss alike), not compaction loss.
- **Neither candidate knob joins the defaults.** `controlMaxBytes=6000` only
  moved refactor-18 (0.80x of baseline; flat elsewhere); `passageWorkingset`
  was flat (0.90-0.98x), did not reduce reads consistently, and enlarged the
  checkpoint. The `fix` bundle is 0.83x/0.95x in refactor/long but 1.05x/1.11x
  in feature/bugfix. Default stays `controlMaxBytes=0`,
  `passageWorkingset=false`; both remain opt-in.
- **Merged and verified by the matrix**: value-ledger persistence across
  regions, state/path/synthetic-notice fixes, extraction rejection histogram.
- Residual: run-to-run variance is still large (refactor wsc 0.187-0.323,
  one run called `compact_context` four times); output is now 72-82% of cost,
  so further work should target turns/output rather than checkpoint bytes.

## Checkpoint state fix and warning threshold (2026-11-21)

Reading the actual checkpoints exposed a defect the scores did not show: in
87% of long-run checkpoints the state block had no Done/Open/Next rows (journal:
80 facts, 8 decisions, 0 requirements). The reference projects requirements from
all events; DSH used only the current region and dropped unmatched requests.

- **Fixed by default** (`stateFromControls`): requirements are synthesized over
  the accumulated controls and the newest unmatched request becomes `Next`.
  `passageRecent` adds a three-path Recent changes block; `passageLatest`
  restates the latest request at the top of long quote lists.
- **`warnRatio` 0.8**: the 60% pressure notice arrives as a new user turn after
  the answer, costing a step and leaving a meta final. At 80% (equal to the
  force ratio) the probe round answers in one step.
- **Same-day controlled run** (long-40, old shape vs new): cost median
  CNY 0.459 -> 0.429; empty-state checkpoints 87% -> 9.6%; final answer 2/2 ->
  3/3. New-function and refactor scenarios stay neutral or improve (0.169 vs
  0.161; 0.207 vs 0.238). Tests and probes all pass.
- **Not merged**: `controlMaxBytes` and `passageWorkingset` stay off.
- The `desktop` profile now sets `warnRatio: 0.8`; one app restart loads the new
  engine and this value.

## Extraction, values and variance root causes (2026-11-23)

Full record: `doc/experiment_results/prod-matrix-20261121/root-causes-20261123.md`.

- **Gap lines: 408/616 checkpoints (66.2%)** were mostly partial rejections, not
  failed extractions: 369 "N entries rejected", 30 not finished, 4 non-JSON, 2
  empty. Causes: cite index drift, revision refs pointing outside the 4KB prior
  window, one-attempt stream/truncation failures, and gap disclosure even for
  partial or empty results.
- **Fixed**: re-locate a misplaced cite when the literal is elsewhere in the
  region (strong anchors only); convert a revision with an unknown ref into an
  addition (dedupe by text; stale refs still rejected); retry thrown calls and
  ask for a smaller answer after `finish=length`; prior ledger 4KB -> 8KB; an
  empty well-formed answer is no longer a gap. New counters: `recovered`,
  `converted`.
- **Verified**: feature-25 w80 was 12/21 checkpoints with gaps before; rep5 (new
  code) is 0/4, probe 5/5, tests 20/20, extraction CNY 0.080. Off rep2 also 0/4.
  long-40 w80 was 11/20, 16/28, 21/25, 14/21; rep5 is 0/18, probe 6/6, tests
  36/36, total CNY 0.726 (rep4 0.854). `npm test` 222 pass.
- **Value noise**: 14,584 value rows over 616 checkpoints were 85.6% file
  snapshots, test files, spill paths and JSON payloads; only 2 labels were real
  constants. `values.js` now distills numeric assignments from non-test file
  reads, keyed by `path#name`, updating in place. Replay of three sessions:
  126/148/46 reads -> 3/3/2 constants. rep5 checkpoint shows one clean
  `TAX_RATE = 0.07`.
- **Cost accounting**: extraction calls were outside the matrix cost. Journal
  `op:"usage"` now records them (~CNY 0.020/compaction; 0.080 for 4 compactions).
  Native compaction calls are likewise absent and are estimated from shadowed
  tokens + summary size. Full cost: feature-25 ~0.38 vs 0.21-0.26, long-40 ~1.35
  vs 0.73-0.85, i.e. WSC 0.54-0.69x, not the main-loop-only 0.47-0.65x.
- **Variance**: compaction count correlates 0.978 with output tokens and 0.931
  with steps; the CNY 0.571/40-compaction outlier read report.js 39 times and
  report.test.mjs 33 times (207 reads total; native also re-reads). Work volume,
  not engine thrash. Keep warnRatio 0.8 and compare medians on same-day pairs.
- **Still open**: reasoning-off default decision (preliminary: ~18% cheaper
  extraction, equal probes); native compaction usage instrumentation.

## Determinism-first rule (2026-11-23, confirmed)

凡是能从 session 事件、receipts、edit/check 关系、账本和文件状态机械判定的内容，
在质量不退化的前提下，一律由引擎判定；模型只负责需要语义理解的“新观察/决定”，
其输出必须再经过机械校验（literal/cite/ref/预算）。禁止用模型调用替代可确定规则。

审计结果：

| 环节 | 判定方 | 说明 |
|---|---|---|
| 用户命令状态 done/open/next | 引擎 | receipts 的 edit + post-edit check |
| 第一条真命令 | 引擎 | 控制序列第一条非空、非 continue 的用户消息 |
| 命令被后续替代 | 引擎 | 后续控制共享显著词且含 change/instead/replace 等 |
| 值账本 | 引擎 | 文件 read 的数值赋值蒸馏 |
| 机械检查/修改关系 | 引擎 | receiptsFromRows |
| 索引 seq 指向 | 引擎 | 结果事件序号，必须离线可解析 |
| 探针判分 | 引擎 | must/forbid 断言，不做关键词“提及即通过” |
| 抽取接受/拒绝 | 引擎校验 | 模型只产候选，literal/cite/ref 由引擎判 |
| 抽取新关系 | 模型 | 语义提炼，无法机械生成 |
| 状态叙事（可选） | 模型 | 默认关闭；开启时只作 prose，不参与状态判定 |

实现新臂时不得增加模型调用；状态分类、渲染、省略与预算都必须有纯函数单测。

### Command-state arm (implemented 2026-11-23)

- `lib/command-state.js`: `classifyCommands()` + `renderCommandState()`. The first
  real command stays verbatim; later commands become `done/open/next/unknown/
  superseded/recorded` lines. A supersede requires the same file path and the
  same identifier plus a change word, so independent fixes are not relabelled.
  Only the newest `commandDoneLines` (default 3) completed/superseded lines stay;
  older ones are dropped. The block is bounded by `commandSectionBytes` (1800).
- Config: `controlMode: command-state` (default `quotes`), `originMaxChars`,
  `activeCommandMaxChars`, `commandHeadChars`, `commandSectionBytes`,
  `commandDoneLines`. Profile `wsc-cmd`; matrix arm `cmd`.
- State projection still consumes every control; command state is presentation
  only. No model call is added. `npm test` 228 pass (6 command-state tests).
- The command block is bounded: 559 B at the end of a 40-round run, versus
  5,498 B of quoted controls in w80.
- `long-40/cmd` first clean sample (before the ledger cap) was an outlier:
  44 compactions, main CNY 0.740, extraction CNY 0.984, total 1.724, strict
  probe 5/6, tests 41/41, one `max-tokens` extraction gap. Its ledger reached
  14.9k, so the ledger, not controls, was the remaining growth source.
- Added `capLedger()` in command mode: active entries capped by
  `nosigLedgerBytes` (8k), high rank first, newest first within rank, omitted
  count disclosed. Offline projection of the same run: 14.9k -> ~8.0k, final
  checkpoint 16.7k -> ~10.3k.
- Extraction retry now recognizes `max-tokens`/`truncat` as truncation, not
  only `length`. `npm test` 230 pass.
- Remaining work: one final `long-40/cmd` clean run with the ledger cap; feature
  run in progress. Acceptance: checkpoint <=12.5k at 40 rounds, no test/probe
  regression, cost <= w80 +5%.

### Strict probe correction (2026-11-23)

- `probe.json` now accepts `{must, forbid, source}`; scoring reads only the
  final answer text, not tool results or the user prompt. The old haystack
  included the prompt, so a run that never answered still scored 6/6.
- `long-40` fact 6 is now strict (`amountWithTaxCents`, `dry-run`; forbid
  `pre-tax`). Re-scored: native rep1 6/6, native rep2 5/6, w80 rep5 5/6;
  several long arms that ended with a meta message now score 0/6.
- Feature-25 stays 5/5 under strict scoring.

## Six-step consolidation (2026-11-23)

1. **P0 strict probes + constraint scenario — done.** `probe.json` now reads
   only the final answer and supports `must/forbid`. `feature-25` fact 5 is
   strict (`JSON`, `CSV`), `long-40` fact 6 is strict (`amountWithTaxCents`,
   `dry-run`; forbid `pre-tax`). New `constraint-25` scenario: the first command
   creates a README `## Compatibility` section with `BLUEBIRD` and requires all
   later rounds to preserve it; final probe asks for the word plus TAX_RATE,
   REPORT_LIMIT and summary fields.
2. **P1 persistent receipts — done.** Journal stores `op:"receipt"`
   `{path, edit, check, terms}` keyed by edit seq; replay dedupes and rebuilds
   the check list. Command completion uses receipts across regions, not only
   the current one. No model call. `npm test` 231 pass.
3. **P2 ledger cap pricing — pending.** Add a quotes-mode `ledgerCapBytes` and
   an arm `ledger`; compare 40-round checkpoint bytes/quality against w80.
4. **P3 cmd final A/B — pending.** cmd x2 vs w80 x2 on long-40, plus
   constraint-25; strict probe, tests, checkpoint <=12.5k, cost <= w80 +5%.
5. **P4 working-set switch — pending.** One switch (`payloadWorkingset`), gate
   profiles until A/B; quotes-mode `w80` vs `ws2`, then `cmd` vs `cmd+ws`.
6. **P5 index seq — pending.** Result seq, `read_history seq=`, offline
   resolution assertion, call-rate and exactness metric.

After P6, phase 7: low-cost exact-code retention (delta cards), see the
discussion in the report, not yet implemented.

## Composition gaps

- `standard` preset is not overridden; only `cordis` uses the WSC engine.
