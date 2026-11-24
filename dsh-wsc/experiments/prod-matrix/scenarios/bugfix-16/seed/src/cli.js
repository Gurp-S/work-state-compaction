import { readFileSync } from 'node:fs'
import { buildJsonReport, renderReport, toCsv } from './report.js'

const args = process.argv.slice(2)
const options = {}
let file
let asJson = false
let asCsv = false

// Output format precedence: --csv wins over --json when both are passed.
for (let i = 0; i < args.length; i += 1) {
  if (args[i] === '--limit') {
    const value = args[i + 1]
    const limit = Number(value)
    if (value === undefined || !Number.isInteger(limit) || limit < 0) {
      console.error('--limit requires a non-negative integer')
      process.exit(1)
    }
    options.limit = limit
    i += 1
  } else if (args[i] === '--json') {
    asJson = true
  } else if (args[i] === '--csv') {
    asCsv = true
  } else if (file === undefined) {
    file = args[i]
  }
}

const order = JSON.parse(readFileSync(file ?? 'data/sample.json', 'utf8'))
if (asCsv) {
  console.log(toCsv(buildJsonReport(order, options).rows))
} else if (asJson) {
  console.log(JSON.stringify(buildJsonReport(order, options)))
} else {
  console.log(renderReport(order, options))
}
