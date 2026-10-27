# Deterministic benchmark v0.1 — capability-qualified MVP

## Actual WSC boundary qualification (2026-10-27)

`wsc_blackbox_admission.py` connects the existing native incremental selector and
indexed checkpoint policy. `resume_wsc_blackbox.py` reuses an already-generated,
never-probed package if an administrative transfer check failed; it never
regenerates selection. `native_blackbox_sessions.py` separates fresh configuration
from first-import durability and audits effective material using existing native
transport-field rules. These are qualification entry points, not the final matrix
runner. Do not blindly rerun their already-executed output directories.

The genuine WSC branch now answered the same two questions 2/2: 21,618 selection
plus 20,473 continuation tokens, with complete receipts. It retained one whole
source and a span, with no new understanding; the 335-byte business observation
became a 1,293-byte package. Thus this validates the integration, not compression
efficiency or long-horizon superiority. Original readiness/import failures remain
saved. No production WSC algorithm change or fabricated installation receipt.

## Black-box revision (2026-10-27; authoritative for native behavior evaluation)

Native summary visibility is not a prerequisite. `blackbox.py` scores typed
answers from the tested Agent with deterministic comparisons; it never judges
encrypted summary content. `native_capability.py` checks live sibling-history
equivalence without inference. `native_blackbox_smoke.py` requires `--execute`
and explicit registration, capability, parent budget and new output paths.
One bounded smoke has already run: actual native compression confirmed, sibling
baseline/post probes both 2/2, three complete receipts totaling 60,291 tokens.
Do not rerun it merely to recheck this result. See the current black-box feasibility
report in `wsc/reviews/2026-10-27-blackbox-benchmark-feasibility.md`.

This is not yet a native-versus-WSC behavior comparison. Existing `run.py` below
remains the deterministic mechanism suite. Its direct opaque-content abstention
does not imply native black-box behavior is unscorable. Use sibling probes to
avoid pre-query contamination; keep multi-round trunks unprobed.

`run.py --case artifact-lifecycle` and `--case version-validation` add named
structured counterfactuals. Fixed stale source selections are negative controls,
not evidence against the normal WSC semantic selector. Task scope is enforced.

This is an opt-in benchmark, not a change to WSC's compression algorithm.
No scoring/extraction/ground-truth LLM is called. Python 3.11 and the project's
standard library are sufficient; matplotlib is optional for plots.

## Investigation, before implementation

* `wsc/src/wsc/core.py`: capture/material expose a source-bound snapshot;
  prepare consumes caller-authored Selection; generate delegates to GeneratorPort.
  There is no built-in semantic model or automatic trigger in the core.
* `store.py`: SQLite events, understandings, views, operations, usage.
  `publication.py` stages actual checkpoints and requires a real host receipt for
  installation. This benchmark never manufactures a production receipt.
* `adapters/codex.py`: explicit checkpoint conversion, not transparent native
  compaction. Structured facts are fixtures, not an assumed production WSC format.
* Native `experiments/native_application_session.py` already calls
  `thread/compact/start`. Existing actual records bind usage to compaction response
  IDs. Observed native replacement histories contain encrypted compaction items.
* Existing registrations pin CLI/model/effort. That does not prove control of the
  internal summarizer's model, temperature, seed, prompt, or provider routing.
  Original history and event order can be fixed; internal semantics cannot be read.
* No tiktoken/tokenizers installation was found during this investigation.
  Encoding token counts are optional and are not automatically exact model billing
  or native capacity counts. Equal-token experiments deliberately fail admission
  until a common, verified accounting/capacity contract is supplied.

## Components

* `dataset.py`: seeded public event stream, separately bound private answers.
  Records have fact ID, typed value, validity interval, priority, dependency and
  task. Gold does not enter compression input. Fixtures model constraints,
  updates, overwrites, conflicts, distance/noise, switching, expiry and relations.
  These are a small structured protocol, not twelve fully validated natural-language suites.
* `adapters.py`: real WSC stage/read, uncompressed identity control, and actual
  native archive audit. The identity control is **never** called native Codex.
  Full/empty fixed selections are mechanism controls, not a new semantic selector.
* `evaluator.py`: one shared protocol decoder and deterministic state evaluator.
  Scores exact typed values and version relationships, never keyword presence.
  Natural-language paraphrases and encrypted summaries abstain. Such coverage
  cannot be ranked against fully decodable data as though it were zero accuracy.
* `run.py`: public-only adapter inputs; compression finishes before answers or
  scores are saved. Each cell retains raw product/error, config, timing and source
  hashes. Output directories are exclusive; re-runs never overwrite old failures.
* `report.py`: JSON, CSV, Markdown, local plots and narrowly scoped byte Pareto.
  Missing token plots/native comparisons are explicitly unavailable.

## Commands (PowerShell, from repository root)

```powershell
py -3.11 -B -X utf8 -m pytest wsc/tests/test_deterministic_benchmark.py -q

py -3.11 -B -X utf8 wsc/benchmarks/deterministic_v1/run.py --rounds 5 --noise 2 --seed 1 --out D:/agent-task-runs/my-benchmark-unique

# Full recovery scan within a declared larger system resource budget:
py -3.11 -B -X utf8 wsc/benchmarks/deterministic_v1/run.py --adapters wsc-fixed-selection --selection-ordinals-json '[]' --rounds 5 --noise 2 --recovery-calls 128 --recovery-bytes 262144 --out D:/agent-task-runs/my-cold-benchmark-unique

# Retry failed adapters from the start, preserving stateful prefix semantics:
py -3.11 -B -X utf8 wsc/benchmarks/deterministic_v1/run.py --dataset D:/agent-task-runs/my-benchmark-unique/dataset.public.json --oracle D:/agent-task-runs/my-benchmark-unique/oracle.private.json --rerun-failed D:/agent-task-runs/my-benchmark-unique/results.json --out D:/agent-task-runs/my-retry-unique
```

`--rounds` accepts 1/5/10/20/50 and other positive integers. This controls repeated
stage-only replay, **not** actual repeated native installation/compaction. Large
matrices are intentionally not run before validating smaller cells.

`--byte-budget` bounds rendered context and currently also the independent WSC
serialized view. These are different resource surfaces: view rejection is retained
as an implementation failure, not attributed to semantic loss. No exact equal-token
algorithm comparison is claimed.

`--generator-command-json '["program", "arg"]' --model-config-json '{...}'`
with `--adapters wsc-generator` connects WSC's normal JsonCommandGenerator. The
caller must register the actual command, model, parameters, cost reporting and
allowed credentials/runtime. No such live generator was dispatched in this MVP.
Generator claims about usage/parameters remain unverified unless independently
bound. This CLI is not a hostile-process security sandbox: malicious adapters
with arbitrary host access are outside the isolation guarantee. Normal adapters
receive no answers, and no answers/results are on disk during compression.

`--native-archive ABSOLUTE_JSONL` audits a real existing native compaction. It
does not assert dataset equivalence. It is excluded from paired scores by default.
There is no fake native adapter and no silently launched native model session.

## Current scope and remaining work

Executed: deterministic scorer positive/negative checks, actual WSC stage-only
replay, bounded real evidence reads, actual native archive audit, error retention,
byte/quality plots and exact-field metrics. No WSC production algorithm changes.

Not executed/proven: actual semantic WSC selection against the new dataset,
matched-input live Codex compaction, verified equal-token resource comparisons,
native recovery parity, 10/20/50 real compaction cycles, free-text semantics,
stochastic confidence intervals, exact money costs, full long-horizon Agent gains.
Those limits are material, not a completed native-versus-WSC study.

Recovery reports index/data reads and returned bytes, including failed/partial
reads. Expanded context size is recorded separately; larger recovery resources
are system comparisons. Sequential scanning is a declared test policy, not proof
that a model can discover the right evidence. Stored export snapshots accumulate;
their size measures this stage-only harness, not steady-state production storage.
