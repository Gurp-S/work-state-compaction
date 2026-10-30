/** Experimental host boundary; not enabled in Codex or DSH by default. */
import { runtimeDenoise } from '../../dsh-wsc/lib/denoise.js'

export function runtimeDenoiseView(text, context) {
  // Classification comes from the executing tool contract, never shell-name guessing.
  if (context.resultClass !== 'log' || context.exitCode !== 0 || context.rawRecovery === true) return null
  // Existing stripNoiseLines treats the empty suffix of CRLF as the current line.
  // Normalize transport newlines before applying the existing rules; preserve raw externally.
  const normalized = text.replace(/\r\n/g, '\n')
  const view = runtimeDenoise(normalized, context)
  // Newline normalization alone is not an eligible compression action.
  return view
}
