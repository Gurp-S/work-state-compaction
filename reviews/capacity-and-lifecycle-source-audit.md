# 容量入口与恢复生命周期：当前源码核对

本轮静态阅读当前 `wsc/`、`python/` 相关文件，并提取既有日志字段；没有网络计数请求、模型、会话启动、测试或实验。提取数据见 `capacity-lifecycle-audit/observations.json`，19 个阶段、30 条通知均保留并绑定原 thread/turn；原始文件哈希随数据保存。

## 1. 修正：原生窗口上限并非完全不可观察

全部 30 条 `thread/tokenUsage/updated` 通知的 `params.tokenUsage.modelContextWindow` 都是 **258400**。这是对应历史线程/回合的服务端报告值，不是从模型名字推算的，也没有读取或解密内部压缩状态。

此前“宿主容量接口仍缺”的准确含义应收窄为：**独立 WSC 尚未接上下一次完整请求的可靠容量准入**，而不是完全拿不到窗口字段。

|需要的量|当前能观察什么|不能由此证明什么|
|---|---|---|
|窗口上限|请求后通知给出 modelContextWindow=258400|当前其他模型/路由/线程也同值；请求前已经有有效容量回执|
|输入 Token|普通回合有 last.inputTokens；total.inputTokens 随响应累加|累计调用量等于某时刻 Context 占用；上一输入等于下一完整请求输入|
|原生压缩输入|通知中的 last.inputTokens 为 0，但计费回执有非零输入|压缩输入为空、原生压缩免费或内部摘要占 0 Token|
|输出预留|当前 native_application_session 的 turn/start 没有从真实输出上限构建预留准入|模型最后输出较短就证明此前容量足够；研究 Token 总额就是输出预留|
|下一完整请求|独立 adapter 只声明 token_capacity=host_checked；本地预算仍按字节|已经验证宿主隐藏提示词、工具 schema、历史及输出预留共同装得下|

原生 B 三次 B1 的计费输入均为 58212，而通知 last.inputTokens 均为 0；B2 的计费输入为 18435、18341、18328，通知仍为 0。两种字段语义不同，不能替换或择低使用。此前压缩器原始计费表不变。

窗口通知也不能直接成为 C2 接收线程的预发证明：selector 与 receiver 的运行配置和上下文不同；已导入但尚未请求的 receiver 没有自己的这次请求用量。窗口值即使可复用，输入占用及输出预留仍缺。

## 2. XEYO 主链路已有可参考的计量接口

这部分是当前源码事实，未经本轮执行验证，不能当作独立 WSC 或历史 B/C 已有能力：

- `python/memory/wsc_request_timing.py` 对实际组装的 messages/tools 做计量，读取 `context_output_limit`/`context_output_limit_measure`，最终检查 input+output reserve 是否超过声明容量；普通 prepare/prepare_counted 具有明确入口。
- `python/model/context_capacity.py` 可按连接和精确供应商模型行获取窗口；它面向特定客户端，不能推成原生 Codex 的统一预发接口。
- `python/memory/wsc_timing.py::request_measure` 可使用客户端计数接口，否则按归一化完整请求的 UTF-8/4 估算。估算不等于提供方回执；声明窗口已知也不使估算变成精确值。
- Anthropic 有 `predict_context_tokens` 的远程预测接口；DeepSeek 的指定官方模型使用固定参考 tokenizer 估算；普通 OpenAICompat 的 `context_token_measure` 可返回 None。它们不能冒充原生 Codex tokenizer，也不能在本轮调用计数服务。
- `python/engine/query_loop.py` 在投影和工具 schema 组装后调用这些接口，可参考“最后组装面准入”的职责位置，而不是把历史存储大小当 Context。

独立 `wsc/` 保持标准库组件与宿主端口边界。可以参考这些契约，不直接导入整套 engine/model，也不把主链路的 80%/85% 策略无依据复制到原生对照方案。

## 3. 生命周期已有宿主骨架，无需另造状态机

`NativeApplicationSession.execute_stage` 在执行前检查 server、opened、closed；`close` 标记 session 已关闭并清理拥有的进程。回调分派使用该 session 的真实 thread ID 和当前 turn ID。现有短选材回合已经依赖这一骨架。

因此，“handler 没有 close 方法”本身不证明当前执行路径在关闭后仍会服务请求。不能为了补一个方法就新增第二套完整生命周期状态机。

但普通任务还没有接通以下组合：

1. receiver 创建时注册 SOURCE_TOOL，而不是只给 selector 注册。
2. 普通任务 execute_stage 传入绑定该 session 的 handler，不能从请求参数自行决定预期 owner。
3. 同一恢复范围跨回合共享 reader 的累计计数；换范围显式绑定，不让旧缓存回执换义。handler 的 seen 现按 call_id 缓存并含 turn 指纹，跨回合 ID 作用域和重放规则需明确，不能假定单回合行为已经覆盖长期任务。
4. session 结束后不从旁路直接调用遗留 handler；引用和审计数据的持有方式由宿主负责，不把已关闭 actor 标为可恢复。

这些是接入缺口，不是已经复现的当前越权缺陷。单独补注册或新建包装器都不能证明已完成长期端口。继续复用已有 session 生命周期、精确读/查找和正常工具配置；不新增恢复模型或语义选择逻辑。

## 4. 当前交付与未交付

已核实：窗口字段可观察；已有按实际请求计量和输出预留的参考接口；原生 session 具备关闭/分派边界。已报告的历史耗时、计费和正确率不变。

未交付：原生下一请求的完整预发计量与可信输出预留、普通 receiver 的恢复工具注册/分派、跨回合恢复范围和资源归属、跳过 C2 后的任务正确率及总收益。`continuation_inspection` 仍 executable=false，不能把窗口字段回填进去就授权执行。

后续只整理现有候选与目标的源码/证据缺口，停止新增未验证机制。实验继续禁止；所有缺失值保持 unknown，不用字节比例、上一回合用量或其他提供方计数器补出确定结果。长期目标仍未完成。

离线字段提取：`py -3.11 -B -X utf8 wsc/validation/report_existing_capacity_observations.py --out <新的输出目录>`。只读固定历史记录，不查询实时宿主或计数服务。
