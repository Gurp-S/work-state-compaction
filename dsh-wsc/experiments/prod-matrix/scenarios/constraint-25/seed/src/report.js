import { lineTotals } from './store.js'
import { formatAmount } from './format.js'

export function buildReport(order) {
  const rows = lineTotals(order)
  return rows.map((row) => `${row.sku}  ${formatAmount(row.total)}`)
}

export function renderReport(order) {
  return buildReport(order).join('\n')
}
