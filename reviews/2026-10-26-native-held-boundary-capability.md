# 原生动态工具等待点：存在候选边界，直接活动压缩不是安全续接

2026-10-26。上一轮真实C/S3失败和输入增长属有效进展，本轮核对阶段内控制接口。未重跑开发，未改默认NativeApplicationSession、原生B、应用源码或旧失败账本。

## 静态审查

同一已绑定CLI的experimental schema声明动态工具和item/tool/call，允许thread/inject_items与thread/compact/start请求。现有NativeApplicationSession的普通execute_stage会对任何未登记server callback报错，因此不能把该API直接加入旧循环。NativeRPC可将带id的方法请求保存在事件队列，且可回送响应；这只是传输能力。

仓库已有native_host_checkpoint与native_successor_checkpoint，能复用宿主前缀/冷祖先校验，不应再造同类模块。但其Pending导入记录明确installation_receipt=None，不是原子安装证明。活动回合受控结束与新受体确认仍需新契约，不能放宽旧“完整普通回合”判定来吞掉中断。

## 唯一一次有模型协议实验

登记native-boundary-capability-20261026-v3，上限120000 total tokens/4响应/120秒，无推理重试。任务只调用无副作用的checkpoint_ready并等结果；只读空目录，没有应用开发。两次早先bootstrap准备失败在v1/v2保留：尚未发turn/start、预算臂未启动、0已知推理消耗。新线程尚未保证rollout文件落盘，复用执行事实注入后再封存前缀才继续；单纯加等待无效。另一次语法修正发生在脚本执行之前，没有创建模型会话。

实际观察：

1. 动态回调到达且结果被宿主暂扣；两秒观察窗内有1条匹配threadId/turnId的响应回执。22497已知tokens（输入22449、输出48），说明本例能观察“推理已有回执，工具仍等待”。它不自动证明通用工具图或外部副作用已排空。
2. 事件流有匹配callId的dynamicToolCall inProgress；同一时点thread/read只列user/reasoning，不能据此把thread/read当完整活动工具清单。
3. thread/inject_items返回接受，但关闭后完整日志没有boundary_probe_marker。该次请求的持久化及下一模型实际接收均未证实；不能将RPC {}当交付回执，也不能仅据未见标记就断言所有活动注入都丢失。
4. thread/compact/start返回接受，原turn随后turn_aborted(reason=replaced)，等待中的外层exec记aborted by user；新压缩turn开始。不是原回合原地继续。
5. 探针控制器只等原turn终止便关闭服务，新压缩turn在22ms后被中断，没有compacted完成记录或对应压缩用量回执。这是控制器不足，不能拿它证明压缩失败或原生接口绝对不支持。原生返回接受也不构成安全WSC检查点。

实际7.156秒、1条已知响应/22497 tokens，完整用量未知，已冻结；原回合不是正常交付。全部所属进程清理。120000中未用97503 tokens与3响应继续保留，不当作费用估计或未知上界。后续准入87672516 tokens/1747响应/19327秒，旧账本与已绑定CLI哈希核对未变。不会重跑同一探针补绿。

## 本轮证据边界

确认的是：动态等待回调可观察、匹配回执可在等待点出现、活动压缩会在本例替换原回合。尚未证明：持久化注入、下一模型见过标记、完整工具排空、稳定交接后续接、压缩完成、完整协议用量、任务经济收益。原有完整未知保持，原生B未改。

## 下一步

采用[受控检查点v0.2设计](2026-10-26-controlled-checkpoint-design-v0.2.md)继续审查和旁路：显式记录原回合结束、新状态提交与新受体导入，不再尝试把compact/start包装成同turn透明续接。先验证排空、来源封存、失败保留及独立账本；通过再考虑小额交接能力验证。此后才回真实长期任务及原五任务各三轮对照，不再追加同类6M开发。
