# 精简选择器三配对续跑：部分结果与评测修正

2026-10-27。长期目标未完成，当前没有三次完整 B/C 结论。选择/恢复核心保持 v1.20；本轮只扩展已有封存状态的评测续跑与资源准入，原生 B 算法不改，无子代理或 LLM 裁判。

## 已完成与缺口

原 release-receipt-recovery 的三个重复均有两个已确认的原生压缩；公共事件流一致，129 条旧来源在 C 第二轮不直接提供原正文/span。三个未压缩基线都答对 2/2。上一轮精简版 C 的 R02 已完成 2/2，61634 新增 Token，保持复用，不重做。

本轮两次实际派发尝试与一次零模型拦截，均留原目录：

| 重复 | 未压缩基线（复用） | B 后测 | 精简 C 后测 |
| --- | --- | --- | --- |
| R01 | 2/2 | 两次工具查找后被旧 2 响应上限截断，无最终答案 | 未派发，受共享账目 unknown 冻结 |
| R02 | 2/2 | 两次工具查找后被旧 2 响应上限截断，无最终答案 | 2/2，复用上一轮 |
| R03 | 2/2 | 完整 1/2：历史 nonce 为 null，当前版本 65 正确 | 未派发，受共享账目 unknown 冻结 |

**不可把中断当成答案错误，也不可把 C 未派发当成 C 成功。** R03 B 与 R02 C 来自不同重复，不直接组成一对收益结论。不能计算完整配对均值、置信区间或宣称三配对完成。现有 R02 精简 C 的收益仍限于 [上一轮单次资格](D:/lea/XenYon%20code/wsc/reviews/2026-10-27-source-access-port.md)。

## 两个实际暴露的问题

第一次组 `wsc-minimal-recovery-group-20261027-v1`：B 的三个后测均 TLS handshake EOF，C 额度端点也无法连接。没有完整 response 用量回执，已知 0 Token / 0 响应，**实际用量未知**。研究账目冻结保留，不能写成免费。所有 owned 进程关闭。

结构性原因：新续跑执行器让 B 工作线程直接派发，C 线程各自检查额度，未共用协调器的服务准入。修正为单个协调器先做零模型额度检查，成功后才允许启动任何模型线程；独立 C-only 工具原检查保留。零模型复核一度成功，第二次组因此开始。

第二次组 `wsc-minimal-recovery-group-20261027-v2`：连接可用，但两个 B 在使用原生可用工具寻找历史依据时，达到原先 2 响应上限：R01 查全局记忆再列目录；R02 查工具目录再列文件。均未产生 final。限制在执行层结束运行，这不是压缩内容损失的直接证明。

根因是后测预算允许两次模型响应，不能容纳这两次真实工具请求后的第三次最终作答；当任一分支用量不完整，原共享 StudyBudget 正确冻结其余派发。保留此冻结规则，不将未知补零，也不绕过旧失败。

## 基于证据的修订

下一轮 **B 与 C 后测统一**为最多 4 响应、120000 Token、120 秒。C 选择仍最多 4 响应、200000 Token、240 秒；并未改变选择算法、增加摘要提示或提示答案。新 C 臂最多 320000 / 8 响应 / 360 秒，仅为选择+后测的预算总和；阶段仍受实际剩余额度约束。不是承诺用满预算，更不是无限重试。

选择 4 响应的依据是已观测到两次工具请求后尚缺最终作答；12 万覆盖约 2.1–2.4 万输入/响应下四次请求并留输出空间。与旧 2 响应的限制相比，预算变更必须单独标注。实际 provider 内部参数仍不可控，仍是系统级黑盒比较。

上一轮完成的 R02 C（1 次后测）与本轮完成的 R03 B（1 次后测）都未触碰旧预算，且测试问题/来源/工具/模型未变，因此在**较大但未约束它们的后测预算**下保留复用。它们是已知结果的历史单元，不能标为整组全部前瞻预登记。原 R01/R02 中断尝试及花费单列；下一轮从未被测题污染的原生 B2 主干建新答题分支，不删除旧子分支。

先并行补两个 C，再并行补缺失 B；若 C 未完成或账目 unknown，B 不派发。每组无自动重试；新策略/原失败都登记。后测限额相同不代表总资源相同，选择开销仍计入 C 完整链路。

第三目录 `wsc-minimal-recovery-group-20261027-v3` 在新协调器零模型检查时再次遇连接失败，**模型请求为 0**，因此没有启动上述修订预算的新试验。这里的零调用是主机未派发的证据，与 v1 已派发但用量未知不同。连接仍不稳定，暂不重复模型尝试。

## 代码与验证

- `blackbox_minimal_recovery_group.py`：冻结原来源/原生主干哈希；校验两次压缩回执；严格核对复用版本、同题与完整结果；共享资源账目；协调器零模型服务准入；C 完成后才派发缺失 B；原结果复用不重复记账。
- `qualify_source_tool.run_candidate`：抽出已有 C 资格链路供组执行器复用。非组入口仍仅允许原 R02 未派发来源；组入口必须与登记的路径/源哈希匹配。旧 C1/失败 usage 完整复制保留，不改变 WSC 语义选择或恢复实现。
- `test_minimal_recovery_gate.py`：失败检查和仅检查服务模式都不能启动工作线程，额度不被虚记为已调用，旧 unknown 保留。
- `audit_minimal_recovery_group_20261027.py`：离线核对所有原始 DB/来源/原生父线程未变，新增 response_id 不重复、回执之和等于账目、未完成对应 unknown，清理确认。

三个组目录独立审计均通过，验证的是**局部失败记录与不可变来源**，不是压缩质量通过。最终 8 个命名测试文件 **37 passed / 8 subtests**，非全项目回归。C 核心输入/运行配置仍与 R02 已测版相同；允许变化的是执行器编排和统一后测预算，未反向修改历史注册或结果。

## 成本与证据

第二组新增已知 116732 Token / 5 响应：R01 B 48619/2、R02 B 43437/2、R03 B 24676/1。前两者没有完整完成回执，额外用量仍未知。两个 C 新选择均未派发。第一组没有已知 response 回执，但存在未知；第三组主机派发 0。没有额外 LLM 评分或标准答案生成。

各目录包含 registration/result/phase-outcome/完整 events+rollout/清理/封套/group-audit。两个未派发准入目录 `wsc-minimal-recovery-group-admission-20261027-v1/v2` 各 0.016 秒，总计另扣 ceil1 秒。额度等待不计，已执行计时保留；维护耗时未完全仪表化仍未知。最新为 `wsc-minimal-recovery-group-20261027-v3/next-time-reconciled-envelope.json`：24691795 Token / 444 响应 / 12098 秒。未知仍在；保守扣留的 360000 预算不是 116732 实际已知用量，也不是未知费用的可证上界。

此前成功链路的压缩成本只复用而不重记：B1/B2 分别 R01=28132/21481，R02=27989/20892，R03=27813/20599；C1 分别 40077/43192/40292。最终完整链路比较必须加入这些成本，不能只比较后测。

## 下一步

连接稳定后先做一次零模型检查；通过再补 R01/R03 C 与 R01/R02 B，复用 R02 C、R03 B，保留全部中断/未知。命令如下，`<新目录>` 必须不存在；不要重跑 C1、B1/B2 或已完成后测。

```powershell
py -3.11 -B -X utf8 wsc/benchmarks/deterministic_v1/blackbox_minimal_recovery_group.py --source D:/agent-task-runs/wsc-two-boundary-recovery-20261027-v2 --reuse D:/agent-task-runs/wsc-source-tool-minimal-candidate-20261027-v1 --registration D:/agent-task-runs/wsc-source-tool-candidate-20261027-v1/reused-session-registration.json --admission D:/agent-task-runs/wsc-source-tool-admission-20261027-v1 --parent-envelope D:/agent-task-runs/wsc-minimal-recovery-group-20261027-v3/next-time-reconciled-envelope.json --prior-attempt D:/agent-task-runs/wsc-minimal-recovery-group-20261027-v2 --reuse-native D:/agent-task-runs/wsc-minimal-recovery-group-20261027-v2 --query-responses 4 --query-tokens 120000 --out <新目录> --execute
```

用 `--check-service` 替代 `--execute` 只检查连接，仍会生成新封套，后续须承接那个最新封套。不做高频轮询。完整三对后再给正确率、完整成本/恢复次数/耗时与局限；5/10/20/50 次压缩、其他案例和长期实际任务仍未完成，不将此两轮小案例等同于最终目标。
