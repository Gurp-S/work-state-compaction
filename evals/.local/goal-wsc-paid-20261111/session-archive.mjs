import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { zstdDecompressSync } from 'node:zlib'

export function sessionArchive(path) {
  const bytes = readFileSync(path)
  const magic = Buffer.from('28b52ffd', 'hex')
  const frames = []
  for (let offset = bytes.indexOf(magic); offset !== -1; offset = bytes.indexOf(magic, offset + 4)) {
    frames.push(offset)
  }
  assert.equal(frames[0], 0)
  const decoder = new TextDecoder('utf-8', { fatal: true })
  const events = frames.flatMap((offset, index) => decoder
    .decode(zstdDecompressSync(bytes.subarray(offset, frames[index + 1])))
    .split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line)))
  const numbered = events.filter(event => event.seq !== undefined)
  assert.ok(numbered.length && numbered.every((event, index) =>
    Number.isSafeInteger(event.seq) && (index === 0 || event.seq > numbered[index - 1].seq)))
  return { events, sha256: createHash('sha256').update(bytes).digest('hex') }
}
