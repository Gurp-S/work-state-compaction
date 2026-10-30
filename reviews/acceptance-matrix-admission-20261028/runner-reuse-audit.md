# 共享运行器复用检查

2026-10-28，静态检查，不是运行准入凭据，没有额外模型调用。

- `experiments/native_application_budget.py::StudyBudget` 已有锁内预留、在途额度扣除、回执去重、未知用量冻结、逐臂/全局累计。复用此逻辑；模块本身明确不保证崩溃恢复，不把内存原子性冒充持久化原子性。仍需矩阵的逐运行绑定、恢复后不重复派发和实际运行计时接线。供应商未提供完整请求硬限额时，只能响应边界停止并保留在途超额。
- `benchmarks/deterministic_v1/native_blackbox_sessions.py::fresh/verify_material` 及 `experiments/native_study_fork_session.py::inject` 已有模型校验、密封导入比对和生命周期；`native_application_session.py::execute_stage` 已有压缩入口、事件收集、停止和用量回执。保留这些实现，矩阵只加协调层，不复制第二套原生传输/计费。
- 现有 fresh 使用 read-only。本地协议 `TurnStartParams.json` 的 readOnly 只有 type/networkAccess，没有可读根目录字段。只读不能证明模型无法读取私有 oracle 或其他实验臂。隔离仍须实际负向验证，不能把目录拆分或 runtimeWorkspaceRoots 当作已证明的读取隔离。
- `experiments/native_task_recovery.py` 已有普通续接恢复端口及生命周期/owner 检查；新矩阵尚未接线。其容量回调要求不能以恒真函数糊弄。用户已批准固定检查点的系统级黑盒口径，无需把未知的下一完整请求精确 Token 再升级成新的用户前置条件；应明确区分运行准入与未知容量，不声称已测得70%。

未改上述旧模块，没有声称这些旧检查自动覆盖新矩阵。下一步是协调层及其无模型负向准入；不是重新开发预算器、恢复工具或原生会话实现。
