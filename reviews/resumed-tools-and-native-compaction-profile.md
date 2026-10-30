# 恢复后工具与原生压缩协议准入

2026-10-30。只连接隔离环境内的本地固定响应服务，真实提供方调用 0。不修改原生二进制，不生成或模拟 Codex 的压缩摘要。

## 恢复后的工具已可观察、可分派

从上一轮已安装并重开的原生会话复制持久记录到新的隔离目录，原证据保持不变；thread/resume 没有重传 dynamicTools。

实际发送的请求中，WSCContext 声明仍存在。当前版本把代码模式工具放在 input 的 additional_tools 记录及 functions.exec 描述中，不能只检查顶层 tools。核对的是完整 WSCContext 声明字节，与此前真实模型成功回查时的声明相等。

本地固定响应随后产生 tools.WSCContext 的代码模式调用，原生实际发出对应动态回调。测试宿主仅回复“本地注册探针”数据，随后原生完成固定响应轮。这里证明注册保留与运行时分派，不是新增来源恢复或模型正确率证据。

内置 OpenAI 工具目录还包含 web 等其他声明，因此整套 exec 描述不必与自定义提供方完全相等。判定聚焦 WSCContext 自身声明及实际回调，不能因为额外工具存在就误报 WSC 丢失。

## 发现一个会污染后续对照的配置差异

三种配置都在 /v1/responses 路由发送压缩请求，仅看路径无法区分模式：

|实际原生配置|传输|压缩请求中的结构化触发项|
|---|---|---|
|原自定义提供方默认值|HTTP|没有 compaction_trigger；末项为普通 message|
|自定义提供方显式 remote_compaction=v2|HTTP|1 个 compaction_trigger|
|内置 OpenAI、本地占位 API key|WebSocket|1 个 compaction_trigger|

官方将 `remote_compaction` 的 `unsupported` 定义为本地压缩，`v2` 定义为经 Responses 发送压缩触发；配置需要明确记录，不能仅凭同版二进制就当作相同压缩机制。[OpenAI 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)

这是新宿主原先“只接普通 Responses”的配置风险，不改变旧 Windows 默认提供方 B′ 的历史地位；此前真实恢复准入未运行原生压缩，因此也不撤销其恢复链路证据。

内置配置实际采用 WebSocket，并有 generate=false 预热帧、previous_response_id 增量状态；本地探针用现有已安装 websockets 17.0.1 的纯 Python 文件处理，未改全局依赖。仅在本地固定服务使用无权限占位 API key，没有加载或复制真实凭据。该占位认证不证明用户 ChatGPT 认证条件下的全部配置等价。

## 新增显式旁路与准入

experiments/native_compaction_profile.py 定义 native_remote_v2_http_v1。宿主显式传 --compaction-v2 时才给 wsc_bridge 设置公开 v2 能力；原默认普通恢复链路不变。此配置是“原生远程 V2 算法 + 共同 HTTP 宿主”的候选系统比较条件，不冒称默认 WebSocket 传输性能完全相同。

ProviderGate 新增默认关闭的 require_compaction_v2。用于原生压缩阶段时，在真实派发前同时核对结构化 request_kind=compaction 及恰好一个 compaction_trigger。路径相同、普通消息中提及压缩、或只有 request_kind 都不构成准入；不匹配返回事实错误、保存请求、不调用真实提供方。

对本轮实际捕获的请求做离线核验：默认自定义请求被拒绝，显式 V2 HTTP 与内置 OpenAI WebSocket 请求均通过该构造检查。这里不读或解密任何 opaque 内容。

11 项针对性检查通过：新配置/准入 4，既有网关边界 7。原生源码、WSC 选材与发布核心没有更改；没有把本地协议错误改成付费重试。

## 验证范围与保留的失败

本地压缩阶段固定返回明确错误，没有制造 encrypted_content 或可被误当作原生摘要的文本。**本轮没有完成真实原生压缩，也没有 B/C 成本或质量结论。** 内置传输对本地错误出现重连帧，全部局限于本地服务及预登记帧上限，不是远端付费重试。

证据位于 D:/agent-task-runs/wsc-resumed-native-routes-20261030-v1 至 v8：

- v1 验证器误查顶层 tools，保留原失败。
- v2 复核 additional_tools 并收到原生动态回调，观察默认自定义压缩请求。
- v3 内置配置对 HTTP-only 探针发起 WebSocket，探针不支持，保留失败。
- v4 显式 V2 HTTP 生成原生 compaction_trigger。
- v5 只读配置未暴露内置解析后能力，结果不可据以认定默认值。
- v6 未处理 WebSocket 预热，v7 整体工具描述相等断言过宽，均为验证器问题，保留失败。
- v8 正确处理预热、实际回调及 WSC 声明，并捕获内置配置的 V2 触发请求。

源码 as-run、原始请求与固定响应、事件、配置及清理记录在对应目录保留。完整声明相等不意味着不同提供方的全部工具及传输相等。各轮 WSL 已清理。

## 下一步

新付费对照继续关闭。先把已验证的 V2 配置与发送前核验接入共同宿主，预登记一次限额的真实原生压缩准入，以实际压缩事件、opaque 项类型和完整用量确认真正完成，不能靠路由或触发项冒充完成。通过后才准备既定任务的同条件长程 B′/C；大结果新增臂仍遵守已有暴露检查，不重跑没有触发条件的旧组。
