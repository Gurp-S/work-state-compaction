# ledger-cli

Zero-dependency accounting CLI. Reads transactions from CSV, aggregates them,
prints a report.

    node bin/ledger.js transactions.csv
    node bin/ledger.js transactions.csv --json
    node bin/ledger.js transactions.csv --by-category
    node bin/ledger.js transactions.csv --dry-run

Amounts are integers in cents everywhere. `src/config.json` holds the runtime
settings (currency, retention window).


| 臂 | 场景 | 样本 | 总成本¥ 中位(区间) | 压缩次数 中位 | 测试 | 严格探针 |
|---|---|---|---|---|---|---|

## 裁定
