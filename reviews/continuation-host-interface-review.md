# 续接呈现与恢复接口：静态审查

范围：当前源码与目标原文静态核对。未运行模型、测试、跑分、故障注入或方案实验；没有修改默认行为或 Codex 原生 B。

## 方向修正：正常续接不等于再次发布

目标原文要求在合理成本下持续正确工作，并明确区分 Preserve、Discover、Retrieve、Use。不能为了绕过一次选材，先引入新的视图转换和发布链。当前代码已有两条不同路径：

|路径|当前接口事实|本次结论|
|---|---|---|
|继续已有接收线程|LateCell.run 已将完整 delta 追加给 first_receiver；append_history 验证已有前缀不变及追加值|已有旧帧在前、新事件在后的构造路径，不需要为了普通续接再开发渲染器|
|重建、发布一个新检查点|publication.stage 使用 view binding.cut 渲染；基础 adapter 先消息、后旧 working_state、最后 cut 之后的原始尾部|简单将新来源合进旧 body 并把 cut 改成新边界，会改变原有呈现顺序；这条路径仍需要单独设计与验证|

此前“有序渲染尚未实现”只适用于重建新检查点，不能泛化为继续原线程的必要阻碍。无需给正常续接增加发布、generation 或理解修订操作。历史选择仍是历史选择，新原文中的变更由任务模型理解，引擎不替它判断旧 clue 是否语义过期。

这只证明代码存在上述构造接口；不证明当前保留的任何历史线程仍存活，也不证明续接一定成功。没有发起新进程或尝试恢复旧会话。

## 恢复工具缺口：注册和分派缺一不可

当前 LateCell.new 仅在 selector-* 上调用 fresh(dynamic_tools=[SOURCE_TOOL])。其他 receiver/probe 走 Cell.new 的普通 fork；Cell.probe 经 self.phase 执行，未传 source tool handler。

现有通用接口已经具备基础部件：

1. native_blackbox_sessions.fresh 可在 thread/start 注册动态工具，但不能由此推断已经存在的线程或其 fork 可以事后添加工具。当前 fork 包装没有传 dynamicTools。
2. NativeApplicationSession.execute_stage 接受 tool_handler；遇到 item/tool/call 才会分派给它。只注册工具而未传 handler，会落入 application_unregistered_callback；只传 handler 而未注册，也不构成模型可调用的工具。
3. SourceToolHandler/BudgetResultSourceToolHandler 和 SnapshotLiteralAccess 已实现确切读取/查找、来源绑定、权限、返回预算和 trace。可以复用这些机制，不需要新增语义检索或额外裁判模型。
4. 当前普通任务仍有原生工具和冷索引路径。缺的是专用恢复接口的同等交付证据，不能声称普通任务完全不能恢复。

如果以后实施，正常接收器从创建时即需拥有恢复工具，并在普通任务回合分派同一个已注册工具。任务模型自行发现缺口并查询；引擎不预读目标 nonce、不把 oracle、测试问题或预期答案放进工具描述。中性工具信息只说明精确访问范围、快照身份、预算和结果覆盖。

快照绑定的历史工具不能冒充当前状态工具。旧快照恢复早期来源时仍以旧 cut/digest 表示；若后续需要检索新增来源，需明确新的快照绑定与权限检查，不能静默让同一别名跨快照换义。工具实际调用、恢复输出和任务消耗必须计入整个续接成本，不能只报省掉的选材调用。

## 宿主安装证据不能混用

RecoveryCell.publish 的实际动作是 stage/package/check_evidence、import_receiver、verify_paths，然后 core.discard(op)。这不是 core.install/confirm 路径，不会据此得到已确认的 head/cursor/generation。

因此新 continuation_inspection 返回 previous_installed_head_matches=false，不足以单独认定这类研究接收器的材料导入失败；也不能把导入证明当作生产宿主的原子安装回执。研究接收器要核对 native-import/有效历史与追加证明；生产重启恢复要核对正式安装回执。两种证据分开，原状态机不改。

## 当前取舍

先保留“已有有效旧帧＋完整原始尾部”的正常续接方向，不另建渲染器，不启用新策略。新检查模块仍只是读取时刻的事实报告，不能授权继续、证明恢复可用或宣称可跳过 C2。

当上下文不足、调用方明确请求重选，或必须缩减/改写信息时，语义选择仍由模型作出；完整性、权限、未决发布等失败先处理机械状态。容量判定仍缺宿主实际 Token/输出预留，不能用几 KB 的字节数替代。

未来若接入，将改变普通任务的工具配置，因此只能作为独立 C 系统候选，不能套用旧协议的 6/6 或继续称为严格算法级同资源比较。B 保持原生；旧失败和用量保留。用户当前禁止实验，故本轮没有开启该候选，也没有新的省时、正确率或成本结果。

下一步只做正常任务恢复接口的最小接入契约与安全边界审查，复用已有读/查找组件；未经验证不接入默认链路，不继续叠加新压缩表示或发布机制。
