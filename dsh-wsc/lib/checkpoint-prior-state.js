import { carryCheckpointState, readCheckpointState, renderCheckpointState } from './checkpoint-state.js'

/** Remove only a complete duplicate from the allocated prior section. */
export function omitCarriedStateEcho(section, priorText, published) {
  if (!section || !published) return section
  const prior = readCheckpointState(priorText)
  if (!prior || renderCheckpointState(carryCheckpointState(prior)) !== renderCheckpointState(published)) return section
  const [heading, ...rows] = section.split('\n')
  const stateRows = renderCheckpointState(prior).split('\n')
  const starts = rows.flatMap((row, index) =>
    (row === `- ${stateRows[0]}` || row === `  ${stateRows[0]}`) &&
      stateRows.slice(1).every((line, offset) => rows[index + 1 + offset] === `  ${line}`)
      ? [index] : [])
  if (starts.length !== 1) return section
  const start = starts[0]
  const tail = rows.slice(start + stateRows.length)
  if (rows[start].startsWith('- ')) {
    while (tail[0] === '  ') tail.shift()
    if (tail[0]?.startsWith('  ')) tail[0] = `- ${tail[0].slice(2)}`
  }
  const retained = [...rows.slice(0, start), ...tail]
  return retained.length ? [heading, ...retained].join('\n') : undefined
}
