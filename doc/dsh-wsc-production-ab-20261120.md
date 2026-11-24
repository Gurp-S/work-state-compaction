# dsh-wsc 生产对话对比：WSC(nosig) vs dsh 原生压缩（2026-11-20）

- 目的：在 DSH 真实会话里比较「WSC nosig 引擎 + 60/80 触发 + minReclaimRatio 0.15」与「dsh 原生 compaction」的压缩次数、成本、压缩后连续性和测试完整性。
- 模型：`deepseek-flash`（new-api，reasoningEffort low）。
- 窗口：`contextWindow 32768 / maxTokens 8192`（可用 24576）。
- 有效触发（修复后确认）：WSC `capacityPercent 100 / warnRatio 0.6 / forceRatio 0.8 / retainRatio 0 / minReclaimRatio 0.15 / nosigMaxTokens 6144` → 警告 14746、强制 19661；原生 `thresholdRatio 0.6 / headroomTokens 0 / retainRatio 0.16` → 阈值 19660。
- 驱动：headless 逐轮调用，`--permission-mode workspace-write --approval-policy never`，同一游标续跑；25 轮脚本化仓库任务（10 个文件的 orders-report CLI），第 25 轮为「不读文件」的连续性探针。
- 数据目录：`.tmpfloor/prod-eval/out-a`（WSC 有效配置）、`out-a-base`（第一次运行，配置未生效）、`out-b`（原生）。

## 结果（有效配置）

| 指标 | WSC nosig | 原生 | 比值 |
| --- | --- | --- | --- |
| 压缩次数 | 9 | 8 | 1.13× |
| 单次回收 token | 9.1k–11.1k | 6.9k–8.1k | 1.4× |
| 检查点字符（中位数/范围） | 11.8k / 9.5–15.4k | 8.9k / 6.1–11.7k | 1.3× |
| Agent prompt（未命中/命中） | 225k / 1663k | 231k / 1232k | 0.97× / 1.35× |
| 压缩调用 token（入/出） | 117k / 46k | 86k / 21k | 1.36× / 2.15× |
| 总成本当量（未命中 1.0、命中 0.02、输出 4.0 元/百万） | ¥0.714 | ¥0.557 | 1.28× |
| 墙钟（25 轮） | 1247s | 848s | 1.47× |
| 最终测试 | 22 passed | 20 passed | — |
| 连续性探针 | 全对，0 次读文件 | 全对，0 次读文件 | 持平 |

探针问题：TAX_RATE、默认行数环境变量、`summary(rows)` 字段、最新两条 CHANGELOG、toCsv 负值规则。两臂都只凭检查点回答；WSC 的检查点带引用（如 `TOTAL $153.00`、`toCsv header = 'sku,amountCents'`），可核对。

两次运行的探针轮都被模型自己的 `compact_context` 占用（收到 60% 提示后主动请求压缩，该轮只返回 pending），补一轮才答出；说明「60% 提示 + 模型可随时压缩」会推迟当前任务一轮。

## 第一次运行为什么不能用（配置未生效）

第一次运行（`out-a-base`）得到 36 次压缩、成本 ¥1.090（原生 1.96×）。`compactions.jsonl` 新增的 `timing` 遥测显示实际 `capacity=17203`（70%）、`retainTokens=2752`（0.16）、在 85% 强制——全是代码默认值。

根因：桌面版 schemastery 的 `volatile()` 字段在运行时是 `{ get }` 活动单元（cell），`WscConfigService` 构造器把 cell 当普通值读，所有 profile 配置在运行时都落回默认。修复：构造时先解包 `{ get }`（`dsh-wsc/index.js`）；调试输出确认之后 profile 值原样到达引擎。此前所有 WSC 生产运行（包括桌面 live profile）都受此影响。

## 关于 minReclaimRatio

代码里强制压缩（`action: 'capacity'`，即到 80% 硬边界）**永远放行**，门槛只拦模型在低压力下主动请求的压缩；且「回收」按整个上下文减 retained tail 计算，不是实际被遮蔽的字节。所以 0.15 不是压缩频次的旋钮。频次主要由容量基线与 retain 决定：配置生效后单次回收从 ~4k 升到 ~10k，压缩次数从 36 降到 9。

## 本次发现并修复的引擎缺陷

- `session.events` 在当前 DSH 构建不存在（只有 `session.log`/`eventAt`），`#recordReady` 抛错导致每次压缩重试。修复：`sessionEvents()` 统一读取。
- volatile 配置单元未解包，profile 配置全部失效（见上）。
- 账本前缀浮点（`n4.0600000000000005`）与重复事实：回放取整、渲染去重。
- 抽取缺口透出具体原因；`nosigMaxTokens` 4096→6144。
- 压缩账本新增 `nosig` / `extraction` / `timing` 遥测。

## 结论与待定

- 在有效 60/80 配置下，WSC 与原生压缩次数基本持平（9 vs 8），连续性持平，成本高 28%、墙钟高 47%。
- 成本增量主要来自检查点更大（中位 11.8k vs 8.9k 字符）导致的缓存 prompt 增长，以及抽取输出（46k vs 21k）；9 次压缩中仍有 8 个抽取缺口（每轮 1–2 段失败），扩大输出上限或分段策略可再降。
- 60% 提示会让模型推迟当前任务一轮去压缩；若只作预警，可考虑降低提示频率或让 `compact_context` 回执携带压缩结果。
- 尚未覆盖：1M 窗口、真实仓库长会话、跨模型（GLM）。
