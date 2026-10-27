# 选择输入优化：成本下降，两个案例正确率保持

按用户要求，优化实际WSC选择模型输入，保持原文、来源、理解和恢复能力；引擎不增加关键词排名或语义删选。主要改动在独立`experiments/native_selection_wire.py`，默认旧接口保留，显式compact_wire启用。本轮新增961663 Token、21个响应；复用先前原生和旧WSC数据的部分没有重复计费。金额和历史未知项保留。

## 结果

同一“优先级与冲突”历史，三次新WSC与三次已完成的原WSC对照；原生、基线结果复用。每次均一次真实压缩检查点，不是多轮连续压缩。

| 指标 | 原WSC | 新WSC | 原生B |
| --- | --- | --- | --- |
| 正确回答 | 6/6 | 6/6 | 3/6 |
| 平均总调用Token（含选材/压缩及查询） | 219295 | 100459 | 70317 |
| WSC/B比值 | 3.12 | 1.43 | 1 |
| WSC模型阶段平均秒数 | 42.86 | 41.17 | B为20.26 |

新WSC比原WSC总调用Token减少54.2%，选材输入由约193–195k降到75.27–75.29k。三次原选材草稿先做无模型重放，结果等价；随后三次真实新输出也均保持正确。耗时下降很小、单次波动明显，不能声称同等幅度提速。

再用提前生成、未用于调整算法的“版本与验证关系”案例验证：

| 分支 | 三次合计正确 | 平均调用Token | 模型阶段平均秒数 |
| --- | --- | --- | --- |
| 未压缩 | 9/9 | 50678 | 7.89 |
| 原生B | 9/9 | 69290 | 17.11 |
| 新WSC | 9/9 | 100127 | 39.25 |

两组新WSC共6次、15道结构化问题全部正确；当前版本v5、已测版本v4与artifact-4的关系均保留，没有把旧验证升级为当前验证。第二组没有旧WSC实测，不能把首组54.2%下降直接外推成第二组的对照结果。新WSC仍比B多用约43%–45% Token、模型阶段约多21–22秒；尚未实现比原生更省、更快。

## 改动及安全边界

1. 417条来源的长路径、hash、原始身份和时间移入带SHA256的可读manifest，模型保留短来源句柄、manifest路径、hash及字段说明。原始定位符没有改写或删除，模型需要时仍可查找。实际读权限在付费调用前检验。
2. 只在类型明确的引用字段里转换长ID与短句柄；不替换自由文本、scope、版本或判断。schema不再重复枚举长来源ID。
3. 相同机械字段用共享默认值表达；字段在全部事件中原本明确存在才允许使用默认值，null/缺失/false/0不混同。
4. 逐条预算事实转成有列名的无损表格；模型仍有完整成本与必留事实，不增加“日志不重要”之类引擎决策。

源顺序、角色、已知时间、原文、全部候选span、理解和CAS字段均保留。必留user/system/developer/control规则未改，未加摘要提示词，原生B的算法与运行机制未改。

原三份request+schema各434966规范字节，新约168747字节，减少61.2%；每份仍有417来源/417候选span。无模型检查证明完整还原后与原offered严格相等，旧草稿编译出的Selection也相等。新schema只是约束引用形式，不提供标准答案或测试问题。两个真实数据目录的compact-wire-audit.json验证完整还原、候选覆盖、无oracle字段、账目闭合和owned进程清理。

恢复元数据旁置会增加持久化与潜在恢复I/O，未宣称免费；本次所有新来源的原文都在frontier，尚未证明多轮之后选择模型会主动正确查manifest。主机hash与一次可访问性检查也不是模型每次读取的原子完整性证明。详见[引擎与模型边界](../../docs/wsc-engine-model-semantic-boundary.md)。

## 接入与凭据

- API：`generate(..., short_span_handles=True, compact_wire=True)`。
- 黑盒CLI：`blackbox_group_runner.py --execute --compact-wire ...`；复用模式`blackbox_group_resume.py --execute --compact-wire --compare-completed ... --parent-envelope 最新封套 ...`。
- 既有真实worker增加显式`conditions.compact_selection_wire=true`入口，配合`short_span_handles=true`。默认旧行为保留，未重启已退休的长程实验。
- 定向检查：21通过、6子用例通过，覆盖投影、篡改拒绝、字段类型、引用、旧接口、worker、生成回执和报告成本未知语义；不是全项目验收。
- [同历史新旧WSC比较JSON](D:/agent-task-runs/wsc-compact-wire-quality-20261027-v1/variant-comparison.json)
- [第一组完整报告](D:/agent-task-runs/wsc-compact-wire-quality-20261027-v1/report.md)
- [版本关系组完整报告](D:/agent-task-runs/wsc-compact-version-group-20261027-v1/report.md)
- 无模型原始重放：`D:/agent-task-runs/wsc-selection-wire-profile-20261027-v2/result.json`；早期失败夹具v1保留。

最新预算从version-group-v1/next-admission-envelope.json续接：27471795 Token/524响应/12453秒。已补扣本次独立准入12.953秒（ceil13），两轮有模型运行74.282/118.938秒计入各自封套；代码维护/未仪表化检查不假装为零，历史unknown不重置。

## 下一步

保留显式旁路和旧输入回退，先验证第二次压缩时旧正文不再直接提供的冷恢复场景，检查manifest实际发现、恢复I/O、成本与事实正确率；再做多轮3次配对。暂不继续压缩正文或引擎判定语义相关性。当前证明的是范围明确的输入和Token收益、两个案例未观察到正确率损失，不能保证任意任务的最终正确率，也未证明达到全局最小输入。
