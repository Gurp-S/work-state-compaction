# Changelog

All notable changes to this project are documented here.

## Unreleased

- Initial orders report CLI with text output.
- Add `formatCents` for `$0.00` formatting, including negative amounts as `-$3.50`.
- Add `TAX_RATE` and `taxCents`, with an optional rate parameter defaulting to `TAX_RATE`.
- Show each report row's line total in cents including tax, and sort rows by amount descending.
- Support `REPORT_LIMIT` (default 20) and a `--limit N` CLI override for the row count.
- Add a `--json` output mode returning `{sku, amountCents}` objects.
- Append a `TOTAL $x.xx` grand total line to text output via the `totalCents` helper.
- Add `toCsv` and a `--csv` output mode (takes precedence over `--json`) with header `sku,amountCents`.
- `--json` output now includes a `summary` key (`{count, totalCents}`) alongside `rows`.
- `toCsv` rejects rows with negative `amountCents`, naming the offending SKU in the error.
