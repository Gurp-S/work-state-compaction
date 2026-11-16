/** One byte-based budget calculation for preflight and both builders. */
import { jsonBytes } from './bytes.js'
import { resolvePayloadPolicy } from './payload.js'

export function checkpointBudget(messages, options = {}) {
  const policy = resolvePayloadPolicy(options.payload)
  const sourceBytes = messages.reduce((sum, message) => sum + jsonBytes(message.content), 0)
  const ceiling = options.maxChars ?? policy.maxChars
  return { policy, sourceBytes,
    budget: Math.min(ceiling, Math.max(600, Math.floor(sourceBytes * policy.sourceFraction))) }
}
