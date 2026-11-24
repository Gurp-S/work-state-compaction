export function lineTotal(line) {
  return line.unitPrice * line.quantity
}

export function lineTotals(order) {
  return order.lines.map((line) => ({ sku: line.sku, total: lineTotal(line) }))
}
