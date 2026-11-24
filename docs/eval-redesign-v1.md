# 三臂测试方案 v2（行为续作评测）

现有 `live.py` / `longhorizon.py` 的分数已经饱和：WSC 与 thin 在 probe、recall、约束保留上都是 1.00，
只有 native 在波动。**继续增加同样的样本只会缩小方差，不会增加区分度**，因为问题不在样本量，在测量对象。

## 为什么现有分数区分不出三臂

| 原因 | 证据 | 后果 |
| --- | --- | --- |
| 两臂共享 3/5 的输入段落 | Control、回执、索引逐字节相同（见 [thin-vs-wsc-composition.md](thin-vs-wsc-composition.md)） | 测出来的是共享引擎，不是两臂差异 |
| 探针是“存在性检索” | 答案原样在视图或索引里 | probe/recall 天花板 1.00，无法反映“会不会用” |
| 场景只有加性约束 | 每轮只新增约束，没有推翻、回退、冲突 | 更新语义（重写 vs 增量）从未被压到 |
| 单点工作区 | 每个用例只测一个预算/一次压缩 | 没有质量-字节曲线，无法判定代价 |
| 无配对、样本小 | 每臂每例一次，native 方差主导 | 差异落在噪声内，再跑也只是重复抽样 |
| 只看压缩后字节 | ratio 衡量表示大小 | 不衡量续作成本与错误 |

## 新方案的原则

1. **测“用”，不测“有”**：压缩后的状态交给一个新模型继续做任务，按动作是否正确评分。
2. **测“更新”，不测“累积”**：推翻、回退、失效、改名必须进入场景。
3. **机械 oracle**：评分只对照预定义动作与约束，不让模型自评，也不让生成压缩的模型参与评分。
4. **配对 + 区间**：同一实例上三臂配对，报告差值及 bootstrap 95% CI；预先定停止规则。
5. **成本归一**：每个“续作成功”消耗的压缩 token + 续作 token，而不是只看检查点字节。

## 任务族与 oracle

| 族 | 输入 | 模型要做的事 | 机械评分 |
| --- | --- | --- | --- |
| A 续作（Resume） | 三臂各自的 checkpoint + “继续” | 输出 JSON 动作列表（edit / shell / fetch） | 目标文件与改动标记命中、命令命中、禁止动作未出现 |
| B 修订（Revision） | 中途推翻/恢复一条约束或决策 | 按**最新**版本行动 | `current_version_used`、`old_version_absent` |
| C 失效验证（Stale check） | 检查之后又编辑了同一文件 | 重新检查，而不是引用旧通过 | `reverify_after_edit`、`stale_pass_claimed` |
| D 规模发现（Scale discovery） | 200+ 近似重复源，索引进视图 | 先取正确键，再回答 | 首次 fetch 命中、fetch 次数、取回后答案正确 |
| E 预算曲线（Budget sweep） | 2 / 4 / 8 / 16 KB 四个工作点 | 同 A | 动作正确率-字节曲线下面积，而非单点 ratio |

动作解析：续作模型只输出 JSON，动作由评测器在**模拟工作区**执行（不触碰真实仓库），
索引键由评测器按 action 返回源字节；这样可同时测“发现”和“使用”。

## 对照 `12.md` 目标矩阵

| `12.md` 目标 | v2 指标 | 场景要求 |
| --- | --- | --- |
| 任务连续性 | `action_success` | 续作必须依赖“下一步/未完成项”，且后续轮次不回述 |
| 信息保留质量 | `current_version_used`、`stale_use_rate` | 存在被推翻的约束、被合并的早期决策、版本化验证 |
| 缺口识别与补证 | `fetch_accuracy`、`over_recovery_rate` | 既要有“必须取”的缺口，也要有“无需取”的充足依据 |
| 执行与上下文一致性 | 动作对照 edit/check 身份 | 检查后编辑、跨文件编辑、失效回执 |
| 证据恢复 | Discover / Retrieve / Use 三段分开计分 | 200+ 近似重复源、干扰项、取回后动作 |
| 压缩恢复可靠性 | 现有 CI 契约测试 | 不并入语义分 |
| 长期稳定性 | `first_failure_round`、错误复活率 | 3–5 轮闭环：执行→压缩→续接→再执行 |
| 经济性 | `cost_per_success` | 记录失败成本，不只统计成功任务 |

`12.md` 明确反对把目标加权成一个不透明总分；v2 同样按指标分列，不合成单一分数。

## 消融臂：让差异可归因

只比三臂排名还不够。增加四个**测量用**消融（不改产品）：

| 消融 | 去掉什么 | 若指标不降说明什么 |
| --- | --- | --- |
| thin − state | 不渲染 Work state | 状态段对续作没有可测价值 |
| thin − repair | 不追加 `Exact source tokens` | 逐字校验对动作正确性没有影响 |
| thin − increment | 账本改为整篇重写（WSC 语义） | 增量账本的优势不存在 |
| thin − receipts | 不渲染机械回执 | 版本关系可由模型自行概括 |

消融必须在**依赖这些内容**的场景里跑；否则结论只能是“这些字节可以删”。
当前三例的 open/next 全空（见 [thin-vs-wsc-composition.md](thin-vs-wsc-composition.md)），
正是缺少依赖场景的例子。

## 闭环 Episode

单次续作只测能力，不测 `12.md` 的最终目标。Episode 模式：

1. 模型执行动作 → 评测器在模拟工作区应用并返回结果；
2. 到达轮次边界 → 三臂各自压缩 → 新上下文续接；
3. 重复 3–5 次，直到任务完成、预算耗尽或动作失败。

评分：任务完成、约束违反、错误复活（被撤销的结论再次被当作现行）、总 token、单位成功成本。
这是对“以值得的成本持续正确完成长期任务”最接近的可测代理。

## 能否出现“巨大差异”

方案的设计目标是**敏感**，不是保证效应量。差异大小取决于场景是否依赖各臂独有的内容：

- thin 对 WSC 的独有内容只有 state、增量账本、回填。只有场景要求“下一步未被复述”“早期决策被重写会丢”“命令需要逐字标识符”时，两者才会明显分开；简单召回场景仍会打平。
- native 缺少引擎回执与增量修订，在失效验证、修订、规模发现上预计差距更大。
- 如果消融后指标不降，正确结论是“这部分字节在这个场景不划算”，而不是继续调提示词。

因此“巨大差异”只能由**预先登记的硬场景**产生，并由配对 CI 判定；这也是新方案与旧方案的根本区别。

## 首轮实测（Phase 1，2026-11-18）

run `resume-20261118-150424`，四族场景，deepseek-flash：

| 场景 | native 成功/额外动作 | WSC 成功/额外动作 | thin 成功/额外动作 | 检查点字节 native/WSC/thin |
| --- | --- | --- | --- | --- |
| pending-check | 1/1 | 1/0 | 1/0 | 1993 / 813 / 995 |
| reversed-requirement | 1/1 | 1/1 | 1/1 | 2289 / 858 / 1214 |
| recorded-next-step | 1/1 | 1/0 | 1/0 | 1518 / 658 / 888 |
| hidden-value | 1/1 | 1/1（fetch 命中） | 1/1（无需 fetch） | 2270 / 576 / 1054 |

首个结论：

- **动作正确性在这个难度饱和**：三臂都 4/4。再重复同一组不会改变排序。
- **真正可测的差异**是代价与过度动作：native 每例多 1 个非必要动作；WSC 与 thin 各 2/4；
  检查点字节 WSC 最小、thin 居中（+150–370B，来自 state/增量账本）、native 最大（约 2–4 倍）。
- **发现路径不同**：hidden-value 中 WSC 通过 fetch 取回正确键；thin 的检查点直接包含了该历史值，
  无需取回；native 的摘要也保住了值。三种都通过，但只有 WSC 的路径是“索引→取回→使用”。
- 结构成本：改动前 WSC 每次压缩 2 次模型调用（distill + select）；当前实现为每次压缩 1 次，
  并新增了 `wsc_lean` 臂（r2+ 只发增量、合并 create/update 规则），见下节。

据此，在当前难度下的排序只能按“同质量下的总代价”给出（**改动前的结构；当前四臂结果见下节**）：

1. **thin**：动作质量与 WSC 相同，视图仅比 WSC 多 150–370B，但压缩调用数为 1/4；
2. **WSC**：视图最小，发现路径完整，但压缩调用与 token 最高，且有非必要取数；
3. **native**：动作质量相同，但检查点最大、每例都有额外动作，且前一轮实测出现旧验证残留。

要出现“巨大差异”，下一阶段必须提高难度（5+ 轮压缩、assistant-only 下一步、更多干扰源），
而不是重复当前四题。该结果已写入停止线的“噪声区冻结”：当前难度不再增加样本。


| 指标 | 定义 | 角色 |
| --- | --- | --- |
| `action_success` | 正确必需动作数 / 必需动作数 | **主终点** |
| `constraint_violation_rate` | 违反 must / must-not 的实例比例 | 次终点 |
| `stale_use_rate` | 引用或依赖已失效验证的实例比例 | 次终点 |
| `fetch_accuracy` | 首次取键正确率 × 取回后答案正确率 | 次终点（D 族） |
| `over_recovery_rate` | 依据已充分却仍额外读取/验证的实例比例 | 次终点，防“过度补证” |
| `use_accuracy` | 取回源后动作/结论正确率（Use 段） | 次终点（D 族） |
| `cost_per_success` | 元成本（缓存 0.02 / 未缓存 1.00 / 输出 4.00 元每百万 token，压缩 + 续作）/ 成功实例数 | 次终点 |
| `first_failure_round` | 长程中首次出现约束丢失/旧验证复用的轮次 | 次终点（长程） |

## 统计设计

- **单元** = 场景实例（用例 × 轮次 × 变体 × 重复）。三臂在同一实例上配对，消除场景难度差异。
- **重复**：每实例至少 2 次（温度 0 的端点仍有抖动）；报告配对差值，不报告未配对的均值。
- **区间**：bootstrap 95% CI；主终点差值 CI 不含 0 才判定“有区别”。
- **停止规则**：主终点 CI 半宽 < 0.05，或每臂累计 200 个实例运行；不按“感觉不够再跑一次”。
- **预注册**：主终点固定为 `action_success`；其余指标只作解释，不用于事后挑选结论。

## Phase 2：六轮压缩与困难场景

`resume.py --long` 使用 `resume_cases.LONG_CASES`，每个场景 6 轮压缩：

| 场景 | 难点 | oracle |
| --- | --- | --- |
| long-hidden | 精确 token 位于第 1 轮的工具输出，后面 5 轮噪音/无关编辑 | 用该 token 完成 `src/share.py`，且值必须有依据 |
| assistant-next | 下一步只出现在助手消息里，后续 5 轮从不复述 | 向 `docs/relnotes.md` 写入不可猜的 `REL-9482` |
| reversed-late | 第 3 轮才反转需求，之后 4 轮不再提 | 按最新 `async def export` 执行，禁止旧的同步版本 |

四臂链路与各自语义一致：native 链式摘要、WSC 每轮整篇重写账本（一次调用）、
`wsc_lean` 每轮只发增量 + 当前账本（一次调用，合并规则）、thin 增量修订 + state。
压缩调用受 429 退避保护；结果仍按 `success / extra / violations / grounded / bytes` 输出。

### Phase 2 实测（run `resume-20261118-161000`）

| 场景 | native 成功/额外动作 | WSC 成功/额外动作 | thin 成功/额外动作 | 字节 native/WSC/thin |
| --- | --- | --- | --- | --- |
| long-hidden | 1 / 2 | 1 / 1 | 1 / 2 | 4243 / 1872 / 1939 |
| assistant-next | 1 / 1 | 1 / 0 | 1 / 0 | 3969 / 1707 / 2139 |
| reversed-late | 1 / 1 | 1 / 1 | 1 / 1 | 4326 / 1551 / 1962 |

- 动作正确性仍然 9/9 全过：把下一步改成不可猜的 `REL-9482`、把需求反转推迟到第 3 轮、把精确值放到 6 轮之前，
  三臂的检查点仍然保住了足够信息。**长程难度没有制造动作层面的失败。**
- 差异落在总动作数（native 4、thin 3、WSC 2）和检查点字节（native 3.9–4.3KB、WSC 1.6–1.9KB、thin 1.9–2.1KB）。
- 排序：质量/economy（跨模型 judge）WSC > thin > native；总成本（thin 1 次压缩调用/轮，WSC 4 次）thin > WSC > native。
  因此“最好”取决于约束：质量优先选 WSC，成本优先选 thin，native 在两个口径下都落后。

### 四臂与“每次压缩一次调用”（run `20261118-174038`）

| 臂 | 每次压缩的模型工作 | r2+ 输入 | 规则 |
| --- | --- | --- | --- |
| native | 1 次摘要 | 先前摘要 + 新消息 | 内置 COMPACTION_INSTRUCTION |
| WSC | 1 次账本提炼 | 全量 transcript + 账本 | DISTILL / REVISE |
| WSC-lean | 1 次账本提炼 | 仅本轮新消息 + 账本 | 合并后的单一规则 |
| thin | 1 次槽位更新 | 仅本轮新消息 + 账本 + state | THIN_CREATE / THIN_UPDATE |

- 证据选择：WSC 两臂都由账本 `cites` 机械推导；独立的 `select` 调用、行范围解析与 `excerpt_evidence` 选段已从 harness 删除，核心 `Excerpt` 契约保留但不再被评测调用。
- 三例成本（prompt + completion）：native 29.8k、WSC-lean 56.9k、thin 71.5k、WSC 82.2k。
  改动前 WSC 为 136.6k，因此 WSC −40%，WSC-lean −58%；四臂调用次数现在都是 2 次（每压缩 1 次）。
- 三例检查点字节：WSC-lean 5.3KB、WSC 6.0KB、thin 6.8KB、native 11.5KB。
- 质量：四臂 recall 与 constraint 均保持；`checkpoint-index` 的 probe 0.75 由 WSC 与 WSC-lean 共有，
  缺的仍是旧缺口 `d2`（thin 本次 1.0，属采样波动）。
- 复合口径（调用次数 + 检查点字节）：WSC-lean > WSC > thin > native。纯 token 口径 native 最低，
  但检查点最大、额外动作最多，因此不改变复合排序。

### 四臂 6 轮续作（run `resume-20261118-175519`）

| 场景 | 成功/额外动作 native | WSC | WSC-lean | thin | 字节 native / WSC / lean / thin |
| --- | --- | --- | --- | --- | --- |
| long-hidden | 1 / 1 | 1 / 1 | 1 / 1（fetch 命中） | 1 / 2 | 3266 / 2211 / 1502 / 2407 |
| assistant-next | 1 / 0 | 1 / 1（fetch 未命中） | 1 / 0 | 1 / 0 | 4855 / 1930 / 1779 / 2038 |
| reversed-late | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 4004 / 1995 / 1634 / 2344 |

- 12/12 动作成功；额外动作合计 native 2、WSC-lean 2、WSC 3、thin 3。
- 字节合计：WSC-lean 4.9KB < WSC 6.1KB < thin 6.8KB < native 12.1KB。
- 压缩 token 合计：native 35.5k < WSC-lean 96.1k ≈ WSC 101.4k < thin 144.4k。
  增量输入把 lean 的 6 轮 prompt 压到 4.6–5.1k（WSC 8.2–9.5k），但 completion 波动较大，
  因此 token 总账只比 WSC 低约 5%，真正稳定的优势在字节。
- 质量风险（本次实测）：WSC 在 reversed-late 的账本同时保留了“保持同步”和“必须改为异步”两条需求，
  这是账本更新规则的模型侧失误；lean 的增量输入没有这个问题。该缺陷机械 oracle 不检查，只有 judge 指出。

### 更新规则修复与 lean 三次确认（2026-11-18）

在 `REVISE` / `LEAN` 中加入显式 Replacement check：用户消息以 `Change:`、`now`、`instead`、
`no longer`、`replace` 修改同一文件或主题时，必须在同一份输出中 supersede 旧需求；两条矛盾需求
同时 current 视为错误。`src/wsc` 未改动。

复跑（3 个 6 轮长场景；WSC 1 次、lean 3 次）：

| 运行 | 臂 | 成功 | 额外动作 | 字节合计 | 压缩 token（prompt + completion） |
| --- | --- | --- | --- | --- | --- |
| `191100` | WSC | 3/3 | 2 | 6.1KB | 27.7k + 98.4k |
| `191743` | WSC-lean | 3/3 | 2 | 4.4KB | 17.0k + 68.3k |
| `192228` | WSC-lean | 3/3 | 2 | 5.2KB | 15.5k + 79.1k |
| `192745` | WSC-lean | 3/3 | 2 | 4.8KB | 15.5k + 93.1k |

lean 三次均值：字节 4.8k ±0.4k，压缩 prompt 16.0k ±0.8k，completion 80.2k ±12.4k，
续作 token 14.8k ±2.1k；额外动作恒为 2，成功恒为 3/3。

- WSC 修复后 reversed-late 只保留 async 需求，旧的 sync 需求不再出现。
- lean 三次都没有“sync + async 并存”；其中两次账本不写需求条目，但 Control 逐字保留了最新
  `Change: ... async now`，因此不是矛盾，而是把需求交给控制块承载。
- 结论：矛盾缺陷已修复；lean 的 3 次确认稳定，可以作为下一阶段主线臂。仍需注意“账本不写需求”
  是把权威性交给 Control，评测时应同时检查 Control 与账本。

### 真实价格成本口径（2026-11-18）

`cost.py` 按用户给定的真实价格拆分每次调用：缓存输入 0.02 元/百万 token、未缓存输入
1.00 元/百万、输出 4.00 元/百万。成本只用 endpoint 返回的 `prompt_tokens`、
`prompt_tokens_details.cached_tokens` 和 `completion_tokens` 计算，不做估算。
`stats.py` 汇总多次同质运行时输出 `cost/case`（live）和 `cost/success`（resume）；
`cost/success` 是总成本除以成功实例数，失败成本留在分母之外的分子里，不隐去。

旧 summary 只保留了主调用的 prompt/completion 总和，没有保留 `cached_tokens`；只有检索探针的
usage 被写进了 result.json（0–384）。对照调用显示主调用的缓存命中很高（约 5k/5k prompt），
因此旧表的输入成本是上界，实际更低。输出价格是输入未缓存价的 4 倍，输出仍是成本主因。
新 run 已持久化缓存拆分，后续成本不再需要这个近似。

同质 live 12 次（每次 3 例；WSC 仍是“distill + select”两次调用的旧实现）：

| 臂 | 调用/例 | prompt | completion | 检查点 | cost/例 |
| --- | --- | --- | --- | --- | --- |
| native | 2 | 23.8k | 7.2k | 12.4KB | ¥0.0175 ±0.0009 |
| WSC（旧，2 调用/压缩） | 4 | 78.6k | 62.6k | 5.4KB | ¥0.1097 ±0.0080 |
| thin | 2.1 | 26.8k | 57.5k | 7.3KB | ¥0.0857 ±0.0122 |

四臂 live 单次 `174038`（WSC 已改为每次压缩一次调用）：
native ¥0.0162、lean ¥0.0517、thin ¥0.0696、WSC ¥0.0705（每例）。
WSC 相对旧实现下降约 36%。该 run 的 completion 比值 native : WSC 约为 1 : 6.9，
但这是**汇总口径**（包含 2 轮压缩、后轮账本增长、以及两臂输出预算不同），不能直接当作
单次压缩的推理比。

#### 推理量复核：native 不是零推理

同一份 round-1 会话、同样的输入，分别用 native 指令和 DISTILL 指令调用，记录
`finish_reason`、`completion_tokens_details.reasoning_tokens` 和可见输出字符数：

| 用例 | 臂 | max_tokens | finish | completion | reasoning | 可见输出 |
| --- | --- | --- | --- | --- | --- | --- |
| lease-identity | native | 8192 | stop | 1675 | 711 | 3779 字符 |
| lease-identity | ledger | 8192 | stop | 3213 | 2921 | 1115 字符 |
| checkpoint-index | native | 8192 | stop | 1279 | 449 | 3531 字符 |
| checkpoint-index | ledger | 8192 | stop | 4475 | 4195 | 1010 字符 |
| handoff-multi-round | native | 8192 | stop | 898 | 258 | 2663 字符 |
| handoff-multi-round | ledger | 8192 | stop | 5893 | 5643 | 889 字符 |

- native 的隐藏推理是 258–711 token，不是 0 或 100 以下；其 completion 中约 1k token 是
  可见的 Markdown 检查点，推理只占一小部分。
- ledger 的可见 JSON 只有约 250 token，但隐藏推理 2.9–5.6k，是 completion 的主体。
- 在相同 8192 预算下，单次压缩的总 completion 比值是 native : ledger ≈ 1 : 1.9–6.6，
  多数落在 2–3.5 倍；此前的“native 平均 317 推理/调用”没有逐调用数据支撑，撤回。
- 之前看到的 68/85/117 推理是**证据检索探针**的调用，不是压缩调用，不能混算。
- 预算不对称仍然存在：native 固定 8192，账本/瘦层固定 16384。对照调用中 ledger 从 8192
  升到 16384 后 reasoning 2921→3891、completion 3213→4146（约 +29%），native 则基本不变
  （711→632）。因此汇总成本把账本臂抬高了一截；公平做法是两臂统一到 16384（或统一到 8192
  并在 `finish=length` 时升级），当前 harness 尚未统一。

四臂 6 轮续作 `175519`（3 个场景，12/12 成功）：

| 臂 | 压缩 prompt/completion | 续作 token | 字节合计 | cost/成功任务 |
| --- | --- | --- | --- | --- |
| native | 21.3k / 14.2k | 12.9k | 12.1KB | ¥0.0327 |
| WSC | 26.8k / 74.6k | 10.4k | 6.1KB | ¥0.1167 |
| lean | 14.5k / 81.6k | 9.6k | 4.9KB | ¥0.1224 |
| thin | 22.2k / 122.2k | 14.6k | 6.8KB | ¥0.1848 |

修复后单跑：WSC `191100` ¥0.1513/成功任务；lean 三次 `191743/192228/192745`
¥0.1271 ±0.0153/成功任务（9/9 成功）。

- 结论一：在当前样本上，native 仍是每个成功任务最便宜的臂；按当前（未统一预算的）汇总，
  WSC 与 lean 多付约 3.5–3.9 倍。统一到 16384 后，native 的推理基本不变，因此这个倍数的
  合理区间约为 2.5–3.5 倍，而不是早期口径暗示的 4–8 倍。多付买到的是更小检查点
  （4.9–6.1KB vs 12.1KB）和更高的证据召回（live recall 1.00 vs 0.57），但续作成功率
  尚未拉开差距（3 例全部 12/12）。这符合 `12.md` 的警告：更短 Context 不等于更好，
  经济性必须以成功率为分母、以任务范围为前提。
- 结论二：成本主要不是压缩字节，而是输出 token。native 的输出主要是可见摘要，ledger 的输出
  主要是隐藏推理；账本把“写摘要”换成了“做语义记账”，所以推理更长。把账本从两次调用降到
  一次后，WSC 的单例成本从旧实现 ¥0.1097（12 次均值）降到 ¥0.0705（`174038`）。
  按输入价差估算，检查点每次续用节省约 7KB（≈1.8k token，约 ¥0.0018），而每次压缩多付
  约 ¥0.015，约 8–9 次续用可以摊回；不是“几十次”。这个估算依赖续用次数，尚未实测。
- 局限：`143135`–`161000` 的续作 run 未记录 usage，无法回溯精确成本；结论只来自
  `175519`（1 次 3 例）与 lean 三次确认。现在 summary 已持久化 `cost` 与缓存拆分，
  下一批 run 可直接累计 `cost/success`。另外，当前 native 与账本臂的输出预算仍不一致，
  在统一预算前，账本臂的成本数字应视为上界。

### WSC 极限审计（Kimi K3，2026-11-18）

方法：取三个 6 轮原始会话，把原始 transcript 与同一 case 的三个 checkpoint
（A = WSC `191100`，B = lean `192745`，C = native `175519`）匿名后交给 `kimi-k3`，
要求逐条找出“继续工作所需但缺失或含糊的关系”，并把损失归入
selection / state_projection / version_binding / verification_coverage /
evidence_discoverability / authority_marking / presentation。两轮独立调用
（`reversed-late`；`long-hidden` + `assistant-next`），原文与输出保存在
`runs/wsc-limit-kimi-20261118/`。

Kimi 的聚合结论：**state_projection 频次 7、最高 severity 3，是唯一贯穿全部场景和
WSC/lean 两臂的核心**；其次是 verification_coverage、authority_marking、
evidence_discoverability。native 在两个场景被判定会做对下一步，但 Kimi 也指出 native
把 assistant 自己提出的 REL-9482 放进 “Primary Request”，并把 “likely corrupted”
当成事实，所以 native 不是真值基准。

引擎侧证据：

- WSC/lean 的 resume 渲染把 state 直接传成 `None`（[resume.py:190](../../benchmarks/coding_compaction_v1/resume.py#L190)；
  live 的 WSC 也一样，[live.py:689](../../benchmarks/coding_compaction_v1/live.py#L689)）；只有 thin
  会传 state（[live.py:1183](../../benchmarks/coding_compaction_v1/live.py#L1183)，
  `thin_state` 在 [live.py:1065](../../benchmarks/coding_compaction_v1/live.py#L1065)）。
  渲染器本身支持 state（[passage.py:29](../../src/wsc/passage.py#L29)），只是 WSC 不给它。
- 账本 schema 只有 `kind/text/cites/invalid_when`（[live.py:101](../../benchmarks/coding_compaction_v1/live.py#L101)），
  没有 status、next、authority、covers。
- 提示词明确禁止“process narration / edit applied / file summary”（[live.py:105](../../benchmarks/coding_compaction_v1/live.py#L105)、
  [live.py:144](../../benchmarks/coding_compaction_v1/live.py#L144)），却没有提供
  “未实现 / 仍开放”的替代槽位；thin 才有 state 规则（[live.py:166](../../benchmarks/coding_compaction_v1/live.py#L166)）。
- `repair_identifiers` 只逐字回填标识符（[live.py:1344](../../benchmarks/coding_compaction_v1/live.py#L1344)），
  不校验模型句子是否被 cites 蕴含。

具体失败：

- `reversed-late` 原文 m17/m24/m31 都是 `round N change` 占位编辑，`async def export`
  从未落地；WSC/lean checkpoint 只写“要求 async”加“m31 后 tests PASS”，没有“未实现”；
  native 明确写 “async conversion has NOT been applied”。
- `long-hidden` lean 写 “checks m4 and m6 do not report SHARE-9”，但 m5（m4 的结果）
  就报告了 SHARE-9。引用可用、语义为假；实际运行靠 fetch 取回 SHARE-9，说明冷层能救，
  但 checkpoint 本身没有告诉 agent 该取哪个键。
- `assistant-next` WSC 把 REL-9482 标成 Requirement，但它来自 assistant 的 m4，不是用户；
  账本没有 authority 字段。该场景的 oracle 也把 assistant 的 next 当作必需动作，
  这是评测本身的权威性歧义，不只是 WSC 的问题。
- 三个臂都把 synthetic PASS 记为 Verification，没有“这个测试不覆盖该需求”的关系。

结论：WSC 的瓶颈不在压缩率，也不在事实保留——WSC 能保留 SHARE-9、路径和版本。
它缺的是**关系**：需求↔实现状态、检查↔覆盖范围、结论↔说话者权威、句子↔引用源的蕴含。
账本记的是结论，不是让结论可行动的关系；state_projection 只是这个缺口最明显的表现。
可修的是把 state、coverage、authority 变成引擎侧一等投影；不可修的是“从未观察到的
当前文件状态”，只能标 unknown 并强制重读。

#### 关系投影落地与结果（2026-11-18）

只改 benchmark 侧，`src/wsc` 未动；thin/native 行为不变。

- [live.py:808](../../benchmarks/coding_compaction_v1/live.py#L806) `event_edit`：从事件解析
  `old_string/new_string/content`，不再只留路径。
- [live.py:849](../../benchmarks/coding_compaction_v1/live.py#L847) `receipts_from_events`：
  receipt 增加 `edit_text` 与 `synthetic`；latest receipt 仍按文件/版本窗口计算。
- [live.py:1210](../../benchmarks/coding_compaction_v1/live.py#L1208) `engine_state`：
  - 对 active requirement，取该文件**最后一次 edit** 的 `new_string`，用精确标记
    （路径、`SHARE-9`、`REL-9482`、`FEATURE_X`、引号值、`async/await/synchronous`）判断是否仍匹配；
  - 最后一次匹配且其后有 check：`done`；不匹配：`open` 并引用实际写入内容；
  - 早先匹配但最后一次被覆盖：`unknown`，并写明两次 edit；
  - `Pending/Next` 上下文提升为 open 义务；显式 `next:` 提取并带来源角色；
  - receipt 无 check / synthetic / stale 进入 `unknown`；否定事实的正向匹配被排除（避免
    “wrote X, not Y”把失败当完成）。
- [live.py:1199](../../benchmarks/coding_compaction_v1/live.py#L1197) `recent_receipts`：
  WSC/lean 每个文件只渲染最后一条 receipt，用重复的编辑历史换状态字节。
- 接线：[resume.py:190](../../benchmarks/coding_compaction_v1/resume.py#L190)、
  [live.py:688](../../benchmarks/coding_compaction_v1/live.py#L688)、
  [live.py:709](../../benchmarks/coding_compaction_v1/live.py#L709)。

最终长场景 run `resume-20261118-215903`（3 场景 × WSC/lean）：

| 臂 | 成功 | 违规 | 额外动作 | 检查点合计 | 压缩调用 | 续作调用 | cost/成功任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WSC | 3/3 | 0 | 2 | 4.9KB | 18 | 6 | ¥0.1692 |
| lean | 3/3 | 0 | 3 | 4.9KB | 19 | 7 | ¥0.1339 |

对照修复前 `191100` / lean 三次：WSC 6.1KB、¥0.1513；lean 4.9KB、¥0.1373。
字节合计从 10.9KB 降到 9.7KB（−11%）；WSC 单例成本 +12%、lean −2.5%，在单次运行的
推理波动范围内。引擎状态本身不增加模型调用；lean 的 19 次压缩调用中有 1 次 JSON 重试。

| 场景 | 旧 WSC / lean | 新 WSC / lean |
| --- | --- | --- |
| long-hidden | 2016 / 1684B | 1630 / 1519B |
| assistant-next | 2606 / 1624B | 1856 / 1997B |
| reversed-late | 1519 / 1508B | 1370 / 1355B |

lean 的 assistant-next 单例 +23%，因为该次模型账本本身写了 5 条 Context/Verification；
其余 5 个 checkpoint 都变小。总字节仍下降。

live 单例 `handoff-multi-round` 也验证了接线：WSC/lean 的 probe 与 recall 均为 1.00，
WSC 1810B、lean 2039B，native 3520B。matched-bytes gate 仍为 false，原因是 WSC 内容
不足以填到 native 的字节数（旧的 `174038` 也有两例 false），不是状态投影错误。

Kimi K3 定向审计（同一原始会话 + 最终 A/B checkpoint）：
- 两个臂、三个场景的 `effective_requirements`、`work_status`、`edit_payload`、
  `check_coverage` 均为 **yes**；`assistant-next` 的 `authority` 为 yes。
- 剩余损失是账本文本问题：lean 把检查绑定到 “m1” 而非 m35（version_binding 2）、
  evidence index 仍保留 “Export is synchronous now” 旧注记（selection 1）、
  状态里的需求文本省略号（presentation 1）。这些不是 state 投影缺失。

模型问题与信息问题的区分：
- `resume-20261118-210505/212336/214055` 的 lean assistant-next 失败，检查点已经写明
  `open/next: append REL-9482` 和最后一次 edit 内容；模型却去 fetch E6、或额外编辑
  `src/flags.py`，导致漏做/违规。这是模型的动作选择与过度补证，不是 checkpoint 缺信息。
- 因此没有为这些失败增加 “do first / do not edit / 过滤无关 unknown” 之类的行为机制；
  最终只保留事实性的 state、edit 内容、覆盖、来源，以及 `Pending/Next` 义务。
  最终 run 6/6 成功；先前失败按模型侧问题记录，不混入 checkpoint 评分。

## LLM-as-judge（次级判定）

`judge.py --run <run>` 对同一批 checkpoint 与动作做匿名评分：

- 每个场景的响应随机映射为匿名字母（四臂 A–D，旧 run 自动按实际臂数 A–C），judge 不看臂名；
- 固定评分项：continuity、grounding、constraint、economy、overall（0–2），并给出排序；
- 输出 `judge.json`：每场景排序、每臂均分、胜场数；
- 默认使用同一端点模型（`WSC_JUDGE_MODEL` 可换），因此 `self_judge` 字段会记录该偏差；
- 机械 oracle 仍是主判定，judge 只用于解释“为什么”和发现 oracle 未覆盖的问题。

### 首轮 judge 结果（同一 run）

| judge 模型 | native 均分/胜场 | WSC 均分/胜场 | thin 均分/胜场 | 说明 |
| --- | --- | --- | --- | --- |
| kimi-k3（跨模型） | 1.33 / 0 | **2.00 / 2** | 1.67 / 1 | WSC 三轮全部前二，economy 满分 |
| deepseek-flash（自评） | 1.33 / 2 | 1.00 / 0 | 1.00 / 1 | 与机械的“native 额外动作最多”冲突 |

跨模型 judge 与机械的方向一致：WSC 的检查点最小、无多余动作；native 每例都有额外读/检索。
同模型自评把 native 排第一，说明 `self_judge` 偏差真实存在，**judge 必须换模型**，否则只能作参考。

### 四臂 run 的三次 judge（同一批 checkpoint）

同一 run `resume-20261118-175519` 在修正判定口径前后共判三次，排序不稳定：

| 判定口径 | native | WSC | WSC-lean | thin | 备注 |
| --- | --- | --- | --- | --- | --- |
| 初版 | 2.00 / 3 胜 | 1.67 / 0 | 1.67 / 0 | 2.00 / 0 | 把 fetch 路径判为未 grounded |
| + 逐字需求 + fetch 规则 | 2.00 / 3 胜 | 1.67 / 0 | 1.33 / 0 | 1.67 / 0 | lean 仍被判 grounding 0 |
| + 引擎取回记录 | 2.00 / 2 胜 | 1.67 / 0 | 1.67 / 0 | 2.00 / 1 胜 | lean 的 fetch 命中被正确承认 |

结论：

- 三次判定都没有把 WSC 排在首位，与上一轮三臂 run（WSC 2.00 / 2 胜）相反；同一模型、同一 rubric 下单次 judge
  的排序不可作为判决依据，**必须多次采样或换 judge 模型后再配对**。
- judge 确实发现了机械 oracle 不看的东西：本次 WSC 在 reversed-late 的账本同时保留新旧两条需求；
  lean 因增量输入未出现该矛盾。该发现应反馈到账本更新规则，而不是靠 judge 打分掩盖。
- `judge.py` 会把每臂的 `fetched / fetch_hit / grounded` 机械记录一并给 judge，避免把“索引→取回”误判为无依据。
- `judge.py --self-check` 验证 schema 与排序合法性，已加入 CI stop-line job。

## 落点（不动 `src/wsc`）

| 文件 | 内容 | 状态 |
| --- | --- | --- |
| `benchmarks/coding_compaction_v1/resume.py` | 四臂 checkpoint → 续作模型 → 动作 oracle 评分；记录压缩/续作 token；`--long` 支持六轮；`--self-check` 离线自检 | Phase 1 已实现，Phase 2 已加长程 |
| `benchmarks/coding_compaction_v1/resume_cases.py` | 四族短场景 + 三族长程场景 | 已实现 |
| `benchmarks/coding_compaction_v1/judge.py` | 匿名 LLM-as-judge，输出排序与均分 | 已实现 |
| `benchmarks/coding_compaction_v1/curve.py` | E 族预算扫描，输出质量-字节曲线 | Phase 3 |
| `benchmarks/coding_compaction_v1/stats.py` | 配对 bootstrap、CI、停止规则 | 待实现 |
| `.github/workflows/wsc.yml` | 离线 oracle/judge 自检 + 手动 live job | 已加入 |

Phase 1 的离线判别力已覆盖：完美动作 1.00、缺必需动作失败、禁止动作失败、额外动作计数、
`fetch → 取回 → 使用` 链路。真实模型的结果按 `success / required / extra / violations / fetch` 分臂输出。

旧的 `live.py` / `longhorizon.py` 语义指标（ratio、probe、漂移）已饱和，仅作诊断；
`live.py` 现在只以四臂的调用次数、token 与检查点字节参与成本口径。

## 判别力验收

新方案必须先证明自己能区分，才允许用于结论：

1. **上限**：完美 checkpoint（人工构造）在 oracle 上 `action_success = 1.00`。
2. **下限**：把 Work state 删掉的 checkpoint，`action_success` 必须显著下降；否则该族没有测到状态。
3. **失效**：把旧验证写成 current 的 checkpoint，`stale_use_rate` 必须显著上升。
4. **通过**：四臂配对差值的 CI 能稳定分开，且离线（fake model）可重复。

## 实施顺序

1. Phase 1：`resume.py` + A 族，复用现有 3 个用例；先离线跑 oracle 判别力，再接真实模型。
2. Phase 2：B 族（修订/回退）与 C 族（失效验证）。
3. Phase 3：D 族（规模发现）与 E 族（预算曲线）。
4. 每个 Phase 都先通过“判别力验收”，再进入下一阶段；不通过就修改场景，不修改 oracle 去迁就结果。

本方案只增加测量，不增加压缩机制；[optimization-stop-line.md](optimization-stop-line.md) 仍然有效。
