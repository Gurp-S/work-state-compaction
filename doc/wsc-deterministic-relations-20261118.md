# WSC 关系确定性实验记录（2026-11-18）

- 关联目标：[今日目标达成表](goals-20261118.md)、[次日目标达成表](goals-20261119.md)
- 模型：deepseek-flash（OpenAI 兼容端点）
- 臂：`wsc`、`wsc_lean`；场景：`long-hidden`、`assistant-next`、`reversed-late`（各 6 轮）
- 运行：`benchmarks/coding_compaction_v1/runs/resume-20261118-230043`
- 判定：机械动作 oracle 为主，成本按 cached 0.02 / uncached 1.00 / output 4.00 元每百万 token 计

## 一、发现了什么

1. **WSC 的瓶颈是关系，不是压缩率，也不是事实条目。** 旧 checkpoint 里 State 占 23–25%，同一关系被写成多句：无检查同时进 open 和 unknown，next 同时出现在 next 和 open，检查又在独立 Checks 段重算一遍。
2. **提示词要求模型写引擎能推导的内容。** `DISTILL`/`REVISE`/`LEAN` 都要求“没有检查就记录缺口”，而引擎本来就能从收据算出缺口。
3. **同一套状态规则有两份实现。** `thin_state` 与 `engine_state` 各写一遍缺口规则，措辞不同；改规则要改两处。
4. **需求在 checkpoint 里存三份并被截断。** 逐字引用一份、账本一份、State 一份；State 那份按 100 字符截断。
5. **索引里的助手旧说法与当前要求并列。** `reversed-late` 的 `[E10] m4 note Export is synchronous now.` 仍在索引中，只增加了消息位置，没有机械的“已过时”判定。
6. **编辑是否成功没有被检查。** 旧实现把所有 edit 调用都当作已应用，工具返回错误也会进入收据和状态。

## 二、能如何优化

已实施（引擎内、零模型调用）：

- 需求锚点只来自需求自身（字面量、引号值、赋值式 `name to value`），不再借用无关事实词；
- 用户提出的需求在 State 中只写位置引用 `req#N`，逐字原文只保留在 Control；
- 每条需求只产生一个状态，synthetic/stale 缺口只写一次；删除独立 Checks 段，检查编号与结果并入状态行；
- next 只出现在 `next`，不再复制进 open；
- 编辑调用带错误结果时不进入 applied，状态按“未找到编辑”处理；
- 提示词删除“记录缺口”的 A 类要求，缺口由引擎生成；
- 索引助手 note 标注消息位置 `m<序号>`，不做语义层面的新旧判断；
- `resume.py` 增加归因字段：必需值在 checkpoint 内（model）、只能通过索引取回（recovery）、两者都没有（wsc）。

未实施（记录在案，留待讨论）：

- thin 臂迁移到同一条 coverage 投影；
- 索引旧说法的确定性删除；
- 产品适配器 `factual_codex.py` 的 JSON dump 与重复路径；
- denoise 正文中的哈希/字节数标记。

## 三、证据

| 事项 | 证据 |
| --- | --- |
| State 占比与重复 | 旧 `assistant-next`：WSC 1848B 中 State 419B、Checks 117B；lean 1989B 中 State 452B |
| 双实现 | [thin_state](../../benchmarks/coding_compaction_v1/live.py#L1104) 与 [engine_state](../../benchmarks/coding_compaction_v1/live.py#L1236) |
| 旧提示词 | [live.py:106](../../benchmarks/coding_compaction_v1/live.py#L106)、[live.py:123](../../benchmarks/coding_compaction_v1/live.py#L123)、[live.py:143](../../benchmarks/coding_compaction_v1/live.py#L143) |
| 锚点修正 | [requirement_terms](../../benchmarks/coding_compaction_v1/live.py#L1158) |
| 编辑成功门 | [receipts_from_events](../../benchmarks/coding_compaction_v1/live.py#L847) |
| 收据去重 | [passage.py:38](../../src/wsc/passage.py#L38) |
| 归因字段 | [resume.py:96](../../benchmarks/coding_compaction_v1/resume.py#L96) |
| 离线验收 | `python benchmarks/coding_compaction_v1/acceptance.py`、`stopline.py`、`resume.py --self-check` |

## 四、具体收益

| 项 | 预测 | 实测 |
| --- | --- | --- |
| 单例总字节 | −15%~−20% | lean −26.2%，WSC −2.2% |
| State 字节 | −30%~−40% | lean long-hidden 452→184；reversed-late 190（含 req#3） |
| Checks 段 | 0（并入状态） | 0 |
| 多余动作 | 不增加 | WSC 2→1，lean 3→2 |
| 每成功任务成本 | 不高于旧版 | WSC ¥0.1692→¥0.1405，lean ¥0.1339→¥0.1054 |

WSC 总字节只降 2%：它的账本本身 1016B（long-hidden），是模型输出，不是引擎渲染。这说明下一步的空间在账本体积，不在 checkpoint 结构。

## 五、实验中遇到的问题

1. **索引去消息导致发现率崩塌。** 试过把消息行全部排除出索引，三例 discover 掉到 0.33/0.20/0.40（第二轮 0），因为部分 needle 只存在于助手消息。回退为保留消息，仅增加位置标注。
2. **通用词作锚点造成误匹配。** 曾把需求里的普通小写词全部当锚点，`export` 让旧编辑被当成“已匹配”，`reversed-late` 落入 unknown。改为只取赋值式标识符与值。
3. **运行后才发现 next 重复。** `assistant-next` 的 State 同时有 Pending 文本和 next；已改为 next 唯一，离线验收通过，但未在模型端复测。
4. **账本需求截断。** WSC long-hidden 的 State 出现省略号；已把账本需求的 brief 放宽到 160 字符，同样只过了离线验收。
5. **归因是字面量判定。** `reversed-late` 的 lean 被判为 `recovery`（文件在状态内，`async def export` 需从索引取回），本轮没有失败样例可校准。
6. **成本口径。** 单轮推理量波动大，每成功成本只作方向参考；历史 native 对照 run 没有记录 cost。

## 六、实验后数据和收益

运行：`resume-20261118-230043`

| 场景 | 臂 | 成功 | 多余 | 违规 | 字节 | 成本 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| long-hidden | WSC | 1/1 | 1 | 0 | 1939 | 0.1200 |
| long-hidden | lean | 1/1 | 1 | 0 | 1059 | 0.1122 |
| assistant-next | WSC | 1/1 | 0 | 0 | 1608 | 0.1406 |
| assistant-next | lean | 1/1 | 0 | 0 | 1416 | 0.1099 |
| reversed-late | WSC | 1/1 | 0 | 0 | 1180 | 0.1609 |
| reversed-late | lean | 1/1 | 1 | 0 | 1103 | 0.0941 |

| 汇总 | WSC | lean | 上一轮 WSC | 上一轮 lean |
| --- | ---: | ---: | ---: | ---: |
| 成功 | 3/3 | 3/3 | 3/3 | 3/3 |
| 违规 | 0 | 0 | 0 | 0 |
| 多余 | 1 | 2 | 2 | 3 |
| 字节 | 4727 | 3578 | 4832 | 4847 |
| 总成本 | ¥0.4215 | ¥0.3162 | ¥0.5075 | ¥0.4017 |
| 每成功成本 | ¥0.1405 | ¥0.1054 | ¥0.1692 | ¥0.1339 |

归因：6/6 成功；模型侧多余动作 3 次（完成后自行跑测试），WSC 侧致错 0 次。

## 七、实验结果暴露的问题

1. 索引中的助手旧说法仍可能与当前要求并列；没有语义就无法机械判定过时，只能暴露位置。
2. WSC 的主要体积来源变成账本（long-hidden 1016B，占 52%），属于模型输出。
3. 模型写入账本的 requirement 仍与逐字引用重复；只有引擎合成的需求改成了 `req#N`。
4. 无锚点需求还没有闭合状态词，靠“匹配为空”间接表达。
5. thin 臂未迁移，两套状态实现并存。
6. 运行后的三处修正（next 去重、160 字符 brief、编辑失败门）只经过离线验收。
7. 状态行的来源只在内部保留，checkpoint 中没有逐行来源，审计仍要靠 run 目录回查。

## 八、与 12.md 的对照

| 12.md 目标 | 本轮位置 |
| --- | --- |
| 任务连续性（二） | 3 场景 6/6，无重复与错误阻止 |
| 关键区别保留（三） | 编辑载荷、覆盖、权威、需求位置进入状态；语义覆盖仍不可证明 |
| 缺口识别与补证（四） | 只有机械缺口；语义缺口仍是研究目标 |
| 执行与上下文一致（五） | 编辑成功门、版本绑定在状态层成立 |
| 证据访问（六） | 离线 discover/retrieve 1.00；旧说法问题仍在 |
| 压缩恢复可靠性（七） | 本轮未触 |
| 长期稳定（八） | 6 轮 × 3 场景，不足以外推 |
| 经济性（九） | 每成功成本 WSC −17%、lean −21%，单轮口径 |

## 反向链接

- [今日目标达成表](goals-20261118.md)
- [次日目标达成表](goals-20261119.md)
