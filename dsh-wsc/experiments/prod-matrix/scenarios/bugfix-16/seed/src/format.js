export function formatAmount(amount) {
  return `$${amount.toFixed(2)}`
}

export function centsToAmount(cents) {
  return cents / 100
}

export function formatCents(cents) {
  return formatAmount(centsToAmount(cents))
}
