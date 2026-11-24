export const TAX_RATE = 0.07

export function taxCents(cents, rate = TAX_RATE) {
  return Math.round(cents * rate)
}

export function lineTotal(line) {
  return line.unitPrice * line.quantity
}

export function lineTotals(order) {
  return order.lines.map((line) => ({ sku: line.sku, total: lineTotal(line) }))
}
