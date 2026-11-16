/** All declared dependencies must resolve to retained literal source material. */
export function bindJudgmentSources(sources, selected, address = 'quotes') {
  if (!Array.isArray(sources) || sources.length === 0) return []
  const refs = []
  for (const source of sources) {
    if (typeof source !== 'string' || !source.trim()) return []
    const quote = source.trim()
    if (address === 'lines') {
      const match = /^m([1-9]\d*)$/.exec(quote)
      if (!match) return []
      const excerpts = selected.filter(item => item.index === Number(match[1]) - 1)
      if (excerpts.length === 0) return []
      refs.push(...excerpts.map(item => item.ref))
      continue
    }
    const exact = selected.filter(item => item.text === quote)
    // The builder deduplicates nested quotes. A unique enclosing excerpt still
    // carries the complete declared source; multiple matches remain ambiguous.
    const matches = exact.length ? exact : selected.filter(item => item.text.includes(quote))
    if (matches.length !== 1) return []
    refs.push(matches[0].ref)
  }
  return [...new Set(refs)]
}
