/** The token budget WSC is allowed to fill before pressure applies. */
export function capacityWindow(usable, effectiveWindowTokens) {
  const base = Number.isInteger(usable) && usable > 0 ? usable : 0
  if (!Number.isInteger(effectiveWindowTokens) || effectiveWindowTokens <= 0) return base
  return Math.min(base, effectiveWindowTokens)
}
