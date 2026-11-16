/** Bound a command to observed session order without inferring file coverage. */
export function receiptWriteOrder(pairs, command) {
  if (!command || !['bash', 'pwsh'].includes(command.call.name)) return null
  const writes = [...pairs.values()]
    .filter(pair => ['write', 'edit'].includes(pair.call.name) && pair.call.status === 'passed')
  const latestBefore = writes.reduce((latest, pair) => pair.receipt.seq < command.callEvent.seq
    ? Math.max(latest ?? 0, pair.receipt.seq) : latest, null)
  const overlaps = writes.filter(pair => pair.callEvent.seq < command.receipt.seq &&
    pair.receipt.seq > command.callEvent.seq).map(pair => pair.receipt.seq).sort((a, b) => a - b)
  return {
    call_seq: command.callEvent.seq,
    receipt_seq: command.receipt.seq,
    latest_prior_write_receipt_seq: latestBefore,
    overlapping_write_receipt_seqs: overlaps.slice(-8),
    overlapping_write_receipts_omitted: Math.max(0, overlaps.length - 8),
    file_coverage: 'unknown',
    tested_version: 'unknown',
  }
}
