/**
 * The one unresolved failure a checkpoint should mention.
 *
 * A pin is actionable only when the failure is flagged by the runtime or its
 * first real line opens as an error, and the address belongs to the workspace.
 * Scanning whole result text for the word "error" pins a successful source read
 * (`throw new Error(...)`) and names a spill file as the location.
 */
import { toolResultOf } from './projection.js'
import {
  envelopePathOf, firstLine, isOutsideWorkspace, looksLikeError, unwrapToolResult,
} from './values.js'

const LOCATION = /((?:[A-Za-z]:)?[\\/][^\s:]+\.\w+:\d+|[\w./\\-]+\.\w+:\d+)/

const lineOf = (text) => firstLine(text).replace(/^\d+:\s*/, '')

/**
 * @param {ReadonlyArray<{ message: object }>} rows region rows, oldest first.
 * @returns {string} a `## Unresolved error` section, or ''.
 */
export function errorPinOf(rows) {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const result = toolResultOf(rows[index]?.message)
    if (result === undefined) continue
    const text = String(result.text ?? '').trim()
    if (text === '') continue
    if (!looksLikeError(text, result.isError === true)) continue

    const envelope = envelopePathOf(text)
    if (envelope !== '' && isOutsideWorkspace(envelope)) continue

    const unwrapped = unwrapToolResult(text)
    const line = lineOf(unwrapped)
    if (line === '' || line.startsWith('<')) continue
    if (isOutsideWorkspace(line)) continue

    const found = LOCATION.exec(unwrapped)?.[1] ?? ''
    const location = found === '' || isOutsideWorkspace(found) ? '' : found
    return `## Unresolved error\n- ${location === '' ? '' : `${location}: `}${line.slice(0, 160)}`
  }
  return ''
}
