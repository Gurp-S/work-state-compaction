# 原生阶段内自动压缩：真实触发、正常继续；工具访问尚缺跨界证据

2026-10-26。继上一轮零模型配置读取后，本轮只验证运行能力，没有业务开发、正式B/C或WSC语义收益试验。原生B、默认宿主与用户配置文件不改。

## 当前证据确立的能力

`D:/agent-task-runs/native-auto-compaction-20261026-v4`，原CLI/model/effort，只在独立服务启动参数设32000阈值。它是降低协议成本的fixture阈值，不是把未来应用候选96000改为32000。

同一个thread/turn中：第一响应调用exec启动持久PowerShell进程并轮询；随后原生内部产生compacted；压缩后第三响应正常给最终JSON。没有外部活动compact/inject，没有中断或新受体安装。account_turn验证append-only、身份、累计计数、compactor对应latest_token_usage_record、task_complete和末尾计数均通过。

| 项目 | 实际已知值 |
| --- | --- |
| 响应 | 3 |
| 总token | 88803 |
| 原生压缩响应 | 48120（输入47800，输出320） |
| 两个普通响应 | 20491 + 20192 |
| 自有后台PID | 25980 |
| 压缩前后进程观察 | 同PID均在Job实时成员中 |
| 清理 | Job成员为空，fixture hash不变 |

这次压缩支出占本协议多数，不能当作经济收益。本轮完整用量只指本试验，不修复旧研究未知。

## 为什么工具续接还没验收通过

模型把启动和write_stdin轮询放在同一外层exec里。实际源码顺序只有一个call及对应output，随后才是compacted；压缩后没有新工具调用。因此压缩后OS进程存活已证，压缩后通过原native session_id访问成功仍未证。

最终模型JSON声明state_survived=true、session_id=52317、pid=25980。它基于压缩前轮询，不能作为跨压缩工具访问证据。独立审核明确post_compaction_native_tool_access_proven=false，不把它升级成C资格通过。

完整来源中的外层output是内容块列表，input_text正文合计52323字节，不能用PowerShell把列表强转字符串的结果衡量。streamed command output合计12040字节与持久内容信封不同，也不能仅比较长度断言缺失或送达成功。

## 所有尝试与修正均保留

- v1：首轮遗漏原生工具环境预检。py -3.11在工具环境报告No installed Python found；进程未启动、无压缩。2响应/46767 tokens，普通会计完整。历史记录保留，不追认成功。
- v2：零模型预检被Windows sandbox拒绝自定义outputBytesCap；未发turn/start、未预留模型预算。
- v3：零模型绝对Python路径预检被CreateProcessAsUserW错误5拒绝；未发turn/start、未预留模型预算。
- v4：PowerShell实际脚本ProbeOnly在相同readOnly策略下预检成功后才预留并调用模型，获得本轮真实自动压缩证据。没有放松执行权限或修改私有路径规则。

两次实际模型试验累计135570 tokens/5响应；两次启动前失败0模型。最终next-admission-envelope在v4为87491638 tokens/1740响应/19239秒，沿旧累计记录扣减，不是现金余额或未知历史费用上界。所有服务和自有后台进程已关闭。

v4的result.json含未赋值更新的两个false初始标志，是控制器记录缺陷，不是测量结论；该冻结记录不改写，controller.py运行快照保留。当前控制器删除未测量的session标志，并从实际closed rows计算compaction_observed；没有为这个记录修正重跑模型。

独立审核audit.json早期错误使用str(list)计字节且写了不正确的one-byte描述，保留；audit-v2.json从真实内容块input_text计量，取代其输出描述，核心压缩/用量/访问边界结论不变。当前结论以绑定原记录hash的audit-v2为准。

## 下一步

把压缩后的原session访问作为一个独立请求，在同一仍存活服务内执行，确保不可能与首次启动合并。它需要新的单次小额登记，沿累计上限，不重放旧目录或仅凭最终声明判断。门槛通过后才登记原S2/S3的C资格；不直接再开6M。

后续仍需区分原生更早压缩与WSC语义管理的收益。正式B不改；五任务各三轮、WSC长期正确续接和总体成本优势均未证明。
