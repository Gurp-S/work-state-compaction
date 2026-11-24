# WSC 重复采样与契约消融实验记录（2026-11-19）

- 关联目标：[今日目标达成表](goals-20261119.md)、[明日目标讨论稿](goals-20261120.md)
- 模型：deepseek-flash、glm-5.3（同一 OpenAI 兼容端点）
- 臂：`dsh_native`、`wsc_nosig`（默认候选）、`wsc_gatex`（EXT2）、`wsc_nosig_v1`（恢复提示消融）
- 场景：`silent-decision`（短，6 轮）、`silent-decision-long`（20 轮，阈值 32k 字符，2 次压缩）
- 运行：`resume-20261119-192024`、`193055`、`192026`、`205651`（基线）；`220908`、`220917`（EXT2 原版）；`232238`（EXT2 修复版，DeepSeek）；`233322`（恢复提示消融）
- 判定：每格 5 个独立样本，独立 `Model` 实例与缓存；机械动作 oracle；成本按 cached 0.02 / uncached 1.00 / output 4.00 元每百万 token

## 一、发现了什么

1. **单次运行不能作为比较依据。** GLM native 短用例 5 次成本均值 ¥0.1384，标准差 ¥0.0616，区间 ¥0.0713–¥0.2538；区间宽度大于两臂均值差。此前的单次结论（如“gater 更贵”“GLM 是 3.4×”）都是采样噪声。
2. **成本主体是模型推理 token，不是检查点大小。** WSC 检查点 1.6–1.9KB，native 5.9–6.7KB，但 prompt 只占总成本 6–8%；压缩与恢复的 reasoning 决定了费用。
3. **压缩契约的形状直接决定推理量。** 单次压缩调用的推理 token：DeepSeek EXT 2.1k vs native 0.37k；GLM EXT 7.3k vs native 1.9k。输入只有 0.5–7.6k，输出推理却达 7k，与当年 gater→nosig 同属“契约措辞诱使模型多想”。
4. **EXT2 的失败是信息删除过度。** “不要抄精确值、路径或命令输出”被模型理解为连目标路径也省掉，检查点失去 `src/retry.py`，5 次里 4 次改错 `src/client.py`。补上“决策必须保留标识符和目标路径”后回到 4/5，但仍有 1/5 把账本写成空。
5. **恢复契约在无值段时讲值规则是无效指令。** 同一检查点、压缩调用复用缓存，v1 与 v2 都 5/5，v2 恢复成本高约 25%；该检查点没有 “Observed values” 段。
6. **格式重试是纯浪费。** GLM 50 次调用中 3 次返回无法解析的 JSON（压缩 2、恢复 1），压缩重试占 GLM 长用例总花费 3.3%。
7. **WSC 的质量优势出现在方差里。** 五次采样 WSC 20/20；native 19/20，唯一失败是模型侧——检查点已写明 `send_once`，该样本仍写 `client.send`。

## 二、能如何优化

已实施：

- `resume.py --repeat N`：每格 N 个独立样本，每样本独立缓存；汇总成功率、成本均值±标准差、区间与检查点大小（[aggregate](../benchmarks/coding_compaction_v1/resume.py#L483)）。
- 默认变体定为 `wsc_nosig`：阈值触发压缩 + EXT 契约 + 引擎值账本（[DEFAULT_ARMS](../benchmarks/coding_compaction_v1/resume.py#L52)）。
- EXT2 措辞修复：只省略工具结果值，决策保留标识符与目标路径（[EXT2](../benchmarks/coding_compaction_v1/live.py#L195)）；该方向随后被放弃。
- 恢复契约按检查点内容组合：仅出现 “Observed values” 段时加入两条值规则；缺值取回、批量取回、覆盖即直出、陈旧值禁用始终保留（[resume_contract](../src/wsc/resume_contract.py#L16)、[resume_prompt](../benchmarks/coding_compaction_v1/resume.py#L59)）。

未实施，记录在案：

- 解析失败时先用宽松修复再重发（消掉 GLM 3–6% 的重试成本，原始失败文本尚未持久化）；
- 短用例统一为阈值一次性压缩（评测口径修正，非产品优化）；
- EXT2 增加“有决策的区域至少记一条”的硬规则（收益不足以承担新的脆弱性）；
- 第二模型替换（kimi 429、Qwen 16 token 上限未解除）。

## 三、证据

| 事项 | 证据 |
| --- | --- |
| 重复采样与聚合 | `resume.py --repeat`、[aggregate](../benchmarks/coding_compaction_v1/resume.py#L483) |
| 基线四组 | [192024](../benchmarks/coding_compaction_v1/runs/resume-20261119-192024/summary.json)（DS 短）、[193055](../benchmarks/coding_compaction_v1/runs/resume-20261119-193055/summary.json)（DS 长）、[192026](../benchmarks/coding_compaction_v1/runs/resume-20261119-192026/summary.json)（GLM 短）、[205651](../benchmarks/coding_compaction_v1/runs/resume-20261119-205651/summary.json)（GLM 长） |
| native 唯一失败 | 192024 第 3 次：检查点含 `send_once`，输出编辑 `client.send`，归因 model |
| EXT2 原版失败 | [220908](../benchmarks/coding_compaction_v1/runs/resume-20261119-220908/summary.json)（DS 1/5）、[220917](../benchmarks/coding_compaction_v1/runs/resume-20261119-220917/summary.json)（GLM 1/5） |
| EXT2 修复版 | [232238](../benchmarks/coding_compaction_v1/runs/resume-20261119-232238/summary.json)（DS 4/5，1 次空账本） |
| 恢复提示消融 | [233322](../benchmarks/coding_compaction_v1/runs/resume-20261119-233322/summary.json)（检查点相同，v1/v2 均 5/5） |
| 条件化契约 | 单元测试 `test_value_rules_only_when_checkpoint_has_values`（[tests/test_coding_ledger.py:116](../tests/test_coding_ledger.py#L116)） |

## 四、具体收益

| 项 | 预测 | 实测 |
| --- | --- | --- |
| 单次结论噪声 | 需要重复采样 | GLM native 短用例区间宽 ¥0.18，大于两臂均值差 |
| 默认变体简化 | 去掉高信号提示 | nosig 在两模型都比 gater 便宜；质量不降 |
| EXT2 压缩输出 | −30%~−50% | DeepSeek −49%（¥0.0235→¥0.0119）；GLM 仅 −14% |
| EXT2 质量 | 不降 | 原版 1/5；修复版 4/5（仍有一次空账本）→ 放弃 |
| 恢复契约文本 | 有值段才讲值规则 | 无值段 6 条、有值段 8 条；离线全绿 |
| 恢复成本 | 无值段时不应更贵 | v2 比 v1 高 25%（¥0.0237 vs ¥0.0189）→ 条件化后二者一致 |

## 五、实验中遇到的问题

1. **用例名过滤错误。** 首次启动用了 `--case silent-decision` 但没有 `--long`，短用例在 `LONG_CASES` 中，直接 `no case matched`；未产生调用。
2. **GLM 超时与推理不受 max_tokens 约束。** 单次恢复推理可达 20–40k，600 秒超时下仍能完成；不能用 `max_tokens` 压成本。
3. **缓存必须按样本隔离。** 重复采样若共用 `Model` 缓存会把 5 次退化成同一个答案；现在每次重复一个独立实例。
4. **WSC 独有的压缩推理放大。** EXT 契约下 DeepSeek 一次压缩 0.5k 输入产出 4k 推理；GLM 短用例甚至 6.5k。这是后续真正可压的空间。
5. **GLM 修复版 EXT2 实验被主动停止。** 结论只来自 DeepSeek；停止是为了不把时间花在已决定放弃的方向上。
6. **短用例口径不真实。** 当前短用例逐轮蒸馏，生产上短会话不会触发压缩；其成本比较仅作方向参考。

## 六、实验后数据和收益

基线（每格 5 次，成本单位人民币）：

| 模型 | 用例 | native | wsc_nosig |
| --- | --- | --- | --- |
| deepseek-flash | silent-decision | 4/5，¥0.0429±0.0082 | 5/5，¥0.0725±0.0074 |
| deepseek-flash | silent-decision-long | 5/5，¥0.0281±0.0060 | 5/5，¥0.0407±0.0080 |
| glm-5.3 | silent-decision | 5/5，¥0.1384±0.0616 | 5/5，¥0.2105±0.0434 |
| glm-5.3 | silent-decision-long | 5/5，¥0.0727±0.0135 | 5/5，¥0.1404±0.0451 |

EXT2 与恢复提示消融：

| 实验 | 模型 | 臂 | 成功 | 压缩 | 恢复 |
| --- | --- | --- | ---: | ---: | ---: |
| EXT2 原版 | deepseek-flash | gatex | 1/5 | ¥0.0124 | ¥0.0415 |
| EXT2 原版 | glm-5.3 | gatex | 1/5 | ¥0.0375 | ¥0.1264 |
| EXT2 修复版 | deepseek-flash | gatex | 4/5 | ¥0.0119 | ¥0.0228 |
| 恢复消融 | deepseek-flash | v2 | 5/5 | （复用） | ¥0.0237±0.0051 |
| 恢复消融 | deepseek-flash | v1 | 5/5 | （复用） | ¥0.0189±0.0037 |

## 反向链接

- [今日目标达成表](goals-20261119.md) · [明日目标讨论稿](goals-20261120.md)
