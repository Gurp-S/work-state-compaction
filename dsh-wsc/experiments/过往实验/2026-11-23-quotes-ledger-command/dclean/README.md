# 2026-11-23-quotes-ledger-command · dclean

> 实验场次：`2026-11-23-quotes-ledger-command`

## 机制

ledger + `ledgerDenoise: true`

## 配置

见同目录的 `config.yml`（运行时的 `wsc-config`）。

## 结果（本场样本，summary.csv 原样口径；裁定基于全部样本）

| 臂 | 场景 | 样本 | 总成本¥ 中位(区间) | 压缩次数 中位 | 测试 | 严格探针 |
|---|---|---|---|---|---|---|
| dclean | constraint-25 | 1 | 0.250 (0.250–0.250) | 4 | 19/19 | 4/4 |
| dclean | long-40 | 3 | 0.929 (0.714–1.720) | 23 | 141/141 | 15/18 |

## 裁定

去噪成立，成为 v2 配置
