# 宿主上下文重复进入检查点：实际证据与零推理演练

2026-10-23。本轮不修选材schema、不重跑旧C、不进行新的模型推理。发现并验证了独立于选材格式的输入边界问题，形成[候选v1.1](../../docs/WSC-HOST-CONTEXT-BOUNDARY-v1.1.md)。

## 依据

原来源：`D:/agent-task-runs/wsc-control-continuation-20261023-v1/source_task/{admission,registration,phase-outcome}.json` 及 `native-rollout-archive/source.jsonl`。

已有真实C：`D:/agent-task-runs/wsc-message-checkpoint-20261023-v1/expanded_task/admission.json`、同目录的 `rollout.jsonl`，以及该研究的 `checkpoint/package.json`。

旧准入在真实执行事实之前观测4条宿主消息：记忆/技能说明、代理工具说明、协作模式、AGENTS与环境。新宿主也提供4条。三条完全相同；第一条记忆摘要已经变化，旧文本却在新宿主之后重新导入。它可能影响指令优先关系，但没有证明这就是此前输出量或中断的原因。

`audit.py` 在未经修改的真实包上构造反事实items：保留全量原冷档及原来源标识，只把已绑定旧宿主前缀的热呈现变为历史入口。任务尾部消息和工作状态原内容逐项不变。原63836字节，候选25596字节（-59.90%）。其中纯粹完全重复的3条原记录合计9173字节；大部分减少来自不再重放31052字节的旧版宿主说明，不能混称完全相同文本去重。

回放目录 `D:/agent-task-runs/wsc-host-context-20261023-offline`。counterfactual-items.json明确不是可安装包；没有伪造package digest、HostReceipt或模型使用证据。两个负例验证前缀改变和当前user覆盖缺失时拒绝。

## 原生传输演练

脚本只允许 initialize、thread/start、thread/inject_items 及初始化通知。模型推理、压缩、命令执行RPC均未开放。

| 登记 | 结果 | 实际意义 |
| --- | --- | --- |
| `D:/agent-task-runs/wsc-host-context-20261023-transport` | 只读宿主user环境权限文字与历史不同，覆盖校验拒绝；会话9417退出0 | 原型没有无条件抹去不同的用户角色控制；不是模型失败 |
| `D:/agent-task-runs/wsc-host-context-20261023-transport-matched` | 使用原实验workspace-write配置，user覆盖通过，候选实际导入并逐项归档匹配；会话38078退出0 | 原生导入可接受这种投影；未执行任务或证明语义收益 |

两次均0模型响应、没有任务命令、工作区不变。第一次脚本旧版存于 `versions/20261023-host-transport-readonly-v1.zip`，其原SHA-256 `cf6bfd55c569e168348f53126e55bb26b1ae31f20cbdf1d8ebf729111199cba4` 与该登记相符。第二次独立登记明确sandbox参数，当前脚本与其pins一致。两次结果都保留，未重启任一运行。

## 当前决定

把宿主上下文与任务状态的边界作为下一实现前提，依据真实启动回执处理，不按角色名称或相似文字猜测。此次没有改活动运行代码、原生配置或默认路径；122源码仍逐项匹配 message-checkpoint 回执。

同时复查了10响应上限：旧登记和实际执行一致，不能把触及上限归成记账bug，也不证明扩大预算一定成功。今后长期任务预算须预先制定并由真实入口一致执行；旧中断和未知完整账单不能回填成成功。

下一步不再重复Cursor研究、旧选材schema或原opaque题；需要把这项已验证边界接入实际检查点生命周期，并在独立的新连续任务上检验模型使用和总费用。当前证据仍不足以宣布C资格、总体收益或长期目标完成。
