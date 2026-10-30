# 普通任务恢复：最小旁路接入实现

2026-10-28。新增 `experiments/native_task_recovery.py`，仅复用已有来源读取/字面查找、普通 fresh 接收器工厂、execute_stage 回调及会话关闭机制。既有运行器不导入此模块；未启用候选，未启动真实原生进程、模型、任务续接、性能或 B/C 实验。本轮只有限定单元检查，没有新的 Token、耗时或正确率收益数据。

## 接通了什么

- `open_task_receiver` 接收已有 reader 和 fresh 风格的工厂（可由调用方绑定 registration/destination）。同一次创建同时注册 WSCSource 并建立固定接收线程的分派器；不额外创建选材器或另一个恢复模型。
- 显式 `selector_runtime=None` 保持普通任务配置，不关闭其 shell/skills/memory/apps。既有工具 schema 不变；描述仅追加历史来源前缀 cut 的中性事实，不注入目标答案、选择指令、长目录或哈希列表。
- 正常 execute_stage 使用同一 handler/reader，原 request、output schema、限额及对账回调原样传递；跨回合 reader/callback 总额度不重置。
- 固定线程及工作区；执行和回调前复用 session.closed/server/opened 检查，关闭后拒绝新请求，绑定失败关闭返回的 session。没有第二套发布/生命周期状态机。
- 同一 reader 的锁覆盖 handler 缓存和额度状态。不会额外预读任何来源，原 ACL、来源 seal 和返回范围校验仍在原组件内执行。

容量仍归实际宿主：execute_stage 没有提供容量检查回调时直接返回 `task_source_capacity_unverified`；回调未返回严格的 True 时返回 `task_source_capacity_not_admitted`，均不执行任务。检查后再次核对 session/owner，防止检查过程中对象变化被忽略。

**这只接出了宿主准入钩子，未实现原生完整请求的可靠计量或输出预留。** 单元检查中允许回调返回 True 仅为模拟宿主分派条件，不是容量证据。真实集成方必须检查实际请求；不能用窗口258400、字节比或恒真函数补齐准入。本候选没有进入实际评测或默认链路。

## 跨回合缓存的根因修复

原 SourceToolHandler 按 call_id 保存回执，但指纹包含 thread/turn。相同本地 call_id 出现在新回合时，原实现错误地报身份冲突，不能把现有单回合 handler 直接用于正常长期任务。

复用前先写三项单元反例，旧实现均因 `source_tool_call_identity_conflict` 未通过。缓存键改为 `(thread_id, turn_id, call_id)`；同回合同一请求重放保持原回执，不多读；新回合按新请求重新授权；改参数仍按原规则拒绝。

reader 额度和 seen 总数没有按回合重置；超过累计限额仍由原 BudgetResultSourceToolHandler 返回原有中性错误。trace 的真实 call_id、线程/回合以及工具输出不改写。此变更不影响原单回合选择器的有效回执结构，也不改变“同一请求重放不是新鲜权限观察”的既有语义。

## 检查结果与边界

|范围|结果|
|---|---|
|跨回合3项反例|修复前3项错误，修复后3项通过|
|新旁路宿主契约9项|全部通过；使用假 session/factory，真实来源 reader 和临时数据库|
|既有来源工具/超限4项|全部通过；包含原回执一致、非法参数/线程及重复冲突、超限后不读源|

共16项定向代码检查。新旁路覆盖注册＋分派、普通运行配置、容量未知/拒绝不执行、跨回合共享额度、关闭/owner变化拒绝、绑定失败清理及原 schema/限额传递。原生工具注册是否被实际服务器接受、真实任务是否按需恢复、当前容量和最终收益均未验证，不能套用旧6/6。

重复范围检测没有进入执行限制；模型仍可合法重读。新回合 ACL 检查并不撤回已交付上下文。关闭检查也不承诺撤销已经在执行的系统 I/O 或原子协调外部 ACL；会话控制仍由原宿主负责。

凭据 `reviews/task-recovery-port-implementation/` 保留旧源码与3项失败日志、后测与兼容日志、指纹和机器结果。不复制研究数据库或冷目录。

下一步仍是原生容量准入的实际证据边界；没有可靠完整请求计量/输出预留前，不启动该旁路的真实续接，不创建额外包装器或压缩格式。停止实验的用户约束保持有效。
