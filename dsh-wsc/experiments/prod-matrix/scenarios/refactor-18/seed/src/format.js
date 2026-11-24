export function formatAmount(amount) {
  return `$${amount.toFixed(2)}`
}

export function centsToAmount(cents) {
  return cents / 100
}

export function formatCents(cents) {
  const amount = centsToAmount(cents)
  return `${amount < 0 ? '-' : ''}${formatAmount(Math.abs(amount))}`
}
