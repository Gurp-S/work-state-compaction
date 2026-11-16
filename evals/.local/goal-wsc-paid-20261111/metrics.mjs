import fs from 'node:fs'
import zlib from 'node:zlib'

const decode = (path) => {
  const buf = fs.readFileSync(path)
  const magic = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
  const starts = []
  for (let i = 0; i + 4 <= buf.length; i += 1) {
    if (buf[i] === magic[0] && buf[i + 1] === magic[1] && buf[i + 2] === magic[2] && buf[i + 3] === magic[3]) starts.push(i)
  }
  const chunks = []
  for (let i = 0; i < starts.length; i += 1) {
    try { chunks.push(zlib.zstdDecompressSync(buf.subarray(starts[i], starts[i + 1] ?? buf.length))) } catch {}
  }
  return Buffer.concat(chunks).toString('utf8').split('\n').filter(Boolean).map((line) => JSON.parse(line))
}

for (const path of process.argv.slice(2)) {
  const rows = decode(path)
  let input = 0
  let output = 0
  let calls = 0
  const compactions = []
  for (const row of rows) {
    const usage = row.data?.usage ?? row.usage
    if (usage) {
      input += Number(usage.inputTokens ?? usage.input_tokens ?? usage.prompt_tokens ?? 0) || 0
      output += Number(usage.outputTokens ?? usage.output_tokens ?? usage.completion_tokens ?? 0) || 0
      calls += 1
    }
    if (row.type === 'compaction/summary') {
      compactions.push({ shadowed: row.data.shadowedTokenCount, in: row.data.usage?.inputTokens, out: row.data.usage?.outputTokens })
    }
  }
  console.log(`${path}\ncalls=${calls} input=${input} output=${output} total=${input + output} compactions=${JSON.stringify(compactions)}\n`)
}
