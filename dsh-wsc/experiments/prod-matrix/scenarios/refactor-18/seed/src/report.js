import { lineTotals, taxCents } from './store.js'
import { formatCents } from './format.js'

const DEFAULT_REPORT_LIMIT = 20

function reportLimit(options) {
  if (options.limit !== undefined) return options.limit
  const raw = process.env.REPORT_LIMIT
  const parsed =
    raw === undefined || raw.trim() === '' ? DEFAULT_REPORT_LIMIT : Number(raw)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : DEFAULT_REPORT_LIMIT
}

function taxedRow(row) {
  const cents = Math.round(row.total * 100)
  return { sku: row.sku, amountCents: cents + taxCents(cents) }
}

function taxedRows(order, options) {
  return lineTotals(order)
    .slice(0, reportLimit(options))
    .map(taxedRow)
    .sort((a, b) => b.amountCents - a.amountCents)
}

export function buildReport(order, options = {}) {
  return taxedRows(order, options).map(
    ({ sku, amountCents }) => `${sku}  ${formatCents(amountCents)}`,
  )
}

export function buildJsonReport(order, options = {}) {
  const rows = taxedRows(order, options)
  return { rows, summary: summary(rows) }
}

export function toCsv(rows) {
  const lines = ['sku,amountCents']
  for (const { sku, amountCents } of rows) {
    if (amountCents < 0) {
      throw new Error(`negative amounts are not allowed in CSV export: ${sku}`)
    }
    lines.push(`${sku},${amountCents}`)
  }
  return lines.join('\n')
}

export function totalCents(rows) {
  return rows.reduce((sum, row) => sum + row.amountCents, 0)
}

export function summary(rows) {
  return { count: rows.length, totalCents: totalCents(rows) }
}

export function renderReport(order, options = {}) {
  const rows = taxedRows(order, options)
  if (rows.length === 0) return ''
  const lines = rows.map(
    ({ sku, amountCents }) => `${sku}  ${formatCents(amountCents)}`,
  )
  lines.push(`TOTAL ${formatCents(totalCents(rows))}`)
  return lines.join('\n')
}
