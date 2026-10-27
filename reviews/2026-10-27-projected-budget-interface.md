# 预算接口复审：修正投影计量，拒绝无依据删除读取

本轮 0 模型调用。确认并通过可选旁路修复了资源事实错误：预算描述按完整记录计算，而实际 prepared view 在 `native_source_refs_v1` 下对非消息 payload 存引用；此外原空视图计量缺少 source_projection 字段。没有证据证明它导致上一轮 85 秒的模型选材，不把这个正确性修复包装成提速。

## 复现与根因

原 `selection_facts.describe` 和 `view_budget.minimum_view_bytes/admit_generation` 的计量对象是未投影视图，实验 frontier 却用这些值描述 `core.prepare(..., source_projection=MODE)`。前者在投影前计算，后者在投影后最终执行预算检查，契约对象不一致。span 前端还会把 source_ids 说明覆盖成“完整 payload”，进一步抹掉存储投影区别。

结构规则：预算必须对准最终存储表示；跨度前端不能改变存储表示的描述。引用投影不代表渲染时免费，适配器水合后的体积仍需独立检查。语义选择、权限、哈希、CAS、发布状态机和宿主交付规则都不变。

|确定性复现|旧计量|新计量|真实 prepare|
|---|---:|---:|---:|
|普通观察记录，200000 字符 payload|200148 B|143 B|143 B|
|普通控制消息构成的空视图|190 B|234 B|234 B|
|大型显式控制观察构成的必留视图|200338 B|377 B|377 B|

第三例预算设为 1000 B，旧预检报 mandatory_view_byte_budget_exhausted，实际投影 prepare 成功；新预检也正确通过。另验证真实空视图预算减一时，新预检和 prepare 均拒绝。opaque 必留源和未知投影仍拒绝，必留判定仍仅按角色/显式 control，未加入关键词或语义规则。

真实晚位 643 来源案例全是 message，其来源行体积不会因 payload 引用减少；空视图 1526→1570 B，差 44 B 投影标记。故本问题不能解释这个案例的巨大 Token 或耗时差异。

## 实现边界

新独立 `projected_selection_facts.py` 按现有投影函数计算真实记录字节和最小控制视图，复用原控制判定，不对模型重要性作判断。`frontier(..., projection_facts=True)` 才启用新事实与投影预检；默认保持原描述和预检。新 schema 显式标记 source_projection，span 前端仅保留该契约并补充 span 事实。

核心 prepare 和 adapter 不变，新预检不代替最终硬检查；public_text 仍在投影记录内，不把其大小冒作 payload 引用大小。该事实描述只适用于已注册的 at-rest 投影，不能用它估算渲染模型输入、外部存储、费用或恢复成本。此旁路尚未接入默认模型实验，不宣称收益或任意任务正确率保证。

## 重复验证诊断

复审上一轮真实 WSCSource trace，find(build270) 的 s540 片段范围 [0,186)，read(s540) 返回 [0,227)，增加 41 个字符，且有 complete=true 和 full_text_sha256。后一次不是相同信息的机械重复；find 的搜索完成状态也不能冒充整个来源正文完整。

因此不能为了减少调用由引擎删除这个 read，也不能按“已经见过 nonce”自动推断其余原文无用。这些涉及模型要依据多少信息作判断。引擎可做的只是提供真实范围、完整性和资源事实，不代替语义保留。当前工具记录没有直接证据说明模型在手工计算预算，不将不可见推理当作已查明根因，也不声称询问模型后必能得到准确因果解释。

## 验证与账目

17 项定向测试通过：实际 prepare 的空视图/记录/重复 ID 成本一致、真实预算边界、projection 保留控制与 public text、span 不覆盖描述、默认 frontier 旧 schema 不变、opaque/未知 mode 拒绝，以及既有事实与增量编译检查。未跑全项目。开发时测试路径误填、别名断言写成原 ID 导致的失败另存补记，没有修改产品行为迎合错误断言。

证据目录 `D:/agent-task-runs/wsc-projected-budget-audit-20261027-v1`：result.json 是独立真实视图 A/B，scoped-tests.xml 是最终测试，source_unchanged=true；原始 trace 和 DB 仍引用上轮外部目录，不复制大树。

```powershell
py -3.11 -B -X utf8 wsc/validation/audit_projected_budget_20261027.py --source D:/agent-task-runs/wsc-late-recovery-qualification-20261027-v1/R01/state.db --trace D:/agent-task-runs/wsc-metadata-columns-qualification-20261027-v1/candidate/source-tool-trace.json --out <全新输出目录>
```

已知零模型回放 0.084468 秒，扣 ceil1；测试/导入/维护未完整计时仍 unknown，旧花费/失败保留。最新封套在本证据目录 next-admission-envelope.json，19651795 Token/316 响应/11334 秒。v1.30 为 v1.29 的小增量。

下一步先设计并离线验证“预算事实按需查询”接口：保持原预算事实可获取，用引擎计算确定性资源范围，语义选材仍由模型负责；只有在能完整恢复原事实、权限/计量与最终 prepare 对齐且确有输入收益后，才考虑新模型资格。不重复已有三组，也不推广上一轮未提速的列式候选。
