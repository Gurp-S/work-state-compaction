import fs from 'node:fs'
import zlib from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const decode = (path) => {
  const buf = fs.readFileSync(path)
  const starts = []
  for (let i = 0; i + 4 <= buf.length; i += 1) {
    if (buf[i] === MAGIC[0] && buf[i + 1] === MAGIC[1] && buf[i + 2] === MAGIC[2] && buf[i + 3] === MAGIC[3]) starts.push(i)
  }
  const chunks = []
  for (let index = 0; index < starts.length; index += 1) {
    const end = index + 1 < starts.length ? starts[index + 1] : buf.length
    try { chunks.push(zlib.zstdDecompressSync(buf.subarray(starts[index], end))) } catch {}
  }
  return Buffer.concat(chunks).toString('utf8')
}

for (const path of process.argv.slice(2)) {
  const raw = decode(path)
  const rows = raw.split('\n').filter(Boolean).map((line) => JSON.parse(line))
  const types = {}
  for (const row of rows) types[row.type] = (types[row.type] ?? 0) + 1
  const compactions = rows.filter((row) => String(row.type).includes('compaction') || String(row.type).includes('summary'))
  let input = 0
  let output = 0
  let calls = 0
  for (const row of rows) {
    const usage = row.data?.usage ?? row.usage
    if (usage && typeof usage === 'object') {
      input += Number(usage.input_tokens ?? usage.prompt_tokens ?? 0) || 0
      output += Number(usage.output_tokens ?? usage.completion_tokens ?? 0) || 0
      calls += 1
    }
  }
  console.log(JSON.stringify({ path, rows: rows.length, types, calls, input, output,
    compactions: compactions.map((row) => ({ type: row.type, seq: row.seq, keys: Object.keys(row.data ?? {}) })) }, null, 2))
}
