# WSC 输入优化：来源读取端口与精简选择器

2026-10-27。当前代理直接完成，无子代理。原生 B 未改。新能力均显式启用，长期目标仍未完成。

## 当前结果

已有可逆输入编码在先前两案例中保持质量，authority 的 C 平均调用 Token 从 219295 降到 100459（-54.2%），C/B 从 3.12 降到 1.43；版本关系组 C/B 仍为 1.445。详见 [前次报告](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-compact-selection-input.md)。这些是局部已测收益，不能证明任意任务正确率。

本轮继续处理第二次压缩后的旧信息恢复，以及选择器携带通用编码代理启动材料的问题。两个实际运行复用**同一个原 R02 的 C1、131 条来源及后续测题**，没有重做 C1 或 B 的两次原生压缩。新 selector 不继承原始业务历史，通过正常选材输入与 WSCSource 读取历史。最终答题器配置未修改。

| 可观测指标 | 来源工具版 | 精简选择器版 |
| --- | ---: | ---: |
| 选择器启动项规范 JSON 字节 | 94005 | 43807 |
| 第一次选择响应的输入 Token | 32630 | 18701 |
| 选择阶段输入 Token 总量 | 137180 | 38433 |
| 选择阶段输出 Token 总量 | 8182 | 2493 |
| 选择阶段总 Token / 响应 | 145362 / 4 | 40926 / 2 |
| 后测总 Token / 响应 | 29985 / 1 | 20708 / 1 |
| 新增合计 Token / 响应 | 175347 / 5 | 61634 / 3 |
| 模型实际 WSCSource 调用 | 4 | 1 |
| 后测确定性正确数 | 2/2 | 2/2 |
| 选择阶段秒数 | 71.703 | 25.312 |
| 后测阶段秒数 | 4.766 | 12.375 |
| 整个候选执行秒数 | 91.110 | 46.609 |

启动字节减少 53.4%，首次输入 Token 减少 42.7%，选择阶段总 Token 减少 71.8%，新增整体总 Token 减少 64.9%。整体减少包含工具调用次数、输出长度、选材结果和模型随机性的差异，**不是全部可以归因于静态输入裁减**。两版 cached-input 分别为选择 100864/18560，后测 0/18560；总 Token 不等于实际费用，货币成本未知。

这只是一个原历史上的两种 C 候选资格验证，每种一次。不是三次正式 B/C，不代表已比原生更便宜。复用原 C1 的 43192 Token 后，成功 C 链路分别为 218539 和 104826；这是含历史复用的链路口径，不能再次记为新增花费。B 后测尚缺，不能计算本案例的 C/B 成本比。

## 结构性原因与边界

根因有两部分：旧正文折叠后，选择器只有冷入口却缺少一个明确、受限的来源读取端口，曾搜索无关目录；同时，专做选材的角色仍携带通用开发指令、全局记忆、技能目录与通用工具说明。

结构规则：来源发现只在当前封存快照内，模型决定查什么与保留什么；引擎只做精确字面查找、权限、身份、范围、哈希、预算与传输还原。选择器运行环境采用私有显式配置，和 B、最终业务执行器分开；不裁剪业务正文、必留控制信息或语义不确定项。

回归覆盖：精确读取与 Unicode 范围、权限/来源封印、跨快照绑定、回调身份与幂等、分页/预算未读游标、旧引用短别名可逆、False/0 等严格传输区分。8 个命名文件共 **35 passed / 6 subtests**；不是全项目回归。

## 实现

- `wsc/src/wsc/source_access.py`：可选 SnapshotSourceAccess。read 返回原 producer public text；find 只对模型给出的 literal 精确查找，按来源顺序分页，不按相关性排序，不替模型选择热内容。
- 读取绑定 session、cut、source_digest 与各来源行摘要；每次读取前后检查权限。最多 8 调用、累计 512 行校验、单返回 16384 字节、累计检查正文 2MiB。错误/权限拒绝/不完整扫描不等于内容不存在。快照构造仍遍历来源；这不是 O(1) 内存实现。
- `native_source_tool.py`：WSCSource 原生动态工具，严格 thread/turn/call/namespace 绑定，回调幂等，拒绝额外路径参数。`engine_binding` 在主机侧校验后移出模型输入。
- `native_selection_wire.py`：先前 `source_ids`、clue.sources、previous_excerpts.source_id 使用一致短别名；原 typed 值保存在绑定中，可精确还原。自由文字和 scope 不改写。
- `native_selector_runtime.py`：显式 `source_selector_minimal_v1`，仅用于 C selector 私有进程。替换通用开发指令为中性组件事实，关闭全局记忆注入、压低技能目录预算、关闭 apps 与 shell 功能；WSC 自身存储和来源工具不受全局记忆开关影响。

官方配置说明了 shell_tool、model_instructions_file、memories.use_memories、skills.max_context_tokens 与 apps 的作用；这些设置只传给本次私有进程，未修改用户全局配置。[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)

动态工具通过 experimental thread/start 注册，按 item/tool/call 返回结构化工具结果，本机固定二进制的 schema 与持久化 session_meta 均已核对。[App Server](https://learn.chatgpt.com/docs/app-server)

`skip_host_skill_discovery` 仅在本机 CLI feature 列表观测到，未在已查官方配置页找到；实验性质单列。零模型 v2 证明它单独并没有去掉全局记忆/技能目录，不能仅凭接受配置宣称生效。关闭 shell 后仍存在约 36KB 通用工具定义，因此还未达到全局最小输入。

## 原始证据与审计

原始公共历史：`D:/agent-task-runs/wsc-two-boundary-recovery-20261027-v2/dataset.public.json`。oracle 仅在生成完成后用于后测与程序评分，不进入选择器请求或动态工具注册。

- 来源端口零模型准入：`D:/agent-task-runs/wsc-source-tool-admission-20261027-v1`。
- 来源工具版：`D:/agent-task-runs/wsc-source-tool-candidate-20261027-v1`。
- 精简版零模型启动调查：`D:/agent-task-runs/wsc-selector-minimal-runtime-admission-20261027-v2`、`...-v3`。
- 精简版实际运行：`D:/agent-task-runs/wsc-source-tool-minimal-candidate-20261027-v1`。

两实际目录均有 registration、完整选择/查询 rollout、阶段回执、source-tool-trace、result、封存清理与预算封套。离线 `source-tool-audit.json` 将每个工具结果与 native 模型实际工具输出作严格 JSON 对比，并从独立数据库重新核对身份、原文范围与哈希；来源工具版 4/4、精简版 1/1 均一致。find(build-003) 返回原 s6 与后续请求 s131，不把新请求误当原回执。精简版主动查询一次后选择 s6、s130、s131，后测正确恢复历史 nonce 和当前版本 65。

物理磁盘读字节未知；端口指标是逻辑来源行/正文检查量，不能称物理 I/O。旧文本不是已认证业务事实，解释、当前适用性和理解的语义支持仍由模型负责。

来源工具版实际对应 v1.19。其后新增快照描述绑定、coverage、范围说明与精简运行环境；这些变动在 35 个定向测试与精简版实测验证，不能反向说旧付费运行已覆盖新代码。

两次候选新增合计 **236981 Token / 8 响应**，本地账目闭合、所有 owned 进程清理确认。历史失败和未知仍保留。三次零模型 3.094+2.766+2.453 秒合计向上扣 9 秒，最新封套位于精简实际目录 `next-admission-envelope.json`：25051795 Token、456 响应、12146 秒。保守扣留的未用分配不是真实花费，未计时维护仍未知。

## 复现与下一步

CLI：`py -3.11 -B -X utf8 wsc/benchmarks/deterministic_v1/qualify_source_tool.py --source D:/agent-task-runs/wsc-two-boundary-recovery-20261027-v2/R02 --registration D:/agent-task-runs/wsc-source-tool-candidate-20261027-v1/reused-session-registration.json --admission D:/agent-task-runs/wsc-source-tool-admission-20261027-v1 --parent-envelope <当前最新封套> --out <新输出目录> --selector-runtime source_selector_minimal_v1 --execute`。输出目录拒绝覆盖；不要无目的重复资格验证。

零模型审计：`py -3.11 -B -X utf8 wsc/validation/audit_source_tool_20261027.py --root <实际目录>`。审计输出也拒绝覆盖。

下一步按同一精简配置准备三次正式配对：复用已有 C1 与 B 两次压缩主干，补同题 B 后测，隔离答题分支；原始错误/未知用量保留，分别登记新策略，不通过删除旧 usage 绕过一次策略。原 R01 的真实失败、R02 未派发和 R03 已完成草稿必须分别处理，不能混合不同候选当作三次重复。以实际输入/总调用 Token、正确率、恢复次数和耗时判断是否推广；不盲增 cap，不恢复退休长程方式。
