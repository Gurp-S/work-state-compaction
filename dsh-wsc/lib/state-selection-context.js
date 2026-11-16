import { toolResultOf } from './projection.js'

const MAX_READS = 6

/** Read observations for exact filenames named in retained user controls. */
export function controlledReads(observations, pairs, controls) {
  const reads = new Map()
  for (const call of observations) {
    const pair = pairs.get(call.id)
    if (call.name !== 'read' || !pair || call.status !== 'passed') continue
    const path = call.args?.file_path ?? call.args?.path
    if (typeof path !== 'string' || !path) continue
    const name = path.split(/[\\/]/).at(-1)
    if (!name || !controls.some(text => text.includes(name))) continue
    const result = toolResultOf(pair.receipt.message)?.text ?? ''
    const scope = result.trimEnd().split('\n').at(-2)?.trim() ?? ''
    const marker = /^(?:\((?:End of file|Showing lines)[^\r\n]{0,100}\))$/.test(scope) ? scope : ''
    const window = ['offset', 'limit'].filter(key => Number.isSafeInteger(call.args[key]))
      .map(key => `${key}=${call.args[key]}`).join(', ')
    reads.delete(path)
    reads.set(path, `read ${JSON.stringify(path)} (call #${pair.callEvent.seq}, receipt #${pair.receipt.seq}` +
      `${window ? `; ${window}` : ''})${marker ? ` ${marker}` : ''}`)
  }
  return [...reads.values()].slice(-MAX_READS)
}
