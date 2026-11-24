/**
 * Deterministic view-level denoise rules, ported from XENYON `wsc/denoise`.
 *
 * Every rule rewrites a copy of the message content; the session log keeps the
 * original bytes. Rules never touch error results or non-text blocks.
 */
import { createHash } from 'node:crypto'

const ANSI = /\x1b\[[0-9;?]*[A-Za-z]/g
const DOTS = /^[.sFE]{8,}$/
const BLANKS = /\n{3,}/g

/** Every rule, in application order. */
export const ALL_DENOISE_RULES = [
  'strip_noise_lines',
  'collapse_stack',
  'diff_digest',
  'dedupe_identical',
  'dedupe_reads',
  'outline_json',
  'truncate_head_tail',
]

const textOf = (message) =>
  message.content
    .filter((block) => block.type === 'text')
    .map((block) => block.text)
    .join('\n')

const withText = (message, text) => ({
  ...message,
  content: [
    { type: 'text', text },
    ...message.content.filter((block) => block.type !== 'text'),
  ],
})

/** Drop ANSI escapes, carriage-return progress lines, pytest dots, and blank runs. */
export function stripNoiseLines(text) {
  const out = []
  for (const raw of text.split('\n')) {
    const line = raw.includes('\r') ? raw.split('\r').at(-1) : raw
    const cleaned = line.replace(ANSI, '')
    if (DOTS.test(cleaned.trim())) continue
    out.push(cleaned)
  }
  return out.join('\n').replace(BLANKS, '\n\n')
}

/** Collapse runs of identical consecutive lines into one line plus a count. */
export function collapseStack(text, minRun = 2) {
  const lines = text.split('\n')
  const out = []
  let index = 0
  while (index < lines.length) {
    let run = 1
    while (index + run < lines.length && lines[index + run] === lines[index]) run += 1
    out.push(run >= minRun ? `${lines[index]}  ×${run}` : lines.slice(index, index + run).join('\n'))
    index += run
  }
  return out.join('\n')
}

/**
 * Keep the actionable head and tail of an error stack.
 *
 * Error results are deliberately excluded from `applyDenoise` so a failure is
 * never rewritten silently. A selected error excerpt is different: the later
 * model needs the error string, the code and the first/last frames, not the
 * twenty middle frames that only repeat the call chain.
 */
export function trimErrorStack(text) {
  const lines = String(text ?? '').split('\n')
  const firstFrame = lines.findIndex((line) => /^\s+at\s/.test(line))
  if (firstFrame === -1) return text
  const head = lines.slice(0, Math.min(firstFrame + 3, lines.length))
  const tailStart = Math.max(head.length, lines.length - 3)
  const omitted = Math.max(0, tailStart - head.length)
  if (omitted === 0) return text
  return [...head, `…[${omitted} stack frames omitted]…`, ...lines.slice(tailStart)].join('\n')
}

const SIGNAL = /(?:Traceback|SyntaxError|NameError|TypeError|ValueError|KeyError|IndexError|ImportError|ModuleNotFoundError|AttributeError|OSError|FileNotFoundError|PermissionError|RuntimeError|AssertionError|RecursionError|IndentationError|CompileError|undefined reference|No such file|fatal error|FAILED|\bE\s{2,}|✗|✖|●|error:)/i
const TEST_HINT = /(?:Traceback|exception|error:|FAILED|FAILURES|✗|✖|●)/i

const SIGNAL_LINES = 8
const SIGNAL_CHARS = 800

const FAILURE_MIN_CHARS = 200
const FAILURE_MEMORY = 64

const normalizedFailureLine = (line) =>
  line
    .replace(/\b0x[0-9a-f]+\b/gi, '0x#')
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, '<uuid>')
    .replace(/\b\d+(?:\.\d+)?\s*(?:ms|msec|s|sec|secs|seconds?)\b/gi, '<duration>')
    .replace(/([A-Za-z0-9_./\\-]+):\d+(?=:|\s|$)/g, '$1:#')
    .replace(/:\d+:\d+/g, ':#:#')
    .replace(/\bline\s+\d+\b/gi, 'line #')
    .replace(/\b\d+(?:\.\d+)?%/g, '<pct>')
    .replace(/\s+/g, ' ')
    .trim()

/**
 * Stable identity for a failing result.
 *
 * Two runs of the same failure differ in durations, addresses and line numbers,
 * so one signal line plus a summary is too coarse: a different set of failing
 * tests can share both. The whole normalized output is hashed instead, so a fold
 * only happens when every remaining line is identical.
 */
export function failureFingerprint(text) {
  const raw = String(text ?? '')
  if (raw.length < FAILURE_MIN_CHARS || !SIGNAL.test(raw)) return undefined
  const lines = raw
    .split('\n')
    .map((line) => line.replace(ANSI, '').trim())
    .filter((line) => line !== '')
  const signal = lines.find((line) => SIGNAL.test(line))
  if (signal === undefined || signal.length < 12) return undefined
  const key = hashOf(lines.map(normalizedFailureLine).join('\n'))
  return { key, label: signal.slice(0, 160) }
}

/** Keep a few high-signal error lines from the middle being dropped. */
function signalExcerpt(text) {
  const kept = []
  const seen = new Set()
  let chars = 0
  for (const line of String(text ?? '').split('\n')) {
    if (!SIGNAL.test(line)) continue
    const key = line.trim()
    if (key === '' || seen.has(key)) continue
    seen.add(key)
    kept.push(key.slice(0, 200))
    chars += kept.at(-1).length
    if (kept.length >= SIGNAL_LINES || chars >= SIGNAL_CHARS) break
  }
  return kept.length === 0 ? '' : `[error excerpt preserved]\n${kept.join('\n')}`
}

/**
 * Keep a bounded head and tail, marking the omitted middle by size.
 *
 * Runtime command output is truncated after thousands of successful lines; an
 * error in the omitted middle would otherwise disappear. `rescue` keeps a few
 * high-signal lines from that middle.
 */
export function truncateHeadTail(text, head = 800, tail = 300, rescue = false) {
  if (text.length <= head + tail + 80) return text
  const omitted = text.length - head - tail
  const middle = text.slice(head, text.length - tail)
  const excerpt = rescue && !SIGNAL.test(text.slice(-tail)) ? signalExcerpt(middle) : ''
  const kept = excerpt === '' ? '' : `\n${excerpt}`
  return `${text.slice(0, head)}\n…[${omitted} chars omitted]…${kept}\n${text.slice(-tail)}`
}

const COMMAND_MIN_CHARS = 4000
const COMMAND_MAX_LINES = 120
const COMMAND_MAX_CHARS = 12000
const COMMAND_MAX_FILES = 40

const FAMILIES = [
  ['pytest', /(?:^|[\s;&|])(?:python(?:\d+(?:\.\d+)?)?\s+-m\s+)?pytest\b/],
  ['test', /(?:^|[\s;&|])(?:npx\s+|pnpm\s+|yarn\s+)?(?:vitest|jest)\b|(?:npm|pnpm|yarn)\s+test\b|(?:^|[\s;&|])(?:cargo\s+test|go\s+test)\b|(?:^|[\s;&|])node\s+--test\b|(?:^|[\s;&|])node\s+(?:--\S+\s+)*[^\s;&|]*\.test\.(?:mjs|cjs|js)\b/i],
  ['tsc', /(?:^|[\s;&|])(?:npx\s+)?tsc\b/i],
  ['lint', /(?:^|[\s;&|])(?:npx\s+|pnpm\s+|yarn\s+)?(?:eslint|ruff|biome)\b/i],
  ['git', /(?:^|[\s;&|])git\s+(?:status|log|diff)\b/i],
  ['build', /(?:^|[\s;&|])(?:cargo\s+(?:build|clippy)|(?:npm|pnpm|yarn)\s+run\s+build)\b/i],
]

/** Command family for log compaction, or '' when the output is not a known build/test log. */
export function commandFamily(command) {
  const text = String(command ?? '').trim()
  if (text === '') return ''
  for (const [family, pattern] of FAMILIES) if (pattern.test(text)) return family
  return ''
}

function bound(lines) {
  const kept = []
  let chars = 0
  for (const line of lines) {
    if (kept.length >= COMMAND_MAX_LINES || chars + line.length > COMMAND_MAX_CHARS) break
    kept.push(line)
    chars += line.length + 1
  }
  return kept.length === lines.length ? kept : [...kept, `…[${lines.length - kept.length} lines omitted]…`]
}

function compactPytest(text) {
  const lines = text.split('\n')
  const summary = [...lines].reverse().find((line) => /(?:passed|failed|error)/i.test(line) && /(?:=|summary)/i.test(line))
  const failures = []
  let block = false
  for (const line of lines) {
    if (/^=+\s*(?:FAILURES|ERRORS)\s*=+/.test(line)) {
      block = true
      failures.push(line)
      continue
    }
    if (block && /^=+\s*(?:\d+|short test summary)/i.test(line)) block = false
    if (block) failures.push(line)
    else if (/^(?:FAILED|ERROR)\s+\S+/.test(line)) failures.push(line)
  }
  const out = [summary, ...failures].filter((line) => line !== undefined)
  return out.length === 0 ? text : bound(out).join('\n')
}

function compactLines(text, keep, tailLines = 8) {
  const lines = text.split('\n')
  const selected = lines.filter(keep)
  const tail = lines.slice(-tailLines)
  for (const line of tail) if (!selected.includes(line)) selected.push(line)
  return selected.length === 0 ? text : bound(selected).join('\n')
}

const TSC_DIAGNOSTIC = /^([^\s(]+?)(?:\(\d+,\d+\)|:\d+:\d+)\s*:\s*(.+)$/

/** Group tsc diagnostics by file so one noisy file cannot crowd out the rest. */
function compactTsc(text) {
  const byFile = new Map()
  const other = []
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (line === '') continue
    const match = TSC_DIAGNOSTIC.exec(line)
    if (match !== null && /error TS\d+|warning TS\d+/.test(match[2])) {
      const list = byFile.get(match[1]) ?? []
      list.push(line)
      byFile.set(match[1], list)
    } else if (/error TS\d+/i.test(line)) {
      other.push(line)
    }
  }
  const total = [...byFile.values()].reduce((sum, list) => sum + list.length, other.length)
  if (total === 0) return text
  const out = [`tsc: ${total} issues in ${byFile.size} files`]
  let files = 0
  for (const [path, list] of byFile) {
    if (files >= COMMAND_MAX_FILES) {
      out.push(`… +${byFile.size - files} more files`)
      break
    }
    out.push(`${path}: ${list.length}`)
    out.push(...list.slice(0, 8).map((line) => `  ${line}`))
    if (list.length > 8) out.push(`  … +${list.length - 8} more`)
    files += 1
  }
  out.push(...other.slice(0, 40))
  return bound(out).join('\n')
}

/** Count status entries and keep log subjects; a unified diff is left to diffDigest. */
function compactGit(text) {
  if (text.includes('diff --git')) return text
  const lines = text.split('\n').filter((line) => line.trim() !== '')
  const statusLike = lines.some((line) => line.startsWith('## ') || /^(?:M|A|D|R|\?\?)\s/.test(line))
  if (statusLike) {
    let staged = 0
    let unstaged = 0
    let untracked = 0
    let branch = ''
    const samples = []
    for (const line of lines) {
      if (line.startsWith('## ')) {
        branch = line.slice(3).split('...')[0].trim()
        continue
      }
      if (line.startsWith('??')) untracked += 1
      else if ('MADRC'.includes(line[0])) staged += 1
      else if (line.length > 1 && 'MADRC'.includes(line[1])) unstaged += 1
      if (samples.length < 30) samples.push(line)
    }
    return [
      ...(branch === '' ? [] : [`branch: ${branch}`]),
      `dirty: staged=${staged} unstaged=${unstaged} untracked=${untracked}`,
      ...samples,
    ].join('\n')
  }
  const logish = lines.filter((line) => /^[0-9a-f]{7,}\b/.test(line) || line.startsWith('commit '))
  if (logish.length === 0) return text
  const out = logish.slice(0, 40)
  if (logish.length > 40) out.push(`… +${logish.length - 40} more commits`)
  return out.join('\n')
}

/**
 * Compress a known build/test command log before generic truncation.
 *
 * Failure lines and the final summary are preserved; unrecognised commands and
 * outputs that would not actually shrink are returned unchanged.
 */
export function compactCommandOutput(command, text, minChars = COMMAND_MIN_CHARS) {
  const raw = String(text ?? '')
  if (raw.length < minChars) return raw
  const family = commandFamily(command)
  if (family === '') return raw
  let next = raw
  if (family === 'pytest') next = compactPytest(raw)
  else if (family === 'test') next = compactLines(raw, (line) => /(?:FAIL|ERROR|✖|✗|●|Expected|Received|AssertionError|Tests?:|Test Files|Snapshots|test at |failing tests|^ℹ (?:tests|pass|fail|cancelled|skipped|todo|duration_ms))/i.test(line))
  else if (family === 'tsc') next = compactTsc(raw)
  else if (family === 'lint') next = compactLines(raw, (line) => /\b(?:error|warning)\b|problems?\b/i.test(line), 4)
  else if (family === 'git') next = compactGit(raw)
  else if (family === 'build') next = compactLines(raw, (line) => /(?:error|warning|failed|cannot|undefined reference|not found)/i.test(line))
  if (next === raw || next.length >= raw.length) return raw
  // A failure marker that disappeared means the compaction dropped evidence.
  if (TEST_HINT.test(raw) && !TEST_HINT.test(next)) return raw
  if (/error TS\d+/.test(raw) && !/error TS\d+/.test(next)) return raw
  return `${next.trimEnd()}\n\n[compacted ${family}]`
}

/** Replace a large JSON payload with a key/type outline. */
export function outlineJson(text, maxLines = 40) {
  if (text.length < 1500) return text
  let value
  try {
    value = JSON.parse(text)
  } catch {
    return text
  }
  const lines = []
  const walk = (node, path, depth) => {
    if (lines.length >= maxLines) return
    if (Array.isArray(node)) {
      lines.push(`${path}: array(${node.length})`)
      if (node.length > 0 && depth < 2) walk(node[0], `${path}[0]`, depth + 1)
      return
    }
    if (node !== null && typeof node === 'object') {
      const keys = Object.keys(node)
      lines.push(`${path}: object(${keys.length} keys)`)
      if (depth < 2) for (const key of keys.slice(0, 12)) walk(node[key], `${path}.${key}`, depth + 1)
      return
    }
    lines.push(`${path}: ${node === null ? 'null' : typeof node}`)
  }
  walk(value, '$', 0)
  if (lines.length === 0) return text
  return `[json outline, ${text.length} bytes]\n${lines.join('\n')}`
}

/** Replace a unified diff with per-file change counts and hunk headers. */
export function diffDigest(text) {
  if (!text.includes('diff --git')) return text
  const files = []
  let current
  for (const line of text.split('\n')) {
    const header = /^diff --git a\/(\S+) b\/(\S+)/.exec(line)
    if (header !== null) {
      current = { path: header[2], added: 0, removed: 0, hunks: 0 }
      files.push(current)
      continue
    }
    if (current === undefined) continue
    if (line.startsWith('@@')) current.hunks += 1
    else if (line.startsWith('+') && !line.startsWith('+++')) current.added += 1
    else if (line.startsWith('-') && !line.startsWith('---')) current.removed += 1
  }
  if (files.length === 0) return text
  const body = files
    .map((file) => `${file.path} +${file.added} -${file.removed} (${file.hunks} hunks)`)
    .join('\n')
  return `[diff digest, ${text.length} bytes]\n${body}`
}

/**
 * Apply enabled rules to a copy of the region messages.
 *
 * @param {ReadonlyArray<object>} messages region messages.
 * @param {ReadonlyArray<string>} rules enabled rule ids.
 * @returns {{ messages: object[], actions: Array<{ rule: string, before: number, after: number }> }}
 */
export function applyDenoise(messages, rules) {
  const enabled = new Set(rules)
  if (enabled.size === 0) return { messages: [...messages], actions: [] }

  const callMeta = new Map()
  for (const message of messages) {
    if (message.role !== 'assistant') continue
    for (const block of message.content) {
      if (block.type !== 'tool-call') continue
      let args
      try {
        args = JSON.parse(block.arguments)
      } catch {
        args = undefined
      }
      callMeta.set(block.id, {
        name: block.name,
        path: typeof args?.path === 'string' ? args.path : args?.file_path,
      })
    }
  }

  const lastRead = new Map()
  for (const message of messages) {
    if (message.role !== 'tool') continue
    const meta = callMeta.get(message.toolCallId)
    if (meta?.name === 'read' && typeof meta.path === 'string') lastRead.set(meta.path, message.toolCallId)
  }

  const seen = new Set()
  const actions = []
  const output = messages.map((message) => {
    if (message.role !== 'tool' || message.isError === true) return message
    const text = textOf(message)
    if (text.length === 0) return message
    const meta = callMeta.get(message.toolCallId)

    if (enabled.has('dedupe_reads') && meta?.name === 'read' && lastRead.get(meta.path) !== message.toolCallId) {
      const replacement = `[superseded by a later read of ${meta.path}]`
      actions.push({ rule: 'dedupe_reads', before: text.length, after: replacement.length })
      return withText(message, replacement)
    }

    if (enabled.has('dedupe_identical')) {
      const key = text
      if (seen.has(key)) {
        const replacement = '[identical to an earlier result]'
        actions.push({ rule: 'dedupe_identical', before: text.length, after: replacement.length })
        return withText(message, replacement)
      }
      seen.add(key)
    }

    let next = text
    if (enabled.has('strip_noise_lines')) next = stripNoiseLines(next)
    if (enabled.has('collapse_stack')) next = collapseStack(next)
    if (enabled.has('diff_digest')) next = diffDigest(next)
    if (enabled.has('outline_json')) next = outlineJson(next)
    if (enabled.has('truncate_head_tail')) next = truncateHeadTail(next)

    if (next === text) return message
    actions.push({ rule: 'combined', before: text.length, after: next.length })
    return withText(message, next)
  })

  return { messages: output, actions }
}

/** Per-session runtime state for cross-call rules. */
export function createDenoiseState() {
  return { reads: new Map(), seen: new Set(), failures: new Map() }
}

/**
 * Drop cross-call memory at a compaction boundary.
 *
 * A duplicate is only cheap to drop while its original is still in the request
 * the model sees. After compaction that original is gone, so a pointer turns
 * one repeat read into two (the pointer plus the spill fetch). Clearing the
 * state makes the first post-compaction read return real bytes again.
 */
export function resetDenoiseState(state) {
  if (state === undefined || state === null) return
  state.reads.clear()
  state.seen.clear()
  state.failures.clear()
}

const hashOf = (text) => createHash('sha1').update(text).digest('hex')

/**
 * Runtime denoise for one tool result, applied before the result enters the
 * request history. Cross-call rules use the session state.
 *
 * `read` results keep their exact bytes unless an identical repeat is detected;
 * rewriting source text would defeat the tool's purpose.
 *
 * @param {string} text joined text content of the result.
 * @param {{ toolName: string, callId: string, args: unknown, state: object }} context
 * @returns {{ text: string, rules: string[] } | null} replacement, or null to keep the original.
 */
export function runtimeDenoise(text, context) {
  const { toolName, callId, args, state } = context
  const hash = hashOf(text)
  const path =
    typeof args?.path === 'string'
      ? args.path
      : typeof args?.file_path === 'string'
        ? args.file_path
        : undefined

  if (toolName === 'read' && path !== undefined) {
    const previous = state.reads.get(path)
    state.reads.set(path, { callId, hash })
    if (previous !== undefined && previous.hash === hash) {
      return { text: `[read ${path} again; identical to call ${previous.callId}]`, rules: ['dedupe_reads'] }
    }
    return null
  }

  if (state.seen.has(hash)) return { text: '[identical to an earlier result]', rules: ['dedupe_identical'] }
  state.seen.add(hash)

  const shell = toolName === 'bash' || toolName === 'pwsh'
  if (shell) {
    const failure = failureFingerprint(text)
    if (failure !== undefined) {
      const previous = state.failures.get(failure.key)
      if (previous !== undefined) {
        previous.count += 1
        return {
          text: `[same failure as call ${previous.callId} (repeat ${previous.count}): ${failure.label}]`,
          rules: ['dedupe_failures'],
        }
      }
      state.failures.set(failure.key, { callId, count: 1 })
      if (state.failures.size > FAILURE_MEMORY) state.failures.delete(state.failures.keys().next().value)
    }
  }

  const rules = []
  let next = text
  const apply = (id, fn) => {
    const before = next
    next = fn(next)
    if (next !== before) rules.push(id)
  }
  const command = typeof args?.command === 'string'
    ? args.command
    : typeof args?.cmd === 'string' ? args.cmd : ''
  // Shell logs are capped well below XEYO's 4k trigger here, so a test/build
  // family gets its semantic pass earlier; the size budget below is the fallback.
  if (command !== '') apply('command_family', (value) => compactCommandOutput(command, value, shell ? 1000 : undefined))
  apply('strip_noise_lines', stripNoiseLines)
  apply('collapse_stack', (value) => collapseStack(value, 6))
  apply('diff_digest', diffDigest)
  apply('outline_json', outlineJson)
  apply('truncate_head_tail', (value) => truncateHeadTail(value, shell ? 4000 : 800, shell ? 1500 : 300, true))

  return rules.length === 0 ? null : { text: next, rules }
}
