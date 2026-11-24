import { readFileSync } from 'node:fs'
import { renderReport } from './report.js'

const file = process.argv[2] ?? 'data/sample.json'
const order = JSON.parse(readFileSync(file, 'utf8'))
console.log(renderReport(order))
