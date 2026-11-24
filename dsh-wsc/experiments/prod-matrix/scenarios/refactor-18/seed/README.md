# orders-report

Small CLI that renders an order as a text report.

## Usage

```sh
node src/cli.js data/sample.json
```

## Options

### `--limit N`

Show at most `N` rows, overriding the `REPORT_LIMIT` environment variable (default `20`).

```sh
node src/cli.js data/sample.json --limit 5
```

### `--json`

Print the report as JSON instead of text. The output is an object with a `rows` array of `{sku, amountCents}` objects and a `summary` object of `{count, totalCents}`, e.g. `{"rows":[...],"summary":{"count":2,"totalCents":4066}}`.

```sh
node src/cli.js data/sample.json --json
```

### `--csv`

Print the report rows as CSV with the header `sku,amountCents`. Negative amounts are rejected with an error (`negative amounts are not allowed in CSV export: <sku>`). If both `--csv` and `--json` are given, `--csv` takes precedence.

```sh
node src/cli.js data/sample.json --csv
```

## Tests

```sh
npm test
```
