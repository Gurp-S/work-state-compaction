# 过往实验

每个文件夹是一场实验，含 `README.md`（问题、臂、结果、裁定）、`logs/`（当次运行日志）、
`configs/<臂>.yml`（运行时的 wsc-config）和 `results.csv`（summary 行）。

| 实验 | 内容 | 结论 |
|---|---|---|
| [2026-11-17-mini-build-fixtures](2026-11-17-mini-build-fixtures/) | 早期 9 任务夹具与评分 | 历史材料，评分脚本缺依赖 |
| [2026-11-21-baseline-and-early-arms](2026-11-21-baseline-and-early-arms/) | wsc/cap/fix/sf/old/off vs native | 方向筛选，被长跑矩阵取代 |
| [2026-11-23-quotes-ledger-command](2026-11-23-quotes-ledger-command/) | quotes/ledger/cmd/ws/cards/dclean | ledger 晋升；其余不进主线 |
| [2026-11-23-denoise-v2](2026-11-23-denoise-v2/) | ledger 去噪 + R1–R3 | 成为 v3 基线 |
| [2026-11-24-v3-matrix](2026-11-24-v3-matrix/) | v3i/v3x/v3r/v3b/v4q | v3r 成为默认；v4q 负结果 |
| [2026-11-24-final-benchmark](2026-11-24-final-benchmark/) | 四臂各 8+4 次 | v3r > v2f > w80 > native |

旧臂的引擎代码版本也不同：这里的 `configs/` 只能复现旋钮，不能复现代码；需要精确复跑时请用对应日期的提交。
原始 run 数据（workspace、session 快照，约 116 MB）留在实验室目录，不入仓库；
本目录只保留可复核的记录、配置和日志。
