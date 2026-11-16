import { indexToolReceipts } from './continuity-links.js'
import { toolResultOf } from './projection.js'
import { runtimeObservations } from './verification.js'
import { receiptWriteOrder } from './receipt-write-order.js'

export function originalReceiptEvents(events, derive) {
  const originals = []
  const receipts = new Map()
  events.forEach((event, index) => {
    if (!['assistant/message', 'tool/result'].includes(event.type)) return
    const message = derive(event)
    if (!message) return
    if (event.type === 'tool/result') {
      const id = toolResultOf(message)?.callId
      const source = event.sourceEventSeqs?.[0]
      const prior = events[index - 1]
      const patch = event.surfaceOp
      const isPrune = typeof id === 'string' && receipts.get(source) === id &&
        event.sourceEventSeqs?.length === 1 && prior?.type === 'compaction/prune' &&
        prior.data?.shadowedSeqs?.length === 1 && prior.data.shadowedSeqs[0] === source &&
        patch?.op === 'replace' && patch.start === source && patch.end === source
      receipts.set(event.seq, id)
      if (isPrune) return
    }
    originals.push({ seq: event.seq, message })
  })
  return originals
}

function excerpt(text, matchOffset = null) {
  const limit = 2500
  const offset = matchOffset === null ? 0 : Math.max(0, matchOffset - 250)
  const end = Math.min(offset + limit, text.length)
  return { text: text.slice(offset, end), total_chars: text.length, truncated: offset > 0 || end < text.length,
    ...(matchOffset === null ? {} : { offset_chars: offset, end_chars: end, match_offset_chars: matchOffset }) }
}

/** One original invocation and its exact associated response, scoped to this session. */
export function readReceiptHistory(session, seq, { query, includeWriteOrder = false } = {}) {
  if (!Number.isSafeInteger(seq) || seq < 1) throw new Error('read_history: invalid receipt_seq')
  if (query !== undefined && (typeof query !== 'string' || !query.trim() || query.length > 200)) {
    throw new Error('read_history: invalid receipt_query')
  }
  const rows = originalReceiptEvents([...session.events], event => session.deriveEventMessage(event))
  const receipt = rows.find(row => row.seq === seq)
  const result = toolResultOf(receipt?.message)
  const observations = runtimeObservations(rows.map(row => row.message))
  const pairs = indexToolReceipts(rows, observations)
  const pair = pairs.get(result?.callId)
  if (!pair || pair.receipt !== receipt) throw new Error(`read_history: unbound tool receipt #${seq}`)
  const { call, callEvent } = pair
  const args = typeof call.arguments === 'string' ? call.arguments : JSON.stringify(call.arguments ?? {})
  const matchOffset = query === undefined ? null : result.text.indexOf(query)
  if (matchOffset === -1) throw new Error(`read_history: no literal match in receipt #${seq}`)
  const writeOrder = includeWriteOrder ? receiptWriteOrder(pairs, pair) : null
  return {
    text: JSON.stringify({
      call_seq: callEvent.seq, receipt_seq: seq, tool: call.name,
      arguments: excerpt(args), result: excerpt(result.text, matchOffset),
      tool_error: result.isError, process_status: call.status === 'passed' ? 'completed' : call.status,
      ...(writeOrder ? { write_order: writeOrder } : {}),
    }),
    matches: 1,
  }
}
