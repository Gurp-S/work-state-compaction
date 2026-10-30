# Linux 上下文阶段执行路径接入

2026-10-30。接续 v1.69，未启动模型或重跑旧 B/C。

## 根因与修复规则

结构性根因：原生阶段执行器将 thread.path 直接作为宿主 Path 读取。Windows 宿主不能将 Linux 客体的 /work/home/.codex/sessions/... 当成同一路径。上一轮证明了工作区映射与原生历史注入，没有证明旧阶段执行器已支持这一路径。

规则：原生元数据保留客体路径；宿主日志读取、产物归档、源码清单使用显式映射。模型、线程、工作区、服务对象或日志路径改变即拒绝。不能改写 opened 元数据来伪装同路径，也不能用空日志绕过计费核对。

新增 experiments/native_context_session.py 的 MappedContextSession 接入已打开的会话。NativeApplicationSession 只提取 workspace_path/rollout_path 两个默认保持原行为的钩子；新逻辑全部位于新模块。旧默认执行链没有采用 Linux 映射。

映射日志只接受 /work/home/.codex/sessions 下的 .jsonl，拒绝遍历、反斜杠、路径变化和链接；工作区只映射 actor-root/actor。宿主文件解析仍是受信协调器下的检查后读取，不宣称抗任意并发宿主路径替换。ContextWorkspace 的真实标记与挂载证明、ContextReceiver 的来源及容量准入仍须由调用方接入，不能由本类代替。

外部调用方明确拥有进程清理；本类不启动提供方或授予容量。清理失败保留可重试状态；成功后重复 close 不重复清理。构造失败时进程仍由调用方清理。注册、原生 opened 元数据、宿主映射分别留档。没有读取或复制用户凭据。

## 验证边界

同一确定性夹具中：未映射旧类在发送任何请求前 FileNotFoundError；映射类通过原阶段执行循环，产物日志与宿主原日志逐字节相等，阶段只记一次，没有用量回执时保持 usage_complete=false。这是模拟传输的代码路径验证，不是真实模型闭环。

本轮新路径用例 8 项：7 通过、1 因 Windows 符号链接权限不足跳过。另原清理分支 4 项与轮次记账 14 项通过。合计 25 通过、1 跳过，模型调用 0。证据：D:/agent-task-runs/wsc-context-stage-mapping-20261030-v1/checks.json；修改前源码另存。未重复上一轮 58 项，不合并声称全项目通过。

## 尚缺少的真实运行条件

本轮确认 docker-desktop WSL 初始 Stopped，短时启动只检查运行时清单，随后 terminate 成功。已有 nc 与 busybox；未找到 python3、python、node、socat、curl、gcc、cc。当前封闭网络策略依旧 --unshare-all，没有模型凭据。没有把失败连接解释成额度不足。

OpenAI 官方配置提供自定义 Responses 服务入口与重试配置，但文档不能证明本机闭集网络下已有可用通道：[配置示例](https://learn.chatgpt.com/docs/config-file/config-sample)。本轮没有修改用户全局配置、开放宿主网络或下载运行时。

下一步：独立接入仅允许登记提供方的通信通道和任务 Python 运行时，先证明原始请求/响应、私有材料隔离和清理。再按预算登记最小真实模型闭环，记录概览输入、模型实际查询、工具回包、完整调用用量和确定性任务结果。旧 B/C 不重跑；不得将脚本回调算模型主动恢复或将字节比例算 Token 收益。
