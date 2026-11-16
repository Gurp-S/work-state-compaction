import { isDeepStrictEqual } from 'node:util'
import { toolResultOf } from './projection.js'

/** Bind an excerpt only when the archive has one matching call and receipt. */
export function indexToolReceipts(original, observations) {
  const calls = new Map()
  const receipts = new Map()
  const record = (map, id, value) => map.set(id, map.has(id) ? null : value)
  for (const call of observations) record(calls, call.id, call)
  original.forEach(({ message }, index) => {
    const result = toolResultOf(message)
    if (result) record(receipts, result.callId, index)
  })
  const pairs = new Map()
  for (const [id, call] of calls) {
    if (!call || typeof id !== 'string' || !id) continue
    const receiptIndex = receipts.get(id)
    if (receiptIndex == null || call.completedAt !== receiptIndex) continue
    const receipt = original[receiptIndex]
    const callEvent = original[call.index]
    if (callEvent.seq < receipt.seq) pairs.set(id, { call, callEvent, receipt })
  }
  return pairs
}

export function toolReceiptLinks(messages, pairs) {
  const links = new Map()
  messages.forEach((message, index) => {
    const result = toolResultOf(message)
    const pair = pairs.get(result?.callId)
    if (!pair || result.isError !== toolResultOf(pair.receipt.message).isError ||
        !isDeepStrictEqual(message.content, pair.receipt.message.content)) return
    links.set(index, `call #${pair.callEvent.seq}, receipt #${pair.receipt.seq}`)
  })
  return links
}
